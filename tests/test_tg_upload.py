import io
import json
from pathlib import Path

import pytest
from fastapi import UploadFile
from starlette.responses import FileResponse

from app.routes import tg
from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB


@pytest.mark.asyncio
async def test_upload_route_accepts_file_between_old_and_new_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(tg, "_cleanup_uploads", lambda: None, raising=False)
    content = b"x" * (14 * 1024 * 1024)

    result = await tg.upload_file(UploadFile(io.BytesIO(content), filename="document.pdf"))

    assert result["path"].endswith(".pdf")
    assert (tmp_path / result["path"].split("/")[-1]).read_bytes() == content


@pytest.mark.asyncio
async def test_upload_route_rejects_above_shared_limit_with_named_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "UPLOADS_DIR", tmp_path)
    content = b"x" * (MAX_UPLOAD_BYTES + 1)

    response = await tg.upload_file(UploadFile(io.BytesIO(content), filename="too-large.pdf"))
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert payload["error"] == f"file too large (max {MAX_UPLOAD_MB} MB)"


@pytest.mark.asyncio
async def test_chart_route_serves_only_png_inside_chart_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "CHART_DIR", tmp_path)
    chart = tmp_path / "report.png"
    chart.write_bytes(b"png")

    response = await tg.serve_chart("report.png")
    assert isinstance(response, FileResponse)
    assert Path(response.path) == chart
    assert response.media_type == "image/png"

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"png")
    traversal = await tg.serve_chart("../outside.png")
    assert traversal.status_code == 403

    missing = await tg.serve_chart("missing.png")
    assert missing.status_code == 404
