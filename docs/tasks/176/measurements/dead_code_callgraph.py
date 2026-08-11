"""Доказательство мёртвого кластера в groom_demo/client.py — граф вызовов по AST.

Grep по имени метода недостаточен: он не видит внутрифайловых вызовов и не
отличает «вызывается живым кодом» от «вызывается таким же мёртвым методом»
(это поймало Codex-ревью, см. codex-review-research.md, blocking B4).

Скрипт строит граф вызовов по всему пакету и проверяет два условия:
  1. у метода нет вызывающих ВНЕ подозреваемого кластера;
  2. в пакете нет динамической диспетчеризации, способной обойти статический граф.

Запуск из каталога groom-demo-bot:
    python3 dead_code_callgraph.py [путь_к_пакету]
"""
import ast
import collections
import pathlib
import sys

# Кластер, оставшийся после того, как #108 убрал consent-стену и guided-FSM из UI.
SUSPECTS = [
    "consent_prompt", "accept_consent", "start_guided", "select_guided_breed",
    "transition_showcase_callback", "prepare_booking_callback", "set_awaiting_phone",
    "action_result", "active_session_id",
]
DYNAMIC = ("getattr(", "__getattr__", "globals()[", "locals()[", "eval(", "importlib")


def build(pkg: pathlib.Path):
    """Вернуть (определения в client.py, вызовы по всему пакету)."""
    defs: dict[str, tuple[int, int]] = {}
    calls: dict[str, set[str]] = collections.defaultdict(set)

    for path in sorted(pkg.glob("*.py")):
        tree = ast.parse(path.read_text(), str(path))

        class Walk(ast.NodeVisitor):
            def __init__(self) -> None:
                self.stack: list[str] = []

            def visit_ClassDef(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def _fn(self, node):
                if path.name == "client.py":
                    defs.setdefault(node.name, (node.lineno, node.end_lineno))
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            visit_FunctionDef = _fn
            visit_AsyncFunctionDef = _fn

            def visit_Call(self, node):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else None
                )
                if name:
                    enclosing = ".".join(self.stack) or "<module>"
                    calls[name].add(f"{path.name}::{enclosing}")
                self.generic_visit(node)

        Walk().visit(tree)
    return defs, calls


def main(pkg_path: str = "groom_demo") -> None:
    pkg = pathlib.Path(pkg_path)
    defs, calls = build(pkg)
    suspects = set(SUSPECTS)
    total = 0
    all_dead = True

    print(f"{'метод':32s} {'строки':>12s}  живые вызывающие (вне кластера)")
    for name in SUSPECTS:
        lo, hi = defs.get(name, (0, 0))
        callers = sorted(calls.get(name, set()))
        # Вызывающий «живой» только если он сам не входит в подозреваемый кластер.
        live = [c for c in callers if c.split("::")[-1].split(".")[-1] not in suspects]
        total += hi - lo + 1
        all_dead &= not live
        print(f"{name:32s} {lo:5d}-{hi:<6d}  {live or 'НЕТ'}")
        if callers and not live:
            print(f"{'':32s} {'':12s}  (вызывается только изнутри кластера: {callers})")

    print(f"\nстрок в кластере: {total}")
    print(f"кластер замкнут сам на себя: {'ДА' if all_dead else 'НЕТ'}")

    # Динамическая диспетчеризация обошла бы статический граф — проверяем, что её нет.
    print("\nдинамическая диспетчеризация:")
    for path in sorted(pkg.glob("*.py")):
        for num, line in enumerate(path.read_text().splitlines(), 1):
            if any(marker in line for marker in DYNAMIC):
                print(f"  {path.name}:{num}: {line.strip()[:90]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "groom_demo")
