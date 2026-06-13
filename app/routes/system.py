"""System routes: dashboard/auth pages, files, projects, profiles, usage,
orchestrators, test-lock, git-status, restart, GitHub webhook."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import is_auth_enabled
from app.db import get_all_sessions, list_profiles, upsert_profile, delete_profile
from app.deps import manager, templates
from app.models import MODELS, CONTEXT_LIMITS, TOKEN_PRICES, is_proxy_connected
from app.pipeline import list_pipelines

logger = logging.getLogger("orchestra.system")

router = APIRouter()


class ProfileRequest(BaseModel):
    """Тело запроса для создания/обновления профиля Claude."""
    name: str
    config_dir: str = ""


class TestLockRequest(BaseModel):
    scope: str
    holder: str
    reason: str = ""


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
        "client_name": os.getenv("CLIENT_NAME", "Client"),
    })


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


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


@router.get("/api/jobs")
async def list_api_jobs(scope: str | None = None):
    from app.db import get_jobs
    return get_jobs(scope=scope)


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
                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
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
async def get_file_raw(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from starlette.responses import FileResponse
    target = Path(path)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


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


@router.get("/api/open-file")
async def open_file(path: str):
    if not os.environ.get("ALLOW_OPEN_FOLDER"):
        return JSONResponse({"error": "disabled on this server"}, status_code=403)
    # same safety gate as get_file_content/list_files — was the one unguarded sibling
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    import subprocess
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.Popen(["xdg-open", str(p)], env=env)
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
    if is_auth_enabled():
        raise HTTPException(403, "Not available")
    return list_profiles()


@router.post("/api/profiles")
async def create_profile(req: ProfileRequest):
    """Создать или обновить профиль."""
    if is_auth_enabled():
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
    if is_auth_enabled():
        raise HTTPException(403, "Not available")
    try:
        delete_profile(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return list_profiles()


@router.get("/api/models")
async def list_models():
    models = []
    for mid, name in MODELS.items():
        entry = {"id": mid, "name": name}
        ctx = CONTEXT_LIMITS.get(mid)
        if ctx:
            entry["context_length"] = ctx
        prices = TOKEN_PRICES.get(mid)
        if prices:
            entry["price_input"] = prices["input"]
            entry["price_output"] = prices["output"]
        models.append(entry)
    return {"models": models, "proxy_connected": is_proxy_connected()}


@router.post("/api/models/refresh")
async def refresh_models_endpoint():
    from app.models import refresh_models
    await refresh_models()
    return {"ok": True, "proxy_connected": is_proxy_connected(), "model_count": len(MODELS)}


@router.get("/api/stats")
async def stats(scope: Optional[str] = None):
    return manager.stats(scope)


# ── Usage (Anthropic OAuth) ──

_USAGE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_cache.json"
_usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
_USAGE_CACHE_TTL = 300
_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


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


def _get_agents_cost() -> dict:
    """Get per-agent cost breakdown from DB."""
    from app.db import _conn
    with _conn() as c:
        rows = c.execute(
            "SELECT name, model, cost_usd, cost_usd_cached FROM sessions ORDER BY cost_usd DESC"
        ).fetchall()
        total = sum(r["cost_usd"] for r in rows)
        total_cached = sum(r["cost_usd_cached"] or 0 for r in rows)
        agents = [
            {"name": r["name"], "cost_usd": round(r["cost_usd"], 4),
             "cost_usd_cached": round(r["cost_usd_cached"] or 0, 4), "model": r["model"]}
            for r in rows if r["cost_usd"] > 0
        ]
        return {
            "total_cost_usd": round(total, 4),
            "total_cost_usd_cached": round(total_cached, 4),
            "agents_count": len(agents),
            "agents": agents,
        }


@router.get("/api/usage")
async def get_usage():
    if is_auth_enabled():
        return {"usage": None}
    now = time.time()

    if _usage_cache["data"] and (now - _usage_cache["ts"]) < _USAGE_CACHE_TTL:
        anthropic_data = _usage_cache["data"]
    else:
        token, refresh_token, _tier = _read_oauth_credentials()
        if not token:
            return JSONResponse({"error": "no OAuth credentials found"}, status_code=500)

        try:
            anthropic_data = await _fetch_anthropic_usage(token)
        except PermissionError:
            if refresh_token:
                new_token = await _refresh_oauth_token(refresh_token)
                if new_token:
                    try:
                        anthropic_data = await _fetch_anthropic_usage(new_token)
                        _usage_cache["token"] = new_token
                    except Exception as e:
                        return JSONResponse({"error": f"refresh succeeded but usage fetch failed: {e}"}, status_code=500)
                else:
                    return JSONResponse({"error": "token expired, refresh failed"}, status_code=500)
            else:
                return JSONResponse({"error": "token expired, no refresh token"}, status_code=500)
        except RuntimeError:
            if _usage_cache["data"]:
                anthropic_data = _usage_cache["data"]
            else:
                return JSONResponse({"error": "rate limited by Anthropic, no cached data"}, status_code=429)
        except Exception as e:
            if _usage_cache["data"]:
                anthropic_data = _usage_cache["data"]
            else:
                return JSONResponse({"error": str(e)}, status_code=500)

        _usage_cache["data"] = anthropic_data
        _usage_cache["ts"] = now
        _save_usage_cache()

    return {
        "anthropic": anthropic_data,
        "orchestra": _get_agents_cost(),
    }


SNAPSHOT_INTERVAL = 300


async def _usage_snapshot_loop():
    from app.db import usage_save_snapshot, usage_cleanup_old
    await asyncio.sleep(10)
    while True:
        try:
            token, refresh_token, _tier = _read_oauth_credentials()
            if token:
                try:
                    data = await _fetch_anthropic_usage(token)
                except PermissionError:
                    if refresh_token:
                        new_token = await _refresh_oauth_token(refresh_token)
                        if new_token:
                            data = await _fetch_anthropic_usage(new_token)
                        else:
                            data = None
                    else:
                        data = None
                except Exception:
                    data = None

                if data:
                    fh = data.get("five_hour") or {}
                    sd = data.get("seven_day") or {}
                    cost = sum(s.cost_usd for s in manager.sessions.values())
                    active = sum(1 for s in manager.sessions.values() if s.status.value == "running")
                    usage_save_snapshot(
                        fh.get("utilization", 0), sd.get("utilization", 0),
                        fh.get("resets_at", ""), sd.get("resets_at", ""),
                        round(cost, 4), active,
                    )
                    _usage_cache["data"] = data
                    _usage_cache["ts"] = time.time()
                    _save_usage_cache()
            usage_cleanup_old(30)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"usage snapshot error: {e}")
        await asyncio.sleep(SNAPSHOT_INTERVAL)


@router.get("/api/usage/history")
async def usage_history(hours: int = 24):
    if is_auth_enabled():
        return []
    from app.db import usage_get_history
    return usage_get_history(hours)


# ── Misc ──

@router.post("/api/report_bug")
async def report_bug_endpoint(req: Request):
    data = await req.json()
    title = data.get("title", "Untitled")
    description = data.get("description", "")
    reporter = data.get("reporter", "unknown")
    scope = data.get("scope", "")
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{ts}] {title}\n- **Reporter:** {reporter}\n- **Scope:** {scope}\n{description}\n"
    bugs_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "BUGS.md")
    try:
        with open(bugs_path, "a") as f:
            f.write(entry)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"result": f"Bug reported: {title}"}


@router.get("/api/orchestrators")
async def list_orchestrators():
    from app.prompting import is_orchestrator_role
    active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
    active_ids = {s["id"] for s in active}
    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
    result = active + db_orchs
    running_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "running"}
    waiting_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "waiting"}
    for o in result:
        o["any_running"] = o.get("scope", "") in running_scopes
        o["any_waiting"] = o.get("scope", "") in waiting_scopes
    return result


@router.delete("/api/orchestrators/{name}")
async def delete_orchestrator(name: str, scope: str, delete_tg_topics: bool = False):
    result = await manager.remove_scope(scope, delete_tg_topics=delete_tg_topics)
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
    ok, holder = acquire_test_lock(req.scope, req.holder, req.reason)
    return {"acquired": ok, "holder": holder}


@router.post("/api/test-lock/release")
async def release_lock_endpoint(req: TestLockRequest):
    from app.db import release_test_lock
    ok = release_test_lock(req.scope, req.holder)
    return {"released": ok}


# ── Git status ──

# Short TTL: git status is cheap but 10s prevents dashboard refresh storms
_git_status_cache: dict = {}  # scope -> {ts, data}
_GIT_STATUS_TTL = 10


async def _run_git(cmd: list[str], cwd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()
        return ""


@router.get("/api/git-status")
async def get_git_status(scope: str):
    now = time.time()
    cached = _git_status_cache.get(scope)
    if cached and (now - cached["ts"]) < _GIT_STATUS_TTL:
        return cached["data"]

    sessions = manager.list_sessions(scope)
    result = []
    for s in sessions:
        # list_sessions() always yields dicts (to_dict for live, raw row for DB)
        wt = s.get("worktree_path")
        if not wt or not Path(wt).is_dir():
            continue
        name = s.get("name")
        branch = s.get("branch")

        ahead_str, dirty_str, last_commit = await asyncio.gather(
            _run_git(["git", "rev-list", "main..HEAD", "--count"], wt),
            _run_git(["git", "status", "--porcelain"], wt),
            _run_git(["git", "log", "-1", "--format=%s"], wt),
        )

        commits_ahead = int(ahead_str) if ahead_str.isdigit() else 0
        dirty_files = len([l for l in dirty_str.splitlines() if l.strip()])
        last_commit = last_commit[:50] if last_commit else ""

        result.append({
            "name": name,
            "branch": branch or "",
            "commits_ahead": commits_ahead,
            "dirty_files": dirty_files,
            "last_commit": last_commit,
        })

    _git_status_cache[scope] = {"ts": now, "data": result}
    return result


@router.post("/api/restart")
async def restart_server():
    import subprocess
    result = await asyncio.to_thread(
        subprocess.run,
        ["sudo", "-n", "systemctl", "restart", "orchestra"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return JSONResponse({"error": result.stderr.strip()}, status_code=500)
    return {"ok": True}


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
