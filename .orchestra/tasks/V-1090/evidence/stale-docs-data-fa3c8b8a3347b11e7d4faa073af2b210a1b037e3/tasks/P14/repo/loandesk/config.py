"""Branch settings."""

from dataclasses import dataclass, fields

from loandesk.errors import ConfigError


@dataclass
class Settings:
    """Settings for one library branch."""

    loan_days: int = 21
    fine_per_day: float = 0.25
    max_fine: float = 10.0
    max_loans: int = 6


def load_settings(lines: list[str] | None = None) -> Settings:
    """Build settings from ``name = value`` lines on top of the defaults.

    Args:
        lines: Settings lines. Blank lines and ``#`` comments are skipped.
            ``None`` gives the defaults.

    Returns:
        The branch settings.

    Raises:
        ConfigError: If a line is malformed, names an unknown setting or has
            a value of the wrong type.
    """
    settings = Settings()
    known = {f.name: f.type for f in fields(Settings)}
    for line in lines or []:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        name, sep, raw = (part.strip() for part in text.partition("="))
        if not sep or name not in known:
            raise ConfigError(f"bad settings line: {line!r}")
        convert = int if known[name] in (int, "int") else float
        try:
            value = convert(raw)
        except ValueError:
            raise ConfigError(f"bad value for {name}: {raw!r}") from None
        setattr(settings, name, value)
    return settings
