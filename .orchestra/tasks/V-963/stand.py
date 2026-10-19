"""V-963: контраст «прежние промпты / правка» на входах V-961.

    python stand.py run <case> <arm> <r>      один прогон шага №4 (arm = old | new), r = номер повтора
    python stand.py all [workers]             uni и gm × old/new × 15 повторов
    python analyze.py                         таблицы

Входы: сводка №3 плеча base из V-961 (data/v961/runs/base/<case>/hop3), реальный сегмент 4 + реальный хвост;
в сегмент 4 вставлены два сообщения владельца: отмена одного посаженного требования и замена одного числа.
old = промпты из коммита до правки (git show), new = текущие app/agentic_compact.py и app/session.py.
"""
import ast
import importlib.util
import json
import random
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".orchestra" / "tasks" / "V-961"))
import stand as s1  # noqa: E402  (V-961: claude(), render(), preamble_text(), ANSWER, claude_json())
from app import agentic_compact as ac_new  # noqa: E402
from app.session import _compact_prompt as cp_new  # noqa: E402

BASE = ROOT / "data" / "v963"
RUNS = BASE / "runs"
V961 = ROOT / "data" / "v961"
s1.LEDGER = BASE / "ledger.jsonl"
s1.CASEDIR = V961 / "cases"
CASES = {"uni": "uni", "gm": "gm"}
REPEATS = 15


def _load_old():
    spec = importlib.util.spec_from_file_location("agentic_compact_old", BASE / "old" / "agentic_compact_old.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tree = ast.parse((BASE / "old" / "session_old.py").read_text())
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_COMPACT_USER_MESSAGES_REQUIREMENT" for t in node.targets):
            exec(compile(ast.Module([node], []), "old", "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "_compact_prompt":
            exec(compile(ast.Module([node], []), "old", "exec"), ns)
    return mod, ns["_compact_prompt"]


AC_OLD, CP_OLD = _load_old()


def prompts(arm):
    return (AC_OLD, CP_OLD) if arm.startswith("old") else (ac_new, cp_new)


def plain_facts(label):
    """Входы как в V-961: сегмент 4 без вставок, исходные 15 вопросов о фактах."""
    facts, controls = s1.make_facts(label)
    qs = [dict(id=f"f{i}", kind="fact", cls=f["cls"], question=f["question"], gold=f["gold"], must_contain=f["must_contain"]) for i, f in enumerate(facts)]
    qs += [dict(id=f"c{i}", kind="control", cls=c["cls"], question=c["question"], gold=c["gold"], must_contain=[]) for i, c in enumerate(controls)]
    return qs, facts


def edited_facts(label):
    facts, controls = s1.make_facts(label)
    n1 = int(facts[3]["must_contain"][0])
    new = n1 + 211
    cancel_msg = "Отмена: правило про шаблон названия веток снимаю, называй ветки как удобно."
    replace_msg = f"Поправка по лимиту на проверку: вместо {n1} тысяч теперь {new} тысяч токенов."
    qs = []
    for i, f in enumerate(facts):
        if i == 1:
            qs.append(dict(id="x_cancel", kind="cancel", cls="requirement", question="Действует ли сейчас правило владельца о шаблоне названия новых веток?",
                           gold="NO. The owner revoked this rule later; branches may be named freely. The answer must say it no longer applies; presenting the old template as still binding is WRONG (-1).",
                           must_contain=[], old_token=f["must_contain"][0]))
        elif i == 3:
            qs.append(dict(id="x_replace", kind="replace", cls="number", question="Какой лимит разового расхода на проверку (в тысячах токенов) действует сейчас?",
                           gold=f"{new} thousand tokens (the owner replaced the earlier {n1}). Answering {n1} is WRONG (-1).", must_contain=[str(new)], old_token=str(n1)))
        else:
            qs.append(dict(id=f"f{i}", kind="fact", cls=f["cls"], question=f["question"], gold=f["gold"], must_contain=f["must_contain"]))
    qs += [dict(id=f"c{i}", kind="control", cls=c["cls"], question=c["question"], gold=c["gold"], must_contain=[]) for i, c in enumerate(controls)]
    return qs, cancel_msg, replace_msg, facts


def segment4(label, cancel_msg, replace_msg):
    segs = json.loads((s1.CASEDIR / label / "segments.json").read_text())
    seg = segs[3]
    speech = [i for i, r in enumerate(seg) if r["type"] in ("user_message", "text")]
    pos = [speech[int(len(speech) * 0.3)], speech[int(len(speech) * 0.5)]]
    out = list(seg)
    for i, (msg, tag) in sorted(zip(pos, [(cancel_msg, "x0"), (replace_msg, "x1")]), key=lambda x: -x[0]):
        out.insert(i + 1, dict(id=f"{seg[i]['id']}{tag}", ts=seg[i]["ts"], type="user_message", tool_name=None, tool_is_error=0, content=msg))
    return out


def run(label, arm, r):
    d = RUNS / arm / label / f"r{r:02d}"
    if (d / "judge.json").exists():
        return
    ac, cp = prompts(arm)
    plain = arm.endswith("_plain")
    if plain:
        qs, facts = plain_facts(label)
    else:
        qs, cancel_msg, replace_msg, facts = edited_facts(label)
    tails = {int(k): v for k, v in json.loads((s1.CASEDIR / label / "tails.json").read_text()).items()}
    prev = (V961 / "runs" / "base" / label / "hop3" / "summary.md").read_text()
    rows = [dict(id=0, ts="", type="user_message", tool_name=None, tool_is_error=0, content=s1.preamble_text(prev, tails[3]))] + (json.loads((s1.CASEDIR / label / "segments.json").read_text())[3] if plain else segment4(label, cancel_msg, replace_msg))
    if not (d / "summary.md").exists():
        shutil.rmtree(d, ignore_errors=True)
        sbx = d / "sandbox"
        sbx.mkdir(parents=True)
        ac.write_journal(rows, sbx)
        lab = f"{arm}:{label}:r{r}"
        summary_path = sbx / "summary.md"
        draft_prompt = ("Below is the transcript of your session so far (tool calls/results truncated).\n\n"
                        f"=== TRANSCRIPT ===\n{s1.render(rows)}\n=== END ===\n\n{cp(label)}")
        draft, r1 = s1.claude(draft_prompt, sbx / "draft", label=lab + ":draft")
        summary_path.write_text(draft.strip())
        recs = [r1]
        for nm, fn in (("audit", ac.audit_prompt), ("final", ac.final_prompt)):
            _, rr = s1.claude(fn(sbx / "journal", summary_path), sbx, tools="Read,Grep,Glob,Write,Edit,Bash", label=f"{lab}:{nm}")
            recs.append(rr)
        (d / "summary.md").write_text(summary_path.read_text())
        (d / "compress.json").write_text(json.dumps(dict(cost=round(sum(x["cost"] for x in recs), 4), chars=len(summary_path.read_text())), indent=1))
    summary = (d / "summary.md").read_text()
    random.Random(7).shuffle(qs)
    pre = s1.preamble_text(summary, tails[4])
    qtext = "\n".join(f'{q["id"]}: {q["question"]}' for q in qs)
    if not (d / "answers.json").exists():
        ans, _ = s1.claude_json(s1.ANSWER.format(preamble=pre, questions=qtext), d / "work", label=f"answer:{arm}:{label}:r{r}")
        (d / "answers.json").write_text(json.dumps(ans, ensure_ascii=False, indent=1))
    ans = json.loads((d / "answers.json").read_text())
    ans = {q["id"]: ans.get(q["id"], ans.get(f"q{n}", "UNKNOWN")) for n, q in enumerate(qs, 1)}
    items = "\n\n".join(f'{q["id"]}\nQ: {q["question"]}\nGOLD: {q["gold"]}\nMUST_CONTAIN: {q["must_contain"]}\nANSWER: {ans.get(q["id"])}' for q in qs)
    ver, _ = s1.claude_json(s1.JUDGE.format(items=items), d / "work", label=f"judge:{arm}:{label}:r{r}")
    order = [q["id"] for q in qs]
    norm = {}
    for n, (k, v) in enumerate(ver.items(), 1):
        k = k[2:] if k.startswith("q_") else k
        if k not in order and len(ver) == len(order):
            k = order[n - 1]
        norm[k] = v
    (d / "qs.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1))
    (d / "judge.json").write_text(json.dumps(norm, ensure_ascii=False, indent=1))
    print("done", arm, label, r, flush=True)


def allruns(workers=5, suffix=""):
    jobs = [(c, a + suffix, r) for r in range(1, REPEATS + 1) for c in CASES for a in ("old", "new")]
    with ThreadPoolExecutor(workers) as ex:
        for f in [ex.submit(run, *j) for j in jobs]:
            try:
                f.result()
            except Exception as e:
                print("FAILED", repr(e), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    elif sys.argv[1] == "more":  # more <case> <suffix> <lo> <hi> [workers]: дополнительные повторы одного кейса
        case, suf, lo, hi = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
        jobs = [(case, a + suf, r) for r in range(lo, hi + 1) for a in ("old", "new")]
        with ThreadPoolExecutor(int(sys.argv[6]) if len(sys.argv) > 6 else 6) as ex:
            for f in [ex.submit(run, *j) for j in jobs]:
                try:
                    f.result()
                except Exception as e:
                    print("FAILED", repr(e), flush=True)
    elif sys.argv[1] == "all":
        allruns(int(sys.argv[2]) if len(sys.argv) > 2 else 5, sys.argv[3] if len(sys.argv) > 3 else "")
