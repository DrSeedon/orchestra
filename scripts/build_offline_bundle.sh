#!/usr/bin/env bash
# Собирает офлайн-комплект поставки: код + wheels всех зависимостей рантайма
# (linux x86_64, CPython 3.12, версии и хеши из uv.lock) + install-offline.sh.
# Сборке нужна сеть (pypi.org), установке из комплекта — нет.
# Использование: scripts/build_offline_bundle.sh [каталог-вывода]   (по умолчанию dist/)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
cd "$ROOT"

VERSION="$(python3 -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
NAME="orchestra-offline-${VERSION}-linux-x86_64-cp312"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT" "$STAGE/$NAME"

# Тот же набор, что даёт `uv sync` без dev-группы; хеши закрепляют бинарники.
uv export --no-dev --frozen --no-emit-project 2>/dev/null | grep -v '^#' > "$STAGE/$NAME/requirements-offline.txt"

rm -rf "$ROOT/wheels"
python3 -m pip download --require-hashes --no-deps --only-binary=:all: \
    --python-version 3.12 --implementation cp --abi cp312 \
    --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
    --platform manylinux_2_28_x86_64 --platform manylinux_2_34_x86_64 --platform any \
    -r "$STAGE/$NAME/requirements-offline.txt" -d "$ROOT/wheels"
cp -a "$ROOT/wheels" "$STAGE/$NAME/wheels"

# Состав поставки — явный список того, что нужно для установки и работы. Файлы разработки
# (CI, правила агентов разработки, TODO, служебные хуки) в поставку не входят.
git ls-files -z -- app .orchestra/pipelines .orchestra/layout.json pyproject.toml .env.example \
    README.md README.ru.md LICENSE deploy/install-offline.sh deploy/orchestra.service.template \
    deploy/nginx.conf.template \
    | tar --null -T - -cf - | tar -xf - -C "$STAGE/$NAME"

tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME"
( cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
ls -l "$OUT/$NAME.tar.gz"
