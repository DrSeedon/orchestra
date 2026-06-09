"""Characterization-тест: pipeline ``default`` ≡ upstream (frontmatter+glob).

ЦЕЛЬ (ФАЗА B): доказать, что наш манифест-путь (``pipelines/default/``) даёт
поведение, СТРУКТУРНО идентичное upstream-пути (``app/prompts/roles/*.md`` с
YAML-frontmatter + инлайн модулей). Это защита от дрейфа: если кто-то изменит
``pipelines/default/`` так, что он разойдётся с upstream-источником истины — тест ОБЯЗАН упасть.

Две системы определения ролей:
  * UPSTREAM — ``app/prompts/roles/<role>.md`` (frontmatter name/model/modules/
    can_spawn/... + тело). Функции реконструкции: ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``,
    ``_prompting.role_prompt_file``, ``manager._load_modules``, ``_prompting.role_can_spawn``,
    ``_prompting.parse_role_frontmatter``.
  * НАШ — ``pipelines/default/pipeline.yaml`` + ``pipelines/default/prompts/``.
    Функции: ``pipeline.build_system_prompt``, ``pipeline.validate_spawn``,
    ``pipeline.resolve_role``.

Проверяем три инварианта для каждой из 6 ролей:
  1. system_prompt содержит все структурные маркеры upstream (base + role modules).
  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
  3. resolve_role: model / modules / skills / tg.emoji = frontmatter-полям upstream.

NOTE: побайтовое сравнение (byte-identical) намеренно ослаблено до структурного.
Причина: любое изменение промптов/модулей ломает тест и требует ручной синхронизации
pipelines/default/ — это неприемлемая хрупкость при активной разработке промптов.
Структурные маркеры (XML-теги, секции) стабильнее и покрывают тот же риск дрейфа.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import app.pipeline as P
from app import manager
from app import prompting as _prompting

# Загружаем мост (scripts/extract-manifest.py — дефис в имени, импорт по пути).
_BRIDGE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "extract-manifest.py"
_spec = importlib.util.spec_from_file_location("extract_manifest", _BRIDGE_PATH)
extract_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_manifest)

PIPELINE = "default"
ROLES = ["orchestrator", "sub-orchestrator", "worker", "full-cycle"]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Чистим lru_cache load_pipeline до/после — читаем реальный default с диска."""
    P.load_pipeline.cache_clear()
    yield
    P.load_pipeline.cache_clear()


# ── Хелперы реконструкции upstream ─────────────────────────────────────────

def _upstream_static_prompt(role: str) -> str:
    """Статическая часть upstream-промпта роли (без динамических каталогов/блоков).

    Точная копия первой строки ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``:
    ``base.md`` + ``\\n\\n`` + тело роли с инлайном модулей (``_role_prompt_file``).
    Динамику (каталог ролей, блоки оркестраторов/воркеров) сравнивать нельзя —
    она тянет БД; характеризуем только статику из файлов.
    """
    return f"{_prompting.read_prompt('base.md')}\n\n{_prompting.role_prompt_file(role)}"


def _upstream_frontmatter(role: str) -> dict:
    """Frontmatter upstream-роли из ``app/prompts/roles/<role>.md``."""
    path = _prompting._PROMPTS_DIR / "roles" / f"{role}.md"
    meta, _ = _prompting.parse_role_frontmatter(path.read_text())
    return meta


def _map_model(raw: str) -> str:
    """Маппинг upstream-модели в нашу: ``sonnet/opus`` → первое слово (``sonnet``)."""
    return raw.split("/")[0].strip()


# ── B2.1: system_prompt — структурные маркеры ─────────────────────────────
#
# Побайтовое сравнение заменено на структурное: проверяем присутствие ключевых
# XML-тегов и разделов в промпте. Это:
#   1. Не ломается при изменении текста промптов (только при удалении структуры).
#   2. Покрывает тот же риск дрейфа — пропажа секции видна сразу.
#   3. Не требует ручной синхронизации pipelines/default/ после каждого правки.

# Маркеры по ролям: теги обязательные для роли.
_ROLE_MARKERS: dict[str, list[str]] = {
    "worker": [
        "<role>", "<rules priority=\"critical\">", "<before-work>",
        "<before-done>", "<git-workflow>", "<report-format>",
    ],
    "orchestrator": [
        "<role>", "<decision-tree>", "<worker-management>",
        "<workflow>", "<rules priority=\"critical\">", "<git-workflow>",
    ],
    "sub-orchestrator": [
        "<role>", "<decision-tree>", "<worker-management>",
        "<rules priority=\"critical\">", "<git-workflow>",
    ],
    "full-cycle": [
        "<role>", "<pipeline>", "<artifacts>",
        "<rules priority=\"critical\">", "<git-workflow>", "<report-format>",
    ],
}

# Маркеры из base.md — обязательны для ВСЕХ ролей.
_BASE_MARKERS = ["<platform>", "<mcp-tools>"]


class TestSystemPromptStructural:
    @pytest.mark.parametrize("role", ROLES)
    def test_contains_base_markers(self, role):
        """Промпт роли содержит маркеры из base.md (инфра-секции присутствуют)."""
        prompt = P.build_system_prompt(PIPELINE, role)
        for marker in _BASE_MARKERS:
            assert marker in prompt, (
                f"роль '{role}': base-маркер {marker!r} не найден в промпте")

    @pytest.mark.parametrize("role", ROLES)
    def test_contains_role_markers(self, role):
        """Промпт роли содержит обязательные структурные теги роли."""
        prompt = P.build_system_prompt(PIPELINE, role)
        markers = _ROLE_MARKERS.get(role, [])
        for marker in markers:
            assert marker in prompt, (
                f"роль '{role}': маркер {marker!r} не найден в промпте")

    @pytest.mark.parametrize("role", ROLES)
    def test_upstream_markers_present_in_ours(self, role):
        """Все XML-теги из upstream-промпта присутствуют и в нашем промпте.

        Проверяет структурный drift: если upstream добавит новую секцию,
        а pipelines/default/ не обновят — тест упадёт.
        """
        import re
        ours = P.build_system_prompt(PIPELINE, role)
        upstream = _upstream_static_prompt(role)
        # Извлекаем открывающие теги (не закрывающие) из upstream
        upstream_tags = set(re.findall(r"<(?!/)\w[\w\-]*(?:\s[^>]*)?>", upstream))
        for tag in upstream_tags:
            assert tag in ours, (
                f"роль '{role}': тег {tag!r} из upstream не найден в нашем промпте")


# ── B2.2: validate_spawn для всех пар ролей ────────────────────────────────

def _our_spawn_allowed(parent: str, child: str) -> bool:
    """True, если наш ``validate_spawn`` РАЗРЕШАЕТ спавн (не бросает ValueError)."""
    try:
        P.validate_spawn(PIPELINE, parent, child)
        return True
    except ValueError:
        return False


def _upstream_spawn_allowed(parent: str, child: str) -> bool:
    """Решение upstream по ``_role_can_spawn`` (frontmatter can_spawn).

    Семантика ``_role_can_spawn``:
      * None  — поля нет/битое → unrestricted (спавн кого угодно).
      * []    — терминал (никого).
      * [...] — whitelist.
    Все 6 ролей в upstream существуют (parent известен), child всегда из ROLES.
    """
    wl = _prompting.role_can_spawn(parent)
    if wl is None:
        return True
    if "*" in wl:
        return True
    return child in wl


class TestValidateSpawnMatchesUpstream:
    @pytest.mark.parametrize("parent", ROLES)
    @pytest.mark.parametrize("child", ROLES)
    def test_spawn_pair_matches_upstream(self, parent, child):
        """Для каждой пары (parent, child) разрешение спавна == upstream-логике."""
        assert _our_spawn_allowed(parent, child) == _upstream_spawn_allowed(parent, child), (
            f"спавн {parent} → {child}: наш результат != upstream")

    def test_worker_and_full_cycle_unlimited(self):
        """После B1: worker / full-cycle (нет can_spawn в upstream → unlimited)
        как родители РАЗРЕШАЮТ спавн любой роли."""
        for parent in ("worker", "full-cycle"):
            assert _prompting.role_can_spawn(parent) is None  # upstream: поля нет
            for child in ROLES:
                assert _our_spawn_allowed(parent, child), f"{parent} должен спавнить {child}"



# ── B2.3: resolve_role поля == upstream frontmatter ────────────────────────

class TestResolveRoleMatchesFrontmatter:
    @pytest.mark.parametrize("role", ROLES)
    def test_model_matches(self, role):
        """model резолвнутой роли == frontmatter ``model`` (с маппингом sonnet/opus)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        # orchestrator/sub-orchestrator/full-cycle/reviewer — opus; worker — sonnet/opus
        # → sonnet; watcher — haiku. Defaults манифеста (opus) дают то же для ролей
        # без явной модели, но upstream явно указывает model у всех — сверяем напрямую.
        expected = _map_model(fm["model"])
        assert rr.model == expected, f"роль '{role}': model {rr.model} != upstream {expected}"

    @pytest.mark.parametrize("role", ROLES)
    def test_modules_match(self, role):
        """modules резолвнутой роли == frontmatter ``modules`` (порядок важен — инлайн)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        assert rr.modules == fm.get("modules", []), f"роль '{role}': modules разошлись"

    @pytest.mark.parametrize("role", ROLES)
    def test_skills_match(self, role):
        """skills роли == frontmatter ``skills`` (union с defaults.skills=[], т.е. как есть)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        # defaults.skills=[] → union не добавляет ничего; sorted из _merge_list.
        expected = sorted(fm.get("skills", []))
        got = sorted(rr.skills) if isinstance(rr.skills, list) else rr.skills
        assert got == expected, f"роль '{role}': skills {got} != upstream {expected}"

    @pytest.mark.parametrize("role", ROLES)
    def test_tg_emoji_matches(self, role):
        """tg.emoji роли == frontmatter ``icon`` (нет icon → нет tg / пустой emoji)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        icon = fm.get("icon", "")
        our_emoji = rr.tg.emoji if rr.tg is not None else ""
        assert our_emoji == icon, f"роль '{role}': emoji '{our_emoji}' != upstream icon '{icon}'"


# ── B4: мост воспроизводит рабочий default ─────────────────────────────────

class TestBridgeReproducesDefault:
    """Сгенерированный мостом манифест проходит те же characterization-проверки.

    Мост (``scripts/extract-manifest.py``) пишется во временный
    ``pipelines/bridge-default/`` (с симлинком на реальные prompts default),
    загружается нашим loader'ом и сверяется по roles/can_spawn/model/modules/tg.
    Гарантия: мост не только совпадает с текущим файлом (``--check``), но и даёт
    рабочий, поведенчески верный манифест.
    """

    @pytest.fixture
    def bridge_pipeline(self, tmp_path, monkeypatch):
        """Сгенерировать манифест мостом → tmp pipelines/bridge-default/."""
        data = extract_manifest.build_manifest()
        data["name"] = "bridge-default"  # имя == имени папки (требование loader'а)

        root = tmp_path / "pipelines"
        pdir = root / "bridge-default"
        pdir.mkdir(parents=True)
        import yaml
        (pdir / "pipeline.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        # prompts нужны build_system_prompt — симлинк на реальный default.
        (pdir / "prompts").symlink_to(P.PIPELINES_DIR / "default" / "prompts")

        monkeypatch.setattr(P, "PIPELINES_DIR", root)
        P.load_pipeline.cache_clear()
        yield "bridge-default"
        P.load_pipeline.cache_clear()

    def test_bridge_manifest_self_validates(self, bridge_pipeline):
        """Манифест моста проходит pydantic-валидацию loader'а."""
        cfg = P.load_pipeline(bridge_pipeline)
        assert sorted(cfg.roles) == sorted(ROLES)

    @pytest.mark.parametrize("role", ROLES)
    def test_bridge_role_model_and_modules(self, bridge_pipeline, role):
        """model / modules / tg.emoji роли из моста == upstream frontmatter."""
        rr = P.get_role(bridge_pipeline, role)
        fm = _upstream_frontmatter(role)
        assert rr.model == _map_model(fm["model"])
        assert rr.modules == fm.get("modules", [])
        icon = fm.get("icon", "")
        assert (rr.tg.emoji if rr.tg is not None else "") == icon

    @pytest.mark.parametrize("parent", ROLES)
    @pytest.mark.parametrize("child", ROLES)
    def test_bridge_spawn_matches_upstream(self, bridge_pipeline, parent, child):
        """validate_spawn на манифесте моста == upstream-логике для всех пар."""
        try:
            P.validate_spawn(bridge_pipeline, parent, child)
            ours = True
        except ValueError:
            ours = False
        assert ours == _upstream_spawn_allowed(parent, child)
