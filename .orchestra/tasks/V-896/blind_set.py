"""Owner blind set: 4 creative A-vs-B pairs, distinct tasks, seed 896. pairs.md has no arm info; key.json holds it."""
import json, random, glob
from pathlib import Path
from tasks import CREATIVE
H = Path(__file__).parent; out = H / "owner_blind"; out.mkdir(exist_ok=True)
rng = random.Random(896)
tasks = rng.sample(sorted(CREATIVE), 4)
md = ["# Слепой набор V-896: какой текст лучше (1 или 2)?\n", "Для каждой пары выбери лучший ответ на задание. Ключ в key.json не открывай до выбора.\n"]
key = {}
for i, t in enumerate(tasks):
    model = rng.choice(["luna", "sonnet"]); rep = rng.choice(["1", "2"])
    a = json.load(open(H / f"raw/A-{t}-{model}-r{rep}.json"))["final_text"]
    b = json.load(open(H / f"raw/B-{t}-{model}-r{rep}.json"))["final_text"]
    flip = rng.random() < 0.5
    first, second = (b, a) if flip else (a, b)
    letter = "ABCD"[i]
    md += [f"\n## Пара {letter}\n", f"**Задание:** {CREATIVE[t]['prompt']}\n", f"### {letter}1\n{first}\n", f"### {letter}2\n{second}\n"]
    key[letter] = dict(task=t, model=model, rep=rep, first="B" if flip else "A", second="A" if flip else "B")
(out / "pairs.md").write_text("\n".join(md)); (out / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False))
print(tasks)
