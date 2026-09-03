#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 DEST PROJECT_NAME FULL_PROJECT_YML" >&2
    exit 2
fi

dest=$1
project_name=$2
project_yml=$3
script_dir=$(cd "$(dirname "$0")" && pwd)
source_root=$(cd "$script_dir/../../../.." && pwd)
frozen_ref=b3d1fccc61381b457c9f06baa55256c24cf454f7

mkdir -p "$dest"
git -C "$source_root" archive "$frozen_ref" | tar -x -C "$dest"
mkdir -p "$dest/.serena"
cp "$project_yml" "$dest/.serena/project.yml"
sed -i "s/^project_name:.*/project_name: $project_name/" "$dest/.serena/project.yml"
git -C "$dest" init -q
git -C "$dest" config user.email eval346@example.invalid
git -C "$dest" config user.name Eval346
git -C "$dest" add -A
git -C "$dest" commit -qm "frozen #346 evaluator snapshot"
git -C "$dest" status --short
git -C "$dest" rev-parse HEAD
git -C "$source_root" rev-parse "$frozen_ref"
