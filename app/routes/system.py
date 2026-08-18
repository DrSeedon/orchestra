"""System routes: dashboard/auth pages, files, projects, profiles, usage,
orchestrators, test-lock, restart, GitHub webhook."""

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.auth import is_auth_enabled, is_owner_mode, require_operator_session
from app.db import get_all_sessions, list_profiles, upsert_profile, delete_profile
from app.deps import build_id, manager, templates
from app.errtext import err_text
from app.models import (
    MODELS,
    cache_policy_for_runtime,
    get_model_spec,
    is_proxy_connected,
    provider_metadata_payload,
    runtime_for_record,
)
from app.pipeline import list_pipelines
from app.runtime_registry import get_runtime
from app.runtime_router import (
    PolicyRevisionError,
    ROUTING_CONTRACT_VERSION,
    explain_inputs_from_dict,
    get_runtime_router,
)

logger = logging.getLogger("orchestra.system")

router = APIRouter()


def get_quota_controller():
    """Return the process-owned, non-enforcing shadow observer."""
    from app.quota_controller import get_quota_controller as get_controller

    return get_controller()


class ProfileRequest(BaseModel):
    """Тело запроса для создания/обновления профиля Claude."""
    name: str
    config_dir: str = ""


class TestLockRequest(BaseModel):
    scope: str
    holder: str
    reason: str = ""
    # Поле ДОБАВЛЯЕТСЯ: старый MCP его не шлёт, и тогда держатель сравнивается по имени.
    holder_session_id: str = ""


class ChangeScopeRequest(BaseModel):
    old_scope: str
    new_scope: str
    new_cwd: Optional[str] = None


# ── Pages / auth ──

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "currency_symbol": os.getenv("CURRENCY_SYMBOL", "₽"),
        "hide_thinking": is_auth_enabled(),
        "is_auth_enabled": is_auth_enabled(),
        "is_owner_mode": is_owner_mode(),
        "client_name": os.getenv("CLIENT_NAME", "Client"),
    # Кешировать HTML нельзя: в нём лежат версии статики, устареет он — версии
    # не обновятся, и весь механизм из #9 перестанет работать
    }, headers={"Cache-Control": "no-cache"})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": ""},
                                      headers={"Cache-Control": "no-cache"})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
    from app.auth import check_credentials, create_session
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=302)
    if check_credentials(username, password):
        token = create_session(username)
        response = RedirectResponse("/", status_code=302)
        secure = request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"
        response.set_cookie("session", token, httponly=True, samesite="lax", max_age=2592000, secure=secure)
        return response
    return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})


@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ── Projects / files ──

def _encode_path(path: str) -> str:
    return "".join("-" if (c == "/" or c == " " or ord(c) > 127) else c for c in path)


def _build_path_map() -> dict[str, str]:
    scan_roots = [
        "/mnt/data/Projects/Python",
        "/mnt/data/Projects/Unity",
        "/mnt/data/Projects",
        str(Path.home()),
    ]
    mapping = {}
    for root in scan_roots:
        if not Path(root).is_dir():
            continue
        mapping[_encode_path(root)] = root
        for entry in Path(root).iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                mapping[_encode_path(str(entry))] = str(entry)
    return mapping


@router.get("/api/projects")
async def list_projects():
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []
    path_map = _build_path_map()
    results = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        real_path = path_map.get(entry.name)
        if not real_path or not Path(real_path).is_dir():
            continue
        if real_path == str(Path.home()):
            continue
        folder = real_path.rstrip("/").split("/")[-1]
        results.append({"path": real_path, "name": folder})
    return results


_ALLOWED_ROOTS: list[str] = []


def _get_allowed_roots() -> list[str]:
    # Lazy init: ALLOWED_ROOTS env lets operators add extra roots without code changes;
    # standard data directories are always included as a baseline
    if _ALLOWED_ROOTS:
        return _ALLOWED_ROOTS
    extra = os.environ.get("ALLOWED_ROOTS", "")
    if extra:
        for p in extra.split(":"):
            if p and Path(p).is_dir():
                _ALLOWED_ROOTS.append(p)
    for root in ["/mnt/data", "/opt", "/tmp", str(Path.home())]:
        if Path(root).is_dir():
            _ALLOWED_ROOTS.append(root)
    uploads = str(Path(__file__).parent.parent.parent / "data" / "uploads")
    _ALLOWED_ROOTS.append(uploads)
    return _ALLOWED_ROOTS


# Block access to secrets and key material even if they live inside an allowed root
_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube", "opencode.json"}
_DENIED_HOME_PARTS = {".claude", ".config"}
_DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}


def _is_safe_path(path: str) -> bool:
    try:
        p = Path(path).resolve()
        resolved = str(p)
    except (ValueError, OSError):
        return False
    def _within(root: str) -> bool:
        try:
            return os.path.commonpath([os.path.realpath(root), resolved]) == os.path.realpath(root)
        except (ValueError, OSError):
            return False
    if not any(_within(root) for root in _get_allowed_roots()):
        return False
    home = str(Path.home())
    for part in p.parts:
        if part in _DENIED_PARTS or part.startswith(".env"):
            return False
    if resolved.startswith(home):
        for part in _DENIED_HOME_PARTS:
            if f"{home}/{part}" in resolved:
                return False
    if p.suffix in _DENIED_EXTENSIONS:
        return False
    return True


BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
                     '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z',
                     '.exe', '.bin', '.so', '.whl', '.dll', '.dylib', '.pyc',
                     '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.mp3', '.mp4',
                     '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2'}


@router.get("/api/files/raw")
async def get_file_raw(path: str, download: bool = False):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from starlette.responses import FileResponse
    target = Path(path)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    headers = {}
    if target.suffix.lower() in {".html", ".htm"}:
        headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; "
            "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
            "connect-src 'none'"
        )
    # download=1 forces a save dialog (Content-Disposition: attachment); default lets
    # the browser render HTML inline under the sandbox CSP.
    filename = target.name if download else None
    return FileResponse(str(target), filename=filename, headers=headers)


@router.get("/api/files/content")
async def get_file_content(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    if not target.is_file():
        return JSONResponse({"error": "not a file"}, status_code=400)
    size = target.stat().st_size
    if target.suffix.lower() in BINARY_EXTENSIONS:
        return JSONResponse({"error": "binary file", "size": size})
    if size > 500 * 1024:
        return JSONResponse({"error": "too large", "size": size})
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "size": size, "name": str(target)}


@router.post("/api/open-folder")
async def open_folder(req: dict):
    if not os.environ.get("ALLOW_OPEN_FOLDER"):
        return JSONResponse({"error": "disabled on this server"}, status_code=403)
    import subprocess
    path = req.get("path", "")
    if not Path(path).is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.Popen(["xdg-open", path], env=env)
    return {"ok": True}


@router.get("/api/files")
async def list_files(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError as e:
        logger.debug(f"file listing partial (permission denied): {e}")
    return items


# ── Catalogs ──

@router.get("/api/role-icons")
async def role_icons():
    from app.prompting import get_role_icons
    return get_role_icons()


@router.get("/api/pipelines")
async def get_pipelines():
    """Только валидные пайплайны для UI-дропдаунa: ``[{name, description, roles}]``."""
    return [
        {"name": p["name"], "description": p["description"], "roles": p["roles"]}
        for p in list_pipelines()
        if p["valid"]
    ]


@router.get("/api/profiles")
async def get_profiles():
    """Все профили Claude: ``[{name, config_dir}]``."""
    if not is_owner_mode():
        raise HTTPException(403, "Not available")
    return list_profiles()


@router.post("/api/profiles")
async def create_profile(req: ProfileRequest):
    """Создать или обновить профиль."""
    if not is_owner_mode():
        raise HTTPException(403, "Not available")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", req.name):
        return JSONResponse(
            {"error": "name must be alphanumeric with ._- allowed, 1-50 chars"},
            status_code=400,
        )
    warning = None
    config_dir = req.config_dir
    if config_dir and not Path(os.path.expanduser(config_dir)).is_dir():
        warning = (
            f"config_dir '{config_dir}' не существует — будет создан CLI "
            "или приведёт к ошибке при запуске"
        )
    upsert_profile(req.name, config_dir)
    return {"profiles": list_profiles(), "warning": warning}


@router.delete("/api/profiles/{name}")
async def remove_profile(name: str):
    """Удалить профиль."""
    if not is_owner_mode():
        raise HTTPException(403, "Not available")
    try:
        delete_profile(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return list_profiles()


@router.get("/api/models")
async def list_models(response: Response):
    # Версию фронта отдаём ЗАГОЛОВКОМ, а не полем в теле: heartbeat дёргает этот маршрут
    # раз в 3 с и читает только статус — разбирать ради одного значения несколько
    # килобайт JSON незачем. Тело маршрута при этом не меняется, старый клиент цел.
    response.headers["X-Orchestra-Build"] = build_id()
    models = []
    for mid, name in MODELS.items():
        spec = get_model_spec(mid)
        entry = {
            "id": mid,
            "name": name,
            "runtime": spec.runtime,
            "backend": spec.runtime,
            "provider": spec.provider,
            "context_length": spec.context_length,
            "capabilities": get_runtime(spec.runtime).capabilities.to_dict(),
        }
        if spec.price_input is not None:
            entry["price_input"] = spec.price_input
        if spec.price_output is not None:
            entry["price_output"] = spec.price_output
        models.append(entry)
    return {
        "models": models,
        "provider_metadata": provider_metadata_payload(),
        "proxy_connected": is_proxy_connected(),
    }


@router.head("/api/models")
async def head_models():
    """Heartbeat'у нужны только статус и версия сборки — тело GET'а он выбрасывает.
    Тот же заголовок, что у GET: без него баннер обновления замолчит, не сломавшись."""
    return Response(status_code=200, headers={"X-Orchestra-Build": build_id()})


@router.post("/api/models/refresh")
async def refresh_models_endpoint():
    from app.models import refresh_models
    await refresh_models()
    return {"ok": True, "proxy_connected": is_proxy_connected(), "model_count": len(MODELS)}


@router.get("/api/stats")
async def stats(scope: Optional[str] = None):
    return manager.stats(scope)


# ── Usage (subscription limits) ──

_USAGE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_cache.json"
_usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
_codex_usage_cache: dict = {"data": None, "ts": 0.0}
_grok_usage_cache: dict = {"data": None, "ts": 0.0}
_USAGE_CACHE_TTL = 300
_quota_refresh_locks = {
    "anthropic": asyncio.Lock(),
    "codex": asyncio.Lock(),
    "grok": asyncio.Lock(),
}
_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
_GROK_CREDENTIALS_PATH = Path.home() / ".grok" / "auth.json"


def _load_usage_cache():
    if _USAGE_CACHE_FILE.exists():
        try:
            cached = json.loads(_USAGE_CACHE_FILE.read_text())
            _usage_cache["data"] = cached.get("data")
            _usage_cache["ts"] = cached.get("ts", 0.0)
        except Exception as e:
            logger.warning(f"usage cache load failed: {e}")


def _save_usage_cache():
    try:
        _USAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE_CACHE_FILE.write_text(json.dumps({"data": _usage_cache["data"], "ts": _usage_cache["ts"]}))
    except Exception as e:
        logger.warning(f"usage cache save failed: {e}")


_load_usage_cache()


def _read_oauth_credentials() -> tuple[str | None, str | None, str | None]:
    """Read accessToken, refreshToken, and rateLimitTier from credentials file."""
    try:
        creds = json.loads(_CREDENTIALS_PATH.read_text())
        oauth = creds.get("claudeAiOauth", {})
        return oauth.get("accessToken"), oauth.get("refreshToken"), oauth.get("rateLimitTier")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None, None, None


def _read_grok_token() -> str | None:
    """Read the freshest Grok CLI bearer without persisting its short-lived token."""
    try:
        credentials = json.loads(_GROK_CREDENTIALS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    candidates = [
        value for value in credentials.values()
        if isinstance(value, dict) and isinstance(value.get("key"), str) and value["key"]
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda value: str(value.get("expires_at") or ""))
    return latest["key"]


async def _fetch_anthropic_usage(token: str) -> dict:
    """Call Anthropic OAuth usage API. Raises PermissionError on 401, RuntimeError on 429."""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
            },
        )
        if resp.status_code == 401:
            raise PermissionError("token_expired")
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        resp.raise_for_status()
        return resp.json()


def _normalize_codex_window(window: dict | None) -> dict | None:
    if not isinstance(window, dict):
        return None
    used = window.get("usedPercent")
    duration = window.get("windowDurationMins")
    if not isinstance(used, (int, float)) or not isinstance(duration, int) or duration <= 0:
        return None
    resets_at = window.get("resetsAt")
    reset_iso = None
    if isinstance(resets_at, (int, float)) and resets_at > 0:
        reset_iso = datetime.fromtimestamp(resets_at, timezone.utc).isoformat().replace("+00:00", "Z")
    utilization = max(0, min(100, used))
    return {
        "utilization": int(utilization) if float(utilization).is_integer() else utilization,
        "window_minutes": duration,
        "resets_at": reset_iso,
    }


def _normalize_codex_usage(result: dict) -> dict:
    by_limit = result.get("rateLimitsByLimitId") or {}
    limits = by_limit.get("codex") or result.get("rateLimits") or {}
    credits = limits.get("credits") or {}
    reset_credits = result.get("rateLimitResetCredits") or {}
    usage = {
        "plan_type": limits.get("planType"),
        "primary": _normalize_codex_window(limits.get("primary")),
        "secondary": _normalize_codex_window(limits.get("secondary")),
        "credits": {
            "has_credits": bool(credits.get("hasCredits")),
            "unlimited": bool(credits.get("unlimited")),
            "balance": credits.get("balance"),
        },
        "reset_credits": reset_credits.get("availableCount", 0),
    }
    spark_limits = by_limit.get("codex_bengalfox")
    if isinstance(spark_limits, dict):
        usage["spark"] = {
            "limit_id": "codex_bengalfox",
            "plan_type": spark_limits.get("planType"),
            "primary": _normalize_codex_window(spark_limits.get("primary")),
            "secondary": _normalize_codex_window(spark_limits.get("secondary")),
        }
    return usage


def _normalize_grok_usage(result: dict) -> dict | None:
    config = result.get("config")
    if not isinstance(config, dict):
        return None
    period = config.get("currentPeriod")
    used = config.get("creditUsagePercent")
    if (
        not isinstance(period, dict)
        or period.get("type") != "USAGE_PERIOD_TYPE_WEEKLY"
        or not isinstance(used, (int, float))
        or isinstance(used, bool)
    ):
        return None
    try:
        start = datetime.fromisoformat(str(period["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(period["end"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None:
        return None
    duration_seconds = (end - start).total_seconds()
    if duration_seconds <= 0 or duration_seconds % 60:
        return None
    utilization = max(0, min(100, used))
    reset_iso = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "plan_type": result.get("subscription_tier"),
        "primary": {
            "utilization": int(utilization) if float(utilization).is_integer() else utilization,
            "window_minutes": int(duration_seconds // 60),
            "resets_at": reset_iso,
        },
        "secondary": None,
    }


async def _fetch_grok_usage(token: str) -> dict | None:
    """Read the weekly credits view exposed by the Grok CLI billing backend."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://cli-chat-proxy.grok.com/v1/billing",
            params={"format": "credits"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code == 401:
            raise PermissionError("token_expired")
        resp.raise_for_status()
        return _normalize_grok_usage(resp.json())


def _usage_window_label(window_minutes: int) -> str:
    if window_minutes % 1440 == 0:
        return f"{window_minutes // 1440}d"
    if window_minutes % 60 == 0:
        return f"{window_minutes // 60}h"
    return f"{window_minutes}m"


def _provider_usage_snapshot(
    anthropic: dict | None,
    codex: dict | None,
    grok: dict | None = None,
) -> dict:
    """Normalize provider-specific limits into one history/chart contract."""
    providers = {}
    anthropic_windows = []
    for window_id, label, minutes in (
        ("five_hour", "5h", 300),
        ("seven_day", "7d", 10080),
    ):
        window = (anthropic or {}).get(window_id)
        if not isinstance(window, dict) or not isinstance(window.get("utilization"), (int, float)):
            continue
        anthropic_windows.append({
            "id": window_id,
            "label": label,
            "utilization": window["utilization"],
            "window_minutes": minutes,
            "resets_at": window.get("resets_at"),
        })
    if anthropic_windows:
        providers["anthropic"] = {"label": "Claude", "windows": anthropic_windows}

    fable = next(
        (
            limit for limit in (anthropic or {}).get("limits", [])
            if (
                isinstance(limit, dict)
                and limit.get("kind") == "weekly_scoped"
                and str(limit.get("scope_model_display_name", "")).casefold() == "fable"
                and isinstance(limit.get("percent"), (int, float))
                and not isinstance(limit.get("percent"), bool)
            )
        ),
        None,
    )
    if fable is not None:
        providers["anthropic_fable"] = {
            "label": "Claude Fable",
            "windows": [{
                "id": "weekly_scoped",
                "label": "7d",
                "utilization": fable["percent"],
                "window_minutes": 10080,
                "resets_at": fable.get("resets_at"),
            }],
        }

    for provider_id, label, usage in (
        ("codex", "Codex", codex),
        ("codex_spark", "Codex Spark", (codex or {}).get("spark")),
        ("grok", "Grok", grok),
    ):
        windows = []
        for window_id in ("primary", "secondary"):
            window = (usage or {}).get(window_id)
            if not isinstance(window, dict) or not isinstance(window.get("utilization"), (int, float)):
                continue
            minutes = window.get("window_minutes")
            if not isinstance(minutes, int) or minutes <= 0:
                continue
            windows.append({
                "id": window_id,
                "label": _usage_window_label(minutes),
                "utilization": window["utilization"],
                "window_minutes": minutes,
                "resets_at": window.get("resets_at"),
            })
        if windows:
            providers[provider_id] = {
                "label": label,
                "plan_type": (usage or {}).get("plan_type"),
                "windows": windows,
            }
    return providers


async def _fetch_codex_usage() -> dict:
    """Read ChatGPT subscription limits through Codex's local app-server protocol."""
    from app.backend_codex import CODEX_BIN

    proc = await asyncio.create_subprocess_exec(
        CODEX_BIN, "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def send(message: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

    try:
        await send({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "orchestra-dashboard", "title": "Orchestra dashboard", "version": "1"},
                "capabilities": None,
            },
        })
        assert proc.stdout is not None
        init = json.loads((await asyncio.wait_for(proc.stdout.readline(), timeout=5)).decode())
        if init.get("id") != 1 or init.get("error"):
            raise RuntimeError(f"Codex app-server initialization failed: {init.get('error', 'invalid response')}")

        await send({"method": "initialized"})
        await send({"id": 2, "method": "account/rateLimits/read", "params": None})
        async with asyncio.timeout(10):
            while line := await proc.stdout.readline():
                response = json.loads(line)
                if response.get("id") != 2:
                    continue
                if response.get("error"):
                    raise RuntimeError(f"Codex rate limit fetch failed: {response['error']}")
                return _normalize_codex_usage(response.get("result") or {})
        raise RuntimeError("Codex app-server closed without a rate limit response")
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def _refresh_oauth_token(refresh_token: str) -> str | None:
    """Refresh expired OAuth token. Returns new access token or None."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://platform.claude.com/v1/oauth/token",
                json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")
    except Exception as e:
        logger.warning(f"OAuth token refresh failed: {e}")
    return None


def _cost_cached_for(r) -> float:
    """Cached cost recomputed from RAW tokens + current TOKEN_PRICES, so a price
    change reprices history. Fallback to stored cost_usd_cached when we can't
    recompute (no price for model, or no raw cache tokens = old/no-cache rows).
    Mirrors backend_claude.py:396 (cache_read=10% input, cache_create=125% input)."""
    from app.models import TOKEN_PRICES
    stored = r["cost_usd_cached"] or 0
    prices = TOKEN_PRICES.get(r["model"])
    cache_read = r["total_cache_read_tokens"] or 0
    cache_create = r["total_cache_create_tokens"] or 0
    if not prices or (cache_read == 0 and cache_create == 0):
        return stored
    p_in = prices["input"]
    p_out = prices["output"]
    return ((r["total_input_tokens"] or 0) * p_in
            + cache_read * p_in * 0.1
            + cache_create * p_in * 1.25
            + (r["total_output_tokens"] or 0) * p_out) / 1_000_000


def _get_agents_cost() -> dict:
    """Get per-agent cost breakdown from DB."""
    from app.db import _conn
    with _conn() as c:
        rows = c.execute(
            "SELECT name, model, cost_usd, cost_usd_cached, "
            "total_input_tokens, total_output_tokens, "
            "total_cache_read_tokens, total_cache_create_tokens "
            "FROM sessions ORDER BY cost_usd DESC"
        ).fetchall()
        total = sum(r["cost_usd"] for r in rows)
        cached_by_row = [_cost_cached_for(r) for r in rows]
        total_cached = sum(cached_by_row)
        agents = [
            {"name": r["name"], "cost_usd": round(r["cost_usd"], 4),
             "cost_usd_cached": round(cc, 4), "model": r["model"]}
            for r, cc in zip(rows, cached_by_row) if r["cost_usd"] > 0
        ]
        return {
            "total_cost_usd": round(total, 4),
            "total_cost_usd_cached": round(total_cached, 4),
            "agents_count": len(agents),
            "agents": agents,
        }


def _get_voice_cost_usd() -> float:
    from app.db import voice_cost_total_usd
    return voice_cost_total_usd()


async def _get_usage_data(
    *,
    force_refresh: bool = False,
    required_provider: str = "",
) -> dict:
    now = time.time()

    anthropic_data = None
    anthropic_fetched = False
    skip_anthropic_refresh = bool(required_provider) and required_provider != "anthropic"
    if skip_anthropic_refresh:
        anthropic_data = _usage_cache["data"]
    elif (
        not force_refresh
        and _usage_cache["data"]
        and (now - _usage_cache["ts"]) < _USAGE_CACHE_TTL
    ):
        anthropic_data = _usage_cache["data"]
    else:
        token, refresh_token, _tier = _read_oauth_credentials()
        if token:
            try:
                anthropic_data = await _fetch_anthropic_usage(token)
                anthropic_fetched = True
            except PermissionError:
                if refresh_token:
                    new_token = await _refresh_oauth_token(refresh_token)
                    if new_token:
                        try:
                            anthropic_data = await _fetch_anthropic_usage(new_token)
                            anthropic_fetched = True
                            _usage_cache["token"] = new_token
                        except Exception as error:
                            logger.warning(
                                f"Anthropic usage fetch after refresh failed: {error}"
                            )
                    else:
                        logger.warning("Anthropic token refresh failed")
                else:
                    logger.warning("Anthropic token expired without refresh token")
            except Exception as error:
                logger.warning(f"Anthropic usage fetch failed: {error}")
        else:
            logger.warning("Anthropic usage unavailable: no OAuth credentials")

        if anthropic_data is None:
            anthropic_data = _usage_cache["data"]
        if required_provider == "anthropic" and not anthropic_fetched:
            raise RuntimeError("fresh Anthropic usage is unavailable")
        if anthropic_fetched:
            _usage_cache["data"] = anthropic_data
            _usage_cache["ts"] = now
            _save_usage_cache()

    codex_fetched = False
    skip_codex_refresh = bool(required_provider) and required_provider not in {
        "codex", "codex_spark",
    }
    if skip_codex_refresh:
        codex_data = _codex_usage_cache["data"]
    elif (
        not force_refresh
        and _codex_usage_cache["data"]
        and (now - _codex_usage_cache["ts"]) < _USAGE_CACHE_TTL
    ):
        codex_data = _codex_usage_cache["data"]
    else:
        try:
            codex_data = await _fetch_codex_usage()
            codex_fetched = codex_data is not None
            if codex_fetched:
                _codex_usage_cache["data"] = codex_data
                _codex_usage_cache["ts"] = now
            else:
                codex_data = _codex_usage_cache["data"]
        except Exception as e:
            logger.warning(f"Codex usage fetch failed: {e}")
            codex_data = _codex_usage_cache["data"]
    if required_provider in {"codex", "codex_spark"} and not codex_fetched:
        raise RuntimeError("fresh Codex usage is unavailable")

    grok_data = None
    grok_fetched = False
    skip_grok_refresh = bool(required_provider) and required_provider != "grok"
    if skip_grok_refresh:
        grok_data = _grok_usage_cache["data"]
    elif (
        not force_refresh
        and _grok_usage_cache["data"]
        and (now - _grok_usage_cache["ts"]) < _USAGE_CACHE_TTL
    ):
        grok_data = _grok_usage_cache["data"]
    else:
        token = _read_grok_token()
        if token:
            try:
                grok_data = await _fetch_grok_usage(token)
                grok_fetched = grok_data is not None
            except PermissionError:
                logger.warning("Grok usage unavailable: OAuth token expired")
            except Exception as error:
                logger.warning(f"Grok usage fetch failed: {error}")
        else:
            logger.warning("Grok usage unavailable: no OAuth credentials")
        if grok_fetched:
            _grok_usage_cache["data"] = grok_data
            _grok_usage_cache["ts"] = now
        elif required_provider == "grok" or not required_provider:
            _grok_usage_cache["data"] = None
            _grok_usage_cache["ts"] = 0.0
    if required_provider == "grok" and not grok_fetched:
        raise RuntimeError("fresh Grok usage is unavailable")

    return {
        "anthropic": anthropic_data,
        "codex": codex_data,
        "grok": grok_data,
        "orchestra": _get_agents_cost(),
        "voice_cost_usd": round(_get_voice_cost_usd(), 4),
        # Единственное РЕАЛЬНОЕ число в этой панели (остальные — API-эквивалент).
        # Свободная строка, потому что тариф не выражается одним числом: "$200+$20/мес".
        # Не задано → фронт строку не рисует, чтобы не показывать устаревшую цену.
        "subscription_cost": os.getenv("SUBSCRIPTION_COST", ""),
    }


def _quota_headroom(anthropic: dict | None) -> dict | None:
    """Реальный потолок 5h с учётом остатка недельного окна (#162).

    Пятичасовой процент сам по себе вводит в заблуждение: в недельный лимит влезает
    ≈7 полных пятичасовых расходов (замерено двумя независимыми методами,
    docs/tasks/162/research.md), поэтому недельный кончается раньше, чем пятичасовой
    успевает упереться в себя. При 5h = 9 % и 7d = 92 % свободными выглядят 91 п.п.,
    а взять можно 58.

    None — когда посчитать нечем: курса нет или окон нет. Молчим, а не показываем
    последнее известное: курс за месяц дважды менялся вдвое.
    """
    from app.db import usage_exchange_rate

    five = (anthropic or {}).get("five_hour") or {}
    seven = (anthropic or {}).get("seven_day") or {}
    p5, p7 = five.get("utilization"), seven.get("utilization")
    if not isinstance(p5, (int, float)) or not isinstance(p7, (int, float)):
        return None
    try:
        measured = usage_exchange_rate()
    except Exception as error:
        # Производное число не имеет права уронить весь /api/usage: на нём висят
        # дашборд и гейты, а это лишь подсказка на одной шкале. Причину — в журнал,
        # с классом исключения, иначе «просто перестало показываться».
        logger.warning("quota headroom: история недоступна — %s: %s",
                       type(error).__name__, error)
        return None
    if not measured:
        return None
    weekly_room = max(0.0, 100.0 - p7) / measured["rate"]  # в п.п. пятичасового окна
    visible = max(0.0, 100.0 - p5)
    available = min(visible, weekly_room)
    return {
        "rate": round(measured["rate"], 4),
        "available_pct": round(available, 1),
        "locked_pct": round(visible - available, 1),
        "windows_left": round(weekly_room / 100.0, 2),
        "window_hours": measured["window_hours"],
        "sample_five_hour_pct": round(measured["five_hour_pct_sum"], 1),
    }


@router.get("/api/usage")
async def get_usage():
    if not is_owner_mode():
        return None
    data = await _get_usage_data()
    # Считаем только здесь: гейтам и limit_wake, которые ходят через
    # current_provider_usage, этот вывод не нужен, а он стоит запроса к истории.
    return {**data, "quota_headroom": _quota_headroom(data.get("anthropic"))}


@router.get("/api/usage/card")
async def get_usage_card():
    """Render the canonical `/limits` PNG for trusted local clients.

    The Telegram bridge and Kesha must not grow separate copies of the quota
    arithmetic or the HTML card: a visual that looks identical but was built
    from different numbers is worse than an explicit failure.
    """
    if not is_owner_mode():
        raise HTTPException(status_code=404, detail="not found")
    data = await _get_usage_data()
    usage = {**data, "quota_headroom": _quota_headroom(data.get("anthropic"))}
    from app.limits_card import render_limits_card

    path = await render_limits_card(usage)
    return FileResponse(path, media_type="image/png", filename="limits.png")


async def current_provider_usage(
    *,
    provider: str = "",
    force_refresh: bool = False,
) -> dict:
    """Return the normalized provider windows used by scheduling and wake guards."""
    usage = await _get_usage_data(
        force_refresh=force_refresh,
        required_provider=provider if force_refresh else "",
    )
    return _provider_usage_snapshot(
        usage.get("anthropic"),
        usage.get("codex"),
        usage.get("grok"),
    )


def _quota_observation_from_cache() -> dict:
    observed_at_by_provider = {
        "anthropic": _usage_cache.get("ts"),
        "anthropic_fable": _usage_cache.get("ts"),
        "codex": _codex_usage_cache.get("ts"),
        "codex_spark": _codex_usage_cache.get("ts"),
    }
    grok_ts = _grok_usage_cache.get("ts")
    if (
        _grok_usage_cache.get("data") is not None
        and isinstance(grok_ts, (int, float))
        and grok_ts > 0
    ):
        observed_at_by_provider["grok"] = grok_ts
    return {
        "providers": _provider_usage_snapshot(
            _usage_cache.get("data"),
            _codex_usage_cache.get("data"),
            _grok_usage_cache.get("data"),
        ),
        "observed_at_by_provider": observed_at_by_provider,
    }


async def current_quota_observation(
    *,
    required_provider: str,
    max_age: float = 300.0,
    timeout: float = 12.0,
    now: float | None = None,
) -> dict:
    """Return quota telemetry, refreshing only the requested provider family."""
    family = "codex" if required_provider in {"codex", "codex_spark"} else required_provider
    if family not in _quota_refresh_locks:
        return _quota_observation_from_cache()

    cache = _usage_cache if family == "anthropic" else _codex_usage_cache

    def fresh() -> bool:
        timestamp = cache.get("ts")
        checked_at = time.time() if now is None else float(now)
        return (
            isinstance(timestamp, (int, float))
            and not isinstance(timestamp, bool)
            and 0 <= checked_at - float(timestamp) < max_age
            and cache.get("data") is not None
        )

    if fresh():
        return _quota_observation_from_cache()

    lock = _quota_refresh_locks[family]
    async with lock:
        if fresh():
            return _quota_observation_from_cache()
        try:
            async with asyncio.timeout(timeout):
                await _get_usage_data(
                    force_refresh=True,
                    required_provider=required_provider,
                )
        except Exception as error:
            logger.warning(
                "quota observation refresh failed for %s: %s: %s",
                required_provider, type(error).__name__, err_text(error),
            )
    return _quota_observation_from_cache()


SNAPSHOT_INTERVAL = 300


async def _collect_usage_snapshot() -> None:
    import shutil

    from app.backend_codex import CODEX_BIN
    from app.db import usage_save_snapshot
    anthropic_data = None
    anthropic_error = ""
    token, refresh_token, _tier = _read_oauth_credentials()
    if token:
        try:
            anthropic_data = await _fetch_anthropic_usage(token)
        except PermissionError as e:
            # Причину пишем СРАЗУ: если обновление токена не поможет, дальше её взять
            # будет неоткуда и отказ станет безымянным.
            anthropic_error = f"{type(e).__name__}: {e}"
            if refresh_token:
                new_token = await _refresh_oauth_token(refresh_token)
                if new_token:
                    anthropic_data = await _fetch_anthropic_usage(new_token)
                    anthropic_error = ""
        except Exception as e:
            anthropic_data = None
            anthropic_error = f"{type(e).__name__}: {e}"
    if anthropic_data:
        _usage_cache["data"] = anthropic_data
        _usage_cache["ts"] = time.time()
        _save_usage_cache()

    codex_error = ""
    try:
        codex_data = await _fetch_codex_usage()
    except Exception as e:
        codex_data = None
        codex_error = f"{type(e).__name__}: {e}"
    if codex_data:
        _codex_usage_cache["data"] = codex_data
        _codex_usage_cache["ts"] = time.time()

    grok_data = None
    grok_error = ""
    grok_token = _read_grok_token()
    if grok_token:
        try:
            grok_data = await _fetch_grok_usage(grok_token)
        except Exception as e:
            grok_data = None
            grok_error = f"{type(e).__name__}: {e}"
    if grok_data:
        _grok_usage_cache["data"] = grok_data
        _grok_usage_cache["ts"] = time.time()

    # В историю идут ТОЛЬКО свежие ответы. Подстановка кеша (как было раньше)
    # штампует последнее известное значение новым временем — рисует ровную
    # линию там, где провайдер на самом деле молчал.
    providers = _provider_usage_snapshot(anthropic_data, codex_data, grok_data)
    # Спросили, но не ответил → явная метка. Без неё «молчит» неотличимо от
    # «не настроен»: в обоих случаях ключа провайдера просто нет.
    for provider_id, label, asked, answered, error in (
        ("anthropic", "Claude", bool(token), anthropic_data, anthropic_error),
        ("codex", "Codex", bool(shutil.which(CODEX_BIN)), codex_data, codex_error),
        ("grok", "Grok", bool(grok_token), grok_data, grok_error),
    ):
        if asked and not answered:
            providers[provider_id] = {
                "label": label,
                "windows": [],
                "status": "unavailable",
                "error": error or "no data",
            }
            logger.warning(
                "usage snapshot: %s asked and did not answer — %s",
                provider_id, error or "empty response",
            )
    if not providers:
        return

    fh = (anthropic_data or {}).get("five_hour") or {}
    sd = (anthropic_data or {}).get("seven_day") or {}
    cost = sum(s.cost_usd for s in manager.sessions.values())
    active = sum(1 for s in manager.sessions.values() if s.status.value == "running")
    # Ноль здесь означал бы «квота не израсходована» — ровно то, чего не знаем, когда
    # источник молчал. Пишем NULL: агрегаты SQLite такие строки пропускают, а график
    # рисует разрыв вместо падения в пол. Саму строку оставляем — в ней ещё живут
    # codex/grok и локальные cost/active, которые от молчания anthropic не пострадали.
    usage_save_snapshot(
        fh.get("utilization"), sd.get("utilization"),
        fh.get("resets_at", ""), sd.get("resets_at", ""),
        round(cost, 4), active, providers=providers,
    )
    # Строго ПОСЛЕ записи снимка и намеренно без `await`: оценка недельной квоты (#186)
    # уходит в фон и не может задержать сбор — на снимках висят дашборд, `quota_headroom`
    # и вход #187. Планирование не делает ни одного запроса и возвращается мгновенно.
    from app.quota_alert import schedule_evaluation

    schedule_evaluation(anthropic_data)


async def _usage_snapshot_loop():
    await asyncio.sleep(10)
    while True:
        try:
            await _collect_usage_snapshot()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"usage snapshot error: {e}")
        await asyncio.sleep(SNAPSHOT_INTERVAL)


# График рисует не весь запрошенный диапазон, а одно окно лимита (≤7 сут)
# в 252 px — это 40 минут на пиксель. Шаг 30 мин даёт 1.3 точки на пиксель,
# больше отдавать нечего рисовать: год в 5-минутной сетке — 4.32 МБ (замер 03.08).
HISTORY_FINE_STEP = 5
HISTORY_COARSE_STEP = 30
# Сразу после недельного сброса текущий период — это часы, и на прореженной
# сетке в нём остаётся 2-3 точки. Плюс решение «пора остановиться» принимают
# по текущему 5h-окну, где нужна минутная детализация. Поэтому свежий хвост
# всегда отдаём в полном разрешении.
HISTORY_FINE_HOURS = 48


@router.get("/api/usage/history")
async def usage_history(hours: int = 24, step_minutes: int = 0, until: str = ""):
    """История снимков: {step_minutes, rows, oldest_ts}.

    step_minutes — шаг сетки в прореженной части ответа. Фронт по нему решает,
    где разрыв данных: расстояние между соседними точками больше шага = дырка,
    её нельзя соединять линией.
    until — правая граница окна (исключительно). Фронт грузит период по клику ◀,
    передавая время самой старой уже загруженной точки. oldest_ts — время первого
    снимка вообще, по нему видно, осталось ли что грузить.
    """
    if step_minutes < 0:
        # шаг сетки идёт в `t += step`: отрицательный зациклит выборку намертво
        raise HTTPException(400, "step_minutes must be >= 0")
    from app.db import usage_get_history, usage_history_oldest_ts, usage_history_ts_before
    step = step_minutes or (HISTORY_FINE_STEP if hours <= HISTORY_FINE_HOURS
                            else HISTORY_COARSE_STEP)
    if not is_owner_mode():
        return {"step_minutes": step, "rows": [], "oldest_ts": ""}
    if until:
        # Окно навигации привязываем к данным: после простоя длиннее запрошенного
        # куска календарное окно пришло бы пустым, и ◀ упёрлась бы в него навсегда.
        previous = usage_history_ts_before(until)
        if previous:
            until = (datetime.fromisoformat(previous) + timedelta(microseconds=1)).isoformat()
    rows = usage_get_history(hours, step, until)
    # Хвост в полном разрешении нужен только живому виду: в куске из прошлого
    # «последние 48 часов» — это такое же прошлое, детализация там не нужна.
    if not until and not step_minutes and hours > HISTORY_FINE_HOURS:
        fine = usage_get_history(HISTORY_FINE_HOURS, HISTORY_FINE_STEP)
        cut = fine[0]["ts"] if fine else None
        rows = [row for row in rows if cut is None or row["ts"] < cut] + fine
    return {"step_minutes": step, "rows": rows, "oldest_ts": usage_history_oldest_ts()}


@router.get("/api/usage/analytics")
async def usage_analytics_endpoint(days: int = 7):
    """Return one coherent capacity, cost, efficiency and reliability snapshot."""
    from app.usage_analytics import build_usage_analytics

    current = await get_usage()
    capacity = current if isinstance(current, dict) and any(
        key in current for key in ("anthropic", "codex", "orchestra")
    ) else {}
    payload = build_usage_analytics(days=days, capacity=capacity)
    try:
        payload["quota_controller"] = get_quota_controller().status()
    except Exception as error:
        # Cost history remains useful when the optional controller telemetry is
        # unavailable; the frontend renders this as an explicit error state.
        payload["quota_controller"] = {
            "data_available": False,
            "reason": "quota_controller_error",
            "error": type(error).__name__,
            "enforcement_active": False,
        }
    from app.limit_wake import wake_status

    payload["wake_after_reset"] = wake_status()
    return payload


@router.post("/api/usage/wake-after-reset")
async def wake_after_reset_endpoint():
    from app.limit_wake import schedule_wake_after_reset

    return await schedule_wake_after_reset()


@router.get("/api/usage/readiness")
async def usage_readiness(model: str):
    """Return the same weekly worker admission decision used at execution time."""
    from app.quota_gate import get_worker_admission, worker_readiness_envelope

    decision = await get_worker_admission(
        model,
        observation_loader=current_quota_observation,
    )
    return worker_readiness_envelope(decision)


@router.get("/api/usage/quota-controller")
async def quota_controller_status():
    try:
        result = get_quota_controller().status()
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            return result
    except Exception as error:
        from app.quota_controller import empty_status, record_shadow_error

        record_shadow_error()
        result = empty_status()
        result["status_error"] = f"{type(error).__name__}: {err_text(error)}"
        return result
    from app.quota_controller import empty_status

    return empty_status()


def _operator_actor() -> str:
    """Use the authenticated server identity; never trust a request body actor."""
    return os.environ.get("DASHBOARD_USER", "operator") or "operator"


@router.get("/api/usage/quota-controller/policy")
async def quota_controller_policy(request: Request):
    require_operator_session(request)
    from app.db import quota_policy_audit, quota_policy_snapshot

    result = quota_policy_snapshot()
    result["audit"] = quota_policy_audit()
    return result


@router.put("/api/usage/quota-controller/policy")
async def replace_quota_controller_policy(request: Request, payload: dict):
    require_operator_session(request)
    from app.db import QuotaPolicyRevisionMismatch, replace_quota_policy

    values = payload.get("thresholds", payload.get("lanes", payload))
    if not isinstance(values, dict):
        raise HTTPException(status_code=422, detail="thresholds must be an object")
    aliases = {
        "sol": "sol", "sol_threshold": "sol",
        "luna": "luna", "luna_threshold": "luna",
        "spark": "spark", "spark_threshold": "spark",
    }
    parsed = {}
    for key, value in values.items():
        lane = aliases.get(str(key))
        if lane is not None:
            parsed[lane] = value
    if not parsed:
        raise HTTPException(status_code=422, detail="at least one quota threshold is required")
    expected = payload.get("expected_revision", payload.get("revision"))
    if expected is not None and (
        isinstance(expected, bool) or not isinstance(expected, int)
    ):
        raise HTTPException(status_code=422, detail="expected_revision must be an integer")
    try:
        result = replace_quota_policy(
            parsed,
            actor=_operator_actor(),
            reason=str(payload.get("reason") or "").strip(),
            expected_revision=expected,
        )
    except QuotaPolicyRevisionMismatch as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result["audit"] = __import__("app.db", fromlist=["quota_policy_audit"]).quota_policy_audit()
    return result


@router.post("/api/usage/quota-controller/policy/rollback")
async def rollback_quota_controller_policy(request: Request, payload: dict | None = None):
    require_operator_session(request)
    from app.db import quota_policy_audit, rollback_quota_policy

    payload = payload or {}
    result = rollback_quota_policy(
        actor=_operator_actor(),
        reason=str(payload.get("reason") or "operator rollback to defaults"),
    )
    result["audit"] = quota_policy_audit()
    return result


@router.post("/api/usage/quota-controller/reserve")
async def create_quota_reserve_intent(request: Request, payload: dict):
    require_operator_session(request)
    result = get_quota_controller().create_reserve_intent(payload)
    if inspect.isawaitable(result):
        result = await result
    return result


@router.delete("/api/usage/quota-controller/reserve/{intent_id}")
async def cancel_quota_reserve_intent(request: Request, intent_id: str):
    require_operator_session(request)
    result = get_quota_controller().cancel_reserve_intent(intent_id)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        raise HTTPException(status_code=404, detail="reserve intent not found")
    return result


@router.get("/api/usage/routing-policy")
async def routing_policy_status():
    return await get_runtime_router().status()


@router.put("/api/usage/routing-policy")
async def replace_routing_policy(request: Request, payload: dict):
    require_operator_session(request)
    try:
        policy = await get_runtime_router().replace_policy(payload)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except PolicyRevisionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "contract_version": ROUTING_CONTRACT_VERSION,
        "policy": policy.model_dump(mode="json", exclude_none=True),
    }


@router.post("/api/usage/routing-policy/explain")
async def explain_routing_policy(payload: dict):
    try:
        request, observation, baseline, latches, terminal, now = (
            explain_inputs_from_dict(payload)
        )
        decision = await get_runtime_router().explain(
            request,
            observation,
            claude_baseline=baseline,
            latched_window_ids=latches,
            terminal_limited_buckets=terminal,
            now=now,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "contract_version": ROUTING_CONTRACT_VERSION,
        "decision": decision.to_dict(),
    }


# ── Misc ──

@router.post("/api/sessions/{name}/hibernate")
async def hibernate_session_endpoint(name: str, req: dict):
    scope = str(req.get("scope", ""))
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not found.loaded:
        return {"ok": True, "state": "already_process_free"}
    try:
        result = await found.hibernate_now()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error(f"hibernate failed for {name}: {error}")
        return JSONResponse({"error": error}, status_code=500)
    if not result["ok"]:
        return JSONResponse(result, status_code=409)
    return result


_BUG_STATE_ROOT_CACHE: Path | None = None
_BUG_VALIDATED_DIRS: dict[str, tuple[int, int]] = {}
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _nearest_existing(path: Path) -> Path:
    current = path
    while not os.path.lexists(current):
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _assert_bug_path_outside_git(path: Path) -> None:
    probe_path = _nearest_existing(path.absolute()).resolve(strict=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "LC_ALL": "C",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    })
    result = subprocess.run(
        ["git", "-C", str(probe_path), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        raise RuntimeError(
            f"bug inbox path resolves inside Git metadata: {result.stdout.strip()}"
        )
    if result.returncode != 128 or "not a git repository" not in result.stderr:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"bug inbox Git isolation probe failed: {detail}")


def _bug_state_root() -> Path:
    global _BUG_STATE_ROOT_CACHE
    if _BUG_STATE_ROOT_CACHE is not None:
        return _BUG_STATE_ROOT_CACHE

    systemd_state = os.environ.get("STATE_DIRECTORY", "").strip()
    if systemd_state:
        parts = [part for part in systemd_state.split(":") if part]
        if len(parts) != 1:
            raise RuntimeError("STATE_DIRECTORY must contain exactly one path")
        candidate = Path(parts[0])
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
        candidate = (
            Path(xdg_state) / "orchestra"
            if xdg_state
            else Path.home() / ".local" / "state" / "orchestra"
        )
    if not candidate.is_absolute():
        raise RuntimeError(f"bug inbox state path is not absolute: {candidate}")
    _assert_bug_path_outside_git(candidate)
    _BUG_STATE_ROOT_CACHE = candidate
    return candidate


def _sync_fd(fd: int) -> None:
    os.fsync(fd)


def _open_private_path(path: Path) -> int:
    if not path.is_absolute():
        raise RuntimeError(f"private state path is not absolute: {path}")
    fd = os.open(os.sep, _DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            try:
                child_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                _sync_fd(fd)
                child_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_private_child(parent_fd: int, name: str) -> int:
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        _sync_fd(parent_fd)
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise RuntimeError(f"bug inbox component is not a directory: {name}")
        os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _verify_open_directory(fd: int, path: Path) -> None:
    opened = os.fstat(fd)
    current = os.lstat(path)
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise RuntimeError(f"bug inbox directory identity changed: {path}")
    identity = (opened.st_dev, opened.st_ino)
    cache_key = str(path)
    if _BUG_VALIDATED_DIRS.get(cache_key) != identity:
        _assert_bug_path_outside_git(path)
        _BUG_VALIDATED_DIRS[cache_key] = identity


def _open_regular_at(dir_fd: int, name: str) -> tuple[int, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | _FILE_NOFOLLOW, dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"bug inbox entry is not a regular file: {name}")
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
        return fd, info
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _open_bug_store():
    root = _bug_state_root()
    root_fd = _open_private_path(root)
    inbox_fd = tmp_fd = records_fd = None
    try:
        _verify_open_directory(root_fd, root)
        inbox_fd = _open_private_child(root_fd, "bug-inbox")
        inbox = root / "bug-inbox"
        _verify_open_directory(inbox_fd, inbox)
        tmp_fd = _open_private_child(inbox_fd, "tmp")
        _verify_open_directory(tmp_fd, inbox / "tmp")
        records_fd = _open_private_child(inbox_fd, "records")
        _verify_open_directory(records_fd, inbox / "records")
        try:
            legacy_fd, _legacy_info = _open_regular_at(inbox_fd, "legacy.md")
        except FileNotFoundError:
            pass
        else:
            os.close(legacy_fd)
        yield inbox, inbox_fd, tmp_fd, records_fd
    finally:
        for fd in (records_fd, tmp_fd, inbox_fd, root_fd):
            if fd is not None:
                os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("bug record write made no progress")
        remaining = remaining[written:]


def _publish_bug_record(entry: str) -> tuple[str, str]:
    payload = entry.encode("utf-8")
    token = uuid.uuid4().hex
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    temp_name = f".{token}.tmp"
    record_name = f"{stamp}-{token}.md"
    published = False

    with _open_bug_store() as (inbox, _inbox_fd, tmp_fd, records_fd):
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
            0o600,
            dir_fd=tmp_fd,
        )
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, payload)
            _sync_fd(fd)
        finally:
            os.close(fd)
        try:
            os.replace(
                temp_name,
                record_name,
                src_dir_fd=tmp_fd,
                dst_dir_fd=records_fd,
            )
            published = True
            _sync_fd(records_fd)
            _sync_fd(tmp_fd)
        finally:
            if not published:
                try:
                    os.unlink(temp_name, dir_fd=tmp_fd)
                    _sync_fd(tmp_fd)
                except FileNotFoundError:
                    pass
        return str(inbox / "records" / record_name), record_name


def _regular_metadata(dir_fd: int, name: str) -> dict:
    fd, info = _open_regular_at(dir_fd, name)
    try:
        return {
            "name": name,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
        }
    finally:
        os.close(fd)


def _bug_snapshot() -> dict:
    with _open_bug_store() as (inbox, inbox_fd, _tmp_fd, records_fd):
        legacy = None
        try:
            legacy = _regular_metadata(inbox_fd, "legacy.md")
        except FileNotFoundError:
            pass
        records = sorted(
            (
                _regular_metadata(records_fd, name)
                for name in os.listdir(records_fd)
                if name.endswith(".md")
            ),
            key=lambda item: item["name"],
        )
        return {
            "inbox": str(inbox),
            "legacy": legacy,
            "records": records,
        }


def _stream_snapshot_file(dir_fd: int, metadata: dict) -> Iterator[bytes]:
    fd, current = _open_regular_at(dir_fd, metadata["name"])
    try:
        if (
            (current.st_dev, current.st_ino, current.st_size)
            != (metadata["dev"], metadata["ino"], metadata["size"])
        ):
            raise RuntimeError(f"bug inbox snapshot changed: {metadata['name']}")
        remaining = metadata["size"]
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise OSError(f"unexpected EOF reading bug record: {metadata['name']}")
            remaining -= len(chunk)
            yield chunk
    finally:
        os.close(fd)


def _stream_bug_snapshot(snapshot: dict) -> Iterator[bytes]:
    with _open_bug_store() as (_inbox, inbox_fd, _tmp_fd, records_fd):
        if snapshot["legacy"]:
            yield from _stream_snapshot_file(inbox_fd, snapshot["legacy"])
        for metadata in snapshot["records"]:
            yield from _stream_snapshot_file(records_fd, metadata)


@router.post("/api/report_bug")
async def report_bug_endpoint(req: Request):
    data = await req.json()
    title = data.get("title", "Untitled")
    description = data.get("description", "")
    reporter = data.get("reporter", "unknown")
    scope = data.get("scope", "")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{ts}] {title}\n- **Reporter:** {reporter}\n- **Scope:** {scope}\n{description}\n"
    try:
        record_path, record_id = await asyncio.to_thread(_publish_bug_record, entry)
    except Exception as exc:
        error = err_text(exc)
        logger.exception(f"report_bug failed: {error}")
        return JSONResponse({"error": error}, status_code=500)
    # Запись в стор уже состоялась и не должна зависеть от судьбы уведомления (#56):
    # репорт зарегистрирован, даже если сообщать о нём некому или не вышло.
    try:
        from app.notify import notify_bug_report

        notified = await notify_bug_report(
            manager, scope=scope, reporter=reporter, title=title, record_id=record_id,
        )
    except Exception as notify_error:
        notified = f"уведомление упало: {type(notify_error).__name__}: {notify_error}"
        logger.warning("bug report %s notification failed: %s", record_id, notified)
    return {
        "result": f"Bug reported: {title}. Read: /api/report_bug",
        "record_id": record_id,
        "path": record_path,
        "view_url": "/api/report_bug",
        "notified": notified,
    }


@router.get("/api/report_bug")
async def read_bug_reports():
    try:
        snapshot = await asyncio.to_thread(_bug_snapshot)
    except Exception as exc:
        error = err_text(exc)
        logger.exception(f"report_bug read failed: {error}")
        return JSONResponse({"error": error}, status_code=500)
    return StreamingResponse(
        _stream_bug_snapshot(snapshot),
        media_type="text/markdown",
        headers={"Content-Disposition": 'inline; filename="BUGS.md"'},
    )


@router.get("/api/orchestrators")
async def list_orchestrators():
    from app.prompting import is_orchestrator_role
    from app.db import get_last_turn_map
    active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
    active_ids = {s["id"] for s in active}
    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
    result = active + db_orchs
    running_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "running"}
    waiting_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "waiting"}
    turn_map = get_last_turn_map()
    for o in result:
        # Системный промпт — 92.8% веса этого ответа по проводу (19.8 КБ из 21.3 КБ на
        # пяти записях, замер в docs/tasks/71/research.md), и в списке его не читает никто:
        # ни дашборд, ни MCP. За полным промптом ходят в GET /api/sessions/{name}/prompt.
        # Срезается ЗДЕСЬ, а не в to_dict(): его же отдаёт /api/sessions/{name}, где промпт
        # нужен. И в обоих путях сразу — активные сессии и строки БД лежат в одном списке,
        # иначе поле осталось бы у половины записей.
        o.pop("system_prompt", None)
        o["any_running"] = o.get("scope", "") in running_scopes
        o["any_waiting"] = o.get("scope", "") in waiting_scopes
        if not o.get("last_turn_ts"):
            o["last_turn_ts"] = turn_map.get(o["id"])
        o.update(cache_policy_for_runtime(runtime_for_record(o)))
    return result


@router.delete("/api/orchestrators/{name}")
async def delete_orchestrator(name: str, scope: str, delete_tg_topics: bool = False):
    try:
        result = await manager.remove_scope(scope, delete_tg_topics=delete_tg_topics)
    except Exception as e:
        logger.error(f"orchestrator remove failed for {name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"ok": True, **result}


@router.post("/api/orchestrators/{name}/change-scope")
async def change_orchestrator_scope_endpoint(name: str, req: ChangeScopeRequest):
    new_scope = req.new_scope.rstrip("/")
    new_cwd = (req.new_cwd or req.new_scope).rstrip("/")
    if not _is_safe_path(new_scope) or not _is_safe_path(new_cwd):
        return JSONResponse({"error": "path not in allowed roots"}, status_code=403)
    result = await manager.change_orchestrator_scope(
        name, req.old_scope.rstrip("/"), new_scope, new_cwd)
    if result.get("error"):
        return JSONResponse(result, status_code=409)
    return result


@router.get("/api/test-lock")
async def test_lock_status_endpoint(scope: str):
    from app.db import get_test_lock
    row = get_test_lock(scope)
    if not row:
        return {"held": False, "holder": None, "reason": None, "acquired_at": None}
    return {"held": True, "holder": row["holder"],
            "reason": row["reason"], "acquired_at": row["acquired_at"]}


@router.post("/api/test-lock/acquire")
async def acquire_lock_endpoint(req: TestLockRequest):
    from app.db import acquire_test_lock
    ok, holder = acquire_test_lock(
        req.scope, req.holder, req.reason, holder_session_id=req.holder_session_id,
    )
    return {"acquired": ok, "holder": holder}


@router.post("/api/test-lock/release")
async def release_lock_endpoint(req: TestLockRequest):
    from app.db import release_test_lock
    ok = release_test_lock(
        req.scope, req.holder, holder_session_id=req.holder_session_id,
    )
    return {"released": ok}


_restart_tasks: set[asyncio.Task] = set()

# 15 минут: замер #220 — дренаж сходится за это время в 80% случаев (p50 1.2 мин).
# Дедлайн БЕЗУСЛОВНЫЙ: гарантии сходимости нет вовсе, потому что ходы порождаются
# изнутри контура (send_message между агентами, автоотчёт родителю).
_DRAIN_DEADLINE_S = 900


def _drain_sessions() -> list:
    """Живые сессии одним местом — тест подменяет именно её."""
    return list(manager.sessions.values())


def _record_restart_outcome(outcome: dict) -> None:
    """Записать итог дренажа ДО сигнала: после него отчитываться уже некому.

    Процесс умирает внутри workflow, поэтому ни HTTP-ответ, ни живой TG-канал итог
    не донесут — переживает рестарт только запись на диск. Потребитель — существующий
    журнал сессии в дашборде; нового эндпоинта и таблицы не заводим (#220 T3).
    """
    from app.db import add_log

    ts = datetime.now(timezone.utc)
    summary = (
        f"[system] рестарт: дренаж {outcome['waited_s']:.1f} с, "
        f"разорвано ходов: {outcome['cut_turns']}"
    )
    logger.warning(summary)
    for session_id in outcome["cut_ids"]:
        add_log(session_id, ts, "system",
                f"{summary}. Твой ход разорван — автоматического повтора нет.")


async def restart_preflight() -> dict:
    """Decide whether a restart may proceed, BEFORE systemd is invoked (#230 T6).

    A gate inside the lifespan is too late: by then `systemctl restart` is already committed
    and nobody can be told "no". Order matters — close admission FIRST, so nothing new starts
    a side effect while we wait, THEN drain what was already accepted.
    """
    from app import main as app_main

    # BOTH gates, both before the first await. Closing only the HTTP half left a window where
    # a new agent turn could start after the drain had taken its snapshot — so the very turn
    # the drain protects was the one the signal cut (#237 T3).
    manager.begin_drain()
    app_main.close_mutating_admission()
    drained = await app_main.drain_mutating_requests()
    if drained:
        return {"ok": True}
    left = app_main.inflight_mutating_count()
    app_main.open_mutating_admission()  # the restart is off: do not starve the agents
    manager.end_drain()
    return {
        "ok": False,
        "reason": (
            f"{left} mutating tool call(s) still in flight after "
            f"{app_main.MUTATING_DRAIN_BUDGET_S:.0f}s; restarting now would leave their "
            "outcome unknown to the agent"
        ),
    }


_RESPONSE_FLUSH_PAUSE_S = 0.5  # so the caller sees `scheduled` before we start
_WATCHDOG_MARGIN_S = 120.0  # fleet quiesce + store + the outcome write, generously


def _watchdog_budget_s() -> float:
    """How long the safety net waits before deciding the restart is not coming.

    Summed from the waits themselves rather than picked, because picking is how this broke
    once already: the constant was sized against the 90.2s slowest mutating call, then T3 put
    a 900s wait for live turns underneath the same gates and nobody re-added the numbers.

    Firing early is not a harmless false alarm — it reopens the turn gate while the drain loop
    is still legitimately waiting, new turns start, `_blocking_runtimes()` stops emptying, and
    the restart becomes UNREACHABLE: the safety net feeding exactly what the loop waits on.

    `MUTATING_DRAIN_BUDGET_S` is read at call time on purpose: `app.main` imports this module,
    so a module-level import would be circular, and copying the number would give one budget
    two owners — the same mistake in a new place.
    """
    from app import main as app_main

    return (_RESPONSE_FLUSH_PAUSE_S          # let the HTTP response leave first
            + app_main.MUTATING_DRAIN_BUDGET_S  # the restart path drains HTTP a second time
            + _DRAIN_DEADLINE_S              # then waits for turns it must not cut
            + _WATCHDOG_MARGIN_S)            # fleet prepare + the outcome write

#: Which restart attempt is current. A watchdog belongs to the attempt that armed it: firing
#: into a LATER attempt would strip descriptors out of systemd's store and reopen both gates
#: mid-transaction, from a coroutine that has no idea any of it is happening.
_restart_attempt = 0


async def _reopen_admission_if_still_alive(attempt: int = 0) -> None:
    """Undo the preflight's admission gate if the restart never arrived (#230 T6).

    A real restart kills this process, so in the happy path this coroutine simply dies with it
    and the sleep is never observed. Reaching the end means the signal did not do its job.

    Two things keep it from sawing the branch it sits on: it outlasts everything the attempt
    may legitimately wait for, and it stands down if its own attempt is no longer the current
    one. Without the first, it reopens the turn gate while the drain loop is still waiting —
    new turns start, `_blocking_runtimes()` stops emptying, and the restart becomes
    unreachable because its own safety net keeps feeding what it waits on.
    """
    budget = _watchdog_budget_s()
    await asyncio.sleep(budget)
    if attempt != _restart_attempt:
        logger.info("restart watchdog for attempt %d stood down: attempt %d is current",
                    attempt, _restart_attempt)
        return
    # Reopening the gates is not enough. A fleet that was already prepared is quiesced and
    # stored: those agents would stay deaf and their descriptors would sit in systemd's store
    # until it fills up. Give them their readers back too (found by the pre-mortem).
    await _abort_restart(
        f"no restart within {budget}s of a successful preflight")
    logger.error(
        "restart did not happen within %ss after a successful preflight — handover rolled "
        "back and both admissions reopened so agents are not starved", budget,
    )


async def _restart_service_after_response() -> dict:
    """Дренаж → запись итога → SIGINT; systemd Restart=always поднимает нас обратно.

    Порядок обязателен: дренаж идёт ДО сигнала, а `shutdown_merge_operations()`,
    `bg_manager.shutdown()` и `manager.shutdown_all()` — уже ПОСЛЕ него, внутри
    lifespan (`app/main.py:114,126,127`).
    """
    try:
        return await _do_restart_service()
    except BaseException:
        from app import main as app_main
        # The fleet may already be quiesced and stored: leaving it that way would abandon
        # running CLIs that nobody owns any more, each of them deaf (#237 T3).
        await _abort_restart("the restart path failed")
        app_main.open_mutating_admission()
        logger.exception("restart path failed; handover rolled back, admission reopened")
        raise


async def _abort_restart(reason: str) -> None:
    """Give every prepared agent back its reader, and reopen both gates (#237 T3)."""
    from app import main as app_main

    try:
        await manager.rollback_restart_handover()
    except Exception as error:
        logger.error("could not roll back the prepared handover: %s: %s",
                     type(error).__name__, error)
    manager.end_drain()
    app_main.open_mutating_admission()
    logger.warning("restart aborted (%s): no signal sent", reason)


def _blocking_runtimes() -> list:
    """Live turns that CANNOT be handed over, so the restart must wait for them (#237 T3).

    Only Codex survives a restart today; Claude and Grok are separate trains. Their live turn
    is the one thing a restart may never cut, so it blocks instead.
    """
    return [s for s in _drain_sessions()
            if s.is_busy and getattr(s, "backend_type", "") != "codex"]


async def _do_restart_service() -> dict:
    from app import main as app_main

    await asyncio.sleep(_RESPONSE_FLUSH_PAUSE_S)
    # Already-admitted mutating calls first: one of them may have committed its effect and
    # not yet returned it, and signalling there makes its outcome unknown to the agent.
    if not await app_main.drain_mutating_requests():
        left = app_main.inflight_mutating_count()
        await _abort_restart(f"{left} mutating call(s) still in flight")
        return {"ok": False, "reason": f"{left} mutating call(s) still in flight",
                "cut_turns": 0, "cut_names": [], "cut_ids": []}

    started = time.monotonic()
    while time.monotonic() - started < _DRAIN_DEADLINE_S:
        if not _blocking_runtimes():
            break
        await asyncio.sleep(1)
    blocked = _blocking_runtimes()
    if blocked:
        await _abort_restart(f"{len(blocked)} non-adoptable turn(s) still running")
        return {
            "ok": False,
            "reason": "a live turn on a runtime that cannot be handed over",
            "waited_s": time.monotonic() - started,
            "cut_turns": 0,
            "cut_names": [s.name for s in blocked],
            "cut_ids": [s.id for s in blocked],
        }

    live_codex = [s for s in _drain_sessions()
                  if s.is_busy and getattr(s, "backend_type", "") == "codex"]
    prepared = await manager.prepare_restart_handover(live_codex)
    if not prepared["ok"]:
        await _abort_restart(prepared["reason"])
        return {"ok": False, "reason": prepared["reason"], "waited_s": time.monotonic() - started,
                "cut_turns": 0, "cut_names": [], "cut_ids": []}

    # Last look before the point of no return: preparing the fleet takes real time, and both
    # of these can have changed underneath it.
    late = _blocking_runtimes()
    if late or app_main.inflight_mutating_count():
        await _abort_restart("work started while the fleet was being prepared")
        return {
            "ok": False,
            "reason": "work started while the fleet was being prepared",
            "waited_s": time.monotonic() - started,
            "cut_turns": 0,
            "cut_names": [s.name for s in late],
            "cut_ids": [s.id for s in late],
        }

    outcome = {
        "ok": True,
        "handed_over": prepared["handed_over"],
        "waited_s": time.monotonic() - started,
        "cut_turns": 0,
        "cut_names": [],
        "cut_ids": [],
    }
    try:
        _record_restart_outcome(outcome)
    except Exception as error:
        # Побочный учёт не имеет права отменить основное действие: дедлайн назван
        # безусловным, и сбой записи не делает рестарт менее обязательным (класс #215).
        logger.warning("could not record restart outcome: %s: %s",
                       type(error).__name__, error)
    from app.live_broker import broker
    broker.close_subscribers()
    os.kill(os.getpid(), signal.SIGINT)
    return outcome


def _disarm_watchdog_if_aborted(done: asyncio.Task, watchdog: asyncio.Task) -> None:
    """Stand the watchdog down when the attempt ended WITHOUT signalling (#237).

    Deliberately not "whenever the attempt finishes": the one case the watchdog exists for is
    a signal that failed to kill us, and there the attempt has completed normally. An abort,
    by contrast, has already reopened both gates itself, so a live watchdog there can only
    fire into whatever comes next.
    """
    if done.cancelled():
        watchdog.cancel()
        return
    if done.exception() is not None:
        watchdog.cancel()  # the failure path reopened the gates already
        return
    outcome = done.result()
    if isinstance(outcome, dict) and outcome.get("ok") is False:
        watchdog.cancel()


@router.post("/api/restart")
async def restart_server():
    try:
        verdict = await restart_preflight()
        if not verdict["ok"]:
            raise HTTPException(409, verdict["reason"])
        # The preflight left BOTH gates closed so nothing new starts. If the restart does not
        # actually happen, they must not stay shut: a stuck-closed gate answers every mutating
        # tool call with "retry later" and refuses every agent turn, forever.
        global _restart_attempt
        _restart_attempt += 1
        attempt = _restart_attempt
        watchdog = asyncio.create_task(_reopen_admission_if_still_alive(attempt))
        _restart_tasks.add(watchdog)
        watchdog.add_done_callback(_restart_tasks.discard)
        task = asyncio.create_task(_restart_service_after_response())
        _restart_tasks.add(task)
        task.add_done_callback(_restart_tasks.discard)
        task.add_done_callback(lambda done: _disarm_watchdog_if_aborted(done, watchdog))
    except BaseException:
        # Nothing was scheduled, so nobody downstream will ever reopen the gates for us.
        from app import main as app_main
        app_main.open_mutating_admission()
        manager.end_drain()
        raise
    return {"ok": True, "scheduled": True}


# ── GitHub Webhook (CI failure routing) ──

_FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}


def _parse_repo_to_scope() -> dict[str, str]:
    raw = os.environ.get("GITHUB_REPO_SCOPE_MAP", "")
    if not raw:
        return {}
    result = {}
    for item in raw.split(","):
        item = item.strip()
        if "=" in item:
            repo, scope = item.split("=", 1)
            result[repo.strip()] = scope.strip()
    return result


REPO_TO_SCOPE = _parse_repo_to_scope()


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    # compare_digest prevents timing attacks on the signature check
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _fetch_failed_log(owner: str, repo: str, run_id: int, token: str) -> str:
    import httpx
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            headers=headers,
        )
        if resp.status_code != 200:
            return f"(failed to fetch jobs: HTTP {resp.status_code})"
        jobs = resp.json().get("jobs", [])
        failed_job = next((j for j in jobs if j.get("conclusion") in _FAILURE_CONCLUSIONS), None)
        if not failed_job:
            return "(no failed job found)"
        job_id = failed_job["id"]
        log_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            headers=headers,
            follow_redirects=True,
        )
        if log_resp.status_code != 200:
            return f"(failed to fetch log: HTTP {log_resp.status_code})"
        lines = log_resp.text.splitlines()
        return "\n".join(lines[-50:])


@router.post("/api/webhook/github")
async def github_webhook(request: Request):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return JSONResponse({"error": "webhook not configured"}, status_code=500)

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature or not _verify_github_signature(body, signature, secret):
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    event = request.headers.get("X-GitHub-Event", "")
    if event != "workflow_run":
        return {"ok": True, "skipped": event}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    action = payload.get("action")
    workflow_run = payload.get("workflow_run") or {}
    conclusion = workflow_run.get("conclusion")

    if action != "completed" or conclusion not in _FAILURE_CONCLUSIONS:
        return {"ok": True, "skipped": f"{action}/{conclusion}"}

    repository = payload.get("repository") or {}
    repo_full = repository.get("full_name", "")
    scope = REPO_TO_SCOPE.get(repo_full)
    if not scope:
        logger.warning(f"No scope mapping for repo: {repo_full}")
        return {"ok": True, "skipped": f"unmapped repo {repo_full}"}

    workflow_name = workflow_run.get("name", "unknown")
    run_id = workflow_run.get("id")
    run_url = workflow_run.get("html_url", "")
    head_commit = workflow_run.get("head_commit") or {}
    commit_sha = str(head_commit.get("id", ""))[:7]
    commit_msg = str(head_commit.get("message", "")).split("\n")[0]

    token = os.getenv("GITHUB_TOKEN", "")
    error_log = ""
    if token and run_id:
        owner, repo = repo_full.split("/", 1)
        try:
            error_log = await _fetch_failed_log(owner, repo, run_id, token)
        except Exception as e:
            error_log = f"(log fetch error: {e})"

    message = (
        f"🔴 CI FAIL: {repo_full}\n"
        f"Workflow: {workflow_name}, Run #{run_id}\n"
        f"Commit: {commit_sha} \"{commit_msg}\"\n"
    )
    if error_log:
        message += f"Error:\n{error_log}\n"
    message += f"URL: {run_url}"

    orch_name = manager._find_orchestrator_name(scope)
    if not orch_name:
        logger.warning(f"No orchestrator for scope: {scope}")
        return JSONResponse({"error": f"no orchestrator for scope {scope}"}, status_code=404)

    session = await manager.ensure_loaded(orch_name, scope)
    if not session:
        return JSONResponse({"error": f"orchestrator {orch_name} not loadable"}, status_code=404)

    try:
        await manager.send(session.id, message)
        logger.info(f"CI failure routed to {orch_name}: {repo_full} run #{run_id}")
        return {"ok": True, "routed_to": orch_name}
    except Exception as e:
        logger.error(f"Failed to send CI failure to {orch_name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
