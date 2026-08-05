#!/usr/bin/env python3
"""Проверка карты кода. Запуск из корня репозитория:

    python3 docs/codemap/validate.py

Падает (exit 1) на первом же расхождении карты с кодом. Пустой список — тоже провал:
проверка, агрегирующая пустой сбор, печатает зелёное, ничего не проверив.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAP_DIR = REPO / "docs/codemap"
FINGERPRINT_ALGO = "sha256-v1: sha256 над отсортированными строками '<путь>\\0<sha256 содержимого>\\n'"

fails: list[str] = []
checks = 0


def check(ok: bool, msg: str) -> bool:
    global checks
    checks += 1
    if not ok:
        fails.append(msg)
    return ok


def nonempty(seq, what: str) -> bool:
    """Пустой сбор = провал: иначе all()/any() ниже зеленеют, ничего не проверив."""
    return check(len(seq) > 0, f"пустой набор: {what}")


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} упал: {r.stderr.strip()}")
    return r.stdout


def sha_file(rel: str) -> str:
    return hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


def fingerprint(files: list[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(f"{rel}\0{sha_file(rel)}\n".encode())
    return h.hexdigest()


def module_files(node: dict, tracked: set[str]) -> list[str]:
    return sorted(f for f in node["files"] if f in tracked)


def scope_dirty(scope: list[str]) -> bool:
    """Незакоммиченные правки В СКОУПЕ карты. Правки в docs/ карту не протухают."""
    return bool(git("status", "--porcelain", "--", *scope).strip())


# ── 1. codemap.json парсится ───────────────────────────────────────────
raw = (MAP_DIR / "codemap.json").read_text()
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    sys.exit(f"FAIL codemap.json не парсится: {e}")
print("OK   codemap.json парсится")

nodes, edges, flows = data["nodes"], data["edges"], data["flows"]
tracked = set(git("ls-files").split("\n")) - {""}

if "--emit-lock" in sys.argv:
    # Единственный владелец алгоритма фингерпринта — этот файл. Лок пишется тем же
    # кодом, которым потом проверяется, иначе они разойдутся молча.
    modules = {}
    for n in nodes:
        if not n["primary"]:
            continue
        files = module_files(n, tracked)
        if not files:
            sys.exit(f"модуль {n['id']} без трекнутых файлов")
        modules[n["id"]] = {"files": files, "fingerprint": fingerprint(files)}
    lock = {
        "commit": git("rev-parse", "HEAD").strip(),
        "commit_policy": "коммит, из которого снята карта; актуальность проверяется "
                         "фингерпринтами, а сам коммит обязан быть предком HEAD",
        "working_tree_dirty": scope_dirty(data["scope"]),
        "generated_at": data["generated_at"],
        "scope": data["scope"],
        "excluded": data["excluded"],
        "fingerprint_algorithm": FINGERPRINT_ALGO,
        "modules": modules,
    }
    (MAP_DIR / "codemap.lock").write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n")
    print(f"codemap.lock записан: {len(modules)} модулей, коммит {lock['commit'][:8]}")
    sys.exit(0)

nonempty(nodes, "nodes")
nonempty(edges, "edges")
nonempty(flows, "flows")
by_id = {n["id"]: n for n in nodes}
check(len(by_id) == len(nodes), "дубли node.id")

# ── 2. пути существуют, символы реально есть в исходниках ─────────────
ev_total = 0
for n in nodes:
    check((REPO / n["path"]).is_file(), f"{n['id']}: нет файла {n['path']}")
    nonempty(n["files"], f"{n['id']}.files")
    nonempty(n["evidence"], f"{n['id']}.evidence")
    for f in n["files"]:
        check((REPO / f).is_file(), f"{n['id']}: нет файла {f}")
    for t in n["tests"]:
        check((REPO / t).is_file(), f"{n['id']}: нет теста {t}")
    for e in n["evidence"]:
        ev_total += 1
        src = REPO / e["path"]
        if not check(src.is_file(), f"{n['id']}: evidence-файл отсутствует {e['path']}"):
            continue
        lines = src.read_text(errors="replace").splitlines()
        line_ok = 0 < e["line"] <= len(lines) and e["symbol"] in lines[e["line"] - 1]
        check(line_ok, f"{n['id']}: символ {e['symbol']!r} не найден в {e['path']}:{e['line']}")
nonempty([1] * ev_total, "evidence узлов")
print(f"OK   пути и символы узлов: {len(nodes)} узлов, {ev_total} доказательств")

# ── 3. рёбра и шаги потоков ссылаются на существующие узлы ────────────
EDGE_TYPES = {"imports", "calls", "reads", "writes", "publishes", "subscribes"}
edge_ev = 0
unknown = 0
for e in edges:
    check(e["from"] in by_id, f"ребро из несуществующего узла: {e['from']}")
    check(e["to"] in by_id, f"ребро в несуществующий узел: {e['to']}")
    check(e["type"] in EDGE_TYPES, f"неизвестный тип ребра: {e['type']}")
    # 6. связь без доказательства обязана быть помечена unknown
    if not e["evidence"]:
        unknown += 1
        check(e.get("unknown") is True,
              f"связь без доказательства не помечена unknown: {e['from']}→{e['to']}")
        continue
    check(not e.get("unknown") or e.get("note"),
          f"unknown-связь без объяснения: {e['from']}→{e['to']}")
    for ev in e["evidence"]:
        edge_ev += 1
        src = REPO / ev["path"]
        if not check(src.is_file(), f"ребро {e['from']}→{e['to']}: нет {ev['path']}"):
            continue
        lines = src.read_text(errors="replace").splitlines()
        ok = 0 < ev["line"] <= len(lines) and ev["symbol"] in lines[ev["line"] - 1]
        check(ok, f"ребро {e['from']}→{e['to']}: символ {ev['symbol']!r} "
                  f"не найден в {ev['path']}:{ev['line']}")
nonempty([1] * edge_ev, "evidence рёбер")

steps = 0
for f in flows:
    nonempty(f["steps"], f"flow {f['id']}.steps")
    check(bool(f["trigger"]) and bool(f["outcome"]), f"flow {f['id']}: пустой trigger/outcome")
    for s in f["steps"]:
        steps += 1
        check(s["node"] in by_id, f"flow {f['id']}: шаг ссылается на несуществующий узел {s['node']}")
nonempty([1] * steps, "шаги потоков")
print(f"OK   ссылки: {len(edges)} рёбер ({edge_ev} доказательств, {unknown} unknown), "
      f"{len(flows)} потоков / {steps} шагов")

# ── 4. html и json используют ОДИН И ТОТ ЖЕ набор ─────────────────────
html = (MAP_DIR / "codemap.html").read_text()
m = re.search(r'<script id="codemap-data" type="application/json">(.*?)</script>', html, re.S)
if not check(m is not None, "в codemap.html нет блока codemap-data"):
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
embedded = json.loads(m.group(1))
for key in ("nodes", "edges", "flows"):
    check(embedded[key] == data[key], f"html и json расходятся по {key}")
check(embedded["generated_from_commit"] == data["generated_from_commit"],
      "html и json собраны из разных коммитов")
net = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', html) + re.findall(r"@import", html)
check(not net, f"codemap.html не self-contained, грузит по сети: {net[:3]}")
print("OK   html и json используют один набор nodes/edges/flows, html self-contained")

# ── 5. lock: коммит, состояние дерева, фингерпринты модулей ───────────
lock = json.loads((MAP_DIR / "codemap.lock").read_text())
head = git("rev-parse", "HEAD").strip()
dirty = scope_dirty(lock["scope"])
ancestor = subprocess.run(
    ["git", "-C", str(REPO), "merge-base", "--is-ancestor", lock["commit"], head]).returncode == 0
check(ancestor, f"lock собран на {lock['commit'][:8]}, который не является предком HEAD {head[:8]}")
check(lock["working_tree_dirty"] == dirty,
      f"lock: working_tree_dirty={lock['working_tree_dirty']}, фактически {dirty}")
check(lock["fingerprint_algorithm"] == FINGERPRINT_ALGO, "lock: другой алгоритм фингерпринта")
nonempty(lock["modules"], "lock.modules")
nonempty(lock["scope"], "lock.scope")
nonempty(lock["excluded"], "lock.excluded")

primary = [n for n in nodes if n["primary"]]
nonempty(primary, "primary-узлы")
check(len(primary) <= 20, f"primary-узлов {len(primary)} > 20")
check(set(lock["modules"]) == {n["id"] for n in primary},
      "lock.modules не совпадает с набором primary-узлов карты")

changed = []
for n in primary:
    files = module_files(n, tracked)
    if not nonempty(files, f"{n['id']}: трекнутые файлы модуля"):
        continue
    rec = lock["modules"].get(n["id"])
    if not check(rec is not None, f"lock: нет модуля {n['id']}"):
        continue
    check(rec["files"] == files, f"lock: список файлов {n['id']} разошёлся с картой")
    if rec["fingerprint"] != fingerprint(files):
        changed.append(n["id"])
check(not changed, f"модули изменились с момента генерации карты: {', '.join(changed)}")

# каждый трекнутый .py в app/ принадлежит ровно одному primary-модулю
owners: dict[str, list[str]] = {}
for n in primary:
    for f in n["files"]:
        owners.setdefault(f, []).append(n["id"])
app_py = sorted(f for f in tracked if f.startswith("app/") and f.endswith(".py"))
nonempty(app_py, "трекнутые app/**/*.py")
orphans = [f for f in app_py if f not in owners]
dupes = [f for f, o in owners.items() if len(o) > 1]
check(not orphans, f"файлы вне карты: {', '.join(orphans[:8])}")
check(not dupes, f"файлы в двух модулях сразу: {', '.join(dupes[:8])}")
print(f"OK   lock: коммит {head[:8]}, dirty={dirty}, {len(lock['modules'])} модулей, "
      f"{len(app_py)} файлов app/**/*.py покрыты картой")

# ── итог ──────────────────────────────────────────────────────────────
if fails:
    print(f"\n{len(fails)} ПРОВАЛОВ из {checks} проверок:")
    for f in fails:
        print("  FAIL " + f)
    sys.exit(1)
print(f"\nВСЁ ЗЕЛЁНОЕ: {checks} проверок")
