"""Собрать витрину дизайн-системы из НАСТОЯЩЕГО design-system.css (V-876).

Витрина не держит своих цветов: CSS вклеивается из app/static/css/design-system.css,
поэтому она не разойдётся с дашбордом. Пересборка после правки токенов:
    python3 .orchestra/tasks/V-876/build_showcase.py
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = (ROOT / "app/static/css/design-system.css").read_text()
OUT = Path(__file__).with_name("showcase.html")

root = CSS[CSS.index(":root {"):CSS.index("}", CSS.index(":root {"))]
tokens = re.findall(r"(--[\w-]+):\s*([^;]+);", root)
groups = {
    "Модели": [t for t in tokens if t[0].startswith("--model-") and not t[0].endswith("-soft")],
    "Поставщики и пулы": [t for t in tokens if t[0].startswith("--provider-")],
    "Статусы агента": [t for t in tokens if t[0].startswith("--status-") and not t[0].endswith("-bg")],
    "Смысл": [t for t in tokens if t[0].split("-")[2] in {"ok", "warn", "danger", "info"} or t[0] in {"--ok", "--warn", "--danger", "--info"}],
    "Акцент": [t for t in tokens if t[0].startswith("--accent")],
    "Поверхности и границы": [t for t in tokens if t[0].startswith(("--bg", "--surface", "--border"))],
    "Текст": [t for t in tokens if t[0].startswith("--ink")],
}
MODELS = [("opus", "Opus 5.5 (1M)", "claude-opus-5-5[1m]"), ("sonnet", "Sonnet 5.5 (1M)", "claude-sonnet-5-5[1m]"),
          ("haiku", "Haiku 5.5", "claude-haiku-5-5"), ("fable", "Fable 5.1", "claude-fable-5-1[1m]"),
          ("luna", "GPT-6 Luna", "gpt-6-luna"), ("sol", "GPT-6.1 Sol", "gpt-6.1-sol"),
          ("astra", "GPT-6 Astra", "gpt-6-astra"), ("spark", "GPT-5.3 Codex Spark", "gpt-5.3-codex-spark"),
          ("grok", "Grok 4.6", "grok-4.6")]
STATUSES = [("running", "⚡ выполняется"), ("waiting", "📆 ждёт"), ("idle", "☕️ простаивает"),
            ("broken", "⛔ сломан"), ("error", "● ошибка"), ("starting", "● запускается"), ("stopped", "● остановлен")]


def swatch(name, value):
    return (f'<div class="sw"><i style="background:var({name})"></i><div><code>{html.escape(name)}</code>'
            f'<small>{html.escape(value.split("/*")[0].strip())}</small></div></div>')


palette = "".join(
    f'<section class="panel"><h3>{g}</h3><div class="sws">{"".join(swatch(*t) for t in items)}</div></section>'
    for g, items in groups.items()
)
model_rows = "".join(
    f'<tr><td><span class="ds-model" style="--ds-c:var(--model-{f})">{l}</span></td>'
    f'<td><span class="ds-model ds-pill" style="--ds-c:var(--model-{f})">{l}</span></td>'
    f'<td><span class="ds-model-dot" style="--ds-c:var(--model-{f})"></span></td>'
    f'<td><span class="ds-model-text" style="--ds-c:var(--model-{f})">{i}</span></td>'
    f'<td><code>--model-{f}</code></td></tr>'
    for f, l, i in MODELS
)
status_row = "".join(f'<span class="ds-status" data-status="{s}">{t}</span>' for s, t in STATUSES)
dot_row = "".join(f'<span class="ds-status-dot" data-status="{s}">●</span> <small>{s}</small> ' for s, _ in STATUSES)

page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orchestra — дизайн-система</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='4' cy='8' r='3' fill='%23fb923c'/%3E%3Ccircle cx='8' cy='8' r='3' fill='%2338bdf8'/%3E%3Ccircle cx='12' cy='8' r='3' fill='%232dd4bf'/%3E%3C/svg%3E">
<style>
{CSS}
/* оформление самой витрины */
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f5f5f7; color: #1d1d1f; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
header {{ padding: 20px 28px 8px; }} h1 {{ font-size: 23px; margin: 0 0 4px; }} header p {{ margin: 0; color: #555; max-width: 900px; }}
main {{ padding: 8px 28px 32px; display: grid; gap: 14px; }}
h2 {{ font-size: 16px; margin: 10px 0 0; }}
.dark {{ background: var(--bg); color: var(--ink-body); border-radius: 12px; padding: 14px 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr)); gap: 12px; }}
.panel {{ background: var(--surface); border: 1px solid var(--border-soft); border-radius: 10px; padding: 10px 12px; }}
.panel h3 {{ margin: 0 0 8px; font-size: 13px; color: var(--ink); }}
.sws {{ display: grid; gap: 6px; }} .sw {{ display: flex; gap: 8px; align-items: center; }}
.sw i {{ width: 26px; height: 18px; border-radius: 4px; border: 1px solid rgba(255,255,255,.12); flex: none; }}
.sw code {{ color: var(--ink); font: 11px var(--font-mono); display: block; }} .sw small {{ color: var(--ink-dim); font: 10px var(--font-mono); }}
table {{ border-collapse: collapse; width: 100%; }} td, th {{ padding: 5px 8px; border-bottom: 1px solid var(--border-soft); text-align: left; font-size: 12px; }}
th {{ color: var(--ink-dim); font-weight: 600; font-size: 11px; }} td code {{ color: var(--ink-muted); font: 11px var(--font-mono); }}
.row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
.rules {{ background: #fff; border-radius: 12px; padding: 12px 18px; }} .rules li {{ margin: 3px 0; }}
.demo-agent {{ display: flex; gap: 10px; align-items: center; padding: 8px 10px; border-left: 3px solid #818cf8; border-radius: 8px; background: rgba(99,102,241,.08); max-width: 340px; }}
@media print {{ .dark {{ break-inside: avoid; }} }}
</style></head><body>
<header><h1>Orchestra — дизайн-система дашборда</h1>
<p>Все цвета ниже вклеены из <code>app/static/css/design-system.css</code> — того же файла, что грузит дашборд. Одна модель — один цвет на всех экранах; статус — иконка + цвет; поверхности и текст — общая шкала. Брендбук: <code>docs/design-system.md</code>.</p></header>
<main>
<h2>Модели — бейдж, пилюля, точка, текст</h2>
<div class="dark" style="overflow-x:auto"><table><tr><th>ds-model (список агентов, «Инфо»)</th><th>ds-model ds-pill (чат)</th><th>ds-model-dot (вкладки)</th><th>ds-model-text (строка «Модель»)</th><th>токен</th></tr>{model_rows}</table></div>
<h2>Статусы агента</h2>
<div class="dark"><div class="row">{status_row}</div><div class="row" style="margin-top:10px">{dot_row}</div></div>
<h2>Кнопки, чипы, карточка</h2>
<div class="dark"><div class="row">
<button class="ds-btn">Обычная</button><button class="ds-btn ds-btn-primary">Отправить</button>
<button class="ds-btn ds-btn-danger">Остановить</button><button class="ds-btn ds-btn-ghost">Ghost</button><button class="ds-btn" disabled>Disabled</button>
<span class="ds-chip">нейтральный</span><span class="ds-chip" data-tone="ok">открыт</span><span class="ds-chip" data-tone="warn">гейт</span><span class="ds-chip" data-tone="danger">заблокирован</span><span class="ds-chip" data-tone="accent">оркестратор</span>
</div>
<div class="grid" style="margin-top:12px">
<div class="ds-card"><div class="row" style="justify-content:space-between"><span class="ds-card-title"><span class="ds-status-dot" data-status="running">●</span> design-system</span><span class="ds-model" style="--ds-c:var(--model-opus)">Opus 5.5 (1M)</span></div><div class="ds-card-meta">выполняется · обновлён 11:06</div></div>
<div class="demo-agent"><span>⚙️</span><div style="flex:1"><div class="row" style="justify-content:space-between"><span style="font-size:12px">feat-voice</span><span class="ds-status" data-status="running">⚡ выполняется</span></div><div class="row" style="margin-top:3px"><span class="ds-model" style="--ds-c:var(--model-luna)">GPT-6 Luna</span><span style="margin-left:auto;color:var(--ok-soft);font-size:12px">$1.48</span></div></div></div>
</div></div>
<h2>Палитра токенов</h2>
<div class="dark"><div class="grid">{palette}</div></div>
<div class="rules"><h2>Когда что использовать</h2><ul>
<li>Название модели в интерфейсе → <code>modelBadge(id)</code> / <code>modelBadgeHtml(id)</code> из theme.js; цвет выбирается по семейству (opus, sonnet, luna…), неизвестная модель — цвет поставщика.</li>
<li>Статус агента → <code>.ds-status[data-status]</code> с иконкой из <code>_STATUS_ICON</code> и подписью <code>T(status)</code>; одна только точка — <code>.ds-status-dot</code>.</li>
<li>Canvas, Chart.js, SVG-атрибуты → <code>modelColor()</code>, <code>providerColor()</code>, <code>cssToken('--…')</code>: туда <code>var()</code> не подставится.</li>
<li>Новый hex в style.css или JS не пишем: нужен новый смысл — новый токен в design-system.css.</li>
</ul></div>
</main></body></html>"""
OUT.write_text(page)
print(OUT, len(page))
