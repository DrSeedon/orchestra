/* Фоновые задания агентов: понятные названия, «зачем», когда сработает, что уже было.
 * Чистая логика (cron, описание, время) живёт в window.JobsView и не трогает DOM —
 * её проверяет tests/test_jobs_view.py через node. Панель во вкладке JOBS рисует renderPanel. */
(function () {
    const TZ = 'Asia/Krasnoyarsk';
    const STALE_DAYS = 2;
    const VERY_STALE_DAYS = 7;

    const KINDS = {
        timer: {icon: '⏰', name: 'Напоминание', hint: 'разбудит агента один раз через заданное время'},
        cron: {icon: '🔁', name: 'По расписанию', hint: 'будит агента по расписанию, пока не отменят'},
        cron_command: {icon: '🔎', name: 'Проверка по расписанию', hint: 'запускает команду по расписанию, будит при совпадении'},
        idle: {icon: '💤', name: 'Сторож простоя', hint: 'будит агента, когда вся его ветка и другие задания затихли'},
        command: {icon: '🖥️', name: 'Сторож команды', hint: 'периодически запускает команду, будит при совпадении'},
        file: {icon: '📄', name: 'Сторож файла', hint: 'следит за файлом, будит при совпадении'},
        ssh: {icon: '🔗', name: 'Сторож по SSH', hint: 'читает вывод команды на другом хосте, будит при совпадении'},
        run: {icon: '▶️', name: 'Команда в фоне', hint: 'выполняет команду и будит агента по её завершении'},
        merge: {icon: '🔀', name: 'Слияние ветки', hint: 'ждёт исхода слияния'},
    };
    const STATES = {
        active: ['🟢', 'активно', '#4ade80'],
        triggering: ['🟡', 'срабатывает', '#fbbf24'],
        triggered: ['✅', 'сработало', '#94a3b8'],
        expired: ['⌛', 'истекло, не дождалось', '#fbbf24'],
        cancelled: ['🚫', 'отменено', '#64748b'],
        failed: ['❌', 'сбой', '#f87171'],
    };

    function parseCfg(job) {
        try { return JSON.parse(job.config || '{}') || {}; } catch (_) { return {}; }
    }

    function _field(spec, lo, hi) {
        const out = new Set();
        for (const part of spec.split(',')) {
            const [range, stepStr] = part.split('/');
            const step = stepStr ? parseInt(stepStr, 10) : 1;
            if (!(step > 0)) return null;
            let a = lo, b = hi;
            if (range !== '*') {
                const m = range.match(/^(\d+)(?:-(\d+))?$/);
                if (!m) return null;
                a = parseInt(m[1], 10);
                b = m[2] !== undefined ? parseInt(m[2], 10) : (stepStr ? hi : a);
            }
            if (a < lo || b > hi || a > b) return null;
            for (let v = a; v <= b; v += step) out.add(v);
        }
        return out;
    }

    /** Ближайшее срабатывание 5-польного cron (UTC, как в bg_jobs) строго после `after`, либо null. */
    function cronNext(expr, after) {
        const f = String(expr || '').trim().split(/\s+/);
        if (f.length !== 5) return null;
        let [mi, ho, dom, mo, dow] = [_field(f[0], 0, 59), _field(f[1], 0, 23), _field(f[2], 1, 31),
            _field(f[3], 1, 12), _field(f[4], 0, 7)];
        if (!mi || !ho || !dom || !mo || !dow) return null;
        if (dow.has(7)) dow.add(0);
        const domAny = f[2] === '*', dowAny = f[4] === '*';
        const hours = [...ho].sort((x, y) => x - y), mins = [...mi].sort((x, y) => x - y);
        const start = new Date(after.getTime());
        for (let d = 0; d < 800; d++) {
            const day = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + d));
            if (!mo.has(day.getUTCMonth() + 1)) continue;
            const domOk = dom.has(day.getUTCDate()), dowOk = dow.has(day.getUTCDay());
            const dayOk = !domAny && !dowAny ? (domOk || dowOk) : (domOk && dowOk);
            if (!dayOk) continue;
            for (const h of hours) for (const m of mins) {
                const t = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), h, m));
                if (t > after) return t;
            }
        }
        return null;
    }

    function _dur(ms) {
        const s = Math.max(0, Math.round(ms / 1000));
        const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        if (d >= 1) return h ? `${d} дн ${h} ч` : `${d} дн`;
        if (h >= 1) return m ? `${h} ч ${m} мин` : `${h} ч`;
        if (m >= 1) return `${m} мин`;
        return `${s} с`;
    }

    /** «через 3 ч» / «3 ч назад» относительно now. */
    function rel(at, now) {
        const diff = at.getTime() - now.getTime();
        return diff >= 0 ? `через ${_dur(diff)}` : `${_dur(-diff)} назад`;
    }

    /** Абсолютное время в Красноярске (UTC+7). */
    function krsk(at) {
        return new Intl.DateTimeFormat('ru-RU', {
            timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
        }).format(at) + ' КРСК';
    }

    function _date(s) {
        if (!s) return null;
        const d = new Date(s);
        return Number.isNaN(d.getTime()) ? null : d;
    }

    function _every(sec) {
        if (sec % 3600 === 0) return `${sec / 3600} ч`;
        if (sec % 60 === 0) return `${sec / 60} мин`;
        return `${sec} с`;
    }

    /** Всё, что нужно показать про задание, одним объектом. */
    function describe(job, now) {
        const cfg = parseCfg(job);
        const kind = KINDS[job.type] || {icon: '⚙️', name: job.type, hint: ''};
        const [sIcon, sName, sColor] = STATES[job.status] || ['⚪', job.status, '#94a3b8'];
        const live = job.status === 'active' || job.status === 'triggering';
        const created = _date(job.created_at);
        const ageMs = created ? now - created : 0;
        const ageDays = Math.floor(ageMs / 86400000);
        const permanent = !!cfg.no_expiry || job.type === 'cron' || job.type === 'cron_command';
        const out = {
            kind, cfg, live, sIcon, sName, sColor, ageDays,
            creator: job.created_by_name || '', target: job.target_name || '',
            nextAt: null, nextText: '', pastAt: null, pastText: '', scheduleText: '',
            stale: 0, staleText: '',
        };

        if (job.type === 'timer') {
            out.nextAt = _date(job.trigger_at);
        } else if (job.type === 'cron' || job.type === 'cron_command') {
            out.nextAt = cronNext(cfg.cron_expr, now);
            out.scheduleText = `расписание ${cfg.cron_expr || '?'} (UTC)`;
        } else if (cfg.interval_seconds) {
            out.scheduleText = `проверка каждые ${_every(cfg.interval_seconds)}`;
        }
        if (live && out.nextAt) {
            const late = job.type === 'timer' && out.nextAt < now;
            out.nextText = late ? `должно было сработать ${rel(out.nextAt, now)} — не сработало`
                : `сработает ${rel(out.nextAt, now)} · ${krsk(out.nextAt)}`;
        } else if (live && job.type === 'idle') {
            out.nextText = 'ждёт, пока всё затихнет';
        } else if (live && job.type === 'run') {
            out.nextText = 'выполняется';
        } else if (live) {
            const exp = _date(job.expires_at);
            out.nextText = permanent ? 'следит без срока' : exp ? `истекает ${rel(exp, now)} · ${krsk(exp)}` : '';
        }

        // Прошедшее: для расписаний — последний запуск и счётчик, для остальных — момент срабатывания.
        const fired = _date(cfg.last_fired_at) || _date(job.triggered_at);
        if (fired) {
            out.pastAt = fired;
            const n = cfg.fire_count ? ` · всего ${cfg.fire_count}×` : '';
            out.pastText = `${job.status === 'failed' ? 'сбой' : 'сработало'} ${rel(fired, now)} · ${krsk(fired)}${n}`;
        } else if (!live && created) {
            out.pastAt = created;
            out.pastText = `${sName}; поставлено ${rel(created, now)}`;
        }

        if (live && created) {
            const lateTimer = job.type === 'timer' && out.nextAt && out.nextAt < now;
            // Таймер с понятным сроком не «забыт»; забытым считаем вечное и просроченное.
            if (lateTimer) { out.stale = 2; out.staleText = 'застряло: срок вышел'; }
            else if (job.type !== 'timer' && ageDays >= VERY_STALE_DAYS) { out.stale = 2; out.staleText = `висит ${ageDays} дн`; }
            else if (job.type !== 'timer' && ageDays >= STALE_DAYS) { out.stale = 1; out.staleText = `висит ${ageDays} дн`; }
        }
        return out;
    }

    /** Лента: прошедшие и будущие события по времени, с границей «сейчас». */
    function buildTimeline(jobs, now) {
        const events = [];
        for (const job of jobs) {
            const d = describe(job, now);
            if (d.pastAt) events.push({at: d.pastAt, future: false, job, d});
            if (d.live && d.nextAt && d.nextAt >= now) events.push({at: d.nextAt, future: true, job, d});
        }
        events.sort((a, b) => a.at - b.at);
        return events;
    }

    window.JobsView = {cronNext, describe, buildTimeline, rel, krsk, KINDS, STATES};
    if (typeof document === 'undefined') return;

    const _expanded = new Set();
    const _VIEW_KEY = 'orchestra.jobsView';
    let _lastJobs = [];
    let _panel = null;

    function _viewMode() {
        try { return localStorage.getItem(_VIEW_KEY) === 'timeline' ? 'timeline' : 'agents'; } catch (_) { return 'agents'; }
    }

    function _card(job, now, showTarget) {
        const d = describe(job, now);
        const open = _expanded.has(job.id);
        const msg = (job.message || '').trim();
        const who = d.creator && d.creator !== d.target
            ? `поставил ${escHtml(d.creator)} → разбудит ${escHtml(d.target)}`
            : `${escHtml(d.target)} поставил себе`;
        const staleBadge = d.stale
            ? `<span class="job-stale job-stale-${d.stale}" title="Долго живущее задание — проверь, нужно ли оно">⚠ ${escHtml(d.staleText)}</span>` : '';
        const cancel = d.live ? `<button class="job-cancel-btn" data-job-cancel="${escHtml(job.id)}" title="Отменить задание">✕</button>` : '';
        const lines = [];
        if (d.nextText) lines.push(`<div class="job-line job-next">${escHtml(d.nextText)}</div>`);
        if (d.scheduleText) lines.push(`<div class="job-line">${escHtml(d.scheduleText)}</div>`);
        if (d.pastText) lines.push(`<div class="job-line job-past">${escHtml(d.pastText)}</div>`);
        let detail = '';
        if (open) {
            const row = (k, v) => v ? `<div><span class="job-k">${k}:</span> ${escHtml(String(v))}</div>` : '';
            detail = `<div class="job-detail">
                <div class="job-full">${escHtml(msg || '(без текста)')}</div>
                ${row('Тип', d.kind.name + ' — ' + d.kind.hint)}
                ${row('Кто → кого', `${d.creator || '?'} → ${d.target}`)}
                ${row('Поставлено', job.created_at ? `${krsk(new Date(job.created_at))} (${rel(new Date(job.created_at), now)})` : '')}
                ${row('Команда', d.cfg.command)}${row('Шаблон', d.cfg.pattern)}${row('Путь', d.cfg.path)}${row('Хост', d.cfg.host)}
                ${row('Ошибка', job.error)}
                ${job.last_output ? `<pre class="job-out">${escHtml(String(job.last_output).slice(-600))}</pre>` : ''}
                <div class="job-k">id: ${escHtml(job.id)}</div>
            </div>`;
        }
        return `<div class="job-card${d.live ? '' : ' job-done'}${d.stale === 2 ? ' job-card-stale' : ''}" data-job-id="${escHtml(job.id)}">
            <div class="job-head" data-job-toggle="${escHtml(job.id)}">
                <span class="job-kind" style="color:${d.sColor}" title="${escHtml(d.kind.hint)}">${d.kind.icon} ${escHtml(d.kind.name)}</span>
                <span class="job-state" style="color:${d.sColor}">${d.sIcon} ${escHtml(d.sName)}</span>${cancel}
            </div>
            <div class="job-msg${open ? '' : ' job-clamp'}" data-job-toggle="${escHtml(job.id)}">${escHtml(msg || '(без текста)')}</div>
            <div class="job-who">${showTarget ? who : (d.creator && d.creator !== d.target ? `поставил ${escHtml(d.creator)}` : 'себе')} ${staleBadge}</div>
            ${lines.join('')}${detail}
        </div>`;
    }

    function _agentsHtml(jobs, now) {
        const groups = new Map();
        for (const j of jobs) {
            const key = j.target_name || '?';
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(j);
        }
        const order = (j) => j.status === 'active' || j.status === 'triggering' ? 0 : 1;
        return [...groups.entries()].map(([name, list]) => {
            list.sort((a, b) => order(a) - order(b) || (a.created_at < b.created_at ? 1 : -1));
            const live = list.filter(j => order(j) === 0).length;
            return `<div class="job-group"><div class="job-group-h">🤖 ${escHtml(name)} <span>${live} активно · ${list.length} всего</span></div>
                ${list.map(j => _card(j, now, false)).join('')}</div>`;
        }).join('');
    }

    function _timelineHtml(jobs, now) {
        const events = buildTimeline(jobs, now);
        let nowDone = false, prevDay = '';
        const out = [];
        const marker = () => `<div class="job-now">▶ СЕЙЧАС · ${escHtml(krsk(now))}</div>`;
        for (const e of events) {
            if (!nowDone && e.at >= now) { out.push(marker()); nowDone = true; }
            const day = new Intl.DateTimeFormat('ru-RU', {timeZone: TZ, weekday: 'short', day: 'numeric', month: 'long'}).format(e.at);
            if (day !== prevDay) { out.push(`<div class="job-day">${escHtml(day)}</div>`); prevDay = day; }
            const hm = new Intl.DateTimeFormat('ru-RU', {timeZone: TZ, hour: '2-digit', minute: '2-digit'}).format(e.at);
            out.push(`<div class="job-ev ${e.future ? 'is-future' : 'is-past'}"><div class="job-ev-t">${hm}<br><span>${escHtml(rel(e.at, now))}</span></div>
                <div class="job-ev-c">${_card(e.job, now, true)}</div></div>`);
        }
        if (!nowDone) out.push(marker());
        return out.join('');
    }

    function renderPanel(panel, jobs) {
        _panel = panel; _lastJobs = jobs;
        const scrollTop = panel.scrollTop;
        if (!jobs.length) {
            panel.innerHTML = '<div class="p-4 text-center text-slate-600 italic">Фоновых заданий нет</div>';
            return;
        }
        const now = new Date();
        const mode = _viewMode();
        const live = jobs.filter(j => j.status === 'active' || j.status === 'triggering');
        const stale = live.filter(j => describe(j, now).stale).length;
        panel.innerHTML = `<div class="job-bar">
            <span>активно <b>${live.length}</b>${stale ? ` · <span class="job-stale job-stale-2">⚠ забытых ${stale}</span>` : ''}</span>
            <span class="job-switch"><button data-job-view="agents" class="${mode === 'agents' ? 'on' : ''}">По агентам</button><button data-job-view="timeline" class="${mode === 'timeline' ? 'on' : ''}">Лента</button></span>
        </div>${mode === 'timeline' ? _timelineHtml(jobs, now) : _agentsHtml(jobs, now)}`;
        panel.scrollTop = scrollTop;
        if (!panel._jobsBound) {
            panel._jobsBound = true;
            panel.addEventListener('click', _onClick);
        }
    }

    function _onClick(e) {
        const cancelBtn = e.target.closest('[data-job-cancel]');
        if (cancelBtn) {
            e.stopPropagation();
            cancelJob(cancelBtn.dataset.jobCancel);
            return;
        }
        const view = e.target.closest('[data-job-view]');
        if (view) {
            try { localStorage.setItem(_VIEW_KEY, view.dataset.jobView); } catch (_) {}
            renderPanel(_panel, _lastJobs);
            return;
        }
        const tog = e.target.closest('[data-job-toggle]');
        if (tog) {
            const id = tog.dataset.jobToggle;
            if (_expanded.has(id)) _expanded.delete(id); else _expanded.add(id);
            renderPanel(_panel, _lastJobs);
        }
    }

    window.renderJobsPanel = renderPanel;
    window.cancelJob = async function cancelJob(id) {
        const job = _lastJobs.find(j => j.id === id);
        const what = job ? `«${(job.message || '').slice(0, 80)}» (${job.target_name})` : id;
        if (!confirm(`Отменить фоновое задание?\n${what}`)) return;
        try {
            await fetch(`/api/bg/jobs/${encodeURIComponent(id)}`, {method: 'DELETE'});
            if (typeof loadJobs === 'function') loadJobs();
        } catch (e) { console.warn('Cancel job failed:', e); }
    };
})();
