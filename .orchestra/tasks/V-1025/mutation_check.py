"""Offline mutation: validate normally but drop options before the hub call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import pytest
from app.backend_hub import HubBackend

original = HubBackend._model_selection


async def drop_options(self, *args, **kwargs):
    selection = await original(self, *args, **kwargs)
    selection.pop("options", None)
    return selection


HubBackend._model_selection = drop_options
raise SystemExit(pytest.main([
    "tests/test_hub_effort.py", "-q", "-p", "no:cacheprovider",
    "--basetemp=" + str(Path.cwd() / ".orchestra/tasks/V-1025/tmp/mutation"),
]))
