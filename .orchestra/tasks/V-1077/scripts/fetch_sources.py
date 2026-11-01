"""Capture public primary sources; never execute fetched code. Run separately from offline tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TASK = Path(__file__).resolve().parents[1]
OUT = TASK / "sources"
records = []


def fetch(label, url):
    record = {"file": label, "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat()}
    try:
        request = Request(url, headers={"User-Agent": "Orchestra-V1077-public-research"})
        with urlopen(request, timeout=35) as response:
            content = response.read()
            record.update(status=response.status, final_url=response.url,
                          content_type=response.headers.get("Content-Type"))
        (OUT / label).write_bytes(content)
        record.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
        print(f"OK {label}: {len(content)} bytes", flush=True)
        return content
    except (HTTPError, URLError, TimeoutError) as exc:
        record["error"] = str(exc)
        print(f"FAILED {label}: {exc}", flush=True)
        return None
    finally:
        records.append(record)
        (OUT / "retrieval.json").write_text(json.dumps(records, indent=2) + "\n")


for label, url in [
    ("anthropic-donation.html", "https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation"),
    ("aaif-announcement.html", "https://aaif.io/blog/agent-skills-sharing-team-expertise-across-ai-agents"),
    ("vercel-report.html", "https://vercel.com/blog/state-of-agent-skills"),
    ("telegram.html", "https://t.me/s/vibecoding_tg/4167"),
    ("live-specification.md", "https://agentskills.io/specification.md"),
    ("live-best-practices.md", "https://agentskills.io/skill-creation/best-practices.md"),
    ("live-evaluating-skills.md", "https://agentskills.io/skill-creation/evaluating-skills.md"),
    ("live-optimizing-descriptions.md", "https://agentskills.io/skill-creation/optimizing-descriptions.md"),
]:
    fetch(label, url)

for repo in ("agentskills/agentskills", "anthropics/skills"):
    prefix = repo.replace("/", "--")
    metadata = fetch(f"{prefix}-commit.json", f"https://api.github.com/repos/{repo}/commits/main")
    if not metadata:
        continue
    sha = json.loads(metadata)["sha"]
    tree_raw = fetch(f"{prefix}-tree.json", f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1")
    if not tree_raw:
        continue
    paths = [entry["path"] for entry in json.loads(tree_raw)["tree"] if entry["type"] == "blob"]
    wanted = [path for path in paths if path in ("README.md", "LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE")]
    if repo == "agentskills/agentskills":
        wanted += [path for path in paths if any(part in path for part in (
            "specification.mdx", "best-practices.mdx", "evaluating-skills.mdx", "optimizing-descriptions.mdx"))]
        wanted += [path for path in paths if "LICENSE" in path or path.endswith("validator.py")]
    else:
        wanted += [path for path in paths if path.startswith("skills/skill-creator/") and
                   (path.endswith(("SKILL.md", "schemas.md", "LICENSE.txt")))]
    for path in sorted(set(wanted)):
        fetch(f"{prefix}--{path.replace('/', '--')}", f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
