from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[4]
PATTERNS = (
    "payment_receive",
    "payment_status",
    "/api/tm/payments",
    "tm_yougile",
    "tm_import_yougile",
    "mcp__yougile__",
    "/api/proxy/",
    "/api/tunnel/",
    "start_tunnel",
    "stop_tunnel",
    "proxy_manager",
)


def main() -> None:
    roots = (ROOT / "app", ROOT / "pipelines/default/prompts", ROOT / "tests")
    hits = []
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".js", ".html", ".md", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in PATTERNS:
                if re.search(re.escape(pattern), text):
                    hits.append(f"{path.relative_to(ROOT)}: {pattern}")
    assert not hits, "live surface leftovers:\n" + "\n".join(hits)


if __name__ == "__main__":
    main()
