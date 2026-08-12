"""Тесты дефолтного пайплайна ``pipelines/default/``.

Проверяют реальный локальный манифест на базе mccalpink/orchestra v2.18:
4 роли (orchestrator/sub-orchestrator/worker/full-cycle), локальные модели,
fail-open валидацию, сборку промпта без слоя ``_pipeline.md`` и инлайн ``modules``
после слоёв роли.

В отличие от test_pipeline.py (tmp-фикстуры), здесь тесты идут по РЕАЛЬНОМУ
``pipelines/default/`` на диске. Уровень loader'а: БД/manager НЕ задействованы.
"""
from __future__ import annotations

import pytest

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

    def test_has_four_upstream_roles(self):
        """4 роли апстрима v2.18."""
        cfg = P.load_pipeline(PIPELINE)
        assert set(cfg.roles) == {
            "orchestrator", "sub-orchestrator", "worker",
            "full-cycle"}

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
            "git-workflow", "report-format", "self-improvement", "memory-search",
        ]
        assert P.get_role(PIPELINE, "full-cycle").modules == [
            "model-routing", "research-method", "git-workflow", "worker-lifecycle",
            "report-format", "self-improvement", "memory-search",
        ]

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

    def test_fail_open_unknown_child_passes(self):
        """fail-open: при can_spawn=['*'] и неизвестном child — пропуск (дух апстрима,
        каталог ролей = подсказка, не жёсткий контракт)."""
        assert P.validate_spawn(PIPELINE, "orchestrator", "nonexistent-role") is None

    def test_fail_open_unknown_parent_passes(self):
        """fail-open: неизвестный parent не роняет спавн."""
        assert P.validate_spawn(PIPELINE, "phantom", "worker") is None


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
