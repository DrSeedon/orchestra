"""CodexBackend — wraps Codex CLI subprocess for agent sessions."""

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tomllib
import uuid
import weakref
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from app.backend_jsonrpc import (
    JsonRpcStdioTransport,
    bounded_tool_arguments,
    terminate_cli_process,
)
from app.events import AgentEvent
from app.runtime_history import (
    CODEX_CLI_HISTORY_VERSION,
    HISTORICAL_TOOL_INSTRUCTION,
    CodexHistoryImport,
    NativeHistoryUnsupported,
    sanitize_sensitive_text,
    build_model_visible_manifest,
)
from app.usage_contract import AggregateUsage, TurnUsage, current_context

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")

# Effective context budgets reported by the ChatGPT-auth Codex runtime. The public API
# advertises a larger GPT-5.6 window, but that is a different surface; local rollout
# token_count events are the runtime source of truth and may override these fallbacks.
CODEX_CONTEXT_LIMITS = {
    "gpt-5.3-codex-spark": 128000,
    "gpt-5.6-sol":   258400,
    "gpt-5.6-terra": 258400,
    "gpt-5.6-luna":  258400,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

# Standard-tier API list prices per 1M tokens, verified 11.08.2026 against
# https://platform.openai.com/docs/pricing (fetched through https://r.jina.ai/ — the page
# itself answers 403 to curl/WebFetch). Cached input is exactly 10% of the input rate for
# every priced model here; `tests/test_backend_codex.py` pins that ratio so a typo cannot
# pass silently.
# Terra and Luna list prices dropped below what we had (Luna 5×: was 1.0/6.0) — rows already
# in `turn_usage` keep the price of their own day and are deliberately not rewritten.
# The long-context tier is per request, while Codex's measured 258,400-token request window
# is below its 272K threshold. Spark is listed explicitly but has no published final price.
CODEX_TOKEN_PRICES = {
    # Promotional pricing from 22.08.2026, published "at least through November 21, 2026":
    # input −20%, output −33%. Verified in the source table, not from the announcement.
    # Rows already in `turn_usage` keep their own day's price, as with Terra/Luna below.
    "gpt-5.6-sol":   {"input": 4.0, "cached": 0.4, "write": 5.0, "output": 20.0},
    "gpt-5.6-terra": {"input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0},
    "gpt-5.6-luna":  {"input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2},
    "gpt-5.5":      {"input": 5.0, "cached": 0.5, "output": 30.0},
    "gpt-5.4":      {"input": 2.5, "cached": 0.25, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.3, "cached": 0.03, "output": 1.25},
    "gpt-5.3-codex-spark": None,
}


# GPT-5.6 reasoning ladder (light→low→medium→high→xhigh→max→ultra). "minimal" kept for
# 5.4/5.5 back-compat. "ultra" (parallel sub-agents) intentionally excluded — a special
# mode, not a plain effort level, and risky to trigger from a generic worker effort field.
CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
CODEX_SILENCE_HEARTBEAT_SECONDS = 30
CODEX_COMPACT_TIMEOUT_SECONDS = 120
CODEX_PROCESS_TIMEOUT_SECONDS = 5
DEFERRED_INTERRUPT_TERMINAL_TIMEOUT_SECONDS = 5.0
CODEX_STREAM_LIMIT = 16 * 1024 * 1024
CODEX_OVERSIZE_READLINE_ERROR = (
    "Separator is not found, and chunk exceed the limit"
)
CODEX_OVERSIZE_READLINE_ERRORS = frozenset({
    CODEX_OVERSIZE_READLINE_ERROR,
    "Separator is found, but chunk is longer than limit",
})


class CodexOversizedRecordError(RuntimeError):
    """The app-server JSONL framing was lost and this transport is unusable."""


_scope_support_cache: tuple[bool, dict[str, str], str] | None = None


async def _run_process(
    *cmd: str,
    env: dict[str, str] | None = None,
    timeout: float = CODEX_PROCESS_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    return (
        int(proc.returncode or 0),
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


def _scope_unit(prefix: str = "orchestra-codex") -> str:
    return f"{prefix}-{os.getpid()}-{uuid.uuid4().hex}.scope"


async def _codex_scope_support() -> tuple[bool, dict[str, str], str]:
    global _scope_support_cache
    if _scope_support_cache is not None:
        return _scope_support_cache
    try:
        runtime_dir = Path(f"/run/user/{os.getuid()}")
        bus = runtime_dir / "bus"
        commands = {
            name: shutil.which(name)
            for name in ("loginctl", "systemd-run", "systemctl")
        }
        missing = [name for name, path in commands.items() if not path]
        if missing:
            raise RuntimeError(f"missing commands: {', '.join(missing)}")
        if not bus.is_socket():
            raise RuntimeError(f"systemd user bus is unavailable: {bus}")

        env = dict(os.environ)
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        rc, linger, stderr = await _run_process(
            commands["loginctl"], "show-user", str(os.getuid()),
            "-p", "Linger", "--value",
        )
        if rc or linger.lower() != "yes":
            detail = stderr or f"Linger={linger or 'unknown'}"
            raise RuntimeError(f"systemd user manager is not persistent: {detail}")

        unit = _scope_unit("orchestra-codex-probe")
        probe = (
            "from pathlib import Path; "
            "row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines() "
            "if line.startswith('0::')); "
            "path = row.split('::', 1)[1]; "
            "events = (Path('/sys/fs/cgroup') / path.lstrip('/') / 'cgroup.events').read_text(); "
            "print(path); print(events)"
        )
        rc, cgroup, stderr = await _run_process(
            commands["systemd-run"], "--user", "--scope", "--quiet", "--collect",
            f"--unit={unit}", "--", sys.executable, "-c", probe,
            env=env,
        )
        if rc:
            raise RuntimeError(stderr or f"disposable scope exited with code {rc}")
        lines = cgroup.splitlines()
        control_group = lines[0] if lines else ""
        events = dict(
            line.split(maxsplit=1)
            for line in lines[1:]
            if " " in line
        )
        if unit not in control_group:
            raise RuntimeError(
                f"disposable process was not attached to {unit}: {control_group}"
            )
        if events.get("populated") != "1":
            raise RuntimeError(
                f"disposable scope has no usable cgroup.events: {events}"
            )
        _scope_support_cache = (True, env, "")
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "Codex verified process scope unavailable; direct launch remains enabled "
            "but hibernation is disabled: %s",
            reason,
        )
        _scope_support_cache = (False, {}, reason)
    return _scope_support_cache


def _codex_cost(model: str, input_tokens: int, cached_input_tokens: int,
                cache_write_input_tokens: int, output_tokens: int) -> float:
    """API-equivalent cost with cached input charged at its actual lower rate."""
    if model not in CODEX_TOKEN_PRICES:
        raise ValueError(f"No token price configured for {model}")
    prices = CODEX_TOKEN_PRICES[model]
    if prices is None:
        raise ValueError(f"No published token price for {model}")
    cached = min(max(0, cached_input_tokens), max(0, input_tokens))
    cache_write = min(max(0, cache_write_input_tokens), max(0, input_tokens - cached))
    fresh = max(0, input_tokens - cached - cache_write)
    return (fresh * prices["input"] + cached * prices["cached"]
            + cache_write * prices.get("write", prices["input"])
            + max(0, output_tokens) * prices["output"]) / 1_000_000


def _read_rollout_context(path: Path) -> dict[str, int] | None:
    """Return the last model-call context from a Codex rollout, or None fail-soft.

    `turn.completed.usage` is cumulative work for the thread and cannot represent the
    currently occupied window. Internal rollout token_count events expose both the last
    call and the runtime-provided effective model_context_window.
    """
    latest = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                payload = row.get("payload") or {}
                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = info.get("last_token_usage") or {}
                window = info.get("model_context_window")
                input_tokens = usage.get("input_tokens")
                if not isinstance(window, int) or window <= 0:
                    continue
                if not isinstance(input_tokens, int) or input_tokens < 0:
                    continue
                cached = usage.get("cached_input_tokens", 0)
                cache_write = usage.get("cache_write_input_tokens", 0)
                latest = {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached if isinstance(cached, int) else 0,
                    "cache_write_input_tokens": (
                        cache_write if isinstance(cache_write, int) else 0
                    ),
                    "model_context_window": window,
                }
    except (FileNotFoundError, OSError):
        return None
    return latest


def _read_rollout_totals(path: Path) -> dict[str, int] | None:
    latest = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                payload = row.get("payload") or {}
                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                total = ((payload.get("info") or {}).get("total_token_usage") or {})
                input_tokens = total.get("input_tokens")
                if not isinstance(input_tokens, int) or input_tokens < 0:
                    continue
                latest = {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": max(0, int(total.get("cached_input_tokens") or 0)),
                    "cache_write_input_tokens": max(
                        0, int(total.get("cache_write_input_tokens") or 0)
                    ),
                    "output_tokens": max(0, int(total.get("output_tokens") or 0)),
                }
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    return latest


def _usage_delta(current: dict[str, int], baseline: dict[str, int] | None) -> dict[str, int]:
    baseline = baseline or {}
    result = {}
    for key in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens"
    ):
        value = max(0, int(current.get(key) or 0))
        before = max(0, int(baseline.get(key) or 0))
        result[key] = value - before if value >= before else value
    return result


def _tool_arguments_json(arguments) -> str:
    return json.dumps(
        bounded_tool_arguments(arguments if isinstance(arguments, dict) else {}),
        ensure_ascii=False,
    )


_SAFE_HOME_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
_CODEX_HOME_ROOT = Path.home() / ".orchestra" / "codex-home"
_MANAGED_HOME_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_CODEX_STATE_MIGRATIONS_BY_CLI = {
    # Captured from a fresh Codex 0.149.0 app-server state DB. Checksums are SQLx's
    # provider-owned migration identity; a mutable base DB is not schema authority.
    CODEX_CLI_HISTORY_VERSION: (
        (1, bytes.fromhex("627ef19164c9bb298a0cd99945981c9b7bda3d9e6cf12eb35145e3b1d3bf7cf8740f0dbaa0b475185fc2993397078049")),
        (2, bytes.fromhex("521b72cbc04c7d03b1e4aef8dc0fdee672f1f7f5881385a55a0e937e4ebe87a3f67bca4d3f6b59afbc9a7ca723c82856")),
        (3, bytes.fromhex("e58a2862bdb66d3274e60144a26dc9d68bbefff834cd29b82b740f38fcf95862934f412665d985715167839e8f0eb377")),
        (4, bytes.fromhex("8adc251366e4c7e5ea78b620ac71f4c4bdfb8f048bf9f2fd7204226cfba54c8e83fc9d83fc1ec334bc683bb7f6d0d8a8")),
        (5, bytes.fromhex("1ac64f85e083e5b49b974bf498fc39c630f0032057fb4bf4cb31708619fac5a80189f261cf3e38dafd92dc406e73c220")),
        (6, bytes.fromhex("a203fc4b597e1420bffdc4e00e214798b21cf7fc921d8bd6f089c75248fb6a4b4942c97a1f8e0271eca8cf3b3e5e7a80")),
        (7, bytes.fromhex("7e35a464df6d4c82694de50865ba3fe9104f9e1385a33be7d633ab4b8d6cf60b7f369fe083d31251fd77b75fa2d61f82")),
        (8, bytes.fromhex("aa3f287f7a448554e7af01f259f0871ce90ace1a7d4b8ebbd74c87ae57c3e21119f7eec8b9c2e9f4a9e76e63a0f0b60a")),
        (9, bytes.fromhex("8b469360777e6dd6c21d3f0eb93481251846b0a50e0a44eb0dbee4a0a32b7206768a5d83a5fcec30c6fd2e43d755ff1b")),
        (10, bytes.fromhex("8adaf1365f8e5deeba68bdeee9fd83b094a87bdab364d95ab5c714f7b8bd95dc3b38576871470312154c9d41e8f10f93")),
        (11, bytes.fromhex("31ececbd07f04452d0dc5127d824ed183056b9900a31aa739387a4aef232016d975110829814841fb6bf3fd23634b799")),
        (12, bytes.fromhex("0012a213ed25f2cf806c2530c487ebb00b4f102f5960d1a852154a0f77d25c9e9f7df29550faeb30ebaff15a26c7d604")),
        (13, bytes.fromhex("05526a0900a8430523a9a05932ea61302fce20782b245498565c1b9a2dfd10cf5c49932089b496ae23af44f6c5f76af4")),
        (14, bytes.fromhex("4d2fbb2442c5c5c7c47b4254b5b8dc2c52129f65c4a952a79f1ec5c40fb07483326429ce5acdbd372bc9262352cb6277")),
        (15, bytes.fromhex("0eece6db59c948faa6608526af440a9f53f5a982d27f3e866cd9f1401c2e59bc61f8381b5a1c9744acb232f50db493e5")),
        (16, bytes.fromhex("4768f743e981293735c6e07b0282ec8ace98af720059d68555b17979d28c94b0c893a97a950d5e32758bc6d92d8fe6ff")),
        (17, bytes.fromhex("4cbdb2edfebf6040858ffc193cffa36e6b3fbf508f8418ad073081bbfcf59d53d423b6eb4c0ded206ab4d4c1a0efed94")),
        (18, bytes.fromhex("a4363003bc44f0a4ae1eed53b536b7175f97863ea6881a059dc6642e70e2921576204697cec2345f560e65ff7fbf4455")),
        (19, bytes.fromhex("3884c02f080f0184e92b620f870dfbb840a8ec5dfce2fe6455dd8197fcd27d7dd86e63ad6ec7c4091a1161d9ed199f8d")),
        (20, bytes.fromhex("07673f4859f740134569ab9606760d8173ed6df92da47c86fbd0ceeb333e18ab7ac91d525ab8c11503c42164fd4167ae")),
        (21, bytes.fromhex("ea1aebe4f5a1d56c8effcc15f705c272275dd8adfeb01bc97d3f7b283474a3b8c2b0c8c69de55786e8bda17cae6f4de7")),
        (22, bytes.fromhex("160fe01b757dd06f9573b9030952d021f2b148732bea5fc5f5ae09e9227f3f83ca676695edaf8502669fcb546119dc94")),
        (23, bytes.fromhex("e6c748a9a18286e4c773ffe0dad659f16fb7e5b7b032235815991c405f2d32c068f3edde920d0fcf589b687bffcfee2e")),
        (24, bytes.fromhex("e92aa526b1f36e26f6221c04a671f07b27de2e7a5112d93a8c3af816a87846e7804d5fbad689e61cf4ec91fd79d3bd8a")),
        (25, bytes.fromhex("d6fb51d79941b93c3278fe2a8a0c6fa882407b7b716e32d72329f0b7b60c181a42f49e56cd552315efb0402a111ede12")),
        (26, bytes.fromhex("6c62a325d3b9ca8e424eacb9e3890d8d9de57c3725e2d1fa30c3743ae779fca2969387174359dfb26e4920791ae7e831")),
        (27, bytes.fromhex("d84dca6a039e004c0c7d06c5a16c2ccc363137537f3dd9898f50bb013ce9067140761b87d58ca742d769d35976863fc3")),
        (28, bytes.fromhex("ef44adaa291e40dfe6b74e3cd259711adae13f01c5594b177d08e2d2041a67ed3813feecf049662aaed0f636bd3f4ac3")),
        (29, bytes.fromhex("e9ec76f97dbf41ce4949de324a2a26538c2025c0ac4f272b77a852970fb14b7ec970d6978a765f91ae171dce9c0e4149")),
        (30, bytes.fromhex("80c1cdacd4520b42b18b960164912685591a7ee041645f35609a2ee2792eb474b7b0b758366556982d8cde2acb583672")),
        (31, bytes.fromhex("943675a9b3dc92d0b2731ae7d2fe324ff1a40b6366b9d5d8b4cb47ca885c08beb6ebb1d776a5a47c878b4094dde70ea0")),
        (32, bytes.fromhex("3c01d615c5e3aba0fd858b7168e73881598d7d33a0ecc41527bdf6595a199d1aec2ff9f3b3000a57241c500d81b34259")),
        (33, bytes.fromhex("4904aae354e3d8ce32ac21d2ae579fd708446ae1dfb2649fc9dd22dc9279b91a2bbb02e6f01b3e0abd1088177bf2f030")),
        (34, bytes.fromhex("d6fea739c76ebdef35a23f06e54efb5904d7987fb6b663db1ebc98eb9b192305f454932bfbaa2231aedca6209903a5f3")),
        (35, bytes.fromhex("d7b56acb07c96858bdc7ca4c53db51eb71c6a19ef2c524ff68c2660a6fe0d23211a6d39cb905f01c42ffb7c8ee913bbc")),
        (36, bytes.fromhex("6381f7bb4c36be41c6106b8523ea6c68f5a00273a5522155b7b84bad26d152436f3375df7097ce3abf2421aec32641ed")),
        (37, bytes.fromhex("f6a5ab0db36bb9e45ab5285b56090fb453df0a4d4d8d62eace234f0b557f4203c6c455fc67bd7d6e72623c3979ec9405")),
        (38, bytes.fromhex("e7778522cbe529f5e2ba179b502aee8e5c21272ad820e672ab0a565f7edc9bd0f29171ccf9815c0acc0f89eae0a2b1fc")),
        (39, bytes.fromhex("c217b3d14c08c23603f485af11452ee2b68f65fa8dbaf215f33f53b608c092be8738de3f63d6a38f120edea5af247c17")),
        (40, bytes.fromhex("a7a99674f90a43184e43d66595c4f1da50ae8715a5bfcb1579a2b7b10668335d7f7ab6b6f2d7a7a379272773d803a914")),
        (41, bytes.fromhex("0dc734dbe4cbcc5ad5a8bbc2fdc1cf770ddea3cb53eb36c55a4da6fa2e8be4cc8e68672f43ac953e727e415e45c50a78")),
        (42, bytes.fromhex("cfdc4fd47328d1b67c0c7555125de4fb4add5b3b57fd31ac1987e4d8b0c99b1f5418db9ee7ec2158aed8a2e3dfcfd636")),
        (43, bytes.fromhex("605128e722bd2521c7e979e9961c16706435e442b3e3a8efa36f6b16c42e3833090906d9a62fde097a109b78e29da830")),
        (44, bytes.fromhex("5d29223bd1cafe456a4af992a545e8ec420b71331eb12a7427e26512b8a44117d9445b83562f095b3a5a0f11c4f091d2")),
        (45, bytes.fromhex("a7fadc8caea8b6abeb108f588a91b8e5d1c9e2645ce990f2251b9f0234e6e53d78fc854f1c88c7217cc143016539d691")),
        (46, bytes.fromhex("63addf6115c3fb1a22a886108ce6ebff5cd8408f219606dc2f8396836418e56d5be2a6de7b0df877119a28096ee67d22")),
        (47, bytes.fromhex("1ae117e4ab40813de2b6cfed521585a5396a8dcb7277923d539ed111f5e76424787131ef1de353be5dd78e8228f204cc")),
        (48, bytes.fromhex("9d298333f7523010502044685009ffe1ed18c3fed7f01fb200d62252f90ab0d897ccf05e478f90150b941ea6c0bd459c")),
        (49, bytes.fromhex("faf45c392bb8572062bbd52f9702966cf62e3d195a1633f54cfe1b7dcb5865a3f951dc75c975179dc9a0ee639f7426a7")),
        (50, bytes.fromhex("d2802e96f5fc1900fc6d3d595f040ebca8d25310ae9d1499a12b91f1635617adf5d2b4a93d0807203a22f4a6d4edb77e")),
    ),
}
# Из базового конфига переносим ТОЛЬКО это. Расширять список осознанно: каждая строка
# здесь — копия, которая начинает расходиться с оригиналом.
_CARRIED_BASE_KEYS = (
    "project_doc_max_bytes",
    "model_context_window",
    "model_auto_compact_token_limit",
)


def _write_private(path: Path, text: str) -> None:
    """Атомарная запись файла 0600: сначала временный сосед, потом os.replace.

    Права ставятся ДО первой записи (окно 0644 между созданием и chmod — ровно тот зазор,
    через который эта задача и текла), а os.replace не даёт прочитать полуфайл.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _base_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


@dataclass(frozen=True)
class _CodexStateInfo:
    status: str
    last_success_at: int | None
    migrations: tuple[tuple[int, bytes], ...]
    thread_count: int


def _managed_home_async_lock(home: Path) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _MANAGED_HOME_LOCKS.setdefault(loop, {})
    return locks.setdefault(home.resolve(), asyncio.Lock())


def _acquire_managed_home_file_lock(home: Path) -> int:
    lock_dir = home.parent / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(lock_dir, 0o700)
    digest = hashlib.sha256(os.fsencode(str(home.resolve()))).hexdigest()[:24]
    lock_path = lock_dir / f"{digest}.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _release_managed_home_file_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


async def _acquire_managed_home_file_lock_async(home: Path) -> int:
    task = asyncio.create_task(asyncio.to_thread(_acquire_managed_home_file_lock, home))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # flock cannot be cancelled in the worker thread. If it acquires after this
        # waiter is cancelled, release it before propagating cancellation.
        await asyncio.gather(task, return_exceptions=True)
        if not task.cancelled() and task.exception() is None:
            await asyncio.to_thread(_release_managed_home_file_lock, task.result())
        raise


@asynccontextmanager
async def _managed_home_lock(home: Path):
    async with _managed_home_async_lock(home):
        fd = await _acquire_managed_home_file_lock_async(home)
        try:
            yield
        finally:
            await _run_home_io(_release_managed_home_file_lock, fd)


async def _run_home_io(func, *args):
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Releasing the home lock while the thread still moves SQLite files would let the
        # next owner overlap the very operation the lock exists to serialize.
        await asyncio.gather(task, return_exceptions=True)
        raise


def _state_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _inspect_codex_state(path: Path, *, check_integrity: bool) -> _CodexStateInfo:
    required = {
        "_sqlx_migrations": {
            "version", "description", "installed_on", "success", "checksum",
            "execution_time",
        },
        "backfill_state": {
            "id", "status", "last_watermark", "last_success_at", "updated_at",
        },
        "threads": {"id"},
    }
    try:
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing_tables = required.keys() - tables
            if missing_tables:
                raise RuntimeError(
                    f"Codex state schema is incomplete: missing {sorted(missing_tables)}"
                )
            for table, columns in required.items():
                missing = columns - _state_columns(conn, table)
                if missing:
                    raise RuntimeError(
                        f"Codex state schema is incomplete: {table} missing {sorted(missing)}"
                    )
            if check_integrity:
                result = [str(row[0]) for row in conn.execute("PRAGMA quick_check")]
                if result != ["ok"]:
                    raise RuntimeError(f"Codex state quick_check failed: {result[:3]}")
            migration_rows = list(conn.execute(
                "SELECT version, success, checksum FROM _sqlx_migrations ORDER BY version"
            ))
            if not migration_rows or any(int(row[1]) != 1 for row in migration_rows):
                raise RuntimeError("Codex state migrations are absent or incomplete")
            migrations = tuple(
                (int(version), bytes(checksum))
                for version, _success, checksum in migration_rows
            )
            backfill_rows = list(conn.execute(
                "SELECT status, last_success_at FROM backfill_state WHERE id = 1"
            ))
            if len(backfill_rows) != 1:
                raise RuntimeError("Codex state has no unique backfill_state row")
            status, last_success_at = backfill_rows[0]
            thread_count = int(conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
    except RuntimeError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"cannot validate Codex state {path}: {type(exc).__name__}: {exc}"
        ) from exc
    return _CodexStateInfo(
        status=str(status),
        last_success_at=(int(last_success_at) if last_success_at is not None else None),
        migrations=migrations,
        thread_count=thread_count,
    )


def _validate_codex_state_migrations(
    info: _CodexStateInfo,
    cli_version: str,
    *,
    allow_older_prefix: bool = False,
) -> None:
    expected = _CODEX_STATE_MIGRATIONS_BY_CLI.get(cli_version)
    if expected is None:
        raise RuntimeError(
            f"no validated Codex state migration signature for CLI {cli_version or 'unknown'}"
        )
    matches_known_older_schema = (
        allow_older_prefix
        and len(info.migrations) < len(expected)
        and expected[:len(info.migrations)] == info.migrations
    )
    if info.migrations != expected and not matches_known_older_schema:
        raise RuntimeError(
            "refusing unsupported Codex state migration signature: "
            f"CLI={cli_version}, expected={len(expected)} migrations through "
            f"{expected[-1][0]}, got={len(info.migrations)} migrations through "
            f"{info.migrations[-1][0] if info.migrations else 'none'}"
        )


def _managed_codex_state_needs_seed(home: Path, cli_version: str) -> bool:
    target = home / "state_5.sqlite"
    if not target.exists():
        return True
    info = _inspect_codex_state(target, check_integrity=False)
    # A pinned newer CLI may encounter the exact validated prefix produced by the
    # previous release. Preserve it and let SQLx apply only the missing provider-owned
    # migrations on app-server startup; changed, reordered, or extra rows still fail.
    _validate_codex_state_migrations(info, cli_version, allow_older_prefix=True)
    if info.status == "complete" and info.last_success_at is not None:
        return False
    if info.status == "running" and info.last_success_at is None:
        return True
    raise RuntimeError(
        "refusing to replace Codex state that may contain successful history: "
        f"status={info.status!r}, last_success_at={info.last_success_at!r}"
    )


def _backup_codex_state(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_conn:
        source_conn.execute("PRAGMA query_only=ON")
        with sqlite3.connect(destination) as destination_conn:
            source_conn.backup(destination_conn)
    os.chmod(destination, 0o600)


def _select_managed_codex_state_source(target_home: Path, cli_version: str) -> Path:
    base = _base_codex_home() / "state_5.sqlite"
    candidates: list[tuple[int, int, Path]] = []
    sources = [base]
    if _CODEX_HOME_ROOT.is_dir():
        sources.extend(
            candidate
            for candidate in _CODEX_HOME_ROOT.glob("*/state_5.sqlite")
            if candidate.parent != target_home
        )
    for candidate in sources:
        try:
            info = _inspect_codex_state(candidate, check_integrity=True)
            _validate_codex_state_migrations(
                info,
                cli_version,
                allow_older_prefix=True,
            )
        except RuntimeError as exc:
            logger.warning("ignoring invalid Codex state source %s: %s", candidate, exc)
            continue
        if info.status == "complete" and info.last_success_at is not None:
            candidates.append((info.thread_count, info.last_success_at, candidate))
    if not candidates:
        raise RuntimeError(
            f"no healthy Codex state source validated for CLI {cli_version}"
        )
    return max(candidates, key=lambda item: (item[0], item[1], str(item[2])))[2]


def _prepare_managed_codex_state(
    home: Path,
    source: Path,
    cli_version: str,
) -> str:
    """Seed only absent or never-successful state from a validated WAL-safe backup."""
    if cli_version != CODEX_CLI_HISTORY_VERSION:
        raise RuntimeError(
            "managed Codex state seed is validated only for CLI "
            f"{CODEX_CLI_HISTORY_VERSION}, got {cli_version or 'unknown'}"
        )
    target = home / "state_5.sqlite"
    if target.exists():
        target_info = _inspect_codex_state(target, check_integrity=False)
        _validate_codex_state_migrations(
            target_info,
            cli_version,
            allow_older_prefix=True,
        )
        if target_info.status == "complete" and target_info.last_success_at is not None:
            return "healthy"
        if not (
            target_info.status == "running" and target_info.last_success_at is None
        ):
            raise RuntimeError(
                "refusing to replace Codex state that may contain successful history: "
                f"status={target_info.status!r}, "
                f"last_success_at={target_info.last_success_at!r}"
            )
    else:
        target_info = None

    source_info = _inspect_codex_state(source, check_integrity=True)
    _validate_codex_state_migrations(
        source_info,
        cli_version,
        allow_older_prefix=True,
    )
    if source_info.status != "complete" or source_info.last_success_at is None:
        raise RuntimeError(
            "refusing incomplete Codex state source: "
            f"status={source_info.status!r}, "
            f"last_success_at={source_info.last_success_at!r}"
        )
    # Both sides are independently validated as the current schema or an exact older
    # prefix. Replacing a never-successful target with a healthy source is safe even when
    # their prefix lengths differ: the pinned provider applies the remaining migrations.

    temporary = home / f".state_5.seed-{uuid.uuid4().hex}.sqlite"
    recovery: Path | None = None
    moved: list[tuple[Path, Path]] = []
    try:
        _backup_codex_state(source, temporary)
        copied = _inspect_codex_state(temporary, check_integrity=True)
        if (
            copied.status != "complete"
            or copied.last_success_at is None
            or copied.migrations != source_info.migrations
        ):
            raise RuntimeError("Codex state backup is incomplete or changed schema")
        if target_info is None:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise RuntimeError(
                    "Codex managed state appeared during seed; refusing to overwrite it"
                ) from exc
            temporary.unlink()
            logger.info(
                "Codex managed state seeded: home=%s source=%s threads=%d",
                home, source, copied.thread_count,
            )
            return "seeded"

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        recovery = home / f"state-recovery-{stamp}-{uuid.uuid4().hex[:8]}"
        recovery.mkdir(mode=0o700)
        try:
            for path in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
                if path.exists():
                    preserved = recovery / path.name
                    os.replace(path, preserved)
                    moved.append((path, preserved))
            os.replace(temporary, target)
        except BaseException:
            for original, preserved in reversed(moved):
                if original.exists():
                    original.unlink()
                os.replace(preserved, original)
            if recovery.exists() and not any(recovery.iterdir()):
                recovery.rmdir()
            raise
        logger.warning(
            "Codex never-successful running state recovered: home=%s source=%s "
            "preserved=%s threads=%d",
            home, source, recovery, copied.thread_count,
        )
        return "recovered"
    finally:
        temporary.unlink(missing_ok=True)


def _carried_base_scalars() -> str:
    """Разрешённые скаляры из базового config.toml (потолок обрезки AGENTS.md и т.п.)."""
    base = _base_codex_home() / "config.toml"
    if not base.is_file():
        return ""
    try:
        data = tomllib.loads(base.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("could not read base codex config %s: %s", base, exc)
        return ""
    lines = [
        f"{key} = {json.dumps(data[key])}"
        for key in _CARRIED_BASE_KEYS
        if isinstance(data.get(key), (int, float, bool, str))
    ]
    return "\n".join(lines)


_ORCHESTRA_MCP_TOOL_EXCLUSIONS: frozenset[str] = frozenset()


def _orchestra_full_mcp_tools() -> tuple[str, ...]:
    """Build Codex's full allowlist from the authoritative FastMCP registry."""
    from app.mcp_stdio import mcp

    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    stale_exclusions = _ORCHESTRA_MCP_TOOL_EXCLUSIONS - registered
    if stale_exclusions:
        raise RuntimeError(
            f"Orchestra MCP exclusions are not registered: {sorted(stale_exclusions)}"
        )
    # resolve_merge_operation and send_chart were absent only because their registrations
    # postdated the deleted static allowlist; neither omission expressed an access policy.
    return tuple(sorted(registered - _ORCHESTRA_MCP_TOOL_EXCLUSIONS))


class CodexProtocolError(RuntimeError):
    """JSON-RPC error returned by Codex app-server."""

    def __init__(self, method: str, error: dict):
        self.method = method
        self.error = error
        super().__init__(f"{method}: {error.get('message', 'Codex app-server error')}")


class CodexBackend(JsonRpcStdioTransport):
    """Persistent Codex app-server client with native turn steering.

    One app-server process owns one resumable thread. `send()` starts a turn while idle
    and uses `turn/steer` while that turn is in flight, matching the native Codex TUI.
    """

    RUNTIME_LABEL = "Codex app-server"

    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_thread_id: str | None = None,
                 mcp_env: dict[str, str] | None = None,
                 mcp_servers: dict | None = None,
                 reasoning_effort: str = "high",
                 is_orchestrator: bool = False,
                 history_import: object | None = None,
                 validation_profile: bool = False):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._thread_id: str | None = resume_thread_id
        self._mcp_env: dict[str, str] = mcp_env or {}
        self._mcp_servers: dict = mcp_servers or {}
        # #224: приватный CODEX_HOME этого агента; готовится лениво в _prepare_codex_home,
        # чтобы конструктор оставался безопасным для вызова без session id.
        self._codex_home: Path | None = None
        # Digest of the managed config actually loaded by the current app-server.
        # Adopted pre-restart processes deliberately start unknown and reconnect before
        # their next idle turn, so config/context upgrades cannot leave them behind.
        self._loaded_config_sha256: str | None = None
        self._is_orchestrator = is_orchestrator
        if history_import is not None and not isinstance(history_import, CodexHistoryImport):
            raise TypeError("history_import must be CodexHistoryImport")
        self._history_import = history_import
        self._validation_profile = validation_profile
        self.reasoning_effort = (
            reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
        )
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._request_seq = 0
        self._write_lock = asyncio.Lock()
        self._active_turn_id: str | None = None
        self._events_active = False
        self._deferred_control: dict | None = None
        self._deferred_control_turn_id: str | None = None
        self._deferred_terminal_deadline: float | None = None
        self._disconnecting = False
        self._last_stderr = ""
        self._last_turn_error: dict = {}
        self._started_items: set[str] = set()
        self._subagent_descriptions: dict[str, str] = {}
        self._rollout_path: Path | None = None
        self._usage_baseline: dict[str, int] | None = None
        self._thread_usage_total: dict[str, int] | None = None
        self._last_call_usage: dict[str, int] | None = None
        self._model_context_window = CODEX_CONTEXT_LIMITS.get(model, 258400)
        self._compact_future: asyncio.Future | None = None
        self._compact_notifications: asyncio.Queue[dict] | None = None
        self._compact_context_tokens: int | None = None
        self._scope_unit: str | None = None
        self._scope_env: dict[str, str] = {}
        self._hibernate_safe = False
        self._scope_reason = "scope preflight has not run"
        self._teardown_error: str | None = None
        self._reader_failure: BaseException | None = None
        self._terminal_reader_failure = False

    @property
    def session_id(self) -> Optional[str]:
        return self._thread_id

    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
        return build_model_visible_manifest(
            runtime="codex",
            model=self.model,
            effective_window=self._model_context_window,
            system_prompt=self.system_prompt,
            prepared=prepared,
            validation_profile=validation_profile,
            project_docs=getattr(prepared, "project_docs", ()),
            mcp_servers=self._mcp_servers,
        )

    @property
    def active_turn_id(self) -> Optional[str]:
        """The turn the adopted bytes belong to (#230 T4)."""
        return self._active_turn_id

    @property
    def deferred_interrupt_pending(self) -> bool:
        return bool(
            self._deferred_control
            and self._deferred_control_turn_id
            and self._deferred_control_turn_id == self._active_turn_id
        )

    def _clear_deferred_control(self) -> None:
        self._deferred_control = None
        self._deferred_control_turn_id = None
        self._deferred_terminal_deadline = None

    @property
    def oversized_reader_failure(self) -> bool:
        """Whether a JSONL record was lost and the native thread must be retired."""
        return self._terminal_reader_failure

    @property
    def hibernate_safe(self) -> bool:
        return self._hibernate_safe

    @property
    def hibernate_unavailable_reason(self) -> str:
        return self._scope_reason

    @property
    def has_owned_processes(self) -> bool:
        return self._proc is not None or self._scope_unit is not None

    async def _verify_history_version(self) -> None:
        if not self._history_import:
            return
        try:
            returncode, stdout, stderr = await _run_process(
                CODEX_BIN,
                "--version",
                timeout=10,
            )
        except (OSError, asyncio.TimeoutError) as error:
            raise NativeHistoryUnsupported(
                f"cannot verify Codex CLI history version: {type(error).__name__}: {error}"
            ) from error
        version_text = stdout or stderr
        parts = version_text.split()
        actual_version = parts[1] if len(parts) >= 2 and parts[0] == "codex-cli" else ""
        if returncode != 0 or actual_version != CODEX_CLI_HISTORY_VERSION:
            actual = version_text or f"exit {returncode}"
            raise NativeHistoryUnsupported(
                f"native Codex history requires CLI {CODEX_CLI_HISTORY_VERSION}, got {actual}"
            )

    async def _managed_state_cli_version(self) -> str:
        try:
            returncode, stdout, stderr = await _run_process(
                CODEX_BIN,
                "--version",
                timeout=10,
            )
        except (OSError, asyncio.TimeoutError) as error:
            raise RuntimeError(
                "cannot verify CLI version for managed Codex state: "
                f"{type(error).__name__}: {error}"
            ) from error
        version_text = stdout or stderr
        parts = version_text.split()
        version = parts[1] if len(parts) >= 2 and parts[0] == "codex-cli" else ""
        if returncode != 0 or not version:
            raise RuntimeError(
                "cannot identify CLI version for managed Codex state: "
                f"{version_text or f'exit {returncode}'}"
            )
        return version

    async def adopt(self, fd_in: int, fd_out: int, thread_id: str,
                    active_turn_id: str | None = None, *,
                    leftover: str = "", cli_pid: int = 0, cli_started_at: int = 0) -> None:
        """Take over an ALREADY RUNNING app-server over inherited pipes (#230 T2).

        No process is spawned and no handshake is sent: the CLI outlived the supervisor
        restart, it is already initialized, and its turn is still streaming into fd_out
        (measured — docs/tasks/230/research.md F1). Re-initializing here would be wrong and
        would also block, because the stream may be silent for minutes.
        """
        self._notifications = asyncio.Queue()
        self._disconnecting = False
        self._last_stderr = ""
        await self.adopt_pipes(fd_in, fd_out, limit=CODEX_STREAM_LIMIT,
                               leftover=leftover, cli_pid=cli_pid,
                               cli_started_at=cli_started_at)
        self._thread_id = thread_id
        self._loaded_config_sha256 = None
        self._active_turn_id = active_turn_id
        self._teardown_error = None
        self._reader_failure = None
        self._terminal_reader_failure = False
        self._reader_task = asyncio.create_task(self._read_stdout())

    async def connect(self) -> None:
        home = self._managed_codex_home_path()
        if home is None:
            await self._connect_unlocked()
            return
        async with _managed_home_lock(home):
            config_sha256 = await _run_home_io(
                self._refresh_managed_config_sha256
            )
            cli_version = await self._managed_state_cli_version()
            if cli_version != CODEX_CLI_HISTORY_VERSION:
                # The provider owns forward migrations.  Blocking before the app-server
                # starts strands every fresh worker after a CLI upgrade; let that binary
                # migrate its own managed state under the per-home lock.
                logger.warning(
                    "skipping pinned managed Codex state seed for CLI %s; "
                    "provider will migrate state on startup",
                    cli_version or "unknown",
                )
                await self._connect_unlocked()
                self._loaded_config_sha256 = config_sha256
                return
            if await _run_home_io(
                _managed_codex_state_needs_seed,
                home,
                cli_version,
            ):
                logger.info("Codex managed state preparation started: home=%s", home)
                source = await _run_home_io(
                    _select_managed_codex_state_source,
                    home,
                    cli_version,
                )
                await _run_home_io(
                    _prepare_managed_codex_state,
                    home,
                    source,
                    cli_version,
                )
            await self._connect_unlocked()
            self._loaded_config_sha256 = config_sha256

    async def _connect_unlocked(self) -> None:
        if self.is_alive and not self._teardown_error:
            return

        if self.has_owned_processes:
            await self.disconnect()
        await self._verify_history_version()
        self._notifications = asyncio.Queue()
        self._disconnecting = False
        self._last_stderr = ""
        self._reader_failure = None
        self._terminal_reader_failure = False
        codex_cmd = self._codex_command()

        scope_ok, scope_env, scope_reason = await _codex_scope_support()
        env = self._build_env()
        self._hibernate_safe = scope_ok
        self._scope_reason = scope_reason
        if scope_ok:
            self._scope_unit = _scope_unit()
            self._scope_env = scope_env
            env.update({
                key: scope_env[key]
                for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
            })
            cmd = [
                shutil.which("systemd-run") or "systemd-run",
                "--user", "--scope", "--quiet", "--collect",
                f"--unit={self._scope_unit}", "--", *codex_cmd,
            ]
        else:
            self._scope_unit = None
            self._scope_env = {}
            cmd = codex_cmd

        if scope_ok:
            # A scoped launch puts `systemd-run` between us and the CLI, so `_proc.pid` is the
            # launcher, not the app-server. Handing those pipes over would advertise a survivor
            # we could not identify later, so this path keeps PIPE and stays non-adoptable —
            # the same behaviour as before #237, but said out loud instead of silently.
            logger.warning(
                "Codex scope launch: seamless handover is unavailable for this session "
                "(pid identity belongs to systemd-run, not to the app-server)"
            )

        child_stdin = child_stdout = our_stdin = our_stdout = None
        try:
            if scope_ok:
                stdio = {"stdin": asyncio.subprocess.PIPE,
                         "stdout": asyncio.subprocess.PIPE}
            else:
                child_stdin, child_stdout, our_stdin, our_stdout = self.new_child_pipes()
                stdio = {"stdin": child_stdin, "stdout": child_stdout}
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                **stdio,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.cwd,
                limit=CODEX_STREAM_LIMIT,
            )
            if our_stdin is not None:
                # Ownership passes at the CALL, not on success: half-attached, one of these
                # already belongs to a live transport and the cleanup below cannot tell which.
                attach_in, attach_out = our_stdin, our_stdout
                our_stdin = our_stdout = None
                await self.attach_owned_pipes(attach_in, attach_out,
                                              limit=CODEX_STREAM_LIMIT)
                # Only now drop our copies of the CLI's own ends: the child has had them
                # since the spawn, and keeping ours open would stop it from ever seeing EOF.
                # Closing them AFTER wiring also means a failed wiring leaves them in hand,
                # so the CLI dies on EOF instead of hanging on a pipe nobody reads.
                os.close(child_stdin)
                os.close(child_stdout)
                child_stdin = child_stdout = None
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            metadata_only_resume = self._history_import is None and bool(self._thread_id)
            initialize_params = {
                "clientInfo": {
                    "name": "orchestra",
                    "title": "Orchestra",
                    "version": "1",
                },
            }
            if self._history_import or metadata_only_resume:
                initialize_params["capabilities"] = {"experimentalApi": True}
            await self._request("initialize", initialize_params)
            await self._notify("initialized", {})
            params = {
                "cwd": self.cwd,
                "model": self.model,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
            }
            history_import = self._history_import
            developer_instructions = self.system_prompt
            if history_import:
                developer_instructions = "\n\n".join(filter(None, (
                    developer_instructions,
                    HISTORICAL_TOOL_INSTRUCTION,
                )))
            if developer_instructions:
                params["developerInstructions"] = developer_instructions
            requested_thread_id = self._thread_id
            if history_import:
                params["threadId"] = history_import.thread_id
                params["history"] = list(history_import.history)
                result = await self._request("thread/resume", params)
            elif requested_thread_id:
                params["threadId"] = requested_thread_id
                # The app-server otherwise reconstructs and serializes the complete native
                # history into one JSONL response. Image-heavy threads have exceeded 16 MiB
                # in production; Orchestra only needs the live subscription and thread id.
                params["excludeTurns"] = True
                result = await self._request("thread/resume", params)
            else:
                result = await self._request("thread/start", params)
            thread_id = ((result.get("thread") or {}).get("id"))
            if not thread_id:
                raise RuntimeError("Codex app-server returned no thread id")
            if requested_thread_id and not history_import and thread_id != requested_thread_id:
                raise RuntimeError(
                    "Codex app-server resumed a different thread: "
                    f"requested={requested_thread_id}, returned={thread_id}"
                )
            self._thread_id = thread_id
            self._history_import = None
            self._rollout_path = None
            self._teardown_error = None
        except BaseException:
            # Raw descriptors that never reached a transport are ours alone to close; the
            # ones already handed to `attach_owned_pipes` are cleared above and closed by
            # `disconnect()`, so nothing is closed twice.
            for fd in (child_stdin, child_stdout, our_stdin, our_stdout):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            await self.disconnect()
            raise

    async def send(self, message: str) -> None:
        if self._teardown_error or not self.is_alive:
            await self.connect()
        if not self._thread_id:
            raise RuntimeError("Codex thread is not initialized")

        user_input = [{"type": "text", "text": message}]
        if self._active_turn_id:
            await self._request("turn/steer", {
                "threadId": self._thread_id,
                "expectedTurnId": self._active_turn_id,
                "input": user_input,
            })
            return
        if self._events_active:
            # The server completed the old turn but session.py has not left its event
            # iterator yet. Queue at the session layer so the new turn gets a listener.
            raise RuntimeError("Codex turn is settling; queue this message")

        self._clear_deferred_control()
        await self._reload_stale_managed_config_before_turn()

        self._last_turn_error = {}
        self._last_call_usage = None
        self._started_items.clear()
        self._usage_baseline = (
            dict(self._thread_usage_total)
            if self._thread_usage_total is not None
            else (self._runtime_totals() if self._thread_id else None)
        )
        result = await self._request("turn/start", {
            "threadId": self._thread_id,
            "input": user_input,
            "model": self.model,
            "effort": self.reasoning_effort,
        })
        turn_id = ((result.get("turn") or {}).get("id"))
        if not turn_id:
            raise RuntimeError("Codex app-server returned no turn id")
        self._active_turn_id = turn_id

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self.is_alive:
            return
        expected_turn_id = self._active_turn_id
        self._events_active = True
        try:
            while True:
                timeout = CODEX_SILENCE_HEARTBEAT_SECONDS
                if self.deferred_interrupt_pending:
                    deadline = self._deferred_terminal_deadline
                    if deadline is not None:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            for event in await self._fail_deferred_interrupt(
                                "deferred_interrupt_timeout",
                                "Deferred interrupt did not produce a native terminal in time",
                            ):
                                yield event
                            return
                        timeout = min(timeout, remaining)
                try:
                    message = await asyncio.wait_for(
                        self._notifications.get(),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    if self.deferred_interrupt_pending:
                        for event in await self._fail_deferred_interrupt(
                            "deferred_interrupt_timeout",
                            "Deferred interrupt did not produce a native terminal in time",
                        ):
                            yield event
                        return
                    if not self._active_turn_id:
                        return
                    yield AgentEvent(
                        "thinking_stream",
                        "Still working · no new events for 30s. Steered messages wait for the next model checkpoint.",
                        {"activity": "waiting", "item_id": self._active_turn_id},
                    )
                    continue
                method = message.get("method", "")
                params = message.get("params") or {}
                thread_id = params.get("threadId")
                if thread_id and self._thread_id and thread_id != self._thread_id:
                    continue
                if not self._lifecycle_belongs_to_turn(message, expected_turn_id):
                    continue
                if self._quarantine_deferred_assistant(message):
                    continue
                control = None
                if not self._deferred_control:
                    control = self._deferred_control_from_notification(
                        message, expected_turn_id,
                    )
                    if control:
                        self._deferred_control = control
                        self._deferred_control_turn_id = str(params.get("turnId") or "")
                for event in self._convert_notification(message):
                    yield event
                if control:
                    if not await self.interrupt():
                        for event in await self._fail_deferred_interrupt(
                            "deferred_interrupt_failed",
                            "Deferred interrupt request was not acknowledged",
                        ):
                            yield event
                        return
                    self._deferred_terminal_deadline = (
                        asyncio.get_running_loop().time()
                        + DEFERRED_INTERRUPT_TERMINAL_TIMEOUT_SECONDS
                    )
                if method in ("turn/completed", "_process/exited"):
                    return
        finally:
            self._events_active = False

    def _deferred_control_from_notification(
        self, message: dict, expected_turn_id: str | None,
    ) -> dict | None:
        if message.get("method") != "item/completed":
            return None
        params = message.get("params") or {}
        thread_id = str(params.get("threadId") or "")
        turn_id = str(params.get("turnId") or "")
        if (
            not thread_id
            or thread_id != self._thread_id
            or not turn_id
            or turn_id != expected_turn_id
            or turn_id != self._active_turn_id
        ):
            return None
        item = params.get("item") or {}
        if (
            item.get("type") != "mcpToolCall"
            or item.get("server") != "orchestra"
            or item.get("tool") != "codex_review"
            or item.get("error")
        ):
            return None
        result = item.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            return None
        structured = result.get("structuredContent")
        if not isinstance(structured, dict) or structured.get("error") is not None:
            return None
        control = structured.get("result")
        expected_keys = {"kind", "origin", "job_id", "event_id", "turn_control"}
        if not isinstance(control, dict) or set(control) != expected_keys:
            return None
        job_id = control.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return None
        if control != {
            "kind": "deferred_job",
            "origin": "orchestra.bg_jobs",
            "job_id": job_id,
            "event_id": f"bgjob:v1:{job_id}:completed",
            "turn_control": "interrupt",
        }:
            return None
        return dict(control)

    def _quarantine_deferred_assistant(self, message: dict) -> bool:
        turn_id = self._deferred_control_turn_id
        if not turn_id:
            return False
        params = message.get("params") or {}
        if str(params.get("turnId") or "") != turn_id:
            return False
        method = message.get("method")
        if method == "item/agentMessage/delta":
            return True
        return bool(
            method == "item/completed"
            and (params.get("item") or {}).get("type") == "agentMessage"
        )

    async def _fail_deferred_interrupt(
        self, stop_reason: str, message: str,
    ) -> list[AgentEvent]:
        turn_id = self._deferred_control_turn_id or self._active_turn_id or ""
        control = dict(self._deferred_control or {})
        self._active_turn_id = None
        self._clear_deferred_control()
        disconnect_error = ""
        try:
            await self.disconnect()
        except Exception as exc:
            disconnect_error = f"; disconnect failed: {type(exc).__name__}: {exc}"
        detail = f"{message}{disconnect_error}"
        usage = TurnUsage(
            AggregateUsage.normalized(),
            current_context(
                None,
                self._model_context_window,
                unknown_reason="Codex deferred interrupt ended without native usage",
            ),
        )
        metadata = {
            "event_id": turn_id,
            "session_id": self._thread_id,
            "ok": False,
            "stop_reason": stop_reason,
            "cost_usd": 0,
            "cost_unaccounted": True,
            **usage.metadata(),
            "model_error": "error",
            "errors": [detail],
            "deferred_control": control,
        }
        return [
            AgentEvent("error", detail, {"model_error": "error"}),
            AgentEvent(
                "turn_end",
                f"stop_reason={stop_reason}",
                metadata=metadata,
                usage=usage,
            ),
        ]

    @staticmethod
    def _lifecycle_belongs_to_turn(message: dict, expected_turn_id: str | None) -> bool:
        method = message.get("method", "")
        if method not in ("turn/started", "turn/completed"):
            return True
        received_turn_id = str(
            (((message.get("params") or {}).get("turn") or {}).get("id")) or ""
        )
        if received_turn_id == expected_turn_id:
            return True
        logger.debug(
            "Codex ignored lifecycle event for another turn: "
            "method=%s received_turn_id=%s expected_turn_id=%s",
            method,
            received_turn_id,
            expected_turn_id,
        )
        return False

    async def interrupt(self) -> bool:
        if not self._active_turn_id or not self._thread_id or not self.is_alive:
            return False
        try:
            await asyncio.wait_for(self._request("turn/interrupt", {
                "threadId": self._thread_id,
                "turnId": self._active_turn_id,
            }), timeout=5)
            return True
        except Exception as exc:
            logger.warning("Codex turn interrupt failed: %s", exc)
            return False

    async def compact_context(self) -> dict:
        """Compact the current Codex thread without replacing its thread id."""
        if not self.is_alive:
            raise RuntimeError("Codex app-server is not running")
        if not self._thread_id:
            raise RuntimeError("Codex thread is not initialized")
        if self._active_turn_id:
            raise RuntimeError("cannot compact Codex context during an active turn")
        if self._compact_future and not self._compact_future.done():
            raise RuntimeError("Codex context compact already in progress")

        future = asyncio.get_running_loop().create_future()
        compact_notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._compact_future = future
        self._compact_notifications = compact_notifications
        self._compact_context_tokens = None
        stage = "request acknowledgement"
        try:
            async with asyncio.timeout(CODEX_COMPACT_TIMEOUT_SECONDS):
                await self._request(
                    "thread/compact/start",
                    {"threadId": self._thread_id},
                )
                stage = "completion notification"
                result = await future
                stage = "turn lifecycle"
                await self._drain_compact_lifecycle(compact_notifications)
                # The usage notification normally precedes contextCompaction completion,
                # but yield once for app-server versions that emit it immediately after.
                await asyncio.sleep(0)
            context_tokens = self._compact_context_tokens
            if context_tokens is None:
                runtime_context = self._runtime_context()
                if runtime_context:
                    context_tokens = int(runtime_context.get("input_tokens") or 0)
                    runtime_window = runtime_context.get("model_context_window")
                    if isinstance(runtime_window, int) and runtime_window > 0:
                        self._model_context_window = runtime_window
            result["context_tokens"] = context_tokens
            result["max_tokens"] = self._model_context_window
            return result
        except TimeoutError as exc:
            raise TimeoutError(
                f"Codex compact timed out after {CODEX_COMPACT_TIMEOUT_SECONDS:g}s "
                f"while waiting for {stage}"
            ) from exc
        finally:
            if self._compact_future is future:
                self._compact_future = None
            if self._compact_notifications is compact_notifications:
                self._compact_notifications = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _drain_compact_lifecycle(
        self,
        notifications: asyncio.Queue[dict],
    ) -> None:
        compact_turn_id: str | None = None
        while True:
            message = await notifications.get()
            method = message.get("method", "")
            turn_id = str(
                (((message.get("params") or {}).get("turn") or {}).get("id")) or ""
            )
            if method == "turn/started":
                compact_turn_id = turn_id
            elif method == "turn/completed":
                if compact_turn_id is None:
                    raise RuntimeError(
                        "Codex compact completed without a preceding turn/started"
                    )
                if self._lifecycle_belongs_to_turn(message, compact_turn_id):
                    return

    async def _scope_populated(self) -> bool:
        unit = self._scope_unit
        if not unit:
            return False
        systemctl = shutil.which("systemctl") or "systemctl"
        rc, stdout, stderr = await _run_process(
            systemctl, "--user", "show", unit,
            "-p", "LoadState", "-p", "ActiveState", "-p", "ControlGroup",
            "--no-pager",
            env=self._scope_env,
        )
        if rc:
            raise RuntimeError(stderr or f"systemctl show exited with code {rc}")
        state = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                state[key] = value
        if state.get("LoadState") == "not-found":
            return False
        control_group = state.get("ControlGroup", "")
        if control_group:
            events_path = Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.events"
            try:
                events = dict(
                    line.split(maxsplit=1)
                    for line in events_path.read_text().splitlines()
                    if " " in line
                )
            except OSError as exc:
                raise RuntimeError(
                    f"cannot verify Codex scope {unit}: {type(exc).__name__}: {exc}"
                ) from exc
            if "populated" in events:
                return events["populated"] == "1"
        return state.get("ActiveState") not in ("inactive", "failed", "")

    async def _signal_scope(self, signal_name: str) -> None:
        if not await self._scope_populated():
            return
        systemctl = shutil.which("systemctl") or "systemctl"
        rc, _, stderr = await _run_process(
            systemctl, "--user", "kill", f"--signal={signal_name}",
            "--kill-whom=all", self._scope_unit or "",
            env=self._scope_env,
        )
        if rc and await self._scope_populated():
            raise RuntimeError(
                stderr or f"systemctl kill {signal_name} exited with code {rc}"
            )

    async def _wait_scope_empty(self) -> None:
        async with asyncio.timeout(CODEX_PROCESS_TIMEOUT_SECONDS):
            while await self._scope_populated():
                await asyncio.sleep(0.05)

    async def _wait_owned_process(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        await asyncio.wait_for(
            asyncio.shield(proc.wait()),
            timeout=CODEX_PROCESS_TIMEOUT_SECONDS,
        )

    async def _disconnect_scoped(self, proc: asyncio.subprocess.Process | None) -> None:
        await self._signal_scope("TERM")
        try:
            if proc:
                await self._wait_owned_process(proc)
            await self._wait_scope_empty()
        except TimeoutError:
            await self._signal_scope("KILL")
            if proc:
                await self._wait_owned_process(proc)
            await self._wait_scope_empty()

    async def _disconnect_direct(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.shield(proc.wait()),
                    timeout=CODEX_PROCESS_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()

    async def _finalize_disconnect(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("Codex app-server disconnected"))
        self._pending_requests.clear()
        if self._compact_future and not self._compact_future.done():
            self._compact_future.set_exception(
                RuntimeError("Codex app-server disconnected during context compact")
            )
        await self.teardown_owned_pipes()
        self._proc = None
        self._scope_unit = None
        self._reader_task = None
        self._stderr_task = None
        self._active_turn_id = None
        self._clear_deferred_control()
        self._teardown_error = None

    async def disconnect(self) -> None:
        if self._terminal_reader_failure:
            await self._abort_oversized_transport()
            self._proc = None
            self._scope_unit = None
            self._reader_task = None
            self._stderr_task = None
            self._active_turn_id = None
            self._teardown_error = None
            return
        proc = self._proc
        if proc is None and self._scope_unit is None:
            if self._adopted_fds is not None or self._adopted_writer is not None:
                # An ADOPTED backend owns no Process, but it very much owns a running CLI:
                # returning here left it alive next to its replacement (found in impl review).
                self._disconnecting = True
                await self.teardown_adopted()
            return
        self._disconnecting = True
        try:
            if self._active_turn_id and proc and proc.returncode is None:
                await self.interrupt()
            if self._scope_unit:
                await self._disconnect_scoped(proc)
            elif proc:
                await self._disconnect_direct(proc)
            await self._finalize_disconnect()
        except BaseException as exc:
            self._teardown_error = f"{type(exc).__name__}: {exc}"
            raise

    async def _read_stdout(self) -> None:
        stream = self._out
        if stream is None:
            return
        try:
            while True:
                try:
                    raw = await stream.readline()
                except ValueError as exc:
                    error_text = str(exc)
                    if error_text not in CODEX_OVERSIZE_READLINE_ERRORS:
                        self._reader_failure = exc
                        raise
                    failure = CodexOversizedRecordError(
                        "Codex app-server emitted an oversized JSONL record; "
                        f"aborting the poisoned transport at the "
                        f"{CODEX_STREAM_LIMIT} byte limit"
                    )
                    self._reader_failure = failure
                    self._terminal_reader_failure = True
                    self._active_turn_id = None
                    logger.error("%s", failure)
                    for future in self._pending_requests.values():
                        if not future.done():
                            future.set_exception(failure)
                    if self._compact_future and not self._compact_future.done():
                        self._compact_future.set_exception(failure)
                    await self._abort_oversized_transport()
                    await self._notifications.put({
                        "method": "_process/exited",
                        "params": {
                            "returncode": getattr(self._proc, "returncode", None),
                            "stderr": sanitize_sensitive_text(self._last_stderr).strip(),
                            "reader_failure": str(failure),
                        },
                    })
                    return
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning("Codex app-server emitted invalid JSONL")
                    continue
                request_id = message.get("id")
                if request_id is not None and message.get("method"):
                    # Autonomous workers have no interactive approval/elicitation UI.
                    # `approvalPolicy=never` should prevent these requests; reject any
                    # unexpected one explicitly so the turn fails instead of deadlocking.
                    await self._write({
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": (
                                f"Orchestra does not implement client request "
                                f"{message.get('method')}"
                            ),
                        },
                    })
                    continue
                if request_id is not None:
                    future = self._pending_requests.get(request_id)
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(
                                CodexProtocolError("request", message.get("error") or {})
                            )
                        else:
                            future.set_result(message.get("result") or {})
                    continue
                if message.get("method"):
                    if message["method"] == "thread/tokenUsage/updated":
                        self._record_token_usage(message.get("params") or {})
                    self._complete_compaction_from_notification(message)
                    notifications = self._compact_notifications
                    if notifications is None:
                        notifications = self._notifications
                    await notifications.put(message)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._reader_failure is None:
                self._reader_failure = exc
            logger.exception("Codex app-server reader failed: %s", exc)
            if isinstance(exc, ValueError):
                raise
        finally:
            # ONE gate over the whole "the process died" story. A handover cancels this reader
            # on a process that is very much alive, so none of it may run: not the pending
            # futures, not the notification, and above all not `proc.wait()` — waiting for a
            # live CLI to exit stalled every handover until the shutdown timeout (#237 T1).
            if not self._handover_quiescing and not self._terminal_reader_failure:
                # An ADOPTED transport has no Process object at all (#230 T2): the CLI is not
                # our child. Its exit is then visible only as EOF on the pipe, which is why the
                # reason is worded without a code instead of pretending we can wait() on it.
                proc = self._proc
                returncode = await proc.wait() if proc is not None else None
                stderr_task = self._stderr_task
                if stderr_task is not None and stderr_task is not asyncio.current_task():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(stderr_task),
                            timeout=CODEX_PROCESS_TIMEOUT_SECONDS,
                        )
                    except TimeoutError:
                        stderr_task.cancel()
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.warning("Codex stderr drain failed during exit: %s", exc)
                stderr = sanitize_sensitive_text(self._last_stderr).strip()
                message = (
                    f"Codex app-server exited with code {returncode}" if proc is not None
                    else "Codex app-server closed the adopted pipe (no process: adopted transport)"
                )
                if stderr:
                    message = f"{message}: {stderr}"
                queued = getattr(self._notifications, "_queue", ())
                terminal_queued = False
                if self._reader_failure is not None and self._active_turn_id:
                    terminal_queued = any(
                        item.get("method") == "turn/completed"
                        and str(
                            (((item.get("params") or {}).get("turn") or {}).get("id"))
                            or ""
                        ) == self._active_turn_id
                        for item in queued
                    )
                    if terminal_queued and not self._terminal_reader_failure:
                        self._reader_failure = None
                reader_failure = self._reader_failure
                if reader_failure is not None and not terminal_queued:
                    self._active_turn_id = None
                if reader_failure is not None:
                    message = f"{message}; reader failure: {reader_failure}"
                error = RuntimeError(message)
                pending_error = (
                    reader_failure
                    if isinstance(reader_failure, CodexOversizedRecordError)
                    else error
                )
                for future in self._pending_requests.values():
                    if not future.done():
                        future.set_exception(pending_error)
                if self._compact_future and not self._compact_future.done():
                    self._compact_future.set_exception(pending_error)
                if not self._disconnecting and (
                    self._events_active
                    or self._active_turn_id
                    or reader_failure is not None
                    or returncode not in (None, 0)
                ) and not terminal_queued:
                    await self._notifications.put({
                        "method": "_process/exited",
                        "params": {
                            "returncode": returncode,
                            "stderr": stderr,
                            "reader_failure": str(reader_failure) if reader_failure else "",
                        },
                    })

    async def _abort_oversized_transport(self) -> None:
        """Stop only this app-server after JSONL framing becomes ambiguous."""
        if self._adopted_writer is not None or self._adopted_read_transport is not None:
            writer = self._adopted_writer
            read_transport = self._adopted_read_transport
            pid = self._adopted_pid
            started_at = self._adopted_started_at
            if writer is not None:
                with suppress(Exception):
                    writer.close()
            if read_transport is not None:
                with suppress(Exception):
                    read_transport.close()
            self._adopted_writer = None
            self._adopted_reader = None
            self._adopted_read_transport = None
            self._adopted_fds = None
            self._adopted_pid = None
            self._adopted_started_at = 0
            if pid:
                terminate_cli_process(pid, self.RUNTIME_LABEL, started_at)
            return

        with suppress(Exception):
            await self.teardown_owned_pipes()
        proc = self._proc
        if self._scope_unit:
            with suppress(Exception):
                await asyncio.wait_for(self._signal_scope("KILL"), timeout=1)
        if proc is not None and proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()

    def _record_token_usage(self, params: dict) -> None:
        usage = params.get("tokenUsage") or {}
        total = usage.get("total") or {}
        last = usage.get("last") or {}
        self._thread_usage_total = self._usage_breakdown(total)
        self._last_call_usage = self._usage_breakdown(last)
        context_tokens = last.get("totalTokens")
        if isinstance(context_tokens, int) and context_tokens >= 0:
            self._compact_context_tokens = context_tokens
        window = usage.get("modelContextWindow")
        if isinstance(window, int) and window > 0:
            self._model_context_window = window

    def _complete_compaction_from_notification(self, message: dict) -> bool:
        method = message.get("method", "")
        params = message.get("params") or {}
        thread_id = params.get("threadId")
        if thread_id and thread_id != self._thread_id:
            return False

        item = params.get("item") or {}
        completed = (
            method in ("context/compacted", "thread/compacted")
            or (
                method == "item/completed"
                and item.get("type") == "contextCompaction"
            )
        )
        if not completed:
            return False

        future = self._compact_future
        if future and not future.done():
            future.set_result({
                "ok": True,
                "thread_id": self._thread_id,
                "context_tokens": self._compact_context_tokens,
                "max_tokens": self._model_context_window,
            })
        return True

    def _convert_notification(self, message: dict) -> list[AgentEvent]:
        method = message.get("method", "")
        params = message.get("params") or {}

        if method == "thread/started":
            thread_id = ((params.get("thread") or {}).get("id") or params.get("threadId"))
            if not thread_id:
                return []
            self._thread_id = thread_id
            self._rollout_path = None
            return [AgentEvent(
                "status",
                f"codex thread={thread_id}",
                metadata={"session_id": thread_id},
            )]

        if method == "turn/started":
            turn_id = ((params.get("turn") or {}).get("id"))
            if turn_id:
                self._active_turn_id = turn_id
            return [AgentEvent("status", f"codex turn={turn_id} started")]

        if method == "thread/tokenUsage/updated":
            self._record_token_usage(params)
            return []

        if method == "error":
            error = params.get("error") or {}
            self._last_turn_error = error
            content = error.get("message") or "Codex error"
            if params.get("willRetry"):
                return [AgentEvent("status", f"codex reconnecting: {content}")]
            model_error = self._classify_error(error)
            if model_error == "rate_limit":
                content = f"rate_limit: {content}"
            return [AgentEvent("error", content, metadata={"model_error": model_error})]

        if method == "model/rerouted":
            return [AgentEvent("status", f"model rerouted: {json.dumps(params, ensure_ascii=False)}")]

        if method in ("context/compacted", "thread/compacted"):
            return [AgentEvent("status", "codex context compacted")]

        if method in (
            "item/reasoning/summaryTextDelta",
            "item/reasoning/textDelta",
            "item/plan/delta",
        ):
            activity = "plan" if method == "item/plan/delta" else "reasoning"
            return [AgentEvent(
                "thinking_stream",
                params.get("delta", ""),
                metadata={
                    "activity": activity,
                    "item_id": params.get("itemId", ""),
                },
            )]

        if method == "turn/plan/updated":
            return [AgentEvent("plan", json.dumps({
                "explanation": params.get("explanation"),
                "plan": params.get("plan") or [],
            }, ensure_ascii=False))]

        if method == "turn/diff/updated":
            return [AgentEvent(
                "turn_diff",
                params.get("diff", ""),
                metadata={"turn_id": params.get("turnId", "")},
            )]

        if method in (
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        ):
            return [AgentEvent(
                "tool_stream",
                params.get("delta", ""),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/commandExecution/terminalInteraction":
            return [AgentEvent(
                "tool_stream",
                params.get("stdin", ""),
                metadata={
                    "tool_use_id": params.get("itemId", ""),
                    "stream": "stdin",
                },
            )]

        if method == "item/fileChange/patchUpdated":
            return [AgentEvent(
                "tool_patch",
                json.dumps({"changes": params.get("changes") or []}, ensure_ascii=False),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/started":
            item = params.get("item") or {}
            item_id = str(item.get("id") or "")
            if item_id:
                self._started_items.add(item_id)
            return self._item_started(item)

        if method == "item/completed":
            return self._item_completed(params.get("item") or {})

        if method == "item/mcpToolCall/progress":
            return [AgentEvent(
                "tool_stream",
                params.get("message", ""),
                metadata={"tool_use_id": params.get("itemId", "")},
            )]

        if method == "item/agentMessage/delta":
            return [AgentEvent("stream", params.get("delta", ""))]

        if method in ("warning", "guardianWarning", "deprecationNotice", "configWarning"):
            content = (
                params.get("message")
                or params.get("summary")
                or "Codex warning"
            )
            details = params.get("details")
            if details:
                content = f"{content}\n{details}"
            return [AgentEvent("warning", content)]

        if method == "mcpServer/startupStatus/updated":
            name = params.get("name") or "unknown"
            status = params.get("status") or "unknown"
            if status in ("starting", "ready"):
                return []
            detail = params.get("error") or params.get("failureReason") or ""
            content = f"codex mcp {name}: {status}"
            if detail:
                content = f"{content} — {detail}"
            event_type = "warning" if status in ("failed", "cancelled") else "status"
            return [AgentEvent(event_type, content)]

        if method in ("hook/started", "hook/completed"):
            run = params.get("run") or {}
            phase = "started" if method.endswith("/started") else "completed"
            label = run.get("eventName") or run.get("id") or "hook"
            status = run.get("status") or phase
            duration = run.get("durationMs")
            suffix = f" · {duration}ms" if duration is not None else ""
            return [AgentEvent("status", f"codex hook {label}: {status}{suffix}")]

        if method in ("item/autoApprovalReview/started", "item/autoApprovalReview/completed"):
            phase = "started" if method.endswith("/started") else "completed"
            return [AgentEvent("status", f"codex approval review {phase}")]

        if method == "model/safetyBuffering/updated" and params.get("showBufferingUi"):
            reasons = ", ".join(params.get("reasons") or [])
            return [AgentEvent("warning", f"Codex safety buffering: {reasons or params.get('model', '')}")]

        if method == "turn/completed":
            turn = params.get("turn") or {}
            self._active_turn_id = None
            # A terminal lifecycle event proves that the poisoned record was not the
            # turn terminator; later clean EOF must not replay a stale failure.
            self._reader_failure = None
            return self._turn_completed(turn)

        if method == "_process/exited":
            self._active_turn_id = None
            reader_failure = params.get("reader_failure") or ""
            model_error = "reader_failure" if reader_failure else "server_error"
            normalized_usage = TurnUsage(
                AggregateUsage.normalized(),
                current_context(
                    None,
                    self._model_context_window,
                    unknown_reason="Codex exited before reporting current context",
                ),
            )
            return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
                "session_id": self._thread_id,
                "ok": False,
                "stop_reason": f"process_exit_{params.get('returncode')}",
                "returncode": params.get("returncode"),
                "stderr_tail": params.get("stderr", ""),
                "model_error": model_error,
                "errors": [model_error],
                "reader_failure": reader_failure,
                "cost_usd": 0,
                **normalized_usage.metadata(),
            }, usage=normalized_usage)]

        return []

    def _item_started(self, item: dict) -> list[AgentEvent]:
        item_type = item.get("type", "")
        item_id = str(item.get("id") or "")
        if item_type == "commandExecution":
            payload = {
                "command": item.get("command", ""),
                "cwd": item.get("cwd", self.cwd),
                "command_actions": item.get("commandActions") or [],
            }
            return [self._tool_use(
                "Bash",
                json.dumps(payload, ensure_ascii=False),
                item_id,
            )]
        if item_type == "fileChange":
            payload = {
                "changes": item.get("changes") or [],
                "status": item.get("status", ""),
            }
            return [self._tool_use(
                "FileChange",
                json.dumps(payload, ensure_ascii=False),
                item_id,
            )]
        if item_type == "mcpToolCall":
            server, tool = item.get("server", ""), item.get("tool", "")
            name = f"mcp__{server}__{tool}" if server else tool
            return [self._tool_use(
                name,
                _tool_arguments_json(item.get("arguments")),
                item_id,
                short_name=tool,
            )]
        if item_type == "dynamicToolCall":
            return [self._tool_use(
                item.get("tool", "tool"),
                _tool_arguments_json(item.get("arguments")),
                item_id,
            )]
        if item_type == "webSearch":
            return [self._tool_use(
                "WebSearch",
                json.dumps({
                    "query": item.get("query", ""),
                    "action": item.get("action"),
                }, ensure_ascii=False),
                item_id,
            )]
        if item_type == "imageView":
            return [self._tool_use(
                "ViewImage",
                json.dumps({"file_path": item.get("path", "")}, ensure_ascii=False),
                item_id,
            )]
        if item_type == "imageGeneration":
            return [self._tool_use(
                "ImageGeneration",
                json.dumps({"status": item.get("status", "")}, ensure_ascii=False),
                item_id,
            )]
        if item_type == "sleep":
            return [self._tool_use(
                "Sleep",
                json.dumps({"duration_ms": item.get("durationMs", 0)}),
                item_id,
            )]
        if item_type == "collabAgentToolCall":
            return self._collab_events(item, completed=False)
        if item_type == "contextCompaction":
            return [AgentEvent("status", "codex compacting context")]
        return []

    def _item_completed(self, item: dict) -> list[AgentEvent]:
        item_type = item.get("type", "")
        item_id = str(item.get("id") or "")
        unseen = bool(item_id and item_id not in self._started_items)
        events: list[AgentEvent] = []

        if item_type == "agentMessage":
            text = item.get("text", "")
            if text:
                events.append(AgentEvent("text", text))
        elif item_type == "reasoning":
            parts = item.get("summary") or item.get("content") or []
            text = "\n".join(str(part) for part in parts if part)
            if text:
                events.append(AgentEvent("thinking", text))
        elif item_type == "plan":
            if item.get("text"):
                events.append(AgentEvent("thinking", item["text"]))
        elif item_type == "commandExecution":
            if unseen:
                events.extend(self._item_started(item))
            output = item.get("aggregatedOutput")
            exit_code = item.get("exitCode")
            failed = exit_code is not None and exit_code != 0
            if output is not None or failed:
                events.append(AgentEvent(
                    "tool_result",
                    str(output) if output is not None else f"command exited with code {exit_code}",
                    metadata={
                        "exit_code": exit_code,
                        "tool_use_id": item_id,
                        "tool_name": "Bash",
                        "is_error": failed,
                    },
                ))
        elif item_type == "fileChange":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "status": item.get("status", ""),
                    "files": len(item.get("changes") or []),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "mcpToolCall":
            server, tool = item.get("server", ""), item.get("tool", "")
            name = f"mcp__{server}__{tool}" if server else tool
            if unseen:
                events.append(self._tool_use(
                    name,
                    _tool_arguments_json(item.get("arguments")),
                    item_id,
                    short_name=tool,
                ))
            if item.get("result") is not None:
                events.append(AgentEvent(
                    "tool_result",
                    self._result_text(item["result"]),
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": name,
                        "is_error": False,
                    },
                ))
            if item.get("error"):
                error = item["error"]
                error_text = (
                    error.get("message", str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
                events.append(AgentEvent(
                    "tool_result",
                    error_text,
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": name,
                        "is_error": True,
                    },
                ))
                events.append(AgentEvent(
                    "error",
                    error_text,
                ))
        elif item_type == "dynamicToolCall":
            if unseen:
                events.extend(self._item_started(item))
            content = item.get("contentItems")
            failed = item.get("success") is False or item.get("status") == "failed"
            if content is not None or failed:
                events.append(AgentEvent(
                    "tool_result",
                    self._result_text(content) if content is not None else json.dumps({
                        "status": item.get("status"),
                        "success": item.get("success"),
                    }),
                    metadata={
                        "tool_use_id": item_id,
                        "tool_name": item.get("tool", "tool"),
                        "is_error": failed,
                    },
                ))
        elif item_type == "webSearch":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "query": item.get("query", ""),
                    "action": item.get("action"),
                    "status": "completed",
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "imageView":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "status": "viewed",
                    "file_path": item.get("path", ""),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "imageGeneration":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({
                    "result": item.get("result"),
                    "saved_path": item.get("savedPath"),
                    "status": item.get("status", ""),
                    "revised_prompt": item.get("revisedPrompt"),
                }, ensure_ascii=False),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "sleep":
            if unseen:
                events.extend(self._item_started(item))
            events.append(AgentEvent(
                "tool_result",
                json.dumps({"status": "completed", "duration_ms": item.get("durationMs", 0)}),
                metadata={"tool_use_id": item_id},
            ))
        elif item_type == "collabAgentToolCall":
            events.extend(self._collab_events(item, completed=True))
        elif item_type == "subAgentActivity":
            sub_id = item.get("agentThreadId", "")
            kind = item.get("kind", "activity")
            agent_path = item.get("agentPath", "")
            events.append(AgentEvent(
                "subagent_progress",
                f"{agent_path} | type=codex | id={sub_id} | tool={kind}",
                metadata={"subagent_id": sub_id, "status": kind, "phase": "progress"},
            ))
        elif item_type == "contextCompaction":
            events.append(AgentEvent("status", "codex context compacted"))
        elif item_type in ("enteredReviewMode", "exitedReviewMode"):
            phase = "entered" if item_type == "enteredReviewMode" else "exited"
            events.append(AgentEvent("review", json.dumps({
                "phase": phase,
                "review": item.get("review", ""),
            }, ensure_ascii=False)))

        if item_id:
            self._started_items.discard(item_id)
        return events

    def _collab_events(self, item: dict, *, completed: bool) -> list[AgentEvent]:
        tool = item.get("tool", "")
        receiver_ids = item.get("receiverThreadIds") or [item.get("id", "")]
        agent_states = item.get("agentsStates") or {}
        events = []
        for sub_id in receiver_ids:
            prompt = item.get("prompt") or ""
            if tool == "spawnAgent" and prompt:
                self._subagent_descriptions[sub_id] = prompt
            description = prompt or self._subagent_descriptions.get(sub_id) or tool
            agent_state = agent_states.get(sub_id) or {}
            agent_status = agent_state.get("status", "")
            summary = agent_state.get("message") or ""
            metadata = {
                "subagent_id": sub_id,
                "tool_use_id": item.get("id", ""),
                "description": description,
                "task_type": "codex",
                "status": agent_status or item.get("status", ""),
                "summary": summary,
            }
            if tool == "spawnAgent" and not completed:
                metadata["phase"] = "start"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')}"
                )
                events.append(AgentEvent("subagent_start", content, metadata))
            elif completed and (
                tool == "closeAgent"
                or agent_status in {"interrupted", "completed", "errored", "shutdown", "notFound"}
            ):
                metadata["phase"] = "end"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')} | status={metadata['status']}"
                    f"{' | ' + summary[:500] if summary else ''}"
                )
                events.append(AgentEvent("subagent_end", content, metadata))
            else:
                metadata["phase"] = "progress"
                content = (
                    f"{description} | type=codex | id={sub_id} | "
                    f"tool_use_id={item.get('id', '')} | tool={tool}"
                )
                events.append(AgentEvent("subagent_progress", content, metadata))
        return events

    def _turn_completed(self, turn: dict) -> list[AgentEvent]:
        status = turn.get("status", "failed")
        error = turn.get("error") or self._last_turn_error or {}
        turn_id = str(turn.get("id") or "")
        deferred_control = (
            dict(self._deferred_control)
            if self._deferred_control
            and self._deferred_control_turn_id == turn_id
            else None
        )
        if deferred_control and status == "interrupted":
            ok = False
            model_error = ""
            stop_reason = "interrupted"
        elif deferred_control:
            ok = False
            model_error = "error"
            stop_reason = "deferred_interrupt_not_honored"
        else:
            ok = status == "completed"
            model_error = "" if ok else self._classify_error(error)
            stop_reason = {
                "completed": "end_turn",
                "interrupted": "interrupted",
                "failed": "error",
            }.get(status, status)

        totals = self._thread_usage_total or self._runtime_totals() or {}
        delta = _usage_delta(totals, self._usage_baseline)
        turn_input = delta["input_tokens"]
        turn_cached = delta["cached_input_tokens"]
        turn_cache_write = delta["cache_write_input_tokens"]
        turn_output = delta["output_tokens"]
        context = self._last_call_usage or self._runtime_context()
        if context:
            ctx_tokens = int(context.get("input_tokens") or 0)
            ctx_window = int(
                context.get("model_context_window") or self._model_context_window
            )
        else:
            ctx_tokens = None
            ctx_window = self._model_context_window
        normalized_usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=turn_input,
                output_tokens=turn_output,
                cache_read_tokens=turn_cached,
                cache_create_tokens=turn_cache_write,
            ),
            current_context(
                ctx_tokens,
                ctx_window,
                semantics_known=context is not None,
                unknown_reason="Codex did not report last-call context",
            ),
        )
        cost_error = ""
        try:
            cost = _codex_cost(
                self.model, turn_input, turn_cached, turn_cache_write, turn_output
            )
        except Exception as cost_exception:
            cost = 0.0
            cost_error = f"{type(cost_exception).__name__}: {cost_exception}"
            logger.error("Codex usage unaccounted: %s", cost_error)
        metadata = {
            "event_id": turn_id,
            "session_id": self._thread_id,
            "ok": ok,
            "stop_reason": stop_reason,
            "cost_usd": cost,
            "cost_usd_cached": cost,
            "cost_is_delta": True,
            "cache_hit": int(turn_cached * 100 / turn_input) if turn_input else 0,
            **normalized_usage.metadata(),
            "model_error": model_error,
            "errors": [model_error] if model_error else [],
        }
        events = []
        if deferred_control:
            metadata["deferred_control"] = deferred_control
            if status != "interrupted":
                events.append(AgentEvent(
                    "error",
                    f"Deferred interrupt ended with native status {status!r}",
                    {"model_error": "error"},
                ))
        if not ok and error.get("message"):
            events.append(AgentEvent("error", error["message"], {"model_error": model_error}))
        if cost_error:
            metadata["cost_unaccounted"] = True
            metadata["cost_error"] = cost_error
            events.append(AgentEvent(
                "warning",
                f"Codex usage unaccounted: {cost_error}",
                {"cost_unaccounted": True, "cost_error": cost_error},
            ))
        events.append(AgentEvent(
            "turn_end",
            f"stop_reason={stop_reason}",
            metadata=metadata,
            usage=normalized_usage,
        ))
        self._last_turn_error = {}
        if deferred_control:
            self._clear_deferred_control()
        return events

    @staticmethod
    def _usage_breakdown(data: dict) -> dict[str, int]:
        return {
            "input_tokens": max(0, int(data.get("inputTokens") or 0)),
            "cached_input_tokens": max(0, int(data.get("cachedInputTokens") or 0)),
            "cache_write_input_tokens": max(0, int(data.get("cacheWriteInputTokens") or 0)),
            "output_tokens": max(0, int(data.get("outputTokens") or 0)),
        }

    @staticmethod
    def _classify_error(error: dict) -> str:
        info = error.get("codexErrorInfo")
        if isinstance(info, dict) and any(key in info for key in (
            "httpConnectionFailed",
            "responseStreamConnectionFailed",
            "responseStreamDisconnected",
            "responseTooManyFailedAttempts",
        )):
            return "server_error"
        if info in ("serverOverloaded", "internalServerError"):
            return "server_error"
        if info in ("usageLimitExceeded", "sessionBudgetExceeded"):
            return "rate_limit"
        if info == "contextWindowExceeded":
            return "context_window"
        message = str(error.get("message") or "").lower()
        if any(part in message for part in (
            "connection refused", "stream disconnected", "network error",
            "tls", "unexpected eof", "error sending request",
        )):
            return "server_error"
        return "error"

    @staticmethod
    def _tool_use(name: str, summary: str, item_id: str,
                  short_name: str | None = None) -> AgentEvent:
        if item_id:
            try:
                payload = json.loads(summary)
            except (json.JSONDecodeError, TypeError):
                payload = None
            if isinstance(payload, dict):
                payload["_codex_item_id"] = item_id
                summary = json.dumps(payload, ensure_ascii=False)
        short = short_name or name
        return AgentEvent(
            "tool_use",
            f"{name}: {summary}",
            metadata={
                "tool_name": name,
                "short_name": short,
                "tool_use_id": item_id,
            },
        )

    @staticmethod
    def _result_text(result) -> str:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(str(block.get("text", block)))
                    else:
                        parts.append(str(block))
                return "\n".join(parts)[:20_000]
            return json.dumps(result, ensure_ascii=False)[:20_000]
        if isinstance(result, list):
            return "\n".join(
                block.get("text", str(block)) if isinstance(block, dict) else str(block)
                for block in result
            )[:20_000]
        return str(result)[:20_000]

    def _runtime_context(self) -> dict[str, int] | None:
        if not self._thread_id:
            return None
        if self._rollout_path is None or not self._rollout_path.exists():
            # #224: os.environ здесь — окружение РОДИТЕЛЬСКОГО процесса Orchestra, а
            # дочерний env отдаётся только в create_subprocess_exec. Спрашивать надо
            # собственный каталог бэкенда, иначе rollout не находится и учёт токенов с
            # context% ломаются МОЛЧА (None неотличим от «данных ещё нет»).
            root = Path(self._codex_home or _base_codex_home()).expanduser()
            sessions = root / "sessions"
            try:
                matches = list(sessions.glob(f"**/*{self._thread_id}.jsonl"))
            except OSError:
                matches = []
            if not matches:
                return None
            self._rollout_path = max(matches, key=lambda p: p.stat().st_mtime)
        return _read_rollout_context(self._rollout_path)

    def _runtime_totals(self) -> dict[str, int] | None:
        # Locate the rollout through the same path/cache as context extraction.
        self._runtime_context()
        if self._rollout_path is None:
            return None
        return _read_rollout_totals(self._rollout_path)

    @staticmethod
    def _toml_str(s: str) -> str:
        """TOML basic string. Управляющие символы экранируем ЯВНО: значения и имена
        приходят из данных (`mcp_servers_custom` со спавна), а сырой перевод строки
        внутри строки делает config.toml неразбираемым — то есть роняет старт Codex."""
        out = s.replace("\\", "\\\\").replace('"', '\\"')
        out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        # `>= " "` мало: U+007F (DEL) эту проверку проходит, но TOML его запрещает, и
        # tomllib отвергает файл целиком — Codex не стартует. Проверено прогоном:
        # NUL/BEL/US разбираются после \u-экранирования, DEL — нет.
        out = "".join(
            ch if " " <= ch < "\x7f" else f"\\u{ord(ch):04x}" if ch < "\xa0" else ch
            for ch in out
        )
        return '"' + out + '"'

    @classmethod
    def _toml_key(cls, s: str) -> str:
        if any("\ud800" <= ch <= "\udfff" for ch in s):
            # UTF-8 такие точки не кодирует: без явного отказа падала бы запись файла
            # где-то ниже, без имени виновника.
            raise ValueError(f"TOML key contains a lone surrogate: {s!r}")
        """Ключ таблицы TOML — ВСЕГДА в кавычках: bare key допускает только [A-Za-z0-9_-],
        а имена серверов и переменных мы не контролируем."""
        return cls._toml_str(s)

    def _codex_command(self) -> list[str]:
        """Полная командная строка Codex — отдельным методом, чтобы её можно было
        проверить тестом целиком (#224). argv публичен: `/proc/<pid>/cmdline` читает
        процесс любого uid, поэтому «в нём нет значений» должно быть утверждением о
        ВСЕЙ строке, а не о той её части, которую мы помним."""
        cmd = [CODEX_BIN]
        cmd += ["-c", f"model_reasoning_effort={self._toml_str(self.reasoning_effort)}"]
        # Every CodexBackend here is Orchestra-managed. Delegation must use the tracked
        # Orchestra spawn_worker path, never invisible native agents in this checkout.
        cmd += ["-c", "features.multi_agent=false"]
        # Managed workers are research/implementation agents, so expose current web
        # results explicitly instead of inheriting a user's cached/disabled setting.
        cmd += ["-c", 'web_search="live"']
        for arg in self._mcp_config_args():
            cmd += ["-c", arg]
        cmd += ["app-server", "--stdio"]
        return cmd

    def _mcp_config_args(self) -> list[str]:
        """Больше НИЧЕГО не кладём в argv (#224).

        Раньше отсюда уходили `-c mcp_servers.<name>.env={...}` со ЗНАЧЕНИЯМИ секретов —
        а argv читает процесс любого uid. Весь конфиг, включая env, теперь собирается в
        `$CODEX_HOME/config.toml` с правами 600 (`_prepare_codex_home`). Держать вторую
        копию в argv нельзя: два владельца одной настройки молча разъезжаются.
        """
        return []

    def _mcp_servers_toml(self) -> str:
        """Секции `[mcp_servers.*]` для config.toml — единственный носитель конфига MCP."""
        blocks: list[str] = []
        for name, cfg in self._mcp_servers.items():
            command = cfg.get("command")
            url = cfg.get("url")
            if not command and not url:
                continue
            # Имя сервера и ключи env приходят ИЗ ДАННЫХ (`mcp_servers_custom` со спавна),
            # поэтому идут в TOML как КЛЮЧИ В КАВЫЧКАХ. Сырая подстановка позволяла закрыть
            # секцию и открыть свою — либо, как минимум, сделать конфиг неразбираемым,
            # то есть уронить старт Codex.
            key = self._toml_key(str(name))
            lines = [f"[mcp_servers.{key}]", "enabled = true"]
            if command:
                lines.append(f"command = {self._toml_str(str(command))}")
                srv_args = cfg.get("args") or []
                lines.append(
                    "args = [" + ", ".join(self._toml_str(str(a)) for a in srv_args) + "]"
                )
            else:
                lines.append(f"url = {self._toml_str(str(url))}")
            enabled_tools = cfg.get("enabled_tools")
            if name == "orchestra" and enabled_tools is None:
                enabled_tools = _orchestra_full_mcp_tools()
            if enabled_tools is not None:
                lines.append(
                    "enabled_tools = ["
                    + ", ".join(self._toml_str(str(t)) for t in enabled_tools)
                    + "]"
                )
            env = cfg.get("env") or {}
            if command and env:
                lines.append("")
                lines.append(f"[mcp_servers.{key}.env]")
                lines.extend(
                    f"{self._toml_key(str(k))} = {self._toml_str(str(v))}"
                    for k, v in env.items()
                )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _trusted_project_toml(self) -> str:
        """Trust only this backend's canonical cwd in its private CODEX_HOME.

        Managed Codex runs are created for an Orchestra-owned project/worktree.  Without
        this entry Codex deliberately disables that checkout's project-local `.codex`
        config, hooks, and rules.  Copying the base config's whole `[projects]` table is
        still forbidden: it would grant one agent trust in unrelated checkouts.
        """
        project = str(Path(self.cwd).expanduser().resolve())
        return (
            f"[projects.{self._toml_key(project)}]\n"
            'trust_level = "trusted"'
        )

    def _managed_codex_home_path(self) -> Path | None:
        if not self._mcp_servers:
            return None
        session_id = (self._mcp_servers.get("orchestra", {}).get("env") or {}).get(
            "ORCHESTRA_SESSION_ID"
        )
        # Fail loud: анонимный запасной путь давал бы на каждом коннекте НОВЫЙ каталог,
        # то есть тихо терял thread-id и ломал resume.
        if not session_id or not _SAFE_HOME_KEY.match(session_id):
            raise ValueError(
                "CodexBackend requires a well-formed ORCHESTRA_SESSION_ID in the trusted "
                f"'orchestra' MCP server env; got {session_id!r}"
            )
        return _CODEX_HOME_ROOT / session_id

    def _prepare_codex_home(self) -> Path:
        """Собрать приватный `CODEX_HOME` этого агента и вернуть путь.

        СОБРАТЬ, а не скопировать базовый: копия затащила бы глобальные MCP-серверы
        (со своими токенами) и `[projects.*]` в конфиг каждого воркера, в обход отбора
        в `runtime_registry`. Переносим из базового только разрешённые скаляры.
        """
        home = self._managed_codex_home_path()
        if home is None:
            # Нечего изолировать: без MCP-серверов нет ни конфига, ни секретов в argv,
            # и подменить идентичность нечем — env-блока не существует.
            # ОСТАТОЧНЫЙ РИСК, названный явно: такой бэкенд работает на ОБЩЕМ home и видит
            # глобальные серверы из ~/.codex/config.toml. Managed-путь сюда не приходит —
            # `_make_mcp_config` всегда кладёт сервер `orchestra`, — поэтому ветка
            # достижима только при конструировании бэкенда в обход менеджера.
            self._codex_home = _base_codex_home()
            return self._codex_home
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(_CODEX_HOME_ROOT, 0o700)
        os.chmod(home, 0o700)

        # `sessions/` — СИМЛИНК на общий каталог, а не свой пустой.
        # Rollout'ы адресуются thread-id, а не агентом, и в них же лежит учёт токенов.
        # Свой пустой каталог означал бы: у всех живых тредов (336 файлов на момент
        # правки) пропадает `thread/resume` и молча обнуляется context% — то есть
        # изоляция конфига оплачивалась бы потерей истории. Секреты живут в config.toml,
        # он приватный; журналы ходов секретами не являются и делятся как раньше.
        sessions = home / "sessions"
        base_sessions = _base_codex_home() / "sessions"
        base_sessions.mkdir(parents=True, exist_ok=True)
        if sessions.is_symlink():
            # Протухшую или битую ссылку ЧИНИМ, а не оставляем: она указывает в никуда
            # молча, и симптомом будет «resume перестал работать», а не ошибка здесь.
            try:
                stale = sessions.resolve(strict=True) != base_sessions.resolve()
            except OSError:
                stale = True
            if stale:
                sessions.unlink()
        elif sessions.is_dir() and not any(sessions.iterdir()):
            sessions.rmdir()
        if not sessions.exists() and not sessions.is_symlink():
            sessions.symlink_to(base_sessions)

        # Подписочная авторизация: СИМЛИНК на боевой auth.json. Копия протухнет при
        # перелогине, а без него app-server не авторизуется вовсе (проверено прогоном).
        auth = home / "auth.json"
        base_auth = _base_codex_home() / "auth.json"
        if not auth.is_symlink() and base_auth.exists():
            auth.unlink(missing_ok=True)
            auth.symlink_to(base_auth)

        parts = []
        carried = _carried_base_scalars()
        if carried:
            parts.append(carried)
        parts.append(self._trusted_project_toml())
        servers = self._mcp_servers_toml()
        if servers:
            parts.append(servers)
        # Через временный файл + os.replace: коннект, попавший на середину записи,
        # прочитал бы ОБРЕЗАННЫЙ config.toml и стартовал без части серверов — тихий отказ.
        _write_private(home / "config.toml", "\n\n".join(parts) + "\n")

        self._codex_home = home
        return home

    def _refresh_managed_config_sha256(self) -> str:
        """Rewrite the desired managed config and return its content identity."""
        home = self._prepare_codex_home()
        return hashlib.sha256((home / "config.toml").read_bytes()).hexdigest()

    async def _reload_stale_managed_config_before_turn(self) -> None:
        """Reconnect an idle managed app-server when its launch config is stale.

        Codex reads `config.toml` when the app-server starts.  Merely rewriting the file
        does not update an already-running worker, and restart adoption intentionally keeps
        those processes alive.  Reconnect here preserves the thread id through
        `thread/resume` while making the next turn use current context/config settings.
        """
        if self._managed_codex_home_path() is None:
            return
        desired = await _run_home_io(self._refresh_managed_config_sha256)
        if desired == self._loaded_config_sha256:
            return
        thread_id = self._thread_id
        logger.info(
            "reconnecting Codex before idle turn to load current managed config: "
            "thread=%s old=%s new=%s",
            thread_id,
            (self._loaded_config_sha256 or "unknown")[:12],
            desired[:12],
        )
        await self.disconnect()
        await self.connect()
        if self._thread_id != thread_id:
            raise RuntimeError(
                "Codex config refresh resumed a different thread: "
                f"requested={thread_id}, returned={self._thread_id}"
            )

    def _build_env(self) -> dict:
        env = dict(os.environ)
        env.update(self._mcp_env)
        # #224: процесс обязан стартовать в ТОМ ЖЕ home, для которого собран config.toml.
        # Иначе argv чист, конфиг верен, а воркер работает на общем каталоге — тихий отказ.
        env["CODEX_HOME"] = str(self._codex_home or self._prepare_codex_home())
        # Codex, Claude, Cursor, and Orchestra intentionally share the proxy selected in
        # Orchestra's .env. The launcher wrapper also reloads that file, but preserving the
        # inherited values keeps direct CODEX_BIN deployments consistent and testable.
        return env
