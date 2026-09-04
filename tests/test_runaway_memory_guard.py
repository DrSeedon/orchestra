"""Сторож памяти: один прожорливый процесс умирает, остальные живут.

Замер 04.09.2026: `awk` с вложенным квантификатором `([^|]*\\|){8}`, написанный
Luna в ходе `codex_review`, съел 7.9 ГБ на файле в 21 КБ. `MemoryHigh=8G` на юните
виновника НЕ убил — он зажал в своп ВЕСЬ cgroup, поэтому тормозила Orchestra
целиком (iowait 68.7%, load 26 на 12 ядрах), а не только нарушитель.

Швы:
  T1 — нарушитель убит, соседи не тронуты;
  T2 — одиночный всплеск не убивает: нужны ДВА подряд превышения;
  T3 — сам процесс Orchestra неприкосновенен, каким бы он ни был жирным.
"""

import pytest


@pytest.fixture
def guard(monkeypatch):
    from app import runaway_guard

    monkeypatch.setattr(runaway_guard, "_STRIKES", {})
    return runaway_guard


def _world(monkeypatch, guard, procs, killed):
    """procs: {pid: (rss_bytes, cmdline)}."""
    monkeypatch.setattr(guard, "_cgroup_pids", lambda: list(procs))
    monkeypatch.setattr(guard, "_rss_bytes", lambda pid: procs.get(pid, (0, ""))[0])
    monkeypatch.setattr(guard, "_cmdline", lambda pid: procs.get(pid, (0, ""))[1])
    monkeypatch.setattr(guard, "_kill", lambda pid: killed.append(pid))


def test_t1_runaway_is_killed_and_neighbours_are_untouched(guard, monkeypatch):
    """Бьём по одному процессу, а не по всему дереву."""
    killed = []
    procs = {
        841079: (7_900_000_000, "awk NR>=3 ... ane-by-region.md"),
        654375: (259_000_000, "/home/maxim/.local/bin/claude --output-format stream-json"),
        257790: (247_000_000, "python3 -u -m uvicorn app.main:app --fd 3"),
    }
    _world(monkeypatch, guard, procs, killed)
    logged = []
    monkeypatch.setattr(guard, "_report", lambda pid, rss, cmd: logged.append((pid, rss, cmd)))

    guard.sweep_once(limit_bytes=2_000_000_000, self_pid=257790)
    guard.sweep_once(limit_bytes=2_000_000_000, self_pid=257790)

    assert killed == [841079], f"убито не то: {killed}"
    assert logged and logged[0][0] == 841079, "нарушитель не назван в журнале"
    assert "awk" in logged[0][2], "журнал не показывает команду виновника"


def test_t2_single_spike_survives_two_strikes_are_required(guard, monkeypatch):
    """Разовый всплеск не повод убивать: тест-прогон или сборка законно жирные."""
    killed = []
    procs = {900001: (3_000_000_000, "uv run pytest -q")}
    _world(monkeypatch, guard, procs, killed)
    monkeypatch.setattr(guard, "_report", lambda *a: None)

    guard.sweep_once(limit_bytes=2_000_000_000, self_pid=1)
    assert killed == [], "убит с первого превышения, без подтверждения"

    procs[900001] = (500_000_000, "uv run pytest -q")  # схлопнулся сам
    guard.sweep_once(limit_bytes=2_000_000_000, self_pid=1)
    procs[900001] = (3_000_000_000, "uv run pytest -q")
    guard.sweep_once(limit_bytes=2_000_000_000, self_pid=1)

    assert killed == [], "счётчик превышений не обнуляется при возврате в норму"


def test_t3_orchestra_itself_is_never_killed(guard, monkeypatch):
    """Сторож не имеет права убить процесс, внутри которого сам живёт."""
    killed = []
    procs = {257790: (9_000_000_000, "python3 -u -m uvicorn app.main:app --fd 3")}
    _world(monkeypatch, guard, procs, killed)
    reported = []
    monkeypatch.setattr(guard, "_report", lambda pid, rss, cmd: reported.append(pid))

    for _ in range(5):
        guard.sweep_once(limit_bytes=2_000_000_000, self_pid=257790)

    assert killed == [], "сторож убил собственный процесс Orchestra"
