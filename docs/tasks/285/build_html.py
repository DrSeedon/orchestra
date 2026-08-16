#!/usr/bin/env python3
"""Build the self-contained offline HTML view for #285."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def compact_timeline(points: list[dict[str, Any]], stride: int = 1) -> list[dict[str, Any]]:
    kept = []
    prior_band = None
    for index, point in enumerate(points):
        value = point["utilization"]
        band = 100 if value >= 100 else 95 if value >= 95 else 90 if value >= 90 else 80 if value >= 80 else 0
        if index == 0 or index == len(points) - 1 or index % stride == 0 or band != prior_band:
            kept.append({"t": point["ts"], "u": value, "plan": point.get("plan"), "b": point.get("break_before", False)})
        prior_band = band
    return kept


def build_payload(data: dict[str, Any]) -> dict[str, Any]:
    live = data["live_read_only_capture"]
    canonical = data["canonical_observed_thresholds"]["summary"]
    thresholds: dict[str, dict[str, float]] = {}
    for row in canonical:
        key = f"{row['provider']}.{row['window_id']}"
        thresholds.setdefault(key, {})[str(row["threshold_pct"])] = round(row["observed_duration_seconds"] / 3600, 3)
    series_map = {
        "claude.five_hour": "Claude 5h",
        "claude.seven_day": "Claude 7d",
        "codex.primary": "Codex main",
        "codex.spark": "Spark",
        "grok.weekly": "Grok 7d",
    }
    series = [
        {"id": key, "label": label, "points": compact_timeline(data["timeline_series"].get(key, []))}
        for key, label in series_map.items()
    ]
    fan = data["research_fan_usage"]["agents"]
    return {
        "generated": data["generated_at"],
        "live": live,
        "thresholds": thresholds,
        "series": series,
        "transition": {
            "at": data["codex_plan_transition"]["first_pro_ts"],
            "rows": data["codex_plan_transition"]["snapshot_rows"],
        },
        "fan": fan,
        "grokTurns": data["grok_evidence"]["real_turns"],
        "controller": data["controller_99"],
    }


TEMPLATE = r'''<!doctype html>
<html lang="ru" data-theme="auto">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Orchestra · лимиты моделей — source of truth</title>
  <style>
    :root {
      color-scheme: light dark;
      --font-sans: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: ui-monospace, "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      --bg: light-dark(#f5f3ee, #0c1116); --panel: light-dark(#fffdfa, #131a21);
      --panel2: light-dark(#efede7, #19232c); --ink: light-dark(#172027, #e8edf0);
      --muted: light-dark(#687077, #93a0a9); --line: light-dark(#d8d4cb, #2b3944);
      --accent: light-dark(#0c766f, #64d8ce); --accent2: light-dark(#a35016, #f2a65a);
      --danger: light-dark(#a33131, #ff8585); --ok: light-dark(#32734a, #72d995);
      --shadow: 0 16px 40px light-dark(#1d2a3020, #00000055);
    }
    html[data-theme="light"] { color-scheme: light; --bg:#f5f3ee;--panel:#fffdfa;--panel2:#efede7;--ink:#172027;--muted:#687077;--line:#d8d4cb;--accent:#0c766f;--accent2:#a35016;--danger:#a33131;--ok:#32734a;--shadow:0 16px 40px #1d2a3020 }
    html[data-theme="dark"] { color-scheme: dark; --bg:#0c1116;--panel:#131a21;--panel2:#19232c;--ink:#e8edf0;--muted:#93a0a9;--line:#2b3944;--accent:#64d8ce;--accent2:#f2a65a;--danger:#ff8585;--ok:#72d995;--shadow:0 16px 40px #00000055 }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-sans);line-height:1.45}
    a{color:var(--accent)} button,select,input{font:inherit}.wrap{max-width:1240px;margin:auto;padding:28px}
    .top{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:24px}
    h1{font-size:clamp(2rem,5vw,4.8rem);letter-spacing:-.055em;line-height:.94;margin:.2rem 0 1rem;max-width:850px}
    h2{font-size:clamp(1.35rem,2.5vw,2.2rem);letter-spacing:-.035em;margin:0 0 16px} h3{margin:0 0 8px;font-size:1.05rem}
    p{margin:.35rem 0}.eyebrow,.mono{font-family:var(--font-mono);font-size:.78rem;letter-spacing:.055em;text-transform:uppercase}
    .eyebrow{color:var(--accent)}.muted{color:var(--muted)}.danger{color:var(--danger)}.ok{color:var(--ok)}
    .theme{border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:9px 12px;border-radius:999px;cursor:pointer}
    .hero-note{max-width:750px;font-size:1.08rem;color:var(--muted)}
    .grid{display:grid;gap:14px}.kpis{grid-template-columns:repeat(4,minmax(0,1fr));margin:24px 0}
    .card,.section{background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow)}
    .card{padding:18px;min-height:150px;position:relative;overflow:hidden}.card::after{content:"";position:absolute;width:90px;height:90px;border-radius:50%;right:-35px;top:-35px;background:color-mix(in srgb,var(--accent) 15%,transparent)}
    .value{font-size:2.6rem;font-weight:720;letter-spacing:-.055em;margin:.25rem 0}.sub{font-size:.86rem;color:var(--muted)}
    .section{padding:24px;margin:18px 0}.section-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:18px}
    .filters{display:flex;flex-wrap:wrap;gap:8px}.pill{border:1px solid var(--line);background:var(--panel2);color:var(--muted);padding:7px 10px;border-radius:999px;cursor:pointer}
    .pill[aria-pressed="true"]{color:var(--ink);border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
    .poolmap{grid-template-columns:repeat(3,minmax(0,1fr))}.pool{padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--panel2)}
    .relation{display:inline-block;padding:3px 7px;border-radius:6px;background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent);font:700 .72rem var(--font-mono)}
    .chart-wrap{position:relative;height:330px;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--panel2)}
    #chart{width:100%;height:100%;display:block}.tooltip{position:absolute;display:none;pointer-events:none;background:var(--ink);color:var(--bg);padding:7px 9px;border-radius:8px;font:12px var(--font-mono);z-index:3;white-space:nowrap}
    .legend{display:flex;gap:15px;flex-wrap:wrap;margin-top:10px;font-size:.8rem;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}
    .bars{display:grid;gap:10px}.bar-row{display:grid;grid-template-columns:150px 1fr 86px;gap:10px;align-items:center;font-size:.86rem}.track{height:11px;background:var(--panel2);border-radius:99px;overflow:hidden}.fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:99px}
    .controller{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:18px}.controls{display:grid;grid-template-columns:1fr 1fr;gap:14px}.control{padding:14px;background:var(--panel2);border-radius:12px}.control label{display:flex;justify-content:space-between;font-size:.83rem;color:var(--muted)}input[type=range]{width:100%;accent-color:var(--accent)}
    .zone{border-left:5px solid var(--accent);padding:18px;background:var(--panel2);border-radius:12px}.zone strong{font-size:1.8rem;letter-spacing:-.04em}.formula{font:13px/1.6 var(--font-mono);padding:12px;border:1px dashed var(--line);border-radius:10px;margin-top:12px}
    .steps{counter-reset:step;display:grid;gap:8px}.step{display:grid;grid-template-columns:32px 1fr;gap:10px}.step::before{counter-increment:step;content:counter(step);width:28px;height:28px;display:grid;place-items:center;border-radius:50%;background:var(--accent);color:var(--bg);font:bold 13px var(--font-mono)}
    table{width:100%;border-collapse:collapse;font-size:.86rem}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font:700 .72rem var(--font-mono);text-transform:uppercase;color:var(--muted)}
    .callout{border-left:4px solid var(--accent2);padding:13px 15px;background:color-mix(in srgb,var(--accent2) 10%,var(--panel));border-radius:0 12px 12px 0}.two{grid-template-columns:1fr 1fr}.footer{padding:28px 0 8px;color:var(--muted);font-size:.8rem}
    [data-provider].hidden{display:none!important}
    @media(max-width:900px){.kpis,.poolmap,.two{grid-template-columns:1fr 1fr}.controller{grid-template-columns:1fr}.top{align-items:center}.chart-wrap{height:280px}}
    @media(max-width:600px){.wrap{padding:18px}.kpis,.poolmap,.two,.controls{grid-template-columns:1fr}.section{padding:17px}.section-head{display:block}.filters{margin-top:12px}.bar-row{grid-template-columns:110px 1fr 62px}.top{gap:8px}.theme{white-space:nowrap}}
    @media print{html,html[data-theme="dark"],html[data-theme="light"]{color-scheme:light;--bg:#fff;--panel:#fff;--panel2:#f3f3f0;--ink:#111820;--muted:#5b646b;--line:#bfc3c5;--accent:#0c766f;--accent2:#a35016;--danger:#a33131;--ok:#32734a;--shadow:none}.theme,.filters,.interactive-only{display:none!important}body{background:#fff;color:var(--ink)}.wrap{max-width:none;padding:0}.card,.section{box-shadow:none;break-inside:avoid;border-color:#bbb}.section{page-break-inside:avoid}.chart-wrap{background:#fff;height:260px}a{color:#111;text-decoration:none}.kpis{grid-template-columns:repeat(4,1fr)}h1{font-size:42px}}
  </style>
</head>
<body>
<main class="wrap">
  <header class="top">
    <div><div class="eyebrow">Orchestra / #285 / source of truth</div><h1>Лимиты — это граф, не один процент.</h1><p class="hero-note">Измеренные окна, реальные turns и контроллер, который стремится к 99% у reset — без статичного stop-at-95 и без смешивания подписки с виртуальной API-ценой.</p></div>
    <button class="theme" id="theme" aria-label="Переключить тему">◐ тема</button>
  </header>

  <section class="grid kpis" aria-label="Состояние пулов">
    <article class="card" data-provider="claude"><div class="eyebrow">Claude weekly all</div><div class="value danger">100%</div><div class="sub">reset Tue 18 Aug · 06:59 UTC<br>Fable scoped 0%, но не extra pool</div></article>
    <article class="card" data-provider="codex"><div class="eyebrow">Codex main · pro</div><div class="value">4%</div><div class="sub">fresh live capture · 7d counter<br><span class="mono">prolite 97 → pro 24 → 0</span></div></article>
    <article class="card" data-provider="spark"><div class="eyebrow">Spark · separate</div><div class="value ok">0%</div><div class="sub">свой demand-adjusted limit<br>цена preview: unknown</div></article>
    <article class="card" data-provider="grok"><div class="eyebrow">Grok · laptop DB</div><div class="value danger">98%</div><div class="sub">08:57 UTC · reset через 10.9h<br>VPS token_expired ≠ quota</div></article>
  </section>

  <section class="section">
    <div class="section-head"><div><div class="eyebrow">Pool topology</div><h2>Какие кошельки связаны</h2></div><div class="filters" id="filters"></div></div>
    <div class="grid poolmap">
      <article class="pool" data-provider="claude"><span class="relation">AND gate</span><h3>Claude 5h + weekly all</h3><p>Turn проходит только при headroom обоих окон. Fable добавляет scoped constraint, но не ёмкость поверх weekly.</p></article>
      <article class="pool" data-provider="codex"><span class="relation">shared main</span><h3>Sol · Terra · Luna · Fast</h3><p>Один Codex/ChatGPT agentic pool. Luna растягивает его; Fast GPT‑5.6 тратит credits ×2.5.</p></article>
      <article class="pool" data-provider="spark"><span class="relation">separate</span><h3>Codex Spark</h3><p>Другая менее способная модель и отдельный limit. Не «Fast mode» и не бесплатный overflow.</p></article>
      <article class="pool" data-provider="grok"><span class="relation">shared weekly</span><h3>Grok paid surfaces</h3><p>Chat, Imagine, Voice и Build делят один weekly pool. X/web — приоритетная ниша Orchestra.</p></article>
      <article class="pool" data-provider="claude"><span class="relation">disabled</span><h3>Claude usage credits</h3><p>$0 spent, credits disabled, auto-reload off. Баланс не продолжает работу после included limit.</p></article>
      <article class="pool" data-provider="codex"><span class="relation">not public</span><h3>Numeric capacity</h3><p>Codex weekly и Spark allowance публично не числятся. Internal plan labels — не invoice.</p></article>
    </div>
  </section>

  <section class="section">
    <div class="section-head"><div><div class="eyebrow">Observed timeline · UTC</div><h2>Проценты, reset и structural break</h2></div><label class="mono interactive-only">range <select id="range"><option value="7">7d</option><option value="14" selected>14d</option><option value="all">all</option></select></label></div>
    <div class="chart-wrap"><svg id="chart" viewBox="0 0 1000 330" role="img" aria-label="Timeline utilization by pool"></svg><div class="tooltip" id="tip"></div></div>
    <div class="legend" id="legend"></div>
    <p class="muted mono">VPS timeline · hourly display + threshold changes · source gaps &gt;15m are not bridged · laptop Grok snapshot 98% is outside this VPS series</p>
  </section>

  <section class="section">
    <div class="eyebrow">Observed time above threshold</div><h2>Высокая загрузка ≠ точное время блокировки</h2>
    <div class="bars" id="bars"></div>
    <p class="callout">Codex main был на 100% 118.889 наблюдаемых часов подряд. Claude weekly — 52.957 часа суммарно; два Opus turns успешно завершились уже при reported 100%, поэтому percentage не равен hard denial.</p>
  </section>

  <section class="section" id="controller99">
    <div class="eyebrow">Контроллер 99% к сбросу</div><h2>Цель — попасть к reset, а не остановиться на 95</h2>
    <div class="controller">
      <div>
        <div class="controls interactive-only">
          <div class="control"><label><span>utilization</span><output id="uOut">95%</output></label><input id="u" type="range" min="0" max="100" value="95"></div>
          <div class="control"><label><span>hours to reset</span><output id="hOut">92h</output></label><input id="h" type="range" min="1" max="168" value="92"></div>
          <div class="control"><label><span>q95 turn + rounding guard</span><output id="gOut">1.0pp</output></label><input id="g" type="range" min="0.5" max="8" step="0.5" value="1"></div>
          <div class="control"><label><span>critical reserve</span><output id="rOut">2.0pp</output></label><input id="r" type="range" min="0" max="15" step="0.5" value="2"></div>
        </div>
        <div class="formula">H = 99 − utilization − guard − unreleased reserve<br>required rate = max(0, H / hours-to-reset)<br>dispatch iff u + q95(turn) + guard ≤ 99 − reserve</div>
        <div class="steps" style="margin-top:16px">
          <div class="step"><div><b>Inputs</b><p class="muted">fresh quota, reset, plan, per-turn distribution, critical queue</p></div></div>
          <div class="step"><div><b>Forecast</b><p class="muted">moving-block bootstrap; block length from autocorrelation, p50/p90/p95</p></div></div>
          <div class="step"><div><b>Fail-safe</b><p class="muted">stale &gt;10m, plan/reset drift или мало истории → no blind burn</p></div></div>
        </div>
      </div>
      <aside class="zone" id="zone"><div class="mono">illustrative headroom calculator</div><strong id="zoneName">NO HEADROOM</strong><p id="zoneText"></p><p class="mono" id="zoneMath"></p><p class="muted">Не policy-zone engine: реальные ACCELERATE/TRACK/THROTTLE требуют p50/p90, early-exhaust risk, freshness, drift и calibration history.</p></aside>
    </div>
    <p class="callout"><b>Replay:</b> Claude weekly впервые показал 95% за 91.972h до reset и 100% за 68.969h. От начала 168h окна elapsed = 168−68.969 = 99.031h; линейная target-trajectory = 99×99.031/168 = 58.36% → non-critical следовало перелить, Claude оставить под reserve.</p>
  </section>

  <section class="section">
    <div class="grid two">
      <div><div class="eyebrow">Routing</div><h2>Luna first, Sol by complexity</h2><table><tbody>
        <tr><th>Luna</th><td>closed/high-volume, максимум использования</td></tr><tr><th>Sol</th><td>сложный research/architecture/exact protocol</td></tr>
        <tr><th>Fast</th><td>только latency SLA; burn ×2.5, off при throttle</td></tr><tr><th>Spark</th><td>one-file fully specified + frozen oracle</td></tr>
        <tr><th>Opus</th><td>special complex при Claude headroom</td></tr><tr><th>Grok</th><td>X, web, opinions; login gate отдельно от quota</td></tr>
      </tbody></table></div>
      <div><div class="eyebrow">Measured boundary · #286</div><h2>Spark быстрее, не доказано дешевле</h2><div class="value">−28.4%</div><p>wall time на 2/2 fresh closed tasks; обе модели 2/2 PASS, diffs byte-identical.</p><p class="muted">Spark output +50.1%; cold-start хуже 17.6%; price unknown. #222: missing data → Spark invented 2/2, Luna asked 2/2.</p></div>
    </div>
    <p class="muted">Normal↔Fast paired live result #208 не поступил до cutoff: в policy используется только официальный claim 1.5× speed / 2.5× credits, не «observed» коэффициент.</p>
  </section>

  <section class="section">
    <div class="eyebrow">Grok empirical</div><h2>Laptop 98%; VPS quota-fetch потерял login, quota после 79% unknown</h2>
    <div class="grid two"><div><div class="value">36</div><p>реальных `turn ended` в logs; последние 20 — успешные Grok 4.5. Последний завершён при 78%.</p></div><div><div class="value">0</div><p>Grok rows в `turn_usage` → tokens последних turns unavailable, а не zero.</p></div></div>
    <p class="callout">Laptop provider snapshot: 98%, 10.898h до reset. VPS: 640 snapshots `token_expired`, 0 explicit quota/rate-exhaustion markers, 0 datacenter/IP markers. IP-block остаётся user-reported hypothesis.</p>
  </section>

  <section class="section">
    <div class="eyebrow">Research cost · API-equivalent only</div><h2>Цена веера</h2><table><thead><tr><th>agent</th><th>model</th><th>turns</th><th>input</th><th>cache read</th><th>virtual $</th></tr></thead><tbody id="fan"></tbody></table>
    <p class="muted">Parent current turn не может попасть в `turn_usage` до собственного terminal event. Это unavailable, не $0.</p>
  </section>

  <section class="section">
    <div class="eyebrow">Security note · values omitted</div><h2>Две credential-class находки, ротация только владельцем</h2>
    <div class="grid two"><div><h3>Legacy Codex app-server</h3><p>Затронуты классы Orchestra bridge/session, YouGile account/API, Google OAuth client и OpenRouter API. Legacy process был жив при safe metadata check; эфемерные PID/PPID/path не публикуются, argv/cmdline/environ повторно не читались.</p></div><div><h3>Laptop Orchestra proxy</h3><p>Затронут класс HTTP(S) proxy URL userinfo. Конкретного owner безопасная DB-only выборка не устанавливает.</p></div></div>
    <p class="callout">Owner-run: определить значения приватно в secret store → rotate/revoke у providers → обновить mode-0600 config → в согласованное окно reconnect legacy Codex и restart laptop Orchestra → value-free health check и повторный shape scan. В рамках #285 ничего не ротировалось и не перезапускалось.</p>
    <p class="muted mono">bug records: 20260816T090547…b3f3 · 20260816T092037…c7d4</p>
  </section>

  <section class="section">
    <div class="eyebrow">Official primary sources · accessed 2026-08-16</div><h2>Что опубликовано, а что нет</h2>
    <div class="grid two">
      <ul><li><a href="https://support.claude.com/en/articles/11049741-what-is-the-max-plan">Claude Max plan</a></li><li><a href="https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work">Claude usage windows</a></li><li><a href="https://support.claude.com/en/articles/15424964-claude-fable-5-on-your-plan">Fable scoped limit</a></li><li><a href="https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans">Claude usage credits</a></li><li><a href="https://platform.claude.com/docs/en/about-claude/pricing">Claude API pricing</a></li></ul>
      <ul><li><a href="https://learn.chatgpt.com/docs/pricing">Codex plan usage</a></li><li><a href="https://learn.chatgpt.com/docs/agent-configuration/speed.md">Codex Fast vs Spark</a></li><li><a href="https://help.openai.com/en/articles/20001106">Codex credit rate card</a></li><li><a href="https://docs.x.ai/grok/faq">Grok subscription FAQ</a></li><li><a href="https://docs.x.ai/developers/tools/x-search">xAI X Search</a> · <a href="https://docs.x.ai/developers/tools/web-search">Web Search</a></li></ul>
    </div>
    <p class="muted">Числовая ёмкость current Codex primary, Spark allowance, точное rounding/enforcement Claude и Spark price публично не раскрыты; они помечены <code>not_public</code>, а не оценены догадкой.</p>
  </section>

  <section class="section">
    <div class="eyebrow">Provenance</div><h2>Границы доверия</h2>
    <ul><li>Primary series: <code>vmi3407579</code>, не ноутбук; БД скопирована только <code>Connection.backup</code>, <code>quick_check=ok</code>.</li><li>10 219 snapshots с 05.07; provider history с 03.08; 106 legacy 0/0 исключены как unknown.</li><li>Все изменчивые внешние факты: 26 official URLs, access 2026‑08‑16; непубличные числа помечены <code>not_public</code>.</li><li>Source of truth: <code>docs/tasks/285/research.md</code> + <code>limits-data.json</code>. Этот HTML — view.</li></ul>
  </section>
  <footer class="footer mono">#285 · generated <span id="generated"></span> · offline / no CDN / no external fonts</footer>
</main>
<script type="application/json" id="dataset">__DATA__</script>
<script>
(() => {
  'use strict';
  const D=JSON.parse(document.getElementById('dataset').textContent);
  document.getElementById('generated').textContent=D.generated;
  const root=document.documentElement, theme=document.getElementById('theme');
  const saved=localStorage.getItem('limits-theme'); if(saved) root.dataset.theme=saved;
  theme.onclick=()=>{const now=root.dataset.theme==='dark'?'light':root.dataset.theme==='light'?'auto':'dark';root.dataset.theme=now;localStorage.setItem('limits-theme',now);draw();};
  const providerFor=id=>id.startsWith('claude')?'claude':id.startsWith('codex.spark')?'spark':id.startsWith('codex')?'codex':'grok';
  const colors={"claude.five_hour":"#ef7f5a","claude.seven_day":"#a755d6","codex.primary":"#18a99e","codex.spark":"#e1a72f","grok.weekly":"#4b83e3"};
  const active=new Set(['claude','codex','spark','grok']);
  const names={claude:'Claude',codex:'Codex',spark:'Spark',grok:'Grok'};
  const filters=document.getElementById('filters');
  Object.keys(names).forEach(id=>{const b=document.createElement('button');b.className='pill';b.textContent=names[id];b.dataset.id=id;b.setAttribute('aria-pressed','true');b.onclick=()=>{active.has(id)?active.delete(id):active.add(id);b.setAttribute('aria-pressed',String(active.has(id)));document.querySelectorAll(`[data-provider="${id}"]`).forEach(x=>x.classList.toggle('hidden',!active.has(id)));draw();};filters.appendChild(b)});
  const legend=document.getElementById('legend');D.series.forEach(s=>{legend.insertAdjacentHTML('beforeend',`<span><i class="dot" style="background:${colors[s.id]}"></i>${s.label}</span>`)});
  const svg=document.getElementById('chart'),tip=document.getElementById('tip'),range=document.getElementById('range');range.onchange=draw;
  function draw(){
    const visible=D.series.filter(s=>active.has(providerFor(s.id))&&s.points.length); const all=visible.flatMap(s=>s.points.map(p=>Date.parse(p.t))).filter(Number.isFinite); if(!all.length){svg.innerHTML='';return}
    const max=Math.max(...all), days=range.value==='all'?Infinity:Number(range.value), min=days===Infinity?Math.min(...all):max-days*864e5; const W=1000,H=330,L=48,R=18,T=18,B=34;
    const x=t=>L+(Date.parse(t)-min)/(max-min||1)*(W-L-R), y=u=>T+(100-u)/100*(H-T-B);
    let out='';[0,20,40,60,80,90,95,100].forEach(v=>{out+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".12"/><text x="8" y="${y(v)+4}" fill="currentColor" opacity=".55" font-size="12">${v}%</text>`});
    visible.forEach(s=>{let path='',started=false;s.points.filter(p=>Date.parse(p.t)>=min).forEach(p=>{const cmd=!started||p.b?'M':'L';path+=`${cmd}${x(p.t).toFixed(1)},${y(p.u).toFixed(1)} `;started=true});out+=`<path d="${path}" fill="none" stroke="${colors[s.id]}" stroke-width="3" vector-effect="non-scaling-stroke"/>`});
    out+=`<line id="cursor" x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="currentColor" opacity="0"/>`;svg.innerHTML=out;
    svg.onmousemove=e=>{const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)/r.width*W,t=min+(px-L)/(W-L-R)*(max-min);let best=null;visible.forEach(s=>s.points.forEach(p=>{const pt=Date.parse(p.t);if(pt<min)return;const d=Math.abs(pt-t);if(!best||d<best.d)best={d,s,p}}));if(!best)return;const cx=x(best.p.t);const c=svg.querySelector('#cursor');c.setAttribute('x1',cx);c.setAttribute('x2',cx);c.setAttribute('opacity','.45');tip.style.display='block';tip.style.left=Math.min(e.clientX-r.left+12,r.width-185)+'px';tip.style.top=Math.max(8,e.clientY-r.top-38)+'px';tip.textContent=`${best.s.label} · ${best.p.u}% · ${best.p.t.slice(0,16)}Z`;};svg.onmouseleave=()=>{tip.style.display='none';const c=svg.querySelector('#cursor');if(c)c.setAttribute('opacity','0')};
  }
  draw();
  const barData=[['Claude 5h',D.thresholds['anthropic.five_hour']],['Claude 7d',D.thresholds['anthropic.seven_day']],['Codex main',D.thresholds['codex.primary']]];const bars=document.getElementById('bars');const maxH=Math.max(...barData.map(x=>x[1]?.['80']||0));barData.forEach(([name,v])=>{['80','90','95','100'].forEach(t=>{const h=v?.[t]||0;bars.insertAdjacentHTML('beforeend',`<div class="bar-row"><span>${name} ≥${t}</span><div class="track"><div class="fill" style="width:${h/maxH*100}%"></div></div><b class="mono">${h.toFixed(1)}h</b></div>`)})});
  const ids=['u','h','g','r'];ids.forEach(id=>document.getElementById(id).oninput=calc);
  const uOut=document.getElementById('uOut'),hOut=document.getElementById('hOut'),gOut=document.getElementById('gOut'),rOut=document.getElementById('rOut');
  const zone=document.getElementById('zone'),zoneName=document.getElementById('zoneName'),zoneText=document.getElementById('zoneText'),zoneMath=document.getElementById('zoneMath');
  function calc(){const u=+document.getElementById('u').value,h=+document.getElementById('h').value,g=+document.getElementById('g').value,r=+document.getElementById('r').value;uOut.textContent=u+'%';hOut.textContent=h+'h';gOut.textContent=g.toFixed(1)+'pp';rOut.textContent=r.toFixed(1)+'pp';const H=99-u-g-r,rate=Math.max(0,H/h);let z,text,color;if(u>=100||H<=0){z='NO HEADROOM';text='Guarded non-critical headroom исчерпан; policy должна проверить reserve, risk и spillover.';color='var(--danger)'}else if(rate>.35){z='BURN BUDGET AVAILABLE';text='Headroom/h высокий; это только вход в p90 forecast, не команда автоматически ускоряться.';color='var(--ok)'}else if(rate>.08){z='MODERATE HEADROOM';text='Есть умеренный guarded budget; действие определяет полный forecast и freshness gates.';color='var(--accent)'}else{z='THIN HEADROOM';text='Headroom тонкий; даже малый turn требует q95-fit и полной policy-проверки.';color='var(--accent2)'}zoneName.textContent=z;zoneText.textContent=text;zoneMath.textContent=`H=${H.toFixed(1)}pp · budget rate=${rate.toFixed(3)}pp/h`;zone.style.borderLeftColor=color}
  calc();
  const fan=document.getElementById('fan');D.fan.forEach(a=>fan.insertAdjacentHTML('beforeend',`<tr><td>${a.name}</td><td>${a.model}</td><td>${a.finalized_turns}</td><td>${a.input_tokens?.toLocaleString('en-US')??'in-flight'}</td><td>${a.cache_read_tokens?.toLocaleString('en-US')??'—'}</td><td>${a.virtual_cost_usd==null?'unavailable':'$'+a.virtual_cost_usd.toFixed(4)}</td></tr>`));
})();
</script>
</body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = build_payload(json.loads(args.data.read_text()))
    rendered = TEMPLATE.replace("__DATA__", html.escape(json.dumps(data, ensure_ascii=False), quote=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)


if __name__ == "__main__":
    main()
