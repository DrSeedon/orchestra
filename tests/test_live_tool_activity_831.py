"""V-831: what the model is generating is visible while it is generated.

A tool call that takes the model minutes to write (a 42 KB Bash heredoc) used to show
nothing until the call was complete. Live partials (tool-call arguments, thinking, shell
task output) now travel through the in-memory broker only; the DB keeps the final rows.
"""
import asyncio
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.events import AgentEvent
from app.live_broker import LiveBroker, coalesce
from app import task_output_tail

LIVE_JS = Path(__file__).parent.parent / "app/static/js/live-activity.js"


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("app.db.get_recent_chat_logs", MagicMock(return_value=[]))
    monkeypatch.setattr("app.session.save_session", MagicMock())
    add_log = MagicMock(return_value=1)
    monkeypatch.setattr("app.session.add_log", add_log)
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    from app.session import AgentSession
    s = AgentSession(id="live-831", name="w1", scope="/test", cwd="/tmp",
                     model="claude-sonnet-5-5[1m]", system_prompt="test",
                     created_at=datetime.now(timezone.utc))
    s._add_log_mock = add_log
    return s


@pytest.fixture
def published(monkeypatch):
    from app.live_broker import broker
    out = []
    monkeypatch.setattr(broker, "publish", lambda sid, payload: out.append(payload))
    return out


@pytest.fixture
def live_broker(monkeypatch):
    from app import live_broker as live_broker_module

    broker = LiveBroker()
    monkeypatch.setattr(live_broker_module, "broker", broker)
    return broker


# ── session: partials go to the broker, never to the DB ──

def test_tool_arguments_and_thinking_are_brokered_not_persisted(session, published):
    session._log = MagicMock()
    session._submit_db_write = MagicMock()
    meta = {"tool_use_id": "toolu_A", "tool_name": "Bash", "short_name": "Bash"}

    session._handle_event(AgentEvent("tool_input_stream", "", meta))
    session._handle_event(AgentEvent("tool_input_stream", '{"command": "ech', meta))
    session._handle_event(AgentEvent("thinking_stream", "let me think",
                                     {"activity": "reasoning", "item_id": "claude-thinking-1"}))

    assert [(p["type"], p["content"]) for p in published] == [
        ("tool_input_stream", ""), ("tool_input_stream", '{"command": "ech'),
        ("thinking_stream", "let me think")]
    assert published[1]["tool_use_id"] == "toolu_A" and published[1]["tool_name"] == "Bash"
    session._log.assert_not_called()
    session._submit_db_write.assert_not_called()


def test_subagent_partials_nest_under_their_subagent(session, published):
    session._log = MagicMock()
    session._handle_event(AgentEvent("tool_input_stream", '{"file_path"', {
        "tool_use_id": "toolu_S", "tool_name": "Read", "short_name": "Read", "subagent_id": "task-1"}))

    assert published == [{"type": "subagent_stream", "event_type": "tool_input_stream",
                          "content": '{"file_path"', "subagent_id": "task-1",
                          "item_id": "toolu_S", "tool_name": "Read"}]
    session._log.assert_not_called()


@pytest.mark.asyncio
async def test_final_tool_call_is_persisted_and_retires_the_live_replay(session, live_broker):
    session._handle_event(AgentEvent("tool_input_stream", '{"command": "ls"}',
                                     {"tool_use_id": "toolu_F", "tool_name": "Bash"}))
    assert ("tool_input_stream", "toolu_F") in live_broker._live.get(session.id, {})

    session._handle_event(AgentEvent("tool_use", 'Bash: {"command": "ls"}',
                                     {"tool_use_id": "toolu_F", "tool_name": "Bash"}))

    assert ("tool_input_stream", "toolu_F") not in live_broker._live.get(session.id, {})
    for _ in range(100):  # the log write runs on the DB executor
        if session._add_log_mock.called:
            break
        await asyncio.sleep(0.01)
    logged = [c.args for c in session._add_log_mock.call_args_list]
    assert [args[2] for args in logged] == ["tool"], logged


# ── broker: late subscribers see the block being written ──

@pytest.mark.asyncio
async def test_late_subscriber_gets_replay_with_progress():
    b = LiveBroker()
    b.publish("s", {"type": "tool_input_stream", "content": '{"a":', "tool_use_id": "t1"})
    live = b.subscribe("s")
    assert live.get_nowait()["chars"] == 5  # its own replay
    b.publish("s", {"type": "tool_input_stream", "content": '"b"}', "tool_use_id": "t1"})

    late = b.subscribe("s")
    replay = late.get_nowait()
    assert replay["replace"] is True
    assert replay["content"] == '{"a":"b"}' and replay["chars"] == 9
    assert replay["elapsed_ms"] >= 0 and not any(k.startswith("_") for k in replay)
    # Live subscribers get per-delta payloads with the running total.
    assert live.get_nowait()["chars"] == 9


@pytest.mark.asyncio
async def test_replay_keeps_only_tail_but_counts_everything():
    b = LiveBroker()
    for _ in range(100):
        b.publish("s", {"type": "tool_input_stream", "content": "x" * 1000, "tool_use_id": "t1"})
    replay = b.subscribe("s").get_nowait()
    assert replay["chars"] == 100_000
    assert len(replay["content"]) == 64 * 1024


@pytest.mark.asyncio
async def test_end_and_clear_live_and_waiting_is_not_replayed():
    b = LiveBroker()
    b.publish("s", {"type": "thinking_stream", "content": "a", "item_id": "r1"})
    b.publish("s", {"type": "thinking_stream", "content": "b", "item_id": "r2"})
    b.publish("s", {"type": "thinking_stream", "content": "still", "activity": "waiting", "item_id": "x"})
    b.publish("s", {"type": "tool_stream", "content": "out", "tool_use_id": "t1"})
    b.publish("s", {"type": "tool_stream", "content": "out2", "tool_use_id": "t2"})

    b.end_live("s", "thinking_stream")
    b.end_live("s", "tool_stream", "t1")
    assert set(b._live["s"]) == {("tool_stream", "t2")}
    b.clear_live("s")
    assert "s" not in b._live
    assert b.subscribe("s").empty()


# ── SSE coalescing ──

def test_coalesce_glues_neighbours_of_one_block_only():
    batch = [
        {"type": "tool_input_stream", "content": "a", "tool_use_id": "t1", "chars": 1},
        {"type": "tool_input_stream", "content": "b", "tool_use_id": "t1", "chars": 2},
        {"type": "tool_input_stream", "content": "c", "tool_use_id": "t2", "chars": 1},
        {"type": "stream", "content": "x"},
        {"type": "stream", "content": "y"},
        {"type": "tool_input_stream", "content": "d", "tool_use_id": "t1", "chars": 3},
        {"type": "status", "content": "s1"},
        {"type": "status", "content": "s2"},
    ]
    out = coalesce(batch)
    assert [(p["type"], p["content"]) for p in out] == [
        ("tool_input_stream", "ab"), ("tool_input_stream", "c"), ("stream", "xy"),
        ("tool_input_stream", "d"), ("status", "s1"), ("status", "s2")]
    assert out[0]["chars"] == 2  # latest progress wins
    assert "".join(p["content"] for p in out) == "".join(p["content"] for p in batch)


def test_coalesce_keeps_replace_and_never_merges_waiting_or_a_new_replace():
    out = coalesce([
        {"type": "thinking_stream", "content": "AB", "item_id": "r", "replace": True},
        {"type": "thinking_stream", "content": "C", "item_id": "r"},
        {"type": "thinking_stream", "content": "AB", "item_id": "r", "replace": True},
        {"type": "thinking_stream", "content": "w1", "activity": "waiting", "item_id": "x"},
        {"type": "thinking_stream", "content": "w2", "activity": "waiting", "item_id": "x"},
    ])
    assert [(p["content"], p.get("replace")) for p in out] == [
        ("ABC", True), ("AB", True), ("w1", None), ("w2", None)]


# ── shell task output tail ──

@pytest.mark.asyncio
async def test_tail_publishes_appended_output_until_file_disappears(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    monkeypatch.setattr(task_output_tail, "MISSING_GRACE", 0.05)
    tasks = tmp_path / f"claude-{os.getuid()}" / "-home-proj" / "sdk-1" / "tasks"
    tasks.mkdir(parents=True)
    output = tasks / "b1abc.output"
    output.write_bytes("first ".encode())
    got = []

    runner = asyncio.create_task(task_output_tail.tail_task_output(
        got.append, "b1abc", "toolu_B", "sdk-1", poll=0.01))
    await asyncio.sleep(0.05)
    data = "ü line\n".encode()
    with output.open("ab") as handle:
        handle.write(data[:1])     # split a multi-byte character across two polls
        handle.flush()
        await asyncio.sleep(0.05)
        handle.write(data[1:])
    await asyncio.sleep(0.05)
    output.unlink()
    await asyncio.wait_for(runner, 2)

    assert "".join(p["content"] for p in got) == "first ü line\n"
    assert all(p["type"] == "tool_stream" and p["tool_use_id"] == "toolu_B"
               and p["subagent_id"] == "b1abc" for p in got)


def test_output_file_lookup_rejects_path_tricks(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    tasks = tmp_path / f"claude-{os.getuid()}" / "slug" / "sdk-1" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "ok1.output").write_text("x")
    assert task_output_tail.find_output_file("ok1", "sdk-1") == tasks / "ok1.output"
    # Session id unknown or different → still found by task id.
    assert task_output_tail.find_output_file("ok1", "other") == tasks / "ok1.output"
    assert task_output_tail.find_output_file("../ok1", "sdk-1") is None
    assert task_output_tail.find_output_file("*", "sdk-1") is None


@pytest.mark.asyncio
async def test_session_tails_only_shell_tasks_and_stops_on_end(session, monkeypatch):
    started = []

    async def fake_tail(publish, task_id, tool_use_id, sdk_session_id="", poll=1.0):
        started.append((task_id, tool_use_id, sdk_session_id))
        await asyncio.sleep(3600)

    monkeypatch.setattr(task_output_tail, "tail_task_output", fake_tail)
    session._log = MagicMock()
    session._handle_event(AgentEvent("subagent_start", "agent", {
        "subagent_id": "a1", "task_type": "local_agent", "tool_use_id": "toolu_x"}))
    session._handle_event(AgentEvent("subagent_start", "bash", {
        "subagent_id": "b1", "task_type": "local_bash", "tool_use_id": "toolu_b",
        "sdk_session_id": "sdk-1"}))
    await asyncio.sleep(0)

    assert started == [("b1", "toolu_b", "sdk-1")]
    task = session._output_tails._tasks["b1"]
    session._handle_event(AgentEvent("subagent_end", "bash", {
        "subagent_id": "b1", "task_type": "local_bash", "tool_use_id": "toolu_b"}))
    await asyncio.sleep(0)
    assert task.cancelled() and session._output_tails.active() == set()


# ── frontend argument decoder (pure JS, run in node) ──

def _node(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    code = (f"const vm=require('vm');const ctx={{T:(s,p)=>s.replace(/\\{{(\\w+)\\}}/g,(_,k)=>p[k])}};"
            f"vm.createContext(ctx);vm.runInContext(require('fs').readFileSync({json.dumps(str(LIVE_JS))},'utf8')"
            f"+';this.D=LiveArgsDecoder;this.timeout=liveToolTimeoutMs;this.label=liveRunLabel;',ctx);"
            f"const D=ctx.D;{script}")
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def test_decoder_shows_readable_arguments_for_any_chunking():
    args = {"command": "python3 - <<'EOF'\nprint(\"\\t\u00fc \U0001F600\")\nEOF",
            "description": "Run it", "timeout": 600000}
    raw = json.dumps(args)  # ASCII-escaped: \n, \", \u00fc and a surrogate pair
    out = _node(f"""const raw={json.dumps(raw)};const res=[];
        for (const step of [1,2,5,13,raw.length]) {{
            const d=new D(); for (let i=0;i<raw.length;i+=step) d.feed(raw.slice(i,i+step)); res.push(d.text);
        }}
        console.log(JSON.stringify(res));""")
    expected = (f"command: {args['command']}\ndescription: Run it\ntimeout: 600000")
    assert out == [expected] * 5


def test_decoder_tail_mode_and_timeouts_and_label():
    out = _node("""const d=new D(); d.feedTail('ine 2\\\\nline 3\\\\"x\\\\"'); d.feed('\\\\nmore');
        console.log(JSON.stringify([d.text,
            ctx.timeout('Bash',{command:'x'}), ctx.timeout('Bash',{timeout:900000}),
            ctx.timeout('Bash',{timeout:30000}), ctx.timeout('Bash',{run_in_background:true}),
            ctx.timeout('Read',{file_path:'x'}),
            ctx.label(83000,600000), ctx.label(5000,0)]));""")
    assert out == ['ine 2\nline 3"x"\nmore', 120000, 600000, 30000, 0, 0,
                   "⏳ running 1:23 of 10:00", "⏳ running 0:05"]


def test_background_task_clock_survives_being_built_before_insertion():
    """The card is built detached and inserted afterwards; the old first tick saw
    isConnected=false and removed the clock at birth, so no task ever showed one."""
    chat_js = (Path(__file__).parent.parent / "app/static/js/chat.js").read_text(encoding="utf-8")
    start = chat_js.index("const _SA_CLOCK_TICK_MS")
    end = chat_js.index("function _renderSubagentLifecycleEntry")
    out = _node(f"""
        const src = {json.dumps(chat_js[start:end])};
        const intervals = [];
        const env = {{T: ctx.T, liveRunLabel: ctx.label, document: {{querySelector: () => null}},
                      CSS: {{escape: s => s}}, setInterval: f => (intervals.push(f), intervals.length),
                      clearInterval: () => {{}}, Date}};
        function el() {{
            const node = {{children: [], dataset: {{}}, style: {{}}, isConnected: false, textContent: '',
                appendChild(c) {{ this.children.push(c); c.parent = this; return c; }},
                querySelector(sel) {{ const f = n => n.children.find(c => c.className === 'sa-clock') ||
                    n.children.map(f).find(Boolean); return f(this) || null; }},
                get firstElementChild() {{ return this.children[0] || null; }}}};
            return node;
        }}
        env.document.createElement = () => {{ const n = el(); n.remove = function () {{
            const p = this.parent; p.children.splice(p.children.indexOf(this), 1); }}; return n; }};
        vm.createContext(env);
        vm.runInContext(src + ';this.start=_startSubagentClock;', env);
        const card = el(); card.appendChild(el());           // header
        env.start(card, new Date(Date.now() - 65000).toISOString());
        const before = !!card.querySelector('.sa-clock');
        card.isConnected = true; intervals[0]();
        const text = card.querySelector('.sa-clock')?.textContent || '';
        card.isConnected = false; intervals[0]();
        console.log(JSON.stringify([before, text, !!card.querySelector('.sa-clock')]));""")
    assert out[0] is True and "1:0" in out[1] and out[2] is False


def test_agent_cli_streams_tool_arguments_finely():
    """Without the flag the CLI (DISABLE_TELEMETRY → remote flag default off) streams tool
    arguments per JSON value: measured 3 451 chars after 12.7 s silence vs ~14 chars/50 ms
    with it (.orchestra/tasks/V-831/stream-timing)."""
    from app.backend_claude import ClaudeBackend
    options = ClaudeBackend(model="claude-opus-5-5[1m]", cwd="/tmp")._make_client().options
    assert options.include_partial_messages is True
    assert options.env["CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING"] == "1"


def test_pacer_spreads_a_burst_over_the_observed_gap():
    out = _node("""const P = (vm.runInContext('LivePacer', ctx));
        const p = new P(); const seen = [];
        let now = 0;
        p.push(190, now);                       // first burst
        for (; now < 600; now += 16) seen.push(p.step(now));
        p.push(380, 600);                       // next burst 600 ms later
        for (; now < 1300; now += 16) seen.push(p.step(now));
        const jumps = seen.slice(1).map((v, i) => v - seen[i]);
        console.log(JSON.stringify([seen[seen.length - 1], Math.max(...jumps), seen.filter(v => v > 0).length]));""")
    final, biggest_jump, frames_with_text = out
    assert final == 380
    # Never more than a few dozen chars per frame: a 190-char burst is not painted at once.
    assert biggest_jump <= 30
    assert frames_with_text > 40
