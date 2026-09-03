#!/usr/bin/env python3
import argparse
from pathlib import Path

from datasets import get_dataset_config_names, load_dataset


DATASET = "lmarena-ai/leaderboard-dataset"
REVISION = "543e0628da0a445a3c8918967c1ef7311bc2d868"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    for config in get_dataset_config_names(DATASET, revision=REVISION):
        dataset = load_dataset(DATASET, config, revision=REVISION)
        for split, table in dataset.items():
            path = args.output / f"{config}__{split}.csv"
            table.to_csv(path)
            print(f"{config}/{split}: {len(table)} -> {path}")


if __name__ == "__main__":
    main()
