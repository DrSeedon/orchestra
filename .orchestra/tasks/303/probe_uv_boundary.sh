#!/usr/bin/env bash
set -u

# Scratch-only reproduction for task #303. It refuses to touch the live Orchestra
# environment. Output is TSV so it can be copied into evidence.json without parsing prose.
ROOT=$(mktemp -d "$PWD/docs/tasks/303/.probe-uv.XXXXXX")
UV=/home/kesha/.local/bin/uv
TARGET="$ROOT/shared-env"
A="$ROOT/project-a"
B="$ROOT/project-b"

case "$ROOT" in
  "$PWD"/docs/tasks/303/.probe-uv.*) ;;
  *) echo "refusing unsafe scratch root: $ROOT" >&2; exit 70 ;;
esac
if [ "$TARGET" = /home/kesha/orchestra/.venv ]; then
  echo "refusing live service environment" >&2
  exit 70
fi

mkdir -p "$A" "$B"
printf '%s\n' '[project]' 'name = "probe-a"' 'version = "0.0.0"' \
  'requires-python = ">=3.12,<3.13"' 'dependencies = []' > "$A/pyproject.toml"
printf '%s\n' '3.12' > "$A/.python-version"
printf '%s\n' '[project]' 'name = "probe-b"' 'version = "0.0.0"' \
  'requires-python = ">=3.11,<3.12"' 'dependencies = []' > "$B/pyproject.toml"
printf '%s\n' '3.11' > "$B/.python-version"

env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT "$UV" lock --project "$A" >/dev/null
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT "$UV" lock --project "$B" >/dev/null

fingerprint() {
  if [ ! -f "$1/pyvenv.cfg" ]; then
    printf 'absent'
    return
  fi
  awk -F' = ' '/^(version_info|prompt) =/{printf "%s=%s;",$1,$2}' "$1/pyvenv.cfg"
}

seed_a() {
  env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$TARGET" \
    "$UV" run --project "$A" --frozen python -c 'import sys; print(sys.version_info[:2])' \
    >"$ROOT/seed.out" 2>"$ROOT/seed.err"
}

seed_a
before=$(fingerprint "$TARGET")
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$TARGET" \
  "$UV" run --project "$B" --frozen python -c 'import sys; print(sys.version_info[:2])' \
  >"$ROOT/p1.out" 2>"$ROOT/p1.err"
printf 'P1_explicit_UV_PROJECT_ENVIRONMENT\tbefore=%s\tafter=%s\tremoved=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$(grep -c 'Removed virtual environment' "$ROOT/p1.err")"

seed_a
before=$(fingerprint "$TARGET")
env -u UV_PROJECT_ENVIRONMENT VIRTUAL_ENV="$TARGET" \
  "$UV" run --project "$B" --active --frozen python -c 'import sys; print(sys.version_info[:2])' \
  >"$ROOT/p2.out" 2>"$ROOT/p2.err"
printf 'P2_inherited_VIRTUAL_ENV_active\tbefore=%s\tafter=%s\tremoved=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$(grep -c 'Removed virtual environment' "$ROOT/p2.err")"

seed_a
before=$(fingerprint "$TARGET")
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT \
  "$UV" run --project "$B" --frozen python -c 'import sys; print(sys.version_info[:2])' \
  >"$ROOT/p3.out" 2>"$ROOT/p3.err"
printf 'P3_stripped_env_normal_project\tshared_before=%s\tshared_after=%s\tlocal=%s\trc=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$(fingerprint "$B/.venv")" "$?"

seed_a
before=$(fingerprint "$TARGET")
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT bash -c \
  'UV_PROJECT_ENVIRONMENT="$1" "$2" run --project "$3" --frozen python -c "import sys; print(sys.version_info[:2])"' \
  _ "$TARGET" "$UV" "$B" >"$ROOT/p4.out" 2>"$ROOT/p4.err"
printf 'P4_parent_env_strip_inline_bypass\tbefore=%s\tafter=%s\tremoved=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$(grep -c 'Removed virtual environment' "$ROOT/p4.err")"

seed_a
before=$(fingerprint "$TARGET")
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$TARGET" \
  "$UV" run --project "$B" --frozen --no-sync python -c 'import sys; print(sys.version_info[:2])' \
  >"$ROOT/p5.out" 2>"$ROOT/p5.err"
p5_rc=$?
printf 'P5_no_sync\tbefore=%s\tafter=%s\trc=%s\tpython=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$p5_rc" "$(tr -d '\n' < "$ROOT/p5.out")"

seed_a
before=$(fingerprint "$TARGET")
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT "$UV" venv --clear --python 3.11 "$TARGET" \
  >"$ROOT/p6.out" 2>"$ROOT/p6.err"
printf 'P6_direct_uv_venv_bypass\tbefore=%s\tafter=%s\trc=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$?"

seed_a
before=$(fingerprint "$TARGET")
ln -s "$TARGET" "$ROOT/target-alias"
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$ROOT/target-alias" \
  "$UV" run --project "$B" --frozen true >"$ROOT/p7-alias.out" 2>"$ROOT/p7-alias.err"
p7_alias=$?
printf 'P7_symlink_alias\tbefore=%s\tafter=%s\trc=%s\tremoved=%s\n' \
  "$before" "$(fingerprint "$TARGET")" "$p7_alias" \
  "$(grep -c 'Removed virtual environment' "$ROOT/p7-alias.err")"

seed_a
mkdir "$ROOT/protected-parent"
mv "$TARGET" "$ROOT/protected-parent/runtime"
TARGET="$ROOT/protected-parent/runtime"
chmod -R a-w "$TARGET"
chmod a-w "$ROOT/protected-parent"
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$TARGET" \
  "$UV" run --project "$B" --frozen true >"$ROOT/p7-deny.out" 2>"$ROOT/p7-deny.err"
p7_deny=$?
chmod u+w "$ROOT/protected-parent"
chmod -R u+w "$TARGET"
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT UV_PROJECT_ENVIRONMENT="$TARGET" \
  "$UV" run --project "$B" --frozen true >"$ROOT/p7-bypass.out" 2>"$ROOT/p7-bypass.err"
p7_bypass=$?
printf 'P8_same_uid_modes\treadonly_rc=%s\towner_chmod_then_rc=%s\tafter=%s\n' \
  "$p7_deny" "$p7_bypass" "$(fingerprint "$TARGET")"

bash -c 'uv(){ return 77; }; uv --version'
p8_wrapper=$?
"$UV" --version >"$ROOT/p8.out" 2>"$ROOT/p8.err"
p8_absolute=$?
printf 'P9_PATH_or_shell_wrapper\twrapper_rc=%s\tabsolute_uv_rc=%s\n' \
  "$p8_wrapper" "$p8_absolute"

printf 'SCRATCH\t%s\n' "$ROOT"
chmod -R u+rwX "$ROOT"
find "$ROOT" -depth -delete
printf 'CLEANED\t1\n'
