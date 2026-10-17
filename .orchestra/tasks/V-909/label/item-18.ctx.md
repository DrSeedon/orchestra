# Context for item-18

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/docs/artifacts/quota-runway-controller.html b/docs/artifacts/quota-runway-controller.html
new file mode 100644
index 000000000..f40f09357
--- /dev/null
+++ b/docs/artifacts/quota-runway-controller.html
@@ -0,0 +1,882 @@
+<!doctype html>
+<html lang="ru">
+<head>
+  <meta charset="utf-8">
+  <meta name="viewport" content="width=device-width, initial-scale=1">
+  <title>Quota Runway Controller</title>
+  <style>
+    :root {
+      color-scheme: light dark;
+      --fs: 15px;
+      --radius: 12px;
+      --font: ui-sans-serif, system-ui, sans-serif;
+      --font-head: ui-serif, Georgia, serif;
+      --accent: light-dark(rgba(14, 116, 196, 1), rgba(64, 196, 216, 1));
+      --bg: light-dark(#ecf2f8, #0f141a);
+      --ink: light-dark(#10151b, #f2f4f7);
+      --mut: color-mix(in srgb, var(--ink) 48%, transparent);
+      --card: light-dark(rgba(18, 49, 74, 0.07), rgba(255, 255, 255, 0.04));
+      --border: color-mix(in srgb, var(--ink) 15%, transparent);
+      --shadow: 0 10px 30px -20px rgba(6, 22, 42, 0.52);
+      --ring: var(--accent);
+      --ok: color-mix(in oklab, var(--accent) 70%, #1ea972);
+      --warn: #e2a24a;
+      --bad: #d96a58;
+      --allow: color-mix(in oklab, #1ea972 60%, #0f172a 40%);
+      --hold: color-mix(in oklab, #e8b63f 55%, #0f172a 45%);
+      --reroute: #2d8fff;
+      --fail: #ef6e4a;
+      --fs-sm: 12px;
+      --fs-h1: calc(var(--fs) * 1.66);
+      --fs-h2: calc(var(--fs) * 1.33);
+      --fs-h3: calc(var(--fs) * 1.07);
+      --shadow: 0 8px 22px -16px color-mix(in srgb, var(--ink) 55%, transparent);
+    }
+
+    * { box-sizing: border-box; }
+    body {
+      margin: 0;
+      padding: clamp(14px, 3vw, 36px);
+      font: 430 var(--fs)/1.45 var(--font);
+      background: radial-gradient(1100px 470px at 84% -22%, color-mix(in oklab, var(--accent) 9%, transparent), transparent),
+        var(--bg);
+      color: var(--ink);
+      min-height: 100vh;
+    }
+
+    h1, h2, h3 {
+      margin: 0;
+      font-family: var(--font-head);
+      font-weight: 500;
+      line-height: 1.24;
+    }
+
+    h1 { font-size: var(--fs-h1); }
+    h2 { font-size: var(--fs-h2); }
+    h3 { font-size: var(--fs-h3); }
+
+    .layout {
+      width: min(1260px, 100%);
+      margin: 0 auto;
+      display: grid;
+      gap: 12px;
+    }
+
+    .panel {
+      border: 1px solid var(--border);
+      border-radius: var(--radius);
+      padding: 14px;
+      background: var(--card);
+      box-shadow: var(--shadow);
+    }
+
+    .top {
+      display: grid;
+      gap: 8px;
+    }
+
+    .title-row {
+      display: flex;
+      align-items: center;
+      justify-content: space-between;
+      gap: 12px;
+      flex-wrap: wrap;
+    }
+
+    .badges {
+      display: flex;
+      flex-wrap: wrap;
+      gap: 8px;
+      align-items: center;
+    }
+
+    .badge {
+      border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
+      color: color-mix(in srgb, var(--accent) 94%, white 6%);
+      border-radius: 999px;
+      padding: 4px 10px;
+      background: color-mix(in srgb, var(--accent) 12%, transparent);
+      font-size: var(--fs-sm);
+    }
+
+    .muted { color: var(--mut); }
+    .actions { display: flex; gap: 6px; flex-wrap: wrap; }
+
+    button {
+      border: 1px solid color-mix(in srgb, var(--ink) 18%, transparent);
+      background: color-mix(in srgb, var(--ink) 4%, transparent);
+      color: inherit;
+      padding: 8px 12px;
+      border-radius: 999px;
+      cursor: pointer;
+      font: inherit;
+      font-size: var(--fs-sm);
+    }
+
+    button:hover { border-color: color-mix(in srgb, var(--accent) 52%, transparent); }
+    button:focus-visible, input:focus-visible, select:focus-visible, .toggle:focus-visible {
+      outline: 3px solid var(--ring);
+      outline-offset: 1px;
+    }
+
+    .grid {
+      display: grid;
+      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
+      gap: 12px;
+    }
+
+    .control {
+      display: grid;
+      gap: 6px;
+      padding: 10px;
+      border: 1px dashed color-mix(in srgb, var(--ink) 16%, transparent);
+      border-radius: 10px;
+      background: color-mix(in oklab, var(--bg) 72%, transparent);
+    }
+
+    label { display: grid; gap: 6px; font-size: 0.95rem; }
+    .label-inline { display: flex; justify-content: space-between; gap: 6px; align-items: baseline; }
+    .value-small { color: var(--mut); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
+    input[type="range"] {
+      width: 100%;
+      accent-color: color-mix(in srgb, var(--accent) 70%, white 30%);
+    }
+    .toggle {
+      display: inline-flex;
+      align-items: center;
+      gap: 8px;
+      padding: 8px 10px;
+      border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
+      border-radius: 10px;
+      background: color-mix(in srgb, var(--ink) 3%, transparent);
+    }
+
+    .summary {
+      display: grid;
+      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
+      gap: 10px;
+    }
+
+    .summary-item {
+      border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
+      border-radius: 10px;
+      padding: 10px;
+      background: color-mix(in oklab, var(--card) 90%, transparent);
+    }
+
+    .summary-item dt {
+      margin: 0 0 4px;
+      color: var(--mut);
+      font-size: var(--fs-sm);
+    }
+
+    .summary-item dd {
+      margin: 0;
+      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
+      font-size: 1.03rem;
+      line-height: 1.3;
+    }
+
+    .lane-zone {
+      display: grid;
+      gap: 10px;
+      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
+    }
+
+    .lane {
+      border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
+      border-radius: 12px;
+      padding: 10px;
+      background: color-mix(in srgb, var(--bg) 86%, transparent);
+      min-height: 100%;
+    }
+
+    .lane h3 { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
+    .status {
+      font-size: var(--fs-sm);
+      padding: 3px 8px;
+      border-radius: 999px;
+      font-weight: 600;
+      display: inline-flex;
+    }
+    .status.allow { background: color-mix(in srgb, var(--allow) 25%, transparent); color: var(--allow); }
+    .status.hold { background: color-mix(in srgb, var(--hold) 22%, transparent); color: var(--hold); }
+    .status.reroute { background: color-mix(in srgb, var(--reroute) 18%, transparent); color: var(--reroute); }
+    .status.fail { background: color-mix(in srgb, var(--fail) 20%, transparent); color: var(--fail); }
+
+    .lane ul {
+      margin: 8px 0 0 16px;
+      padding: 0;
+      color: var(--mut);
+      font-size: var(--fs-sm);
+      min-height: 80px;
+    }
+
+    .lane ul li { margin: 4px 0; }
+    .lane .formula {
+      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
+      background: color-mix(in srgb, var(--ink) 12%, transparent);
+      border: 1px dashed color-mix(in srgb, var(--ink) 30%, transparent);
+      padding: 6px 8px;
+      border-radius: 8px;
+      margin-top: 6px;
+    }
+
+    .meta {
+      display: grid;
+      gap: 8px;
+      font-size: var(--fs-sm);
+    }
+
+    code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
+
+    .spark {
+      display: grid;
+      gap: 10px;
+      padding: 10px;
+      border: 1px dashed color-mix(in srgb, var(--accent) 35%, transparent);
+      border-radius: 10px;
+      background: color-mix(in srgb, var(--accent) 6%, transparent);
+    }
+
+    .note {
+      font-size: 0.95rem;
+      color: var(--mut);
+    }
+
+    footer {
+      color: var(--mut);
+      font-size: 0.87rem;
+      padding-bottom: 4px;
+    }
+    footer a {
+      color: color-mix(in srgb, var(--accent) 60%, white 40%);
+    }
+
+    .pill-row { display: flex; gap: 8px; flex-wrap: wrap; }
+
+    @media print {
+      :root { color-scheme: light; }
+      body {
+        background: #fff;
+        color: #000;
+      }
+      .no-print {
+        display: none !important;
+      }
+      .panel {
+        border-color: #9ca3af;
+        box-shadow: none;
+      }
+      * { print-color-adjust: exact; }
+    }
+
+    .spark-meter {
+      height: 18px;
+      width: 100%;
+      border-radius: 999px;
+      border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
+      overflow: hidden;
+      background: color-mix(in oklab, var(--card) 70%, transparent);
+      position: relative;
+    }
+
+    .spark-meter .fill {
+      height: 100%;
+      background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 20%, #60a5fa 80%), color-mix(in srgb, var(--accent) 55%, #06b6d4 45%));
+    }
+
+    .spark-meter .line {
+      position: absolute;
+      top: 0;
+      bottom: 0;
+      width: 2px;
+      background: var(--fail);
+      opacity: 0.8;
+    }
+
+    .zone-bar {
+      display: flex;
+      height: 12px;
+      border-radius: 999px;
+      overflow: hidden;
+      border: 1px solid color-mix(in srgb, var(--ink) 25%, transparent);
+    }
+
+    .zone-bar span {
+      flex: 1;
+      text-indent: -9999px;
+    }
+
+    .zone-accelerate { background: var(--ok); }
+    .zone-track { background: #46c1ff; }
+    .zone-reserve { background: var(--warn); }
+    .zone-throttle { background: var(--bad); }
+    .zone-fail { background: #6b7280; }
+
+    .sr-only { position:absolute;width:1px;height:1px;padding:0;border:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap; }
+
+    @media (max-width: 780px) {
+      body { padding: 10px; }
+      .lane-zone { grid-template-columns: 1fr; }
+      .summary { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
+    }
+  </style>
+</head>
+<body>
+  <main class="layout">
+    <section class="panel top">
+      <div class="title-row">
+        <div>
+          <h1>Quota Runway Controller (промежуточный макет)</h1>
+          <p class="muted">Визуальный offline-полигон для будущего Usage Analytics: формула и объяснения, без production JS.</p>
+        </div>
+        <div class="badges">
+          <span class="badge">current formula: u_eff + q95(next_turn) + guard &lt;= 99 - reserve</span>
+          <span class="badge">target 99 · no fixed 90/95/98</span>
+          <span class="badge no-print">orchestrator · EXEMPT but observed</span>
+        </div>
+      </div>
+
+      <div class="actions no-print">
+        <button id="preset-live" type="button" aria-pressed="true">Preset: current-live (ILLUSTRATIVE)</button>
+        <button id="preset-calibrated" type="button" aria-pressed="false">Preset: calibrated lanes</button>
+        <button id="preset-both-held" type="button" aria-pressed="false">Preset: both held (ILLUSTRATIVE)</button>
+        <button id="download-json" class="no-print" type="button">Скачать JSON</button>
+      </div>
+
+      <div class="grid no-print" id="controls">
+        <label class="control" for="utilization">
+          <span class="label-inline"><span>utilization, pp</span><span class="value-small" id="utilizationValue"></span></span>
+          <input id="utilization" type="range" min="0" max="140" step="0.1" value="95" aria-label="utilization">
+          <input class="sr-only" type="number" min="0" max="140" step="0.1" value="95" id="utilizationN" aria-label="utilization number">
+        </label>
+
+        <label class="control" for="hoursToReset">
+          <span class="label-inline"><span>hours to reset</span><span class="value-small" id="hoursToResetValue"></span></span>
+          <input id="hoursToReset" type="range" min="1" max="240" step="1" value="119" aria-label="hours to reset">
+          <input class="sr-only" type="number" min="1" max="240" step="1" value="119" id="hoursToResetN" aria-label="hours to reset number">
+        </label>
+
+        <label class="control" for="observedBurn">
+          <span class="label-inline"><span>observed burn, pp/h</span><span class="value-small" id="observedBurnValue"></span></span>
+          <input id="observedBurn" type="range" min="0" max="4" step="0.01" value="0.16" aria-label="observed burn">
+          <input class="sr-only" type="number" min="0" max="4" step="0.01" value="0.16" id="observedBurnN" aria-label="observed burn number">
+        </label>
+
+        <label class="control" for="lunaQ95">
+          <span class="label-inline"><span>Luna q95, pp/turn</span><span class="value-small" id="lunaQ95Value"></span></span>
+          <input id="lunaQ95" type="range" min="0" max="20" step="0.1" value="1.6" aria-label="Luna q95">
+          <input class="sr-only" type="number" min="0" max="20" step="0.1" value="1.6" id="lunaQ95N" aria-label="Luna q95 number">
+        </label>
+
+        <label class="control" for="solQ95">
+          <span class="label-inline"><span>Sol q95, pp/turn</span><span class="value-small" id="solQ95Value"></span></span>
+          <input id="solQ95" type="range" min="0" max="20" step="0.1" value="12.0" aria-label="Sol q95">
+          <input class="sr-only" type="number" min="0" max="20" step="0.1" value="12.0" id="solQ95N" aria-label="Sol q95 number">
+        </label>
+
+        <label class="control" for="guard">
+          <span class="label-inline"><span>guard, pp</span><span class="value-small" id="guardValue"></span></span>
+          <input id="guard" type="range" min="0" max="4" step="0.1" value="0.5" aria-label="guard">
+          <input class="sr-only" type="number" min="0" max="4" step="0.1" value="0.5" id="guardN" aria-label="guard number">
+        </label>
+
+        <label class="control" for="reserve">
+          <span class="label-inline"><span>reserve, pp</span><span class="value-small" id="reserveValue"></span></span>
+          <input id="reserve" type="range" min="0" max="8" step="0.1" value="2" aria-label="reserve">
+          <input class="sr-only" type="number" min="0" max="8" step="0.1" value="2" id="reserveN" aria-label="reserve number">
+        </label>
+
+        <label class="control" for="inflight">
+          <span class="label-inline"><span>unsettled/inflight, pp</span><span class="value-small" id="inflightValue"></span></span>
+          <input id="inflight" type="range" min="0" max="12" step="0.1" value="0" aria-label="inflight">
+          <input class="sr-only" type="number" min="0" max="12" step="0.1" value="0" id="inflightN" aria-label="inflight number">
+        </label>
+      </div>
+
+      <label class="toggle no-print" for="q95Known">
+        <input id="q95Known" type="checkbox" checked>
+        <span>q95 known (для всех lanes)</span>
+      </label>
+
+      <p class="note no-print">Пресеты и все q95 ниже — иллюстративные, это не live-измерения.</p>
+    </section>
+
+    <section class="panel">
+      <h2>Расчёт и сигналы</h2>
+      <div class="summary">
+        <dl class="summary-item">
+          <dt>u_eff</dt>
+          <dd id="uEff"></dd>
+        </dl>
+        <dl class="summary-item">
+          <dt>H (до reset)</dt>
+          <dd id="hoursLeft"></dd>
+        </dl>
+        <dl class="summary-item">
+          <dt>required average burn H/h</dt>
+          <dd id="requiredBurn"></dd>
+        </dl>
+        <dl class="summary-item">
+          <dt>projected end from burn*h</dt>
+          <dd id="projectedEnd"></dd>
+        </dl>
+        <dl class="summary-item">
+          <dt>confidence</dt>
+          <dd id="confidence"></dd>
+        </dl>
+        <dl class="summary-item">
+          <dt>early-exhaust warning</dt>
+          <dd id="earlyWarning"></dd>
+        </dl>
+      </div>
+      <p class="meta"><strong>Точная формула:</strong> <span class="mono">u_eff + q95(next_turn) + guard <= 99 - reserve</span>, где <span class="mono">u_eff = utilization + unsettled/inflight</span>.</p>
+      <div class="zone-bar" aria-label="область зон" style="margin-top:8px;">
+        <span class="zone-accelerate" style="flex:2"></span>
+        <span class="zone-track" style="flex:2.5"></span>
+        <span class="zone-reserve" style="flex:2.5"></span>
+        <span class="zone-throttle" style="flex:1"></span>
+      </div>
+      <p class="note" id="zoneHint">Зона по итоговой метрике текущего шага.</p>
+    </section>
+
+    <section class="panel">
+      <h2>Ланы и решения</h2>
+      <div class="lane-zone" id="laneZone">
+        <article class="lane" id="laneLuna">
+          <h3>
+            <span>Luna lane</span>
+            <span class="status hold" id="decisionLuna" data-role="decision-luna">--</span>
+          </h3>
+          <p class="formula" id="laneLunaFormula"></p>
+          <div id="laneLunaZone" class="note"></div>
+          <ul id="laneLunaReasons"></ul>
+        </article>
+
+        <article class="lane" id="laneSol">
+          <h3>
+            <span>Sol lane</span>
+            <span class="status hold" id="decisionSol" data-role="decision-sol">--</span>
+          </h3>
+          <p class="formula" id="laneSolFormula"></p>
+          <div id="laneSolZone" class="note"></div>
+          <ul id="laneSolReasons"></ul>
+        </article>
+      </div>
+
+      <div class="spark">
+        <h3>Spark bucket (отдельный bucket)</h3>
+        <p class="note">Spark не участвует в решении Luna/Sol gate и имеет отдельный лимит-контур. Ниже показан только наблюдаемый тренд по инференсу для иллюстрации.</p>
+        <div class="spark-meter" aria-label="Spark utilization progress">
+          <div class="fill" id="sparkFill"></div>
+          <div class="line" id="sparkLimit"></div>
+        </div>
+        <p class="meta" id="sparkText"></p>
+      </div>
+    </section>
+
+    <section class="panel">
+      <h2>Привязанные правила binding</h2>
+      <p class="note" id="bindingText"></p>
+      <ul id="bindingList"></ul>
+    </section>
+
+    <section class="panel">
+      <h2>Наследование и контекст</h2>
+      <p class="note">orchestrator помечен <strong>EXEMPT</strong> по текущему worker gate, но наблюдается в telemetry как отдельный lane с флагом observed: если его сценарий включён, это отражается в выводе статуса.</p>
+    </section>
+
+    <footer class="no-print">
+      Источники: <a href="docs/tasks/291/plan.md">docs/tasks/291/plan.md</a> · текущая постановка task #318 (входящее описание задачи: расчёт формулой и interactive макет, без production JS).
+    </footer>
+  </main>
+
+<script>
+  const presets = {
+    live: {
+      utilization: 95,
+      hoursToReset: 119,
+      observedBurn: 0.16,
+      lunaQ95: 2.3,
+      solQ95: 2.8,
+      guard: 0.5,
+      reserve: 2,
+      inflight: 0,
+      q95Known: false,
+      note: 'current-live: q95 unknown -> FAIL-SAFE/static fallback'
+    },
+    calibrated: {
+      utilization: 85,
+      hoursToReset: 119,
+      observedBurn: 0.14,
+      lunaQ95: 1.4,
+      solQ95: 11.8,
+      guard: 1.0,
+      reserve: 1.5,
+      inflight: 0.6,
+      q95Known: true,
+      note: 'ИЛЛЮСТРАТИВНЫЙ: Luna fit, Sol hold'
+    },
+    bothHeld: {
+      utilization: 88,
+      hoursToReset: 119,
+      observedBurn: 0.26,
+      lunaQ95: 14.2,
+      solQ95: 13.1,
+      guard: 1.2,
+      reserve: 1.0,
+      inflight: 0.9,
+      q95Known: true,
+      note: 'ИЛЛЮСТРАТИВНЫЙ: оба HOLD'
+    }
+  };
+
+  const controls = ['utilization','hoursToReset','observedBurn','lunaQ95','solQ95','guard','reserve','inflight'];
+  const numInputs = {
+    utilization: ['utilizationN','utilization'],
+    hoursToReset: ['hoursToResetN','hoursToReset'],
+    observedBurn: ['observedBurnN','observedBurn'],
+    lunaQ95: ['lunaQ95N','lunaQ95'],
+    solQ95: ['solQ95N','solQ95'],
+    guard: ['guardN','guard'],
+    reserve: ['reserveN','reserve'],
+    inflight: ['inflightN','inflight']
+  };
+
+  const state = {
+    utilization: 95,
+    hoursToReset: 119,
+    observedBurn: 0.16,
+    lunaQ95: 2.3,
+    solQ95: 2.8,
+    guard: 0.5,
+    reserve: 2,
+    inflight: 0,
+    q95Known: false
+  };
+
+  function syncInput(name) {
+    const range = document.getElementById(name);
+    const num = document.getElementById(numInputs[name][0]);
+    const valueLabel = document.getElementById(name + 'Value');
+    range.addEventListener('input', () => {
+      num.value = range.value;
+      state[name] = Number(range.value);
+      render();
+    });
+    num.addEventListener('input', () => {
+      range.value = num.value;
+      state[name] = Number(num.value);
+      render();
+    });
+    range.value = state[name];
+    num.value = state[name];
+    valueLabel.textContent = Number(state[name]).toFixed(2);
+  }
+
+  Object.entries(numInputs).forEach(([name]) => syncInput(name));
+
+  function setPreset(presetName) {
+    const preset = presets[presetName];
+    if (!preset) return;
+    state.utilization = preset.utilization;
+    state.hoursToReset = preset.hoursToReset;
+    state.observedBurn = preset.observedBurn;
+    state.lunaQ95 = preset.lunaQ95;
+    state.solQ95 = preset.solQ95;
+    state.guard = preset.guard;
+    state.reserve = preset.reserve;
+    state.inflight = preset.inflight;
+    state.q95Known = preset.q95Known;
+    document.getElementById('q95Known').checked = preset.q95Known;
+    for (const name of controls) {
+      document.getElementById(name).value = state[name];
+      document.getElementById(numInputs[name][0]).value = state[name];
+      document.getElementById(name + 'Value').textContent = Number(state[name]).toFixed(2);
+    }
+    render();
+  }
+
+  document.getElementById('preset-live').addEventListener('click', () => {
+    document.getElementById('preset-live').setAttribute('aria-pressed', 'true');
+    document.getElementById('preset-calibrated').setAttribute('aria-pressed', 'false');
+    document.getElementById('preset-both-held').setAttribute('aria-pressed', 'false');
+    setPreset('live');
+  });
+
+  document.getElementById('preset-calibrated').addEventListener('click', () => {
+    document.getElementById('preset-calibrated').setAttribute('aria-pressed', 'true');
+    document.getElementById('preset-live').setAttribute('aria-pressed', 'false');
+    document.getElementById('preset-both-held').setAttribute('aria-pressed', 'false');
+    setPreset('calibrated');
+  });
+
+  document.getElementById('preset-both-held').addEventListener('click', () => {
+    document.getElementById('preset-both-held').setAttribute('aria-pressed', 'true');
+    document.getElementById('preset-calibrated').setAttribute('aria-pressed', 'false');
+    document.getElementById('preset-live').setAttribute('aria-pressed', 'false');
+    setPreset('bothHeld');
+  });
+
+  document.getElementById('q95Known').addEventListener('change', (event) => {
+    state.q95Known = event.target.checked;
+    render();
+  });
+
+  function clamp(v, lo, hi) {
+    return Math.min(hi, Math.max(lo, v));
+  }
+
+  function computeDecision(laneName, q95) {
+    const uEff = state.utilization + state.inflight;
+    const rhs = 99 - state.reserve;
+    const lhs = uEff + (state.q95Known ? q95 : 0) + state.guard;
+    const H = clamp(state.hoursToReset, 0.01, 240);
+    const projectedBase = uEff + state.observedBurn * H;
+    const projectedWithTurn = projectedBase + (state.q95Known ? q95 : 0) + state.guard;
+    const requiredBurn = state.q95Known
+      ? Math.max(0, (rhs - state.guard - q95 - uEff) / H)
+      : Math.max(0, (rhs - state.guard - uEff) / H);
+
+    let zone = 'FAIL_SAFE';
+    if (!state.q95Known) {
+      zone = 'FAIL_SAFE';
+    } else if (projectedWithTurn <= rhs - 8) {
+      zone = 'ACCELERATE';
+    } else if (projectedWithTurn <= rhs - 3) {
+      zone = 'TRACK';
+    } else if (projectedWithTurn <= rhs) {
+      zone = 'RESERVE';
+    } else {
+      zone = 'THROTTLE';
+    }
+
+    return {
+      laneName,
+      uEff,
+      rhs,
+      lhs: state.q95Known ? lhs : null,
+      projectedBase,
+      projectedWithTurn,
+      requiredBurn,
+      formulaText: state.q95Known
+        ? `u_eff=${uEff.toFixed(2)} | q95=${q95.toFixed(2)} | guard=${state.guard.toFixed(2)} | 99-reserve=${rhs.toFixed(2)}`
+        : `u_eff=${uEff.toFixed(2)} | q95=unknown | guard=${state.guard.toFixed(2)} | 99-reserve=${rhs.toFixed(2)}`,
+      passes: state.q95Known && lhs <= rhs,
+      zone
+    };
+  }
+
+  function setStatusEl(el, status) {
+    const map = {
+      'ALLOW': 'allow',
+      'REROUTE': 'reroute',
+      'HOLD': 'hold',
+      'FAIL-SAFE': 'fail',
+    };
+    el.className = 'status ' + (map[status] || 'hold');
+    el.textContent = status;
+  }
+
+  function reasonForLane(name, decision, otherCanPass) {
+    const items = [];
+    if (!state.q95Known) {
+      items.push('q95 неизвестен: используется FAIL-SAFE с static fallback и conservative наблюдаемым режимом.');
+      return items;
+    }
+
+    if (decision.passes && otherCanPass === false) {
+      items.push('PASS по формуле и по всем известным компонентам: u_eff + q95 + guard <= 99 - reserve. Альтернативный lane не проходит, значит ALLOW для текущей пары остается рабочим.');
+    } else if (decision.passes && otherCanPass === true) {
+      items.push('PASS по формуле; параллельно другая lane тоже проходит, reroute не нужен.');
+    } else if (!decision.passes && otherCanPass === true) {
+      items.push('Линия не проходит формулу. Альтернативный lane проходит, поэтому предлагается REROUTE на альтернативный lane.');
+    } else {
+      items.push('Линия не проходит формулу и в паре не найден альтернативный lane: HOLD как защитная реакция.');
+    }
+
+    const delta = (decision.rhs - (decision.lhs ?? 0));
+    if (state.q95Known) {
+      items.push(`Остаток до порога: ${delta.toFixed(2)} pp. Если delta <= 0, то действие блокируется по этой lane.`);
+      items.push(`Зона на основе раннего прогноза: ${decision.zone}.`);
+      items.push(`projected_end = u_eff + burn*H + q95 + guard = ${decision.projectedWithTurn.toFixed(2)} pp.`);
+    }
+
+    return items;
+  }
+
+  function zoneClass(zone) {
+    switch(zone) {
+      case 'ACCELERATE': return 'zone-accelerate';
+      case 'TRACK': return 'zone-track';
+      case 'RESERVE': return 'zone-reserve';
+      case 'THROTTLE':
+      case 'FAIL_SAFE': return zone === 'FAIL_SAFE' ? 'zone-fail' : 'zone-throttle';
+      default: return 'zone-fail';
+    }
+  }
+
+  function render() {
+    for (const name of controls) {
+      document.getElementById(name + 'Value').textContent = Number(state[name]).toFixed(2);
+    }
+
+    const uEff = state.utilization + state.inflight;
+    const rhs = 99 - state.reserve;
+    const H = state.hoursToReset;
+    const projectedNoTurn = uEff + state.observedBurn * H;
+
+    const luna = computeDecision('Luna', state.lunaQ95);
+    const sol = computeDecision('Sol', state.solQ95);
+    const bothPass = {
+      luna: luna.passes,
+      sol: sol.passes
+    };
+
+    let decisionLuna;
+    let decisionSol;
+
+    if (!state.q95Known) {
+      decisionLuna = 'FAIL-SAFE';
+      decisionSol = 'FAIL-SAFE';
+    } else if (luna.passes && sol.passes) {
+      decisionLuna = 'ALLOW';
+      decisionSol = 'ALLOW';
+    } else if (luna.passes && !sol.passes) {
+      decisionLuna = 'ALLOW';
+      decisionSol = 'REROUTE';
+    } else if (!luna.passes && sol.passes) {
+      decisionLuna = 'REROUTE';
+      decisionSol = 'ALLOW';
+    } else {
+      decisionLuna = 'HOLD';
+      decisionSol = 'HOLD';
+    }
+
+    const projectedWithTurnLuna = luna.projectedBase + (state.q95Known ? state.lunaQ95 : 0) + state.guard;
+    const projectedWithTurnSol = sol.projectedBase + (state.q95Known ? state.solQ95 : 0) + state.guard;
+
+    const earliestExhaust = Math.min(
+      projectedWithTurnLuna, projectedWithTurnSol
+    );
+
+    document.getElementById('uEff').textContent = `${uEff.toFixed(2)} pp`;
+    document.getElementById('hoursLeft').textContent = `${H.toFixed(0)} h`;
+    document.getElementById('requiredBurn').textContent = `${Math.max(0, (rhs - uEff - state.guard - (state.q95Known ? Math.min(state.lunaQ95, state.solQ95) : 0)) / Math.max(1, H)).toFixed(3)} pp/h`;
+    document.getElementById('confidence').textContent = state.q95Known ? 'pilot (иллюстративные q95)' : 'fail-safe';
+    document.getElementById('projectedEnd').textContent = `Luna ${projectedWithTurnLuna.toFixed(2)} • Sol ${projectedWithTurnSol.toFixed(2)} pp`;
+
+    const overfillLuna = projectedWithTurnLuna > rhs ? projectedWithTurnLuna - rhs : 0;
+    const overfillSol = projectedWithTurnSol > rhs ? projectedWithTurnSol - rhs : 0;
+    const minOverfill = Math.min(overfillLuna, overfillSol);
+    const warning = !state.q95Known
+      ? 'unknown q95, fail-safe fallback active'
+      : (projectedNoTurn > rhs
+          ? 'прогноз показывает риск перегруза до reset без компенсации'
+          : minOverfill > 0
+            ? `порог target-${rhs.toFixed(2)} пересекается только с учетом next-turn risk; headroom ${minOverfill.toFixed(2)} pp`
+            : `проекция до reset держит headroom ${(rhs - projectedNoTurn).toFixed(2)} pp`);
+    document.getElementById('earlyWarning').textContent = warning;
+
+    const zone = !state.q95Known
+      ? 'FAIL_SAFE'
+      : (projectedWithTurnLuna > rhs && projectedWithTurnSol > rhs)
+        ? 'THROTTLE'
+        : 'TRACK';
+    document.getElementById('zoneHint').textContent = `Текущая зона: ${zone}`;
+
+    const decisionLunaEl = document.getElementById('decisionLuna');
+    const decisionSolEl = document.getElementById('decisionSol');
+    setStatusEl(decisionLunaEl, decisionLuna);
+    setStatusEl(decisionSolEl, decisionSol);
+
+    document.getElementById('laneLunaFormula').textContent = luna.formulaText;
+    document.getElementById('laneSolFormula').textContent = sol.formulaText;
+
+    const laneLunaZone = luna.zone;
+    const laneSolZone = sol.zone;
+    document.getElementById('laneLunaZone').textContent = `zone: ${laneLunaZone}`;
+    document.getElementById('laneSolZone').textContent = `zone: ${laneSolZone}`;
+
+    const zoneHint = {
+      ACCELERATE: 'Ожидаемый расход далёк от порога 99, можно ускорять поток.',
+      TRACK: 'Текущий расход в рабочей зоне наблюдаемости.',
+      RESERVE: 'Идёт расход headroom, нужно удерживать стабильный dispatch.',
+      THROTTLE: 'Риск раннего исчерпания, включать throttling.',
+      FAIL_SAFE: 'Без надежного q95 включается fail-safe fallback.'
+    };
+    document.getElementById('laneLunaZone').title = zoneHint[laneLunaZone] || '';
+    document.getElementById('laneSolZone').title = zoneHint[laneSolZone] || '';
+
+    const reasonsLuna = reasonForLane('Luna', luna, bothPass.sol);
+    const reasonsSol = reasonForLane('Sol', sol, bothPass.luna);
+    renderList('laneLunaReasons', reasonsLuna);
+    renderList('laneSolReasons', reasonsSol);
+
+    const sparkFill = document.getElementById('sparkFill');
+    const sparkLimit = document.getElementById('sparkLimit');
+    const sparkUtil = clamp(uEff + state.observedBurn * 0.6 * state.hoursToReset * 0.2, 0, 140);
+    const sparkText = state.utilization >= 100
+      ? 'Spark в отдельном bucket может пересекать внутренний ceiling даже при стабильных worker-lanes.'
+      : 'Spark-сценарий показателен, но не участвует в пересчете решений Luna/Sol.';
+    sparkFill.style.width = `${Math.min(100, sparkUtil)}%`;
+    sparkLimit.style.left = `72%`;
+    document.getElementById('sparkText').textContent = `Spark (иллюстративно): projected end ${sparkUtil.toFixed(2)} pp, зона threshold 72/100.`;
+
+    document.getElementById('bindingText').textContent =
+      `binding: u_eff + q95(next_turn) + guard <= 99 - reserve. Lane-level gate делается на constraint уровне bucket с учетом unsettled и guard. FAIL-SAFE применяется только при неизвестном/неконсистентном q95.`;
+
+    const bindingItems = [
+      `utilization input используется напрямую в u_eff только после сложения с unsettled/inflight.`,
+      `guard всегда сохраняет дополнительный буфер на коррекцию задержек телеметрии.`,
+      `reserve защищает рабочий план при drift, not as hard-stop.`,
+      `target и решение опираются на 99, без порогов 90/95/98.`,
+    ];
+    if (!state.q95Known) {
+      bindingItems.push('q95 в этой симуляции отмечен as unknown, поэтому действует FAIL-SAFE/ static fallback.');
+    }
+    renderList('bindingList', bindingItems);
+
+    const presetNote = state.q95Known ? 'q95 known' : 'q95 unknown';
+    document.title = `Quota Runway Controller · ${presetNote}`;
+
+    document.querySelectorAll('.no-print .status').forEach((el) => {
+      el.setAttribute('aria-live', 'polite');
+    });
+  }
+
+  function renderList(id, items) {
+    const node = document.getElementById(id);
+    node.innerHTML = '';
+    items.forEach((item) => {
+      const li = document.createElement('li');
+      li.textContent = item;
+      node.appendChild(li);
+    });
+  }
+
+  document.getElementById('download-json').addEventListener('click', () => {
+    const payload = {
+      createdAt: new Date().toISOString(),
+      inputs: { ...state },
+      decisions: {
+        luna: document.getElementById('decisionLuna').textContent,
+        sol: document.getElementById('decisionSol').textContent,
+      },
+      formula: 'u_eff + q95(next_turn) + guard <= 99 - reserve'
+    };
+    const text = JSON.stringify(payload, null, 2);
+    const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
+    const a = document.createElement('a');
+    a.href = URL.createObjectURL(blob);
+    a.download = 'quota-runway-controller-sim.json';
+    document.body.appendChild(a);
+    a.click();
+    a.remove();
+  });
+
+  render();
+</script>
+</body>
+</html>
diff --git a/docs/workers/artifact-quota-runway.md b/docs/workers/artifact-quota-runway.md
new file mode 100644
index 000000000..2aae58e57
--- /dev/null
+++ b/docs/workers/artifact-quota-runway.md
@@ -0,0 +1,3 @@
+# artifact-quota-runway personal memory
+
+- Добавлять файлы в игнорируемый `docs/artifacts/` всегда только через `git add -f`, даже если файл новый и успешно создан, иначе коммит не содержит изменений.


## Later history of the touched files on main (after this commit)

5 later commits touch these paths; the first 40 (oldest first):
e4e3e6b7d 2026-08-18 #321: redesign quota runway as graphical explainer
10b371de1 2026-08-18 #321: make quota map interactive with percentage and hour sliders
b25221f5a 2026-08-18 #321: #321: replace static quota map with weekly trajectory
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e4e3e6b7d #321: redesign quota runway as graphical explainer

diff --git a/docs/artifacts/quota-runway-controller.html b/docs/artifacts/quota-runway-controller.html
index f40f09357..cfc6c2ee4 100644
--- a/docs/artifacts/quota-runway-controller.html
+++ b/docs/artifacts/quota-runway-controller.html
@@ -1,882 +1,471 @@
 <!doctype html>
 <html lang="ru">
 <head>
   <meta charset="utf-8">
-  <meta name="viewport" content="width=device-width, initial-scale=1">
-  <title>Quota Runway Controller</title>
+  <meta name="viewport" content="width=device-width,initial-scale=1">
+  <meta name="color-scheme" content="light dark">
+  <title>Quota runway — как дожить до сброса</title>
   <style>
-    :root {
+    /* костяк производен от visualize.css, (c) OpenAI, Apache-2.0;
+       изменено: убран внешний JS, добавлены печать и вторая шрифтовая семья */
+    :root{
       color-scheme: light dark;
+      /* акцент: бирюзовый — про запас воздуха и управляемый runway */
+      --accent: light-dark(#087a74, #62d3c8);
       --fs: 15px;
       --radius: 12px;
       --font: ui-sans-serif, system-ui, sans-serif;
       --font-head: ui-serif, Georgia, serif;
-      --accent: light-dark(rgba(14, 116, 196, 1), rgba(64, 196, 216, 1));
-      --bg: light-dark(#ecf2f8, #0f141a);
-      --ink: light-dark(#10151b, #f2f4f7);
+      --bg: light-dark(#fff, #181818);
+      --ink: light-dark(#1a1c1f, #f2f2f0);
       --mut: color-mix(in srgb, var(--ink) 48%, transparent);
-      --card: light-dark(rgba(18, 49, 74, 0.07), rgba(255, 255, 255, 0.04));
-      --border: color-mix(in srgb, var(--ink) 15%, transparent);
-      --shadow: 0 10px 30px -20px rgba(6, 22, 42, 0.52);
+      --card: color-mix(in oklab, var(--ink) 5%, transparent);
+      --border: color-mix(in srgb, var(--ink) 12%, transparent);
       --ring: var(--accent);
-      --ok: color-mix(in oklab, var(--accent) 70%, #1ea972);
-      --warn: #e2a24a;
-      --bad: #d96a58;
-      --allow: color-mix(in oklab, #1ea972 60%, #0f172a 40%);
-      --hold: color-mix(in oklab, #e8b63f 55%, #0f172a 45%);
-      --reroute: #2d8fff;
-      --fail: #ef6e4a;
-      --fs-sm: 12px;
-      --fs-h1: calc(var(--fs) * 1.66);
-      --fs-h2: calc(var(--fs) * 1.33);
-      --fs-h3: calc(var(--fs) * 1.07);
-      --shadow: 0 8px 22px -16px color-mix(in srgb, var(--ink) 55%, transparent);
-    }
-
-    * { box-sizing: border-box; }
-    body {
-      margin: 0;
-      padding: clamp(14px, 3vw, 36px);
-      font: 430 var(--fs)/1.45 var(--font);
-      background: radial-gradient(1100px 470px at 84% -22%, color-mix(in oklab, var(--accent) 9%, transparent), transparent),
-        var(--bg);
-      color: var(--ink);
-      min-height: 100vh;
-    }
-
-    h1, h2, h3 {
-      margin: 0;
-      font-family: var(--font-head);
-      font-weight: 500;
-      line-height: 1.24;
-    }
-
-    h1 { font-size: var(--fs-h1); }
-    h2 { font-size: var(--fs-h2); }
-    h3 { font-size: var(--fs-h3); }
-
-    .layout {
-      width: min(1260px, 100%);
-      margin: 0 auto;
-      display: grid;
-      gap: 12px;
-    }
-
-    .panel {
-      border: 1px solid var(--border);
-      border-radius: var(--radius);
-      padding: 14px;
-      background: var(--card);
-      box-shadow: var(--shadow);
-    }
-
-    .top {
-      display: grid;
-      gap: 8px;
-    }
-
-    .title-row {
-      display: flex;
-      align-items: center;
-      justify-content: space-between;
-      gap: 12px;
-      flex-wrap: wrap;
-    }
-
-    .badges {
-      display: flex;
-      flex-wrap: wrap;
-      gap: 8px;
-      align-items: center;
-    }
-
-    .badge {
-      border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
-      color: color-mix(in srgb, var(--accent) 94%, white 6%);
-      border-radius: 999px;
-      padding: 4px 10px;
-      background: color-mix(in srgb, var(--accent) 12%, transparent);
-      font-size: var(--fs-sm);
-    }
-
-    .muted { color: var(--mut); }
-    .actions { display: flex; gap: 6px; flex-wrap: wrap; }
-
-    button {
-      border: 1px solid color-mix(in srgb, var(--ink) 18%, transparent);
-      background: color-mix(in srgb, var(--ink) 4%, transparent);
-      color: inherit;
-      padding: 8px 12px;
-      border-radius: 999px;
-      cursor: pointer;
-      font: inherit;
-      font-size: var(--fs-sm);
-    }
-
-    button:hover { border-color: color-mix(in srgb, var(--accent) 52%, transparent); }
-    button:focus-visible, input:focus-visible, select:focus-visible, .toggle:focus-visible {
-      outline: 3px solid var(--ring);
-      outline-offset: 1px;
-    }
-
-    .grid {
-      display: grid;
-      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
-      gap: 12px;
-    }
-
-    .control {
-      display: grid;
-      gap: 6px;
-      padding: 10px;
### 10b371de1 #321: make quota map interactive with percentage and hour sliders

diff --git a/docs/artifacts/quota-runway-controller.html b/docs/artifacts/quota-runway-controller.html
index cfc6c2ee4..8b6324aac 100644
--- a/docs/artifacts/quota-runway-controller.html
+++ b/docs/artifacts/quota-runway-controller.html
@@ -2,470 +2,314 @@
 <html lang="ru">
 <head>
   <meta charset="utf-8">
   <meta name="viewport" content="width=device-width,initial-scale=1">
   <meta name="color-scheme" content="light dark">
-  <title>Quota runway — как дожить до сброса</title>
+  <title>Quota map — доступность моделей</title>
   <style>
-    /* костяк производен от visualize.css, (c) OpenAI, Apache-2.0;
-       изменено: убран внешний JS, добавлены печать и вторая шрифтовая семья */
+    /* костяк производен от visualize.css, (c) OpenAI, Apache-2.0 */
     :root{
-      color-scheme: light dark;
-      /* акцент: бирюзовый — про запас воздуха и управляемый runway */
-      --accent: light-dark(#087a74, #62d3c8);
-      --fs: 15px;
-      --radius: 12px;
-      --font: ui-sans-serif, system-ui, sans-serif;
-      --font-head: ui-serif, Georgia, serif;
-      --bg: light-dark(#fff, #181818);
-      --ink: light-dark(#1a1c1f, #f2f2f0);
-      --mut: color-mix(in srgb, var(--ink) 48%, transparent);
-      --card: color-mix(in oklab, var(--ink) 5%, transparent);
-      --border: color-mix(in srgb, var(--ink) 12%, transparent);
-      --ring: var(--accent);
-      --bad: light-dark(#c0341a, #ff7a63);
-      --fs-sm: max(11px, calc(var(--fs) - 2px));
-      --fs-h3: calc(var(--fs) * 1.29);
-      --fs-h2: calc(var(--fs) * 1.43);
-      --fs-h1: calc(var(--fs) * 1.72);
-      --r-sm: calc(var(--radius) * .6);
-      --r-lg: calc(var(--radius) * 1.6);
-      --shadow: 0 1px 2px -1px rgb(0 0 0 / 8%);
-      --s1: var(--accent);
-      --s2: light-dark(#c26a1f, #f59a56);
-      --s3: light-dark(#2f7d46, #74d58b);
-      --s4: light-dark(#b8457f, #f08fc0);
-      --s5: light-dark(#6b57c4, #aa91ef);
-      --s6: light-dark(#1f7a72, #5acbc2);
+      color-scheme:light dark;
+      /* акцент: бирюзовый — свободный runway и безопасное продолжение */
+      --accent:light-dark(#087a74,#62d3c8);
+      --fs:15px;--radius:12px;
+      --font:ui-sans-serif,system-ui,sans-serif;
+      --font-head:ui-serif,Georgia,serif;
+      --bg:light-dark(#fff,#181818);--ink:light-dark(#1a1c1f,#f2f2f0);
+      --mut:color-mix(in srgb,var(--ink) 48%,transparent);
+      --card:color-mix(in oklab,var(--ink) 5%,transparent);
+      --border:color-mix(in srgb,var(--ink) 12%,transparent);
+      --ring:var(--accent);--bad:light-dark(#c0341a,#ff7a63);
+      --fs-sm:max(11px,calc(var(--fs) - 2px));--fs-h3:calc(var(--fs) * 1.29);
+      --fs-h2:calc(var(--fs) * 1.43);--fs-h1:calc(var(--fs) * 1.72);
+      --r-sm:calc(var(--radius) * .6);--r-lg:calc(var(--radius) * 1.6);
+      --shadow:0 1px 2px -1px rgb(0 0 0 / 8%);
+      --s1:var(--accent);--s2:light-dark(#c26a1f,#f59a56);
+      --s3:light-dark(#2f7d46,#74d58b);--s4:light-dark(#b8457f,#f08fc0);
+      --s5:light-dark(#6b57c4,#aa91ef);--s6:light-dark(#1f7a72,#5acbc2);
     }
     *{box-sizing:border-box}
     body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);
-         font:430 var(--fs)/1.5 var(--font);letter-spacing:0}
+      font:430 var(--fs)/1.5 var(--font)}
     h1,h2,h3{margin:0;font-family:var(--font-head);font-weight:500;line-height:1.25}
-    h1{font-size:var(--fs-h1)} h2{font-size:var(--fs-h2)} h3{font-size:var(--fs-h3)}
-    small,.sm{font-size:var(--fs-sm)} .mut{color:var(--mut)}
-    table{width:100%;border-collapse:collapse}
-    th,td{padding:10px 24px 10px 0;border-bottom:1px solid var(--border);
-          text-align:start;vertical-align:top;overflow-wrap:anywhere}
-    th{font-weight:600;border-bottom-color:color-mix(in srgb,var(--ink) 16%,transparent)}
-    tbody tr:last-child :is(th,td){border-bottom:0}
-    .num{text-align:end;font-variant-numeric:tabular-nums}
-    .scroll{overflow-x:auto;scrollbar-width:thin}
-    .card{padding:12px;border-radius:var(--r-lg);background:var(--card)}
-    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(max(180px,24%),1fr));gap:12px}
+    h1{font-size:var(--fs-h1)}h2{font-size:var(--fs-h2)}h3{font-size:var(--fs-h3)}
+    small,.sm{font-size:var(--fs-sm)}.mut{color:var(--mut)}
     .badge{padding:3px 8px;border-radius:9999px;font-size:var(--fs-sm);
-           background:color-mix(in srgb,var(--accent) 15%,transparent)}
-    code{padding:1px 6px;border-radius:var(--r-sm);font-size:.92em;
-         font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
-         background:color-mix(in srgb,var(--ink) 10%,transparent);
-         box-decoration-break:clone;-webkit-box-decoration-break:clone;overflow-wrap:anywhere}
-    :is(a,button,summary,input,select,[tabindex]):focus-visible{
-         outline:2px solid var(--ring);outline-offset:2px}
-    :is([aria-pressed="true"],[aria-selected="true"]){background:var(--accent);color:var(--bg)}
+      background:color-mix(in srgb,var(--accent) 15%,transparent)}
+    code{padding:1px 6px;border-radius:var(--r-sm);font:500 .92em/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
+      background:color-mix(in srgb,var(--ink) 10%,transparent)}
+    :is(a,button,input,[tabindex]):focus-visible{outline:2px solid var(--ring);outline-offset:2px}
+    :is([aria-pressed="true"]){background:var(--accent);color:var(--bg)}
     svg{display:block;max-width:100%;height:auto}
-    .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
+    .shell{width:min(1360px,100%);margin:auto}
+    .top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:24px}
+    .top p{max-width:780px;margin:8px 0 0;color:var(--mut);font-size:1.04rem}
+    .live-stamp{text-align:end;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
 
-    .shell{width:min(1220px,100%);margin-inline:auto}
-    .topline{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding-bottom:24px}
-    .lede{max-width:760px;margin:8px 0 0;color:var(--mut);font-size:1.04rem}
-    .snapshot{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;text-align:end;white-space:nowrap}
-    .live-strip{display:grid;grid-template-columns:minmax(220px,1.5fr) repeat(3,minmax(130px,1fr));
+    .control-deck{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr)) minmax(260px,.8fr);
       gap:2px;border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow)}
-    .live-cell{min-height:104px;padding:16px;background:var(--card);display:flex;flex-direction:column;justify-content:space-between}
-    .live-cell strong{font-family:var(--font-head);font-weight:500;font-size:clamp(1.45rem,3vw,2.25rem);line-height:1}
-    .live-cell.primary{background:color-mix(in srgb,var(--accent) 11%,var(--card))}
-    .state-ok{color:var(--s3)} .state-stop{color:var(--bad)} .state-warn{color:var(--s2)}
-    .section{padding:40px 0;border-bottom:1px solid var(--border)}
-    .section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:16px}
-    .section-head p{max-width:670px;margin:4px 0 0;color:var(--mut)}
-    .scenario-tabs{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
-    button{border:1px solid var(--border);border-radius:9999px;padding:6px 12px;background:transparent;
-      color:inherit;font:600 var(--fs-sm)/1.4 var(--font);cursor:pointer}
-    button:hover{border-color:color-mix(in srgb,var(--accent) 65%,var(--border))}
-    .chart-wrap{border:1px solid var(--border);border-radius:var(--r-lg);padding:16px;background:var(--card);overflow:hidden}
-    .chart-caption{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-top:12px}
-    .chart-caption strong{display:block;font-family:var(--font-head);font-size:var(--fs-h3);font-weight:500}
-    .chart-caption p{margin:2px 0 0;color:var(--mut);max-width:720px}
-    .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:var(--fs-sm);color:var(--mut)}
-    .legend span{display:inline-flex;align-items:center;gap:6px}
-    .swatch{width:18px;height:3px;border-radius:3px;background:var(--s1)}
-    .swatch.target{background:var(--s2)} .swatch.unknown{background:var(--mut)}
-    .rail-key{display:flex;justify-content:flex-end;gap:16px;flex-wrap:wrap;margin:24px 0 8px;
-      color:var(--mut);font-size:var(--fs-sm)}
-    .rail-key span{display:inline-flex;align-items:center;gap:6px}
-    .rail-key i{display:inline-block;width:12px;height:3px;border-radius:3px;background:currentColor}
-    .rail-key .sol-key{color:var(--bad)}.rail-key .luna-key{color:var(--s3)}.rail-key .target-key{color:var(--s2)}
-    .quota-rail{position:relative;height:64px;margin:8px 0 24px;border-radius:var(--r-sm);
-      background:color-mix(in srgb,var(--ink) 8%,transparent);overflow:visible}
-    .quota-used{height:100%;width:96%;border-radius:var(--r-sm) 0 0 var(--r-sm);
-      background:color-mix(in srgb,var(--accent) 58%,transparent);position:relative}
-    .quota-used::after{content:"96%";position:absolute;right:10px;top:50%;translate:0 -50%;
-      font-family:var(--font-head);font-size:var(--fs-h2);font-weight:500;color:var(--ink)}
-    .marker{position:absolute;top:-8px;height:80px;width:2px;background:currentColor}
-    .marker.sol{left:95%;color:var(--bad)} .marker.luna{left:98%;color:var(--s3)} .marker.target{left:99%;color:var(--s2)}
-    .rail-labels{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
-    .rail-labels strong{display:block;font-family:var(--font-head);font-size:var(--fs-h3);font-weight:500}
-    .lane-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:24px}
-    .lane{padding:16px;border-top:3px solid var(--border);background:var(--card);border-radius:0 0 var(--r-lg) var(--r-lg)}
-    .lane.luna{border-color:var(--s3)} .lane.sol{border-color:var(--bad)}
-    .lane-top{display:flex;align-items:center;justify-content:space-between;gap:12px}
-    .lane h3{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1rem}
### b25221f5a #321: #321: replace static quota map with weekly trajectory

diff --git a/docs/artifacts/quota-runway-controller.html b/docs/artifacts/quota-runway-controller.html
index 8b6324aac..5a57d5447 100644
--- a/docs/artifacts/quota-runway-controller.html
+++ b/docs/artifacts/quota-runway-controller.html
@@ -2,20 +2,19 @@
 <html lang="ru">
 <head>
   <meta charset="utf-8">
   <meta name="viewport" content="width=device-width,initial-scale=1">
   <meta name="color-scheme" content="light dark">
-  <title>Quota map — доступность моделей</title>
+  <title>Недельная траектория квоты</title>
   <style>
-    /* костяк производен от visualize.css, (c) OpenAI, Apache-2.0 */
     :root{
       color-scheme:light dark;
-      /* акцент: бирюзовый — свободный runway и безопасное продолжение */
+      /* акцент: морская бирюза — траектория расхода и управляемый runway */
       --accent:light-dark(#087a74,#62d3c8);
       --fs:15px;--radius:12px;
       --font:ui-sans-serif,system-ui,sans-serif;
-      --font-head:ui-serif,Georgia,serif;
+      --font-head:ui-serif,Georgia,"Times New Roman",serif;
       --bg:light-dark(#fff,#181818);--ink:light-dark(#1a1c1f,#f2f2f0);
       --mut:color-mix(in srgb,var(--ink) 48%,transparent);
       --card:color-mix(in oklab,var(--ink) 5%,transparent);
       --border:color-mix(in srgb,var(--ink) 12%,transparent);
       --ring:var(--accent);--bad:light-dark(#c0341a,#ff7a63);
@@ -26,290 +25,126 @@
       --s1:var(--accent);--s2:light-dark(#c26a1f,#f59a56);
       --s3:light-dark(#2f7d46,#74d58b);--s4:light-dark(#b8457f,#f08fc0);
       --s5:light-dark(#6b57c4,#aa91ef);--s6:light-dark(#1f7a72,#5acbc2);
     }
     *{box-sizing:border-box}
-    body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);
-      font:430 var(--fs)/1.5 var(--font)}
+    body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);font:430 var(--fs)/1.5 var(--font)}
     h1,h2,h3{margin:0;font-family:var(--font-head);font-weight:500;line-height:1.25}
     h1{font-size:var(--fs-h1)}h2{font-size:var(--fs-h2)}h3{font-size:var(--fs-h3)}
     small,.sm{font-size:var(--fs-sm)}.mut{color:var(--mut)}
-    .badge{padding:3px 8px;border-radius:9999px;font-size:var(--fs-sm);
-      background:color-mix(in srgb,var(--accent) 15%,transparent)}
-    code{padding:1px 6px;border-radius:var(--r-sm);font:500 .92em/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
-      background:color-mix(in srgb,var(--ink) 10%,transparent)}
+    code{padding:1px 6px;border-radius:var(--r-sm);font:500 .92em/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:color-mix(in srgb,var(--ink) 10%,transparent);overflow-wrap:anywhere}
     :is(a,button,input,[tabindex]):focus-visible{outline:2px solid var(--ring);outline-offset:2px}
-    :is([aria-pressed="true"]){background:var(--accent);color:var(--bg)}
     svg{display:block;max-width:100%;height:auto}
     .shell{width:min(1360px,100%);margin:auto}
     .top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:24px}
-    .top p{max-width:780px;margin:8px 0 0;color:var(--mut);font-size:1.04rem}
-    .live-stamp{text-align:end;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
-
-    .control-deck{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr)) minmax(260px,.8fr);
-      gap:2px;border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow)}
-    .control{padding:16px 24px;background:var(--card);min-height:142px}
-    .control-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
-    .control-label{font-weight:650}.control-value{font-family:var(--font-head);font-size:clamp(2rem,5vw,3.35rem);line-height:.95;font-weight:500}
-    .control-value small{font-family:var(--font);font-size:var(--fs-sm);color:var(--mut)}
-    input[type="range"]{appearance:none;width:100%;height:28px;margin:18px 0 0;background:transparent;cursor:pointer}
-    input[type="range"]::-webkit-slider-runnable-track{height:8px;border-radius:9999px;background:linear-gradient(90deg,var(--accent) var(--fill),color-mix(in srgb,var(--ink) 12%,transparent) var(--fill))}
-    input[type="range"]::-moz-range-track{height:8px;border-radius:9999px;background:color-mix(in srgb,var(--ink) 12%,transparent)}
-    input[type="range"]::-moz-range-progress{height:8px;border-radius:9999px;background:var(--accent)}
-    input[type="range"]::-webkit-slider-thumb{appearance:none;width:24px;height:24px;margin-top:-8px;border:4px solid var(--bg);border-radius:50%;background:var(--accent);box-shadow:0 0 0 1px var(--accent)}
-    input[type="range"]::-moz-range-thumb{width:18px;height:18px;border:4px solid var(--bg);border-radius:50%;background:var(--accent)}
+    .top p{max-width:800px;margin:8px 0 0;color:var(--mut);font-size:1.04rem}
+    .stamp{text-align:end;white-space:nowrap;font:500 var(--fs-sm)/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mut)}
+    .deck{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr));gap:2px;border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow)}
+    .control{padding:16px 24px;background:var(--card);min-height:150px}
+    .control-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.control-label{font-weight:650}.control-value{font-family:var(--font-head);font-size:clamp(2.25rem,5vw,3.65rem);line-height:.9;font-weight:500;white-space:nowrap}.control-value small{font-family:var(--font);font-size:var(--fs-sm);color:var(--mut)}
+    input[type=range]{appearance:none;width:100%;height:28px;margin:20px 0 0;background:transparent;cursor:pointer}input[type=range]::-webkit-slider-runnable-track{height:8px;border-radius:9999px;background:linear-gradient(90deg,var(--accent) var(--fill),color-mix(in srgb,var(--ink) 12%,transparent) var(--fill))}input[type=range]::-moz-range-track{height:8px;border-radius:9999px;background:color-mix(in srgb,var(--ink) 12%,transparent)}input[type=range]::-moz-range-progress{height:8px;border-radius:9999px;background:var(--accent)}input[type=range]::-webkit-slider-thumb{appearance:none;width:24px;height:24px;margin-top:-8px;border:4px solid var(--bg);border-radius:50%;background:var(--accent);box-shadow:0 0 0 1px var(--accent)}input[type=range]::-moz-range-thumb{width:18px;height:18px;border:4px solid var(--bg);border-radius:50%;background:var(--accent)}
     .range-ends{display:flex;justify-content:space-between;color:var(--mut);font-size:var(--fs-sm)}
-    .mode-box{display:flex;flex-direction:column;justify-content:space-between}
-    .mode-buttons{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
-    button{border:1px solid var(--border);border-radius:9999px;background:transparent;color:inherit;
-      padding:7px 12px;font:650 var(--fs-sm)/1.3 var(--font);cursor:pointer}
-    button:hover{border-color:var(--accent)}
-    .mode-note{margin:12px 0 0;color:var(--mut)}
-
-    .map-head{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:40px 0 12px}
-    .map-head p{margin:4px 0 0;color:var(--mut)}
-    .map-layout{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(270px,.7fr);gap:12px;align-items:stretch}
-    .map-panel{padding:12px;border:1px solid var(--border);border-radius:var(--r-lg);background:var(--card);overflow:hidden;min-width:0}
-    .side{display:flex;flex-direction:column;gap:8px}
-    .model{padding:16px;border:1px solid var(--border);border-left:5px solid var(--mut);border-radius:var(--r-lg);background:var(--card);min-height:126px}
-    .model.available{border-left-color:var(--s3)}.model.blocked{border-left-color:var(--bad)}.model.conditional{border-left-color:var(--s2)}
-    .model-top{display:flex;justify-content:space-between;align-items:center;gap:12px}
-    .model h3{font:600 1rem/1.3 ui-monospace,SFMono-Regular,Menlo,monospace}
-    .model-state{font-size:var(--fs-sm);font-weight:800;letter-spacing:.06em;text-transform:uppercase}
-    .available .model-state{color:var(--s3)}.blocked .model-state{color:var(--bad)}.conditional .model-state{color:var(--s2)}
-    .model p{margin:8px 0 0;color:var(--mut)}
-    .metric{display:flex;justify-content:space-between;gap:12px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:var(--fs-sm)}
-    .metric strong{font-variant-numeric:tabular-nums}
-    .readout{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2px;margin-top:12px;border-radius:var(--r-lg);overflow:hidden}
-    .readout-item{padding:12px 16px;background:var(--card);min-height:88px}
-    .readout-item strong{display:block;font-family:var(--font-head);font-size:var(--fs-h2);font-weight:500}
-    .readout-item span{color:var(--mut);font-size:var(--fs-sm)}
-    .explain{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.5fr);gap:24px;margin-top:24px;padding:24px 0;border-top:1px solid var(--border)}
-    .formula{font:650 clamp(1rem,2vw,1.35rem)/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
-    .explain p{margin:8px 0 0;color:var(--mut)}
-    .facts{margin:0;padding:0;list-style:none}.facts li{padding:8px 0;border-bottom:1px solid var(--border)}.facts li:last-child{border:0}
-
-    #quota-map text{font-family:var(--font);fill:var(--mut);font-size:13px}
-    #quota-map .strong{fill:var(--ink);font-weight:700}
-    #quota-map .grid{stroke:var(--border);stroke-width:1}
-    #quota-map .axis{stroke:color-mix(in srgb,var(--ink) 34%,transparent);stroke-width:1.5}
-    #quota-map .zone-all{fill:color-mix(in srgb,var(--s3) 18%,transparent)}
-    #quota-map .zone-luna{fill:color-mix(in srgb,var(--accent) 19%,transparent)}
-    #quota-map .zone-stop{fill:color-mix(in srgb,var(--bad) 12%,transparent)}
-    #quota-map .sol-boundary{fill:none;stroke:var(--bad);stroke-width:3;stroke-dasharray:7 5}
-    #quota-map .luna-boundary{fill:none;stroke:var(--s3);stroke-width:4}
-    #quota-map .cursor{stroke:var(--ink);stroke-width:1.5;stroke-dasharray:3 5;opacity:.55}
-    #quota-map .current-diamond{fill:var(--bg);stroke:var(--ink);stroke-width:4}
-    #quota-map .model-dot{stroke:var(--bg);stroke-width:4}
-    #quota-map .point-label{fill:var(--bg);stroke:var(--border);stroke-width:1}
-    #quota-map .point-text{font-size:12px;font-weight:750;fill:var(--ink)}
-    #quota-map .spark-line{stroke:var(--s5);stroke-width:2;stroke-dasharray:3 5}
-    .legend{display:flex;justify-content:flex-end;gap:16px;flex-wrap:wrap;color:var(--mut);font-size:var(--fs-sm)}
-    .legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:16px;height:4px;border-radius:4px;background:currentColor}
-    .legend .all{color:var(--s3)}.legend .luna{color:var(--accent)}.legend .stop{color:var(--bad)}
-    .foot{display:flex;justify-content:space-between;gap:24px;margin-top:24px;padding-top:16px;border-top:1px solid var(--border);color:var(--mut);font-size:var(--fs-sm)}
-
-    @media(max-width:980px){.control-deck{grid-template-columns:1fr 1fr}.mode-box{grid-column:1/-1}.map-layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:repeat(3,1fr)}.explain{grid-template-columns:1fr}}
-    @media(max-width:680px){.top,.map-head,.foot{flex-direction:column;align-items:flex-start}.live-stamp{text-align:start}.control-deck{grid-template-columns:1fr}.mode-box{grid-column:auto}.side{grid-template-columns:1fr}.readout{grid-template-columns:1fr 1fr}.map-panel{padding:4px}.legend{justify-content:flex-start}}
-    @media print{:root{color-scheme:light}body{padding:0;background:#fff;color:#000}.no-print{display:none}.map-layout{grid-template-columns:2fr 1fr}*{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
+    .quick{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.quick button,button{border:1px solid var(--border);border-radius:9999px;background:transparent;color:inherit;padding:7px 12px;font:650 var(--fs-sm)/1.3 var(--font);cursor:pointer}button:hover{border-color:var(--accent)}
+    .readout{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2px;margin-top:12px;border-radius:var(--r-lg);overflow:hidden}.readout-item{padding:12px 16px;background:var(--card);min-height:88px}.readout-item strong{display:block;font-family:var(--font-head);font-size:var(--fs-h2);font-weight:500;font-variant-numeric:tabular-nums}.readout-item span{color:var(--mut);font-size:var(--fs-sm)}
+    .map-head{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:40px 0 12px}.map-head p{margin:4px 0 0;color:var(--mut)}.legend{display:flex;justify-content:flex-end;gap:14px;flex-wrap:wrap;color:var(--mut);font-size:var(--fs-sm)}.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:16px;height:7px;border-radius:3px}.legend .normal i{background:color-mix(in srgb,var(--s3) 70%,transparent)}.legend .middle i{background:color-mix(in srgb,var(--s2) 70%,transparent)}.legend .hold i{background:color-mix(in srgb,var(--bad) 70%,transparent)}
+    .map-layout{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(280px,.7fr);gap:12px;align-items:stretch}.map-panel{padding:12px;border:1px solid var(--border);border-radius:var(--r-lg);background:var(--card);overflow:hidden;min-width:0}.side{display:flex;flex-direction:column;gap:8px}.model{padding:16px;border:1px solid var(--border);border-left:5px solid var(--mut);border-radius:var(--r-lg);background:var(--card);min-height:154px}.model.allow{border-left-color:var(--s3)}.model.hold{border-left-color:var(--bad)}.model-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.model h3{font:600 1rem/1.3 ui-monospace,SFMono-Regular,Menlo,monospace}.model-state{font-size:var(--fs-sm);font-weight:800;letter-spacing:.04em}.allow .model-state{color:var(--s3)}.hold .model-state{color:var(--bad)}.model p{margin:8px 0 0;color:var(--mut)}.metric{display:flex;justify-content:space-between;gap:12px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:var(--fs-sm)}.metric strong{font-variant-numeric:tabular-nums}
+    #quota-map text{font-family:var(--font);fill:var(--mut);font-size:13px}#quota-map .strong{fill:var(--ink);font-weight:700}#quota-map .grid{stroke:var(--border);stroke-width:1}#quota-map .axis{stroke:color-mix(in srgb,var(--ink) 34%,transparent);stroke-width:1.5}#quota-map .zone-normal{fill:color-mix(in srgb,var(--s3) 18%,transparent)}#quota-map .zone-middle{fill:color-mix(in srgb,var(--s2) 18%,transparent)}#quota-map .zone-hold{fill:color-mix(in srgb,var(--bad) 12%,transparent)}#quota-map .target{fill:none;stroke:var(--accent);stroke-width:4}#quota-map .corridor-sol{fill:none;stroke:var(--s2);stroke-width:2.5;stroke-dasharray:8 5}#quota-map .corridor-luna{fill:none;stroke:var(--s3);stroke-width:2.5;stroke-dasharray:3 5}#quota-map .fit{fill:none;stroke:var(--ink);stroke-width:1.5;stroke-dasharray:2 5;opacity:.65}#quota-map .cursor{stroke:var(--ink);stroke-width:1.5;stroke-dasharray:3 5;opacity:.55}#quota-map .current{fill:var(--bg);stroke:var(--ink);stroke-width:4}.point-label{fill:var(--bg);stroke:var(--border);stroke-width:1}.point-text{font-size:12px;font-weight:750;fill:var(--ink)}#quota-map .zone-label{font-size:14px;font-weight:700;fill:var(--ink);opacity:.7}
+    .formula-band{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.5fr);gap:24px;margin-top:24px;padding:24px 0;border-top:1px solid var(--border)}.formula{font:650 clamp(1rem,2vw,1.35rem)/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.formula-band p{margin:8px 0 0;color:var(--mut)}.facts{margin:0;padding:0;list-style:none}.facts li{padding:8px 0;border-bottom:1px solid var(--border)}.facts li:last-child{border:0}.notice{margin-top:16px;padding:12px 16px;border-left:4px solid var(--s2);background:color-mix(in srgb,var(--s2) 9%,transparent);border-radius:var(--r-sm)}
+    .comparison{margin-top:24px;padding-top:16px;border-top:1px solid var(--border)}.comparison table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}.comparison th,.comparison td{padding:8px 16px 8px 0;text-align:start;border-bottom:1px solid var(--border)}.comparison th{font-weight:600}.foot{display:flex;justify-content:space-between;gap:24px;margin-top:24px;padding-top:16px;border-top:1px solid var(--border);color:var(--mut);font-size:var(--fs-sm)}
+    @media(max-width:980px){.map-layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:repeat(3,1fr)}.formula-band{grid-template-columns:1fr}}
+    @media(max-width:680px){.top,.map-head,.foot{flex-direction:column;align-items:flex-start}.stamp{text-align:start}.deck{grid-template-columns:1fr}.side{grid-template-columns:1fr}.readout{grid-template-columns:1fr 1fr}.map-panel{padding:4px}.legend{justify-content:flex-start}.comparison{overflow-x:auto}.comparison table{min-width:520px}}
+    @media print{ :root{color-scheme:light}body{padding:0;background:#fff;color:#000}.no-print{display:none}.map-layout{grid-template-columns:2fr 1fr}*{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
   </style>
 </head>
 <body>
 <main class="shell">
   <header class="top">
-    <div><h1>Карта доступа к моделям</h1><p>Двигайте текущий расход и часы до сброса. Точка переезжает по карте, границы пересчитываются, а Luna, Sol и Spark сразу меняют цвет и статус.</p></div>
-    <div class="live-stamp sm mut">живой старт<br><strong>96% · 121 ч</strong></div>
+    <div><h1>Недельная траектория квоты</h1><p>К контроллеру важен не статичный порог, а вопрос «где мы должны быть к этому часу недели?». Двигайте два ползунка: target, коридоры и решение каждой lane обновятся сразу.</p></div>
+    <div class="stamp">Codex primary · 168 ч<br><strong>предпросмотр · теневой режим</strong></div>
   </header>
 
-  <section class="control-deck no-print" aria-label="Параметры квотного окна">
-    <div class="control">
### 498c0d149 Orchestra: migrate project state to .orchestra

diff --git a/docs/workers/artifact-quota-runway.md b/docs/workers/artifact-quota-runway.md
deleted file mode 100644
index 2aae58e57..000000000
--- a/docs/workers/artifact-quota-runway.md
+++ /dev/null
@@ -1,3 +0,0 @@
-# artifact-quota-runway personal memory
-
-- Добавлять файлы в игнорируемый `docs/artifacts/` всегда только через `git add -f`, даже если файл новый и успешно создан, иначе коммит не содержит изменений.
### f8e00522e #430: research .orchestra path migration

diff --git a/docs/artifacts/quota-runway-controller.html b/docs/artifacts/quota-runway-controller.html
deleted file mode 100644
index 5a57d5447..000000000
--- a/docs/artifacts/quota-runway-controller.html
+++ /dev/null
@@ -1,150 +0,0 @@
-<!doctype html>
-<html lang="ru">
-<head>
-  <meta charset="utf-8">
-  <meta name="viewport" content="width=device-width,initial-scale=1">
-  <meta name="color-scheme" content="light dark">
-  <title>Недельная траектория квоты</title>
-  <style>
-    :root{
-      color-scheme:light dark;
-      /* акцент: морская бирюза — траектория расхода и управляемый runway */
-      --accent:light-dark(#087a74,#62d3c8);
-      --fs:15px;--radius:12px;
-      --font:ui-sans-serif,system-ui,sans-serif;
-      --font-head:ui-serif,Georgia,"Times New Roman",serif;
-      --bg:light-dark(#fff,#181818);--ink:light-dark(#1a1c1f,#f2f2f0);
-      --mut:color-mix(in srgb,var(--ink) 48%,transparent);
-      --card:color-mix(in oklab,var(--ink) 5%,transparent);
-      --border:color-mix(in srgb,var(--ink) 12%,transparent);
-      --ring:var(--accent);--bad:light-dark(#c0341a,#ff7a63);
-      --fs-sm:max(11px,calc(var(--fs) - 2px));--fs-h3:calc(var(--fs) * 1.29);
-      --fs-h2:calc(var(--fs) * 1.43);--fs-h1:calc(var(--fs) * 1.72);
-      --r-sm:calc(var(--radius) * .6);--r-lg:calc(var(--radius) * 1.6);
-      --shadow:0 1px 2px -1px rgb(0 0 0 / 8%);
-      --s1:var(--accent);--s2:light-dark(#c26a1f,#f59a56);
-      --s3:light-dark(#2f7d46,#74d58b);--s4:light-dark(#b8457f,#f08fc0);
-      --s5:light-dark(#6b57c4,#aa91ef);--s6:light-dark(#1f7a72,#5acbc2);
-    }
-    *{box-sizing:border-box}
-    body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);font:430 var(--fs)/1.5 var(--font)}
-    h1,h2,h3{margin:0;font-family:var(--font-head);font-weight:500;line-height:1.25}
-    h1{font-size:var(--fs-h1)}h2{font-size:var(--fs-h2)}h3{font-size:var(--fs-h3)}
-    small,.sm{font-size:var(--fs-sm)}.mut{color:var(--mut)}
-    code{padding:1px 6px;border-radius:var(--r-sm);font:500 .92em/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:color-mix(in srgb,var(--ink) 10%,transparent);overflow-wrap:anywhere}
-    :is(a,button,input,[tabindex]):focus-visible{outline:2px solid var(--ring);outline-offset:2px}
-    svg{display:block;max-width:100%;height:auto}
-    .shell{width:min(1360px,100%);margin:auto}
-    .top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:24px}
-    .top p{max-width:800px;margin:8px 0 0;color:var(--mut);font-size:1.04rem}
-    .stamp{text-align:end;white-space:nowrap;font:500 var(--fs-sm)/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mut)}
-    .deck{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr));gap:2px;border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow)}
-    .control{padding:16px 24px;background:var(--card);min-height:150px}
-    .control-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.control-label{font-weight:650}.control-value{font-family:var(--font-head);font-size:clamp(2.25rem,5vw,3.65rem);line-height:.9;font-weight:500;white-space:nowrap}.control-value small{font-family:var(--font);font-size:var(--fs-sm);color:var(--mut)}
-    input[type=range]{appearance:none;width:100%;height:28px;margin:20px 0 0;background:transparent;cursor:pointer}input[type=range]::-webkit-slider-runnable-track{height:8px;border-radius:9999px;background:linear-gradient(90deg,var(--accent) var(--fill),color-mix(in srgb,var(--ink) 12%,transparent) var(--fill))}input[type=range]::-moz-range-track{height:8px;border-radius:9999px;background:color-mix(in srgb,var(--ink) 12%,transparent)}input[type=range]::-moz-range-progress{height:8px;border-radius:9999px;background:var(--accent)}input[type=range]::-webkit-slider-thumb{appearance:none;width:24px;height:24px;margin-top:-8px;border:4px solid var(--bg);border-radius:50%;background:var(--accent);box-shadow:0 0 0 1px var(--accent)}input[type=range]::-moz-range-thumb{width:18px;height:18px;border:4px solid var(--bg);border-radius:50%;background:var(--accent)}
-    .range-ends{display:flex;justify-content:space-between;color:var(--mut);font-size:var(--fs-sm)}
-    .quick{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.quick button,button{border:1px solid var(--border);border-radius:9999px;background:transparent;color:inherit;padding:7px 12px;font:650 var(--fs-sm)/1.3 var(--font);cursor:pointer}button:hover{border-color:var(--accent)}
-    .readout{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2px;margin-top:12px;border-radius:var(--r-lg);overflow:hidden}.readout-item{padding:12px 16px;background:var(--card);min-height:88px}.readout-item strong{display:block;font-family:var(--font-head);font-size:var(--fs-h2);font-weight:500;font-variant-numeric:tabular-nums}.readout-item span{color:var(--mut);font-size:var(--fs-sm)}
-    .map-head{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:40px 0 12px}.map-head p{margin:4px 0 0;color:var(--mut)}.legend{display:flex;justify-content:flex-end;gap:14px;flex-wrap:wrap;color:var(--mut);font-size:var(--fs-sm)}.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:16px;height:7px;border-radius:3px}.legend .normal i{background:color-mix(in srgb,var(--s3) 70%,transparent)}.legend .middle i{background:color-mix(in srgb,var(--s2) 70%,transparent)}.legend .hold i{background:color-mix(in srgb,var(--bad) 70%,transparent)}
-    .map-layout{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(280px,.7fr);gap:12px;align-items:stretch}.map-panel{padding:12px;border:1px solid var(--border);border-radius:var(--r-lg);background:var(--card);overflow:hidden;min-width:0}.side{display:flex;flex-direction:column;gap:8px}.model{padding:16px;border:1px solid var(--border);border-left:5px solid var(--mut);border-radius:var(--r-lg);background:var(--card);min-height:154px}.model.allow{border-left-color:var(--s3)}.model.hold{border-left-color:var(--bad)}.model-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.model h3{font:600 1rem/1.3 ui-monospace,SFMono-Regular,Menlo,monospace}.model-state{font-size:var(--fs-sm);font-weight:800;letter-spacing:.04em}.allow .model-state{color:var(--s3)}.hold .model-state{color:var(--bad)}.model p{margin:8px 0 0;color:var(--mut)}.metric{display:flex;justify-content:space-between;gap:12px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:var(--fs-sm)}.metric strong{font-variant-numeric:tabular-nums}
-    #quota-map text{font-family:var(--font);fill:var(--mut);font-size:13px}#quota-map .strong{fill:var(--ink);font-weight:700}#quota-map .grid{stroke:var(--border);stroke-width:1}#quota-map .axis{stroke:color-mix(in srgb,var(--ink) 34%,transparent);stroke-width:1.5}#quota-map .zone-normal{fill:color-mix(in srgb,var(--s3) 18%,transparent)}#quota-map .zone-middle{fill:color-mix(in srgb,var(--s2) 18%,transparent)}#quota-map .zone-hold{fill:color-mix(in srgb,var(--bad) 12%,transparent)}#quota-map .target{fill:none;stroke:var(--accent);stroke-width:4}#quota-map .corridor-sol{fill:none;stroke:var(--s2);stroke-width:2.5;stroke-dasharray:8 5}#quota-map .corridor-luna{fill:none;stroke:var(--s3);stroke-width:2.5;stroke-dasharray:3 5}#quota-map .fit{fill:none;stroke:var(--ink);stroke-width:1.5;stroke-dasharray:2 5;opacity:.65}#quota-map .cursor{stroke:var(--ink);stroke-width:1.5;stroke-dasharray:3 5;opacity:.55}#quota-map .current{fill:var(--bg);stroke:var(--ink);stroke-width:4}.point-label{fill:var(--bg);stroke:var(--border);stroke-width:1}.point-text{font-size:12px;font-weight:750;fill:var(--ink)}#quota-map .zone-label{font-size:14px;font-weight:700;fill:var(--ink);opacity:.7}
-    .formula-band{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.5fr);gap:24px;margin-top:24px;padding:24px 0;border-top:1px solid var(--border)}.formula{font:650 clamp(1rem,2vw,1.35rem)/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.formula-band p{margin:8px 0 0;color:var(--mut)}.facts{margin:0;padding:0;list-style:none}.facts li{padding:8px 0;border-bottom:1px solid var(--border)}.facts li:last-child{border:0}.notice{margin-top:16px;padding:12px 16px;border-left:4px solid var(--s2);background:color-mix(in srgb,var(--s2) 9%,transparent);border-radius:var(--r-sm)}
-    .comparison{margin-top:24px;padding-top:16px;border-top:1px solid var(--border)}.comparison table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}.comparison th,.comparison td{padding:8px 16px 8px 0;text-align:start;border-bottom:1px solid var(--border)}.comparison th{font-weight:600}.foot{display:flex;justify-content:space-between;gap:24px;margin-top:24px;padding-top:16px;border-top:1px solid var(--border);color:var(--mut);font-size:var(--fs-sm)}
-    @media(max-width:980px){.map-layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:repeat(3,1fr)}.formula-band{grid-template-columns:1fr}}
-    @media(max-width:680px){.top,.map-head,.foot{flex-direction:column;align-items:flex-start}.stamp{text-align:start}.deck{grid-template-columns:1fr}.side{grid-template-columns:1fr}.readout{grid-template-columns:1fr 1fr}.map-panel{padding:4px}.legend{justify-content:flex-start}.comparison{overflow-x:auto}.comparison table{min-width:520px}}
-    @media print{ :root{color-scheme:light}body{padding:0;background:#fff;color:#000}.no-print{display:none}.map-layout{grid-template-columns:2fr 1fr}*{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
-  </style>
-</head>
-<body>
-<main class="shell">
-  <header class="top">
-    <div><h1>Недельная траектория квоты</h1><p>К контроллеру важен не статичный порог, а вопрос «где мы должны быть к этому часу недели?». Двигайте два ползунка: target, коридоры и решение каждой lane обновятся сразу.</p></div>
-    <div class="stamp">Codex primary · 168 ч<br><strong>предпросмотр · теневой режим</strong></div>
-  </header>
-
-  <section class="deck no-print" aria-label="Параметры недельного окна">
-    <div class="control"><div class="control-head"><div><div class="control-label">Текущий usage</div><div class="sm mut">сообщённое использование + незавершённые резервации</div></div><output id="usage-output" class="control-value" for="usage">80<small>%</small></output></div><input id="usage" type="range" min="0" max="100" step="1" value="80" aria-label="Текущий usage в процентах"><div class="range-ends"><span>0%</span><span>100%</span></div></div>
-    <div class="control"><div class="control-head"><div><div class="control-label">Часы до сброса</div><div class="sm mut">h; слева — начало недели, справа — сброс</div></div><output id="hours-output" class="control-value" for="hours">120<small> ч</small></output></div><input id="hours" type="range" min="0" max="168" step="1" value="120" aria-label="Часы до сброса недельного окна"><div class="range-ends"><span>168 ч</span><span>0 ч</span></div><div class="quick"><button type="button" data-preset="early">Начало · 80%</button><button type="button" data-preset="late">Поздно · 80%</button></div></div>
-  </section>
-
-  <section class="readout" aria-live="polite"><div class="readout-item"><span>Плановая цель сейчас</span><strong id="read-target">—</strong></div><div class="readout-item"><span>Впереди / позади плана</span><strong id="read-ahead">—</strong></div><div class="readout-item"><span>Точка на траектории</span><strong id="read-point">—</strong></div><div class="readout-item"><span>Осталось до B = 99 − reserve</span><strong id="read-headroom">—</strong></div></section>
-
-  <div class="map-head"><div><h2>Usage × ход недели</h2><p>X — время недели от начала к сбросу · Y — usage. Ниже target — обычный режим; выше коридора — удержание.</p></div><div class="legend"><span class="normal"><i></i>normal</span><span class="middle"><i></i>Sol HOLD / Luna ALLOW</span><span class="hold"><i></i>both HOLD</span></div></div>
-  <section class="map-layout">
-    <div class="map-panel">
-      <svg id="quota-map" viewBox="0 0 980 610" role="img" aria-labelledby="map-title map-desc">
-        <title id="map-title">Недельная target-траектория и коридоры допуска</title><desc id="map-desc">График показывает target, коридоры Sol и Luna, жёсткий fit и текущую точку usage по ходу 168-часовой недели.</desc>
-        <path id="zone-hold" class="zone-hold"/><path id="zone-middle" class="zone-middle"/><path id="zone-normal" class="zone-normal"/>
-        <g aria-hidden="true">
-          <line class="grid" x1="84" y1="500" x2="900" y2="500"/><line class="grid" x1="84" y1="412" x2="900" y2="412"/><line class="grid" x1="84" y1="324" x2="900" y2="324"/><line class="grid" x1="84" y1="236" x2="900" y2="236"/><line class="grid" x1="84" y1="148" x2="900" y2="148"/><line class="grid" x1="84" y1="60" x2="900" y2="60"/>
-          <text x="44" y="505">0%</text><text x="35" y="417">20%</text><text x="35" y="329">40%</text><text x="35" y="241">60%</text><text x="35" y="153">80%</text><text x="28" y="65">100%</text>
-          <line class="grid" x1="84" y1="60" x2="84" y2="500"/><line class="grid" x1="288" y1="60" x2="288" y2="500"/><line class="grid" x1="492" y1="60" x2="492" y2="500"/><line class="grid" x1="696" y1="60" x2="696" y2="500"/><line class="grid" x1="900" y1="60" x2="900" y2="500"/>
-          <text x="74" y="529">начало</text><text x="270" y="529">−126 ч</text><text x="475" y="529">−84 ч</text><text x="679" y="529">−42 ч</text><text x="871" y="529">reset</text>
-          <line class="axis" x1="84" y1="500" x2="900" y2="500"/><line class="axis" x1="84" y1="60" x2="84" y2="500"/><text class="strong" x="417" y="570">время недели →</text><text class="strong" transform="translate(15 355) rotate(-90)">usage, %</text>
-        </g>
-        <path id="target-line" class="target"/><path id="sol-corridor" class="corridor-sol"/><path id="luna-corridor" class="corridor-luna"/><line id="sol-fit" class="fit"/><line id="luna-fit" class="fit"/>
-        <g id="zone-labels" aria-hidden="true"><text id="normal-label" class="zone-label">normal</text><text id="middle-label" class="zone-label">Sol HOLD / Luna ALLOW</text><text id="hold-label" class="zone-label">both HOLD</text></g>
-        <line id="cursor-x" class="cursor"/><line id="cursor-y" class="cursor"/><g id="current-point"><path class="current" d="M0 -12 L12 0 L0 12 L-12 0 Z"/><rect class="point-label" x="16" y="-25" rx="6" width="156" height="27"/><text class="point-text" x="27" y="-7">текущая точка</text></g>
-        <g id="line-labels"><rect class="point-label" x="100" y="82" rx="6" width="150" height="26"/><text class="point-text" x="112" y="100">target(h)</text><rect class="point-label" x="100" y="112" rx="6" width="190" height="26"/><text class="point-text" x="112" y="130">+10 / +15 pp — пример</text><rect class="point-label" x="650" y="420" rx="6" width="205" height="26"/><text class="point-text" x="662" y="438">q95 + guard — hard fit</text></g>
-      </svg>
-    </div>
-    <aside class="side" aria-label="Статус моделей">
-      <article id="card-sol" class="model"><div class="model-top"><h3>Sol · сложная линия</h3><span class="model-state">—</span></div><p class="model-copy"></p><div class="metric"><span>кандидат q95 + guard</span><strong>2,9 pp</strong></div><div class="metric"><span>точная причина</span><strong class="model-reason">—</strong></div></article>
-      <article id="card-luna" class="model"><div class="model-top"><h3>Luna · закрытая линия</h3><span class="model-state">—</span></div><p class="model-copy"></p><div class="metric"><span>кандидат q95 + guard</span><strong>1,2 pp</strong></div><div class="metric"><span>точная причина</span><strong class="model-reason">—</strong></div></article>
-      <article class="model allow"><div class="model-top"><h3>Spark · отдельный бакет</h3><span class="model-state">отдельно</span></div><p>Codex Spark не двигается ползунком Codex primary: собственный бакет и собственный telemetry gate.</p><div class="metric"><span>иллюстративный usage</span><strong>9%</strong></div></article>
-    </aside>
-  </section>
-
-  <section class="formula-band"><div><div class="formula">u<sub>eff</sub> + q95(next turn) + guard ≤ B</div><p><code>B = 99 − reserve</code>; <code>u_eff = reported utilization + unsettled reservations</code>. Target — это плановая траектория, а hard fit проверяет конкретную следующую работу и считается один раз.</p><div class="notice"><strong>Иллюстративная карта до калибровки #318.</strong> Для читаемого preview коридоры заданы как target + 10 pp (Sol) и target + 15 pp (Luna). Это не измеренный факт и не production contract; полный p50/p90/p95 moving-block bootstrap из #285 здесь не подменяется. В правой части недели линии коридоров визуально обрезаются рамкой 100%; решение всё равно считает исходные target + 10/15 pp и отдельно применяет hard fit.</div></div><ul class="facts"><li><strong id="reason-ahead">—</strong> — разница между фактическим и плановым usage.</li><li><strong id="reason-target">—</strong> — <code>target(h) = B × elapsed / W</code>, где <code>W = 168 ч</code>.</li><li><strong id="reason-fit">—</strong> — текущая lane может удержаться даже ниже визуального коридора, если hard fit не проходит.</li></ul></section>
-
-  <section class="comparison"><h2>Маленькое сравнение политики</h2><table><thead><tr><th>Сейчас</th><th>Новая система</th><th>Что меняется</th></tr></thead><tbody><tr><td>статичные 95/98%</td><td>траектория к 99% к reset</td><td>одинаковые 80% в начале и конце недели дают разный риск</td></tr><tr><td>порог не видит runway</td><td>target + reserve + q95-fit</td><td>решение объясняется точной причиной для lane</td></tr></tbody></table></section>
-  <footer class="foot"><span>Только предпросмотр · reserve = 1 pp · иллюстративные значения q95/guard</span><span>Источник фактов: <code>docs/tasks/321/source.json</code></span></footer>
-</main>
-<script>
-(() => {
-  'use strict';
-  const $ = s => document.querySelector(s);
-  const usage = $('#usage'), hours = $('#hours');
-  const W=168, reserve=1, B=99-reserve, guard=.5, q95={sol:2.4,luna:.7};
-  const X0=84,X1=900,Y0=500,Y1=60;
-  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
-  const sx=elapsed=>X0+elapsed/W*(X1-X0);
-  const sy=pct=>Y0-pct/100*(Y0-Y1);
-  const target=(h)=>B*(W-h)/W;
-  const corridor=(lane,h)=>target(h)+(lane==='sol'?10:15);
-  const hardFit=lane=>B-q95[lane]-guard;
-  const path=pts=>pts.map((p,i)=>`${i?'L':'M'} ${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(' ');
-  const fillBelow=pts=>`${path(pts)} L ${X1} ${Y0} L ${X0} ${Y0} Z`;
-  const fillBetween=(low,high)=>`${path(low)} ${high.slice().reverse().map(p=>`L ${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(' ')} Z`;
-  const fillAbove=pts=>`${path(pts)} L ${X1} ${Y1} L ${X0} ${Y1} Z`;
-  const fmt=n=>`${n.toFixed(1)}%`;
-  function sliderFill(input){input.style.setProperty('--fill',`${(Number(input.value)-Number(input.min))/(Number(input.max)-Number(input.min))*100}%`)}
-  function setCard(id,lane,allow,reason,delta){const card=$(id);card.className=`model ${allow?'allow':'hold'}`;card.querySelector('.model-state').textContent=allow?'ALLOW':'HOLD';card.querySelector('.model-copy').textContent=allow?`${lane==='sol'?'Sol':'Luna'} проходит: запас ${fmt(delta)} до hard fit.`:`${lane==='sol'?'Sol':'Luna'} удерживается: ${reason}`;card.querySelector('.model-reason').textContent=reason}
-  function update(){
-    const u=Number(usage.value), h=Number(hours.value), elapsed=W-h, t=target(h), ahead=u-t;
-    const solCorr=corridor('sol',h), lunaCorr=corridor('luna',h), solLimit=Math.min(solCorr,hardFit('sol')), lunaLimit=Math.min(lunaCorr,hardFit('luna'));
-    const solFit=u+q95.sol+guard<=B, lunaFit=u+q95.luna+guard<=B;
-    const solCorrOk=u<=solCorr, lunaCorrOk=u<=lunaCorr;
-    const solReason=!solFit?`hard fit: ${fmt(u+q95.sol+guard)} > ${fmt(B)}`:`коридор: ${fmt(u)} > ${fmt(solCorr)} (target + 10 pp)`;
-    const lunaReason=!lunaFit?`hard fit: ${fmt(u+q95.luna+guard)} > ${fmt(B)}`:`коридор: ${fmt(u)} > ${fmt(lunaCorr)} (target + 15 pp)`;
-    const solAllow=solFit&&solCorrOk, lunaAllow=lunaFit&&lunaCorrOk;
-    sliderFill(usage);sliderFill(hours);
-    $('#usage-output').innerHTML=`${u}<small>%</small>`;$('#hours-output').innerHTML=`${h}<small> ч</small>`;
-    $('#read-target').textContent=fmt(t);$('#read-ahead').textContent=`${ahead>=0?'+':''}${fmt(ahead)} ${ahead>=0?'позади':'впереди'}`;$('#read-point').textContent=`${u}% · ${h} ч`;$('#read-headroom').textContent=fmt(B-u);
-    $('#reason-ahead').textContent=`${ahead>=0?'+':''}${fmt(ahead)} ${ahead>=0?'позади':'впереди'} плана`;$('#reason-target').textContent=`target ${fmt(t)} при ${h} ч до reset`;$('#reason-fit').textContent=`B = ${fmt(B)}; hard fit Luna ${fmt(hardFit('luna'))}, Sol ${fmt(hardFit('sol'))}`;
-    setCard('#card-sol','sol',solAllow,solAllow?'проходит hard fit и находится в normal-коридоре':solReason,hardFit('sol')-u);
-    setCard('#card-luna','luna',lunaAllow,lunaAllow?'проходит hard fit и находится в допустимом коридоре':lunaReason,hardFit('luna')-u);
-    const pts=[],solPts=[],lunaPts=[],solLimitPts=[],lunaLimitPts=[];
-    for(let e=0;e<=W;e+=2){const hh=W-e;pts.push([e,target(hh)]);solPts.push([e,clamp(corridor('sol',hh),0,100)]);lunaPts.push([e,clamp(corridor('luna',hh),0,100)]);solLimitPts.push([e,clamp(Math.min(corridor('sol',hh),hardFit('sol')),0,100)]);lunaLimitPts.push([e,clamp(Math.min(corridor('luna',hh),hardFit('luna')),0,100)])}
-    $('#target-line').setAttribute('d',path(pts));$('#sol-corridor').setAttribute('d',path(solPts));$('#luna-corridor').setAttribute('d',path(lunaPts));$('#zone-normal').setAttribute('d',fillBelow(solLimitPts));$('#zone-middle').setAttribute('d',fillBetween(solLimitPts,lunaLimitPts));$('#zone-hold').setAttribute('d',fillAbove(lunaLimitPts));
-    $('#sol-fit').setAttribute('x1',X0);$('#sol-fit').setAttribute('x2',X1);$('#sol-fit').setAttribute('y1',sy(hardFit('sol')));$('#sol-fit').setAttribute('y2',sy(hardFit('sol')));$('#luna-fit').setAttribute('x1',X0);$('#luna-fit').setAttribute('x2',X1);$('#luna-fit').setAttribute('y1',sy(hardFit('luna')));$('#luna-fit').setAttribute('y2',sy(hardFit('luna')));
-    $('#normal-label').setAttribute('x',sx(clamp(elapsed+20,12,150)));$('#normal-label').setAttribute('y',sy(clamp(target(h)+3,8,92)));$('#middle-label').setAttribute('x',sx(clamp(elapsed+10,12,145)));$('#middle-label').setAttribute('y',sy(clamp((solCorr+lunaCorr)/2,8,92)));$('#hold-label').setAttribute('x',sx(clamp(elapsed-42,12,145)));$('#hold-label').setAttribute('y',sy(clamp(lunaCorr+8,8,96)));
-    const cx=sx(elapsed),cy=sy(u);$('#cursor-x').setAttribute('x1',cx);$('#cursor-x').setAttribute('x2',cx);$('#cursor-x').setAttribute('y1',Y1);$('#cursor-x').setAttribute('y2',Y0);$('#cursor-y').setAttribute('x1',X0);$('#cursor-y').setAttribute('x2',X1);$('#cursor-y').setAttribute('y1',cy);$('#cursor-y').setAttribute('y2',cy);$('#current-point').setAttribute('transform',`translate(${cx} ${cy})`);$('#map-desc').textContent=`Текущая точка ${u}% usage и ${h} часов до reset; target ${fmt(t)}. Sol ${solAllow?'ALLOW':'HOLD'}, Luna ${lunaAllow?'ALLOW':'HOLD'}.`;