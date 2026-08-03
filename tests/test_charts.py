"""Тесты тула визуализации (#20).

Главный здесь — test_fact_line_describes_drawn_window_not_source: подпись обязана
описывать нарисованный срез, а не исходный массив.
"""
import datetime as dt
import json
from pathlib import Path

import pytest
from PIL import Image

from app import charts
from app.charts import ChartError, render_chart

# C1 — docs/tasks/13/report.md, вес ответа /api/usage/history
C1 = {
    "unit": "МБ",
    "categories": ["1 сут", "7 сут", "30 сут", "год"],
    "series": [{"name": "до", "values": [0.178, 1.057, 4.248, 4.248], "tone": "bad"},
               {"name": "после", "values": [0.173, 0.413, 0.857, 0.857], "tone": "good"}],
}


@pytest.fixture(autouse=True)
def chart_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, "CHART_DIR", tmp_path / "charts")
    return tmp_path / "charts"


def _bars(**over):
    data = json.loads(json.dumps(C1))
    data.update(over)
    return data


def _colour_pixels(path, hex_colour, y_from=0):
    """Считает пиксели цвета. y_from отсекает шапку: в легенде лежат такие же квадратики."""
    rgb = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.open(path).convert("RGB")
    return sum(1 for y in range(y_from, im.height) for x in range(im.width)
               if im.getpixel((x, y)) == rgb)


# ── T1: столбцы ───────────────────────────────────────────────────────────────

def test_bars_renders_png_of_fixed_size(chart_dir):
    path = render_chart("bars", "Вес ответа", _bars())
    assert Path(path).stat().st_size > 0
    assert Image.open(path).size == (charts.W, charts.H)


def test_fact_line_is_computed_from_data(monkeypatch):
    """Числовую строку считает тул — вызывающий её не передаёт."""
    line = charts._fact_bars(C1["categories"], C1["series"], "МБ")
    assert line == "год: 4.25 → 0.857 МБ (5.0× меньше)"


def test_equal_ratios_break_tie_to_last_category():
    """«30 сут» и «год» дают одинаковые 4.96× — без тай-брейка тест был бы плавающим."""
    line = charts._fact_bars(C1["categories"], C1["series"], "МБ")
    assert line.startswith("год:") and "30 сут" not in line


def test_bars_log_keeps_smallest_bar_visible(chart_dir):
    """Ради этого лог-шкала и нужна: на линейной младший столбец выродился бы в полоску."""
    data = {"unit": "мс", "categories": ["p99", "max"],
            "series": [{"name": "2G", "values": [3807, 30000], "tone": "bad"},
                       {"name": "8G", "values": [44.2, 88], "tone": "good"}]}
    path = render_chart("bars_log", "Латентность", data)
    im = Image.open(path).convert("RGB")
    green = tuple(int(charts.PALETTE["ok"][i:i + 2], 16) for i in (1, 3, 5))
    rows = {y for x in range(im.width) for y in range(im.height)
            if im.getpixel((x, y)) == green}
    assert max(rows) - min(rows) >= 20


def test_bars_log_renders_zero_as_zero_not_as_small_bar(chart_dir):
    """«2254 → 0»: полоска у самого низа читалась бы как «мало», а это «ничего»."""
    data = {"unit": "за 15 с", "categories": ["high", "pgscan_direct"],
            "series": [{"name": "2G", "values": [2254, 854527], "tone": "bad"},
                       {"name": "8G", "values": [0, 0], "tone": "good"}]}
    path = render_chart("bars_log", "Давление в cgroup", data)
    assert _colour_pixels(path, charts.PALETTE["ok"], y_from=300) == 0   # столбца нет вовсе


def test_bars_log_rejects_negative():
    data = _bars(series=[{"name": "x", "values": [-1, 2, 3, 4]}])
    with pytest.raises(ChartError, match="логарифмической"):
        render_chart("bars_log", "t", data)


def test_value_label_shrinks_to_fit_the_bar():
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = charts._fit(d, "854 527", 130)
    assert font is not None and font.size < 34            # уменьшился
    assert d.textlength("854 527", font=font) <= 130      # и влез


def test_value_label_dropped_when_it_cannot_fit_at_any_size():
    """Лучше столбец без подписи, чем налезающие друг на друга цифры."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    assert charts._fit(d, "854 527", 40) is None


def test_long_title_fails_loudly_instead_of_being_clipped():
    with pytest.raises(ChartError, match="сократи"):
        render_chart("bars", "Э" * 200, _bars())


@pytest.mark.parametrize("data, message", [
    ({"categories": [], "series": C1["series"]}, "categories"),
    ({"categories": ["a"], "series": [{"name": "x", "values": [1]}]}, "cards"),
    ({"categories": list("abcdefghi"), "series": [{"name": "x", "values": [1] * 9}]}, "потолке"),
    ({"categories": ["a", "b"], "series": [{"name": "x", "values": [1]}]}, "на 2 категорий"),
    ({"categories": ["a", "b"], "series": [{"name": "x", "values": [1, float("nan")]}]}, "конечное"),
    ({"categories": ["a", "b"], "series": [{"name": "x", "values": [1, "два"]}]}, "не число"),
])
def test_bad_bars_data_fails_loudly(data, message):
    with pytest.raises(ChartError, match=message):
        render_chart("bars", "t", data)


def test_unknown_kind_lists_allowed():
    with pytest.raises(ChartError, match="bars_log"):
        render_chart("pie", "t", {})


def test_empty_title_rejected():
    with pytest.raises(ChartError, match="заголовок"):
        render_chart("bars", "   ", _bars())


# ── T2: ряд во времени ────────────────────────────────────────────────────────

def _series_points(start, count, step_min=5, skip=()):
    """Ряд с равным шагом; интервалы из skip выбрасываются — так делается провал."""
    out = []
    for i in range(count):
        t = start + dt.timedelta(minutes=step_min * i)
        if any(a <= i < b for a, b in skip):
            continue
        out.append([t.isoformat(), 50 + (i % 10)])
    return out


def test_fact_line_describes_drawn_window_not_source(chart_dir, monkeypatch):
    """СТРАЖ ТРЕБОВАНИЯ #20.

    В полной истории провал 9 ч 15 мин, но рисуем 7-суточный срез, где самый длинный
    провал 4 ч 5 мин. Подпись обязана назвать провал ЭТОГО окна.

    Проверяется строка, которая РЕАЛЬНО ушла на холст (перехват `_canvas`), а не
    результат вспомогательной функции: иначе тест был бы зелёным и в случае, когда
    рисуется совсем другой текст.
    """
    drawn = []
    real_canvas = charts._canvas
    monkeypatch.setattr(charts, "_canvas",
                        lambda title, fact: (drawn.append(fact), real_canvas(title, fact))[1])

    t0 = dt.datetime(2026, 7, 5, tzinfo=dt.timezone.utc)
    # 29 суток по пятиминуткам, как в живой БД, с двумя провалами:
    # ранний, длинный — (1110-999)*5 = 555 мин = 9 ч 15 мин,
    # поздний, короткий — (7048-6999)*5 = 245 мин = 4 ч 5 мин.
    full = _series_points(t0, 8352, skip=[(1000, 1110), (7000, 7048)])
    assert "9 ч 15 мин" in charts._fact_series(*_gaps_of(full)), "фикстура: длинный провал в полной истории"

    cut = dt.datetime.fromisoformat(full[-1][0]) - dt.timedelta(days=7)
    recent = [p for p in full if dt.datetime.fromisoformat(p[0]) >= cut]

    path = render_chart("series", "Расход лимита", {"unit": "%", "series": [
        {"name": "5h", "points": recent}]})
    assert Path(path).exists()
    assert len(drawn) == 1, "подпись рисуется ровно один раз"
    fact = drawn[0]
    assert "4 ч 5 мин" in fact, f"подпись обязана назвать провал НАРИСОВАННОГО окна: {fact}"
    assert "9 ч 15 мин" not in fact, f"подпись взята из исходного массива, а не из среза: {fact}"
    assert "7 суток" in fact, f"окно в подписи не совпадает с нарисованным: {fact}"


def _gaps_of(points):
    parsed = [(dt.datetime.fromisoformat(t), v) for t, v in points]
    gaps, _ = charts._find_gaps(parsed)
    span = (parsed[-1][0] - parsed[0][0]).total_seconds()
    return parsed, gaps, span


def test_fact_line_on_live_db_slice_matches_measured(chart_dir):
    """Живые данные: 7 суток из data/orchestra.db, сверено с БД в фазе 1."""
    raw = Path("docs/tasks/20/bench/usage_7d.json")
    if not raw.exists():
        pytest.skip("нет выгрузки живой БД")
    rows = json.loads(raw.read_text())
    fact = charts._fact_series(*_gaps_of([[r[0], r[1]] for r in rows]))
    assert "провалов" in fact and "7 суток" in fact


def test_series_without_gaps_says_so_and_draws_no_bands(chart_dir):
    pts = _series_points(dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc), 200)
    path = render_chart("series", "Ровный ряд", {"unit": "%", "series": [{"name": "x", "points": pts}]})
    assert "провалов нет" in charts._fact_series(*_gaps_of(pts))
    assert _colour_pixels(path, charts._GAP_FILL_MAX, y_from=300) == 0


def test_gap_breaks_the_line_instead_of_bridging_it(chart_dir):
    """Провал рисуется разрывом: линия сквозь дырку — выдуманные данные."""
    pts = _series_points(dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc), 300, skip=[(100, 200)])
    path = render_chart("series", "С провалом", {"unit": "%", "series": [{"name": "x", "points": pts}]})
    im = Image.open(path).convert("RGB")
    line = tuple(int(charts._CYCLE[0][i:i + 2], 16) for i in (1, 3, 5))
    parsed, gaps, _ = _gaps_of(pts)
    t0, t1 = parsed[0][0], parsed[-1][0]
    span = (t1 - t0).total_seconds()
    a, b = gaps[0]
    x_of = lambda t: charts.PL + (t - t0).total_seconds() / span * (charts.W - charts.PL - charts.PR)
    inside = range(int(x_of(a)) + 6, int(x_of(b)) - 6)
    hits = sum(1 for x in inside for y in range(im.height) if im.getpixel((x, y)) == line)
    assert hits == 0


def test_series_limits_and_bad_timestamps():
    ok = _series_points(dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc), 10)
    with pytest.raises(ChartError, match="потолке"):
        render_chart("series", "t", {"series": [{"name": f"s{i}", "points": ok} for i in range(4)]})
    with pytest.raises(ChartError, match="ISO-8601"):
        render_chart("series", "t", {"series": [{"name": "x", "points": [["вчера", 1], ["позавчера", 2]]}]})
    with pytest.raises(ChartError, match="минимум 2"):
        render_chart("series", "t", {"series": [{"name": "x", "points": [["2026-08-01T00:00:00", 1]]}]})


# ── T3: карточки ──────────────────────────────────────────────────────────────

CARDS = {"metrics": [
    {"label": ".md на диске", "value": "401", "note": "5.54 МБ"},
    {"label": "в индексе", "value": "315", "note": "78 %", "tone": "bad"},
    {"label": "не в индексе", "value": "86", "tone": "bad"},
    {"label": "фантомов", "value": "17", "tone": "bad"}]}


def test_cards_digits_are_big_enough_for_a_phone(chart_dir):
    """F2: то, что мельче ~60 px на холсте 1200, в пузыре Telegram не читается."""
    path = render_chart("cards", "Индекс RAG против диска", CARDS)
    assert Path(path).exists()
    bbox = charts._font(84, True).getbbox("401")
    assert bbox[3] - bbox[1] >= 60


def test_cards_tone_paints_value(chart_dir):
    path = render_chart("cards", "t", CARDS)
    assert _colour_pixels(path, charts.PALETTE["danger"], y_from=200) > 0   # у карточек легенды нет


def test_cards_count_limits():
    with pytest.raises(ChartError, match="от 2 до 4"):
        render_chart("cards", "t", {"metrics": [{"label": "a", "value": "1"}]})
    with pytest.raises(ChartError, match="потолке"):
        render_chart("cards", "t", {"metrics": [{"label": str(i), "value": "1"} for i in range(5)]})


def test_metric_without_value_rejected():
    with pytest.raises(ChartError, match="без value"):
        render_chart("cards", "t", {"metrics": [{"label": "a"}, {"label": "b", "value": ""}]})


# ── T4: чистка каталога ───────────────────────────────────────────────────────

def test_directory_is_pruned_to_keep(chart_dir, monkeypatch):
    monkeypatch.setattr(charts, "_KEEP", 3)
    for _ in range(5):
        render_chart("bars", "t", _bars())
    assert len(list(chart_dir.glob("*.png"))) == 3


# ── T4: тул send_chart ────────────────────────────────────────────────────────

@pytest.fixture
def mcp_mod(chart_dir, monkeypatch):
    from app import mcp_stdio
    monkeypatch.setattr(charts, "CHART_DIR", chart_dir)
    return mcp_stdio


@pytest.mark.asyncio
async def test_send_chart_draws_and_sends_in_one_call(mcp_mod, chart_dir, monkeypatch):
    sent = []

    async def fake_send_file(path, caption="", as_document=False):
        sent.append((path, caption))
        return f"File sent to TG: {path} (msg_id=1 chat_id=2)"

    monkeypatch.setattr(mcp_mod, "send_file", fake_send_file)
    out = await mcp_mod.send_chart("bars", "Вес ответа", _bars(), caption="подпись")

    assert len(sent) == 1, "картинка отправляется ровно один раз"
    path, caption = sent[0]
    assert Path(path).exists() and Path(path).parent == chart_dir
    assert caption == "подпись"
    assert path in out


@pytest.mark.asyncio
async def test_validation_error_never_reaches_telegram(mcp_mod, monkeypatch):
    async def fail(*a, **kw):
        raise AssertionError("send_file не должен вызываться на кривых данных")

    monkeypatch.setattr(mcp_mod, "send_file", fail)
    with pytest.raises(mcp_mod.ApiToolError) as exc:
        await mcp_mod.send_chart("bars", "t", {"categories": ["a"], "series": [{"name": "x", "values": [1]}]})
    assert "cards" in exc.value.message and exc.value.code == "domain_error"


@pytest.mark.asyncio
async def test_delivery_failure_keeps_the_file_and_reports_its_path(mcp_mod, chart_dir, monkeypatch):
    """Картинка нарисована — путь обязан дойти до агента, иначе работа потеряна."""
    async def boom(path, caption="", as_document=False):
        raise mcp_mod.ApiToolError(code="domain_error", message="Send failed: network error")

    monkeypatch.setattr(mcp_mod, "send_file", boom)
    with pytest.raises(mcp_mod.ApiToolError) as exc:
        await mcp_mod.send_chart("bars", "Вес ответа", _bars())

    files = list(chart_dir.glob("*.png"))
    assert len(files) == 1 and files[0].stat().st_size > 0
    assert str(files[0]) in exc.value.message
    assert exc.value.details["chart_path"] == str(files[0])


@pytest.mark.asyncio
async def test_tool_is_registered_and_visible(mcp_mod):
    names = {t.name for t in mcp_mod.mcp._tool_manager.list_tools()}
    assert "send_chart" in names
    assert "send_chart" not in mcp_mod.READ_ONLY_MCP_TOOLS, "рисование — не read-only операция"
