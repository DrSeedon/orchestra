"""#224 T6 — telegram-bot-api: API ID и hash уезжают из ExecStart в EnvironmentFile.

Юнит на машине: `-rw-r--r-- root root`, то есть world-readable, а значения стоят прямо
в `ExecStart` — и потому же попадают в argv процесса (в БД уже 14 строк с `--api-hash=`).

Установку юнита и `daemon-reload` НЕ делаем — окно у владельца. Проверяем ПОДГОТОВЛЕННЫЙ
артефакт: это delivery-check, а не поведенческий тест.

Тест написан ДО артефакта и коммитится КРАСНЫМ.
"""
import re
from pathlib import Path

PREPARED = Path(__file__).resolve().parent.parent / "docs" / "tasks" / "224" / "telegram-bot-api"
UNIT = PREPARED / "telegram-bot-api.service"
ENVFILE_EXAMPLE = PREPARED / "telegram-bot-api.env.example"
RUNBOOK = PREPARED / "INSTALL.md"


def test_t6_prepared_unit_exists():
    assert UNIT.is_file(), f"подготовленный юнит не создан: {UNIT}"


def test_t6_unit_has_no_inline_credentials():
    """Флаги убираются ЦЕЛИКОМ, а не заменяются ссылкой на переменную.

    `ExecStart=... --api-id=${TELEGRAM_API_ID}` systemd развернёт, и значение окажется в
    `/proc/<pid>/cmdline` — то есть главная утечка (14 строк с `--api-hash=` в БД пришли
    из `ps`) осталась бы незакрытой. Бинарник читает TELEGRAM_API_ID/TELEGRAM_API_HASH
    из окружения сам, поэтому флаг не нужен ни в каком виде.
    """
    assert UNIT.is_file(), f"подготовленный юнит не создан: {UNIT}"
    text = UNIT.read_text()

    # подстрокой, без исключений: голый `--api-id` в конце строки тоже недопустим
    assert "--api-id" not in text, "--api-id всё ещё в юните (в любом виде)"
    assert "--api-hash" not in text, "--api-hash всё ещё в юните (в любом виде)"
    assert "EnvironmentFile=" in text, "EnvironmentFile= не объявлен"
    assert "ExecStart=" in text, "юнит без ExecStart нерабочий"


def test_t6_env_example_carries_no_real_values():
    """Образец в репозитории обязан быть пустым по значениям — файл трекается git."""
    assert ENVFILE_EXAMPLE.is_file(), f"образец env не создан: {ENVFILE_EXAMPLE}"
    text = ENVFILE_EXAMPLE.read_text()

    assert "TELEGRAM_API_ID=" in text and "TELEGRAM_API_HASH=" in text
    # плейсхолдер, а не значение: ни длинного hex, ни длинного числа
    assert not re.search(r"TELEGRAM_API_HASH=[0-9a-f]{8,}", text), "в образце реальный hash"
    assert not re.search(r"TELEGRAM_API_ID=\d{4,}", text), "в образце реальный api-id"


def test_t6_runbook_names_owner_window_commands():
    """Команды владелец выполняет сам — они обязаны быть выписаны дословно."""
    assert RUNBOOK.is_file(), f"инструкция не создана: {RUNBOOK}"
    text = RUNBOOK.read_text()

    assert "daemon-reload" in text
    assert "chmod 600" in text
    assert "systemctl restart telegram-bot-api" in text


def test_t6_runbook_carries_the_post_install_proof():
    """Delivery-check доказывает только ТЕКСТ. Что значение ушло из argv живого процесса,
    доказывает команда после установки — и она обязана быть в инструкции дословно,
    иначе её никто не выполнит."""
    assert RUNBOOK.is_file(), f"инструкция не создана: {RUNBOOK}"
    text = RUNBOOK.read_text()

    assert "ps -o args= -C telegram-bot-api" in text, "нет проверки argv живого процесса"
    assert "--api-" in text, "проверка argv не называет, что именно искать"
    assert "systemctl is-active" in text, "нет проверки, что сервис поднялся"
