"""Error types of the cronlint package."""


class CronError(Exception):
    """Base class of every error that cronlint signals."""


class CronSyntaxError(CronError):
    """A cron expression or a crontab line cannot be parsed."""


class CronRangeError(CronError):
    """A value in a cron field is outside the range that the field allows."""
