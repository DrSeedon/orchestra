"""Loader пайплайнов: схема манифеста (pydantic) + резолв ролей/промптов/спавна.

Источник истины о ролях — единый манифест ``pipelines/<name>/pipeline.yaml``
(вместо frontmatter+glob апстрима). При активном пайплайне ВСЁ берётся только из
``pipelines/<name>/`` — ``app/prompts/`` игнорируется (полная изоляция промптов).

Наследование defaults→roles выполняется на РЕЗОЛВЕ (:func:`resolve_role`), не на
загрузке: ``load_pipeline`` валидирует и кэширует сырой манифест, ``resolve_role``
сливает роль с defaults в :class:`ResolvedRole`.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ALIASES, MODELS

logger = logging.getLogger(__name__)

# Корень с пайплайнами: <repo>/pipelines/. default и tasks-pm — оба в гите.
PIPELINES_DIR = Path(__file__).parent.parent / "pipelines"
DEFAULT_PIPELINE = "default"

# Спецзначение "all" для skills/mcp_servers (строка) vs явный список.
AllOrList = Union[Literal["all"], list[str]]

Kind = Literal["orchestrator", "worker"]
ValidationMode = Literal["fail-closed", "fail-open"]
BranchStrategy = Literal["parent", "main"]


def _model_is_known(model: str) -> bool:
    """Модель валидна, если резолвится в любую доступную модель.

    In enterprise mode with limited models, resolve_model falls back to
    first available — so any alias is valid as long as MODELS is non-empty.
    """
    if model.lower() in ALIASES or model in MODELS:
        return True
    from app.models import resolve_model
    resolved = resolve_model(model)
    return resolved in MODELS


def _is_safe_rel(p: str) -> bool:
    """True если ``p`` — безопасный относительный путь (без абсолютного и '..').

    Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
    """
    from pathlib import PurePosixPath
    if not p or p.startswith("/"):
        return False
    return ".." not in PurePosixPath(p).parts


# ── Pydantic-схема манифеста ───────────────────────────────────────────────

class Symlink(BaseModel):
    """Симлинк в worktree: source (относительно repo) → target (внутри worktree)."""
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str

    @field_validator("source", "target")
    @classmethod
    def _safe_rel(cls, v: str) -> str:
        # B2: source резолвится от repo, target — внутри worktree; ни один не должен
        # выходить за свою границу (abs или '..'). Та же защита, что у docs_dir.
        if not _is_safe_rel(v):
            raise ValueError(f"unsafe symlink path '{v}' (abs или '..')")
        return v


class Worktree(BaseModel):
    """Настройка worktree роли: симлинки и копируемые файлы (= PROJECT_FILES)."""
    model_config = ConfigDict(extra="forbid")
    symlinks: list[Symlink] = Field(default_factory=list)
    copies: list[str] = Field(default_factory=list)

    @field_validator("copies")
    @classmethod
    def _safe_copies(cls, v: list[str]) -> list[str]:
        # B2: copies резолвятся как repo/<name> и пишутся как wt_path/<name>;
        # abs или '..' позволили бы чтение/запись вне repo/worktree. Та же защита,
        # что у symlinks (симметрично — иначе copies остаётся дырой).
        for name in v:
            if not _is_safe_rel(name):
                raise ValueError(f"unsafe copy path '{name}' (abs или '..')")
        return v


class DocsDir(BaseModel):
    """Скаффолдинг doc-папки роли в docs_work/.

    ``requires='feature'`` → плейсхолдер ``{feature}`` обязателен в path; если фича
    не передана при спавне — скаффолд пропускается.
    """
    model_config = ConfigDict(extra="forbid")
    path: str
    template: str | None = None
    requires: Literal["feature"] | None = None

    @field_validator("path", "template")
    @classmethod
    def _safe_rel(cls, v: str | None) -> str | None:
        # B2: путь/шаблон не должны выходить за pipelines/<name>/ (abs или '..').
        # {feature} подставляется в рантайме — containment проверяет B3.
        if v is not None and not _is_safe_rel(v):
            raise ValueError(f"unsafe docs_dir path '{v}' (abs или '..')")
        return v


class Tg(BaseModel):
    """Параметры Telegram-топика роли (emoji + шаблон topic)."""
    model_config = ConfigDict(extra="forbid")
    emoji: str = ""
    topic: str = ""


class PromptLayers(BaseModel):
    """Порядок слоёв промпта по kind. ``{role}`` подставляется на резолве.

    Пути относительны ``pipelines/<name>/prompts/``.
    """
    model_config = ConfigDict(extra="forbid")
    orchestrator: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md", "_pipeline.md"])
    worker: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md"])

    @field_validator("orchestrator", "worker")
    @classmethod
    def _safe_layers(cls, v: list[str]) -> list[str]:
        # B2: слои не должны выходить за pipelines/<name>/prompts/. Плейсхолдер
        # {role} безопасен (_is_safe_rel("roles/{role}.md") True).
        for layer in v:
            if not _is_safe_rel(layer):
                raise ValueError(f"unsafe prompt layer '{layer}' (abs или '..')")
        return v


class Defaults(BaseModel):
    """Дефолты пайплайна. Роль переопределяет: скаляр — replace, список — union."""
    model_config = ConfigDict(extra="forbid")
    model: str = "opus"
    skills: AllOrList = "all"
    mcp_servers: AllOrList = "all"
    inherit_claude_md: bool = True
    prompt_layers: PromptLayers = Field(default_factory=PromptLayers)
    worktree: Worktree = Field(default_factory=Worktree)
    base_branch_strategy: BranchStrategy = "parent"
    docs_scaffold: bool = True

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str) -> str:
        if not _model_is_known(v):
            raise ValueError(
                f"unknown model '{v}'. aliases={sorted(ALIASES)} ids={sorted(MODELS)}")
        return v


class RoleSpec(BaseModel):
    """Сырая роль из манифеста. Опциональные поля (model/skills/...) = None →
    наследуются из defaults на резолве. kind/label — обязательны для контракта.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    label: str
    order: int = 100
    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
    allow_unrouted_workers: bool = False
    # Модули — переиспользуемые блоки промпта (prompts/modules/{m}.md), инлайнятся
    # в system_prompt после слоёв роли. Пусто → ничего не добавляется.
    modules: list[str] = Field(default_factory=list)
    # Переопределения defaults (None → наследуем):
    model: str | None = None
    skills: AllOrList | None = None
    mcp_servers: AllOrList | None = None
    base_branch_strategy: BranchStrategy | None = None
    inherit_claude_md: bool | None = None
    docs_scaffold: bool | None = None
    # Роле-специфика:
    docs_dir: DocsDir | None = None
    tg: Tg | None = None
    when: str | None = None
    not_for: str | None = None
    description: str | None = None

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str | None) -> str | None:
        if v is not None and not _model_is_known(v):
            raise ValueError(f"unknown model '{v}'")
        return v

    @field_validator("modules")
    @classmethod
    def _safe_modules(cls, v: list[str]) -> list[str]:
        # B2: имя модуля → prompts/modules/{m}.md; не должно выходить за изоляцию
        # (abs или '..'). Та же защита, что у docs_dir/prompt_layers.
        for m in v:
            if not _is_safe_rel(m):
                raise ValueError(f"unsafe module name '{m}' (abs или '..')")
        return v


class PipelineConfig(BaseModel):
    """Сырой манифест пайплайна (роли с None-полями, до наследования)."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    validation: ValidationMode = "fail-closed"
    defaults: Defaults = Field(default_factory=Defaults)
    roles: dict[str, RoleSpec]

    @model_validator(mode="after")
    def _check_graph(self) -> "PipelineConfig":
        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
        known = set(self.roles)
        for rname, r in self.roles.items():
            for child in r.can_spawn:
                if child != "*" and child not in known:
                    raise ValueError(
                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
                        f"unknown role '{child}'. known={sorted(known)}")
        return self


class ResolvedRole(BaseModel):
    """RoleSpec после слияния defaults→role. Все поля заполнены, None нет.

    То, что отдаётся наружу (manager/workspace/tg).
    """
    model_config = ConfigDict(extra="forbid")
    name: str
    pipeline: str
    kind: Kind
    label: str
    order: int
    can_spawn: list[str]
    allow_unrouted_workers: bool
    modules: list[str]
    model: str
    skills: AllOrList
    mcp_servers: AllOrList
    base_branch_strategy: BranchStrategy
    inherit_claude_md: bool
    docs_scaffold: bool
    docs_dir: DocsDir | None
    tg: Tg | None
    when: str | None
    not_for: str | None
    description: str | None
    prompt_layers: list[str]  # выбранный (orchestrator|worker) список с подставленным {role}

    @property
    def is_orchestrator(self) -> bool:
        return self.kind == "orchestrator"


# ── Загрузка манифеста ─────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def load_pipeline(name: str) -> PipelineConfig:
    """Прочитать ``pipelines/<name>/pipeline.yaml``, провалидировать, кэшировать.

    :raises FileNotFoundError: если папки/файла нет.
    :raises pydantic.ValidationError: если схема битая (extra-поле, неверный kind/model).
    :raises ValueError: если ``name`` в файле не совпадает с именем папки, либо битый
        граф can_spawn.
    """
    path = PIPELINES_DIR / name / "pipeline.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"pipeline '{name}' not found at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
    if cfg.name != name:
        raise ValueError(f"pipeline name '{cfg.name}' != dir '{name}'")
    return cfg


def get_worktree_config(pipeline_name: str) -> Worktree:
    """Вернуть worktree-конфиг пайплайна (``defaults.worktree``).

    Это pipeline-level настройка (симлинки + copies), общая для всех ролей —
    в :class:`ResolvedRole` её нет.

    :raises FileNotFoundError: если манифест отсутствует (пробрасываем, чтобы
        вызывающий в manager сделал fallback на upstream-поведение).
    """
    return load_pipeline(pipeline_name).defaults.worktree


def list_pipelines() -> list[dict]:
    """Скан ``pipelines/`` (включая gitignored). Для UI-дропдауна.

    Возвращает ``[{name, description, roles:[...], valid:bool, error:str|None}]``.
    Битый манифест НЕ роняет список — помечается ``valid=False`` с текстом ошибки.
    """
    out: list[dict] = []
    if not PIPELINES_DIR.is_dir():
        return out
    for d in sorted(PIPELINES_DIR.iterdir()):
        if not d.is_dir() or not (d / "pipeline.yaml").is_file():
            continue
        try:
            cfg = load_pipeline(d.name)
            out.append({"name": cfg.name, "description": cfg.description,
                        "roles": sorted(cfg.roles), "valid": True, "error": None})
        except Exception as e:  # noqa: BLE001 — намеренно глотаем, чтобы список не падал
            out.append({"name": d.name, "description": "", "roles": [],
                        "valid": False, "error": str(e)})
    return out


# ── Резолв роли: наследование defaults→roles ──────────────────────────────

def _merge_scalar(default_val, role_val):
    """Скаляр: роль переопределяет, если задала (не None); иначе наследуем."""
    return default_val if role_val is None else role_val


def _merge_list(default_val: AllOrList, role_val: AllOrList | None) -> AllOrList:
    """Список: union(defaults ∪ role). ``"all"`` в любом из двух → ``"all"`` (поглощает)."""
    if role_val is None:
        return default_val
    if default_val == "all" or role_val == "all":
        return "all"
    return sorted(set(default_val) | set(role_val))


def resolve_role(pipeline: PipelineConfig, role: str) -> ResolvedRole:
    """Слить роль с defaults в :class:`ResolvedRole` (все поля заполнены).

    Скаляр — роль переопределяет если задан, иначе defaults. Список (skills/
    mcp_servers) — union с поглощением ``"all"``. ``prompt_layers`` — по kind роли
    с подстановкой ``{role}``.

    :raises KeyError: если ``role`` нет в ``pipeline.roles`` (ловит вызывающий).
    """
    spec = pipeline.roles[role]
    d = pipeline.defaults
    layers_tmpl = (d.prompt_layers.orchestrator if spec.kind == "orchestrator"
                   else d.prompt_layers.worker)
    return ResolvedRole(
        name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
        order=spec.order, can_spawn=spec.can_spawn,
        allow_unrouted_workers=spec.allow_unrouted_workers,
        modules=spec.modules,
        model=_merge_scalar(d.model, spec.model),
        skills=_merge_list(d.skills, spec.skills),
        mcp_servers=_merge_list(d.mcp_servers, spec.mcp_servers),
        base_branch_strategy=_merge_scalar(d.base_branch_strategy, spec.base_branch_strategy),
        inherit_claude_md=_merge_scalar(d.inherit_claude_md, spec.inherit_claude_md),
        docs_scaffold=_merge_scalar(d.docs_scaffold, spec.docs_scaffold),
        docs_dir=spec.docs_dir, tg=spec.tg,
        when=spec.when, not_for=spec.not_for, description=spec.description,
        prompt_layers=[p.replace("{role}", role) for p in layers_tmpl],
    )


def get_role(pipeline_name: str, role: str) -> ResolvedRole | None:
    """Загрузить пайплайн и резолвнуть роль. None, если роли нет в манифесте."""
    cfg = load_pipeline(pipeline_name)
    return resolve_role(cfg, role) if role in cfg.roles else None


def known_roles(pipeline_name: str) -> list[str]:
    """Отсортированный список имён ролей пайплайна."""
    return sorted(load_pipeline(pipeline_name).roles)


# ── Резолв путей промпта (полная изоляция: только pipelines/<name>/prompts/) ─

def prompt_path(pipeline_name: str, rel: str) -> Path:
    """Путь к слою промпта. ВСЕГДА внутри ``pipelines/<name>/prompts/``.

    ``rel`` — элемент prompt_layers (``base.md``, ``roles/coder.md``, ``_pipeline.md``).
    ``app/prompts/`` НЕ участвует — гарантия изоляции.
    """
    return PIPELINES_DIR / pipeline_name / "prompts" / rel


def template_path(pipeline_name: str, template: str) -> Path:
    """Путь к шаблону doc-папки внутри ``pipelines/<name>/templates/``."""
    return PIPELINES_DIR / pipeline_name / "templates" / template


def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
    """Собрать system_prompt из prompt_layers резолвнутой роли.

    Каждый слой читается из ``pipelines/<name>/prompts/<layer>`` через
    :func:`prompt_path` (ПОЛНАЯ изоляция — ``app/prompts/`` не читается). Отсутствующий
    слой-файл пропускается. Конкатенация через ``\\n\\n``. Динамика (каталог ролей,
    блоки других оркестраторов/воркеров) добавляется вызывающим в manager — здесь
    только статика из файлов.

    После слоёв роли инлайнятся ``modules`` — переиспользуемые блоки промпта из
    ``prompts/modules/{m}.md`` (та же изоляция). Отсутствующий модуль пропускается с
    warning (роль не должна падать из-за недостающего блока).

    :raises FileNotFoundError: если манифест пайплайна отсутствует (на Этапе 3 manager
        ловит и делегирует в legacy-путь апстрима).
    """
    rr = resolve_role(load_pipeline(pipeline_name), role)
    parts: list[str] = []
    for layer in rr.prompt_layers:
        p = prompt_path(pipeline_name, layer)
        if p.is_file():
            parts.append(p.read_text())
    for m in rr.modules:
        mp = prompt_path(pipeline_name, f"modules/{m}.md")
        if mp.is_file():
            # ``.strip()`` — точное соответствие upstream ``_load_modules`` (manager.py):
            # модули инлайнятся обрезанными, разделитель между ними ровно ``\n\n``.
            # Без strip хвостовые ``\n`` в файле дают ``\n\n\n`` и расхождение с upstream.
            parts.append(mp.read_text().strip())
        else:
            logger.warning(
                "pipeline '%s' role '%s': module '%s' not found at %s — skipped",
                pipeline_name, role, m, mp)
    return "\n\n".join(parts)


# ── Активный пайплайн ──────────────────────────────────────────────────────

def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
    """Определить активный пайплайн для НОВОЙ сессии.

    1) ``parent_pipeline`` (от родителя при спавне) — главный источник: дети
       наследуют пайплайн родителя.
    2) пусто/корневой оркестратор → :data:`DEFAULT_PIPELINE`.

    Один пайплайн на дерево агентов — в середине цепочки сменить нельзя. Полная
    логика (чтение колонки sessions.pipeline) — Этап 7; здесь зафиксирована
    сигнатура и базовое поведение наследования.
    """
    if parent_pipeline:
        return parent_pipeline
    return DEFAULT_PIPELINE


# ── Валидация спавна (fail-closed / fail-open) ────────────────────────────

def validate_spawn(pipeline_name: str, parent_role: str | None, child_role: str) -> None:
    """Проверить допустимость спавна ``child_role`` родителем ``parent_role``.

    Режим из ``PipelineConfig.validation``:

    * **fail-closed** (наш дефолт) — неизвестный parent/child → ValueError.
    * **fail-open** (дух апстрима) — неизвестные роли пропускаются; но явный
      ``can_spawn``-whitelist при ИЗВЕСТНЫХ ролях действует в обоих режимах.

    Корень (parent пуст/None) — спавн от юзера/UI, всегда разрешён. Пустой
    ``child_role`` (генерик-воркер) разрешён только если ``allow_unrouted_workers``.

    :raises ValueError: при запрещённом спавне.
    :raises FileNotFoundError: если манифест отсутствует (manager ловит → fallback).
    """
    cfg = load_pipeline(pipeline_name)
    fail_closed = cfg.validation == "fail-closed"

    if not parent_role:  # корень — спавн от юзера/UI
        return
    parent = cfg.roles.get(parent_role)
    if parent is None:
        if fail_closed:
            raise ValueError(
                f"unknown parent role '{parent_role}' in pipeline '{pipeline_name}'. "
                f"known={known_roles(pipeline_name)}")
        return  # fail-open: неизвестный parent → пропуск
    if not child_role:  # генерик-воркер (роль не указана)
        if not parent.allow_unrouted_workers:
            raise ValueError(
                f"role '{parent_role}' must specify child role. "
                f"allowed: {parent.can_spawn or '(none)'}")
        return
    if child_role not in cfg.roles:
        if fail_closed:
            raise ValueError(
                f"unknown role '{child_role}' in pipeline '{pipeline_name}'. "
                f"known={known_roles(pipeline_name)}")
        return  # fail-open: неизвестный child → пропуск
    if "*" in parent.can_spawn:
        return
    if child_role not in parent.can_spawn:
        raise ValueError(
            f"role '{parent_role}' cannot spawn '{child_role}'. "
            f"allowed: {parent.can_spawn or '(none — terminal)'}")
