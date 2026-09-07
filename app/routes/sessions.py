"""Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""

import asyncio
import hashlib
import json
import logging
import math
import re
import sqlite3
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from app.db import (
    get_all_sessions,
    get_history_logs,
    get_log,
    get_logs,
    get_logs_before,
    get_logs_sync,
    get_runtime_handoff,
    get_session as get_session_row,
    get_session_by_name,
)
from app.deps import manager
from app.errtext import err_text
from app.events import MessageProvenance
from app.models import ensure_dashboard_visible, ensure_spawn_allowed, resolve_model, MODELS
from app.manager import LifecycleQuarantineError
from app.quota_gate import QuotaGateError
from app.routes.errors import keyed_auth_required
from app.session import AgentStatus
from app.session_state import empty_context
from app.status_policy import is_internal_telemetry_status
from app.user_message_display import add_user_message_time_prefix, annotate_user_message

logger = logging.getLogger("orchestra.sessions")

router = APIRouter()

async def _wait_for_merge_idle(session) -> bool:
    """Wait for the current turn's explicit terminal signal; only IDLE is ready."""
    if session.status.value == "idle":
        return True
    if not session.loaded or session.status.value != "running":
        return False
    return await session.wait_for_turn_completion()


def _existing_branch_verdict(worktree_path: str, branch: str, scope: str,
                             force: bool) -> dict:
    """Что делать с УЖЕ существующей целевой веткой при возврате воркера на задачу (#61).

    Три исхода в словаре #17:
    - ветки нет → обычный путь;
    - есть, и наша запись о мерже доказывает, что её содержимое в базе → пересоздать
      от базы (BENIGN): после сквоша слияние базы в такую ветку конфликтует ровно там,
      где база доработала те же строки;
    - есть, запись о мерже указывает ДРУГУЮ голову → после мержа на ветке появилась
      работа, и пересоздание её уничтожит (FATAL), пока человек не скажет force.

    Записи о мерже нет вовсе (ветка старше таблицы или мержилась руками) → прежний путь:
    решать за человека, что его работа не нужна, платформа не вправе.
    """
    from app.db import find_merge_proof
    from app.workspace import _inspect_branch_ref, _resolve_repo, inspect_worktree_identity

    # Политика ДОБАВЛЯЕТ путь, а не отменяет старый: если репозиторий не читается,
    # решение просто не принимается, и всё идёт как раньше — иначе непрочитанный worktree
    # ломал бы любой switch, включая те, что работали годами.
    try:
        repo = _resolve_repo(worktree_path, worktree_path)
    except Exception as e:
        logger.warning("switch verdict skipped for %s: %s: %s",
                       worktree_path, type(e).__name__, e)
        return {"recreate_from_base": False, "discard_current": force}
    # Уйти с ТЕКУЩЕЙ ветки мешает та же слепота: её содержимое тоже слито сквошем, и
    # проверка деревьев считает его неподтверждённым. Та же запись об операции — то же
    # доказательство, и тогда покидать ветку можно без ручного force.
    discard_current = force
    if not discard_current:
        try:
            current_branch, current_head = inspect_worktree_identity(worktree_path)
        except RuntimeError:
            current_branch, current_head = "", ""
        current_proof = find_merge_proof(scope, current_branch) if current_branch else None
        discard_current = bool(current_proof and current_head in current_proof["heads"])

    try:
        head = _inspect_branch_ref(repo, branch)
    except RuntimeError as e:
        logger.warning("switch verdict skipped for %s: %s", branch, e)
        return {"recreate_from_base": False, "discard_current": discard_current}
    if head is None:
        return {"recreate_from_base": False, "discard_current": discard_current}
    if force:
        return {"recreate_from_base": True, "discard_current": True}
    proof = find_merge_proof(scope, branch)
    if not proof:
        return {"recreate_from_base": False, "discard_current": discard_current}
    if head in proof["heads"]:
        return {"recreate_from_base": True, "discard_current": discard_current}
    return {
        "ok": False,
        "state": "branch_has_work_after_merge",
        "error": (
            f"branch '{branch}' has commits made after it was merged (head {head}, "
            f"merged {', '.join(proof['heads'])}, operation {proof['operation_id']}) — "
            f"recreating this target branch from base would discard its commits; "
            "the worker's current branch is unaffected; pass force=true to discard"
        ),
    }


def _session_base_branch(session, requested: str = "") -> str:
    """Resolve an explicit or persisted lifecycle base against the actual repository."""
    from app.workspace import resolve_base_branch

    worktree_path = session.worktree_path
    if not worktree_path:
        raise ValueError("session has no worktree")
    return resolve_base_branch(worktree_path, requested or getattr(session, "base_branch", ""))


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-5[1m]"
    scope: Optional[str] = None
    system_prompt: str = ""
    use_worktree: bool = False
    repo_path: Optional[str] = None
    is_orchestrator: bool = False
    role: str = ""
    task_id: str = ""
    description: str = ""
    base_branch: str = ""
    parent_name: str = ""
    mcp_servers: dict = {}
    pipeline: str = ""
    profile: str = ""
    owned_dirs: list[str] = []
    tg_topic: bool = False
    planned_initial_turn: bool = False
    initial_task_title: str = ""
    model_policy_override_reason: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", v):
            raise ValueError("name must be alphanumeric with ._- allowed, 1-50 chars")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        resolved = resolve_model(v)
        if resolved not in MODELS:
            raise ValueError(f"unknown model '{v}'. Available: {', '.join(MODELS.keys())}")
        return resolved

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, v):
        if not Path(v).is_dir():
            raise ValueError(f"cwd does not exist: {v}")
        return v

    @model_validator(mode="after")
    def validate_worktree(self):
        if self.use_worktree and not self.repo_path:
            raise ValueError("repo_path required when use_worktree=True")
        return self


class SendRequest(BaseModel):
    message: str
    scope: str
    sender: str | None = None
    wake: bool = True
    delivery_id: str = ""
    # #219 T1b: класс сообщения ребёнка. Необязательное поле с совместимым
    # умолчанием — старые процессы `mcp_stdio.py` живут до реконнекта и его не
    # пошлют (грабля #215/#217). Неизвестное значение → буферизуем (fail-closed).
    message_kind: str | None = None


class InitialDeliveryRequest(BaseModel):
    delivery_id: str
    message: str
    scope: str
    sender: str


class ScopeRequest(BaseModel):
    scope: str


# Точка на измеренной кривой, а не «разумное значение»: 5 мин снимают 2.06% расхода
# платформы, 30 мин — 4.35%, 60 мин — 4.94% (.orchestra/tasks/231/research.md §3.7).
# Дедлайн покупается задержкой, поэтому вызывающий вправе выбрать свою точку.
DEFAULT_FAN_DEADLINE_SECONDS = 1800.0


class OpenFanRequest(BaseModel):
    fan_id: str
    parent_name: str
    scope: str
    children: list[str]
    deadline_seconds: float | None = None
    reducer: str | None = None

    @field_validator("deadline_seconds")
    @classmethod
    def validate_deadline(cls, v):
        # NaN даёт веер, который не истечёт НИКОГДА: `deadline_at <= ?` для NaN ложно
        # при любом времени. Отрицательный — веер, истёкший до рождения.
        if v is None:
            return v
        if not math.isfinite(v):
            raise ValueError("deadline_seconds must be finite")
        if v < 0 or v > 86400:
            raise ValueError("deadline_seconds must be within [0, 86400]")
        return v


class FanMemberTerminalRequest(BaseModel):
    fan_id: str
    child: str
    state: str
    summary: str = ""


def _conditional(request: Request, payload) -> Response:
    """Отдать payload с ETag, а при совпадении If-None-Match — пустой 304.

    Дашборд опрашивает `/api/sessions` каждые 3 секунды, и ответ весит 48.8 КБ даже когда
    ничего не изменилось (замер 21.08) — почти мегабайт в минуту и один из ШЕСТИ браузерных
    слотов, из которых один навсегда занят SSE. Условный запрос убирает тело целиком, пока
    состояние агентов не поменялось; ключ считается от самого ответа, поэтому рассинхрон
    невозможен by design. `no-cache` означает «кешируй, но всегда переспрашивай» — без него
    браузер не пришлёт If-None-Match.
    """
    body = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    tag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
    headers = {"ETag": tag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


@router.get("/api/sessions")
async def list_sessions(request: Request, scope: Optional[str] = None):
    # Snapshotting 80+ live/persisted sessions performs two SQLite reads and JSON-ready
    # projection. Keep that work off the event loop so one cold disk/swap page cannot freeze
    # SSE and make every browser retry the same request at once.
    payload = await asyncio.to_thread(manager.list_sessions, scope)
    return _conditional(request, payload)


@router.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
    from app.routes.system import _is_safe_path
    if not _is_safe_path(req.cwd):
        return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
    scope = req.scope or req.cwd
    try:
        session = await manager.create_session(
            name=req.name,
            scope=scope,
            cwd=req.cwd,
            model=req.model,
            system_prompt=req.system_prompt,
            use_worktree=req.use_worktree,
            repo_path=req.repo_path,
            is_orchestrator=req.is_orchestrator,
            role=req.role,
            task_id=req.task_id,
            description=req.description,
            base_branch=req.base_branch,
            parent_name=req.parent_name,
            mcp_servers=req.mcp_servers,
            pipeline=req.pipeline,
            profile=req.profile,
            owned_dirs=req.owned_dirs,
            tg_topic=req.tg_topic,
            planned_initial_turn=req.planned_initial_turn,
            initial_task_title=req.initial_task_title,
            model_policy_override_reason=req.model_policy_override_reason,
        )
        d = session.to_dict()
        if session.task_id:
            from app import tm as _tm
            with _tm._conn() as connection:
                project = _tm.get_project_by_scope(connection, scope)
                task_row = (
                    _tm.resolve_task_ref(connection, session.task_id, project["id"])
                    if project else None
                )
            if task_row:
                d["task"] = _tm.task_dto(task_row)
        if req.use_worktree:
            d["repo_path"] = session._spawn_repo_path
            d["git_common_dir"] = session._spawn_git_common_dir
        if session._spawn_warning:
            d["spawn_warning"] = session._spawn_warning
        return d
    except QuotaGateError as e:
        return JSONResponse(e.envelope(), status_code=e.status_code)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except sqlite3.IntegrityError:
        return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)
    except Exception as e:
        import traceback
        logger.error(f"spawn failed: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/sessions/{name}")
async def get_session(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    # detached: raw DB row keeps legacy response shape (richer than to_dict)
    return found.to_dict() if found.loaded else found.db_row


@router.post("/api/sessions/{name}/initial-deliveries", status_code=202)
async def accept_initial_delivery(name: str, req: InitialDeliveryRequest):
    found = manager.get_by_name(name, req.scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)

    from app import initial_deliveries

    try:
        provenance = MessageProvenance(
            origin="agent", senders=(req.sender,), subtype="initial_delivery",
            ref=req.delivery_id,
        )
        resource, status_code = await initial_deliveries.accept_initial_delivery(
            delivery_id=req.delivery_id,
            session_id=found.id,
            worker_name=found.name,
            scope=req.scope,
            sender=req.sender,
            message=req.message,
            provenance=provenance,
        )
    except sqlite3.DatabaseError:
        if initial_deliveries.get_initial_delivery(req.delivery_id, req.scope) is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "DELIVERY_ACCEPT_REJECTED",
                        "message": "delivery acceptance was not committed; retry is safe",
                        "outcome_unknown": False,
                        "retryable": True,
                        "details": {"commit_state": "NOT_COMMITTED"},
                    }
                },
                status_code=503,
            )
        raise
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(resource, status_code=status_code)


@router.get("/api/initial-deliveries/{delivery_id}")
async def get_initial_delivery(delivery_id: str, scope: str):
    from app import initial_deliveries

    try:
        resource = initial_deliveries.get_initial_delivery(delivery_id, scope)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if resource is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return resource


@router.get("/api/sessions/{name}/prompt")
async def get_session_prompt(name: str, scope: str):
    from app.prompting import read_prompt as _read_prompt
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sp = found.system_prompt or ""
    is_orch = found.is_orchestrator or False
    base = _read_prompt("base.md")
    base_len = len(base)
    role = ""
    custom = ""
    rest = sp[base_len:].lstrip("\n") if sp[:base_len] == base else sp
    if not is_orch:
        marker = "- Branch: "
        idx = rest.rfind(marker)
        if idx != -1:
            after_marker = rest.find("\n", idx)
            if after_marker != -1:
                role = rest[:after_marker + 1].strip()
                custom = rest[after_marker + 1:].strip()
            else:
                role = rest.strip()
        else:
            role = rest.strip()
    else:
        role = rest.strip()
    return {"system_prompt": sp, "base": base, "role": role, "custom": custom}


_SOURCE_BLOCKS = [
    ("file",   "base",   "Platform Base",       "prompts/base.md",              "<platform>",       "</communication-style>", 1),
    ("file",   "role",   "Role",                "prompts/roles/*.md",           "<role>",           "</role>",           1),
    ("module", "module", "Git Workflow",         "prompts/modules/git-workflow.md",  "<git-workflow>",   "</git-workflow>",   1),
    ("module", "module", "Orchestration",        "prompts/modules/orchestration.md", "<orchestration>",  "</orchestration>",  1),
    ("module", "module", "Background Jobs",      "prompts/modules/background-jobs.md","<background-jobs>","</background-jobs>",2),
    ("module", "module", "Task Management",      "prompts/modules/task-management.md","<task-management>","</task-management>",1),
    ("module", "module", "Report Format",        "prompts/modules/report-format.md", "<report-format>",  "</report-format>",  1),
    ("module", "module", "Codex Review",         "prompts/modules/codex-review.md",  "<codex-review>",   "</codex-review>",   1),
    ("module", "module", "Before Work",          "prompts/modules/before-work.md",   "<before-work>",    "</before-work>",    1),
    ("module", "module", "Before Done",          "prompts/modules/before-done.md",   "<before-done>",    "</before-done>",    1),
    ("dynamic","dynamic","Identity",             "manager.py",                   "<identity>",       "</identity>",       1),
]


def _parse_prompt_blocks(text: str) -> list[dict]:
    """Split system prompt into blocks by SOURCE (files/modules/dynamic), not XML tags."""
    import re
    blocks = []
    consumed = set()

    for btype, tag, title, source, open_tag, close_tag, nth in _SOURCE_BLOCKS:
        start = -1
        pos = 0
        for _ in range(nth):
            idx = text.find(open_tag, pos)
            if idx == -1:
                break
            start = idx
            pos = idx + len(open_tag)
        if start == -1:
            continue
        end = text.find(close_tag, start + len(open_tag))
        if end == -1:
            continue
        end += len(close_tag)
        content = text[start:end].strip()
        if title == "Role":
            role_match = re.search(r'## Role:\s*(.+)', content)
            if role_match:
                title = f"Role: {role_match.group(1).strip()}"
        blocks.append({
            "type": btype, "tag": tag, "title": title,
            "source": source, "size": len(content), "content": content,
            "_start": start, "_end": end,
        })
        consumed.update(range(start, end))

    tail = []
    pos = 0
    for b in sorted(blocks, key=lambda x: x["_start"]):
        gap = text[pos:b["_start"]].strip()
        if gap:
            tail.append(gap)
        pos = b["_end"]
    remaining = text[pos:].strip()
    if remaining:
        tail.append(remaining)
    tail_text = "\n\n".join(tail)

    if tail_text:
        sections = re.split(r'(?=^## )', tail_text, flags=re.MULTILINE)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            heading = sec.split('\n')[0].strip('#').strip()[:80] or "Text"
            blocks.append({
                "type": "dynamic", "tag": "dynamic", "title": heading,
                "source": "manager.py", "size": len(sec), "content": sec,
                "_start": 999999,
            })

    blocks.sort(key=lambda x: x.get("_start", 999999))
    for b in blocks:
        b.pop("_start", None)
        b.pop("_end", None)
    return blocks


@router.get("/api/sessions/{name}/prompt-blocks")
async def get_prompt_blocks(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sp = found.system_prompt or ""
    if not sp.strip():
        return []
    return _parse_prompt_blocks(sp)


@router.get("/api/sessions/{name}/context")
async def get_session_context(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return empty_context()
    if not found.loaded:
        return {"percentage": found._last_context.get("percentage", 0),
                "total_tokens": found._last_context.get("total_tokens", 0),
                "max_tokens": 200000}
    return await found.get_context()


@router.get("/api/sessions/{name}/stream")
async def stream_session_logs(name: str, scope: str, request: Request, after_id: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    import json
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    stored = get_session_row(session_id)

    def with_status(payload: dict) -> dict:
        # Живую сессию перерешаем на КАЖДОМ событии: на коннекте её может не быть в
        # реестре (idle-воркер не загружен), а через минуту её грузит `ensure_loaded`
        # и она идёт ход по ЭТОМУ же стриму. Клиент верит `agent_status` каждого
        # события, поэтому статус, замороженный на коннекте, затирал бы верный.
        live_session = manager.get(session_id)
        status = (
            live_session.status.value
            if live_session is not None
            else str((stored or {}).get("status") or "idle")
        )
        result = annotate_user_message({**payload, "agent_status": status})
        if payload.get("type") == "status":
            result["status_hidden"] = is_internal_telemetry_status(
                str(payload.get("content") or "")
            )
        return result

    async def event_generator():
        from app.db import _conn
        from app.live_broker import STREAM_CLOSE, broker
        last_id = after_id
        c = _conn()
        q = broker.subscribe(session_id)  # session_id == manager.get_session_id == session.id
        try:
            # Первым делом называем сессию, которую мы разрешили из name+scope. Клиент
            # держит историю по session_id и до этого события знает её лишь по своей карте,
            # которая могла устареть (агента убили и подняли под тем же именем). Правду
            # знает только сервер, и он обязан сказать её ДО первой строки истории.
            yield f"data: {json.dumps(with_status({'type': '__session', 'session_id': session_id}))}\n\n"
            # initial history first (one-shot) — preserves load-more behavior
            if after_id == 0:
                for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
                    yield f"data: {json.dumps(with_status(log))}\n\n"
                    last_id = log["id"]
            while True:
                if await request.is_disconnected():
                    return
                # 1) drain live partials FIRST (ephemeral, no id) — they always
                #    precede their final 'text' row, so emit before polling DB.
                drained = 0
                while drained < 500:  # cap per tick — don't starve disconnect check
                    try:
                        payload = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if payload is STREAM_CLOSE:
                        return
                    yield f"data: {json.dumps(with_status(payload))}\n\n"
                    drained += 1
                # 2) DB-persisted logs (finals + all other log types)
                logs = get_logs(session_id, after_id=last_id, conn=c)
                for log in logs:
                    yield f"data: {json.dumps(with_status(log))}\n\n"
                    last_id = log["id"]
                # 3) short poll while active (partials follow quickly), back off when idle
                await asyncio.sleep(0.1 if (logs or drained) else 0.5)
        finally:
            broker.unsubscribe(session_id, q)
            c.close()
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/sessions/{name}/logs")
async def get_session_logs(name: str, response: Response, scope: str,
                           after_id: int = 0, before_id: int = 0,
                           limit: int = 500, max_bytes: int = 0, cap: int = 0):
    # Live chat snapshots are authoritative state, not an asset. A browser/intermediary
    # replaying an older 200 here recreates the exact "old messages, then SSE catches up"
    # staircase that the network-first client is designed to eliminate.
    response.headers["Cache-Control"] = "no-store"
    limit = min(limit, 1000)
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)

    def annotate(log: dict) -> dict:
        result = annotate_user_message(log)
        if result.get("type") != "status":
            return result
        return {
            **result,
            "status_hidden": is_internal_telemetry_status(
                str(log.get("content") or "")
            ),
        }

    if before_id > 0:
        logs = get_logs_before(session_id, before_id, limit,
                               max(0, min(max_bytes, 1 << 20)),
                               max(0, min(cap, 1 << 20)))
    else:
        logs = get_logs(session_id, after_id=after_id)
    return [annotate(log) for log in logs]


@router.get("/api/logs/sync")
async def logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384):
    """Зеркало журнала для браузера: все сессии всех проектов одним ответом.

    Scope не принимает намеренно — пользователь один, а логи ключуются по session_id.
    ``tail=0`` — карта сессий без строк журнала; дашборд ходит именно так с #72, потому
    что предзагрузка на все сессии стоила 145 КБ по проводу, а рисовалось из неё ~5%.
    Инкремент (after_id > 0) tail игнорирует и весит единицы КБ.
    """
    return get_logs_sync(after_id=max(after_id, 0),
                         tail=max(0, min(tail, 200)),
                         cap=max(256, min(cap, 1 << 20)))


@router.get("/api/logs/{log_id}")
async def get_single_log(log_id: int):
    """Одна строка журнала целиком — для кнопки «загрузить целиком» под обрезанной (#74).

    Объявлен ПОСЛЕ /api/logs/sync намеренно: маршруты разбираются по порядку, и путь
    ``sync`` должен достаться своему обработчику, а не свалиться сюда с 422.
    """
    row = get_log(log_id)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return annotate_user_message(row)


@router.post("/api/fan/open")
async def open_fan(req: OpenFanRequest):
    """#231 T1: единственный вход в барьер #219 — до этого `open_fan()` не звал никто.

    Родитель объявляет веер сразу после спавна детей: пока веер открыт, их отчёты
    копятся, и родитель просыпается один раз вместо N. Замер выгоды и кривая по
    дедлайну — `.orchestra/tasks/231/research.md` §3.7.
    """
    from app import fan_barrier
    deadline = (
        req.deadline_seconds
        if req.deadline_seconds is not None
        else DEFAULT_FAN_DEADLINE_SECONDS
    )
    fan_barrier.open_fan(
        fan_id=req.fan_id,
        parent_name=req.parent_name,
        scope=req.scope,
        children=req.children,
        deadline_seconds=deadline,
        reducer=req.reducer or "",
    )
    fan_barrier.schedule_deadline(req.fan_id)
    return {"ok": True, "fan_id": req.fan_id, "children": len(req.children)}


@router.post("/api/fan/member/terminal")
async def mark_fan_member_terminal(req: FanMemberTerminalRequest):
    from app import fan_barrier

    released = fan_barrier.record_terminal(
        req.child,
        req.state,
        summary=req.summary,
        fan_id=req.fan_id,
    )
    if released:
        target = fan_barrier.parent_of(req.fan_id)
        if target:
            recipient = fan_barrier.reducer_of(req.fan_id) or target[0]
            destination = await manager.ensure_loaded(recipient, target[1])
            if destination is not None:
                provenance = MessageProvenance(
                    origin="platform", senders=("Orchestra",),
                    subtype="fan_manifest", ref=req.fan_id,
                )
                await manager.send(
                    destination.id, fan_barrier.manifest_text(req.fan_id),
                    provenance=provenance,
                )
    return {"ok": True, "fan_id": req.fan_id, "released": released}


@router.post("/api/sessions/{name}/send")
async def send_message(name: str, req: SendRequest, request: Request = None):
    try:
        if req.delivery_id.strip():
            if not req.wake or req.message_kind is not None:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "UNSUPPORTED_KEYED_INGRESS",
                            "message": "keyed receipts support waking direct messages only",
                            "outcome_unknown": False,
                        },
                    },
                    status_code=400,
                )
            from app.mcp_proof import check_mcp_proof
            from app.auth import validate_session
            import os

            source_id = (request.headers.get("x-orchestra-session-id", "")
                         if request is not None else "").strip()
            proof = (request.headers.get("x-orchestra-mcp-proof", "")
                     if request is not None else "")
            source = get_session_row(source_id) if source_id else None
            operator = bool(
                request is not None
                and validate_session(request.cookies.get("session", ""))
            )
            if operator:
                source_id = ""
                source = None
            elif not source or not check_mcp_proof(source_id, proof):
                return keyed_auth_required(
                    "keyed delivery requires a valid MCP proof", include_ok=True,
                )
            if not operator and req.sender is not None and req.sender != source["name"]:
                return keyed_auth_required()
            if not operator and req.scope != source["scope"]:
                return keyed_auth_required()
            source_is_orchestrator = bool(
                source and (
                    source.get("is_orchestrator")
                    or source.get("role") in {"orchestrator", "sub-orchestrator"}
                )
            )
            from app import message_deliveries

            try:
                delivery_id = message_deliveries._validate_id(req.delivery_id)
            except ValueError as error:
                return JSONResponse(
                    {
                        "error": {
                            "code": "INVALID_DELIVERY_ID",
                            "message": str(error),
                            "outcome_unknown": False,
                        }
                    },
                    status_code=400,
                )
            source_principal = (
                f"operator:{os.environ.get('DASHBOARD_USER', '')}"
                if operator else f"mcp:{source_id}"
            )
            source_name = source["name"] if source else ""
            source_scope = source["scope"] if source else req.scope
            source_task_id = (source.get("task_id") or "") if source else ""
            rendered = req.message if operator else f"[from:{source_name}] {req.message}"
            provenance = MessageProvenance(
                origin="user" if operator else "agent",
                senders=("user" if operator else source_name,),
                subtype="direct_message", ref=delivery_id,
            )

            existing = message_deliveries._row(delivery_id)
            if existing is not None:
                if not operator and existing["source_session_id"] != source_id:
                    return keyed_auth_required()
                if name != existing["target_name"]:
                    conflict, conflict_status = message_deliveries._conflict(delivery_id)
                    return JSONResponse(conflict, status_code=conflict_status)
                if existing["state"] == "FAILED_BEFORE_SUBMIT":
                    async with manager.get_session_lock(existing["target_session_id"]):
                        await manager.preflight_message_delivery(
                            existing["target_session_id"],
                        )
                        resource, status_code = (
                            await message_deliveries.accept_message_delivery(
                                delivery_id=delivery_id,
                                source_session_id=source_id or None,
                                source_principal=source_principal,
                                source_name=source_name,
                                source_scope=source_scope,
                                source_task_id=source_task_id,
                                target_session_id=existing["target_session_id"],
                                target_name=existing["target_name"],
                                target_scope=existing["target_scope"],
                                target_task_id=existing["target_task_id"],
                                target_generation=existing["target_generation"],
                                message=req.message,
                                rendered_message=rendered,
                                message_kind=req.message_kind,
                                wake=req.wake,
                                provenance=provenance,
                            )
                        )
                else:
                    resource, status_code = await message_deliveries.accept_message_delivery(
                        delivery_id=delivery_id,
                        source_session_id=source_id or None,
                        source_principal=source_principal,
                        source_name=source_name,
                        source_scope=source_scope,
                        source_task_id=source_task_id,
                        target_session_id=existing["target_session_id"],
                        target_name=existing["target_name"],
                        target_scope=existing["target_scope"],
                        target_task_id=existing["target_task_id"],
                        target_generation=existing["target_generation"],
                        message=req.message,
                        rendered_message=rendered,
                        message_kind=req.message_kind,
                        wake=req.wake,
                        provenance=provenance,
                    )
                return JSONResponse(resource, status_code=status_code)

            known_targets = get_all_sessions(include_archived=True)
            exact_archived = any(
                row["name"] == name
                and row["scope"].rstrip("/") == req.scope.rstrip("/")
                and row["status"] == "archived"
                for row in known_targets
            )
            exact_active = any(
                row["name"] == name
                and row["scope"].rstrip("/") == req.scope.rstrip("/")
                and row["status"] != "archived"
                for row in known_targets
            )
            target = manager.get_by_name(name, req.scope)
            if not exact_active:
                target = None
            if target is None:
                candidates = [
                    row for row in get_all_sessions(include_archived=True)
                    if row["name"] == name and row["status"] != "archived"
                ]
                if exact_archived or not candidates:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "TARGET_NOT_FOUND",
                                "message": f"agent '{name}' not found",
                                "outcome_unknown": False,
                            }
                        },
                        status_code=404,
                    )
                if not source_is_orchestrator and not operator:
                    return keyed_auth_required(
                        "cross-project target requires an orchestrator proof",
                    )
                if len(candidates) != 1:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "TARGET_NAME_AMBIGUOUS",
                                "message": f"target name '{name}' is ambiguous across projects",
                                "outcome_unknown": False,
                            }
                        },
                        status_code=409,
                    )
                candidate = candidates[0]
                target = manager.get_by_name(candidate["name"], candidate["scope"])
            if target is None:
                return JSONResponse(
                    {
                        "error": {
                            "code": "TARGET_NOT_FOUND",
                            "message": f"agent '{name}' not found",
                            "outcome_unknown": False,
                        }
                    },
                    status_code=404,
                )
            async with manager.get_session_lock(target.id):
                await manager.preflight_message_delivery(target.id)
                target_generation = (
                    f"session={target.id}|task={getattr(target, 'task_id', '')}|"
                    f"branch={getattr(target, 'branch', '')}|"
                    f"needs_switch={int(bool(getattr(target, 'needs_switch', False)))}"
                )
                resource, status_code = await message_deliveries.accept_message_delivery(
                    delivery_id=delivery_id,
                    source_session_id=source_id or None,
                    source_principal=source_principal,
                    source_name=source_name,
                    source_scope=source_scope,
                    source_task_id=source_task_id,
                    target_session_id=target.id,
                    target_name=target.name,
                    target_scope=target.scope,
                    target_task_id=getattr(target, "task_id", "") or "",
                    target_generation=target_generation,
                    message=req.message,
                    rendered_message=rendered,
                    message_kind=req.message_kind,
                    wake=req.wake,
                    provenance=provenance,
                )
            return JSONResponse(resource, status_code=status_code)
        if req.sender:
            provenance = MessageProvenance(
                origin="agent", senders=(req.sender,), subtype="http_send",
            )
        else:
            from app.auth import is_auth_enabled, validate_session

            operator = bool(
                not is_auth_enabled()
                or (
                    request is not None
                    and validate_session(request.cookies.get("session", ""))
                )
            )
            provenance = MessageProvenance(
                origin="user" if operator else "unknown",
                senders=("user",) if operator else ("unknown",),
                subtype="http_send",
            )
        # A non-waking delivery must not load or activate the recipient.  The
        # requested scope is the mailbox address supplied by the sender.
        if not req.wake:
            # #231, находка ревью реализации (F3, раунд 2): ящик разгружается в КОНЦЕ
            # хода. У получателя, который прямо сейчас не работает, следующего конца
            # хода может не быть НИКОГДА — и `wake=False` его не создаёт по построению.
            # Поэтому экономия применяется только там, где она вообще возможна: к
            # получателю, про которого мы ЗНАЕМ, что он занят и ход у него кончится.
            # Во всех остальных случаях (не знаем, не загружен, простаивает) — обычная
            # доставка. Корректность дороже экономии; замер §3.6 и берётся с занятых.
            # Оракул на «неизвестный → в ящик» перезаморожен и снят: он предписывал
            # тихую потерю (F3 ревью реализации).
            live = getattr(manager, "sessions", None) or {}
            target = next(
                (x for x in live.values()
                 if getattr(x, "name", None) == name
                 and getattr(x, "scope", None) == req.scope),
                None,
            )
            busy = target is not None and str(
                getattr(getattr(target, "status", ""), "value", getattr(target, "status", ""))
            ) in {"running", "waiting"}
            if busy:
                durable_target = await asyncio.to_thread(
                    get_session_by_name, name, req.scope,
                )
                taskless_assignment = bool(
                    req.sender and durable_target and not durable_target.get("task_id")
                )
                if not taskless_assignment:
                    from app import mailbox
                    mailbox.enqueue(
                        recipient=name,
                        scope=req.scope,
                        sender=req.sender or "",
                        body=req.message,
                        provenance=provenance,
                    )
                    return {"ok": True, "queued": True}
            # известно, что получатель простаивает → будим, иначе сообщение залежится
        session = await manager.ensure_loaded(name, req.scope)
        if not session:
            session = await manager.ensure_loaded_any(name)
        if not session:
            all_names = [s.name for s in manager.sessions.values()]
            for row in get_all_sessions():
                if row["name"] not in all_names:
                    all_names.append(row["name"])
            similar = [n for n in all_names if name.lower() in n.lower() or n.lower() in name.lower()]
            hint = f" Similar: {', '.join(similar[:5])}" if similar else f" Available: {', '.join(all_names[:10])}"
            return JSONResponse({"error": f"agent '{name}' not found.{hint}"}, status_code=404)
        task_state = None
        task_match = re.match(r"^\s*#(\d+)\s*:\s*", req.message)
        durable = await asyncio.to_thread(__import__("app.db", fromlist=["get_session"]).get_session, session.id)
        if req.sender and not durable:
            return JSONResponse({"error": "durable session binding is required"}, status_code=409)
        durable_task_id = (durable or {}).get("task_id") or ""
        if req.sender and not durable_task_id:
            if req.sender != durable.get("parent_name", ""):
                return JSONResponse(
                    {"error": "only the durable parent may assign a task"}, status_code=403,
                )
            from app import tm as _tm
            title = re.sub(r"^\s*#\d+\s*:\s*", "", req.message).strip() or req.message.strip()
            try:
                created = await asyncio.to_thread(_tm.create_task_for_scope, req.scope, title)
                # Taskless workers created before task binding are on an adhoc branch.
                # Switch before the binding CAS so a failed switch leaves an honest new task.
                if getattr(session, "worktree_path", "") and (
                    getattr(session, "needs_switch", False)
                    or str(getattr(session, "branch", "")).startswith("task-adhoc/")
                ):
                    from app.workspace import switch_worktree_branch
                    switched = await asyncio.to_thread(
                        switch_worktree_branch, session.worktree_path,
                        f"task-{created['par_number']}/{session.name}",
                        getattr(session, "base_branch", "") or "main",
                        force=True, expect_absent=True,
                    )
                    if not switched.get("ok"):
                        return JSONResponse(
                            {"error": switched.get("error") or "task branch switch failed"},
                            status_code=409,
                        )
                    session.needs_switch = False
                    session.branch = switched.get("branch") or (
                        f"task-{created['par_number']}/{session.name}"
                    )
                    from app.db import update_session_lifecycle
                    await asyncio.to_thread(
                        update_session_lifecycle,
                        session.id,
                        branch=session.branch,
                        base_branch=getattr(session, "base_branch", "") or "main",
                        task_id="",
                        needs_switch=False,
                    )
                task_state = await asyncio.to_thread(
                    _tm.bind_task_to_session, req.scope, session.id,
                    str(created["par_number"]),
                )
                session.task_id = str(created["par_number"])
                task_state["auto_created"] = True
            except (ValueError, RuntimeError) as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            if task_match:
                clean_message = re.sub(r"^\s*#\d+\s*:\s*", "", req.message).strip()
                req = req.model_copy(update={
                    "message": f"[Task #{created['par_number']}] "
                    f"{clean_message}"
                })
        elif req.sender and task_match and durable_task_id:
            if task_match.group(1) != str(durable_task_id).lstrip("#"):
                return JSONResponse(
                    {"error": f"worker is bound to task #{durable_task_id}"}, status_code=409,
                )
        if not req.wake and busy:
            from app import mailbox
            mailbox.enqueue(
                recipient=name,
                scope=req.scope,
                sender=req.sender or "",
                body=req.message,
                provenance=provenance,
            )
            result = {"ok": True, "queued": True}
            if task_state:
                result["task"] = task_state
            return result
        # #219 T1b, ГЕЙТ 1 из 2: явный отчёт ребёнка родителю. Второй гейт —
        # `session_turns.fire_auto_report` (молчаливое завершение хода). Прочие
        # девять вызовов `manager.send` не трогаем: среди них `[Background job
        # FAILED]` и живой ввод из Telegram (грабля #154).
        if req.sender:
            from app import fan_barrier
            # #231 T6: полнота сводки — свойство КОДА. Редьюсер, забывший правило
            # «не сокращай», теряет отчёты детей, поэтому манифест приклеивается
            # всегда, а его собственный текст может быть только ДОБАВКОЙ.
            reducer_fan = fan_barrier.peek_summary(req.sender, req.scope)
            if reducer_fan:
                manifest = fan_barrier.manifest_text(reducer_fan)
                body = f"{req.message}\n\n{manifest}" if req.message else manifest
                provenance = MessageProvenance(
                    origin="agent", senders=(req.sender,),
                    subtype="fan_summary", ref=reducer_fan,
                )
                await manager.send(
                    session.id, body, provenance=provenance,
                )
                # Гасим ПОСЛЕ доставки: сбой между пометкой и отправкой уничтожил бы
                # манифест навсегда, а повтор всего лишь пришлёт его дважды (#158).
                fan_barrier.mark_summarised(reducer_fan)
                return {"ok": True, "fan_id": reducer_fan}
            if (
                fan_barrier.should_buffer(req.sender, req.message_kind)
                and fan_barrier.is_terminal_report(req.message_kind)
            ):
                # #276: терминальность — только явный kind, не факт вызова и не
                # слово DONE в тексте. Вопрос / статус / SILENT_TURN идут ниже,
                # к обычной доставке, и барьер не тратят.
                # #231 T6: ребёнок с невыданным входом не терминален. Проверка стоит
                # ВНУТРИ транзакции `record_terminal` — раздельные «посмотреть» и
                # «зафиксировать» пропускают `wake=False`, легший между ними.
                released = fan_barrier.record_terminal(
                    req.sender,
                    req.message_kind,
                    summary=req.message,
                    require_drained_scope=req.scope,
                )
                if released:
                    fan_id = fan_barrier.fan_id_for_child(
                        req.sender, include_released=True
                    )
                    if fan_id:
                        # #231 T6: сводку собирает редьюсер, если он назначен. Дорогой
                        # участник просыпается один раз и уже на готовое.
                        target = session
                        reducer = fan_barrier.reducer_of(fan_id)
                        if reducer:
                            target = await manager.ensure_loaded(reducer, req.scope) or session
                        provenance = MessageProvenance(
                            origin="platform", senders=("Orchestra",),
                            subtype="fan_manifest", ref=str(fan_id or ""),
                        )
                        await manager.send(
                            target.id, fan_barrier.manifest_text(fan_id),
                            provenance=provenance,
                        )
                return {"ok": True, "buffered": not released,
                        "parent_name": session.parent_name or ""}
        msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
        if req.sender:
            msg += manager._context_warning(req.sender)
            if hasattr(session, 'last_task_sender'):
                session.last_task_sender = req.sender
        # Время ставится КАЖДОМУ входящему, включая агентские: юзер требует видеть,
        # когда сообщение написано, а не только от кого (28.08). Раньше метку получал
        # только он сам, и в ленте нельзя было отличить свежий отчёт от вчерашнего.
        msg = add_user_message_time_prefix(msg)
        await manager.send(
            session.id, msg, provenance=provenance,
        )
        pn = session.parent_name or ""
        result = {"ok": True, "parent_name": pn}
        if task_state:
            result["task"] = task_state
        return result
    except LifecycleQuarantineError as e:
        return JSONResponse({"ok": False, "error": e.envelope()}, status_code=409)
    except QuotaGateError as e:
        return JSONResponse(e.envelope(), status_code=e.status_code)
    except sqlite3.DatabaseError:
        from app import message_deliveries

        verification_succeeded = False
        try:
            delivery_id = message_deliveries._validate_id(req.delivery_id)
            committed = message_deliveries._row(delivery_id)
        except (ValueError, sqlite3.DatabaseError):
            committed = None
        else:
            verification_succeeded = True
        if req.delivery_id.strip() and not verification_succeeded:
            return JSONResponse(
                {
                    "error": {
                        "code": "DELIVERY_OUTCOME_UNKNOWN",
                        "message": "delivery acceptance could not be reconciled safely",
                        "outcome_unknown": True,
                        "retryable": False,
                        "details": {"commit_state": "VERIFICATION_FAILED"},
                    }
                },
                status_code=503,
            )
        if req.delivery_id.strip() and committed is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "DELIVERY_ACCEPT_REJECTED",
                        "message": "delivery acceptance was not committed; retry is safe",
                        "outcome_unknown": False,
                        "retryable": True,
                        "details": {"commit_state": "NOT_COMMITTED"},
                    }
                },
                status_code=503,
            )
        raise
    except (RuntimeError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"send_message failed for {name}: {e}", exc_info=True)
        return JSONResponse({"error": f"Send failed: {e}"}, status_code=500)


@router.get("/api/message-deliveries/{delivery_id}")
async def get_message_delivery_status(delivery_id: str, request: Request = None):
    """Return a direct-message receipt only to its MCP owner or an operator."""
    from app import message_deliveries
    from app.auth import validate_session
    from app.mcp_proof import check_mcp_proof

    if request is None:
        return keyed_auth_required()
    if validate_session(request.cookies.get("session", "")):
        try:
            row = message_deliveries._row(message_deliveries._validate_id(delivery_id))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return message_deliveries._resource(row, acceptance="ALREADY_ACCEPTED")

    source_id = request.headers.get("x-orchestra-session-id", "").strip()
    proof = request.headers.get("x-orchestra-mcp-proof", "")
    source = get_session_row(source_id) if source_id else None
    if not source or not check_mcp_proof(source_id, proof):
        return keyed_auth_required()
    try:
        validated_id = message_deliveries._validate_id(delivery_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    row = message_deliveries._row(validated_id)
    if row is not None and row["source_session_id"] != source_id:
        return keyed_auth_required()
    resource = message_deliveries.get_message_delivery(validated_id, source_id)
    if resource is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return resource


@router.post("/api/sessions/{name}/compact")
async def compact_session(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running, wait for idle"}, status_code=400)
    try:
        result = await session.compact()
    except QuotaGateError as error:
        return JSONResponse(error.envelope(), status_code=error.status_code)
    return result


@router.get("/api/sessions/{name}/session-history")
async def session_history(name: str, scope: str = ""):
    session = await manager.ensure_loaded(name, scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "current_session_id": session.session_id,
        "history": session.session_id_history,
    }


@router.post("/api/sessions/{name}/rollback-session")
async def rollback_session(name: str, req: ScopeRequest, index: int = -1):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running"}, status_code=400)
    if not session.session_id_history:
        return JSONResponse({"error": "no session history"}, status_code=400)
    try:
        entry = session.session_id_history[index]
    except IndexError:
        return JSONResponse({"error": f"invalid index {index}"}, status_code=400)
    old_sid = session.session_id
    await session._disconnect_backend()
    session.session_id = entry["session_id"]
    if entry.get("runtime") and entry.get("model"):
        session.backend_type = entry["runtime"]
        session.model = entry["model"]
        session.runtime_handoff = ""
    session._persist()
    return {
        "ok": True,
        "rolled_back_to": entry["session_id"],
        "previous": old_sid,
        "runtime": session.backend_type,
        "model": session.model,
        "compacted_at": entry.get("compacted_at"),
    }


@router.post("/api/sessions/{name}/restart-cli")
async def restart_cli(name: str, req: ScopeRequest):
    from app import message_deliveries
    from app.manager import _wait_owned_task

    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    delivery_lock = message_deliveries._target_delivery_locks.setdefault(session.id, asyncio.Lock())
    manager_lock = manager.get_session_lock(session.id)
    # Fail before mutation, rather than queue a restart behind a send and then
    # unexpectedly interrupt the newly started turn. Uncontended asyncio locks
    # acquire without yielding; this order matches the delivery runner.
    async def restart_locked():
        locks = (delivery_lock, manager_lock, session._lifecycle_lock)
        if any(lock.locked() for lock in locks):
            return JSONResponse({"error": "target is busy; CLI restart made no changes"}, status_code=409)
        async with delivery_lock, manager_lock, session._lifecycle_lock:
            session._turn_start_cancel_gen += 1
            session._manually_interrupted = True
            session._cancel_precompact_timer("restart_cli")
            await session._disconnect_backend()
            settled = await message_deliveries.recover_message_deliveries(target_session_id=session.id)
            session.status = AgentStatus.IDLE
            session._persist()
        if session._pending_messages:
            session._spawn_bg(session._flush_pending())
        return {"ok": True, "unreconciled_deliveries": settled}

    # A disconnected HTTP client must not release the locks while a SQLite
    # recovery thread or runtime teardown is still operating on this session.
    task = asyncio.create_task(restart_locked())
    await _wait_owned_task(task)
    return task.result()


@router.post("/api/sessions/{name}/clear-session")
async def clear_session(name: str, req: ScopeRequest):
    """Drop the conversation thread: next turn starts with an empty history.

    Unlike restart-cli (reconnects the backend but keeps session_id), this
    forgets the thread entirely. The worktree, branch and prompt are untouched.
    """
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running"}, status_code=400)
    old_sid = session.session_id
    await session._disconnect_backend()
    session._cancel_precompact_timer("session_clear")
    session.session_id = ""
    session.runtime_handoff = ""
    session.history_import_source = None
    session.last_summary = ""
    session._last_context = empty_context()
    session._prompt_injected = False
    session.status = AgentStatus.IDLE
    session._persist()
    return {"ok": True, "cleared": old_sid}


@router.post("/api/sessions/{name}/interrupt")
async def interrupt_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or not found.loaded:
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.interrupt(found.id)
    return {"ok": True}


@router.post("/api/sessions/{name}/stop")
async def stop_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or not found.loaded:
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.stop_worker(found.id)
    return {"ok": True}


@router.post("/api/sessions/{name}/description")
async def update_description(name: str, req: dict):
    scope = req.get("scope", "")
    desc = req.get("description", "")
    if not manager.update_session_fields(name, scope, description=desc):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}


@router.post("/api/sessions/{name}/tg_topic")
async def update_tg_topic(name: str, req: dict):
    scope = req.get("scope", "")
    enabled = bool(req.get("enabled", False))
    if not manager.update_session_fields(name, scope, tg_topic=enabled):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True, "tg_topic": enabled}


@router.post("/api/sessions/{name}/prompt")
async def update_prompt(name: str, req: dict):
    scope = req.get("scope", "")
    prompt = req.get("system_prompt", "")
    if not manager.update_session_fields(name, scope, system_prompt=prompt):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}


@router.post("/api/sessions/{name}/owned-dirs")
async def update_owned_dirs(name: str, req: dict):
    scope = req.get("scope", "")
    raw = req.get("owned_dirs", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return JSONResponse({"error": "owned_dirs must be a JSON array"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    from app.manager import LockBusy, wait_for_session_lock

    def _busy(status: str) -> JSONResponse:
        return JSONResponse(
            {
                "error": f"worker is {status} — ownership changes only on idle. Its turn "
                "is already editing under the current ownership; wait for idle or "
                "stop_worker first",
            },
            status_code=409,
        )

    if found.status.value != "idle":
        return _busy(found.status.value)
    try:
        # The status is re-checked under the lock: without it the prompt of a turn
        # that started meanwhile would be rewritten mid-flight.
        async with wait_for_session_lock(
            manager.get_session_lock(found.id),
            what="set_worker_owned_dirs", worker=name,
        ):
            # Re-resolve INSIDE the lock. `found` was hydrated before it, and a
            # concurrent loader (`_get_or_load` takes this same lock) may have registered
            # the authoritative live session since. Writing through the stale detached
            # copy would leave the DB updated while the running session — and its prompt —
            # kept the old boundary.
            found = manager.get_by_name(name, scope) or found
            async with AsyncExitStack() as stack:
                if found.loaded:
                    await stack.enter_async_context(found._lifecycle_lock)
                if found.status.value != "idle":
                    return _busy(found.status.value)
                applied = await manager.apply_owned_dirs(found, raw)
    except LockBusy as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return {"ok": True, "owned_dirs": applied}


@router.post("/api/sessions/{name}/change-model")
async def change_model(name: str, req: dict):
    scope = req.get("scope", "")
    new_model = req.get("model", "").strip()
    # #366: the level depends on WHO changes. MCP tool calls act as an agent and
    # are gated by the `agents` level; UI calls by the `dashboard` level.
    via = req.get("via", "dashboard")
    if not new_model:
        return JSONResponse({"error": "model required"}, status_code=400)
    new_model = resolve_model(new_model)
    if new_model not in MODELS:
        return JSONResponse({"error": f"unknown model: {new_model}"}, status_code=400)
    try:
        if via == "mcp":
            ensure_spawn_allowed(new_model)
        else:
            ensure_dashboard_visible(new_model)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    found = await manager.ensure_loaded(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    fresh = req.get("fresh", False)
    if not isinstance(fresh, bool):
        return JSONResponse({"error": "fresh must be boolean"}, status_code=400)
    result = await found.change_model(new_model, fresh=fresh)
    if not result.get("ok"):
        return JSONResponse(result, status_code=409)
    return result


@router.post("/api/sessions/{session_id}/handoffs/{handoff_id}/events")
async def runtime_handoff_events(
    session_id: str, handoff_id: str, request: Request, req: dict,
):
    import json

    from app.auth import require_operator_csrf
    from app.runtime_history import (
        resolve_runtime_handoff_events,
        runtime_packet_sha256,
        runtime_snapshot_sha256,
    )

    require_operator_csrf(request)
    handoff = get_runtime_handoff(handoff_id)
    if not handoff or handoff["session_id"] != session_id:
        return JSONResponse({"error": "handoff not found"}, status_code=404)
    try:
        event_ids = [int(value) for value in req.get("event_ids", [])]
        _snapshot_id, rows = get_history_logs(session_id)
        packet = json.loads(handoff["packet_json"])
        if (
            packet.get("integrity")
            and runtime_packet_sha256(packet) != handoff["packet_sha256"]
        ):
            raise ValueError("runtime handoff packet checksum mismatch")
        raw_refs = packet.get("raw_event_refs") or {}
        packet_snapshot_sha256 = str(raw_refs.get("snapshot_sha256") or "")
        if packet_snapshot_sha256:
            actual_snapshot_sha256 = runtime_snapshot_sha256(
                rows, snapshot_id=int(handoff["snapshot_log_id"])
            )
            if (
                packet_snapshot_sha256 != handoff["snapshot_sha256"]
                or actual_snapshot_sha256 != packet_snapshot_sha256
            ):
                raise ValueError("runtime handoff snapshot checksum mismatch")
        referenced = raw_refs.get("event_ids")
        events = resolve_runtime_handoff_events(
            rows,
            event_ids=event_ids,
            caller_session_id=session_id,
            owner_session_id=session_id,
            snapshot_id=int(handoff["snapshot_log_id"]),
            referenced_ids=referenced,
        )
    except (TypeError, ValueError, PermissionError) as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return {"events": events}


def _rename_parent_references(parent_id: str, old_name: str, new_name: str) -> int:
    """Дети ссылаются на родителя ИМЕНЕМ (`sessions.parent_name`), и по нему же идёт
    авто-репорт. Родителя переименовали → ссылка указывает в пустоту, а если имя займёт
    другой агент — на ЧУЖУЮ живую сессию. Ищем детей по неизменяемому `parent_id` (#82).
    """
    from app.db import _conn

    with _conn() as c:
        cur = c.execute(
            "UPDATE sessions SET parent_name=? WHERE parent_id=? AND parent_name=?",
            (new_name, parent_id, old_name),
        )
        updated = cur.rowcount
    for child in manager.sessions.values():
        if child.parent_id == parent_id and child.parent_name == old_name:
            child.parent_name = new_name
            # У ребёнка старое имя родителя лежит в PARENT_NAME его MCP-подпроцесса.
            manager.refresh_identity(child)
    return updated


@router.post("/api/sessions/{name}/rename")
async def rename_session(name: str, req: dict):
    scope = req.get("scope", "")
    new_name = req.get("new_name", "").strip()
    if not new_name:
        return JSONResponse({"error": "new_name required"}, status_code=400)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", new_name):
        return JSONResponse({"error": "invalid name: alphanumeric with ._- allowed, 1-50 chars"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found.id
    session = manager.sessions.get(sid)
    old_branch = None
    new_branch = None
    from app.db import _conn
    with _conn() as c:
        row = c.execute(
            "SELECT branch, system_prompt, prompt_overlay FROM sessions WHERE id=?", (sid,),
        ).fetchone()
        updates = {"name": new_name}
        if row and row["system_prompt"]:
            updates["system_prompt"] = row["system_prompt"].replace(
                f"Worker name: {name}", f"Worker name: {new_name}"
            ).replace(
                f"Orchestrator: {name}", f"Orchestrator: {new_name}"
            )
        if row and row["prompt_overlay"] is not None:
            updates["prompt_overlay"] = row["prompt_overlay"].replace(
                f"Worker name: {name}", f"Worker name: {new_name}"
            ).replace(
                f"Orchestrator: {name}", f"Orchestrator: {new_name}"
            )
        if row and row["branch"] and row["branch"].endswith(f"/{name}"):
            old_branch = row["branch"]
            new_branch = row["branch"][: -len(name)] + new_name
            updates["branch"] = new_branch
        sets = ", ".join(f"{k}=?" for k in updates)
        try:
            c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*updates.values(), sid))
        except sqlite3.IntegrityError:
            return JSONResponse({"error": "name already taken"}, status_code=409)
    if session:
        session.name = new_name
        if updates.get("system_prompt"):
            session.system_prompt = updates["system_prompt"]
            session._current_prompt = session._current_prompt.replace(
                f"Worker name: {name}", f"Worker name: {new_name}"
            ).replace(
                f"Orchestrator: {name}", f"Orchestrator: {new_name}"
            )
        if "prompt_overlay" in updates:
            session.prompt_overlay = updates["prompt_overlay"]
        if new_branch:
            session.branch = new_branch
        session._persist()
        # Имя уехало в env MCP-подпроцесса при его старте: без пересборки агент до конца
        # коннекта представляется старым именем (#82).
        manager.refresh_identity(session)
    _rename_parent_references(sid, name, new_name)
    if old_branch and new_branch:
        wt_path = (session.worktree_path if session else None) or found.worktree_path
        if wt_path and Path(wt_path).is_dir():
            import subprocess
            subprocess.run(
                ["git", "branch", "-m", old_branch, new_branch],
                cwd=wt_path, capture_output=True,
            )
    is_orch = session.is_orchestrator if session else found.is_orchestrator
    if is_orch:
        try:
            from app.tg_bridge import rename_orch_topic
            await rename_orch_topic(name, new_name)
        except Exception as e:
            logger.warning(f"TG topic rename failed: {e}")

    return {"ok": True, "old_name": name, "new_name": new_name, "branch": new_branch}


@router.delete("/api/sessions/{name}")
async def delete_session(name: str, scope: str, force: bool = False):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found.id
    if not force:
        if found.loaded and found.status.value == "running":
            return JSONResponse({"error": "worker is running — stop first (or force=true)"}, status_code=400)
        # Orphan-guard: killing a parent with live children leaves them dangling
        # (no kill-cascade). Mirror the change_scope guard — block, force to override.
        children = manager._live_children(name, found.scope or scope)
        if children:
            return JSONResponse({"error": f"worker has {len(children)} live child worker(s): {', '.join(children)}. Kill or merge them first (or force=true)"}, status_code=400)
        wt = found.worktree_path
        if wt and Path(wt).is_dir():
            status_proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain", cwd=wt,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(status_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                status_proc.kill()
                return JSONResponse({"error": "git status timed out in worktree. Use force=true if certain"}, status_code=400)
            if status_proc.returncode != 0:
                return JSONResponse({"error": f"git status failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
            dirty = stdout.decode().strip()
            if dirty:
                files = [l[3:] for l in dirty.splitlines()[:10]]
                return JSONResponse({"error": f"worker has uncommitted changes: {', '.join(files)}. Commit or discard first (or force=true)"}, status_code=400)
            try:
                base_branch = _session_base_branch(found)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            from app.workspace import branch_content_status
            content_status = await asyncio.to_thread(
                branch_content_status,
                wt,
                base_branch,
            )
            if content_status.get("error"):
                return JSONResponse(
                    {
                        "error": (
                            f"worker content check failed: {content_status['error']}. "
                            "Use force=true if certain"
                        )
                    },
                    status_code=400,
                )
            if not content_status["content_merged"]:
                n = content_status["commits_ahead"]
                reason = content_status["reason"]
                return JSONResponse(
                    {
                        "error": (
                            f"worker has {n} commit(s) whose content is not verified in "
                            f"{base_branch} ({reason}). merge_worker first (or force=true)"
                        )
                    },
                    status_code=400,
                )
    try:
        await manager.remove(sid)
    except Exception as e:
        logger.error(f"session remove failed for {name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"ok": True}


def _merge_not_reached(
    error: str,
    *,
    target_branch: str = "",
    worker_branch: str = "",
    worker_head: str = "",
    http_status: int = 400,
) -> dict:
    return {
        "ok": False,
        "state": "failed",
        "commit_point": "not_reached",
        "error": error or "merge rejected without an error detail",
        "target_branch": target_branch,
        "target_before": "",
        "target_after": "",
        "worker_branch": worker_branch,
        "worker_head": worker_head,
        "conflicts": [],
        "_http_status": http_status,
    }


def _legacy_merge_continue_warning(
    worker_name: str, task_id: str, base_branch: str,
) -> dict:
    call = (
        f'switch_worker_branch(name="{worker_name}", task_id="{task_id}", '
        f'from_ref="{base_branch}")'
    )
    return {
        "code": "LEGACY_MERGE_CONTINUE",
        "message": (
            f"merge came from an operation-v1 client: task #{task_id} stays "
            f"in_progress and bound. Repair the worker lifecycle with {call}. "
            "The call is idempotent; reconnect the agent before its next turn."
        ),
    }


async def _persist_lifecycle_quarantine(
    session,
    *,
    branch: str,
    base_branch: str,
    task_id: str = "",
    needs_switch: bool = True,
) -> dict:
    """Persist a fail-closed lifecycle snapshot, retrying one transient failure."""
    errors: list[str] = []
    for _attempt in range(2):
        session.branch = branch
        session.base_branch = base_branch
        session.task_id = task_id
        session.needs_switch = needs_switch
        try:
            await manager.persist_lifecycle(
                session,
                branch=branch,
                base_branch=base_branch,
                task_id=task_id,
                needs_switch=needs_switch,
            )
        except Exception as error:
            errors.append(err_text(error))
            continue
        status = {"ok": True}
        if errors:
            status.update(recovered=True, warning="; ".join(errors))
        return status
    return {
        "ok": False,
        "error": "; ".join(errors) or "lifecycle quarantine persistence failed",
    }


async def apply_merge_finalization(finalization: dict) -> dict:
    """Everything the platform owns AFTER the merge commit point.

    One owner for two callers: the merge that produced the commit, and a same-id replay
    that resumes a DB stage which never landed. Both must be able to run it, and running
    it twice must change nothing the second time.
    """
    from app import tm as _tm
    from app.db import get_session
    from app.ia import merge_receipts
    from app.workspace import switch_worktree_branch

    session_id = finalization["session_id"]
    operation_id = str(finalization.get("operation_id") or "")
    if operation_id and merge_receipts.merge_receipt_configured():
        merge_receipts.require_merge_receipt(
            operation_id, finalization=finalization,
        )
    applied = await asyncio.to_thread(_tm.finalize_merge_outcome, finalization)
    out: dict = {"linked_tasks": applied["links"]}

    row = await asyncio.to_thread(get_session, session_id)
    session = manager.get(session_id) or (manager._hydrate_row(row) if row else None)
    if session is None:
        out["lifecycle_status"] = {
            "ok": False, "error": f"session '{session_id}' disappeared before finalization",
        }
        return out

    terminal = finalization["terminal_session"]
    target = finalization["target_branch"]
    branch = getattr(session, "branch", "") or ""
    if terminal["task_id"]:
        new_branch = f"task-{terminal['task_id']}/{session.name}"
        try:
            switch = await asyncio.to_thread(
                switch_worktree_branch,
                session.worktree_path, new_branch, target, force=True,
            )
        except Exception as error:
            switch = {
                "ok": False, "state": "failed",
                "error": f"branch switch failed: {err_text(error)}",
            }
        out["switch"] = switch
        if switch.get("ok"):
            branch = switch.get("branch") or new_branch
        else:
            # Задача уже назначена в БД, а ветка не сменилась: воркер обязан остаться
            # с needs_switch, иначе он допишет в уже смерженную ветку.
            out["task_status"] = {
                "ok": False,
                "error": f"task assigned, branch switch failed: {switch.get('error', '')}",
            }
            out["lifecycle_status"] = await _persist_lifecycle_quarantine(
                session, branch=branch, base_branch=target,
                task_id=terminal["task_id"], needs_switch=True,
            )
            return out
        out["task_status"] = {"ok": True, "par": terminal["task_id"]}
    out["lifecycle_status"] = await _persist_lifecycle_quarantine(
        session,
        branch=branch,
        base_branch=target,
        task_id=terminal["task_id"],
        needs_switch=bool(terminal["needs_switch"]),
    )
    return out


async def _finalize_committed_merge(
    *,
    result: dict,
    finalization: dict,
    found,
    operation_id: str,
    row_scope: str,
    merged_commits: dict,
) -> dict:
    """Run the durable checkpoint and the DB stage of a merge that already committed."""
    from app import merge_operations as _ops
    from app.ia import merge_receipts
    from app import rag_service

    finalization["commits"] = merged_commits
    finalization["target_after"] = result.get("target_after") or ""
    finalization["stage"] = "PENDING"
    if operation_id:
        try:
            await asyncio.to_thread(
                _ops.checkpoint_merge_commit, operation_id, finalization,
            )
        except Exception as error:
            # Первая запись после Git И ЕСТЬ журнал. Потеряли её — состояние БД неизвестно,
            # и восстанавливать его надо из репозитория (trailer + parent + tree), а не
            # повторной попыткой: повтор не отличить от второго мержа.
            detail = err_text(error)
            logger.error(
                "merge checkpoint lost operation_id=%s: %s", operation_id, detail,
            )
            result.update(
                ok=False,
                state="partial",
                commit_point="unknown",
                error=f"first post-commit checkpoint lost: {detail}",
                finalization=finalization,
                finalization_checkpoint_lost=detail,
            )
            return result
    if operation_id and merge_receipts.merge_receipt_configured():
        try:
            result["receipt"] = await asyncio.to_thread(
                merge_receipts.record_merge_receipt,
                operation_id,
                result,
                finalization,
            )
        except Exception as error:
            detail = err_text(error)
            logger.error(
                "merge receipt failed operation_id=%s: %s", operation_id, detail,
            )
            result.update(
                ok=False,
                state="partial",
                commit_point="target_committed",
                error=f"verified merge receipt failed: {detail}",
                finalization=finalization,
            )
            return result
    try:
        applied = await apply_merge_finalization(finalization)
    except Exception as error:
        detail = err_text(error)
        logger.error("merge finalization failed operation_id=%s: %s", operation_id, detail)
        result.update(
            ok=False,
            state="partial",
            commit_point="target_committed",
            error=f"merge finalization failed: {detail}",
            finalization=finalization,
        )
        return result
    finalization["stage"] = "APPLIED"
    if operation_id:
        await asyncio.to_thread(
            _ops.mark_finalization_applied, operation_id, finalization,
        )
    result.update(applied)
    result["finalization"] = finalization
    result["rag_backfill_status"] = rag_service.schedule_backfill(row_scope)
    return result


async def execute_merge_session(
    *,
    session_id: str,
    expected_name: str,
    expected_scope: str,
    expected_branch: str,
    expected_head: str,
    req: dict,
    expected_target_head: str = "",
) -> dict:
    """Execute a merge for one pinned session identity and own its lock sequence."""
    from app import merge_operations as _ops
    from app import tm as _tm
    from app.db import get_session
    from app.workspace import (
        classify_head_drift,
        inspect_worktree_identity,
        merge_worktree_to_main,
        switch_worktree_branch,
    )

    requested_target = req.get("target", "")
    next_task_id = req.get("next_task_id", "")
    operation_id = str(req.get("operation_id") or "")
    expected_scope = expected_scope.rstrip("/")

    async with manager.get_session_lock(session_id):
        row = await asyncio.to_thread(get_session, session_id)
        if not row or row.get("status") == "archived":
            return _merge_not_reached(
                f"session '{session_id}' not found",
                worker_branch=expected_branch,
                worker_head=expected_head,
                http_status=404,
            )
        row_scope = (row.get("scope") or "").rstrip("/")
        row_branch = row.get("branch") or ""
        if row.get("name") != expected_name or row_scope != expected_scope:
            return _merge_not_reached(
                "session identity changed before merge",
                worker_branch=row_branch,
                worker_head=expected_head,
                http_status=409,
            )
        if expected_branch and row_branch != expected_branch:
            return _merge_not_reached(
                f"session branch changed before merge: expected {expected_branch}, found {row_branch}",
                worker_branch=row_branch,
                worker_head=expected_head,
                http_status=409,
            )

        live = manager.get(session_id)
        if live is not None and (
            live.name != row["name"]
            or live.scope.rstrip("/") != row_scope
            or (live.branch or "") != row_branch
        ):
            return _merge_not_reached(
                "loaded session disagrees with its durable identity",
                worker_branch=live.branch or "",
                worker_head=expected_head,
                http_status=409,
            )
        found = live or manager._hydrate_row(row)
        prior_task_id = str(getattr(found, "task_id", "") or row.get("task_id") or "")
        worktree_path = row.get("worktree_path") or ""
        if not worktree_path:
            return _merge_not_reached(
                "session has no worktree", worker_branch=row_branch, http_status=400,
            )
        if not row_scope:
            return _merge_not_reached(
                "session has no scope", worker_branch=row_branch, http_status=400,
            )

        task_identity = None
        primary_task_identity = None
        primary_task_ref = ""
        project_id = ""
        strict_task_merge = str(req.get("merge_schema_version") or "") == "2"
        from app.ia import merge_receipts

        receipt_required = (
            strict_task_merge and merge_receipts.merge_receipt_configured()
        )
        task_outcome = str(req.get("task_outcome") or "").strip().lower()
        if strict_task_merge:
            if task_outcome not in {"continue", "complete"}:
                return _merge_not_reached(
                    "task_outcome must be 'continue' or 'complete' for merge schema 2",
                    worker_branch=row_branch,
                    worker_head=expected_head,
                    http_status=400,
                )
            if task_outcome == "continue" and next_task_id:
                # Смена задачи — это ЗАКРЫТИЕ текущей и назначение следующей одной
                # транзакцией. `continue` с next_task_id оставил бы текущую открытой
                # и без воркера, то есть ровно ту забывчивость, которую #248 убирает.
                return _merge_not_reached(
                    "next_task_id requires task_outcome='complete'",
                    worker_branch=row_branch,
                    worker_head=expected_head,
                    http_status=400,
                )
            primary_task_ref = str(row.get("task_id") or "").strip()
            if not primary_task_ref:
                return _merge_not_reached(
                    "session has no bound task",
                    worker_branch=row_branch,
                    worker_head=expected_head,
                    http_status=409,
                )
            try:
                primary_resolution = await asyncio.to_thread(
                    _tm.resolve_scoped_task_identities,
                    row_scope,
                    [primary_task_ref],
                    bound_session_id=session_id,
                )
            except ValueError as e:
                return _merge_not_reached(
                    str(e), worker_branch=row_branch, worker_head=expected_head,
                    http_status=409,
                )
            primary_task_identity = primary_resolution["tasks"][0]
            primary_task_ref = primary_resolution["canonical_refs"][0]
            project_id = primary_resolution["project_id"]
        if next_task_id:
            try:
                task_identity = await asyncio.to_thread(
                    _tm.resolve_scoped_task_identity, row_scope, next_task_id,
                )
            except ValueError as e:
                return _merge_not_reached(
                    str(e), worker_branch=row_branch, worker_head=expected_head,
                    http_status=400,
                )
            if not project_id:
                project_id = task_identity["project_id"]
        elif not project_id:
            def _project_for_scope() -> str:
                with _tm._conn() as conn:
                    project = _tm.get_project_by_scope(conn, row_scope)
                return project["id"] if project else ""

            project_id = await asyncio.to_thread(_project_for_scope)

        pinned_head = expected_head
        pinned_branch = expected_branch or row_branch
        if not pinned_head:
            try:
                actual_branch, pinned_head = await asyncio.to_thread(
                    inspect_worktree_identity, worktree_path,
                )
            except RuntimeError as e:
                return _merge_not_reached(
                    str(e), worker_branch=row_branch, http_status=400,
                )
            if pinned_branch and actual_branch != pinned_branch:
                return _merge_not_reached(
                    f"worker branch changed before merge: expected {pinned_branch}, found {actual_branch}",
                    worker_branch=actual_branch,
                    worker_head=pinned_head,
                    http_status=409,
                )
            pinned_branch = actual_branch

        if expected_target_head:
            # Target-aware operations already resolved and persisted this branch/ref at
            # admission. The repository lock rechecks the same pair before mutation.
            target = requested_target or getattr(found, "base_branch", "")
        else:
            try:
                target = await asyncio.to_thread(
                    _session_base_branch, found, requested_target,
                )
            except ValueError as e:
                return _merge_not_reached(
                    str(e), target_branch=requested_target,
                    worker_branch=pinned_branch, worker_head=pinned_head,
                    http_status=400,
                )

        if target == pinned_branch:
            return _merge_not_reached(
                f"target branch '{target}' is the worker branch; refusing to merge it into itself",
                target_branch=target,
                worker_branch=pinned_branch,
                worker_head=pinned_head,
            )

        if not await _wait_for_merge_idle(found):
            status = found.status.value
            return _merge_not_reached(
                f"worker is {status} — wait for idle before merge",
                target_branch=target, worker_branch=pinned_branch,
                worker_head=pinned_head, http_status=400,
            )

        current_row = await asyncio.to_thread(get_session, session_id)
        if (
            not current_row
            or current_row.get("status") == "archived"
            or current_row.get("name") != expected_name
            or (current_row.get("scope") or "").rstrip("/") != row_scope
            or (current_row.get("branch") or "") != row_branch
        ):
            return _merge_not_reached(
                "session identity changed while waiting to merge",
                target_branch=target, worker_branch=pinned_branch,
                worker_head=pinned_head, http_status=409,
            )

        async with AsyncExitStack() as stack:
            if found.loaded:
                await stack.enter_async_context(found._lifecycle_lock)
                if found.status.value != "idle":
                    return _merge_not_reached(
                        f"worker is {found.status.value} — wait for idle before merge",
                        target_branch=target, worker_branch=pinned_branch,
                        worker_head=pinned_head, http_status=400,
                    )
            # Личность перечитывается ЗДЕСЬ — после ожидания хода и под lifecycle-локом,
            # то есть в последний момент, когда воркер уже не может ничего дописать.
            # Пин не забывается: он уезжает в результат вместе с фактическим HEAD и классом.
            drift = await asyncio.to_thread(
                classify_head_drift, worktree_path, pinned_branch, pinned_head,
            )
            if drift["class"] == "FATAL":
                return _merge_not_reached(
                    f"worker identity drifted before merge: {drift['reason']}",
                    target_branch=target,
                    worker_branch=drift["actual_branch"] or pinned_branch,
                    worker_head=drift["actual_head"] or pinned_head,
                    http_status=409,
                )
            merge_head = pinned_head if receipt_required else drift["actual_head"] or pinned_head

            finalization: dict | None = None
            if strict_task_merge:
                try:
                    finalization = await asyncio.to_thread(
                        _tm.prepare_merge_finalization,
                        scope=row_scope,
                        session_id=session_id,
                        project_id=project_id,
                        outcome=task_outcome,
                        task=primary_task_identity,
                        next_task=task_identity,
                        operation_id=operation_id,
                    )
                except ValueError as e:
                    return _merge_not_reached(
                        str(e),
                        target_branch=target,
                        worker_branch=pinned_branch,
                        worker_head=merge_head,
                        http_status=409,
                    )
                finalization["target_branch"] = target
                finalization["worker_head"] = merge_head

            commit_receipt = None
            if finalization is not None and receipt_required:
                def commit_receipt(merge_result: dict) -> dict:
                    return merge_receipts.record_merge_receipt(
                        operation_id, merge_result, finalization,
                    )

            def _resolve_candidate_refs(actual_refs: list[str]) -> list[str]:
                """Turn the refs found on the pinned HEAD into canonical scoped ones.

                Runs under the repository lock, on the same inspection that guards the
                emitted subject — a ref this refuses never reaches a commit.
                """
                resolution = _tm.resolve_scoped_task_identities(
                    row_scope, actual_refs, skip_unknown=True,
                )
                canonical = resolution["canonical_refs"]
                # Незнакомый `#N` в сообщении коммита — факт чужой нумерации репозитория,
                # а не ошибка: он не привязывается, но мержу не мешает (#comfy 06.09).
                unresolved = resolution.get("unresolved_refs") or []
                if unresolved:
                    finalization["unresolved_task_refs"] = list(unresolved)
                finalization["candidate_refs"] = canonical
                return canonical

            def _prepare_finalization(target_before: str, expected_tree: str) -> None:
                """Freeze the pre-Git journal under the repo lock, before any mutation."""
                finalization["target_before"] = target_before
                finalization["expected_tree"] = expected_tree
                if operation_id:
                    _ops.save_prepared_finalization(operation_id, finalization)

            try:
                result = await asyncio.to_thread(
                    merge_worktree_to_main,
                    worktree_path,
                    row_scope,
                    target_branch=target,
                    expected_worker_branch=pinned_branch,
                    expected_worker_head=merge_head,
                    expected_target_head=expected_target_head,
                    waive_diff_budget=bool(req.get("waive_diff_budget")),
                    waived_by=str(req.get("waived_by") or ""),
                    primary_task_ref=primary_task_ref,
                    operation_id=operation_id if finalization is not None else "",
                    prepare=_prepare_finalization if finalization is not None else None,
                    resolve_refs=(
                        _resolve_candidate_refs if finalization is not None else None
                    ),
                    commit_receipt=commit_receipt,
                )
            except Exception as e:
                # Реmержа не было видно ни одной стороной: исход Git неизвестен, поэтому
                # резервация НЕ снимается — иначе задачу заберёт другой воркер, пока
                # никто не знает, коммитнулась она или нет.
                return {
                    **_merge_not_reached(
                        f"merge execution failed: {type(e).__name__}: {e}",
                        target_branch=target,
                        worker_branch=pinned_branch,
                        worker_head=pinned_head,
                        http_status=500,
                    ),
                    "state": "partial",
                    "commit_point": "unknown",
                }

            if (
                isinstance(result, dict)
                and result.get("ok")
                and result.get("target_before")
                and result.get("target_before") == result.get("target_after")
                and int(result.get("commits_merged") or 0) == 0
            ):
                result.update(
                    ok=False,
                    state="failed",
                    commit_point="not_reached",
                    code="NO_COMMITS_MERGED",
                    error="merge produced no new commits",
                )

            if isinstance(result, dict):
                result["head_drift"] = drift["class"]
                result["worker_head_pinned"] = pinned_head
                if strict_task_merge:
                    result["task_outcome"] = task_outcome
                    result["primary_task"] = primary_task_identity
            if not result.get("ok"):
                if finalization is not None and result.get("commit_point") in {
                    "not_reached", "rolled_back",
                }:
                    # Git до commit point не дошёл — доказано самим git'ом, поэтому
                    # резервацию можно снять и задача снова доступна для spawn/send.
                    await asyncio.to_thread(_tm.release_merge_finalization, finalization)
                return result

            merged_commits = result.pop("merged_commits", {})
            if finalization is not None:
                return await _finalize_committed_merge(
                    result=result,
                    finalization=finalization,
                    found=found,
                    operation_id=operation_id,
                    row_scope=row_scope,
                    merged_commits=merged_commits,
                )

            link_results = {}
            for task_ref, commits in merged_commits.items():
                if not project_id:
                    link_results[task_ref] = {
                        "ok": False,
                        "added": 0,
                        "error": f"scope '{row_scope}' has no task project",
                    }
                    continue
                try:
                    link_results[task_ref] = await asyncio.to_thread(
                        _tm.link_commits_to_task,
                        task_ref,
                        commits,
                        project_id,
                    )
                except Exception as link_err:
                    logger.error("Failed to link commits to %s: %s", task_ref, link_err)
                    detail = str(link_err) or type(link_err).__name__
                    link_results[task_ref] = {
                        "ok": False,
                        "added": 0,
                        "error": detail,
                    }
            if link_results:
                result["linked_tasks"] = link_results

            merged_branch = (
                result.get("branch") or getattr(found, "branch", "") or ""
            )
            # Старый MCP не умеет сказать, закончена задача или продолжается, поэтому
            # закрыть её он не может НИКОГДА — он деградирует ровно в сегодняшнее «статус
            # не тронут», но с сохранённой привязкой, чтобы работа не потеряла воркера.
            legacy_task_id = "" if next_task_id else str(row.get("task_id") or "")
            if legacy_task_id:
                result.setdefault("warnings", []).append(
                    _legacy_merge_continue_warning(
                        found.name, legacy_task_id, target,
                    )
                )
            lifecycle_status = await _persist_lifecycle_quarantine(
                found,
                branch=merged_branch,
                base_branch=target,
                task_id=legacy_task_id,
            )
            result["lifecycle_status"] = lifecycle_status
            if not lifecycle_status["ok"]:
                detail = lifecycle_status["error"]
                if task_identity:
                    result["switch"] = {
                        "ok": False,
                        "error": f"switch skipped: post-merge quarantine persistence failed: {detail}",
                    }
                    result["task_status"] = {
                        "ok": False,
                        "error": "task not updated because switch was skipped",
                    }
                return result

            from app import rag_service
            result["rag_backfill_status"] = rag_service.schedule_backfill(row_scope)

            if task_identity:
                par = str(task_identity["par_number"])
                new_branch = f"task-{par}/{expected_name}"
                try:
                    switch_result = await asyncio.to_thread(
                        switch_worktree_branch,
                        worktree_path,
                        new_branch,
                        target,
                        force=True,
                    )
                except Exception as switch_error:
                    detail = err_text(switch_error)
                    switch_result = {
                        "ok": False,
                        "state": "failed",
                        "error": f"branch switch failed: {detail}",
                    }
                if switch_result.get("ok"):
                    switched_branch = switch_result.get("branch", new_branch)
                    try:
                        await manager.transition_lifecycle(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                            task_id=par,
                            needs_switch=False,
                            owned_dirs=[] if str(par) != prior_task_id else None,
                        )
                    except Exception as persist_error:
                        detail = err_text(persist_error)
                        switch_result = {
                            **switch_result,
                            "ok": False,
                            "state": "persistence_failed",
                            "error": (
                                f"branch switched to {switched_branch}, but lifecycle "
                                f"persistence failed: {detail}"
                            ),
                        }
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        if not quarantine_status["ok"]:
                            switch_result["persistence_error"] = (
                                quarantine_status["error"]
                            )
                        result["task_status"] = {
                            "ok": False,
                            "error": "task not updated because switched lifecycle was not persisted",
                        }
                        result["switch"] = switch_result
                        return result
                    try:
                        task_status = await asyncio.to_thread(
                            _tm.api_update_task_if_current,
                            task_identity,
                            status="in_progress",
                        )
                    except Exception as task_error:
                        detail = err_text(task_error)
                        task_status = {"ok": False, "error": detail}
                    if not task_status.get("ok"):
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        task_status["quarantined"] = quarantine_status["ok"]
                        if not quarantine_status["ok"]:
                            task_status["quarantine_error"] = (
                                quarantine_status["error"]
                            )
                    result["task_status"] = task_status
                else:
                    result["task_status"] = {
                        "ok": False,
                        "error": "task not updated because branch switch failed",
                    }
                    if switch_result.get("state") == "rollback_failed":
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=(
                                switch_result.get("actual_branch")
                                or getattr(found, "branch", "")
                                or ""
                            ),
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        if not quarantine_status["ok"]:
                            switch_result["persistence_error"] = (
                                quarantine_status["error"]
                            )
                result["switch"] = switch_result
            return result


async def _promote_current_work_for_task(
    *,
    found,
    task_identity: dict,
    par: str,
    scope: str,
    worktree_path: str,
    new_branch: str,
    from_ref: str,
    requested_owned_dirs: list[str] | None,
    previous_branch: str,
    previous_base_branch: str,
    previous_owned_dirs: list[str],
    waited_seconds: float,
):
    from app import tm as _tm
    from app.workspace import (
        inspect_worktree_identity,
        promote_worktree_branch,
        rollback_promoted_worktree_branch,
    )

    durable = await asyncio.to_thread(get_session_row, found.id)
    if not durable or durable.get("status") == "archived":
        return JSONResponse({"error": "session is not available for promotion"}, status_code=409)
    if durable.get("status") != "idle":
        return JSONResponse({"error": "worker must be idle for promotion"}, status_code=409)
    durable_branch = str(durable.get("branch") or "")
    if str(durable.get("task_id") or ""):
        return JSONResponse({"error": "session is already bound to a task"}, status_code=409)
    if bool(durable.get("needs_switch")):
        return JSONResponse(
            {"error": "normal completed session cannot promote its previous branch"},
            status_code=409,
        )
    if durable_branch != previous_branch or str(getattr(found, "branch", "") or "") != previous_branch:
        return JSONResponse({"error": "session branch changed before promotion"}, status_code=409)
    try:
        actual_branch, worker_head = await asyncio.to_thread(
            inspect_worktree_identity, worktree_path,
        )
    except RuntimeError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    if actual_branch != durable_branch:
        return JSONResponse(
            {"error": f"durable branch {durable_branch} disagrees with Git branch {actual_branch}"},
            status_code=409,
        )
    try:
        await asyncio.to_thread(
            _tm.validate_task_promotion_target,
            task_identity,
            scope=scope,
            session_id=found.id,
            expected_branch=durable_branch,
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)

    latest = await asyncio.to_thread(get_session_row, found.id)
    if (
        not latest
        or latest.get("status") != "idle"
        or str(latest.get("task_id") or "")
        or bool(latest.get("needs_switch"))
        or str(latest.get("branch") or "") != durable_branch
        or str(latest.get("scope") or "").rstrip("/") != scope.rstrip("/")
    ):
        return JSONResponse(
            {"error": "session lifecycle changed before promotion"}, status_code=409,
        )

    promotion = await asyncio.to_thread(
        promote_worktree_branch,
        worktree_path,
        new_branch,
        from_ref=from_ref,
        expected_branch=durable_branch,
        expected_head=worker_head,
    )
    promotion["waited_seconds"] = round(waited_seconds, 2)
    if not promotion.get("ok"):
        if promotion.get("state") == "rollback_failed":
            promotion["lifecycle_status"] = await _persist_lifecycle_quarantine(
                found,
                branch=str(promotion.get("branch") or durable_branch),
                base_branch=from_ref,
                task_id=par,
                needs_switch=True,
            )
        return promotion

    try:
        await manager.transition_lifecycle(
            found,
            branch=new_branch,
            base_branch=from_ref,
            task_id=par,
            needs_switch=True,
            owned_dirs=requested_owned_dirs,
        )
    except Exception as error:
        rollback = await asyncio.to_thread(
            rollback_promoted_worktree_branch,
            worktree_path,
            promoted_branch=new_branch,
            previous_branch=durable_branch,
            expected_head=worker_head,
        )
        if not rollback.get("ok"):
            quarantine = await _persist_lifecycle_quarantine(
                found, branch=rollback.get("branch") or new_branch,
                base_branch=from_ref, task_id=par, needs_switch=True,
            )
            return {
                **promotion,
                "ok": False,
                "state": "rollback_failed",
                "error": f"promotion persistence failed: {err_text(error)}; {rollback.get('error', '')}",
                "rollback": rollback,
                "lifecycle_status": quarantine,
            }
        return {
            **promotion,
            "ok": False,
            "state": "promotion_persistence_failed",
            "branch": rollback["branch"],
            "head": rollback["head"],
            "error": f"promotion persistence failed: {err_text(error)}",
            "rollback": rollback,
        }

    task_status = None
    task_error = None
    try:
        task_status = await asyncio.to_thread(
            _tm.api_update_task_if_current,
            task_identity,
            status="in_progress",
            expected_status="new",
            require_unreserved=True,
        )
    except Exception as error:
        task_error = error

    debt = (task_status or {}).get("projection_debt") or {}
    partial = bool(
        task_error is not None
        or debt
        or (task_status or {}).get("shadow_match") is False
    )
    complete = bool(
        task_error is None
        and task_status
        and task_status.get("ok")
        and not partial
    )
    if not complete and partial:
        message = err_text(task_error) if task_error is not None else str(
            (task_status or {}).get("error") or debt.get("message") or "task binding is partial"
        )
        return {
            **promotion,
            "ok": False,
            "state": (
                "promotion_binding_unknown" if task_error is not None
                else "promotion_binding_partial"
            ),
            "error": message,
            "task_status": task_status or {"ok": False, "error": message},
            "lifecycle_status": {"ok": True, "quarantined": True},
        }
    if not complete:
        rollback = await asyncio.to_thread(
            rollback_promoted_worktree_branch,
            worktree_path,
            promoted_branch=new_branch,
            previous_branch=durable_branch,
            expected_head=worker_head,
        )
        message = str((task_status or {}).get("error") or "task binding was rejected")
        if rollback.get("ok"):
            try:
                await manager.transition_lifecycle(
                    found,
                    branch=durable_branch,
                    base_branch=previous_base_branch,
                    task_id="",
                    needs_switch=False,
                    owned_dirs=previous_owned_dirs,
                )
            except Exception as restore_error:
                quarantine = await _persist_lifecycle_quarantine(
                    found, branch=durable_branch, base_branch=previous_base_branch,
                    task_id=par, needs_switch=True,
                )
                return {
                    **promotion,
                    "ok": False,
                    "state": "rollback_failed",
                    "branch": durable_branch,
                    "head": worker_head,
                    "error": f"{message}; lifecycle restore failed: {err_text(restore_error)}",
                    "rollback": rollback,
                    "lifecycle_status": quarantine,
                }
            return {
                **promotion,
                "ok": False,
                "state": "promotion_binding_failed",
                "branch": durable_branch,
                "head": worker_head,
                "error": message,
                "rollback": rollback,
                "task_status": task_status,
            }
        quarantine = await _persist_lifecycle_quarantine(
            found,
            branch=str(rollback.get("branch") or new_branch),
            base_branch=from_ref,
            task_id=par,
            needs_switch=True,
        )
        return {
            **promotion,
            "ok": False,
            "state": "rollback_failed",
            "error": f"{message}; {rollback.get('error', '')}",
            "rollback": rollback,
            "task_status": task_status,
            "lifecycle_status": quarantine,
        }

    try:
        await manager.transition_lifecycle(
            found,
            branch=new_branch,
            base_branch=from_ref,
            task_id=par,
            needs_switch=False,
            owned_dirs=requested_owned_dirs,
        )
    except Exception as error:
        quarantine = await _persist_lifecycle_quarantine(
            found, branch=new_branch, base_branch=from_ref,
            task_id=par, needs_switch=True,
        )
        return {
            **promotion,
            "ok": False,
            "state": "promotion_binding_partial",
            "error": f"task bound but lifecycle finalization failed: {err_text(error)}",
            "task_status": task_status,
            "lifecycle_status": quarantine,
        }
    return {**promotion, "task_status": task_status}


@router.post("/api/sessions/{name}/switch-branch")
async def switch_branch(name: str, req: dict):
    from app.workspace import inspect_worktree_identity, switch_worktree_branch
    from app import tm as _tm
    scope = req.get("scope", "")
    task_id = req.get("task_id", "")
    force = req.get("force", False)
    promote_current = req.get("promote_current", False)
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    if not isinstance(force, bool):
        return JSONResponse({"error": "force must be a boolean"}, status_code=400)
    if not isinstance(promote_current, bool):
        return JSONResponse({"error": "promote_current must be a boolean"}, status_code=400)
    if promote_current and force:
        return JSONResponse(
            {"error": "promote_current cannot be combined with force"}, status_code=400,
        )
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    scope = (getattr(found, "scope", "") or scope).rstrip("/")
    try:
        task_identity = await asyncio.to_thread(
            _tm.resolve_scoped_task_identity, scope, task_id,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    par = str(task_identity["par_number"])
    new_task = str(getattr(found, "task_id", "") or "") != par
    requested_owned_dirs = None
    if new_task:
        raw_owned_dirs = req.get("owned_dirs", [])
        if raw_owned_dirs is None:
            raw_owned_dirs = []
        if not isinstance(raw_owned_dirs, list):
            return JSONResponse({"error": "owned_dirs must be a JSON array"}, status_code=400)
        try:
            requested_owned_dirs = manager.validate_owned_dirs_transition(
                found, raw_owned_dirs,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    worktree_path = found.worktree_path
    session_id = found.id
    previous_branch = getattr(found, "branch", "") or ""
    previous_base_branch = getattr(found, "base_branch", "") or ""
    previous_task_id = str(getattr(found, "task_id", "") or "")
    previous_needs_switch = bool(getattr(found, "needs_switch", False))
    previous_owned_dirs = list(getattr(found, "owned_dirs", []) or [])
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    new_branch = f"task-{par}/{name}"
    try:
        from_ref = _session_base_branch(found, req.get("from_ref", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from app.manager import LockBusy, wait_for_session_lock

    try:
        # Уступает явный switch, а не доставка: доставка уже в полёте и откату не подлежит,
        # switch повторяется дёшево. Уступка при этом ГРОМКАЯ — в этом весь смысл (#27).
        async with wait_for_session_lock(
            manager.get_session_lock(session_id),
            what="switch_worker_branch", worker=name,
        ) as waited_seconds:
            if not await _wait_for_merge_idle(found):
                return JSONResponse(
                    {"error": f"worker is {found.status.value} — wait for idle before switch"},
                    status_code=400,
                )
            async with AsyncExitStack() as stack:
                if found.loaded:
                    await stack.enter_async_context(found._lifecycle_lock)
                    if found.status.value != "idle":
                        return JSONResponse(
                            {
                                "error": (
                                    f"worker is {found.status.value} — "
                                    "wait for idle before switch"
                                )
                            },
                            status_code=400,
                        )
                if promote_current:
                    return await _promote_current_work_for_task(
                        found=found,
                        task_identity=task_identity,
                        par=par,
                        scope=scope,
                        worktree_path=worktree_path,
                        new_branch=new_branch,
                        from_ref=from_ref,
                        requested_owned_dirs=requested_owned_dirs,
                        previous_branch=previous_branch,
                        previous_base_branch=previous_base_branch,
                        previous_owned_dirs=previous_owned_dirs,
                        waited_seconds=waited_seconds,
                    )
                if not new_task and previous_branch == new_branch:
                    if not previous_needs_switch:
                        return {
                            "ok": True,
                            "state": "already_current",
                            "branch": previous_branch,
                            "waited_seconds": round(waited_seconds, 2),
                            "message": "task/branch binding is already healthy; no changes made",
                        }
                    try:
                        actual_branch, actual_head = await asyncio.to_thread(
                            inspect_worktree_identity, worktree_path,
                        )
                    except Exception as inspect_error:
                        return JSONResponse(
                            {
                                "error": (
                                    "lifecycle repair refused: actual Git identity is "
                                    f"unavailable: {err_text(inspect_error)}"
                                )
                            },
                            status_code=409,
                        )
                    if actual_branch != new_branch:
                        return JSONResponse(
                            {
                                "error": (
                                    f"lifecycle repair refused: durable branch {new_branch} "
                                    f"does not match actual branch {actual_branch or '<detached>'} "
                                    f"at {actual_head or '<unknown>'}"
                                )
                            },
                            status_code=409,
                        )
                    try:
                        binding = await asyncio.to_thread(
                            _tm.validate_task_binding_repair, scope, session_id, par,
                        )
                        await manager.transition_lifecycle(
                            found,
                            branch=previous_branch,
                            base_branch=previous_base_branch,
                            task_id=par,
                            needs_switch=False,
                        )
                    except Exception as repair_error:
                        return JSONResponse(
                            {
                                "error": (
                                    "lifecycle repair failed without changing the binding: "
                                    f"{err_text(repair_error)}"
                                )
                            },
                            status_code=409,
                        )
                    return {
                        "ok": True,
                        "state": "lifecycle_repaired",
                        "branch": previous_branch,
                        "task_status": binding,
                        "waited_seconds": round(waited_seconds, 2),
                        "message": "task/branch binding repaired",
                    }
                try:
                    verdict = await asyncio.to_thread(
                        _existing_branch_verdict, worktree_path, new_branch,
                        found.scope or scope, force,
                    )
                    if verdict.get("error"):
                        return JSONResponse(
                            {**verdict, "waited_seconds": round(waited_seconds, 2)},
                            status_code=409,
                        )
                    result = await asyncio.to_thread(
                        switch_worktree_branch,
                        worktree_path,
                        new_branch,
                        from_ref=from_ref,
                        force=force or verdict["discard_current"],
                        recreate_from_base=verdict["recreate_from_base"],
                    )
                    # Ставится СРАЗУ, до ветвлений: ожидание должно быть видно и в успехе,
                    # и в любом отказе — иначе поле окажется ровно там, где не нужно.
                    result["waited_seconds"] = round(waited_seconds, 2)
                    if result.get("ok"):
                        switched_branch = result.get("branch", new_branch)
                        try:
                            await manager.transition_lifecycle(
                                found,
                                branch=switched_branch,
                                base_branch=from_ref,
                                task_id=par,
                                needs_switch=False,
                                owned_dirs=requested_owned_dirs,
                            )
                        except Exception as persist_error:
                            detail = err_text(persist_error)
                            result = {
                                **result,
                                "ok": False,
                                "state": "persistence_failed",
                                "error": (
                                    f"branch switched to {switched_branch}, but lifecycle "
                                    f"persistence failed: {detail}"
                                ),
                            }
                            quarantine_status = await _persist_lifecycle_quarantine(
                                found,
                                branch=switched_branch,
                                base_branch=from_ref,
                            )
                            if not quarantine_status["ok"]:
                                result["persistence_error"] = quarantine_status["error"]
                            result["task_status"] = {
                                "ok": False,
                                "error": "task not updated because switched lifecycle was not persisted",
                            }
                            return result
                        task_assignment_raised = False
                        try:
                            result["task_status"] = await asyncio.to_thread(
                                _tm.api_update_task_if_current,
                                task_identity,
                                status="in_progress",
                            )
                        except Exception as task_error:
                            task_assignment_raised = True
                            detail = err_text(task_error)
                            result["task_status"] = {"ok": False, "error": detail}
                        if not result["task_status"].get("ok"):
                            if task_assignment_raised and previous_branch:
                                try:
                                    rollback = await asyncio.to_thread(
                                        switch_worktree_branch,
                                        worktree_path,
                                        previous_branch,
                                        from_ref=previous_branch,
                                        force=True,
                                    )
                                except Exception as rollback_error:
                                    rollback = {
                                        "ok": False,
                                        "error": f"branch rollback failed: {err_text(rollback_error)}",
                                    }
                                if rollback.get("ok"):
                                    try:
                                        await manager.transition_lifecycle(
                                            found,
                                            branch=previous_branch,
                                            base_branch=previous_base_branch,
                                            task_id=previous_task_id,
                                            needs_switch=previous_needs_switch,
                                            owned_dirs=previous_owned_dirs,
                                        )
                                    except Exception as restore_error:
                                        rollback = {
                                            **rollback,
                                            "ok": False,
                                            "error": (
                                                "branch rolled back but lifecycle restore failed: "
                                                f"{err_text(restore_error)}"
                                            ),
                                        }
                                if rollback.get("ok"):
                                    result.update(
                                        ok=False,
                                        state="task_assignment_failed",
                                        error=(
                                            "branch switch rolled back after task assignment failed: "
                                            f"{result['task_status']['error']}"
                                        ),
                                        rollback=rollback,
                                    )
                                    return result
                            quarantine_status = await _persist_lifecycle_quarantine(
                                found,
                                branch=switched_branch,
                                base_branch=from_ref,
                            )
                            result["task_status"]["quarantined"] = (
                                quarantine_status["ok"]
                            )
                            if not quarantine_status["ok"]:
                                result["task_status"]["quarantine_error"] = (
                                    quarantine_status["error"]
                                )
                            result.update(
                                ok=False,
                                state="task_assignment_failed",
                                error=(
                                    "branch switched, but task assignment failed: "
                                    f"{result['task_status']['error']}"
                                ),
                            )
                    elif result.get("state") == "rollback_failed":
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=result.get("actual_branch") or getattr(found, "branch", "") or "",
                            base_branch=from_ref,
                        )
                        if not quarantine_status["ok"]:
                            result["persistence_error"] = quarantine_status["error"]
                    else:
                        # Failed/rolled-back Git leaves the previous lifecycle and
                        # ownership untouched. A rollback failure is quarantined above.
                        pass
                    return result
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)
    except LockBusy as busy:
        return JSONResponse(
            {"error": str(busy), "waited_seconds": round(busy.waited, 1)},
            status_code=409,
        )


@router.get("/api/sessions/{name}/wip")
async def session_wip(name: str, scope: str = "", base_ref: str = ""):
    from app.workspace import branch_wip_status
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    worktree_path = found.worktree_path
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    try:
        base_ref = _session_base_branch(found, base_ref)
        result = branch_wip_status(worktree_path, base_ref=base_ref)
        d = found.to_dict()
        result["context_pct"] = d.get("context_pct", 0)
        result["status"] = d.get("status", "unknown")
        lifecycle = manager.lifecycle_quarantine(found)
        if lifecycle:
            result["status"] = "quarantined"
            result["lifecycle_status"] = lifecycle
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/sessions/check-conflict")
async def check_conflict_endpoint(req: dict):
    from app.workspace import simulate_conflict
    scope = req.get("scope", "")
    name_a = req.get("worker_a", "")
    name_b = req.get("worker_b", "")
    a = manager.get_by_name(name_a, scope)
    b = manager.get_by_name(name_b, scope)
    if not a or not b:
        missing = name_a if not a else name_b
        return JSONResponse({"error": f"worker '{missing}' not found"}, status_code=404)
    wt_a = a.worktree_path
    branch_a = a.branch
    branch_b = b.branch
    if not wt_a or not branch_a or not branch_b:
        return JSONResponse({"error": "both workers must have a worktree and branch"}, status_code=400)
    try:
        return simulate_conflict(wt_a, branch_a, branch_b)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/sessions/{name}/progress")
async def update_progress(name: str, req: dict):
    scope = req.get("scope", "")
    pct = max(0, min(100, int(req.get("percent", 0))))
    status_text = str(req.get("status", ""))
    session = manager.get_by_name(name, scope)
    if not session or not session.loaded:
        # progress is live-only: detached sessions 404 (write would flip legacy 404→200)
        session = next((s for s in manager.sessions.values() if s.name == name), None)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    session.progress_pct = pct
    session.progress_status = status_text
    session._persist()
    return {"ok": True}


@router.patch("/api/sessions/{name}/tg-topic")
async def toggle_tg_topic(name: str, scope: str, enabled: bool):
    from app.db import save_session
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    found.tg_topic = enabled
    save_session(found.to_dict())
    return {"ok": True, "name": name, "tg_topic": enabled}
