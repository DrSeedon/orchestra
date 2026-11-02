"""Offline JavaScript behavior of the compaction indicator; a missing Node is a failure."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compaction_indicator_and_stop_confirmation():
    node = shutil.which("node")
    assert node, "Node.js is required to run the offline compaction UI regression"
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs"))],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: compaction indicator and confirmations" in result.stdout
    assert "PASS: SSE forwards compaction state" in result.stdout
    assert "PASS: session poll applies compaction state" in result.stdout
    assert "PASS: agent switch clears compaction state" in result.stdout


def test_russian_texts_and_indicator_slot_exist():
    i18n = (ROOT / "app/static/js/i18n.js").read_text(encoding="utf-8")
    assert "'Codex сжимает контекст · прошло {seconds} с · обычно 1–4 мин'" in i18n
    assert (
        "'Codex сейчас сжимает контекст (обычно 1–4 минуты). Если остановить, сжатие "
        "начнётся заново. Остановить всё равно?'"
    ) in i18n
    template = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="compaction-indicator"' in template
