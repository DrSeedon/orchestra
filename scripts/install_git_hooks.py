#!/usr/bin/env python3
"""Поставить гейт секретов в общий `.git/hooks` (#453).

Один прогон закрывает ВЕСЬ репозиторий: linked worktree берёт хуки из common dir, поэтому
установка покрывает и уже существующие рабочие деревья воркеров, и все будущие. Хуки в git
не версионируются — на новом клоне команду надо повторить.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = "orchestra-secret-gate"
HOOKS = ("pre-commit", "commit-msg", "pre-push")


def _hooks_dir_git_actually_uses() -> Path:
    """`--git-path hooks` учитывает `core.hooksPath`; `.git/hooks` — нет."""
    return Path(
        subprocess.run(
            ("git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"),
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="перезаписать чужой хук")
    args = ap.parse_args()

    common = Path(
        subprocess.run(
            ("git", "rev-parse", "--path-format=absolute", "--git-common-dir"),
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    )
    # Источник — ГЛАВНЫЙ чекаут, тот же, из которого хук потом зовёт сканер: если гейта
    # там ещё нет, установка обязана упасть, а не поставить хук, зовущий несуществующее.
    src_dir = common.parent / "scripts" / "hooks"
    missing = [n for n in HOOKS if not (src_dir / n).exists()]
    if missing:
        print(f"ОТКАЗ: в {src_dir} нет {', '.join(missing)}", file=sys.stderr)
        return 1
    dst_dir = common / "hooks"
    # Положительный признак: git ДОЛЖЕН звать хуки именно оттуда, куда мы пишем. При заданном
    # `core.hooksPath` (в том числе глобальном) установка «успешна», а git наши хуки не зовёт
    # вовсе. Ставить в чужой каталог нельзя: наши хуки ищут сканер в СВОЁМ репозитории и
    # заблокировали бы коммиты во всех остальных.
    effective = _hooks_dir_git_actually_uses()
    if effective.resolve() != dst_dir.resolve():
        print(
            f"ОТКАЗ: git берёт хуки из {effective} (задан core.hooksPath), а не из {dst_dir}.\n"
            "Сними настройку — `git config --unset core.hooksPath` (или `--global`) — и повтори.",
            file=sys.stderr,
        )
        return 1
    dst_dir.mkdir(parents=True, exist_ok=True)

    for name in HOOKS:
        dst = dst_dir / name
        if dst.exists() and MARKER not in dst.read_text(errors="replace") and not args.force:
            print(f"ОТКАЗ: {dst} — чужой хук, перезапись только с --force", file=sys.stderr)
            return 1
        shutil.copyfile(src_dir / name, dst)
        dst.chmod(0o755)
        print(f"установлен {dst}")

    print(f"действует во всех worktree этого репозитория (common dir: {common})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
