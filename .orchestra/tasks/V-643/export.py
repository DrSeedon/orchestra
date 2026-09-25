"""V-643: перенос результатов из data/v643 (gitignored) в results/ с фильтром секретов ПО ФОРМЕ.

Сырые журналы и песочницы не переносятся. Телефоны и почты тоже маскируются: папка задачи
может уехать в публичный origin, а сводки живых сессий содержат личные контакты.
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from app.secret_mask import mask_secrets  # noqa: E402

SRC = ROOT / "data" / "v643"
DST = HERE / "results"
FORMS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"),          # telegram bot token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),  # JWT
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\b(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S{6,}"),
    re.compile(r"\+7[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"),   # телефон
    re.compile(r"\b8[\s\-(]*9\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),        # почта
]
KEEP = {"summary.md", "answers.json", "judge.json", "compress.json", "questions.json"}


def clean(text):
    text = mask_secrets(text)
    hits = 0
    for rx in FORMS:
        text, n = rx.subn("[masked]", text)
        hits += n
    return text, hits


def main():
    if DST.exists():
        shutil.rmtree(DST / "runs", ignore_errors=True)
        shutil.rmtree(DST / "eval", ignore_errors=True)
    total = 0
    for sub in ("runs", "eval"):
        for f in (SRC / sub).rglob("*"):
            if f.name not in KEEP or "sandbox" in f.parts:
                continue
            rel = f.relative_to(SRC)
            out = DST / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            text, hits = clean(f.read_text())
            total += hits
            out.write_text(text)
    ledger, hits = clean((SRC / "ledger.jsonl").read_text())
    (DST / "ledger.jsonl").write_text(ledger)
    print("masked", total + hits)


if __name__ == "__main__":
    main()
