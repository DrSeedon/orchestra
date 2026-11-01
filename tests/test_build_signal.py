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
        from fastapi import Response
        from fastapi.encoders import jsonable_encoder
        from fastapi.testclient import TestClient
        monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
        from app.db import init_db
        init_db()
        from app.main import app
        from app.routes import system
        with TestClient(app) as client:
            # .env с DASHBOARD_* попадает в окружение воркера и даёт 401 — гасим ПОСЛЕ
            # старта, lifespan подтягивает его обратно
            monkeypatch.delenv("DASHBOARD_USER", raising=False)
            monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
            endpoint_payload = client.portal.call(system.list_models, Response())
            r = client.get("/api/models")
            # Compare the transport body to the endpoint, including future additive fields.
            assert r.json() == jsonable_encoder(endpoint_payload)
            # Changing only the header's version must not change the JSON payload.
            monkeypatch.setattr(system, "build_id", lambda: "next-build-for-header-check")
            changed_header = client.get("/api/models")
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Orchestra-Build")
        from app.deps import build_id
        assert r.headers["X-Orchestra-Build"] == build_id()
        assert changed_header.status_code == 200, changed_header.text
        assert changed_header.headers["X-Orchestra-Build"] == "next-build-for-header-check"
        assert changed_header.headers["X-Orchestra-Build"] != r.headers["X-Orchestra-Build"]
        assert changed_header.json() == jsonable_encoder(endpoint_payload)

    @pytest.mark.parametrize("corruption", ["transport_body", "header_in_body"])
    def test_body_integrity_check_rejects_response_corruption(self, tmp_path, monkeypatch, corruption):
        from app.main import app
        from app.routes import system

        endpoint = system.list_models
        calls = []

        async def corrupt_body(response):
            payload = await endpoint(response)
            version = system.build_id()
            calls.append(version)
            payload["header_integrity_probe"] = version if corruption == "header_in_body" else True
            return payload

        route = next(route for route in app.routes
                     if getattr(route, "path", None) == "/api/models"
                     and "GET" in getattr(route, "methods", ()))
        # Transport-only corruption is absent from the direct endpoint baseline.
        monkeypatch.setattr(route.dependant, "call", corrupt_body)
        if corruption == "header_in_body":
            # Both paths agree initially, but changing the header must expose the leak.
            monkeypatch.setattr(system, "list_models", corrupt_body)
        with pytest.raises(AssertionError):
            self.test_header_present_and_body_unchanged(tmp_path, monkeypatch)
        assert len(calls) == (3 if corruption == "header_in_body" else 1)
        if corruption == "header_in_body":
            assert calls[0] != calls[-1]

    def test_head_carries_same_build_header_with_empty_body(self, tmp_path, monkeypatch):
        """Проверка не «метод разрешён», а «заголовок тот же»: heartbeat читает только его,
        и без заголовка баннер обновления замолчал бы, не сломавшись."""
        from fastapi.testclient import TestClient
        monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
        from app.db import init_db
        init_db()
        from app.main import app
        with TestClient(app) as client:
            monkeypatch.delenv("DASHBOARD_USER", raising=False)
            monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
            head = client.head("/api/models")
            get = client.get("/api/models")
        assert head.status_code == 200, head.text
        assert head.headers.get("X-Orchestra-Build")
        assert head.headers["X-Orchestra-Build"] == get.headers["X-Orchestra-Build"]
        assert head.content == b""


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
