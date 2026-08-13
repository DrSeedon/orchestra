"""Telegram and dashboard media routes."""

import asyncio
import hashlib
import math
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()

UPLOADS_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_BLOCKED_UPLOAD_EXTS = {".exe", ".sh", ".bat", ".cmd", ".ps1", ".py", ".js", ".php", ".rb", ".pl"}
VOICE_MAX_BYTES = 10 * 1024 * 1024
VOICE_MAX_SECONDS = 5 * 60
_VOICE_TYPES = {
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


async def _audio_duration_seconds(path: str) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise ValueError("audio duration check timed out")
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[:160]
        raise ValueError(f"invalid audio: {detail or 'ffprobe failed'}")
    try:
        return float(stdout.decode().strip())
    except ValueError as e:
        raise ValueError("invalid audio duration") from e


@router.post("/api/transcribe")
async def transcribe_upload(
    audio: UploadFile,
    session_name: str = Form(""),
    scope: str = Form(""),
):
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    suffix = _VOICE_TYPES.get(content_type)
    if not suffix:
        return JSONResponse(
            {"error": f"unsupported audio type: {content_type or 'unknown'}"},
            status_code=415,
        )
    content = await audio.read(VOICE_MAX_BYTES + 1)
    await audio.close()
    if not content:
        return JSONResponse({"error": "audio is empty"}, status_code=400)
    if len(content) > VOICE_MAX_BYTES:
        return JSONResponse({"error": "audio is too large (max 10 MB)"}, status_code=413)

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(content)
            temp_path = temp.name
        duration = await _audio_duration_seconds(temp_path)
        if not math.isfinite(duration) or duration <= 0:
            return JSONResponse({"error": "audio duration is invalid"}, status_code=400)
        if duration > VOICE_MAX_SECONDS:
            return JSONResponse({"error": "recording is too long (max 5 minutes)"}, status_code=413)

        from app.transcription import transcribe_audio
        digest = hashlib.sha256(content).hexdigest()
        text, error = await transcribe_audio(
            temp_path,
            f"dashboard-{digest}",
            session_name=session_name,
            scope=scope,
            content_type=content_type,
        )
        if error:
            status = 503 if "DEEPGRAM_API_KEY" in error else 502
            return JSONResponse({"error": f"transcription failed: {error}"}, status_code=status)
        if not text.strip():
            return JSONResponse({"error": "speech was not recognized"}, status_code=422)
        return {"text": text}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


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


@router.get("/api/tg/delivery-stats")
async def tg_delivery_stats():
    from app.tg_bridge import _tg_delivery_snapshots
    return _tg_delivery_snapshots()


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
