"""T8 (#314): деградация снимается БЕЗ рестарта — проверяется решением, а не полем.

Замороженный RED-оракул гейта плана. Требование оркестратора дословно: проверить прогоном, что
снятие деградации через политику действительно меняет решение гейта, а не что «поле есть».
Основание — уже случавшийся у нас случай, когда горячая правка манифеста считалась работающей,
а на деле требовала перезапуска процесса.

Поэтому ключевая проверка здесь — РАЗНЫЙ ответ гейта на два вызова в ОДНОМ процессе, между
которыми не было ни рестарта, ни переимпорта модуля. Тождество модуля проверяется явно: без
этого тест зеленел бы и на реализации, которая читает политику один раз при импорте, — её
достаточно было бы перезагрузить между вызовами, и «горячесть» осталась бы недоказанной.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import app.db as db
import app.quota_gate as quota_gate

MODEL = "claude-opus-5[1m]"
CALM_UTILIZATION = 70.0  # заведомо ниже процентного предела: решать должен только дефицит


def _observation_loader(utilization: float):
    """Наблюдение в форме, которую отдаёт `current_quota_observation`."""
    bucket = quota_gate.quota_bucket_for_model(MODEL)
    resets_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    async def loader(*, required_provider=None):
        return {
            "providers": {
                bucket: {
                    "label": "Claude",
                    "windows": [
                        {
                            "id": "seven_day",
                            "window_minutes": 10080,
                            "utilization": utilization,
                            "resets_at": resets_at,
                        }
                    ],
                }
            },
            "observed_at_by_provider": {bucket: datetime.now(timezone.utc).timestamp()},
        }

    return loader


def _set_deficit_policy(*, deficit_hours, min_work_hours=1.0):
    """Записать порог дефицита в горячую политику полосы claude.

    `None` в `deficit_hours` = деградация по дефициту выключена оператором.
    """
    setter = getattr(db, "set_runway_policy", None)
    assert setter is not None, "app.db.set_runway_policy не существует"
    setter(
        lane="claude",
        deficit_hours=deficit_hours,
        min_work_hours=min_work_hours,
        source="test",
        reason="T8 reversibility oracle",
    )


def _decide(utilization: float):
    return asyncio.run(
        quota_gate.get_worker_admission(MODEL, _observation_loader(utilization))
    )


def _force_deficit(monkeypatch, deficit: float | None):
    """Подставить дефицит, не завися от реальной истории `usage_snapshots`.

    Оракул про ОБРАТИМОСТЬ, а не про расчёт дефицита: расчёт закрыт своими тестами, а живая
    история в тестовой БД пуста. Величину подаём через тот же seam, которым её возьмёт T3.
    """
    provider = getattr(quota_gate, "current_runway_deficit", None)
    assert provider is not None, "app.quota_gate.current_runway_deficit не существует"
    monkeypatch.setattr(
        quota_gate, "current_runway_deficit", lambda *a, **k: deficit, raising=True
    )


def test_disable_takes_effect_without_restart(monkeypatch):
    """Два вызова, один процесс, между ними — только запись в политику."""
    _force_deficit(monkeypatch, 41.0)

    module_before = sys.modules["app.quota_gate"]

    _set_deficit_policy(deficit_hours=34.0)
    degraded = _decide(CALM_UTILIZATION)
    assert degraded.binding_constraint == "runway_deficit", (
        "предпосылка теста: при пороге 34 и дефиците 41 гейт обязан деградировать"
    )
    assert degraded.allowed is True, "деградация не имеет права превращаться в отказ"

    _set_deficit_policy(deficit_hours=None)
    restored = _decide(CALM_UTILIZATION)

    assert restored.binding_constraint == "none", (
        "снятие порога не подействовало без рестарта"
    )
    assert sys.modules["app.quota_gate"] is module_before, (
        "модуль был переимпортирован — 'горячесть' не доказана"
    )


def test_raising_threshold_above_deficit_also_reverses(monkeypatch):
    """Обратимость не только выключателем: поднятый порог снимает деградацию тем же путём."""
    _force_deficit(monkeypatch, 41.0)

    _set_deficit_policy(deficit_hours=34.0)
    assert _decide(CALM_UTILIZATION).binding_constraint == "runway_deficit"

    _set_deficit_policy(deficit_hours=90.0)
    assert _decide(CALM_UTILIZATION).binding_constraint == "none"


def test_policy_write_is_audited(monkeypatch):
    """Снятие деградации оставляет след: иначе неизвестно, почему окно вышло чистым.

    Через два месяца (§5.3 research) окно без срабатываний должно быть отличимо от окна, в
    котором оператор выключил механизм.
    """
    _force_deficit(monkeypatch, 41.0)
    _set_deficit_policy(deficit_hours=34.0)
    _set_deficit_policy(deficit_hours=None)

    # ПЕРЕЗАМОРОЖЕНО 19.08: оракул назвал `quota_policy_audit_rows`, но такая функция уже
    # существует под именем `quota_policy_audit` (`app/db.py`). Заводить второе имя для
    # той же мысли — прямое нарушение «один owner», поэтому имя в оракуле исправлено на
    # существующее. Реплеев от прежнего коммита не было, менять больше нечего.
    reader = getattr(db, "quota_policy_audit", None)
    assert reader is not None, "app.db.quota_policy_audit не существует"
    reasons = [row["reason"] for row in reader(limit=10)]
    assert any("T8 reversibility oracle" in str(item) for item in reasons)
