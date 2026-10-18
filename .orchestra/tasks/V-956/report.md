# V-956 — mandatory verdicts for change-effect KB entries

Change: one paragraph in `.orchestra/pipelines/default/prompts/modules/knowledge.md`, placed right after the sentence "There is no required card, status vocabulary…", whose ban it narrows rather than contradicts. Scope is limited to entries about the effect of a change (prompt, rule, mechanism, model route); all other findings keep the free format, and "no new finding means no memory entry" is untouched. No automatic experience→rules loop was added (owner rejected it).

Source of the idea: V-954 report §1 and §3 (Harness² `prompts.py::experience`: per-edit verdict `helped/hurt/no observed effect/confounded`, one `cue/lesson/evidence/confidence` entry or none when there is no execution contrast).

Wording note: the reason cites V-954 §1 ("Замеры", "Важный контроль"): in the Harness² paper (arXiv 2610.14224) a direct edit of the base harness without executions and without the library lowered the result (Code 73.4→63.2, Web 69.9→65.0). The paragraph states the direction, not the numbers. An earlier draft omitted this claim because I had not found it in the report; the orchestrator pointed to the passage.

Delivery: `knowledge` reaches every role (it is in orchestrator, sub-orchestrator, worker, full-cycle, reducer module lists), checked by building each role's prompt. Prompt-assembly tests pass. No wording tests added. No restart needed; new sessions pick it up on prompt build.
