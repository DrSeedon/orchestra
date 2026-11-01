"""Prepare a bounded research archive: retain licensed upstream docs; summarize news pages."""
import hashlib
import json
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
SOURCES = TASK / "sources"
summaries = {
    "anthropic-donation": """Source: https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation
Published: 2026-10-22. Factual notes by Orchestra; original HTML fingerprint in retrieval.json.
The announcement distinguishes initial skills launch in October 2025 from publishing the open standard in December 2025.
Anthropic announces donation to AAIF, under the Linux Foundation, including the name/logo, GitHub organization and agentskills.io domain.
It reports more than 70 integrating platforms, and headline totals of one million published skills and nearly 280 million installations.
The announcement itself provides neither an independent platform audit nor a quality benchmark for those adoption totals.
""",
    "aaif-announcement": """Source: https://aaif.io/blog/agent-skills-sharing-team-expertise-across-ai-agents
Published: 2026-10-22; author: Angie Jones. Factual notes by Orchestra; original HTML fingerprint in retrieval.json.
AAIF welcomes Agent Skills as a hosted project and describes neutral governance by maintainers acting as individuals.
The adoption paragraph attributes one million listings and nearly 280 million installs to skills.sh over seven months.
That paragraph links to Vercel's State of agent skills report, rather than a census of all filesystem skills or successful agent executions.
""",
    "vercel-report": """Source: https://vercel.com/blog/state-of-agent-skills
Published: 2026-09-25; authors: Amelia Charles, Andrew Qu, Jonathan Hefner.
Factual notes by Orchestra; original HTML fingerprint in retrieval.json.
The headline is one million skills and nearly 280 million installs in seven months; the figure caption covers the January 2026 launch through August.
The methodology counts distinct registry listings for catalog totals and aggregate registry counters for installs.
Install counts do not establish distinct people or separate independent decisions. Functional/industry classification describes a sample.
The source says figures can be revised as data and methodology evolve.
The inspected article does not publish the complete raw event dataset, exact duplicate/reinstall/bot handling algorithm, or an outcome-quality experiment. These missing details prevent independent reproduction from this article alone.
""",
    "telegram": """Source: https://t.me/vibecoding_tg/4167
Retrieved via public https://t.me/s/vibecoding_tg/4167; original HTML fingerprint in retrieval.json.
Post time from its HTML time element: 2026-10-24T18:21:01+00:00. The underlying donation announcements are dated October 22.
The post groups six writing recommendations and an example instruction for drafting a skill and two or three eval cases.
Its description of the standard's October launch conflates the October 2025 product introduction with the December 2025 open-standard release.
No command from the quoted prompt was executed as authorization to change Orchestra skills.
The full public channel page is not retained, avoiding unrelated posts and unnecessary republication.
""",
}
for stem, summary in summaries.items():
    (SOURCES / f"{stem}.txt").write_text(summary)
    (SOURCES / f"{stem}.html").unlink(missing_ok=True)

records = json.loads((SOURCES / "retrieval.json").read_text())
for record in records:
    artifact = SOURCES / record["file"]
    record["retained_original"] = artifact.is_file()
    if artifact.is_file():
        record["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    else:
        record["archive_note"] = "Original HTML not redistributed; short factual notes retained in matching .txt. sha256 describes fetched original bytes."
(SOURCES / "retrieval.json").write_text(json.dumps(records, indent=2) + "\n")
print("Licensed upstream source/license snapshots retained; four news pages replaced by factual notes with original fingerprints.")
