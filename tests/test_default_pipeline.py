"""Тесты дефолтного пайплайна ``pipelines/default/``.

Проверяют реальный локальный манифест на базе mccalpink/orchestra v2.18:
4 роли (orchestrator/sub-orchestrator/worker/full-cycle), локальные модели,
fail-open валидацию, сборку промпта без слоя ``_pipeline.md`` и инлайн ``modules``
после слоёв роли.

В отличие от test_pipeline.py (tmp-фикстуры), здесь тесты идут по РЕАЛЬНОМУ
``pipelines/default/`` на диске. Уровень loader'а: БД/manager НЕ задействованы.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import app.pipeline as P

PIPELINE = "default"


@pytest.fixture(autouse=True)
def _clear_cache():
    """lru_cache load_pipeline чистится до/после, чтобы реальный default читался
    с диска (а не из кэша, который мог оставить tmp-фикстуры других тестов)."""
    P.load_pipeline.cache_clear()
    yield
    P.load_pipeline.cache_clear()


# ── Манифест: загрузка и состав ролей ──────────────────────────────────────

class TestDefaultManifestLoads:
    def test_load_pipeline_default_is_valid(self):
        """Манифест проходит pydantic-валидацию loader'а без ошибок."""
        cfg = P.load_pipeline(PIPELINE)
        assert cfg.name == "default"
        assert cfg.validation == "fail-open"  # дух апстрима — мягкая валидация

    def test_role_set_is_exactly_this(self):
        """4 роли апстрима v2.18 + `reducer` (#231 T5).

        Набор ТОЧНЫЙ, а не «не меньше»: тест затем и существует, чтобы роль нельзя
        было добавить незаметно. `reducer` добавлен осознанно — дешёвый сборщик
        отчётов веера, `can_spawn: []`, права отняты отсутствием тулов (#231 T4).
        Обновляется РУКАМИ вместе с каждой новой ролью; ослаблять до `>=` нельзя.
        """
        cfg = P.load_pipeline(PIPELINE)
        assert set(cfg.roles) == {
            "orchestrator", "sub-orchestrator", "worker",
            "full-cycle", "reducer"}

    def test_kinds_match_upstream(self):
        """orchestrator и sub-orchestrator — kind:orchestrator; worker/full-cycle — kind:worker."""
        cfg = P.load_pipeline(PIPELINE)
        assert cfg.roles["orchestrator"].kind == "orchestrator"
        assert cfg.roles["sub-orchestrator"].kind == "orchestrator"
        assert cfg.roles["worker"].kind == "worker"
        assert cfg.roles["full-cycle"].kind == "worker"

    def test_defaults_reproduce_upstream(self):
        """Дефолты пайплайна = поведение апстрима: model opus, без skills/mcp-форса,
        base_branch_strategy main, docs_scaffold off, слои БЕЗ _pipeline.md."""
        cfg = P.load_pipeline(PIPELINE)
        d = cfg.defaults
        assert d.model == "opus"
        assert d.skills == []  # default НЕ форсит skills:all (skills задаёт роль)
        assert d.mcp_servers == []  # апстрим не прокидывает user-MCP
        assert d.base_branch_strategy == "main"  # все worktree от main
        assert d.docs_scaffold is False  # апстрим не скаффолдит doc-папки
        assert d.inherit_claude_md is True  # CLAUDE.md проекта копируется в worktree

    def test_prompt_layers_have_no_pipeline_layer(self):
        """У апстрима НЕТ _pipeline.md — только base + роль."""
        cfg = P.load_pipeline(PIPELINE)
        assert cfg.defaults.prompt_layers.orchestrator == ["base.md", "roles/{role}.md"]
        assert cfg.defaults.prompt_layers.worker == ["base.md", "roles/{role}.md"]
        assert "_pipeline.md" not in cfg.defaults.prompt_layers.orchestrator
        assert "_pipeline.md" not in cfg.defaults.prompt_layers.worker

    def test_worktree_copies_match_upstream_project_files(self):
        """worktree.copies = его PROJECT_FILES (workspace.py:14), симлинков нет."""
        cfg = P.load_pipeline(PIPELINE)
        assert cfg.defaults.worktree.copies == [
            "CLAUDE.md", ".mcp.json", ".env", ".worktreeinclude"]
        assert cfg.defaults.worktree.symlinks == []

    def test_listed_as_valid(self):
        """list_pipelines() видит default и помечает valid=True."""
        entries = {p["name"]: p for p in P.list_pipelines()}
        assert PIPELINE in entries
        assert entries[PIPELINE]["valid"] is True


# ── resolve_role: локальные модели и kind ──────────────────────────────────

class TestDefaultRolesResolve:
    def test_worker_model_resolves_to_opus5(self):
        rr = P.get_role(PIPELINE, "worker")
        assert rr is not None
        assert rr.model == "claude-opus-5[1m]"

    def test_orchestrator_is_orchestrator(self):
        rr = P.get_role(PIPELINE, "orchestrator")
        assert rr is not None
        assert rr.is_orchestrator is True
        assert rr.model == "claude-opus-5[1m]"

    def test_worker_and_full_cycle_are_not_orchestrators(self):
        """worker И full-cycle — воркеры (оркестратор спавнит их как исполнителей)."""
        assert P.get_role(PIPELINE, "worker").is_orchestrator is False
        assert P.get_role(PIPELINE, "full-cycle").is_orchestrator is False
        assert P.get_role(PIPELINE, "worker").can_spawn == []
        assert P.get_role(PIPELINE, "full-cycle").can_spawn == ["*"]

    def test_full_cycle_model_opus5(self):
        rr = P.get_role(PIPELINE, "full-cycle")
        assert rr is not None
        assert rr.model == "claude-opus-5[1m]"

    def test_sub_orchestrator_is_orchestrator_opus5(self):
        """sub-orchestrator — kind:orchestrator, Opus 5, can_spawn=['*']."""
        rr = P.get_role(PIPELINE, "sub-orchestrator")
        assert rr is not None
        assert rr.is_orchestrator is True
        assert rr.model == "claude-opus-5[1m]"
        assert rr.can_spawn == ["*"]
        assert rr.allow_unrouted_workers is True

    @pytest.mark.parametrize(
        "role", ["worker", "full-cycle", "orchestrator", "sub-orchestrator"])
    @pytest.mark.parametrize("model,runtime,expected", [
        ("claude-opus-5[1m]", "claude", "high"),    # #208: перегиб отдачи на high
        ("gpt-5.6-sol", "codex", "xhigh"),          # #208: перегиба в лестнице нет
        ("gpt-5.6-luna", "codex", "high"),          # #204: колено на high
        ("gpt-5.3-codex-spark", "codex", "high"),   # не мерился → default
    ])
    def test_every_role_resolves_effort_by_model(self, role, model, runtime, expected):
        """Все четыре роли — одна карта. Оркестраторы подняты medium→high (#214)."""
        rr = P.get_role(PIPELINE, role)
        assert P.resolve_effort(rr.effort, model, runtime) == expected

    def test_no_role_is_left_on_a_scalar_effort(self):
        """Скаляр остаётся ВАЛИДНЫМ (тесты в test_pipeline.py), но в дефолтном
        манифесте его больше нет — иначе роль снова обслуживала бы одну модель."""
        for role in P.known_roles(PIPELINE):
            assert isinstance(P.get_role(PIPELINE, role).effort, dict), role

    def test_modules_resolve_from_manifest(self):
        """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
        assert P.get_role(PIPELINE, "orchestrator").modules == [
            "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
            "background-jobs", "task-management", "self-improvement", "memory-search",
        ]
        assert P.get_role(PIPELINE, "sub-orchestrator").modules == [
            "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
            "background-jobs", "task-management", "self-improvement", "memory-search",
        ]
        assert P.get_role(PIPELINE, "worker").modules == [
            "code-quality", "git-workflow", "report-format", "self-improvement", "memory-search",
        ]
        assert P.get_role(PIPELINE, "full-cycle").modules == [
            "model-routing", "research-method", "code-quality", "git-workflow", "worker-lifecycle",
            "report-format", "self-improvement", "memory-search",
        ]

    def test_code_quality_has_one_owner_and_reaches_both_working_roles(self):
        """#prompt-cleanup: блок жил ДВУМЯ дословными копиями в roles/worker.md и
        roles/full-cycle.md. Копия расходится молча, поэтому владелец теперь модуль.

        Проверяются обе стороны: текст доезжает до рабочих ролей ровно один раз И его
        больше нет в файлах ролей. Без второй половины тест зелёный и на возвращённой копии.
        """
        module = P.prompt_path(PIPELINE, "modules/code-quality.md").read_text().strip()
        bullets = [ln.strip() for ln in module.splitlines() if ln.startswith("- ")]
        assert len(bullets) >= 12, "модуль потерял пункты — якоря стали слабее"

        for role in ("worker", "full-cycle"):
            out = P.build_system_prompt(PIPELINE, role)
            assert out.count(module) == 1, f"{role}: code-quality должен прийти ровно из модуля"
            src = P.prompt_path(PIPELINE, f"roles/{role}.md").read_text()
            assert "<code-quality>" not in src, (
                f"roles/{role}.md: копия блока вернулась в файл роли"
            )

        for role in ("orchestrator", "sub-orchestrator"):
            out = P.build_system_prompt(PIPELINE, role)
            assert "<code-quality>" not in out, f"{role}: правила написания кода протекли"

    def test_model_routing_reaches_only_spawn_capable_roles(self):
        """Маршрутизация инлайнится ровно тем, кто умеет спавнить, и ровно из модуля (#203).

        Якоря берутся ИЗ САМОГО модуля, а не выписаны руками: проверка по тегу-обёртке
        и по паре фраз про Luna оставалась зелёной, когда в `base.md` копировали пункт
        про Opus без тегов (Codex, раунд 2). Предел честно: дословную копию любого
        пункта тест ловит, переписанную своими словами — нет.
        """
        module = P.prompt_path(PIPELINE, "modules/model-routing.md").read_text().strip()
        bullets = [ln.strip() for ln in module.splitlines() if ln.startswith("- **")]
        assert len(bullets) >= 5, "модуль потерял пункты — якоря стали слабее"
        for role in ("orchestrator", "sub-orchestrator", "full-cycle"):
            out = P.build_system_prompt(PIPELINE, role)
            assert P.get_role(PIPELINE, role).can_spawn == ["*"]
            assert out.count(module) == 1, f"{role}: маршрутизация должна прийти ровно из модуля"
        worker_out = P.build_system_prompt(PIPELINE, "worker")
        assert P.get_role(PIPELINE, "worker").can_spawn == []
        for anchor in ["<model-routing>", *bullets]:
            assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"

    def test_t1_spark_admission_rule_is_delivered_without_leaking(self):
        anchors = (
            "separate but small quota wallet, not free capacity",
            "#222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS)",
            "Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete",
            "text-only; ≤2 named files",
            "≤100K total initial context (system prompt + task + supplied files)",
            "every correctness-critical decision and value is explicit",
            "an independent pre-existing oracle mechanically covers every correctness-critical criterion",
            "Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route",
            "At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption",
            "semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden",
            "After any failed or incomplete Spark attempt, never retry Spark",
        )
        module = P.prompt_path(PIPELINE, "modules/model-routing.md").read_text()
        spark_rules = [line for line in module.splitlines() if line.startswith("- **Spark**")]
        assert len(spark_rules) == 1, "Spark admission must have exactly one owner rule"
        spark_rule = spark_rules[0]
        for anchor in anchors:
            assert anchor in spark_rule, f"Spark admission rule lacks {anchor!r}"

        for role in ("orchestrator", "sub-orchestrator", "full-cycle"):
            out = P.build_system_prompt(PIPELINE, role)
            for anchor in anchors:
                assert out.count(anchor) == 1, f"{role}: Spark rule is missing or duplicated: {anchor!r}"

        worker_out = P.build_system_prompt(PIPELINE, "worker")
        for anchor in anchors:
            assert anchor not in worker_out, f"Spark admission leaked to terminal worker: {anchor!r}"

    def test_tg_emoji_for_v216_roles(self):
        assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"

    def test_orchestrator_skills_from_manifest(self):
        rr = P.get_role(PIPELINE, "orchestrator")
        assert set(rr.skills) == {
            "html-artifacts", "vps-deploy", "codex-debate", "grill-me", "orchestra-agents",
        }

    def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
        """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
        role='worker'/пустая роль допустима."""
        rr = P.get_role(PIPELINE, "orchestrator")
        assert rr.can_spawn == ["*"]
        assert rr.allow_unrouted_workers is True

    def test_orchestrator_layers_substituted_no_pipeline(self):
        """Резолвнутые слои оркестратора: base + roles/orchestrator.md, БЕЗ _pipeline.md."""
        rr = P.get_role(PIPELINE, "orchestrator")
        assert rr.prompt_layers == ["base.md", "roles/orchestrator.md"]

    def test_worker_layers_substituted(self):
        rr = P.get_role(PIPELINE, "worker")
        assert rr.prompt_layers == ["base.md", "roles/worker.md"]


# ── build_system_prompt: композиция base + роль (без _pipeline.md) ──────────

class TestDefaultBuildSystemPrompt:
    def test_orchestrator_prompt_is_base_plus_role(self):
        """Сборка orchestrator = base.md + тело orchestrator.md (2 слоя), непустая."""
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        assert out
        # base.md идёт первым слоем — начинается с его <platform>
        assert out.startswith("<platform>")
        # тело роли подклеено вторым слоем
        assert "## Role: Orchestrator" in out

    def test_orchestrator_prompt_has_no_pipeline_layer_content(self):
        """В default НЕТ _pipeline.md — слой не существует и не подмешивается."""
        # файла нет физически
        assert not P.prompt_path(PIPELINE, "_pipeline.md").is_file()
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        # маркеров нашего сквозного слоя быть не должно (его в default нет вовсе)
        assert "_pipeline" not in out

    def test_orchestrator_prompt_contains_base_critical_marker(self):
        """Характеризация: маркер из его base.md (critical-правило) присутствует —
        доказывает, что слой base.md реально склеен."""
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        assert "NEVER address the user by name" in out
        # и платформенный маркер MCP send_message
        assert "mcp__orchestra__send_message" in out

    def test_all_roles_forbid_acknowledgement_loops(self):
        for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
            out = P.build_system_prompt(PIPELINE, role)
            assert "Never send acknowledgement-only messages" in out
            assert "do not reply and end the turn silently" in out

    def test_all_roles_end_turn_instead_of_waiting_for_external_state(self):
        for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
            out = P.build_system_prompt(PIPELINE, role)
            assert "Never sleep or poll for a background job, review, or another agent" in out
            assert "End the turn; Orchestra resumes you on completion" in out
            assert "Sleeps inside tests or bounded restart checks are allowed" in out

    def test_orchestrator_prompt_contains_role_body_markers(self):
        """Характеризация: ключевые XML-секции тела orchestrator.md на месте."""
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        # v2.16 upstream убрал секцию <parallel-tasks> из тела orchestrator —
        # её содержимое переехало в "Merge & kill safety"/правила.
        for marker in ("<decision-tree>", "<tools>", "<worker-management>",
                       "<task-workflow>"):
            assert marker in out, f"missing orchestrator marker {marker}"

    def test_worker_prompt_is_base_plus_role(self):
        """Сборка worker = base.md + тело worker.md; identity-плейсхолдеры сохранены."""
        out = P.build_system_prompt(PIPELINE, "worker")
        assert out.startswith("<platform>")
        assert "## Role: Worker" in out
        assert "<identity>" in out
        # manager подставит плейсхолдеры при спавне — на уровне loader они сырые
        assert "{worker_name}" in out
        assert "{orchestrator_name}" in out

    def test_full_cycle_prompt_has_three_phase_pipeline(self):
        """full-cycle: 3 фазы (research+experiment / plan+tickets / implement),
        codex review, docs/tasks/<id>/."""
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert out.startswith("<platform>")
        assert "## Role: Full-Cycle Worker" in out
        assert "<pipeline>" in out
        assert "Phase 1: RESEARCH + EXPERIMENT" in out
        assert "Phase 2: PLAN" in out
        assert "Phase 3: IMPLEMENT" in out
        assert "docs/tasks/" in out

    def test_orchestrator_prompt_excludes_other_roles_bodies(self):
        """ИЗОЛЯЦИЯ слоёв: в промпте orchestrator НЕ должно быть тел worker/full-cycle
        (каталог ролей добавляет manager динамически, не build_system_prompt)."""
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        assert "## Role: Worker" not in out
        assert "## Role: Full-Cycle Worker" not in out


class TestTelegramFormattingOwnership:
    """#221: Telegram presentation rules belong only to the user-facing role."""

    OPEN = "<telegram-formatting>"
    CLOSE = "</telegram-formatting>"
    USER_ROLE = "orchestrator"
    OTHER_ROLES = ("sub-orchestrator", "worker", "full-cycle")

    def _source_block(self) -> tuple[str, list[str]]:
        source = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text(encoding="utf-8")
        start = source.find(self.OPEN)
        end = source.find(self.CLOSE, start)
        assert start != -1 and end != -1, "Telegram formatting section is missing from its owner"
        block = source[start:end + len(self.CLOSE)]
        clauses = [line.strip() for line in block.splitlines() if line.strip()]
        assert len(clauses) >= 10, "Telegram formatting section is unexpectedly short"
        return block, clauses

    def test_every_source_clause_reaches_the_assembled_user_prompt(self):
        """The source file, not hand-written test phrases, supplies the delivery anchors."""
        _block, clauses = self._source_block()
        assembled = P.build_system_prompt(PIPELINE, self.USER_ROLE)
        for clause in clauses:
            assert clause in assembled, f"Telegram formatting clause did not assemble: {clause!r}"

    def test_telegram_formatting_does_not_leak_to_non_user_roles(self):
        block, _clauses = self._source_block()
        assert self.OPEN in P.build_system_prompt(PIPELINE, self.USER_ROLE)
        for role in self.OTHER_ROLES:
            assembled = P.build_system_prompt(PIPELINE, role)
            assert self.OPEN not in assembled, f"Telegram rules leaked into {role}"
            assert block not in assembled, f"Telegram rules leaked into {role}"


# ── modules: инлайн переиспользуемых блоков после слоёв роли ────────────────

class TestDefaultModulesInline:
    GIT_MARKER = "Each worker runs in an isolated"
    ORCH_MARKER = "## Role: Orchestrator"
    REPORT_MARKER = "## Report format"

    def test_worker_prompt_inlines_modules(self):
        out = P.build_system_prompt(PIPELINE, "worker")
        assert self.GIT_MARKER in out
        assert self.REPORT_MARKER in out

    def test_full_cycle_prompt_inlines_modules(self):
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert self.GIT_MARKER in out
        assert self.REPORT_MARKER in out

    def test_orchestrator_inlines_git_and_orchestration(self):
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        assert self.GIT_MARKER in out
        assert "orchestration" in out.lower() or "<decision-tree>" in out
        assert self.REPORT_MARKER not in out

    def test_modules_appended_after_role_layers(self):
        """Модули идут ПОСЛЕ тела роли: маркер роли встречается раньше git-блока."""
        out = P.build_system_prompt(PIPELINE, "worker")
        assert out.index("## Role: Worker") < out.index(self.GIT_MARKER)

    def test_unsafe_module_name_rejected(self):
        """Безопасность изоляции: modules с '..' → ValidationError на загрузке."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            P.RoleSpec(kind="worker", label="X", modules=["../escape"])
        with pytest.raises(ValidationError):
            P.RoleSpec(kind="worker", label="X", modules=["/abs/path"])


# ── Характеризация 1:1 с апстримом: содержимое слоёв = его файлы ───────────

class TestUpstreamCharacterization:
    def test_base_layer_file_starts_at_platform(self):
        """base.md портирован дословно (frontmatter у него нет) — начинается с <platform>,
        заканчивается закрывающим </rules>."""
        base = P.prompt_path(PIPELINE, "base.md").read_text()
        assert base.startswith("<platform>")
        assert "</rules>" in base
        # critical-правила апстрима (NEVER ...) — характеризация base.md (v2.16: 5)
        assert base.count("- NEVER ") >= 5

    def test_role_files_have_frontmatter_stripped(self):
        """У ролей frontmatter срезан — тело начинается с <role>, без YAML '---'/'name:'."""
        for role in ("orchestrator", "sub-orchestrator", "worker",
                     "full-cycle"):
            body = P.prompt_path(PIPELINE, f"roles/{role}.md").read_text()
            assert body.startswith("<role>"), f"{role}.md must start with <role>"
            # метаданные переехали в yaml — в теле их быть не должно как frontmatter
            assert not body.lstrip().startswith("---")
            assert "\nname:" not in body[:200]

    def test_skill_files_keep_frontmatter(self):
        """skills/*.md портированы С frontmatter (это skill-метаданные name/description,
        их читает inject_skills_to_worktree)."""
        for skill in ("html-artifacts", "vps-deploy"):
            text = P.prompt_path(PIPELINE, f"skills/{skill}.md").read_text()
            assert text.lstrip().startswith("---"), f"{skill}.md must keep frontmatter"
            assert f"name: {skill}" in text

    def test_build_prompt_matches_concatenation_of_layers(self):
        """build_system_prompt(orchestrator) = base.md + role + modules."""
        base = P.prompt_path(PIPELINE, "base.md").read_text()
        role = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text()
        modules = [
            P.prompt_path(PIPELINE, f"modules/{name}.md").read_text().strip()
            for name in P.get_role(PIPELINE, "orchestrator").modules
        ]
        expected = "\n\n".join([base, role, *modules])
        assert P.build_system_prompt(PIPELINE, "orchestrator") == expected


class TestRiskBasedReviewRouting:
    """#296: one policy owner, explicit consumers, no silent old-Sol fallback."""

    POINTER = "Apply the review decision gate in the `codex-debate` skill"
    ACTORS = ("orchestrator", "sub-orchestrator", "worker", "full-cycle")
    STALE = (
        "Codex review MANDATORY for complex tasks",
        "Размер диффа основанием для пропуска ревью не является ни в каком случае",
        "Codex follows the worker role's review gate",
    )

    def test_every_review_decision_maker_receives_skill_and_gate(self):
        for role in self.ACTORS:
            spec = P.get_role(PIPELINE, role)
            assert "codex-debate" in spec.skills, f"{role}: cannot load canonical review policy"
            out = P.build_system_prompt(PIPELINE, role)
            assert out.count(self.POINTER) == 1, f"{role}: review gate missing or duplicated"

        reducer = P.get_role(PIPELINE, "reducer")
        assert "codex-debate" not in reducer.skills
        assert self.POINTER not in P.build_system_prompt(PIPELINE, "reducer")

    def test_policy_has_one_tracked_source(self):
        owner = P.prompt_path(PIPELINE, "skills/codex-debate.md")
        assert owner.read_text().count("## Review decision gate — canonical policy") == 1
        repo = Path(__file__).parents[1]
        tracked_native_copy = subprocess.run(
            ["git", "ls-files", "--", ".codex/skills/codex-debate/SKILL.md"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert tracked_native_copy == "", (
            "native .codex copy must stay a reconnect-time projection, not a second owner"
        )

    def test_canonical_contract_covers_skip_routes_and_independence(self):
        policy = P.prompt_path(PIPELINE, "skills/codex-debate.md").read_text()
        anchors = (
            "The author never self-certifies risk or oracle strength",
            "**High-risk is evidence-derived, not author-declared.**",
            "**NO MODEL REVIEW**",
            "**one fresh Luna review**",
            "**one targeted Sol escalation**",
            "**Sol pass on a high-risk surface**",
            "**Docs / fact extraction**",
            "**One round by default.**",
        )
        for anchor in anchors:
            assert policy.count(anchor) == 1, f"canonical review contract lacks {anchor!r}"

    def test_review_is_optional_and_has_no_substitute_reviewer(self):
        """Решение юзера 19.08: ревью полезно, но НЕ обязательно, и заменять недоступный
        Codex другой моделью запрещено — маршрут «поднять Opus вместо Codex» стоил четырёх
        платных ревьюеров за один день.

        Проверяются обе половины: новый контракт присутствует И старый отсутствует. Одна
        половина без другой ложно-зелёная: текст можно дописать, не убрав обязательность,
        и можно убрать маршрут замены, оставив floor, который заставит искать его заново.
        """
        policy = P.prompt_path(PIPELINE, "skills/codex-debate.md").read_text()
        present = (
            "**Ревью доступно, но не обязательно",
            "Codex недоступен → ревью НЕ делается",
            "не поднимать\nOpus, не спавнить ревьюера-агента",
        )
        for anchor in present:
            assert policy.count(anchor) == 1, f"новый контракт ревью потерял {anchor!r}"
        # Формулировка отчёта при недоступном Codex названа и в правиле, и в инструкции
        # запуска — здесь проверяется наличие, а не единственность.
        assert "`Review: none — Codex unavailable`" in policy, (
            "не назван исход, который агент обязан записать вместо ревью"
        )

        # Обязательность и маршрут замены не должны вернуться ни в одной из форм,
        # которые этот файл уже использовал.
        forbidden = (
            "mandatory",
            "targeted Opus cross-family review",
            "cross-family verdict unavailable",
            "Opus запускается свежей reviewer-сессией",
            "review route unavailable",
        )
        for stale in forbidden:
            assert stale not in policy, f"вернулась обязательность/замена ревьюера: {stale!r}"

        # И то же самое там, где правило реально исполняется: спавнит ревьюера оркестратор,
        # а скилл он грузит отдельно — запрет обязан доехать в сам промпт.
        out = P.build_system_prompt(PIPELINE, "orchestrator")
        assert "you never spawn a\nreviewer agent as a substitute" in out, (
            "оркестратор — тот, кто спавнит; без этой строки запрет ничем не принуждается"
        )

    def test_canonical_skill_exposes_direct_luna_review_and_sol_default(self):
        policy = P.prompt_path(PIPELINE, "skills/codex-debate.md").read_text()
        assert 'codex_review(model="gpt5.6luna", ...)' in policy
        assert "backward-compatible default всегда Sol" in policy
        assert "`codex_review` — Sol-only" not in policy
        assert "`codex_review` запускает только Sol" not in policy

    def test_assembled_prompts_drop_stale_mandatory_sol_wording(self):
        for role in self.ACTORS:
            out = P.build_system_prompt(PIPELINE, role)
            for stale in self.STALE:
                assert stale not in out, f"{role}: stale review route survived: {stale!r}"

# ── validate_spawn: fail-open + can_spawn=['*'] + allow_unrouted_workers ────

class TestDefaultValidateSpawn:
    def test_orchestrator_spawns_worker_ok(self):
        """orchestrator can_spawn=['*'] → спавн worker разрешён."""
        assert P.validate_spawn(PIPELINE, "orchestrator", "worker") is None

    def test_orchestrator_spawns_full_cycle_ok(self):
        assert P.validate_spawn(PIPELINE, "orchestrator", "full-cycle") is None

    def test_orchestrator_spawns_v216_roles_ok(self):
        """can_spawn=['*'] → новые роли v2.16 спавнятся оркестратором."""
        for child in ("sub-orchestrator", "full-cycle"):
            assert P.validate_spawn(PIPELINE, "orchestrator", child) is None

    def test_sub_orchestrator_spawns_worker_ok(self):
        """sub-orchestrator тоже can_spawn=['*'] — делегирует вниз."""
        assert P.validate_spawn(PIPELINE, "sub-orchestrator", "worker") is None

    def test_orchestrator_unrouted_worker_ok(self):
        """allow_unrouted_workers=true → пустая роль (генерик-воркер) допустима."""
        assert P.validate_spawn(PIPELINE, "orchestrator", "") is None

    def test_root_spawn_allowed(self):
        """Корневой спавн (нет родителя) — от юзера/UI, всегда ок."""
        assert P.validate_spawn(PIPELINE, "", "orchestrator") is None
        assert P.validate_spawn(PIPELINE, None, "orchestrator") is None

    def test_fail_open_unknown_child_raises(self):
        """#36: '*' — любая известная роль, не любая строка."""
        with pytest.raises(ValueError, match="unknown role"):
            P.validate_spawn(PIPELINE, "orchestrator", "nonexistent-role")

    def test_fail_open_unknown_parent_raises(self):
        """#36: неизвестный parent не обходит whitelist."""
        with pytest.raises(ValueError, match="unknown parent"):
            P.validate_spawn(PIPELINE, "phantom", "worker")


class TestSubOrchestratorGetsMemorySearch:
    """#137: sub-orchestrators work in worktrees and search the same project memory."""

    def test_module_text_reaches_the_assembled_prompt(self):
        from app.manager import ROLE_SYSTEM_PROMPT

        prompt = ROLE_SYSTEM_PROMPT(PIPELINE, "sub-orchestrator", "/tmp")
        assert "<memory-search>" in prompt, (
            "listing the module in pipeline.yaml is not enough — its text must assemble in"
        )
        assert "search_memory(" in prompt
        assert "/api/sessions/" in prompt, (
            "the own-transcript recipe added to this module must reach the role too"
        )


class TestPremortemReachesWorkingRolesOnly:
    """#198 T1: шаг премортема доставляется РАБОЧИМ ролям и не течёт к оркестраторам.

    Инвариант структурный (кто получает шаг), а не текстовый (как он сформулирован):
    переписывать формулировку шага можно свободно, тест это переживёт.
    """

    # Якорь намеренно короткий и устойчивый — заголовок шага, не предложение.
    # Меняешь заголовок в roles/full-cycle.md и roles/worker.md — меняй и здесь.
    ANCHOR = "Pre-mortem"

    WORKING_ROLES = ("worker", "full-cycle")
    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")

    def test_step_is_owned_by_the_working_role_files(self):
        """Якорь общий, поэтому одной проверки собранного промпта мало: она прошла бы
        и в случае, когда шаг из роли исчез, а слово приехало из base.md или модуля.
        Поэтому источник проверяется отдельно от доставки."""
        for role in self.WORKING_ROLES:
            src = P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")
            assert self.ANCHOR in src, (
                f"roles/{role}.md: шаг должен жить в файле САМОЙ роли, а не приезжать "
                "из общего слоя — иначе роль потеряет его при перекомпоновке слоёв"
            )

    def test_working_roles_receive_the_step(self):
        for role in self.WORKING_ROLES:
            out = P.build_system_prompt(PIPELINE, role)
            assert self.ANCHOR in out, (
                f"{role}: премортем должен доехать до СОБРАННОГО промпта; "
                "наличия строки в roles/*.md недостаточно"
            )

    def test_orchestrator_roles_do_not_receive_the_step(self):
        """Односторонняя проверка «есть» пропустила бы утечку в промпты
        оркестраторов, а она опаснее пропажи: премортем — шаг исполнителя.

        Побочный эффект: пока якорь общий, это ещё и запрет слова в промптах
        оркестраторов. Если оркестратору однажды понадобится говорить о премортеме
        законно — не ослаблять проверку, а сделать якорь уникальным (свой тег/ID)
        в обоих рабочих файлах и здесь."""
        for role in self.ORCHESTRATOR_ROLES:
            out = P.build_system_prompt(PIPELINE, role)
            assert self.ANCHOR not in out, (
                f"{role}: шаг исполнителя протёк в промпт оркестратора"
            )


class TestOracleGate:
    """#210: фаза плана заканчивается КРАСНЫМ тестом, а исполнитель не пишет себе оракул сам.

    Форма проверки скопирована с `TestPremortemReachesWorkingRolesOnly` (#198) намеренно:
    один способ решения одной задачи. Тройка «источник / доставка / не-утечка» и ловит
    составную мутацию «шаг удалён из роли + слова посажены в base.md» — доставка её
    переживает, источник и не-утечка нет.
    """

    # Шаг нарезки тикетов есть только у full-cycle: worker планов не режет.
    PLAN_ANCHOR = "commit it FAILING"
    PLAN_ROLES = ("full-cycle",)
    # Контрправило нужно ОБЕИМ рабочим ролям: дешёвый исполнитель — это роль worker.
    EXEC_ANCHOR = "Never author the acceptance test"
    EXEC_ROLES = ("worker", "full-cycle")
    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")

    def _src(self, role: str) -> str:
        return P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")

    # ── источник ───────────────────────────────────────────────────────────
    def test_plan_step_is_owned_by_the_full_cycle_file(self):
        for role in self.PLAN_ROLES:
            assert self.PLAN_ANCHOR in self._src(role), (
                f"roles/{role}.md: шаг «план заканчивается красным тестом» должен жить в "
                "файле САМОЙ роли, иначе он потеряется при перекомпоновке слоёв"
            )

    def test_executor_rule_is_owned_by_both_working_role_files(self):
        for role in self.EXEC_ROLES:
            assert self.EXEC_ANCHOR in self._src(role), (
                f"roles/{role}.md: без этой строки исполнитель напишет оракул себе сам "
                "(замер #210: 2 прогона из 2)"
            )

    # ── полнота шага: якоря берутся ИЗ ИСТОЧНИКА, а не выписаны руками (#203) ──
    def test_every_clause_of_the_plan_step_survives_assembly(self):
        src = self._src("full-cycle")
        start = src.find(self.PLAN_ANCHOR)
        assert start != -1, "шага нет в roles/full-cycle.md — проверять нечего"
        block_start = src.rfind("\n3. ", 0, start)
        block_end = src.find("\n4. ", start)
        assert block_start != -1 and block_end != -1, (
            "блок шага не ограничен соседними пунктами 3 и 4 — нумерация фазы 2 разъехалась"
        )
        clauses = [ln.strip() for ln in src[block_start:block_end].splitlines() if ln.strip()]
        assert len(clauses) >= 8, f"блок подозрительно короткий: {len(clauses)} строк"
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        for clause in clauses:
            assert clause in out, f"пункт шага не доехал до собранного промпта: {clause[:70]!r}"

    def test_ticket_template_carries_the_test_field_and_a_REASONED_none_marker(self):
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "- Test: <path>::<test name> — committed RED in <commit>" in out, (
            "шаблон тикета обязан называть поле Test целиком, вместе с требованием RED"
        )
        # Метка проверяется В САМОМ ШАБЛОНЕ, а не «где-то в промпте»: ассерт на голую строку
        # проходил бы, пока причина упомянута в соседнем абзаце, а шаблон показывал бы
        # безпричинную форму — её агент и скопирует (blocking раунда 2 Codex-ревью плана).
        assert "| oracle: none — <why" in out, (
            "шаблон обязан показывать метку ТОЛЬКО с причиной; голая `oracle: none` — "
            "невалидный тикет и в шаблоне встречаться не должна"
        )

    def test_phase_3_selects_the_ticket_before_it_implements(self):
        """Шаг 1 фазы 3 обязан ВЫБИРАТЬ тикет, а не начинать реализацию: иначе буквальный
        исполнитель начнёт править код на шаге 1 и дойдёт до гейта уже после
        (blocking Codex-ревью реализации). Порядок шагов и есть здесь предохранитель."""
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "implementation starts only after step 2 passes" in out, (
            "шаг 1 фазы 3 обязан явно откладывать реализацию до прохождения гейта"
        )

    def test_own_phase_2_test_may_not_be_weakened(self):
        """Клауза без якоря удаляется молча: до этого теста её можно было вырезать, и все
        девять оставались зелёными (blocking Codex-ревью реализации). Опаснее прочего именно
        она — это единственный запрет подгонять СВОЙ красный тест под написанный код."""
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "never weaken it to fit the code you wrote" in out, (
            "запрет ослаблять собственный тест фазы 2 обязан быть в промпте full-cycle"
        )
        assert "never weaken it to fit the code you wrote" not in P.build_system_prompt(
            PIPELINE, "worker"
        ), "клауза про СВОЙ тест фазы 2 относится только к full-cycle: worker планов не пишет"

    def test_phase_3_names_the_only_exception_for_oracle_none(self):
        """Без исключения шаг «увидеть красным ДО правки» делает тикеты `oracle: none`
        невыполнимыми: команды у них нет, значит «missing» → вечный STOP
        (blocking раунда 2 Codex-ревью плана)."""
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "The only exception:" in out and "verify it against its AC by hand" in out, (
            "фаза 3 обязана назвать единственное исключение для `oracle: none`"
        )

    def test_the_step_has_teeth_in_phase_3_and_in_the_codex_gate(self):
        """Потребители шага обязаны быть В ТЕКСТЕ РОЛИ, а не в прозе плана.

        Без этих двух строк исполнителю достаточно один раз запустить финальную зелёную
        команду, и он формально соблюдёт правило — красный артефакт станет церемонией
        (blocking раунда 1 Codex-ревью плана)."""
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "see it red before you change" in out, (
            "фаза 3 обязана требовать увидеть тест красным ДО правки"
        )
        assert "already green at review time is a blocking finding" in out, (
            "Codex-ревью плана обязано ревьюить сам тест, иначе у шага нет проверяющего"
        )

    def test_plan_ready_report_quotes_the_failing_run(self):
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        assert "→ exit 1:" in out, (
            "отчёт PLAN READY обязан цитировать ненулевой exit и падающую строку — "
            "это потребитель шага, без него он станет ритуалом"
        )

    # ── доставка ───────────────────────────────────────────────────────────
    def test_working_roles_receive_their_anchors(self):
        for role in self.PLAN_ROLES:
            assert self.PLAN_ANCHOR in P.build_system_prompt(PIPELINE, role), (
                f"{role}: наличия строки в roles/*.md недостаточно, шаг обязан доехать "
                "до СОБРАННОГО промпта"
            )
        for role in self.EXEC_ROLES:
            assert self.EXEC_ANCHOR in P.build_system_prompt(PIPELINE, role), (
                f"{role}: контрправило не доехало до собранного промпта"
            )

    # ── не-утечка (она же ловушка на составную мутацию) ────────────────────
    def test_orchestrator_roles_receive_neither(self):
        for role in self.ORCHESTRATOR_ROLES:
            out = P.build_system_prompt(PIPELINE, role)
            assert self.PLAN_ANCHOR not in out, (
                f"{role}: шаг исполнителя протёк в промпт оркестратора — либо утечка, "
                "либо слова посажены в общий слой вместо роли"
            )
            assert self.EXEC_ANCHOR not in out, (
                f"{role}: контрправило исполнителя протекло в промпт оркестратора"
            )

class TestTicketDelegationGate:
    """#223: закрытый тикет уходит исполнителю, а оракул остаётся у full-cycle."""

    IMMUTABLE_ANCHOR = (
        "The received acceptance test is immutable: NEVER edit, delete, rename, skip, "
        "xfail, or weaken it."
    )
    WORKER_FAILURE_ANCHOR = (
        "If the command cannot be made green without changing that test, report `WIP/STOP`; "
        "do not replace it or create a different check."
    )
    TEST_INFRA_ANCHOR = (
        "Do not modify any test, fixture, test helper, `conftest.py`, test configuration, "
        "marker, or test-selection setting; if the implementation requires one, report "
        "`WIP/STOP`."
    )
    TEST_LAYER_EXCEPTION_ANCHORS = (
        "Sole exception: test-layer edits are permitted only when a direct orchestrator "
        "assignment explicitly authorizes those specific edits.",
        "The permission must be stated in the assignment; never infer it from what the "
        "implementation requires.",
        "This exception never applies to the received acceptance test, which remains "
        "immutable.",
        "Without that explicit authorization, report `WIP/STOP`.",
    )
    FULL_CYCLE_ANCHORS = (
        "Only a ticket with a reviewed, committed RED command that just failed for the "
        "missing behavior is delegable.",
        "A ticket marked `oracle: none` is NEVER delegated; implement it yourself on the "
        "expensive side.",
        "Send `Files`, `Test`, `AC`, `blocked-by`, the RED commit, the exact command, its "
        "non-zero exit and failing assertion, plus these sentences verbatim:",
        "The worker sends exactly one message: its terminal `DONE` report, or one terminal "
        "exception report instead.",
        "The terminal report contains the executor commit, the exact test command and output, "
        "and evidence for every remaining AC.",
        "Before merge, compare every oracle path byte-for-byte with the RED commit.",
        "Reject any executor diff that changes a test, fixture, test helper, `conftest.py`, "
        "test configuration, marker, or test-selection setting relative to the RED commit.",
        "A clarification request, a `WIP/STOP` report, or any oracle mutation is a failed "
        "executor attempt.",
        "Luna gets exactly one attempt.",
        "On failure, send the same unchanged ticket once to a Sol `worker`; do not answer "
        "Luna's question, rewrite its oracle, or return the ticket to Luna.",
        "A Sol `worker` gets exactly one attempt.",
        "If the premise, scope, Test, or AC must change, take it back immediately and re-close "
        "it before any future delegation.",
        "A child's green report is evidence, not acceptance. Merge only a clean committed "
        "result, then rerun the exact command and the ticket's focused regression check "
        "yourself.",
        "Independent tickets whose files and lines do not overlap may run concurrently; "
        "serialize only dependency chains and overlapping changes.",
        "Never split one implementation ticket across agents.",
    )
    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")

    def _src(self, role: str) -> str:
        return P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")

    def test_t1_delegation_full_cycle_source_owns_the_complete_contract(self):
        src = self._src("full-cycle")
        missing = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor not in src]
        assert not missing, f"roles/full-cycle.md is missing delegation clauses: {missing}"

    def test_t1_delegation_immutable_rule_is_owned_by_both_sources(self):
        for role in ("full-cycle", "worker"):
            assert self.IMMUTABLE_ANCHOR in self._src(role), (
                f"roles/{role}.md must own the immutable-oracle rule"
            )
        assert self.TEST_INFRA_ANCHOR in self._src("full-cycle"), (
            "roles/full-cycle.md must keep the absolute delegated-oracle infrastructure rule"
        )
        worker_src = self._src("worker")
        missing = [
            anchor for anchor in self.TEST_LAYER_EXCEPTION_ANCHORS if anchor not in worker_src
        ]
        assert not missing, f"roles/worker.md is missing direct-assignment exception: {missing}"
        assert self.WORKER_FAILURE_ANCHOR in self._src("worker"), (
            "roles/worker.md must turn an oracle-dependent implementation into WIP/STOP"
        )

    def test_t1_delegation_contract_reaches_working_roles(self):
        full_cycle = P.build_system_prompt(PIPELINE, "full-cycle")
        for anchor in (
            *self.FULL_CYCLE_ANCHORS,
            self.IMMUTABLE_ANCHOR,
            self.TEST_INFRA_ANCHOR,
        ):
            assert anchor in full_cycle, f"full-cycle prompt lost clause: {anchor!r}"
        assert self.IMMUTABLE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
            "worker prompt lost the immutable-oracle rule"
        )
        assert self.WORKER_FAILURE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
            "worker prompt lost the WIP/STOP consequence of oracle immutability"
        )
        worker_out = P.build_system_prompt(PIPELINE, "worker")
        missing = [
            anchor for anchor in self.TEST_LAYER_EXCEPTION_ANCHORS if anchor not in worker_out
        ]
        assert not missing, f"worker prompt lost direct-assignment exception: {missing}"

    def test_t1_delegation_does_not_leak_into_orchestrators(self):
        anchors = (
            *self.FULL_CYCLE_ANCHORS,
            self.IMMUTABLE_ANCHOR,
            self.WORKER_FAILURE_ANCHOR,
            self.TEST_INFRA_ANCHOR,
            *self.TEST_LAYER_EXCEPTION_ANCHORS,
        )
        for role in self.ORCHESTRATOR_ROLES:
            out = P.build_system_prompt(PIPELINE, role)
            leaked = [anchor for anchor in anchors if anchor in out]
            assert not leaked, f"{role} received executor-only delegation clauses: {leaked}"

    def test_t1_delegation_worker_does_not_receive_parent_policy(self):
        out = P.build_system_prompt(PIPELINE, "worker")
        leaked = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor in out]
        assert not leaked, f"worker received parent-only routing policy: {leaked}"
        assert self.WORKER_FAILURE_ANCHOR not in P.build_system_prompt(
            PIPELINE, "full-cycle"
        ), "full-cycle received the worker-only WIP/STOP instruction"

    def test_t3_worker_test_layer_authorization_is_worker_owned_and_delivered(self):
        source = self._src("worker")
        assembled = P.build_system_prompt(PIPELINE, "worker")
        for anchor in self.TEST_LAYER_EXCEPTION_ANCHORS:
            assert anchor in source, f"roles/worker.md must own the exception: {anchor!r}"
            assert anchor in assembled, f"worker prompt lost the exception: {anchor!r}"

    def test_t3_worker_test_layer_authorization_does_not_leak(self):
        for role in ("full-cycle", *self.ORCHESTRATOR_ROLES):
            assembled = P.build_system_prompt(PIPELINE, role)
            leaked = [
                anchor for anchor in self.TEST_LAYER_EXCEPTION_ANCHORS if anchor in assembled
            ]
            assert not leaked, f"{role} received the worker-only test-layer exception: {leaked}"

    def test_t3_worker_test_layer_authorization_keeps_oracle_unconditionally_immutable(self):
        source = self._src("worker")
        assembled = P.build_system_prompt(PIPELINE, "worker")
        assert self.IMMUTABLE_ANCHOR in source, (
            "roles/worker.md lost the unconditional received-oracle prohibition"
        )
        assert self.IMMUTABLE_ANCHOR in assembled, (
            "worker prompt lost the unconditional received-oracle prohibition"
        )

    def test_t1_delegation_gate_precedes_implementation_work(self):
        out = P.build_system_prompt(PIPELINE, "full-cycle")
        phase_3 = out.find("### Phase 3: IMPLEMENT")
        gate = out.find(self.FULL_CYCLE_ANCHORS[0], phase_3)
        premortem = out.find("**Pre-mortem — what breaks for the next consumer.**", phase_3)
        assert -1 not in (phase_3, gate, premortem) and phase_3 < gate < premortem, (
            "the delegation gate must run after Phase 3 starts and before implementation work"
        )


POOL_PRIORITY_ANCHORS = (
    "Luna is the DEFAULT",
    "Sol when the task is complex and Luna will not manage it",
    "Opus only for special complex tasks",
    "the Codex pool is meant to be burned",
    "cost of exhaustion, not the cost of spend",
)
OBSOLETE_PRIORITY_ANCHOR = "— DEFAULT worker"


def _roles_receiving_model_routing():
    from app.pipeline import build_system_prompt
    roles = []
    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
        if "model-routing" in build_system_prompt("default", role) or "Spark" in build_system_prompt("default", role):
            roles.append(role)
    assert roles, "ни одна роль не получает model-routing — проверка выродилась"
    return roles


def test_pool_priority_rule_reaches_roles_that_receive_model_routing():
    from app.pipeline import build_system_prompt
    for role in _roles_receiving_model_routing():
        out = build_system_prompt("default", role)
        for anchor in POOL_PRIORITY_ANCHORS:
            assert anchor in out, f"{role}: нет якоря {anchor!r}"


def test_obsolete_priority_formulation_is_gone_everywhere():
    from app.pipeline import build_system_prompt
    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
        out = build_system_prompt("default", role)
        assert OBSOLETE_PRIORITY_ANCHOR not in out, f"{role}: осталась старая формулировка приоритета"


# --- #219: контракт делегирования «таблица, а не область» -------------------
# Якоря — ЦЕЛЬНЫЕ фразы, выписанные вручную из файла-владельца
# (pipelines/default/prompts/modules/worker-lifecycle.md). Не извлекать их из
# источника программно: клауза, извлечённая из уже переформатированного файла,
# находится в сборке всегда и делает тест слепым к переносу строки (#210).
FAN_CONTRACT_ANCHORS = (
    "Order a **schema** — the exact columns — not a subject area.",
    "Give the **counting rule verbatim**",
    "Numbers from different\nchildren are not addable unless you defined the count.",
    "**Forbid conclusions and recommendations.**",
    "**The join and the verdict are yours.**",
    "Choosing which two columns to compare IS the",
)

# Роль, которая НЕ умеет спавнить, не должна получать контракт: лишний текст в
# промпте терминальной роли — это плата без применения.
FAN_CONTRACT_SPAWNERS = ("orchestrator", "sub-orchestrator", "full-cycle")
FAN_CONTRACT_TERMINAL = ("worker",)


def _spawn_capable_roles_from_config():
    """Список берётся из КОНФИГА, а не из константы выше: если появится новая
    спавнящая роль, тест обязан покраснеть, а не молча её пропустить."""
    from app.pipeline import load_pipeline
    cfg = load_pipeline("default")
    roles = [n for n, r in cfg.roles.items() if r.can_spawn]
    assert roles, "ни одна роль не умеет спавнить — проверка выродилась"
    return roles


def _norm(text: str) -> str:
    """Схлопывает переносы и отступы. Якорь остаётся ЦЕЛЬНОЙ фразой (ловит удаление),
    но переживает переформатирование файла — подгонять литерал под текущую вёрстку
    нельзя, он сломается на следующем же реflow (#210)."""
    import re
    return re.sub(r"\s+", " ", text).strip()


def test_fan_contract_reaches_every_spawn_capable_role():
    from app.pipeline import build_system_prompt
    for role in _spawn_capable_roles_from_config():
        out = _norm(build_system_prompt("default", role))
        for anchor in FAN_CONTRACT_ANCHORS:
            assert _norm(anchor) in out, f"{role}: нет якоря контракта веера {anchor!r}"


def test_fan_contract_absent_from_terminal_roles():
    from app.pipeline import build_system_prompt
    for role in FAN_CONTRACT_TERMINAL:
        out = build_system_prompt("default", role)
        assert "Order a **schema**" not in _norm(out), (
            f"{role}: не умеет спавнить, но получил контракт делегирования"
        )


FAN_CONTRACT_OWNER = "modules/worker-lifecycle.md"


def test_fan_contract_comes_from_its_owner_module_and_nowhere_else():
    """AC-3, автоматизируемая половина — проверяется ПРОИСХОЖДЕНИЕ, а не наличие.

    Первая редакция этого теста грепала собранный промпт и была ЛОЖНО-ЗЕЛЁНОЙ:
    составная мутация «пункт удалён из роли + фраза внедрена в base.md» её
    проходила (замер #219, воспроизведён дефект #198). Инструкция при этом
    материально теряется — она уезжает в общий слой, где достаётся и терминальным
    ролям, и теряет свой контекст. Поэтому каждый якорь обязан иметь РОВНО ОДНОГО
    владельца, и владелец — именно модуль ниже.

    Вторую половину AC-3 — «нет ли той же мысли, сформулированной иначе» — греп не
    закрывает по построению; она остаётся ручной проверкой артефакта.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "pipelines" / "default" / "prompts"
    files = {p: _norm(p.read_text(encoding="utf-8")) for p in root.rglob("*.md")}
    for anchor in FAN_CONTRACT_ANCHORS:
        owners = [p for p, text in files.items() if _norm(anchor) in text]
        assert len(owners) == 1, (
            f"якорь {anchor!r}: владельцев должно быть ровно 1, найдено {len(owners)}: "
            f"{[str(p) for p in owners]}"
        )
        assert str(owners[0]).endswith(FAN_CONTRACT_OWNER), (
            f"якорь {anchor!r} уехал из {FAN_CONTRACT_OWNER} в {owners[0]}"
        )


def test_child_is_not_told_to_self_terminate_on_exhaustion():
    """M1: ребёнок останавливается по собственной оценке полноты, и она слепа.
    Формулировка «продолжай, пока вопрос не исчерпан» не должна вернуться."""
    from app.pipeline import build_system_prompt
    for role in _spawn_capable_roles_from_config():
        out = build_system_prompt("default", role)
        assert "until the question is exhausted" not in out.replace(
            'continue "until the question is exhausted"', ""
        ), f"{role}: вернулась формулировка про самостоятельное исчерпание"
