"""Telegram-related routes: uploads and file forwarding to TG."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()

UPLOADS_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_BLOCKED_UPLOAD_EXTS = {".exe", ".sh", ".bat", ".cmd", ".ps1", ".py", ".js", ".php", ".rb", ".pl"}


@router.post("/api/upload")
async def upload_file(file: UploadFile):
    ext = Path(file.filename or "image.png").suffix or ".png"
    if ext.lower() in _BLOCKED_UPLOAD_EXTS:
        return JSONResponse({"error": f"file type {ext} not allowed"}, status_code=400)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        return JSONResponse({"error": "file too large (max 10MB)"}, status_code=400)
    h = hashlib.md5(content).hexdigest()[:12]
    name = f"{h}{ext}"
    path = UPLOADS_DIR / name
    if not path.exists():
        path.write_bytes(content)
    from app.tg_bridge import _cleanup_uploads
    _cleanup_uploads()
    return {"path": str(path), "url": f"/uploads/{name}"}


@router.get("/uploads/{filename:path}")
async def serve_upload(filename: str):
    from starlette.responses import FileResponse
    path = (UPLOADS_DIR / filename).resolve()
    try:
        path.relative_to(UPLOADS_DIR.resolve())
    except ValueError:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not path.exists() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


@router.post("/api/tg/send_file")
async def tg_send_file(req: dict):
    from app.routes.system import _is_safe_path
    path = req.get("path", "")
    caption = req.get("caption", "")
    scope = req.get("scope", "")
    sender = req.get("sender", "")
    as_document = req.get("as_document", False)
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from app.tg_bridge import send_file_to_tg
    result = await send_file_to_tg(path, caption, scope, sender, as_document=as_document)
    if result.get("error"):
        return JSONResponse(result, status_code=500)
    return result
