"""#224 T3/T4/T5/T7 — конфиг MCP уезжает в файл 600, значения уходят из argv.

Замер ресёрча: 8 живых процессов Claude несли значения чужих ключей в `--mcp-config`,
42 argv-фрагмента Codex несли `INTERNAL_TOKEN`. `/proc/<pid>/cmdline` читает процесс
ЛЮБОГО uid (hidepid не включён), поэтому argv — публичный канал.

Тесты написаны ДО реализации и коммитятся КРАСНЫМИ.
"""
import json
import os
import stat
import tomllib
from pathlib import Path

import pytest

SECRET = "abcdefghijklmnopqrst"


def _claude_backend(**kw):
    from app.backend_claude import ClaudeBackend
    params = dict(
        model="claude-sonnet-5[1m]",
        cwd="/home/kesha/orchestra",
        mcp_servers={"orchestra": {"command": "python", "args": ["/x/mcp_stdio.py"],
                                   "env": {"INTERNAL_TOKEN": SECRET}}},
    )
    params.update(kw)
    return ClaudeBackend(**params)


# ── T3: Claude — путь вместо inline JSON ──────────────────────────────────────

def test_t3_claude_passes_config_path_not_dict():
    """SDK сериализует dict в argv (`subprocess_cli.py:384-390`) и пропускает str/Path
    как путь (391-393). Значит тип аргумента и есть переключатель."""
    options = _claude_backend()._make_client().options

    assert isinstance(options.mcp_servers, (str, Path)), (
        "options.mcp_servers всё ещё dict → SDK положит значения секретов в argv"
    )


def test_t3_claude_config_file_is_0600_and_roundtrips():
    """Файл обязан быть 600 и нести ровно те серверы, что и раньше."""
    options = _claude_backend()._make_client().options
    assert isinstance(options.mcp_servers, (str, Path)), "конфиг ещё не вынесен в файл"

    path = Path(options.mcp_servers)
    assert path.is_file(), f"файл конфига не создан: {path}"

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"права {oct(mode)}, ожидалось 0o600"

    data = json.loads(path.read_text())["mcpServers"]
    assert data["orchestra"]["env"]["INTERNAL_TOKEN"] == SECRET, (
        "конфиг потерял содержимое при переносе в файл"
    )


def test_t3_secret_value_absent_from_option_string():
    """Главная проверка: строка, уходящая в argv, значения не содержит."""
    options = _claude_backend()._make_client().options
    assert SECRET not in str(options.mcp_servers)


MULTI = {
    "orchestra": {"command": "python", "args": ["/x/mcp_stdio.py"],
                  "env": {"INTERNAL_TOKEN": SECRET}, "alwaysLoad": True},
    "websearch": {"command": "node", "args": ["/w/index.js", "--flag"],
                  "env": {"OPENROUTER_API_KEY": SECRET}},
    "docs": {"type": "http", "url": "https://example.invalid/mcp"},
}


def test_t3_every_server_and_field_survives_the_move():
    """Оракул СОХРАННОСТИ, а не только отсутствия секрета.

    Тихая потеря тулов — главный риск файлового маршрута, и пустой grep по argv её
    не ловит. Сверяем ТОЧНОЕ множество серверов и все поля, а не «хотя бы один».
    """
    options = _claude_backend(mcp_servers=MULTI)._make_client().options
    assert isinstance(options.mcp_servers, (str, Path)), "конфиг ещё не вынесен в файл"

    written = json.loads(Path(options.mcp_servers).read_text())["mcpServers"]
    assert set(written) == set(MULTI), (
        f"множество серверов изменилось: было {sorted(MULTI)}, стало {sorted(written)}"
    )
    for name, cfg in MULTI.items():
        assert written[name] == cfg, f"сервер {name} потерял или исказил поля"


def test_t3_config_dir_is_private_and_outside_worktree_and_tmp():
    """Каталог 700, не в рабочем дереве (иначе грязный git status и блок мержей),
    не в /tmp (там tmpfs = RAM, и Codex отдельно отказывается там работать)."""
    options = _claude_backend()._make_client().options
    path = Path(options.mcp_servers)

    parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
    assert parent_mode == 0o700, f"каталог конфигов {oct(parent_mode)}, ожидалось 0o700"
    assert not str(path).startswith("/tmp/"), "конфиг в /tmp"

    repo = Path(__file__).resolve().parent.parent
    assert repo not in path.parents, f"конфиг внутри рабочего дерева: {path}"


def test_t3_repeated_make_client_reuses_one_file():
    """`_make_client` зовётся не раз за жизнь бэкенда — осиротевшие файлы копиться не должны."""
    b = _claude_backend()
    first = Path(b._make_client().options.mcp_servers)
    second = Path(b._make_client().options.mcp_servers)
    assert first == second, "каждый _make_client плодит новый файл конфига"


def test_t3_disconnect_removes_the_config_file():
    """Владелец жизненного цикла — сам бэкенд (`ClaudeBackend.disconnect`), не session-слой."""
    import asyncio
    b = _claude_backend()
    path = Path(b._make_client().options.mcp_servers)
    assert path.is_file()

    asyncio.run(b.disconnect())
    assert not path.exists(), "файл конфига пережил disconnect()"


# ── T7: тихая потеря тулов должна быть громкой ────────────────────────────────

def test_t7_sdk_server_refuses_file_route_loudly():
    """in-process sdk-сервер файлом объявить нельзя — он объект в памяти, не процесс.

    Сегодня таких серверов у нас нет (проверено разбором всех конфигов), но
    `_parse_custom_mcp` пропускает произвольный dict со спавна. Молча потерять тулы
    нельзя — только громко упасть.
    """
    backend = _claude_backend(mcp_servers={
        "orchestra": {"command": "python", "args": ["/x/mcp_stdio.py"], "env": {}},
        "inproc": {"type": "sdk", "name": "inproc"},
    })
    with pytest.raises(Exception) as exc:
        backend._make_client()
    assert "sdk" in str(exc.value).lower(), (
        "sdk-сервер молча уехал в файловый маршрут — тулы пропадут без ошибки"
    )


# ── T4: Codex — CODEX_HOME на агента ──────────────────────────────────────────

def _codex_backend(**kw):
    """Фикстура намеренно НЕСЁТ ORCHESTRA_SESSION_ID: в проде он есть всегда (замер —
    непусто в 50 из 50 живых процессов), а его отсутствие обязано ронять коннект, потому
    что анонимный запасной каталог на каждом коннекте молча терял бы thread-id и resume."""
    from app.backend_codex import CodexBackend
    params = dict(
        model="gpt-5.6-sol",
        cwd="/home/kesha/orchestra",
        mcp_servers={"orchestra": {"command": "python", "args": ["/x/mcp_stdio.py"],
                                   "env": {"INTERNAL_TOKEN": SECRET,
                                           "ORCHESTRA_SESSION_ID": "550e8400-default"}}},
    )
    params.update(kw)
    return CodexBackend(**params)


def test_t4_missing_session_id_fails_loudly():
    """Отсутствие идентификатора — тоже отказ, не запасной путь."""
    from app.backend_codex import CodexBackend
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp",
                     mcp_servers={"orchestra": {"command": "python", "args": [], "env": {}}})
    with pytest.raises(ValueError, match="ORCHESTRA_SESSION_ID"):
        b._prepare_codex_home()


def test_t4_no_env_fragment_in_codex_argv():
    """`-c mcp_servers.*.env={...}` обязан исчезнуть из argv целиком."""
    args = _codex_backend()._mcp_config_args()
    leaking = [a for a in args if ".env=" in a]
    assert not leaking, f"env всё ещё уходит в argv: {[a.split('=')[0] for a in leaking]}"
    assert not any(SECRET in a for a in args)


def test_t4_no_secret_anywhere_in_the_full_codex_command():
    """Проверка про ВСЮ командную строку, а не про её кусок.

    Codex — отдельный канал того же класса, что `--mcp-config` у Claude: значения env
    уезжали в argv через `-c mcp_servers.<n>.env=...`. Утверждать «в argv чисто» можно
    только про собранную целиком строку — по частям легко забыть новый источник.
    """
    b = _codex_backend(mcp_servers=_servers("session-fullcmd", {
        "websearch": {"command": "node", "args": ["/w/i.js"],
                      "env": {"OPENROUTER_API_KEY": SECRET}},
    }))
    cmd = b._codex_command()
    joined = " ".join(cmd)
    assert SECRET not in joined, f"секрет в argv: {[a for a in cmd if SECRET in a]}"
    assert ".env=" not in joined and ".env." not in joined, (
        "env всё ещё рендерится в командную строку"
    )
    assert cmd[-2:] == ["app-server", "--stdio"], "форма запуска изменилась незаметно"


def test_t4_config_written_to_own_codex_home(tmp_path, monkeypatch):
    """Конфиг собирается в приватном CODEX_HOME агента, файл 600."""
    b = _codex_backend()
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    import tomllib
    home = Path(prepare())
    cfg = home / "config.toml"
    assert cfg.is_file(), f"config.toml не создан в {home}"
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    # разбираем TOML, а не ищем подстроку: ключи теперь в кавычках, и подстрочная
    # проверка молча зеленела бы на испорченном синтаксисе
    assert "orchestra" in tomllib.loads(cfg.read_text())["mcp_servers"]


def test_t4_foreign_global_servers_not_copied(tmp_path, monkeypatch):
    """Сборка по белому списку, а не копия базового конфига.

    Подкладываем НАСТОЯЩИЙ базовый конфиг с чужими секциями: без него тест прошёл бы
    и при полном игнорировании base config, то есть не отличал бы сборку от копии.
    """
    base_home = tmp_path / "base-codex"
    base_home.mkdir()
    (base_home / "config.toml").write_text(
        'project_doc_max_bytes = 131072\n'
        'model_context_window = 872000\n'
        'model_auto_compact_token_limit = 784800\n'
        '\n[projects."/home/kesha/projects/seedon"]\ntrust_level = "trusted"\n'
        '\n[mcp_servers.yandex-direct]\ncommand = "node"\nargs = ["/y/index.js"]\n'
        '\n[mcp_servers.yandex-direct.env]\nYANDEX_DIRECT_TOKEN = "foreign-secret-value"\n'
        '\n[mcp_servers.openaiDeveloperDocs]\nurl = "https://developers.openai.com/mcp"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(base_home))

    b = _codex_backend()
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    text = (Path(prepare()) / "config.toml").read_text()
    assert "yandex-direct" not in text, "глобальный чужой MCP-сервер скопирован воркеру"
    assert "openaiDeveloperDocs" not in text
    assert "foreign-secret-value" not in text, "чужой секрет утёк в конфиг воркера"
    data = tomllib.loads(text)
    assert data["projects"] == {
        "/home/kesha/orchestra": {"trust_level": "trusted"},
    }, "нужен trust только собственного cwd, не чужих [projects.*] из base config"
    # разрешённый скаляр обязан переехать — иначе воркер молча теряет потолок обрезки AGENTS.md
    assert "project_doc_max_bytes = 131072" in text
    assert data["model_context_window"] == 872000
    assert data["model_auto_compact_token_limit"] == 784800


def test_t4_trusts_canonical_cwd_and_escapes_it_as_toml_key(tmp_path):
    project = tmp_path / 'project "quoted"'
    project.mkdir()
    b = _codex_backend(
        cwd=str(project),
        mcp_servers=_servers("session-roundtrip"),
    )

    data = tomllib.loads((b._prepare_codex_home() / "config.toml").read_text())
    assert data["projects"] == {
        str(project.resolve()): {"trust_level": "trusted"},
    }


def test_t4_child_env_points_at_the_same_home(tmp_path):
    """Конфиг можно собрать верно и всё равно запустить процесс на ОБЩЕМ home.

    Тогда argv чист, а воркер работает не со своим конфигом — тихий отказ.
    """
    b = _codex_backend()
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    home = str(prepare())
    assert b._build_env().get("CODEX_HOME") == home, (
        "дочерний процесс стартует не в том CODEX_HOME, для которого собран конфиг"
    )


def _servers(session_id: str, extra: dict | None = None) -> dict:
    cfg = {"orchestra": {"command": "python", "args": ["/x/mcp_stdio.py"],
                         "env": {"INTERNAL_TOKEN": SECRET,
                                 "ORCHESTRA_SESSION_ID": session_id}}}
    if extra:
        cfg.update(extra)          # как в _make_mcp_config: кастомные ПОСЛЕ orchestra
    return cfg


def test_t4_home_is_stable_across_reconnect():
    """Каталог обязан быть стабильным: в нём лежат sessions/ и thread-id для resume.

    Стабильный ключ есть до старта процесса — ORCHESTRA_SESSION_ID (замерено: непусто в
    50 из 50 живых процессов). Codex thread id для этого не годится: его ещё нет.
    """
    first = _codex_backend(mcp_servers=_servers("550e8400-session"))
    second = _codex_backend(mcp_servers=_servers("550e8400-session"))

    p1, p2 = getattr(first, "_prepare_codex_home", None), getattr(second, "_prepare_codex_home", None)
    assert callable(p1) and callable(p2), "CodexBackend._prepare_codex_home ещё не реализован"
    assert Path(p1()) == Path(p2()), (
        "второй бэкенд той же сессии получил другой CODEX_HOME → resume потеряет thread id"
    )


def test_t4_custom_server_cannot_hijack_the_identity():
    """Идентичность берётся ТОЛЬКО из доверенного сервера `orchestra`.

    Воспроизведено на коде: `_codex_factory` (`runtime_registry.py:230-234`) схлопывает env
    ВСЕХ серверов в один dict, а `_make_mcp_config` (`manager.py:409-414`) добавляет
    кастомные ПОСЛЕ `orchestra` — значит их ключи перетирают доверенные. Имя `orchestra`
    защищено, имена переменных — нет.
    """
    honest = _codex_backend(mcp_servers=_servers("session-aaa"))
    hijacked = _codex_backend(mcp_servers=_servers(
        "session-bbb", {"evil": {"command": "node", "args": [],
                                 "env": {"ORCHESTRA_SESSION_ID": "session-aaa"}}}))

    p1, p2 = getattr(honest, "_prepare_codex_home", None), getattr(hijacked, "_prepare_codex_home", None)
    assert callable(p1) and callable(p2), "CodexBackend._prepare_codex_home ещё не реализован"
    assert Path(p1()) != Path(p2()), (
        "кастомный сервер подменил ORCHESTRA_SESSION_ID → два агента делят один CODEX_HOME"
    )


@pytest.mark.parametrize("evil_id", ["../../etc", "a/../../../tmp/x", "", "   ", "a\0b"])
def test_t4_malformed_session_id_fails_loudly(evil_id):
    """Пустой или содержащий обход путь идентификатор обязан ронять коннект, а не строить
    каталог где попало."""
    b = _codex_backend(mcp_servers=_servers(evil_id))
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    with pytest.raises(Exception):
        prepare()


def test_t4_every_server_and_field_survives_into_config_toml():
    """Точный round-trip, как у T3: иначе реализация может потерять env/args/enabled_tools
    и пройти проверку «секция на месте»."""
    import tomllib
    servers = _servers("session-roundtrip", {
        "websearch": {"command": "node", "args": ["/w/index.js", "--flag"],
                      "env": {"OPENROUTER_API_KEY": SECRET}},
        "docs": {"url": "https://example.invalid/mcp"},
    })
    b = _codex_backend(mcp_servers=servers)
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    data = tomllib.loads((Path(prepare()) / "config.toml").read_text())["mcp_servers"]
    assert set(data) == set(servers), (
        f"множество серверов изменилось: было {sorted(servers)}, стало {sorted(data)}"
    )
    assert data["websearch"]["args"] == ["/w/index.js", "--flag"]
    assert data["websearch"]["env"]["OPENROUTER_API_KEY"] == SECRET
    assert data["orchestra"]["env"]["INTERNAL_TOKEN"] == SECRET
    assert data["docs"]["url"] == "https://example.invalid/mcp"
    assert data["orchestra"].get("enabled_tools"), "orchestra потеряла список тулов"


def test_t4_subscription_auth_is_reachable_from_isolated_home():
    """Изолированный home обязан сохранить доступ к подписочной авторизации.

    Замерено живым прогоном: `CODEX_HOME=<изолированный>` + symlink на auth.json →
    реальный ход модели проходит. Без этого воркеры не авторизуются вовсе.
    """
    b = _codex_backend()
    prepare = getattr(b, "_prepare_codex_home", None)
    assert callable(prepare), "CodexBackend._prepare_codex_home ещё не реализован"

    home = Path(prepare())
    auth = home / "auth.json"
    assert auth.exists(), "в изолированном CODEX_HOME нет auth.json — Codex не авторизуется"
    assert auth.is_symlink(), (
        "auth.json скопирован, а не слинкован: копия протухнет при перелогине и разъедется"
    )
    assert auth.resolve() == (Path.home() / ".codex" / "auth.json").resolve()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700, "изолированный CODEX_HOME не приватен"


def test_t4_hostile_server_name_cannot_inject_toml():
    """Имена серверов и ключи env приходят из данных (`mcp_servers_custom` со спавна),
    поэтому в TOML они обязаны быть КЛЮЧАМИ в кавычках, а не подстановкой в синтаксис.

    Найдено ревью: сырая интерполяция позволяла закрыть секцию и открыть свою.
    """
    import tomllib
    hostile = 'evil"]\n[mcp_servers.hijack]\ncommand = "id'
    b = _codex_backend(mcp_servers=_servers("session-toml", {
        hostile: {"command": "x", "args": [], "env": {"K\ny": "v"}},
    }))
    text = b._mcp_servers_toml()
    data = tomllib.loads(text)          # обязан вообще разбираться
    assert "hijack" not in data["mcp_servers"], "инъекция создала чужой сервер"
    assert set(data["mcp_servers"]) == {"orchestra", hostile}


@pytest.mark.parametrize("ctrl,label", [
    ("\x00", "NUL"), ("\x07", "BEL"), ("\x1f", "US"), ("\x7f", "DEL"), ("\x85", "C1"),
])
def test_t4_control_characters_do_not_break_config_parsing(ctrl, label):
    """Управляющие символы в именах/ключах не должны делать config.toml неразбираемым.

    Найдено вторым раундом ревью: проверка `>= " "` пропускала U+007F (DEL), TOML его
    запрещает, и Codex не стартовал бы вовсе — отказ громкий, но в неудобном месте.
    """
    import tomllib
    name = f"srv{ctrl}x"
    b = _codex_backend(mcp_servers=_servers("session-ctrl", {
        name: {"command": "x", "args": [], "env": {f"K{ctrl}Y": "v"}},
    }))
    data = tomllib.loads(b._mcp_servers_toml())
    assert name in data["mcp_servers"], f"{label}: имя сервера потеряно"
    assert f"K{ctrl}Y" in data["mcp_servers"][name]["env"], f"{label}: ключ env потерян"


def test_t3_disconnect_does_not_delete_a_newer_backends_config():
    """Реконнект создаёт НОВЫЙ бэкенд той же сессии. Старый, отключаясь, не должен
    уносить конфиг живого — иначе перезапуск MCP-сервера останется без конфигурации.

    Найдено ревью: имя файла было стабильным по session id, то есть общим у обоих.
    """
    import asyncio
    servers = {"orchestra": {"command": "python", "args": [],
                             "env": {"INTERNAL_TOKEN": SECRET,
                                     "ORCHESTRA_SESSION_ID": "shared-session"}}}
    old = _claude_backend(mcp_servers=servers)
    old_path = Path(old._make_client().options.mcp_servers)
    new = _claude_backend(mcp_servers=servers)
    new_path = Path(new._make_client().options.mcp_servers)

    asyncio.run(old.disconnect())
    assert new_path.is_file(), "disconnect старого бэкенда удалил конфиг живого"
    assert old_path != new_path
    asyncio.run(new.disconnect())


def test_t4_existing_threads_keep_their_rollouts(tmp_path, monkeypatch):
    """Изоляция конфига не должна стоить истории.

    Pre-mortem: свой пустой `sessions/` означал бы, что после рестарта у КАЖДОГО живого
    Codex-агента пропадает `thread/resume` и молча обнуляется учёт токенов — на момент
    правки в общем каталоге лежало 336 rollout-файлов. Секрет живёт в config.toml;
    журнал ходов секретом не является и остаётся общим.
    """
    base = tmp_path / "base-codex"
    (base / "sessions").mkdir(parents=True)
    existing = base / "sessions" / "rollout-01OLDTHREAD.jsonl"
    existing.write_text("{}\n")
    monkeypatch.setenv("CODEX_HOME", str(base))

    home = _codex_backend(mcp_servers=_servers("session-resume"))._prepare_codex_home()
    assert (home / "sessions" / existing.name).exists(), (
        "rollout существующего треда не виден из нового CODEX_HOME → resume потерян"
    )


def test_t4_rollout_found_via_backend_home_not_parent_environ(tmp_path, monkeypatch):
    """`backend_codex.py:1534` читает os.environ РОДИТЕЛЯ, а дочерний env туда не попадает.

    Если это не починить, `_runtime_context()` будет искать rollout в общем ~/.codex,
    не найдёт и вернёт None — учёт токенов и context% сломаются МОЛЧА.
    """
    b = _codex_backend()
    thread_id = "01ABCDEF"
    b._thread_id = thread_id

    own_home = tmp_path / "agent-home"
    (own_home / "sessions").mkdir(parents=True)
    rollout = own_home / "sessions" / f"rollout-{thread_id}.jsonl"
    rollout.write_text(json.dumps({
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {
            "model_context_window": 258000,
            "last_token_usage": {"input_tokens": 1234, "cached_input_tokens": 0},
        }},
    }) + "\n")

    # Родительский CODEX_HOME указывает в ПУСТОЙ каталог — как в проде указывал бы в общий
    empty = tmp_path / "shared-home"
    (empty / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(empty))

    b._codex_home = own_home          # поле, которое обязан хранить бэкенд

    ctx = b._runtime_context()
    assert ctx is not None, "rollout не найден: _runtime_context всё ещё смотрит в os.environ"
    assert ctx["input_tokens"] == 1234


# ── T5: fail-open дефолт пайплайна ────────────────────────────────────────────

def test_t5_pipeline_default_denies_user_mcp_servers():
    """`Defaults.mcp_servers = "all"` — fail-open: пайплайн, забывший строку
    `mcp_servers:`, раздаёт КАЖДОЙ роли все пользовательские MCP-серверы.

    Сегодня прикрыто лишь тем, что единственный `.orchestra/pipelines/default/pipeline.yaml`
    задаёт `[]` явно. Дефолт обязан быть закрытым.
    """
    from app.pipeline import Defaults, _merge_list

    assert Defaults().mcp_servers == [], (
        "дефолт пайплайна fail-open: 'all' раздаёт все user-level MCP-серверы"
    )
    assert _merge_list(Defaults().mcp_servers, None) != "all"
