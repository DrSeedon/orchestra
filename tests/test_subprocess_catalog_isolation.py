"""Сервер из module-фикстуры не должен видеть настоящий каталог проектов.

24.09.2026 uvicorn, поднятый такой фикстурой, унаследовал окружение без песочницы
и выполнил `migrate_v621()` над настоящими путями: коммит в ветке воркера и в чужом
проекте /opt/cog-second-brain.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def module_env():
    # Снимок до function-фикстур — ровно то, что получает подпроцесс module-фикстуры.
    return os.environ.copy()


def test_module_fixture_subprocess_resolves_catalog_outside_real_paths(module_env):
    out = subprocess.run(
        [sys.executable, "-c",
         "from app.project_catalog import catalog_path, own_catalog_path;"
         "print(catalog_path());print(own_catalog_path('/opt/cog-second-brain'))"],
        cwd=str(ROOT), env=module_env, capture_output=True, text=True, check=True,
    ).stdout.split()
    home, foreign = (Path(line).resolve() for line in out)
    assert ROOT not in home.parents
    assert not str(foreign).startswith("/opt/cog-second-brain")
