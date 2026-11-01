"""Check one env file against the schema.

Run as ``python -m envcheck.check SETTINGS_FILE ENV_FILE``. The command prints
one line per problem and exits with status 0 when there is none, 1 when a
variable is missing or invalid and 2 when an input file cannot be used.
"""
import argparse
import sys

from envcheck.envfile import read_env_file
from envcheck.errors import EnvCheckError
from envcheck.rules import check_values
from envcheck.schema import load_schema
from envcheck.settings import load_settings


def problem_lines(problems: dict[str, list[str]]) -> list[str]:
    """Turn the result of check_values into lines such as "missing: PORT".

    Args:
        problems: The dict from check_values.

    Returns:
        The missing names first, then the invalid names.
    """
    lines = [f"missing: {name}" for name in problems["missing"]]
    lines += [f"invalid: {name}" for name in problems["invalid"]]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Run the check command.

    Args:
        argv: The command line arguments, or None for sys.argv.

    Returns:
        The exit status.
    """
    parser = argparse.ArgumentParser(prog="python -m envcheck.check")
    parser.add_argument("settings", help="settings file with an [envcheck] section")
    parser.add_argument("env_file", help="env file to check")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.settings)
        schema = load_schema(settings["schema"])
        values = read_env_file(args.env_file)
    except (OSError, EnvCheckError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    lines = problem_lines(check_values(values, schema, settings))
    for line in lines:
        print(line)
    if lines:
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
