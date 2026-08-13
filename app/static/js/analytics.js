// Usage Analytics control room. One snapshot powers every view.
let _analyticsChart = null;
let _analyticsPeriod = 'week';
let _analyticsView = 'overview';
let _analyticsPayload = null;
let _analyticsAgentFilter = 'all';
let _analyticsSelectedAgent = null;
let _analyticsRequestVersion = 0;

const _analyticsPeriods = {
    today: { label: 'Сегодня', days: 1 },
    week: { label: '7 дней', days: 7 },
    month: { label: '30 дней', days: 30 },
    all: { label: 'Всё время', days: 9999 },
};

const _analyticsViews = {
    overview: 'Пулы и расходы',
    agents: 'Агенты',
    efficiency: 'Эффективность',
    reliability: 'Надёжность',
};

// Chart.js — 204 КБ ради одной диаграммы в этой модалке. Он качался на КАЖДОЙ загрузке
// дашборда, а модалку открывают единицы раз в день (#64). Теперь грузится при открытии,
// один раз за жизнь страницы. Адрес берётся из шаблона — там же, где версия для кеша.
let _chartJsPromise = null;

function _ensureChartJs() {
    if (typeof Chart !== 'undefined') return Promise.resolve();
    if (_chartJsPromise) return _chartJsPromise;
    const src = document.getElementById('analytics-modal')?.dataset.chartSrc;
    _chartJsPromise = src
        ? new Promise((resolve, reject) => {
            const el = document.createElement('script');
            el.src = src;
            el.onload = resolve;
            el.onerror = () => reject(new Error(`не загрузился ${src}`));
            document.head.appendChild(el);
        })
        : Promise.reject(new Error('в разметке модалки нет data-chart-src'));
    return _chartJsPromise;
}

function openAnalyticsModal() {
    const modal = document.getElementById('analytics-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    _analyticsRenderControls();
    document.addEventListener('keydown', _analyticsEscHandler);
    // старт загрузки заранее, параллельно запросу данных; отказ покажет _analyticsRenderChart
    _ensureChartJs().catch(() => {});
    _analyticsLoad();
}

function closeAnalyticsModal() {
    const modal = document.getElementById('analytics-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    _analyticsRequestVersion += 1;
    _analyticsDestroyChart();
    document.removeEventListener('keydown', _analyticsEscHandler);
}

function _analyticsEscHandler(event) {
    if (event.key === 'Escape') closeAnalyticsModal();
}

function _analyticsDestroyChart() {
    if (_analyticsChart) {
        _analyticsChart.destroy();
        _analyticsChart = null;
    }
}

function _analyticsRenderControls() {
    const periods = document.getElementById('analytics-periods');
    const views = document.getElementById('analytics-view-tabs');
    const close = document.getElementById('analytics-close');
    if (periods) {
        periods.innerHTML = Object.entries(_analyticsPeriods).map(([key, item]) =>
            `<button type="button" data-analytics-period="${key}" class="${key === _analyticsPeriod ? 'active' : ''}">${item.label}</button>`
        ).join('');
        periods.querySelectorAll('[data-analytics-period]').forEach(button => {
            button.addEventListener('click', () => {
                const next = button.dataset.analyticsPeriod;
                if (next === _analyticsPeriod) return;
                _analyticsPeriod = next;
                _analyticsSelectedAgent = null;
                _analyticsRenderControls();
                _analyticsLoad();
            });
        });
    }
    if (views) {
        views.innerHTML = Object.entries(_analyticsViews).map(([key, label]) =>
            `<button type="button" role="tab" aria-selected="${key === _analyticsView}" data-analytics-view="${key}" class="${key === _analyticsView ? 'active' : ''}">${label}</button>`
        ).join('');
        views.querySelectorAll('[data-analytics-view]').forEach(button => {
            button.addEventListener('click', () => {
                _analyticsView = button.dataset.analyticsView;
                _analyticsRenderControls();
                _analyticsRender();
            });
        });
    }
    if (close) close.onclick = closeAnalyticsModal;
}

async function _analyticsLoad() {
    const body = document.getElementById('analytics-body');
    if (!body) return;
    _analyticsDestroyChart();
    body.innerHTML = '<div class="analytics-state"><span class="analytics-loader"></span>Собираю единый снимок…</div>';
    const days = _analyticsPeriods[_analyticsPeriod].days;
    const requestVersion = ++_analyticsRequestVersion;
    try {
        const payload = await api(`/api/usage/analytics?days=${days}`);
        if (requestVersion !== _analyticsRequestVersion) return;
        _analyticsPayload = payload;
        _analyticsRenderQuality();
        _analyticsRender();
    } catch (error) {
        if (requestVersion !== _analyticsRequestVersion) return;
        _analyticsPayload = null;
        _analyticsRenderQuality();
        body.innerHTML = `<div class="analytics-state analytics-state-error"><strong>Снимок недоступен</strong><span>${_analyticsEsc(error && error.message ? error.message : 'Неизвестная ошибка')}</span></div>`;
    }
}

function _analyticsRenderQuality() {
    const quality = document.getElementById('analytics-quality');
    if (!quality) return;
    if (!_analyticsPayload) {
        quality.innerHTML = '<span class="analytics-badge analytics-badge-danger">нет данных</span>';
        return;
    }
    const period = _analyticsPayload.period || {};
    const generated = _analyticsDateTime(_analyticsPayload.generated_at);
    quality.innerHTML = `${period.complete
        ? '<span class="analytics-badge analytics-badge-ok">полное окно</span>'
        : '<span class="analytics-badge analytics-badge-warn">частичная история</span>'}
        <span class="analytics-generated">${generated}</span>`;
}

function _analyticsRender() {
    const body = document.getElementById('analytics-body');
    if (!body || !_analyticsPayload) return;
    _analyticsDestroyChart();
    if (_analyticsView === 'agents') {
        _analyticsRenderAgents(body);
    } else if (_analyticsView === 'efficiency') {
        _analyticsRenderEfficiency(body);
    } else if (_analyticsView === 'reliability') {
        _analyticsRenderReliability(body);
    } else {
        _analyticsRenderOverview(body);
    }
}

function _analyticsRenderOverview(body) {
    const data = _analyticsPayload;
    const summary = data.summary || {};
    const lifetime = summary.lifetime || {};
    const providers = data.providers || {};
    const providerCards = Object.keys(_PROVIDER_META)
        .filter(provider => providers[provider] || _analyticsCapacity(provider))
        .map(provider => _analyticsProviderCard(provider, providers[provider] || {}))
        .join('');
    const routing = _analyticsRoutingSignal();
    const linkedTasks = Number(summary.linked_completed_tasks || 0);
    const observedTasks = Number(
        summary.fully_costed_linked_tasks
        ?? summary.fully_observed_linked_tasks
        ?? linkedTasks
    );
    const taskCostPartial = summary.task_cost_coverage_complete === false;
    const taskCost = taskCostPartial
        ? 'частичные данные'
        : summary.cost_per_linked_task == null
        ? 'нет связки'
        : _analyticsMoney(summary.cost_per_linked_task);
    const linkageCoverage = `${_analyticsNumber(linkedTasks)} / ${_analyticsNumber(summary.completed_tasks)}`;
    const taskCostDetail = taskCostPartial
        ? `точно оценено ${_analyticsNumber(observedTasks)} / ${_analyticsNumber(linkedTasks)} · связка ${linkageCoverage}`
        : `покрытие связки ${linkageCoverage}`;
    const pricedTurns = Number(summary.priced_turns ?? summary.agent_turns ?? 0);
    const unaccountedTurns = Number(summary.unaccounted_turns || 0);
    const observedCostDetail = `${_analyticsNumber(pricedTurns)} priced turns${unaccountedTurns ? ` · ${_analyticsNumber(unaccountedTurns)} unaccounted` : ''}`;

    body.innerHTML = `
        ${_analyticsWakePanel()}
        <section class="analytics-route analytics-route-${routing.tone}">
            <div><span class="analytics-eyebrow">Куда роутить сейчас</span><strong>${routing.title}</strong></div>
            <p>${routing.detail}</p>
        </section>
        <section>
            <div class="analytics-section-head"><div><span class="analytics-kicker">Два независимых пула</span><h3>Пулы и расходы</h3></div><span>Расходы виртуальные, лимиты подписочные</span></div>
            <div class="analytics-provider-grid">${providerCards || '<div class="analytics-empty">Данные провайдеров пока не накоплены.</div>'}</div>
        </section>
        <section class="analytics-kpi-grid">
            ${_analyticsKpi('За период', _analyticsMoney(summary.observed_cost_usd), observedCostDetail)}
            ${_analyticsKpi('Цена задачи', taskCost, taskCostDetail)}
            ${_analyticsKpi('Активно сейчас', _analyticsNumber(lifetime.active_agents), `${_analyticsNumber(lifetime.agents)} агентов всего`)}
            ${_analyticsKpi('За всё время', _analyticsMoney(lifetime.cost_usd), `${_analyticsNumber(lifetime.turns)} turns`)}
        </section>
        <section class="analytics-overview-grid">
            <article class="analytics-panel analytics-chart-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Burn rate</span><h3>Расход по дням</h3></div><span>Claude + Codex, stacked</span></div>
                <div class="analytics-chart-wrap">${(data.daily || []).length ? '<canvas id="analytics-chart"></canvas>' : '<div class="analytics-empty">Нет turn-cost данных за период.</div>'}</div>
            </article>
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Dispatcher</span><h3>Сигналы</h3></div></div>
                <div class="analytics-signal-list">
                    ${_analyticsSignalRows()}
                </div>
            </article>
        </section>`;
    const wakeButton = body.querySelector('[data-analytics-wake]');
    if (wakeButton) wakeButton.onclick = () => _analyticsScheduleWake(wakeButton);
    _analyticsRenderChart(data.daily || []);
}

function _analyticsWakePanel() {
    const wake = _analyticsPayload.wake_after_reset || {};
    const scheduled = wake.scheduled || [];
    const manual = wake.manual || [];
    const unavailable = wake.unavailable || [];
    const warnings = wake.warnings || [];
    const lines = [];
    let tone = 'neutral';
    for (const item of scheduled) {
        const names = (item.agents || []).map(_analyticsEsc).join(', ');
        const provider = _analyticsEsc(item.provider || 'provider');
        if (item.preserved) {
            const covered = names || 'текущие turn не покрыты';
            lines.push(`Сохранён прежний таймер ${provider} на ${_analyticsDateTime(item.reset_at)}: ${covered}.`);
        } else if (item.reason === 'available_now') {
            lines.push(`Сейчас разбудим ${provider}: ${names || '—'}.`);
        } else {
            lines.push(`Запланировано ${provider} на ${_analyticsDateTime(item.reset_at)}: ${names || '—'}.`);
        }
    }
    for (const item of manual) {
        const names = (item.agents || []).map(_analyticsEsc).join(', ');
        const url = _analyticsEsc(item.manual_action_url || 'https://claude.ai/settings/usage');
        lines.push(`Не проснутся сами: ${names || '—'}. Базовая квота не сбрасывается по таймеру; проверь лимит в <a href="${url}" target="_blank" rel="noopener">Claude Usage</a> и нажми кнопку снова.`);
    }
    for (const item of unavailable) {
        const names = (item.agents || []).map(_analyticsEsc).join(', ');
        lines.push(`Не запланированы: ${names || '—'}. ${_analyticsEsc(item.reason || 'Нет свежих данных о квоте')}.`);
    }
    for (const item of warnings) {
        const names = (item.agents || []).map(_analyticsEsc).join(', ');
        lines.push(`Предупреждение для ${names || '—'}: ${_analyticsEsc(item.reason || 'план не обновлён')}.`);
    }
    if (manual.length || unavailable.length) {
        tone = 'danger';
    } else if (warnings.length) {
        tone = 'danger';
    } else if (scheduled.length) {
        tone = 'ok';
    }
    if (!lines.length) {
        lines.push(
            wake.candidate_count
                ? 'Ничего не запланировано.'
                : 'Ничего не запланировано: сейчас нет агентов, чей последний turn завершился по subscription limit.'
        );
    }
    const detail = lines.join('<br>');
    return `<section class="analytics-wake analytics-wake-${tone}">
        <div>
            <span class="analytics-kicker">Recovery</span>
            <strong>Разбудить после сброса</strong>
            <p data-analytics-wake-status>${detail}</p>
        </div>
        <button type="button" data-analytics-wake>Разбудить после сброса</button>
    </section>`;
}

async function _analyticsScheduleWake(button) {
    const status = button.closest('.analytics-wake').querySelector('[data-analytics-wake-status]');
    button.disabled = true;
    button.textContent = 'Планирую…';
    try {
        const result = await api('/api/usage/wake-after-reset', { method: 'POST' });
        _analyticsPayload.wake_after_reset = result;
        _analyticsRender();
    } catch (error) {
        status.textContent = error && error.message ? error.message : 'Не удалось поставить таймер.';
        button.disabled = false;
        button.textContent = 'Повторить';
    }
}

function _analyticsProviderCard(provider, stats) {
    const meta = _PROVIDER_META[provider] || {
        title: provider, runtime: '', tone: 'slate', windows: () => [],
    };
    const capacity = _analyticsCapacity(provider);
    const { title, runtime, tone } = meta;
    const ttl = stats.cache_ttl_seconds
        ? `${Math.round(stats.cache_ttl_seconds / 60)} мин${stats.cache_ttl_approximate ? ' ≈' : ''}`
        : '—';
    let windows = '';
    if (capacity) {
        windows = meta.windows(capacity)
            .filter(([, value]) => value && value.utilization != null)
            .map(([label, value]) => _analyticsWindow(label, value))
            .join('');
        if (provider === 'codex' && capacity.spark) {
            const sparkWindows = [capacity.spark.primary, capacity.spark.secondary]
                .filter(value => value && value.utilization != null);
            if (sparkWindows.length) {
                windows += `<div class="analytics-spark"><span>Spark — отдельный bucket</span>${sparkWindows.map((value, index) => _analyticsWindow(index ? 'Вторичный' : 'Основной', value)).join('')}</div>`;
            }
        }
    }
    return `<article class="analytics-provider analytics-provider-${tone}" data-analytics-provider="${provider}">
        <div class="analytics-provider-head">
            <div><span class="analytics-provider-dot"></span><div><h3>${title}</h3><p>${runtime}</p></div></div>
            <strong>${_analyticsMoney(stats.cost_usd)}${stats.unaccounted_turns ? ` <small>· ${_analyticsNumber(stats.unaccounted_turns)} unaccounted</small>` : ''}</strong>
        </div>
        <div class="analytics-provider-metrics">
            <div><span>Turns</span><strong>${_analyticsNumber(stats.turns)}</strong></div>
            <div><span>Cache hit</span><strong>${stats.cache_hit_pct == null ? '—' : `${stats.cache_hit_pct}%`}</strong></div>
            <div><span>Cold starts</span><strong>${_analyticsNumber(stats.cold_starts)}</strong></div>
            <div><span>TTL</span><strong>${ttl}</strong></div>
        </div>
        <div class="analytics-window-list">${windows || '<span class="analytics-muted">Лимиты провайдера недоступны — значения не подменены нулями.</span>'}</div>
    </article>`;
}

function _analyticsWindow(label, value) {
    const pct = Math.max(0, Math.min(Number(value.utilization) || 0, 100));
    const tone = pct >= 80 ? 'danger' : pct >= 55 ? 'warn' : 'ok';
    return `<div class="analytics-window">
        <div><span>${label}</span><strong class="analytics-text-${tone}">${pct}%</strong></div>
        <div class="analytics-meter"><i class="analytics-meter-${tone}" style="width:${pct}%"></i></div>
        <small>${value.resets_at ? `reset ${_analyticsDateTime(value.resets_at)}` : 'reset неизвестен'}</small>
    </div>`;
}

function _analyticsRoutingSignal() {
    const claude = _analyticsCapacity('claude');
    const codex = _analyticsCapacity('codex');
    const claudeValues = claude ? [claude.five_hour, claude.seven_day].filter(Boolean).map(item => Number(item.utilization)) : [];
    const codexValues = codex ? [codex.primary, codex.secondary].filter(Boolean).map(item => Number(item.utilization)) : [];
    if (!claudeValues.length || !codexValues.length) {
        return { tone: 'neutral', title: 'Недостаточно данных о лимитах', detail: 'Роутинг не угадывается: минимум один provider snapshot отсутствует.' };
    }
    const claudePressure = Math.max(...claudeValues);
    const codexPressure = Math.max(...codexValues);
    const provider = codexPressure <= claudePressure ? 'Codex' : 'Claude';
    return {
        tone: Math.min(claudePressure, codexPressure) >= 80 ? 'danger' : 'ok',
        title: `${provider} — свободнее`,
        detail: `Пиковая загрузка Claude ${claudePressure}%, Codex ${codexPressure}%. Это capacity-сигнал, а не автоматическое переключение.`,
    };
}

function _analyticsSignalRows() {
    const agents = _analyticsPayload.agents || [];
    const anomalies = agents.filter(agent => agent.anomaly);
    const providers = _analyticsPayload.providers || {};
    const cold = Object.entries(providers)
        .sort((a, b) => (b[1].cold_starts || 0) - (a[1].cold_starts || 0))[0];
    const period = _analyticsPayload.period || {};
    return `
        <div class="analytics-signal"><span class="${anomalies.length ? 'analytics-text-warn' : 'analytics-text-ok'}">${anomalies.length ? 'CHECK' : 'OK'}</span><div><strong>${anomalies.length} аномальных агентов</strong><p>Сигнал: cost/priced turn ≥ 4× медианы при ≥2 priced turns.</p></div></div>
        <div class="analytics-signal"><span>${cold ? _analyticsEsc(cold[0].toUpperCase()) : '—'}</span><div><strong>${cold ? `${_analyticsNumber(cold[1].cold_starts)} cold starts` : 'Cache пока пуст'}</strong><p>TTL считается отдельно для каждого runtime.</p></div></div>
        <div class="analytics-signal"><span class="${period.complete ? 'analytics-text-ok' : 'analytics-text-warn'}">${period.complete ? 'FULL' : 'PART'}</span><div><strong>${period.complete ? 'Полное окно' : 'Частичная retention'}</strong><p>${period.observed_from ? `Наблюдаем с ${_analyticsDateTime(period.observed_from)}.` : 'За период нет наблюдений.'}</p></div></div>`;
}

function _analyticsRenderAgents(body) {
    const allAgents = _analyticsPayload.agents || [];
    const agents = allAgents.filter(agent => {
        if (_analyticsAgentFilter === 'anomaly') return agent.anomaly;
        if (_PROVIDER_META[_analyticsAgentFilter]) return agent.provider === _analyticsAgentFilter;
        return true;
    });
    const selected = _analyticsSelectedAgent
        ? allAgents.find(agent => String(agent.id) === String(_analyticsSelectedAgent))
        : null;
    body.innerHTML = `
        <section class="analytics-panel analytics-agents-panel">
            <div class="analytics-section-head analytics-filter-head">
                <div><span class="analytics-kicker">Fleet</span><h3>Агенты и стоимость</h3></div>
                <div class="analytics-filters">
                    ${[['all', 'Все'], ...Object.entries(_PROVIDER_META).map(([key, meta]) => [key, meta.title]), ['anomaly', 'Аномалии']].map(([key, label]) =>
                        `<button type="button" data-analytics-agent-filter="${key}" class="${key === _analyticsAgentFilter ? 'active' : ''}">${label}</button>`
                    ).join('')}
                </div>
            </div>
            <div class="analytics-table-wrap">
                <table class="analytics-table">
                    <thead><tr><th>Агент</th><th>Модель</th><th>Провайдер</th><th>Turns</th><th>Observed cost</th><th>Cost / priced turn</th><th>Последний turn</th></tr></thead>
                    <tbody id="analytics-agent-table">${agents.map(agent => `
                        <tr data-analytics-agent="${_analyticsEsc(agent.id)}" class="${agent.anomaly ? 'analytics-row-anomaly' : ''}">
                            <td><strong>${_analyticsEsc(agent.name || 'unknown')}</strong>${agent.anomaly ? '<span class="analytics-badge analytics-badge-warn">4× signal</span>' : ''}<small>${_analyticsEsc(agent.scope || '')}</small></td>
                            <td>${_analyticsEsc(agent.model || 'unknown')}</td>
                            <td><span class="analytics-provider-tag analytics-provider-tag-${_analyticsEsc(agent.provider)}">${_analyticsEsc(agent.provider)}</span></td>
                            <td>${_analyticsNumber(agent.turns)}</td>
                            <td>${_analyticsMoney(agent.cost_usd)}${agent.unaccounted_turns ? `<small>${_analyticsNumber(agent.unaccounted_turns)} unaccounted</small>` : ''}</td>
                            <td>${_analyticsMoney(agent.cost_per_priced_turn ?? agent.cost_per_turn)}</td>
                            <td>${_analyticsDateTime(agent.last_turn)}</td>
                        </tr>`).join('')}</tbody>
                </table>
                ${agents.length ? '' : '<div class="analytics-empty">Нет агентов для этого фильтра.</div>'}
            </div>
        </section>
        <section id="analytics-agent-detail" class="analytics-agent-detail">${selected ? _analyticsAgentDetail(selected) : '<span>Нажмите на агента — здесь появится проверяемая разбивка.</span>'}</section>`;
    body.querySelectorAll('[data-analytics-agent-filter]').forEach(button => {
        button.addEventListener('click', () => {
            _analyticsAgentFilter = button.dataset.analyticsAgentFilter;
            _analyticsSelectedAgent = null;
            _analyticsRenderAgents(body);
        });
    });
    body.querySelectorAll('[data-analytics-agent]').forEach(row => {
        row.addEventListener('click', () => {
            _analyticsSelectedAgent = row.dataset.analyticsAgent;
            _analyticsRenderAgents(body);
        });
    });
}

function _analyticsAgentDetail(agent) {
    return `<div><span class="analytics-kicker">Agent drill-down</span><h3>${_analyticsEsc(agent.name)}</h3><p>${_analyticsEsc(agent.scope || 'scope неизвестен')}</p></div>
        <dl>
            <div><dt>Модель</dt><dd>${_analyticsEsc(agent.model || 'unknown')}</dd></div>
            <div><dt>Провайдер</dt><dd>${_analyticsEsc(agent.provider || 'unknown')}</dd></div>
            <div><dt>Turns</dt><dd>${_analyticsNumber(agent.turns)}</dd></div>
            <div><dt>Observed cost</dt><dd>${_analyticsMoney(agent.cost_usd)}</dd></div>
            <div><dt>Priced / unaccounted</dt><dd>${_analyticsNumber(agent.priced_turns ?? agent.turns)} / ${_analyticsNumber(agent.unaccounted_turns)}</dd></div>
            <div><dt>Cost / priced turn</dt><dd>${_analyticsMoney(agent.cost_per_priced_turn ?? agent.cost_per_turn)}</dd></div>
            <div><dt>Последний turn</dt><dd>${_analyticsDateTime(agent.last_turn)}</dd></div>
        </dl>
        ${agent.anomaly ? '<p class="analytics-detail-note">Сигнал, не вердикт: cost/priced turn ≥ 4× медианы флота при минимум двух priced turns.</p>' : ''}`;
}

function _analyticsRenderEfficiency(body) {
    const providers = _analyticsPayload.providers || {};
    const models = _analyticsPayload.models || [];
    body.innerHTML = `
        <section class="analytics-efficiency-grid">
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Cache</span><h3>Эффективность по runtime</h3></div><span>только сравнимые turns</span></div>
                <div class="analytics-cache-grid">${Object.keys(_PROVIDER_META).filter(p => providers[p]).map(provider => {
                    const item = providers[provider] || {};
                    const ttl = item.cache_ttl_seconds ? Math.round(item.cache_ttl_seconds / 60) : null;
                    return `<div class="analytics-cache-card">
                        <div><strong>${_PROVIDER_META[provider].title}</strong><span>TTL ${ttl == null ? '—' : `${ttl} мин${item.cache_ttl_approximate ? ' ≈' : ''}`}</span></div>
                        <b>${item.cache_hit_pct == null ? '—' : `${item.cache_hit_pct}%`}</b>
                        <p>${_analyticsNumber(item.comparable_turns)} сравнимых turns · ${_analyticsNumber(item.cold_starts)} cold starts</p>
                    </div>`;
                }).join('')}</div>
            </article>
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Model mix</span><h3>Куда ушла работа</h3></div><span>доли observed cost</span></div>
                <div class="analytics-model-list">${models.map(model => `
                    <div class="analytics-model-row">
                        <div><strong>${_analyticsEsc(model.model || 'unknown')}</strong><span>${_analyticsEsc(model.provider)} · ${_analyticsNumber(model.priced_turns ?? model.turns)} priced${model.unaccounted_turns ? ` · ${_analyticsNumber(model.unaccounted_turns)} unaccounted` : ''}</span></div>
                        <div class="analytics-model-value"><b>${model.cost_share_pct == null ? '—' : `${Number(model.cost_share_pct).toFixed(1)}%`}</b><span>${_analyticsMoney(model.cost_usd)}</span></div>
                        <div class="analytics-model-track"><i class="analytics-model-${_analyticsEsc(model.provider)}" style="width:${Math.max(0, Math.min(Number(model.cost_share_pct) || 0, 100))}%"></i></div>
                    </div>`).join('') || '<div class="analytics-empty">Нет model-mix данных.</div>'}</div>
            </article>
        </section>`;
}

function _analyticsRenderReliability(body) {
    const reliability = _analyticsPayload.reliability || {};
    const subagents = reliability.subagents || {};
    const background = reliability.background_tasks || {};
    const voice = reliability.voice || {};
    const linkage = reliability.task_linkage || {};
    const errors = reliability.tool_errors || {};
    const turns = reliability.turn_usage || {};
    const errorItems = errors.items || [];
    let errorBlock;
    if (!errors.collector_ready) {
        errorBlock = '<div class="analytics-collector-gap"><strong>нет collector</strong><span>Исторические tool failures не наблюдались структурно; ноль показывать было бы ложью.</span></div>';
    } else if (errorItems.length) {
        errorBlock = `<div class="analytics-error-list">${errorItems.map(item => `<div><strong>${_analyticsEsc(item.tool_name || item.tool || 'unknown')}</strong><span>${_analyticsNumber(item.count)} failures</span><p>${_analyticsEsc(item.last_error || item.error || '')}</p></div>`).join('')}${errors.coverage_complete ? '' : '<div class="analytics-collector-gap"><strong>частичное покрытие</strong><span>Рейтинг включает только события после запуска collector.</span></div>'}</div>`;
    } else if (errors.coverage_complete) {
        errorBlock = '<div class="analytics-error-list"><span class="analytics-text-ok">Ошибок в полностью собранном окне нет.</span></div>';
    } else {
        errorBlock = `<div class="analytics-collector-gap"><strong>частичное покрытие</strong><span>Collector работает с ${_analyticsDateTime(errors.collector_started_at)}; более ранние failures неизвестны.</span></div>`;
    }
    const turnBlock = turns.collector_ready
        ? `<strong>${_analyticsNumber(turns.recorded_rows)} структурных turns</strong><span>${_analyticsNumber(turns.priced_rows ?? turns.recorded_rows)} priced · ${_analyticsNumber(turns.unaccounted_rows)} unaccounted · ${turns.coverage_complete ? 'полное окно' : 'частичное покрытие'} · с ${_analyticsDateTime(turns.collector_started_at || turns.observed_from)}</span>`
        : '<strong>нет collector</strong><span>Per-turn tokens/model/cache пока не собирались структурно.</span>';
    body.innerHTML = `
        <section class="analytics-reliability-grid">
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Delegation</span><h3>Native subagents</h3></div><span>без фоновых Bash</span></div>
                <div class="analytics-status-grid">
                    ${_analyticsStatus('Completed', subagents.completed, 'ok')}
                    ${_analyticsStatus('Failed', subagents.failed, 'danger')}
                    ${_analyticsStatus('Running', subagents.running, 'cyan')}
                    ${_analyticsStatus('Stopped', subagents.stopped, 'muted')}
                </div>
                <div class="analytics-reliability-stats">
                    <div><span>Фоновые Bash</span><strong>${_analyticsNumber(background.total)}</strong><small>${_analyticsNumber(background.failed)} failed · тот же событийный поток, но это не делегирование</small></div>
                    ${subagents.unclassified ? `<div><span>Неизвестный тип</span><strong>${_analyticsNumber(subagents.unclassified)}</strong><small>task_type не распознан — в делегирование не засчитаны</small></div>` : ''}
                </div>
                <p class="analytics-footnote">Считаются local_agent (Claude) и codex. Фоновые Bash-задачи приходят тем же событием <code>subagent_start</code> и раньше попадали сюда же — на живой базе это завышало цифру примерно в 390 раз.</p>
            </article>
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Coverage</span><h3>Задачи и голос</h3></div></div>
                <div class="analytics-reliability-stats">
                    <div><span>Task linkage</span><strong>${_analyticsNumber(linkage.linked)} / ${_analyticsNumber(linkage.total)}</strong><small>стоимость задачи считается только по связанным sessions</small></div>
                    <div><span>Voice</span><strong>${_analyticsNumber(voice.entries)} записей</strong><small>${_analyticsDuration(voice.duration_sec)} · ${_analyticsMoney(voice.cost_usd)}</small></div>
                </div>
            </article>
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Tool health</span><h3>Ошибки инструментов</h3></div></div>
                ${errorBlock}
            </article>
            <article class="analytics-panel">
                <div class="analytics-section-head"><div><span class="analytics-kicker">Structured telemetry</span><h3>Per-turn события</h3></div></div>
                <div class="analytics-collector-gap">${turnBlock}</div>
            </article>
        </section>`;
}

function _analyticsStatus(label, value, tone) {
    return `<div><span>${label}</span><strong class="analytics-text-${tone}">${_analyticsNumber(value)}</strong></div>`;
}

async function _analyticsRenderChart(daily) {
    if (!daily.length) return;
    const canvas = document.getElementById('analytics-chart');
    if (!canvas) return;
    try {
        await _ensureChartJs();
    } catch (e) {
        // Молчать нельзя: пустое место на графике выглядит как «данных нет»
        canvas.replaceWith(Object.assign(document.createElement('div'), {
            className: 'analytics-text-warn', textContent: `График не отрисован: ${e.message}`,
        }));
        return;
    }
    _analyticsChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: daily.map(day => String(day.day || '').slice(5)),
            datasets: [
                {
                    label: 'Claude',
                    data: daily.map(day => {
                        const value = (((day.providers || {}).claude || {}).cost_usd);
                        return value == null ? null : Number(value);
                    }),
                    backgroundColor: 'rgba(167, 139, 250, .72)',
                    borderColor: '#a78bfa',
                    borderWidth: 1,
                },
                {
                    label: 'Codex',
                    data: daily.map(day => {
                        const value = (((day.providers || {}).codex || {}).cost_usd);
                        return value == null ? null : Number(value);
                    }),
                    backgroundColor: 'rgba(34, 211, 238, .65)',
                    borderColor: '#22d3ee',
                    borderWidth: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 } } },
                tooltip: {
                    backgroundColor: '#0b111b',
                    borderColor: '#334155',
                    borderWidth: 1,
                    callbacks: { label: context => `${context.dataset.label}: ${_analyticsMoney(context.raw)}` },
                },
            },
            scales: {
                x: { stacked: true, ticks: { color: '#64748b', font: { size: 9 } }, grid: { display: false } },
                y: { stacked: true, beginAtZero: true, ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(51, 65, 85, .35)' } },
            },
        },
    });
}

function _analyticsCapacity(provider) {
    const capacity = (_analyticsPayload || {}).capacity || {};
    const key = _PROVIDER_CAPACITY_KEY[provider];
    return key ? capacity[key] : null;
}

function _analyticsKpi(label, value, detail) {
    return `<article><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>`;
}

function _analyticsMoney(value) {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const amount = Number(value);
    return `${MODEL_COST_CURRENCY}${amount.toLocaleString('ru-RU', { minimumFractionDigits: amount < 100 ? 2 : 0, maximumFractionDigits: 2 })}`;
}

function _analyticsNumber(value) {
    return Number(value || 0).toLocaleString('ru-RU');
}

function _analyticsDateTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return _analyticsEsc(String(value));
    return date.toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function _analyticsDuration(seconds) {
    const total = Number(seconds || 0);
    if (total < 60) return `${Math.round(total)} сек`;
    return `${Math.floor(total / 60)} мин ${Math.round(total % 60)} сек`;
}

function _analyticsEsc(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
}
