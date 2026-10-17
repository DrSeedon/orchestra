import json, random, re, subprocess, sys
S = json.load(open("sample.json"))["items"]
rnd = random.Random(1909); order = list(range(len(S))); rnd.shuffle(order)
key = {}
for n, i in enumerate(order, 1):
    it = S[i]; rid = it["id"]; name = f"item-{n:02d}"
    text = open(f"raw/{rid}.review.md").read()
    text = re.sub(r"/home/kesha/v909-work/v909-[^/]+/", "", text)
    subj = subprocess.run(["git", "-C", "/home/kesha/orchestra", "show", "-s", "--format=%s%n%ad", "--date=short", it["sha"]],
                          capture_output=True, text=True).stdout.strip()
    open(f"label/{name}.md", "w").write(
        f"# {name}\n\nCommit under review (in /home/kesha/orchestra, read-only): `{it['sha']}`\nSubject / date:\n{subj}\n\n"
        f"The diff reviewed is `git -C /home/kesha/orchestra show {it['sha']} -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.\n\n"
        f"## Reviewer output (verbatim)\n\n{text}\n")
    key[name] = rid
json.dump(key, open("label_key.json", "w"), indent=1)
print(len(key))
