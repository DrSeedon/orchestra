"""Telegram and dashboard media routes."""

import asyncio
import hashlib
import logging
import math
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.events import MessageProvenance
from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB

router = APIRouter()
logger = logging.getLogger("orchestra.routes.tg")

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


_voice_tasks: set[asyncio.Task] = set()


async def _report_voice_failure(row: dict, detail: str) -> None:
    """Keep failed audio on disk and route an actionable report to the owner."""
    from app.deps import manager
    from app.notify import report_undelivered

    outcome = await report_undelivered(
        manager,
        scope=row["scope"],
        worker=row["session_name"],
        what=(f"голосовое сообщение {row['voice_id']} не расшифровано; "
              f"аудио сохранено: {row['path']}"),
        reason=detail,
        dedupe_key=f"voice:{row['voice_id']}",
    )
    logger.error("voice %s transcription failure: %s", row["voice_id"], outcome)


async def _process_dashboard_voice(row: dict) -> None:
    from app.db import (
        dashboard_voice_mark_failed,
        dashboard_voice_mark_running,
        dashboard_voice_mark_sent,
    )
    from app.deps import manager
    from app.transcription import transcribe_audio

    voice_id = row["voice_id"]
    logger.info("voice %s background transcription started", voice_id)
    await asyncio.to_thread(dashboard_voice_mark_running, voice_id)
    try:
        path = Path(row["path"])
        duration = await _audio_duration_seconds(str(path))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("audio duration is invalid")
        if duration > VOICE_MAX_SECONDS:
            raise ValueError("recording is too long (max 5 minutes)")
        text, error = await transcribe_audio(
            str(path),
            f"dashboard-{voice_id}",
            session_name=row["session_name"],
            scope=row["scope"],
            content_type=row["content_type"],
        )
        if error:
            raise RuntimeError(error)
        text = text.strip()
        if not text:
            raise ValueError("speech was not recognized")
        session = await manager.ensure_loaded_by_id(row["session_id"])
        if not session:
            raise RuntimeError(f"target session {row['session_id']} is unavailable")
        provenance = MessageProvenance(
            origin="user", senders=("user",),
            subtype="dashboard_voice", ref=voice_id,
        )
        await manager.send(
            session.id, text, provenance=provenance,
        )
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        await asyncio.to_thread(dashboard_voice_mark_failed, voice_id, detail)
        await _report_voice_failure(row, detail)
        return
    await asyncio.to_thread(dashboard_voice_mark_sent, voice_id)
    try:
        Path(row["path"]).unlink()
    except OSError as error:
        logger.warning("voice %s sent but audio cleanup failed: %s: %s", voice_id, type(error).__name__, error)


def _schedule_dashboard_voice(row: dict) -> None:
    task = asyncio.create_task(_process_dashboard_voice(row))
    _voice_tasks.add(task)
    task.add_done_callback(_voice_tasks.discard)


async def resume_dashboard_voice_transcriptions() -> None:
    """Requeue accepted voice uploads left by a process restart."""
    from app.db import dashboard_voice_pending

    for row in await asyncio.to_thread(dashboard_voice_pending):
        _schedule_dashboard_voice(row)


async def _read_voice_upload(
    audio: UploadFile, *, reject_before_read: JSONResponse | None = None,
) -> tuple[bytes, str, str] | JSONResponse:
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    suffix = _VOICE_TYPES.get(content_type)
    if not suffix:
        return JSONResponse(
            {"error": f"unsupported audio type: {content_type or 'unknown'}"},
            status_code=415,
        )
    if reject_before_read is not None:
        return reject_before_read
    content = await audio.read(VOICE_MAX_BYTES + 1)
    await audio.close()
    if not content:
        return JSONResponse({"error": "audio is empty"}, status_code=400)
    if len(content) > VOICE_MAX_BYTES:
        return JSONResponse({"error": "audio is too large (max 10 MB)"}, status_code=413)
    return content, content_type, suffix


async def _submit_voice_for_sending(
    audio: UploadFile,
    session_name: str = Form(""),
    scope: str = Form(""),
):
    from app.db import dashboard_voice_enqueue
    from app.deps import manager

    target = manager.get_by_name(session_name, scope)
    upload = await _read_voice_upload(
        audio,
        reject_before_read=(
            None if target else JSONResponse(
                {"error": f"agent '{session_name}' not found"}, status_code=404,
            )
        ),
    )
    if isinstance(upload, JSONResponse):
        return upload
    content, content_type, suffix = upload

    voice_id = uuid.uuid4().hex
    path = UPLOADS_DIR / f"dashboard-voice-{voice_id}{suffix}"
    await asyncio.to_thread(path.write_bytes, content)
    await asyncio.to_thread(
        dashboard_voice_enqueue,
        voice_id, target.id, target.name, target.scope, str(path), content_type,
    )
    _schedule_dashboard_voice({
        "voice_id": voice_id,
        "session_id": target.id,
        "session_name": target.name,
        "scope": target.scope,
        "path": str(path),
        "content_type": content_type,
    })
    logger.info("voice %s accepted before background transcription", voice_id)
    return {"accepted": True, "voice_id": voice_id}


@router.post("/api/transcribe")
async def transcribe_upload(
    audio: UploadFile,
    session_name: str = Form(""),
    scope: str = Form(""),
    send: bool = Form(False),
):
    if send:
        return await _submit_voice_for_sending(audio, session_name, scope)
    upload = await _read_voice_upload(audio)
    if isinstance(upload, JSONResponse):
        return upload
    content, content_type, suffix = upload

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
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": f"file too large (max {MAX_UPLOAD_MB} MB)"}, status_code=400)
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
async def tg_send_file(req: dict, request: Request):
    from app.auth import validate_session
    from app.db import get_session
    from app.mcp_proof import check_mcp_proof
    from app.routes.system import _is_safe_path

    paths = req.get("paths")
    is_batch = paths is not None
    path = req.get("path", "")
    caption = str(req.get("caption", ""))
    as_document = bool(req.get("as_document", False))
    event_id = str(req.get("event_id", "")).strip()
    if is_batch and (
        not isinstance(paths, list)
        or not paths
        or not all(isinstance(item, str) and item for item in paths)
    ):
        return JSONResponse({"error": "paths must be a non-empty string list"}, status_code=400)
    if not is_batch and not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if not event_id:
        return JSONResponse({"error": "event_id required"}, status_code=400)
    unsafe_paths = [item for item in paths if not _is_safe_path(item)] if is_batch else []
    if unsafe_paths or (not is_batch and not _is_safe_path(path)):
        return JSONResponse({"error": "access denied"}, status_code=403)

    source_session_id = None
    if validate_session(request.cookies.get("session", "")):
        scope = str(req.get("scope", ""))
        sender = str(req.get("sender", ""))
    else:
        source_session_id = request.headers.get("x-orchestra-session-id", "").strip()
        proof = request.headers.get("x-orchestra-mcp-proof", "")
        source = get_session(source_session_id) if source_session_id else None
        if source is None or not check_mcp_proof(source_session_id, proof):
            return JSONResponse(
                {"error": {"code": "KEYED_AUTH_REQUIRED", "outcome_unknown": False}},
                status_code=403,
            )
        scope = str(source.get("scope") or "")
        sender = str(source.get("name") or "")

    from app import tg_bridge
    orch_name, thread_id = tg_bridge._resolve_topic(scope, sender)
    chat_id = int(tg_bridge.config.get("group_id") or 0)
    if not chat_id or not thread_id:
        return JSONResponse(
            {"error": {"code": "TG_TARGET_UNAVAILABLE", "outcome_unknown": False}},
            status_code=400,
        )
    targets = [{
        "target_kind": "primary",
        "chat_id": chat_id,
        "thread_id": thread_id,
    }]
    mirror = tg_bridge.config.get("mirrors", {}).get(orch_name) if orch_name else None
    if mirror and mirror.get("chat_id"):
        targets.append({
            "target_kind": "mirror",
            "chat_id": int(mirror["chat_id"]),
            "thread_id": mirror.get("topic_id"),
        })
    from app.tg_file_deliveries import (
        BatchValidationError,
        accept_file_batch,
        accept_file_delivery,
    )
    try:
        if is_batch:
            result, status, headers = await accept_file_batch(
                event_id=event_id,
                source_session_id=source_session_id,
                source_name=sender,
                source_scope=scope,
                source_paths=paths,
                caption=caption,
                as_document=as_document,
                orch_name=orch_name,
                targets=targets,
            )
        else:
            result, status, headers = await accept_file_delivery(
                event_id=event_id,
                source_session_id=source_session_id,
                source_name=sender,
                source_scope=scope,
                source_path=str(path),
                caption=caption,
                as_document=as_document,
                orch_name=orch_name,
                targets=targets,
            )
    except BatchValidationError as exc:
        return JSONResponse({
            "ok": False,
            "error": {
                "code": "BATCH_FILE_INVALID",
                "message": "batch rejected; no files were accepted",
                "retryable": False,
                "outcome_unknown": False,
                "invalid": exc.invalid,
            },
        }, status_code=400)
    except (OSError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result, status_code=status, headers=headers)


@router.get("/api/tg/file-deliveries/{event_id}")
async def tg_file_delivery_status(event_id: str, request: Request):
    """Return a file receipt only to its MCP owner or a dashboard operator."""
    from app.auth import validate_session
    from app.db import get_session
    from app.mcp_proof import check_mcp_proof
    from app import tg_file_deliveries

    if validate_session(request.cookies.get("session", "")):
        try:
            resource = tg_file_deliveries._resource(
                tg_file_deliveries._validate_event_id(event_id)
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if resource is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return resource

    source_id = request.headers.get("x-orchestra-session-id", "").strip()
    proof = request.headers.get("x-orchestra-mcp-proof", "")
    if not source_id or get_session(source_id) is None or not check_mcp_proof(source_id, proof):
        return JSONResponse(
            {"error": {"code": "KEYED_AUTH_REQUIRED", "outcome_unknown": False}},
            status_code=403,
        )
    try:
        validated_id = tg_file_deliveries._validate_event_id(event_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    row = tg_file_deliveries._row(validated_id)
    if row is not None and row["source_session_id"] != source_id:
        return JSONResponse(
            {"error": {"code": "KEYED_AUTH_REQUIRED", "outcome_unknown": False}},
            status_code=403,
        )
    resource = tg_file_deliveries.get_file_delivery(validated_id, source_id)
    if resource is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return resource
