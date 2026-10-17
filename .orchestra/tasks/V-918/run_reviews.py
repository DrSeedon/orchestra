"""V-918: offline Luna review of commit diffs. One pass per diff, danger-full-access in a throwaway history-free snapshot (read-only bwrap is unusable on this host: KB models-and-quotas V-813); dirty_after records any edit, no history in the checkout.
Prompt text is copied from the frozen `implementation` branch of codex_review (app/mcp_stdio.py ~4210..4250) and
_REVIEW_RUBRIC (app/mcp_stdio.py:3576). Usage: python -I run_reviews.py <repo> <sample.json> <outdir> <conc> [ids...]
"""
import json, os, shutil, subprocess, sys, tempfile, time, tomllib
from concurrent.futures import ThreadPoolExecutor

repo, sample_f, outdir, conc = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3]), int(sys.argv[4])
only = set(sys.argv[5:])
MODEL = "gpt-6-luna"
RUBRIC = ("Review calibration: blocking = crash/corrupt/security; "
          "suggestion = real improvement; nit = skip.")
LABELS = (("scale", "Scale"), ("users", "Users"), ("stack", "Stack"), ("philosophy", "Philosophy"),
          ("what_matters", "What matters"), ("what_does_not_matter", "What does NOT matter"))
ctx = tomllib.loads(subprocess.run(["git", "-C", repo, "show", "main:.orchestra/project-context.toml"],
                                   capture_output=True, text=True, check=True).stdout)
fields = "\n".join(f"- {l}: {ctx[k]}" for k, l in LABELS)
foundation = ("PROJECT CONTEXT (tool-owned; calibrate review severity):\n" + fields)

def sh(*a, cwd=None, inp=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, check=True, input=inp)

def snapshot(dest, rev):
    for n in os.listdir(dest):
        if n != ".git":
            p = os.path.join(dest, n)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
    tar = subprocess.Popen(["git", "-C", repo, "archive", rev], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", dest, "--exclude=.orchestra/tasks", "--exclude=.orchestra/kb", "--exclude=.orchestra/workers", "--exclude=.orchestra/archive"], stdin=tar.stdout, check=True)
    tar.wait()

def one(it):
    rid = it["id"]
    res = os.path.join(outdir, rid)
    if os.path.exists(res + ".meta.json"):
        return
    subject = sh("git", "-C", repo, "show", "-s", "--format=%s", it["sha"]).stdout.decode().strip()
    work = tempfile.mkdtemp(prefix=f"v918-{rid}-", dir="/home/kesha/v918-work")
    try:
        sh("git", "init", "-q", cwd=work)
        sh("git", "config", "user.email", "r@x", cwd=work); sh("git", "config", "user.name", "r", cwd=work)
        snapshot(work, it["sha"] + "^1")
        sh("git", "add", "-A", cwd=work); sh("git", "commit", "-qm", "base", "--allow-empty", cwd=work)
        base = sh("git", "rev-parse", "HEAD", cwd=work).stdout.decode().strip()
        snapshot(work, it["sha"])
        sh("git", "add", "-A", cwd=work); sh("git", "commit", "-qm", "change", "--allow-empty", cwd=work)
        head = sh("git", "rev-parse", "HEAD", cwd=work).stdout.decode().strip()
        diff = sh("git", "diff", "--binary", "--full-index", base, head, cwd=work).stdout
        open(res + ".diff", "wb").write(diff)
        cmd = f"git diff --binary --full-index {base}...{head}"
        prompt = "\n".join([
            foundation + "\n\nCALLER-SUPPLIED TASK CALIBRATION:\n" + f"Task: {subject}\n"
            + "END CALLER-SUPPLIED TASK CALIBRATION\n\n" + RUBRIC,
            "Review the exact committed implementation snapshot pinned by the server.",
            f"Run `{cmd}` and review that complete diff; do not substitute HEAD or a task file.",
            "Return the complete review in your final response. Do not edit files.",
            "Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict. Start Verdict with APPROVED, NEEDS WORK, or INCOMPLETE. "
            "Use INCOMPLETE if you could not finish the requested review; preserve partial findings.",
        ])
        open(res + ".prompt.txt", "w").write(prompt)
        t0 = time.time()
        p = subprocess.run(
            ["codex", "-m", MODEL, "-s", "danger-full-access", "-a", "never", "exec", "--skip-git-repo-check", "--json",
             "-o", res + ".review.md", "-"],
            cwd=work, input=prompt.encode(), capture_output=True, timeout=1500)
        dt = time.time() - t0
        dirty = sh('git', 'status', '--porcelain', cwd=work).stdout.decode().strip()
        open(res + ".jsonl", "wb").write(p.stdout)
        usage = {}
        for line in p.stdout.decode(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "turn.completed":
                for k, v in (e.get("usage") or {}).items():
                    usage[k] = usage.get(k, 0) + v
        json.dump(dict(id=rid, sha=it["sha"], rc=p.returncode, seconds=round(dt, 1), usage=usage,
                       diff_bytes=len(diff), dirty_after=dirty, stderr=p.stderr.decode(errors="replace")[-500:]),
                  open(res + ".meta.json", "w"))
        print(rid, p.returncode, round(dt), usage, flush=True)
    except Exception as e:
        print("FAIL", rid, repr(e)[:300], flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

REPS = int(os.environ.get('REPS','2'))
items = [dict(i, id=f"{i['id']}.r{r}") for r in range(REPS) for i in json.load(open(sample_f))["items"]]
items = [i for i in items if not only or i["id"] in only]
os.makedirs(outdir, exist_ok=True); os.makedirs("/home/kesha/v918-work", exist_ok=True)
with ThreadPoolExecutor(conc) as ex:
    list(ex.map(one, items))
