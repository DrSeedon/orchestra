#!/usr/bin/env python3
"""Приёмка русского интерфейса ПО ОТРИСОВАННЫМ ЭКРАНАМ.

Пустой grep по исходникам ничего не доказывает: норма (подп. «л» п. 5 ПП РФ № 1236)
говорит о том, что видит пользователь. Поэтому здесь поднимается настоящий сервер,
браузер проходит по экранам, и с КАЖДОГО снимается видимый текст плюс подписи
title/placeholder/aria-label. Остаток латиницы после вычета имён собственных,
путей и идентификаторов — находка.

Отрицательный контроль обязателен и встроен: перед сбором в каждый экран вставляется
заведомо непереведённая надпись, и если проверка её НЕ находит — экран объявляется
недоказанным. Без этого зелёный результат не отличим от сломанного сборщика.

    python3 .orchestra/tasks/V-584/audit_screens.py            # русская локаль
    python3 .orchestra/tasks/V-584/audit_screens.py --lang en  # контрольный прогон
    python3 .orchestra/tasks/V-584/audit_screens.py --json отчёт.json --shots каталог/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

USER = "auditor"
PASSWORD = "audit-pass"

# Имена собственные, единицы и общепринятые сокращения. Норма требует русский
# интерфейс, а не транслитерацию марок: `Orchestra`, `Claude`, `Codex` остаются.
ALLOWED = {
    # продукты, поставщики, инструменты
    "orchestra", "claude", "codex", "openrouter", "telegram", "git", "github",
    "grok", "gpt", "opus", "sonnet", "haiku", "fable", "luna", "astra", "sol",
    "harness", "worktree", "worktrees",
    "spark", "terra", "anthropic", "openai", "playwright", "python", "uvicorn",
    "sqlite", "fastapi", "tailwind", "chrome", "chromium", "linux", "macos",
    "windows", "perplexity", "brave", "serpapi", "marzban", "yougile", "pandoc",
    "serena", "mailru", "kesha", "aperant", "max", "pro", "free", "plus",
    # названия инструментов агента — идентификаторы протокола, не надписи
    "bash", "read", "write", "edit", "glob", "grep", "todowrite", "notebookedit",
    "websearch", "webfetch", "toolsearch", "askuserquestion", "sendmessage",
    "review", "task", "agent", "sleep", "filechange", "viewimage",
    "imagegeneration", "mcp", "cli", "sdk", "api", "sse", "http", "https",
    "url", "json", "html", "css", "js", "ui", "id", "ttl", "ram", "cpu", "gpu",
    "db", "sql", "tg", "vps", "ssh", "ip", "dns", "png", "jpg", "svg", "webp",
    "pdf", "md", "txt", "csv", "yaml", "toml", "env", "utf",
    # единицы и служебные
    "k", "m", "g", "b", "kb", "mb", "gb", "tb", "ms", "s", "h", "d", "usd",
    "eur", "rub", "px", "em", "rem", "vh", "vw", "ru", "en", "ok", "wip",
    "ua", "am", "pm", "utc", "gmt", "v", "x", "n", "a", "i", "e", "t",
}

# Куски экрана, которые интерфейсом не являются: содержимое диалога модели,
# код, пути и идентификаторы. Норма относится к интерфейсу программы.
SKIP_SELECTORS = [
    ".markdown-body",          # текст, написанный моделью
    "pre", "code", "textarea",
    ".font-mono",              # ветки, идентификаторы сессий
    "#file-tree",              # пути файлов
    "#file-preview-path", "#file-preview-content",
    ".grep-code", ".grep-meta", ".diff-line", ".diff-file",
    ".codex-search-query",
    # Аргументы вызова и результат инструмента пишет модель, а не интерфейс:
    # норма про интерфейс, содержимое диалога агента под неё не подпадает.
    ".compact-preview", ".compact-result",
    ".tool-argument-label", ".tool-argument-value",
    ".sf-file-item",           # имена и пути отправленных файлов
    ".codex-live-thinking-body", ".codex-plan-explanation", ".codex-activity-body",
    ".sa-body",                # вывод субагента
    "[data-i18n-skip]",
    "#lang-switch",            # сам переключатель: RU/EN — коды языков
]

# Для ПОДПИСЕЙ (title/placeholder/aria-label/alt) список короче: `textarea`, `pre` и
# `code` прячут набранный текст и код, но их собственные подсказки — это интерфейс.
# Замер по месту: `textarea` в общем списке скрыл непереведённый placeholder поля
# чата, и прогон объявил экран чистым, пока тот же дефект не нашёл тест механики.
ATTR_SKIP_SELECTORS = [
    sel for sel in SKIP_SELECTORS if sel not in {"pre", "code", "textarea"}
]

# Из текста вычищается всё, что надписью не является, ДО поиска латиницы.
NOT_A_LABEL = [
    re.compile(r"https?://\S+"),                    # ссылки
    re.compile(r"[~.]?/[\w./@-]+"),                 # пути
    re.compile(
        r"\b[\w-]+\.(?:py|js|ts|json|md|html|css|yaml|yml|toml|sh|sql|txt|log|db"
        r"|png|jpe?g|gif|webp|svg|ico|pdf|zip|csv|tsv|ini|cfg|lock|xml)\b"
    ),
    re.compile(r"\b[\w-]+\.(?:org|com|net|ru|io|ai|dev|рф)\b"),   # домены
    re.compile(r"\*\*?[/.][^\s]*"),                                 # glob-образцы
    re.compile(r"\b\w*_\w[\w_]*\b"),                # snake_case: типы событий, ключи
    re.compile(r"\b[a-z]+[A-Z]\w*\b"),              # camelCase: имена в коде
    re.compile(r"\b[A-Za-z]*\d[\w.-]*\b"),          # версии, модели, идентификаторы с цифрами
    re.compile(r"#[\w-]+"),                         # ссылки на задачи: #V-584
    re.compile(r"\b[0-9a-f]{7,40}\b"),              # хеши коммитов
    re.compile(r"\b\w+@[\w.-]+\b"),                 # почта
]

# Имена агентов и учётной записи этого стенда — данные, которые сам стенд и завёл.
# Они попадают внутрь переведённых подписей («Сообщение для audit-orch…»), поэтому
# вычитаются по точному значению, а не общим правилом: общее правило спрятало бы
# настоящую надпись с дефисом.
FIXTURE_NAMES = ("audit-orch", "audit-worker", USER)

WORD = re.compile(r"[A-Za-z]{1,}(?:['’][A-Za-z]+)?")

CONTROL_TEXT = "Untranslated control caption"

COLLECT_JS = r"""
([skipSelectors, attrSkipSelectors]) => {
  const out = [];
  const visible = (el) => {
    if (!el || !el.getClientRects) return false;
    if (el.getClientRects().length === 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
  };
  const matches = (el, list) => list.some((sel) => {
    try { return el.closest(sel) !== null; } catch (e) { return false; }
  });
  const skipped = (el) => matches(el, skipSelectors);
  const attrSkipped = (el) => matches(el, attrSkipSelectors);
  const where = (el) => {
    const parts = [];
    for (let node = el; node && node.tagName && parts.length < 4; node = node.parentElement) {
      let step = node.tagName.toLowerCase();
      if (node.id) { parts.unshift(step + '#' + node.id); break; }
      if (node.className && typeof node.className === 'string') {
        const first = node.className.trim().split(/\s+/)[0];
        if (first) step += '.' + first;
      }
      parts.unshift(step);
    }
    return parts.join(' > ');
  };

  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || skipped(el) || !visible(el)) continue;
    out.push({kind: 'text', text, where: where(el)});
  }

  for (const attr of ['title', 'placeholder', 'aria-label', 'alt']) {
    document.querySelectorAll('[' + attr + ']').forEach((el) => {
      const value = (el.getAttribute(attr) || '').trim();
      if (!value || attrSkipped(el) || !visible(el)) return;
      out.push({kind: attr, text: value, where: where(el)});
    });
  }

  const title = (document.title || '').trim();
  if (title) out.push({kind: 'document.title', text: title, where: 'head > title'});
  return out;
}
"""

INJECT_CONTROL_JS = r"""
(text) => {
  const probe = document.createElement('div');
  probe.id = '__i18n_control_probe';
  probe.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;'
    + 'background:#111;color:#fff;font-size:12px;padding:2px 4px';
  probe.textContent = text;
  document.body.appendChild(probe);
}
"""

REMOVE_CONTROL_JS = """
() => { const p = document.getElementById('__i18n_control_probe'); if (p) p.remove(); }
"""


def latin_findings(text: str) -> list[str]:
    """Латинские слова, оставшиеся после вычета нетекстовых кусков и имён собственных."""
    cleaned = text
    for name in FIXTURE_NAMES:
        cleaned = cleaned.replace(name, " ")
    for pattern in NOT_A_LABEL:
        cleaned = pattern.sub(" ", cleaned)
    words = [w for w in WORD.findall(cleaned) if w.lower() not in ALLOWED]
    return words


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed_db(db_path: Path) -> None:
    from app import db as dbmod
    from app.db import init_db, save_session

    previous = dbmod.DB_PATH
    dbmod.DB_PATH = db_path
    try:
        init_db()
        now = datetime.now(timezone.utc).isoformat()
        save_session({
            "id": "audit-orch", "name": "audit-orch", "scope": str(ROOT),
            "cwd": str(ROOT), "model": "claude-opus-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 1.25,
            "worktree_path": None, "branch": None, "is_orchestrator": True,
            "color": "", "created_at": now, "finished_at": None,
            "role": "orchestrator",
        })
        save_session({
            "id": "audit-worker", "name": "audit-worker", "scope": str(ROOT),
            "cwd": str(ROOT), "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 0.4,
            "worktree_path": None, "branch": "task-V-584/audit",
            "is_orchestrator": False, "color": "", "created_at": now,
            "finished_at": None, "role": "worker",
            "parent_id": "audit-orch", "parent_name": "audit-orch",
            "description": "lifecycle=one-shot проверка локали",
        })
    finally:
        dbmod.DB_PATH = previous


def start_server(db_path: Path) -> tuple[subprocess.Popen, str]:
    env = os.environ.copy()
    env["ORCHESTRA_DB_PATH"] = str(db_path)
    env["DASHBOARD_USER"] = USER
    env["DASHBOARD_PASSWORD"] = PASSWORD
    env["OWNER_MODE"] = "1"
    env["SSH_TUNNELS"] = ""
    port = free_port()
    output = tempfile.TemporaryFile(dir=db_path.parent)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=output, stderr=subprocess.STDOUT,
    )
    proc.stdout = output
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output.seek(0)
            raise RuntimeError(
                f"сервер аудита упал с кодом {proc.returncode}:\n"
                + output.read().decode("utf-8", "replace")[-3000:]
            )
        try:
            with urllib.request.urlopen(origin, timeout=1) as response:
                if response.status == 200:
                    return proc, origin
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"сервер аудита не поднялся на {origin} за 120 с")


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    if proc.stdout is not None:
        proc.stdout.close()


def login(page, origin: str) -> None:
    page.goto(f"{origin}/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_selector("#agent-list", timeout=30000)
    page.wait_for_timeout(1200)


def reset(page) -> None:
    """Вернуть дашборд в исходное состояние между экранами."""
    page.evaluate("""() => {
        document.querySelectorAll('.fixed.inset-0').forEach((modal) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        });
        const drop = document.getElementById('profiles-dropdown');
        if (drop) drop.classList.add('hidden');
        if (typeof switchLeftTab === 'function') switchLeftTab('files');
        window.compactMode = false;
        const chat = document.getElementById('chat');
        if (chat) chat.replaceChildren();
        if (window.Connection) Connection.set('online', {});
    }""")
    page.wait_for_timeout(200)


# Лента чата рисуется только из событий, поэтому её состояния подаются
# синтетическими записями в ТОТ ЖЕ addChatEntry, который зовёт живой SSE.
CHAT_ENTRIES_JS = """
() => {
    const chat = document.getElementById('chat');
    chat.replaceChildren();
    const ts = new Date().toISOString();
    const add = (type, content, payload) => addChatEntry(type, content, ts, null, payload || {});
    return add;
}
"""

_TOOL_CALLS = r"""
    add('tool', 'Bash: {"command":"эхо-проба","description":"Смотрит файлы"}', {tool_use_id: 't1'});
    add('tool_result', 'вывод команды', {tool_use_id: 't1'});
    add('tool', 'Read: {"file_path":"/tmp/a.py","offset":10,"limit":40}', {tool_use_id: 't2'});
    add('tool', 'Grep: {"pattern":"образец"}', {tool_use_id: 't3'});
    add('tool_result', '/tmp/a.py:10:строка\n/tmp/b.py:3:строка', {tool_use_id: 't3'});
    add('tool', 'Glob: {"pattern":"**/*.py"}', {tool_use_id: 't4'});
    add('tool_result', '/tmp/a.py\n/tmp/b.py\n/tmp/c.py', {tool_use_id: 't4'});
    add('tool', 'WebSearch: {"action":{"type":"search","queries":["реестр ПО"]}}', {tool_use_id: 't5'});
    add('tool', 'WebSearch: {"action":{"type":"openPage","url":"https://example.org/a"}}', {tool_use_id: 't5b'});
    add('tool', 'WebSearch: {"action":{"type":"findInPage","pattern":"образец"}}', {tool_use_id: 't5c'});
    add('tool', 'WebSearch: {"action":{}}', {tool_use_id: 't5d'});
    add('tool', 'FileChange: {"changes":[{"path":"/tmp/a.py","kind":"update","diff":"--- a\\n+++ b\\n-старое\\n+новое\\n общее\\n общее2\\n общее3\\n общее4\\n общее5\\n общее6\\n общее7\\n общее8\\n общее9"}]}', {tool_use_id: 't6'});
    add('tool_result', '{"status":"completed","files":1}', {tool_use_id: 't6'});
    add('tool', 'ViewImage: {"file_path":"/tmp/shot.png"}', {tool_use_id: 't7'});
    add('tool', 'ImageGeneration: {"prompt":"кот"}', {tool_use_id: 't8'});
    add('tool', 'Sleep: {"duration_ms":4000}', {tool_use_id: 't9'});
    add('tool_result', 'ok', {tool_use_id: 't9'});
    add('tool', 'Agent: {"description":"Разбор","prompt":"Проверь","content":"Проверь ветку"}', {tool_use_id: 't10'});
    add('tool', 'TodoWrite: {"todos":[{"status":"completed","content":"шаг"},{"status":"in_progress","content":"шаг 2"}]}', {tool_use_id: 't11'});
    add('tool', 'mcp__orchestra__spawn_worker: {"name":"w1","model":"luna","role":"worker","task_id":"V-584"}', {tool_use_id: 't12'});
    add('tool', 'mcp__orchestra__kill_worker: {"name":"w1"}', {tool_use_id: 't13'});
    add('tool', 'mcp__orchestra__stop_worker: {"name":"w1"}', {tool_use_id: 't14'});
    add('tool', 'mcp__orchestra__compact_worker: {"name":"w1"}', {tool_use_id: 't15'});
    add('tool', 'mcp__orchestra__rename_worker: {"old_name":"w1","new_name":"w2"}', {tool_use_id: 't16'});
    add('tool', 'mcp__orchestra__change_worker_model: {"name":"w1","model":"astra"}', {tool_use_id: 't17'});
    add('tool', 'mcp__orchestra__update_worker_description: {"name":"w1","description":"разовый воркер"}', {tool_use_id: 't18'});
    add('tool', 'mcp__orchestra__merge_worker: {"name":"w1"}', {tool_use_id: 't19'});
    add('tool', 'mcp__orchestra__list_agents: {}', {tool_use_id: 't20'});
    add('tool', 'mcp__orchestra__list_orchestrators: {}', {tool_use_id: 't21'});
    add('tool', 'mcp__orchestra__get_worker_logs: {"name":"w1","limit":20}', {tool_use_id: 't22'});
    add('tool', 'mcp__orchestra__get_worker_info: {"name":"w1"}', {tool_use_id: 't23'});
    add('tool_result', '{"name":"w1","status":"idle","model":"claude-opus-5[1m]","is_orchestrator":false,"branch":"task-V-584/w1","context_pct":42,"cost_usd":1.2,"task_id":"V-584","total_turns":7,"total_tool_calls":19,"total_input_tokens":12000,"total_output_tokens":3400,"description":"проверка"}', {tool_use_id: 't23'});
    add('tool', 'mcp__orchestra__bg_create: {"type":"timer","delay_seconds":600,"message":"проверь"}', {tool_use_id: 't24'});
    add('tool', 'mcp__orchestra__bg_list: {}', {tool_use_id: 't25'});
    add('tool', 'mcp__orchestra__bg_cancel: {"job_id":"abcdef123456"}', {tool_use_id: 't26'});
    add('tool', 'mcp__orchestra__send_file: {"path":"/tmp/a.txt"}', {tool_use_id: 't27'});
    add('tool_result', 'ok', {tool_use_id: 't27'});
    add('tool', 'mcp__orchestra__send_files: {"paths":["/tmp/a.png","/tmp/b.txt","/tmp/c.txt"]}', {tool_use_id: 't28'});
    add('tool', 'ToolSearch: {"query":"read"}', {tool_use_id: 't29'});
    add('tool_result', '{"tool_name":"Read"}', {tool_use_id: 't29'});
    add('tool', 'mcp__orchestra__report_bug: {"title":"падает"}', {tool_use_id: 't30'});
    add('tool_result', 'ok', {tool_use_id: 't30'});
"""

CHAT_SCREENS: list[tuple[str, str]] = [
    ("Чат: карточки инструментов, обычный вид",
     "() => { const add = (" + CHAT_ENTRIES_JS + ")();" + _TOOL_CALLS + " return true; }"),
    ("Чат: карточки инструментов, компактный вид",
     "() => { window.compactMode = true; const add = (" + CHAT_ENTRIES_JS + ")();"
     + _TOOL_CALLS + " return true; }"),
    ("Чат: субагенты и фоновые задачи", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        addChatEntry('subagent_start', 'Разбор логов', ts, null, {subagent_id: 's1', task_type: 'local_agent'});
        addChatEntry('subagent_progress', 'x', ts, null, {subagent_id: 's1', tool: 'Bash', tokens: '4200'});
        addChatEntry('subagent_end', 'Готово | краткий итог', ts, null, {subagent_id: 's1', status: 'completed'});
        addChatEntry('subagent_start', 'Фоновая сборка', ts, null, {subagent_id: 's2', task_type: 'background'});
        addChatEntry('subagent_end', 'Упало | ошибка сборки', ts, null, {subagent_id: 's2', status: 'failed'});
        addChatEntry('subagent_progress', 'ход', ts, null, {subagent_id: 'нет-такого', tokens: '900'});
        return true;
    }"""),
    ("Чат: служебные плашки состояния", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        const add = (c) => addChatEntry('status', c, ts, null, {});
        add('message steered into active Codex turn');
        add('codex reconnecting: попытка 2');
        add('model rerouted: luna → astra');
        add('codex context compact');
        add('compact done (native Codex): 82% → 31%');
        add('grok mcp ready');  // строка сервера: экран обязан её показать как есть
        addChatEntry('review', '{"phase":"entered","review":"текст ревью"}', ts, null, {});
        addChatEntry('review', '{"phase":"exited","review":"текст ревью"}', ts, null, {});
        addChatEntry('plan', '{"explanation":"почему","plan":[{"step":"шаг","status":"pending"}]}', ts, null, {});
        addChatEntry('thinking', 'рассуждение', ts, null, {});
        addChatEntry('turn_diff', '--- a\n+++ b\n-старое\n+новое', ts, null, {});
        return true;
    }"""),
    ("Чат: сообщения от агентов и платформы", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        ['agent', 'background_task', 'platform', 'system', 'unknown'].forEach((origin, i) => {
            addChatEntry('text', 'Текст сообщения', ts, null,
                {origin, senders: ['отправитель-' + i], from: 'отправитель-' + i});
        });
        return true;
    }"""),
    ("Чат: карточка задачи", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        addChatEntry('tool', 'mcp__orchestra__task_get: {"par":"V-584"}', ts, null, {tool_use_id: 'k1'});
        addChatEntry('tool_result', JSON.stringify({
            task_id: 'V-584', par: 'V-584', title: 'Русский интерфейс', status: 'in_progress',
            project: 'orchestra', price: 20000, assignee: 'i18n-dashboard', priority: 1,
            created_at: '2026-09-17T08:00:00', updated_at: '2026-09-17T09:00:00',
            completed_at: '2026-09-17T10:00:00', paid_at: '2026-09-17T11:00:00',
            description: 'Длинное описание задачи. '.repeat(20),
        }), ts, null, {tool_use_id: 'k1'});
        return true;
    }"""),
    ("Чат: ошибки инструментов", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        addChatEntry('tool', 'mcp__orchestra__send_files: {"paths":["/tmp/a.png"]}', ts, null, {tool_use_id: 'e1'});
        addChatEntry('tool_result', 'Error: отправка не удалась', ts, null, {tool_use_id: 'e1'});
        addChatEntry('tool', 'mcp__orchestra__send_file: {"path":"/tmp/a.png"}', ts, null, {tool_use_id: 'e2'});
        addChatEntry('tool_result', 'error: нет файла', ts, null, {tool_use_id: 'e2'});
        addChatEntry('tool', 'mcp__orchestra__merge_worker: {"name":"w1"}', ts, null, {tool_use_id: 'e3'});
        addChatEntry('tool_result', 'failed: конфликт', ts, null, {tool_use_id: 'e3'});
        addChatEntry('tool', 'Glob: {"pattern":"**/*.нет"}', ts, null, {tool_use_id: 'e4'});
        addChatEntry('tool_result', '', ts, null, {tool_use_id: 'e4'});
        addChatEntry('tool_result', 'сирота без вызова', ts, null, {tool_use_id: 'нет-такого'});
        return true;
    }"""),
    ("Чат: живая активность Codex", r"""() => {
        const chat = document.getElementById('chat'); chat.replaceChildren();
        const ts = new Date().toISOString();
        addChatEntry('thinking_stream', 'рассуждает', ts, null, {activity: 'reasoning', item_id: 'r1'});
        addChatEntry('thinking_stream', 'планирует', ts, null, {activity: 'plan', item_id: 'p1'});
        addChatEntry('thinking_stream', 'ждёт', ts, null, {activity: 'waiting', item_id: 'w1'});
        return true;
    }"""),
    ("Баннер связи: перезапуск", "() => { Connection.set('restarting', {reason: 'restart'}); return true; }"),
    ("Баннер связи: восстановление", "() => { Connection.set('recovering', {reason: 'restart'}); return true; }"),
    ("Баннер связи: нет связи", "() => { Connection.set('offline', {}); return true; }"),
    ("Баннер связи: связь нестабильна",
     "() => { Connection.set('degraded', {path: '/api/sessions'}); return true; }"),
    ("Аналитика: агенты",
     "() => { openAnalyticsModal(); _analyticsView = 'agents'; _analyticsRenderControls(); _analyticsRender(); return true; }"),
    ("Аналитика: эффективность",
     "() => { openAnalyticsModal(); _analyticsView = 'efficiency'; _analyticsRenderControls(); _analyticsRender(); return true; }"),
    ("Аналитика: надёжность",
     "() => { openAnalyticsModal(); _analyticsView = 'reliability'; _analyticsRenderControls(); _analyticsRender(); return true; }"),
]

# Аналитика с ДАННЫМИ: пустая база показывает только заголовки, а половина надписей
# живёт в ветках «данные есть». Снимок подставляется в тот же _analyticsRender.
ANALYTICS_PAYLOAD = """
_analyticsPayload = {
    generated_at: '2026-09-17T09:00:00',
    period: {days: 7, complete: false, observed_from: '2026-09-12T00:00:00'},
    capacity: {anthropic: {pressure_pct: 45}, codex: {pressure_pct: 100}},
    summary: {
        observed_cost_usd: 120.5, agent_turns: 300, priced_turns: 280, unaccounted_turns: 20,
        completed_tasks: 9, linked_completed_tasks: 7, cost_per_linked_task: 12.3,
        task_cost_coverage_complete: true,
        lifetime: {agents: 42, active_agents: 3, cost_usd: 980.1, turns: 5100},
    },
    providers: {
        claude: {cost_usd: 80.2, turns: 190, cache_hit_pct: 62, cold_starts: 4,
                 cache_ttl_seconds: 3600, cache_ttl_approximate: false,
                 comparable_turns: 150, unaccounted_turns: 10,
                 windows: [{window_minutes: 300, utilization: 45, resets_at: '2026-09-17T12:00:00'},
                           {window_minutes: 10080, utilization: 83, resets_at: '2026-09-20T12:00:00'}]},
        codex: {cost_usd: 40.3, turns: 110, cache_hit_pct: null, cold_starts: 9,
                cache_ttl_seconds: 1800, cache_ttl_approximate: true,
                comparable_turns: 90, unaccounted_turns: 0,
                windows: [{window_minutes: 300, utilization: 100, resets_at: '2026-09-19T00:00:00'}],
                spark: {windows: [{window_minutes: 10080, utilization: 12}]}},
    },
    daily: [{day: '2026-09-16', providers: {claude: {cost_usd: 12}, codex: {cost_usd: 5}}}],
    agents: [
        {id: 1, name: 'audit-orch', scope: '/tmp', model: 'claude-opus-5[1m]', provider: 'claude',
         turns: 80, cost_usd: 44.2, priced_turns: 78, unaccounted_turns: 2,
         cost_per_priced_turn: 0.56, last_turn: '2026-09-17T08:40:00', anomaly: true},
        {id: 2, name: 'audit-worker', scope: '', model: '', provider: 'codex',
         turns: 20, cost_usd: 3.1, priced_turns: 20, unaccounted_turns: 0,
         cost_per_priced_turn: 0.15, last_turn: '2026-09-17T07:10:00', anomaly: false},
    ],
    models: [
        {model: 'claude-opus-5[1m]', provider: 'claude', turns: 80, priced_turns: 78,
         unaccounted_turns: 2, cost_share_pct: 66.5, cost_usd: 80.2},
        {model: '', provider: 'codex', turns: 20, priced_turns: 20, unaccounted_turns: 0,
         cost_share_pct: 33.5, cost_usd: 40.3},
    ],
    reliability: {
        subagents: {completed: 12, failed: 2, running: 1, stopped: 3, unclassified: 4},
        background_tasks: {total: 40, failed: 6},
        voice: {entries: 5, duration_sec: 130.5, cost_usd: 0.4},
        task_linkage: {linked: 7, total: 9},
        tool_errors: {collector_ready: true, coverage_complete: false,
                      collector_started_at: '2026-09-14T00:00:00',
                      items: [{tool_name: 'Bash', count: 3, last_error: 'нет доступа'},
                              {tool: '', count: 1, last_error: ''}]},
        turn_usage: {collector_ready: true, coverage_complete: false, recorded_rows: 280,
                     priced_rows: 260, unaccounted_rows: 20,
                     collector_started_at: '2026-09-14T00:00:00'},
    },
    wake_after_reset: {
        scheduled: [{provider: 'claude', agents: ['a1'], reset_at: '2026-09-17T12:00:00'},
                    {provider: 'codex', agents: [], reset_at: '2026-09-17T13:00:00', preserved: true},
                    {provider: 'claude', agents: ['a2'], reason: 'available_now'}],
        manual: [{agents: ['a3'], manual_action_url: 'https://claude.ai/settings/usage'}],
        unavailable: [{agents: ['a4'], reason: 'Нет свежих данных о квоте'}],
        warnings: [{agents: ['a5'], reason: 'план не обновлён'}],
    },
};
"""

ANALYTICS_DATA_SCREENS = [
    (f"Аналитика с данными: {title}",
     "() => { openAnalyticsModal(); " + ANALYTICS_PAYLOAD
     + f"_analyticsView = '{view}'; _analyticsRenderQuality();"
     " _analyticsRenderControls(); _analyticsRender(); return true; }")
    for title, view in [("пулы и расходы", "overview"), ("агенты", "agents"),
                        ("эффективность", "efficiency"), ("надёжность", "reliability")]
]

# Отдельно — выбранный агент в разборе и фильтр без совпадений.
ANALYTICS_DATA_SCREENS += [
    ("Аналитика с данными: разбор по агенту",
     "() => { openAnalyticsModal(); " + ANALYTICS_PAYLOAD
     + "_analyticsView = 'agents'; _analyticsSelectedAgent = '1';"
     " _analyticsRenderControls(); _analyticsRender(); return true; }"),
    ("Аналитика с данными: фильтр без совпадений",
     "() => { openAnalyticsModal(); " + ANALYTICS_PAYLOAD
     + "_analyticsView = 'agents'; _analyticsAgentFilter = 'anomaly';"
     " _analyticsPayload.agents = []; _analyticsRenderControls(); _analyticsRender();"
     " _analyticsAgentFilter = 'all'; return true; }"),
]

USAGE_SCREENS = [
    ("Полоса расхода: данные провайдеров", r"""() => {
        _usageData = {
            anthropic: {five_hour: {utilization: 45, resets_at: '2026-09-17T12:00:00'},
                        seven_day: {utilization: 83, resets_at: '2026-09-20T12:00:00'}},
            codex: {primary: {window_minutes: 300, utilization: 100, resets_at: '2026-09-19T00:00:00'},
                    spark: {primary: {window_minutes: 10080, utilization: 12}}},
            grok: null,
            openrouter: {available: true, daily: {count: 12, limit: 1000}, minute: {count: 2, limit: 20}},
            total_cost_usd: 120.5, voice_cost_usd: 0.4,
        };
        _usageLastSuccessAt = Date.now();
        _usageError = false;
        renderUsageBar();
        return true;
    }"""),
    ("Полоса расхода: данные недоступны", r"""() => {
        _usageData = null; _usageError = true;
        if (window.Connection) Connection.set('online', {});
        renderUsageBar();
        return true;
    }"""),
]

ERROR_SCREENS = [
    ("Левая панель: не удалось загрузить задачи", r"""() => {
        switchLeftTab('tasks');
        document.getElementById('tasks-panel').innerHTML =
            `<div class="p-2 text-slate-500">${T('Failed to load tasks')}</div>`;
        return true;
    }"""),
    ("Левая панель: не удалось загрузить задания", r"""() => {
        switchLeftTab('jobs');
        document.getElementById('jobs-panel').innerHTML =
            `<div class="p-2 text-slate-500">${T('Failed to load jobs')}</div>`;
        return true;
    }"""),
    ("Окно нового оркестратора: ошибка ввода", r"""() => {
        document.getElementById('new-orch-btn').click();
        const err = document.getElementById('orch-error');
        err.textContent = T('Name and project path required');
        err.classList.remove('hidden');
        document.getElementById('create-orch-btn').textContent = T('Creating...');
        return true;
    }"""),
    ("Профили: ошибка ввода", r"""() => {
        document.getElementById('profiles-btn').click();
        const err = document.getElementById('profile-error');
        err.textContent = T('name required');
        err.classList.remove('hidden');
        return true;
    }"""),
]


# Экран = имя + действие в браузере. Действие возвращает False, если экран
# на этом стенде недоступен, — это попадёт в отчёт, а не пропадёт молча.
SCREENS: list[tuple[str, str]] = [
    ("Дашборд: основной вид", "() => true"),
    ("Левая панель: задачи", "() => { switchLeftTab('tasks'); return true; }"),
    ("Левая панель: фоновые задания", "() => { switchLeftTab('jobs'); return true; }"),
    ("Окно: новый оркестратор", "() => { document.getElementById('new-orch-btn').click(); return true; }"),
    ("Окно: каталог моделей", "() => { openCatalogModal(); return true; }"),
    ("Окно: аналитика расхода", "() => { openAnalyticsModal(); return true; }"),
    ("Окно: активность агентов", "() => { openSubagentsModal(); return true; }"),
    ("Окно: системная подсказка", "() => { openPromptModal(); return true; }"),
    ("Окно: сведения о клиенте", "() => { document.getElementById('client-btn').click(); return true; }"),
    ("Панель: профили Claude", "() => { document.getElementById('profiles-btn').click(); return true; }"),
    ("Окно: удаление оркестратора", """() => {
        const modal = document.getElementById('delete-orch-modal');
        modal.classList.remove('hidden'); modal.classList.add('flex');
        document.getElementById('delete-orch-name').textContent = 'audit-orch';
        return true;
    }"""),
    ("Окно: смена папки", """() => {
        const modal = document.getElementById('change-scope-modal');
        modal.classList.remove('hidden'); modal.classList.add('flex');
        return true;
    }"""),
    ("Окно: просмотр файла", """() => {
        const modal = document.getElementById('file-preview-modal');
        modal.classList.remove('hidden'); modal.classList.add('flex');
        document.getElementById('file-preview-download').classList.remove('hidden');
        document.getElementById('file-preview-open').classList.remove('hidden');
        return true;
    }"""),
]


def collect(page) -> list[dict]:
    return page.evaluate(COLLECT_JS, [SKIP_SELECTORS, ATTR_SKIP_SELECTORS])


def audit_screen(page, name: str, shots: Path | None) -> dict:
    # 1. Отрицательный контроль: заведомо английская надпись обязана найтись.
    page.evaluate(INJECT_CONTROL_JS, CONTROL_TEXT)
    control_seen = any(
        CONTROL_TEXT in row["text"] and latin_findings(row["text"])
        for row in collect(page)
    )
    page.evaluate(REMOVE_CONTROL_JS)

    # 2. Собственно сбор.
    rows = collect(page)
    findings = []
    for row in rows:
        words = latin_findings(row["text"])
        if words:
            findings.append({**row, "words": sorted(set(words))})

    if shots is not None:
        safe = re.sub(r"[^\w-]+", "_", name)
        page.screenshot(path=str(shots / f"{safe}.png"), full_page=False)

    return {
        "screen": name,
        "control_detected": control_seen,
        "collected": len(rows),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="ru", choices=["ru", "en"])
    parser.add_argument("--json", default="")
    parser.add_argument("--shots", default="")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    shots = Path(args.shots).resolve() if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="v584-audit-"))
    db_path = workdir / "orchestra.db"
    seed_db(db_path)
    proc, origin = start_server(db_path)
    report: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            context.add_init_script(
                f"try {{ localStorage.setItem('orch_lang', {args.lang!r}); }} catch (e) {{}}"
            )
            page = context.new_page()

            # Первый экран — страница входа: до неё пользователь ещё не вошёл.
            page.goto(f"{origin}/login", wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            report.append(audit_screen(page, "Страница входа", shots))

            login(page, origin)
            all_screens = (SCREENS + CHAT_SCREENS + ANALYTICS_DATA_SCREENS
                           + USAGE_SCREENS + ERROR_SCREENS)
            for name, action in all_screens:
                reset(page)
                try:
                    available = page.evaluate(action)
                except Exception as exc:
                    report.append({
                        "screen": name, "control_detected": False, "collected": 0,
                        "findings": [], "unavailable": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                if available is False:
                    report.append({
                        "screen": name, "control_detected": False, "collected": 0,
                        "findings": [], "unavailable": "экран недоступен на стенде",
                    })
                    continue
                page.wait_for_timeout(900)
                report.append(audit_screen(page, name, shots))

            browser.close()
    finally:
        stop_server(proc)

    total = sum(len(item["findings"]) for item in report)
    unproven = [i["screen"] for i in report if not i.get("control_detected")]
    for item in report:
        mark = "✗" if item["findings"] else "✓"
        if item.get("unavailable"):
            print(f"⚠ {item['screen']}: {item['unavailable']}")
            continue
        print(f"{mark} {item['screen']}: узлов {item['collected']}, "
              f"находок {len(item['findings'])}, "
              f"контроль {'найден' if item['control_detected'] else 'НЕ НАЙДЕН'}")
        for finding in item["findings"]:
            print(f"    [{finding['kind']}] {finding['text']!r}")
            print(f"        {finding['where']}  →  {', '.join(finding['words'])}")

    print(f"\nвсего находок: {total}; экранов: {len(report)}")
    if unproven:
        print("НЕДОКАЗАННЫЕ экраны (отрицательный контроль не сработал): "
              + ", ".join(unproven))

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    return 1 if (total or unproven) else 0


if __name__ == "__main__":
    raise SystemExit(main())
