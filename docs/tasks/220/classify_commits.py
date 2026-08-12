#!/usr/bin/env python3
"""#220 F4: classify a month of main-branch commits into hot/warm/cold tiers.

Run from the repo root:
    git log main --since=2026-07-12 --pretty=format:'@@%H' --name-only > /tmp/c.txt
    python3 docs/tasks/220/classify_commits.py /tmp/c.txt

Tier definition (the criterion is "read from disk at use time" vs "frozen in process memory"):
  T1 hot   — reaches a LIVE agent with no restart and no reconnect
  T2 warm  — reaches on backend reconnect / next spawn; no server restart needed
  T3 cold  — needs a server restart today
Also reports a second unit (changed files) as a sensitivity check on the commit unit.
"""
import sys, collections

# Code that must run inside the per-session process in a split-process design (F8).
SUPERVISOR = {
    'app/session.py', 'app/session_turns.py', 'app/session_hibernate.py',
    'app/session_state.py', 'app/session_cost.py', 'app/backend_claude.py',
    'app/backend_codex.py', 'app/backend_grok.py', 'app/backend_opencode.py',
    'app/backend_protocol.py', 'app/backend_jsonrpc.py', 'app/tool_call_guard.py',
    'app/pidfd_exec.py', 'app/events.py',
}
ARTIFACT_ROOT = ('docs/tasks/', 'docs/archive/')
ARTIFACT_FILE = {'CHANGELOG.md', 'BUGS.md', 'TODO.md', 'README.md', 'CONTRIBUTING.md', 'LICENSE'}


def cat(f: str) -> str:
    if f.startswith('tests/'):
        return 'tests'
    if f.startswith(ARTIFACT_ROOT) or f in ARTIFACT_FILE:
        return 'artifact'
    # personal memory: re-read from disk on every prompt re-injection (prompting.py:81)
    if f.startswith('docs/workers/'):
        return 'T1-hot'
    if f.startswith('docs/'):
        return 'artifact'
    # manifest: lru_cache keyed on (mtime_ns, size) (pipeline.py:369-394); effort is
    # re-applied at every turn boundary (session.py:945 -> _apply_manifest_effort)
    if f.endswith('pipeline.yaml'):
        return 'T1-hot'
    # prompt markdown: ROLE_SYSTEM_PROMPT runs only at spawn / _load_from_db (F1)
    if f.startswith('pipelines/'):
        return 'T3-cold-prompt'
    # read by the CLI itself / mirrored to AGENTS.md at backend connect
    if f in ('CLAUDE.md', 'AGENTS.md'):
        return 'T2-warm'
    if f.startswith('app/static/') or f.startswith('app/templates/'):
        return 'T1-hot'
    if f == 'app/mcp_stdio.py':
        return 'T2-warm'
    # separate process, read from disk at launch
    if f == 'app/codex_review_artifact.py' or f.startswith('scripts/'):
        return 'T1-hot'
    if f in SUPERVISOR:
        return 'T3-cold-sup'
    return 'T3-cold-core'


def main(path: str) -> None:
    commits = []
    for block in open(path).read().split('@@')[1:]:
        lines = block.strip().split('\n')
        files = [x for x in lines[1:] if x.strip()]
        commits.append((lines[0], files))

    def eff(files):
        return {cat(f) for f in files} - {'artifact', 'tests'}

    beh = [(s, f) for s, f in commits if eff(f)]
    n = len(beh)
    cold = {'T3-cold-prompt', 'T3-cold-sup', 'T3-cold-core'}
    t1 = [c for c in beh if eff(c[1]) <= {'T1-hot'}]
    t2 = [c for c in beh if eff(c[1]) <= {'T1-hot', 'T2-warm'} and 'T2-warm' in eff(c[1])]
    t3 = [c for c in beh if eff(c[1]) & cold]
    print(f"commits total {len(commits)}, behaviour-changing {n}")
    print(f"  T1 hot  {len(t1):3d}  {len(t1)/n*100:5.1f}%")
    print(f"  T2 warm {len(t2):3d}  {len(t2)/n*100:5.1f}%")
    print(f"  T3 cold {len(t3):3d}  {len(t3)/n*100:5.1f}%")
    comp = collections.Counter(k for _, f in t3 for k in eff(f) if k in cold)
    print(f"  T3 composition: {dict(comp)}")
    only_prompt = [c for c in t3 if eff(c[1]) & cold == {'T3-cold-prompt'}]
    print(f"  cold ONLY because of stale prompt markdown: {len(only_prompt)} "
          f"({len(only_prompt)/n*100:.1f}% of behaviour commits)")
    sup = [c for c in t3 if 'T3-cold-sup' in eff(c[1])]
    core_only = [c for c in t3 if 'T3-cold-sup' not in eff(c[1])]
    print(f"  F8 split-process: core-only {len(core_only)} ({len(core_only)/n*100:.1f}%), "
          f"supervisor-touching {len(sup)} ({len(sup)/n*100:.1f}%)")

    # sensitivity check: same tiers, counted per changed file instead of per commit
    fc = collections.Counter(cat(f) for _, files in commits for f in files)
    tot = sum(v for k, v in fc.items() if k not in ('artifact', 'tests'))
    hot = fc['T1-hot']; warm = fc['T2-warm']; cld = sum(fc[k] for k in cold)
    print(f"\nsensitivity, unit = changed file (n={tot}): "
          f"T1 {hot/tot*100:.1f}%  T2 {warm/tot*100:.1f}%  T3 {cld/tot*100:.1f}%"
          f"  | cold-prompt-only share {fc['T3-cold-prompt']/tot*100:.1f}%")


if __name__ == '__main__':
    main(sys.argv[1])
