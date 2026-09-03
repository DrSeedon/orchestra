"""#8 — мутационная проверка перехвата: сломанный стаб обязан покраснить verify-скрипт.

Зелёный перехват сам по себе ничего не доказывает: пока файл ветки совпадает с тем, что
отдаёт живой сервер, неприменившийся стаб выглядит точно так же, как применившийся. Поэтому
каждый скрипт запускается с намеренно испорченным app.js: если перехват работает, скрипт
краснеет; остался зелёным — значит страница взяла настоящий файл, и приёмка ничего не стоит.

Мутант пишется РЯДОМ со скриптами (у них ROOT = parents[3]) и удаляется после прогона.

Запуск: uv run python docs/tasks/8/mutation-check.py
"""
import pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
STUB = "body=APP_JS.read_text()"

# скрипт → (мутация стаба, что именно она ломает)
MUTANTS = {
    "verify-store.py": (
        'body=APP_JS.read_text() + "\\nwindow._storeRead = async () => [];\\n"',
        "_storeRead всегда пуст → чтение из зеркала и промах истории",
    ),
    "verify-switch.py": (
        'body=APP_JS.read_text() + "\\nwindow._storeRead = async () => [];\\n"',
        "_storeRead всегда пуст → переключение уходит за историей на сервер",
    ),
    "verify-truncation.py": (
        'body=APP_JS.read_text().replace("!rows.some((r) => r.trunc)", "true")',
        "обрезанные строки считаются целыми → история берётся из зеркала",
    ),
}
TRUNC_MARKER = "!rows.some((r) => r.trunc)"

app_js = (HERE.parents[2] / "app/static/js/app.js").read_text()
if TRUNC_MARKER not in app_js:
    sys.exit(f"мутация для verify-truncation протухла: в app.js нет '{TRUNC_MARKER}'")

failed = []
for name, (stub, what) in MUTANTS.items():
    src = (HERE / name).read_text()
    if STUB not in src:
        sys.exit(f"{name}: не найден стаб '{STUB}' — мутация не применима")
    mutant = HERE / f"_mutant-{name}"
    mutant.write_text(src.replace(STUB, stub))
    print(f"\n=== {name}: {what}")
    try:
        r = subprocess.run([sys.executable, str(mutant)], capture_output=True, text=True)
    finally:
        mutant.unlink()
    tail = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("FAIL")
            or "проверок прошли" in ln]
    print("\n".join(tail) or r.stdout[-800:] or r.stderr[-800:])
    print(f"  код возврата {r.returncode} — {'ПОКРАСНЕЛ (перехват работает)' if r.returncode else 'ЗЕЛЁНЫЙ (перехват НЕ применился)'}")
    if r.returncode == 0:
        failed.append(name)

print(f"\n{len(MUTANTS) - len(failed)}/{len(MUTANTS)} скриптов доказали перехват мутацией")
sys.exit(1 if failed else 0)
