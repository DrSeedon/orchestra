#!/usr/bin/env python3
import argparse
import csv
import hashlib
from pathlib import Path


TEXT_MODELS = {
    "claude-fable-5": "Fable 5",
    "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-8-thinking": "Opus 4.8 thinking",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-6-thinking": "Opus 4.6 thinking",
    "gpt-5.6-sol-xhigh": "Sol xHigh",
    "claude-sonnet-5-high": "Sonnet 5 high",
    "gpt-5.5-high": "GPT 5.5 high",
    "gpt-5.5": "GPT 5.5",
    "gpt-5.3-chat-latest": "GPT 5.3 chat (not Spark)",
}

AGENT_MODELS = {
    "Claude Fable 5 (High)": ("Fable 5", "claude-fable-5"),
    "Claude Opus 4.8": ("Opus 4.8", "claude-opus-4-8"),
    "Claude Opus 4.8 (Thinking)": (
        "Opus 4.8 thinking",
        "claude-opus-4-8-thinking",
    ),
    "Claude Opus 4.6": ("Opus 4.6", "claude-opus-4-6"),
    "GPT 5.6 Sol (xHigh)": ("Sol xHigh", "gpt-5.6-sol-xhigh"),
    "Claude Sonnet 5 (High)": ("Sonnet 5 high", "claude-sonnet-5-high"),
    "GPT 5.5 (High)": ("GPT 5.5 high", "gpt-5.5-high"),
    "GPT 5.5": ("GPT 5.5", "gpt-5.5"),
}

WEBDEV_MODELS = {
    "claude-fable-5": ("Fable 5", "claude-fable-5"),
    "claude-opus-4-8": ("Opus 4.8", "claude-opus-4-8"),
    "claude-opus-4-8-thinking": (
        "Opus 4.8 thinking",
        "claude-opus-4-8-thinking",
    ),
    "claude-opus-4-6": ("Opus 4.6", "claude-opus-4-6"),
    "claude-opus-4-6-thinking": (
        "Opus 4.6 thinking",
        "claude-opus-4-6-thinking",
    ),
    "gpt-5.6-sol-xhigh (codex-harness)": ("Sol xHigh", "gpt-5.6-sol-xhigh"),
    "claude-sonnet-5-high": ("Sonnet 5 high", "claude-sonnet-5-high"),
    "gpt-5.5-high (codex-harness)": ("GPT 5.5 high", "gpt-5.5-high"),
    "gpt-5.5 (codex-harness)": ("GPT 5.5", "gpt-5.5"),
    "gpt-5.3-codex (codex-harness)": (
        "GPT 5.3 Codex (not Spark)",
        "gpt-5.3-codex",
    ),
}

REQUESTED_TEXT_CATEGORIES = {
    "overall",
    "coding",
    "creative_writing",
    "math",
    "instruction_following",
    "hard_prompts",
    "multi_turn",
    "expert",
    "russian",
}

AGENT_CONFIGS = [
    "agent",
    "agent_bash_recovery_steps",
    "agent_praise_complaint",
    "agent_steerability",
    "agent_task_outcome_explicit",
    "agent_tool_hallucination",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def add_model_labels(
    rows: list[dict[str, str]], aliases: dict[str, tuple[str, str]]
) -> list[dict[str, str]]:
    result = []
    for row in rows:
        alias = aliases.get(row["model_name"])
        if alias:
            result.append({"display_name": alias[0], "fleet_id": alias[1], **row})
    return result


def build_manifest(source: Path) -> list[dict[str, str | int]]:
    result = []
    for path in sorted(source.glob("*__*.csv")):
        config, split = path.stem.rsplit("__", 1)
        row_count = 0
        dates = set()
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row_count += 1
                if row["leaderboard_publish_date"]:
                    dates.add(row["leaderboard_publish_date"])
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sorted_dates = sorted(dates)
        result.append(
            {
                "config": config,
                "split": split,
                "rows": row_count,
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "first_publish_date": sorted_dates[0] if sorted_dates else "",
                "last_publish_date": sorted_dates[-1] if sorted_dates else "",
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    text_rows = []
    for row in read_csv(args.source / "text_style_control__latest.csv"):
        display_name = TEXT_MODELS.get(row["model_name"])
        if display_name:
            text_rows.append({"display_name": display_name, "fleet_id": row["model_name"], **row})
    text_fields = [
        "display_name",
        "fleet_id",
        "model_name",
        "rating",
        "rating_lower",
        "rating_upper",
        "variance",
        "vote_count",
        "rank",
        "category",
        "leaderboard_publish_date",
    ]
    write_csv(args.output / "fleet-text-all-categories.csv", text_rows, text_fields)
    write_csv(
        args.output / "fleet-requested-text-categories.csv",
        [row for row in text_rows if row["category"] in REQUESTED_TEXT_CATEGORIES],
        text_fields,
    )

    agent_rows = []
    for config in AGENT_CONFIGS:
        for row in add_model_labels(
            read_csv(args.source / f"{config}__latest.csv"), AGENT_MODELS
        ):
            agent_rows.append({"agent_signal": config, **row})
    write_csv(
        args.output / "fleet-agent.csv",
        agent_rows,
        [
            "agent_signal",
            "display_name",
            "fleet_id",
            "model_name",
            "score",
            "score_ci_lower",
            "score_ci_upper",
            "observation_count",
            "session_count",
            "rank",
            "category",
            "leaderboard_publish_date",
        ],
    )

    webdev_rows = add_model_labels(
        read_csv(args.source / "webdev__latest.csv"), WEBDEV_MODELS
    )
    write_csv(
        args.output / "fleet-webdev.csv",
        webdev_rows,
        [
            "display_name",
            "fleet_id",
            "model_name",
            "rating",
            "rating_lower",
            "rating_upper",
            "variance",
            "vote_count",
            "rank",
            "category",
            "leaderboard_publish_date",
        ],
    )

    write_csv(
        args.output / "dataset-manifest.csv",
        build_manifest(args.source),
        [
            "config",
            "split",
            "rows",
            "bytes",
            "sha256",
            "first_publish_date",
            "last_publish_date",
        ],
    )


if __name__ == "__main__":
    main()
