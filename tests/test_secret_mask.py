"""#224 T1/T2 — маскирование значений секретов на ОБОИХ швах выдачи.

Швов два, и это главная находка ресёрча: `db.add_log` — единственный INSERT в `logs`,
но `live_broker.publish` уходит в SSE МИМО него и в БД не пишется вовсе
(`app/session.py:1434,1440,1453,1482`). Маскирование только на первом оставляет живой
поток в браузер открытым.

Тесты написаны ДО реализации и коммитятся КРАСНЫМИ.
"""
import importlib.util
from datetime import datetime, timezone

import pytest


def mask():
    """Вернуть `mask_secrets`, ПРОВАЛИВ тест внятно, если модуля ещё нет.

    Прямой `import` дал бы ModuleNotFoundError на этапе сбора — это «сломано», а не
    «красное»: по такому провалу не видно, чего именно не хватает.
    """
    assert importlib.util.find_spec("app.secret_mask") is not None, (
        "app.secret_mask ещё не реализован (T1)"
    )
    from app.secret_mask import mask_secrets
    return mask_secrets

# Значение-приманка: 20 символов, подходит под порог ">=12" любого разумного правила.
SECRET = "abcdefghijklmnopqrst"
MASKED = "[secret len=20 tail=qrst]"
# Хеш содержимого — НЕ секрет. Крупнейший класс ложных срабатываний, замерен в ресёрче
# (TEMPLATE_HASH/_TEMPLATE_HASH — 33 вхождения в живой БД).
NOT_SECRET = "0123456789abcdef"


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def session_row(db):
    from app.db import save_session
    row = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "worker-1",
        "scope": "/home/kesha/orchestra",
        "cwd": "/home/kesha/orchestra",
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": "starting",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "",
        "branch": "",
        "is_orchestrator": False,
        "color": "#818cf8",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    save_session(row)
    return row


def _stored_content(session_id: str) -> str:
    from app.db import _conn
    with _conn() as c:
        rows = c.execute(
            "SELECT content FROM logs WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    return "\n".join(r[0] for r in rows)


# ── T1: шов персистенции ──────────────────────────────────────────────────────

def test_t1_add_log_masks_secret_value(session_row):
    """Значение секрета не должно доезжать до строки в `logs`.

    Носитель в проде — вывод рутинного `ps` в tool_result (замер: 21 строка в живой БД).
    """
    from app.db import add_log
    sid = session_row["id"]
    add_log(sid, datetime.now(timezone.utc), "tool_result",
            f'--mcp-config {{"mcpServers":{{"orchestra":{{"env":{{"INTERNAL_TOKEN": "{SECRET}"}}}}}}}}')

    stored = _stored_content(sid)
    assert SECRET not in stored, "значение секрета сохранено в logs дословно"
    assert MASKED in stored, f"ожидалась маска с длиной и хвостом: {MASKED}"


def test_t1_add_log_keeps_content_hash_untouched(session_row):
    """Маска обязана НЕ трогать хеши содержимого — иначе портит диагностику."""
    from app.db import add_log
    sid = session_row["id"]
    add_log(sid, datetime.now(timezone.utc), "tool_result",
            f'TEMPLATE_HASH="{NOT_SECRET}"')

    stored = _stored_content(sid)
    assert NOT_SECRET in stored, "хеш содержимого замаскирован — ложное срабатывание"


# ── T1b: положительная матрица правила ────────────────────────────────────────
# Ревью справедливо указало, что один quoted INTERNAL_TOKEN из простого алфавита
# оракулом правила не является. Значение извлекается ПО ФОРМЕ, а не по классу символов:
# URL/DSN/cookie содержат ':' '@' '?' '&' '=' ';' '%', которых нет в алфавите ключа.

LONG = "abcdefghijklmnopqrst"          # 20 символов → маска с хвостом
SHORT = "abcdefghijkl"                 # 12 символов → маска без хвоста (порог 16)

MATRIX = [
    # (описание, строка лога, что обязано исчезнуть)
    ("json quoted",      f'{{"INTERNAL_TOKEN": "{LONG}"}}',              LONG),
    ("toml quoted",      f'INTERNAL_TOKEN = "{LONG}"',                   LONG),
    ("shell bare",       f'OPENROUTER_API_KEY={LONG}',                   LONG),
    ("single quoted",    f"YOUGILE_PASSWORD='{LONG}'",                   LONG),
    ("explicit list",    f'YANDEX_DIRECT_LOGIN="{LONG}"',                LONG),
    ("api hash flag",    f'--api-hash={LONG}',                           LONG),
    # формы с пунктуацией вне алфавита ключа — именно они ломали первую редакцию правила
    ("database url",     f'DATABASE_URL=postgres://user:{LONG}@host:5432/db',
                         f'postgres://user:{LONG}@host:5432/db'),
    ("dsn",              f'SENTRY_DSN=https://{LONG}@o1.ingest.io/42',
                         f'https://{LONG}@o1.ingest.io/42'),
    ("cookie",           f'SESSION_COOKIE={LONG}+/=; Path=/',            f'{LONG}+/='),
    ("connection string", f'CONNECTION_STRING="Server=a;Pwd={LONG};"',   f'Server=a;Pwd={LONG};'),
]


@pytest.mark.parametrize("label,line,must_vanish", MATRIX, ids=[m[0] for m in MATRIX])
def test_t1b_mask_covers_every_declared_form(label, line, must_vanish):
    mask_secrets = mask()
    out = mask_secrets(line)
    assert must_vanish not in out, f"{label}: значение уцелело целиком"
    assert LONG not in out, f"{label}: секрет уцелел"
    assert "[secret len=" in out, f"{label}: маска не поставлена"


def test_t1b_threshold_and_tail_format():
    mask_secrets = mask()
    # >=16 символов → длина и хвост
    assert mask_secrets(f'TOKEN="{LONG}"') == 'TOKEN="[secret len=20 tail=qrst]"'
    # 12..15 → только длина, хвост не отдаём (4 из 12 — слишком много)
    assert mask_secrets(f'TOKEN="{SHORT}"') == 'TOKEN="[secret len=12]"'
    # <12 → не трогаем вовсе, иначе шум забивает журнал
    assert mask_secrets('TOKEN="short"') == 'TOKEN="short"'


def test_t1b_bearer_and_pem_reuse_existing_patterns():
    """`_AUTH_VALUE` и `_PEM_PRIVATE_KEY` уже есть в runtime_history — переиспользовать."""
    mask_secrets = mask()
    out = mask_secrets(f"Authorization: Bearer {LONG}")
    assert LONG not in out and "Bearer" in out

    pem = "-----BEGIN RSA PRIVATE KEY-----\n" + LONG + "\n-----END RSA PRIVATE KEY-----"
    out = mask_secrets(pem)
    assert LONG not in out
    assert "BEGIN RSA PRIVATE KEY" not in out or "[secret pem" in out


def test_t1b_escaped_quote_does_not_end_the_value():
    """Экранированная кавычка внутри значения не заканчивает его.

    Найдено ревью: `[^"]*` останавливался на `\\"`, маскировался только префикс, а
    остаток секрета оставался в логе. Сериализованный JSON внутри лога — обычное дело.
    """
    mask_secrets = mask()
    out = mask_secrets(f'{{"TOKEN": "pre\\"{LONG}"}}')
    assert LONG not in out, "хвост значения после экранированной кавычки уцелел"


def test_t1b_semicolon_does_not_truncate_a_bare_value():
    """`;` не может быть универсальным концом значения.

    Найдено ревью: cookie и connection string ЯВНО входят в покрываемые классы и
    штатно содержат `;` — обрезание по нему оставляло вторую половину секрета видимой.
    """
    mask_secrets = mask()
    out = mask_secrets(f"CONNECTION_STRING=Server=a;Pwd={LONG};")
    assert LONG not in out, "значение после ';' уцелело"
    # пробел по-прежнему заканчивает значение, иначе замаскируем пол-строки лога
    out = mask_secrets(f"SESSION_COOKIE={LONG}; Path=/ HttpOnly")
    assert LONG not in out and "Path=/ HttpOnly" in out


def test_t1b_fast_prefilter_is_a_superset_of_the_rule():
    """Предфильтр обязан пропускать ВСЁ, что ловит правило.

    `publish` зовётся на каждый partial-чанк, поэтому перед полным проходом стоит дешёвая
    подстрочная проверка. Если она хоть на одном имени окажется у́же правила, секрет
    начнёт утекать МОЛЧА — отказ будет выглядеть как «правило не сработало».
    Инвариант проверяем по самому списку имён, а не по вручную выписанным примерам.
    """
    from app.secret_mask import _SECRET_WORDS
    mask_secrets = mask()
    for word in _SECRET_WORDS:
        line = f'{word}="{LONG}"'
        assert LONG not in mask_secrets(line), f"предфильтр отбросил {word}"


@pytest.mark.parametrize("benign", [
    'TEMPLATE_HASH="0123456789abcdef"',
    '_TEMPLATE_HASH = "0123456789abcdef"',
    'RECEIVED_REQUEST_HASH=0123456789abcdef',
])
def test_t1b_content_hashes_are_not_secrets(benign):
    """`_HASH` суффиксом брать нельзя — крупнейший класс ложных срабатываний (33 вхождения)."""
    mask_secrets = mask()
    assert mask_secrets(benign) == benign


# ── T2: шов живой выдачи (SSE), в БД не пишется ───────────────────────────────

@pytest.mark.asyncio
async def test_t2_broker_publish_masks_content():
    """Живой поток в браузер идёт мимо add_log — маскировать надо и здесь."""
    from app.live_broker import LiveBroker
    b = LiveBroker()
    q = b.subscribe("sid")
    b.publish("sid", {"type": "stream", "content": f'OPENROUTER_API_KEY="{SECRET}"'})

    got = q.get_nowait()
    assert SECRET not in got["content"], "секрет ушёл в SSE-поток дословно"
    assert MASKED in got["content"]


@pytest.mark.asyncio
async def test_t2_broker_replay_is_masked():
    """Накопленный буфер реплеится новым подписчикам — он тоже обязан быть чистым."""
    from app.live_broker import LiveBroker
    b = LiveBroker()
    b.publish("sid", {"type": "stream", "content": f'INTERNAL_TOKEN="{SECRET}"'})

    late = b.subscribe("sid")          # реплей накопленного
    got = late.get_nowait()
    assert SECRET not in got["content"], "секрет остался в реплей-буфере"


@pytest.mark.asyncio
async def test_t2_broker_does_not_mutate_caller_payload():
    """Контракт с вызывающим: publish не портит переданный ему dict.

    `session._handle_event` строит payload и может использовать его дальше; тихая
    мутация чужого объекта — скрытый side effect, запрещённый стилем проекта.
    """
    from app.live_broker import LiveBroker
    b = LiveBroker()
    b.subscribe("sid")
    payload = {"type": "stream", "content": f'INTERNAL_TOKEN="{SECRET}"'}
    b.publish("sid", payload)

    assert payload["content"] == f'INTERNAL_TOKEN="{SECRET}"', (
        "publish замаскировал payload вызывающего на месте — скрытый side effect"
    )


@pytest.mark.asyncio
async def test_t2_broker_publish_keeps_metadata():
    """Маскируется ТОЛЬКО поле content: type/tool_use_id/subagent_id держит фронт."""
    from app.live_broker import LiveBroker
    b = LiveBroker()
    q = b.subscribe("sid")
    b.publish("sid", {"type": "tool_stream", "content": "no secrets here",
                      "tool_use_id": "toolu_01ABC", "subagent_id": "sub-7"})

    got = q.get_nowait()
    assert got["type"] == "tool_stream"
    assert got["tool_use_id"] == "toolu_01ABC"
    assert got["subagent_id"] == "sub-7"
    assert got["content"] == "no secrets here"
