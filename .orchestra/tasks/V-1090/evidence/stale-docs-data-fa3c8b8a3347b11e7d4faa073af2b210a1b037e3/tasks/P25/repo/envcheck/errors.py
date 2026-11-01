"""Errors of envcheck. The commands catch EnvCheckError and exit with status 2."""


class EnvCheckError(Exception):
    """Base class of every envcheck error."""


class EnvParseError(EnvCheckError):
    """An env file has a line that is not NAME=value."""


class SchemaError(EnvCheckError):
    """The schema file is invalid."""


class SettingsError(EnvCheckError):
    """The settings file cannot be read or is invalid."""
