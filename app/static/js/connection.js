window.Connection = (() => {
    const GENERATION_KEY = 'orchestra_server_generation';
    const RESTART_MAX_MS = 120000;
    const storageGet = key => {
        try { return localStorage.getItem(key) || ''; } catch { return ''; }
    };
    const storageSet = (key, value) => {
        try { localStorage.setItem(key, value); } catch {}
    };
    const state = {
        phase: 'online', reason: '', title: '', message: '', path: '', attempts: 0,
        generation: storageGet(GENERATION_KEY), startedAt: '',
        lastOkAt: Date.now(), stale: new Map(), failures: new Map(), flash: '',
        flashTimer: null,
    };
    let restartPending = false;
    let restartPendingSince = 0;
    let consecutiveFailures = 0;
    let wasDown = false;
    let reconnecting = false;
    let recovering = false;
    const pageBuild = document.body.dataset.build || '';
    let buildBannerShown = false;

    const ownsErrors = () => state.phase !== 'online';
    const pathOf = url => String(url || '').split('?')[0];

    function showBuildBanner(serverBuild) {
        if (buildBannerShown) return;
        buildBannerShown = true;
        console.warn(`[build] страница собрана на ${pageBuild}, сервер отдаёт ${serverBuild}`);
        const banner = document.createElement('div');
        banner.id = 'build-banner';
        banner.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:16px;z-index:99998;'
            + 'display:flex;align-items:center;gap:10px;padding:8px 14px;border-radius:10px;'
            + 'background:#1e293b;border:1px solid #f59e0b66;color:#fde68a;font-size:12px;'
            + 'box-shadow:0 8px 24px rgba(0,0,0,.4)';
        banner.innerHTML = '<span>Сервер обновился — обнови страницу, чтобы взять новую версию</span>';
        const close = document.createElement('button');
        close.style.cssText = 'padding:3px 10px;border:1px solid #475569;border-radius:6px;'
            + 'background:transparent;color:#cbd5e1;cursor:pointer;font-size:12px';
        close.textContent = 'Скрыть';
        close.onclick = () => banner.remove();
        banner.appendChild(close);
        document.body.appendChild(banner);
    }

    function rerenderDependents() {
        if (typeof renderUsageBar === 'function') renderUsageBar();
        window.QuotaPanel?.render?.();
    }

    function savedDetail() {
        const items = [...state.stale.entries()]
            .map(([key, ts]) => `${key}: ${snapshotAgeLabel(ts)}`);
        return items.length ? ` Показано сохранённое: ${items.join(' · ')}.` : '';
    }

    function detail() {
        if (state.message) return state.message;
        if (state.phase === 'restarting') {
            return 'Данные на экране сохранены; chat, files, sessions и usage обновятся автоматически.'
                + savedDetail();
        }
        if (state.phase === 'recovering') {
            return 'Обновляю chat, files, sessions, usage, quota и models.' + savedDetail();
        }
        if (state.phase === 'offline') {
            return 'Причина проверяется автоматически; сохранённые данные не выдаются за свежие.'
                + savedDetail();
        }
        if (state.phase === 'degraded') {
            const source = state.path ? `${state.path} не ответил вовремя.` : 'Часть данных не обновилась.';
            return source + savedDetail();
        }
        return state.flash;
    }

    function render() {
        const banner = document.getElementById('connection-banner');
        if (!banner) return;
        if (state.phase === 'online' && !state.flash) {
            banner.classList.add('hidden');
            banner.replaceChildren();
            delete banner.dataset.phase;
            return;
        }
        const labels = {
            restarting: ['🔄', 'Orchestra перезапускается'],
            recovering: ['↻', state.reason === 'restart' ? 'Orchestra перезапустилась' : 'Связь восстановлена'],
            degraded: ['⚠', 'Связь нестабильна'],
            offline: ['●', 'Orchestra недоступна'],
            online: ['✓', state.flash || 'Связь восстановлена'],
        };
        const [icon, defaultTitle] = labels[state.phase] || labels.offline;
        banner.dataset.phase = state.phase;
        banner.classList.remove('hidden');
        banner.innerHTML = `<span aria-hidden="true">${icon}</span>`
            + `<b>${escHtml(state.title || defaultTitle)}</b>`
            + (detail() ? `<span class="connection-detail">${escHtml(detail())}</span>` : '');
    }

    function set(phase, options = {}) {
        state.phase = phase;
        if (Object.hasOwn(options, 'reason')) state.reason = options.reason || '';
        state.title = options.title || '';
        state.message = options.message || '';
        if (Object.hasOwn(options, 'path')) state.path = options.path || '';
        if (Object.hasOwn(options, 'attempts')) state.attempts = Number(options.attempts) || 0;
        if (Object.hasOwn(options, 'flash')) state.flash = options.flash || '';
        if (state.flashTimer) {
            clearTimeout(state.flashTimer);
            state.flashTimer = null;
        }
        render();
        rerenderDependents();
    }

    function startReconnect() {
        if (reconnecting) return;
        reconnecting = true;
        void reconnectLoop();
    }

    function fail(url, error, attempts = 1) {
        const path = pathOf(url);
        state.failures.set(path, {error, at: Date.now()});
        if (restartPending || state.phase === 'restarting') {
            wasDown = true;
            set('restarting', {reason: 'restart', path, attempts});
            startReconnect();
            return;
        }
        const hardDown = error?.name === 'TypeError'
            || Number(error?.status) >= 502 || navigator.onLine === false;
        if (hardDown) {
            wasDown = true;
            consecutiveFailures += 1;
        }
        set(hardDown ? 'offline' : 'degraded', {
            reason: hardDown ? 'unconfirmed' : 'slow', path, attempts,
        });
        if (hardDown && consecutiveFailures >= 2) startReconnect();
    }

    function ok(url) {
        consecutiveFailures = 0;
        state.lastOkAt = Date.now();
        state.failures.delete(pathOf(url));
        if (state.phase === 'degraded' && state.reason !== 'restart_failed'
            && !state.failures.size && !state.stale.size) set('online');
        if (wasDown && !restartPending && state.phase !== 'restarting') {
            reconnecting = false;
            void recover();
        }
    }

    function setRestarting(on) {
        if (on) restartPendingSince = Date.now();
        if (on === restartPending) return;
        const wasPending = restartPending;
        restartPending = on;
        if (on) {
            wasDown = true;
            set('restarting', {reason: 'restart'});
            startReconnect();
        } else if (wasPending && state.phase === 'restarting') {
            set('recovering', {reason: 'restart'});
        }
    }

    function observe(response, url = '') {
        const header = name => response?.headers?.get?.(name) || '';
        const restarting = header('X-Orchestra-Restarting');
        const generation = header('X-Orchestra-Generation');
        const startedAt = header('X-Orchestra-Started-At');
        const previous = state.generation || storageGet(GENERATION_KEY);
        const changed = Boolean(previous && generation && previous !== generation);
        const startedMs = Date.parse(startedAt);
        const recentFirstStart = Boolean(!previous && generation && Number.isFinite(startedMs)
            && Date.now() - startedMs >= 0 && Date.now() - startedMs < RESTART_MAX_MS);
        if (generation) {
            state.generation = generation;
            storageSet(GENERATION_KEY, generation);
        }
        if (startedAt) state.startedAt = startedAt;
        state.lastOkAt = Date.now();
        if (restarting === '1') return setRestarting(true);
        if (changed || recentFirstStart) {
            wasDown = true;
            restartPending = false;
            set('recovering', {reason: 'restart', path: pathOf(url)});
        } else if (restarting === '0' && restartPending) {
            restartPending = false;
            set('recovering', {reason: 'restart', path: pathOf(url)});
        }
    }

    function restartFromBody(status, text) {
        if (status !== 503) return false;
        try { return JSON.parse(text)?.error?.code === 'restart_pending'; } catch { return false; }
    }

    function restartAttempt(message, failed) {
        if (failed) {
            set('degraded', {reason: 'restart_failed', title: 'Рестарт не выполнен', message});
            return;
        }
        restartPending = true;
        restartPendingSince = Date.now();
        wasDown = true;
        set('restarting', {reason: 'restart', title: 'Orchestra перезапускается', message});
        startReconnect();
    }

    function stale(key, ts) {
        state.stale.set(key, ts);
        if (!['restarting', 'recovering', 'offline'].includes(state.phase)) {
            set('degraded', {reason: 'stale'});
        } else render();
    }

    function clear(key) {
        state.stale.delete(key);
        state.failures.delete(`/api/${key}`);
        if (state.phase === 'degraded' && !state.failures.size && !state.stale.size) {
            set('online');
        } else render();
    }

    async function recover() {
        if (recovering) return;
        recovering = true;
        const reason = state.reason;
        try {
            set('recovering', {reason});
            restartPending = false;
            const restartBtn = document.getElementById('restart-btn');
            if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
            // Defer invocation as well as awaiting: one synchronous renderer error
            // must not prevent the other surfaces from recovering.
            const refreshes = [
                ['chat', () => {
                    resetChatTransientState();
                    return selectedAgent && currentScope
                        ? _showChatFor(selectedAgent, currentScope) : null;
                }],
                ['sessions', () => refreshSessions()],
                ['orchestrators', () => loadOrchestrators()],
                ['models', () => loadModels()],
                ['files', () => refreshOpenFolders()],
                ['usage', () => fetchUsage()],
                ['quota', () => window.QuotaPanel?.fetch?.()],
            ];
            const results = await Promise.allSettled(
                refreshes.map(([, refresh]) => Promise.resolve().then(refresh)),
            );
            const errors = [];
            results.forEach((result, index) => {
                const key = `recovery/${refreshes[index][0]}`;
                if (result.status === 'rejected') {
                    state.failures.set(key, {error: result.reason, at: Date.now()});
                    errors.push(`${refreshes[index][0]}: ${String(result.reason)}`);
                } else state.failures.delete(key);
            });
            wasDown = false;
            if (state.failures.size || state.stale.size) {
                set('degraded', {
                    reason: 'partial_recovery',
                    path: state.failures.keys().next().value || '',
                    message: errors.length ? `Не удалось обновить: ${errors.join('; ')}` : '',
                });
                return;
            }
            const flash = reason === 'restart'
                ? 'Orchestra перезапустилась · данные обновлены'
                : 'Связь восстановлена · данные обновлены';
            set('online', {reason: '', path: '', flash});
            state.flashTimer = setTimeout(() => {
                state.flash = '';
                render();
            }, 5000);
        } finally {
            recovering = false;
        }
    }

    async function heartbeat() {
        try {
            const response = await fetch('/api/models', {
                cache: 'no-store', signal: AbortSignal.timeout(2000),
            });
            observe(response, '/api/models');
            if (response.headers.get('X-Orchestra-Restarting') === null
                && restartPending && Date.now() - restartPendingSince > RESTART_MAX_MS) {
                setRestarting(false);
            }
            const restartError = response.headers.get('X-Orchestra-Restart-Error');
            if (restartError) {
                let reason = restartError;
                try { reason = decodeURIComponent(restartError); } catch {}
                restartAttempt(`Рестарт не состоялся: ${reason}`, true);
                const restartBtn = document.getElementById('restart-btn');
                if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
            }
            if (response.status < 502) {
                _pollNoteSuccess('heartbeat');
                ok('/api/models');
                const build = response.headers.get('X-Orchestra-Build');
                if (build && pageBuild && build !== pageBuild) showBuildBanner(build);
            } else {
                _pollNoteFailure('heartbeat', {name: 'TypeError'});
                fail('/api/models', {name: 'TypeError', status: response.status});
            }
        } catch (error) {
            _pollNoteFailure('heartbeat', error);
            if (error.name !== 'AbortError') fail('/api/models', error);
        }
    }

    async function reconnectLoop() {
        while (reconnecting) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            if (!reconnecting) return;
            await heartbeat();
            if (state.phase === 'online' || state.phase === 'recovering') reconnecting = false;
        }
    }

    function init() {
        _pollRegister('heartbeat', heartbeat, 8000, false);
    }

    return {
        state, ownsErrors, set, observe, fail, ok, setRestarting, restartFromBody,
        restartAttempt, stale, clear, recover, heartbeat, init,
        resetForTest() {
            recovering = false;
            reconnecting = false;
            restartPending = false;
            wasDown = false;
            state.failures.clear();
            state.stale.clear();
        },
    };
})();
