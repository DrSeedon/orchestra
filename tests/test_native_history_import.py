"""Pinned native-history canaries against the installed Claude and Codex CLIs.

Три теста здесь помечены `@pytest.mark.live_probe`: они поднимают настоящий CLI и тратят
ход провайдера. **Merge-gate их не гоняет** (`app/merge_test_gate.pytest_argv` передаёт
`-m "not live_probe"`), потому что красными они бывают от квоты и недоступности провайдера,
а не от диффа: 16.08 claude-проба стояла красной по `rate_limit`, 18.08 — codex-проба, и та
блокировала мержи всем, чей набор задевал этот файл.

Запускать руками, и обязательно — если правишь `runtime_history`, `backend_*` или путь
handoff'а:

    uv run pytest -m live_probe tests/                 # все живые пробы
    uv run pytest -m live_probe tests/test_native_history_import.py

Красная живая проба — это НЕ разрешение её пропустить. Сначала посмотри `GET /api/usage` и
время падения: секунды означают, что до провайдера дело не дошло и виноват наш гейт,
десятки секунд — что ответил провайдер.

Заводишь новую живую пробу — добавь маркер И строку в `test_live_probe_inventory_is_explicit`
(`tests/test_merge_test_gate.py`), иначе её падение поедет в чужие мержи.
"""

import asyncio
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.backend_claude import ClaudeBackend
from app.backend_codex import CodexBackend
from app.runtime_history import render_claude_history, render_codex_history


SOURCE_ROWS = 7_251
SEMANTIC_CHARS = 1_760_169
TOOL_ROWS = 4_646
EARLY_USER_MARKER = "17410000-0000-4000-8000-000000000001"
TOOL_RESULT_MARKER = "17420000-0000-4000-8000-000000000002"
SYSTEM_PROMPT_MARKER = "17430000-0000-4000-8000-000000000003"


def _fit(text: str, size: int) -> str:
    if len(text) >= size:
        return text[:size]
    filler = " Native history preserves chronological dialogue without a summary."
    return (text + filler * ((size - len(text)) // len(filler) + 1))[:size]


def _long_history_rows() -> list[dict]:
    semantic_rows = SOURCE_ROWS - TOOL_ROWS
    base, extra = divmod(SEMANTIC_CHARS, semantic_rows)
    lengths = [base + (index < extra) for index in range(semantic_rows)]
    rows: list[dict] = []
    next_id = 1

    rows.append({
        "id": next_id,
        "type": "user_message",
        "content": _fit(f"EARLY_USER_CANARY={EARLY_USER_MARKER}.", lengths[0]),
        "ts": "2026-08-11T00:00:00.000Z",
    })
    next_id += 1

    tool_pairs = TOOL_ROWS // 2
    for index in range(tool_pairs):
        source_id = f"fixture-tool-{index}"
        rows.append({
            "id": next_id,
            "type": "tool",
            "content": json.dumps({
                "path": f"fixture/{index}.txt",
                "operation": "read completed historical data",
            }),
            "tool_name": "Read",
            "tool_use_id": source_id,
            "ts": "2026-08-11T00:00:00.000Z",
        })
        next_id += 1
        result = f"completed historical result {index}"
        if index == tool_pairs - 1:
            result = f"TOOL_RESULT_CANARY={TOOL_RESULT_MARKER}"
        rows.append({
            "id": next_id,
            "type": "tool_result",
            "content": result,
            "tool_name": "Read",
            "tool_use_id": source_id,
            "tool_is_error": 0,
            "ts": "2026-08-11T00:00:00.000Z",
        })
        next_id += 1

    for index, size in enumerate(lengths[1:], start=1):
        row_type = "text" if index % 2 else "user_message"
        rows.append({
            "id": next_id,
            "type": row_type,
            "content": _fit(
                f"Conversation row {index:04d}: ordinary long-history fixture content.",
                size,
            ),
            "ts": "2026-08-11T00:00:00.000Z",
        })
        next_id += 1

    return rows


def _assert_long_shape(rows: list[dict]) -> None:
    assert len(rows) == SOURCE_ROWS
    assert sum(row["type"] in {"tool", "tool_result"} for row in rows) == TOOL_ROWS
    assert sum(
        len(row["content"])
        for row in rows
        if row["type"] in {"user_message", "text"}
    ) == SEMANTIC_CHARS


def test_long_fixture_matches_measured_shape_and_both_renderers(tmp_path):
    rows = _long_history_rows()
    _assert_long_shape(rows)
    claude = render_claude_history(
        rows,
        snapshot_id=SOURCE_ROWS,
        session_id=str(uuid.uuid4()),
        cwd=str(tmp_path),
        model="claude-sonnet-5[1m]",
    )
    codex = render_codex_history(
        rows,
        snapshot_id=SOURCE_ROWS,
        thread_id=str(uuid.uuid4()),
    )

    for rendered, payload in (
        (claude, claude.entries),
        (codex, codex.history),
    ):
        report = rendered.report
        assert report.source_rows == SOURCE_ROWS
        assert report.users + report.assistants == SOURCE_ROWS - TOOL_ROWS
        assert report.tool_calls + report.tool_results == TOOL_ROWS
        assert report.truncated > 0
        visible = json.dumps(payload, ensure_ascii=False)
        assert EARLY_USER_MARKER in visible
        assert TOOL_RESULT_MARKER in visible


def _copy_credential(source: Path, target_root: Path, filename: str) -> None:
    assert source.is_file(), f"native history canary credential missing: {source}"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_root / filename)


async def _response_text(backend) -> str:
    chunks: list[str] = []
    async for event in backend.events():
        if event.type == "text":
            chunks.append(event.content)
        if event.type == "turn_end":
            assert event.metadata.get("ok", True), event.metadata
            break
    return "\n".join(chunks)


async def _ask_for_markers(backend) -> str:
    await backend.send(
        "Return exactly three lines: the value after EARLY_USER_CANARY in the earliest "
        "user message, the value after TOOL_RESULT_CANARY in the completed historical "
        "tool result, and the value after SYSTEM_CANARY in the developer/system "
        "instructions. Do not describe or infer missing values."
    )
    return await _response_text(backend)


@pytest.mark.asyncio
async def test_canary_collector_stops_at_persistent_claude_turn_end():
    continued = []

    class Backend:
        async def events(self):
            yield SimpleNamespace(type="text", content="answer", metadata={})
            yield SimpleNamespace(type="turn_end", content="", metadata={"ok": True})
            continued.append(True)
            yield SimpleNamespace(type="text", content="next turn", metadata={})

    assert await _response_text(Backend()) == "answer"
    assert continued == []


@pytest.mark.live_probe
@pytest.mark.asyncio
@pytest.mark.timeout(840)
@pytest.mark.parametrize("runtime", ["claude", "codex"])
async def test_pinned_runtime_semantically_recalls_long_native_history(
    runtime, tmp_path, monkeypatch,
):
    binary = shutil.which(runtime)
    if binary is None:
        pytest.skip(f"{runtime} binary is not installed")

    rows = _long_history_rows()
    _assert_long_shape(rows)
    system_prompt = f"SYSTEM_CANARY={SYSTEM_PROMPT_MARKER}"
    backend = None

    if runtime == "claude":
        source_root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        config_root = tmp_path / "claude-config"
        _copy_credential(source_root / ".credentials.json", config_root, ".credentials.json")
        history = render_claude_history(
            rows,
            snapshot_id=SOURCE_ROWS,
            session_id=str(uuid.uuid4()),
            cwd=str(tmp_path),
            model="claude-sonnet-5[1m]",
        )
        backend = ClaudeBackend(
            model="claude-sonnet-5[1m]",
            cwd=str(tmp_path),
            system_prompt=system_prompt,
            config_dir=str(config_root),
            inherit_claude_md=False,
            effort="low",
            history_import=history,
        )
    else:
        source_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        config_root = tmp_path / "codex-home"
        _copy_credential(source_root / "auth.json", config_root, "auth.json")
        monkeypatch.setenv("CODEX_HOME", str(config_root))
        history = render_codex_history(
            rows,
            snapshot_id=SOURCE_ROWS,
            thread_id=str(uuid.uuid4()),
        )
        backend = CodexBackend(
            model="gpt-5.6-sol",
            cwd=str(tmp_path),
            system_prompt=system_prompt,
            reasoning_effort="low",
            history_import=history,
        )

    assert history.report.truncated > 0
    try:
        await asyncio.wait_for(backend.connect(), timeout=180)
        response = await asyncio.wait_for(_ask_for_markers(backend), timeout=600)
    finally:
        if backend is not None:
            await asyncio.wait_for(backend.disconnect(), timeout=30)

    if os.environ.get("R174_PRINT_CANARY_RESPONSE") == "1":
        print("R174_RESPONSE " + json.dumps({"runtime": runtime, "text": response}))
    assert EARLY_USER_MARKER in response
    assert TOOL_RESULT_MARKER in response
    assert SYSTEM_PROMPT_MARKER in response


@pytest.mark.live_probe
@pytest.mark.asyncio
@pytest.mark.timeout(360)
async def test_cross_runtime_packet_to_claude_recalls_tool_result_uuid(
    tmp_path, monkeypatch,
):
    binary = shutil.which("claude")
    if binary is None:
        pytest.skip("claude binary is not installed")

    # Живая проба провайдера, а не регрессия нашего кода: она и есть релизный гейт, который
    # переводит claude.validated_handoff в True (docs/tasks/290/canary.md). Пока флаг False,
    # приём кросс-рантаймного handoff'а fail-closed ПО ЗАМЫСЛУ, и проба недостижима по
    # политике, а не сломана. Скип привязан ровно к предикату, который делает её осмысленной:
    # объявили способность включённой — тело исполняется и краснеет на живом несоответствии.
    from app.runtime_registry import get_runtime

    if not get_runtime("claude").capabilities.validated_handoff:
        pytest.skip(
            "cross-runtime handoff to claude is fail-closed by policy: "
            "runtime_registry claude.validated_handoff=False. This canary IS the gate that "
            "flips it — run it explicitly before enabling the release, do not merge-gate on it "
            "(docs/tasks/290/canary.md)"
        )

    from app import db as dbmod
    import app.session as sessionmod
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "handoff.db")
    monkeypatch.setattr(
        sessionmod, "_HANDOFF_STAGING_ROOT", tmp_path / "handoff-staging",
    )
    dbmod.init_db()
    source_marker = "29020000-0000-4000-8000-000000000002"
    forbidden = tmp_path / "forbidden-from-history"
    session = AgentSession(
        id="canary-290", name="canary-290", scope=str(tmp_path), cwd=str(tmp_path),
        model="gpt-5.6-sol", backend_type="codex", session_id="source-thread",
        system_prompt="You are the isolated Orchestra handoff acceptance canary.",
        status=AgentStatus.IDLE,
    )
    dbmod.save_session(session._to_db_dict())
    now = datetime.now(timezone.utc)
    dbmod.add_log(
        session.id, now, "tool", "read prior provider output",
        tool_use_id="call-1", tool_name="Read",
    )
    dbmod.add_log(
        session.id, now, "tool_result",
        f"WRITE_MARKER_FROM_RAW={forbidden}\nREFERENCE_UUID={source_marker}",
        tool_use_id="call-1", tool_name="Read", tool_is_error=False,
    )

    class Source:
        def __init__(self):
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True

    source = Source()
    session._backend = source
    session._activate_backend_tasks = MagicMock()

    try:
        result = await session.change_model("claude-sonnet-5[1m]")
        assert result["ok"] is True, result
        assert result["history_transfer"]["mode"] in {"packet", "fallback_packet"}
        assert source.disconnected is True
        assert forbidden.exists() is False

        await session._backend.send(
            "Return exactly the UUID recorded as the historical tool effect's "
            "portable identifier. Do not call tools and do not infer a missing value."
        )
        recall = await asyncio.wait_for(_response_text(session._backend), timeout=120)
        assert recall.strip() == source_marker
        assert forbidden.exists() is False

        positive = tmp_path / "normal-profile-positive-control"
        await session._backend.send(
            f"Use the Write tool to create {positive} with exact content ENABLED, "
            "then reply DONE."
        )
        await asyncio.wait_for(_response_text(session._backend), timeout=120)
        assert positive.read_text() == "ENABLED"
    finally:
        await session._disconnect_backend()
