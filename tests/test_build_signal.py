"""#15 T2 — сигнал версии фронта.

Проверяем ровно то, ради чего он существует: он обязан меняться при правке статики
БЕЗ перезапуска процесса и приезжать заголовком, не ломая тело /api/models.
"""

import pathlib

import pytest


class TestBuildId:
    def test_stable_between_calls(self):
        from app.deps import build_id
        assert build_id() == build_id()

    def test_changes_after_touching_static_without_restart(self, tmp_path, monkeypatch):
        """Главный сценарий: мерж поменял файл, процесс живой. Кеш на импорте убил бы сигнал."""
        import app.deps as deps
        static = tmp_path / "static"
        (static / "js").mkdir(parents=True)
        (static / "css").mkdir()
        f = static / "js" / "app.js"
        f.write_text("x")
        (static / "css" / "style.css").write_text("y")
        monkeypatch.setattr(deps, "_STATIC_DIR", static)

        before = deps.build_id()
        import os
        os.utime(f, (0, 0))          # заведомо другая mtime
        after = deps.build_id()
        assert after != before

    def test_ignores_vendor_files(self, tmp_path, monkeypatch):
        """Вендор меняется вручную и раз в месяцы — он не должен дёргать баннер."""
        import app.deps as deps
        import os
        static = tmp_path / "static"
        (static / "js").mkdir(parents=True)
        (static / "css" / "vendor").mkdir(parents=True)
        (static / "js" / "app.js").write_text("x")
        (static / "css" / "style.css").write_text("y")
        vendor = static / "css" / "vendor" / "marked.min.js"
        vendor.write_text("z")
        monkeypatch.setattr(deps, "_STATIC_DIR", static)

        before = deps.build_id()
        os.utime(vendor, (0, 0))
        assert deps.build_id() == before

    def test_no_static_dir_does_not_raise(self, tmp_path, monkeypatch):
        import app.deps as deps
        monkeypatch.setattr(deps, "_STATIC_DIR", tmp_path / "нет-такого")
        assert deps.build_id() == "0"


class TestModelsHeader:
    def test_header_present_and_body_unchanged(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
        from app.db import init_db
        init_db()
        from app.main import app
        with TestClient(app) as client:
            # .env с DASHBOARD_* попадает в окружение воркера и даёт 401 — гасим ПОСЛЕ
            # старта, lifespan подтягивает его обратно
            monkeypatch.delenv("DASHBOARD_USER", raising=False)
            monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
            r = client.get("/api/models")
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Orchestra-Build")
        from app.deps import build_id
        assert r.headers["X-Orchestra-Build"] == build_id()
        assert set(r.json()) == {"models", "provider_metadata", "proxy_connected"}


class TestTemplateCarriesBuild:
    def test_body_has_data_build(self):
        html = pathlib.Path("app/templates/dashboard.html").read_text()
        guard = pathlib.Path("app/templates/_globals.html").read_text()
        assert "data-build=" in html
        # #29 увёл страховку глобалов в _globals.html — литерал build_id живёт теперь там
        assert "build_id" in guard

    def test_survives_a_process_that_does_not_know_build_id(self):
        """Окно между мержем и рестартом: шаблон уже новый, процесс ещё старый.

        Без страховки Jinja бросает UndefinedError и дашборд отдаёт 500 — то есть
        мерж кладёт прод до тех пор, пока человек не перезапустит сервис.

        Здесь проверяется КОНКРЕТНО результат: атрибут на месте и пустой, потому что
        app.js читает `document.body.dataset.build`. Что вообще ни один шаблон не падает
        в таком окружении — отдельный страж, `tests/test_template_window.py`.
        """
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
        out = env.get_template("dashboard.html").render(
            currency_symbol="$", hide_thinking=False, is_auth_enabled=False, client_name="")
        assert 'data-build=""' in out
