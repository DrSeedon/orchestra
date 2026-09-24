/* Metadata-only owner presence: one random token per browser tab. */
(function () {
    const TOKEN_KEY = 'orchestra.ownerActivityTabToken';
    const token = (() => {
        try {
            const old = sessionStorage.getItem(TOKEN_KEY);
            if (old) return old;
            const fresh = crypto.randomUUID();
            sessionStorage.setItem(TOKEN_KEY, fresh);
            return fresh;
        } catch (_) {
            return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        }
    })();
    let scope = '';
    let lastInputAt = Date.now();
    let pingTimer = null;
    let sequence = 0;
    let lastSentInputAt = Date.now();

    function activeState() {
        return !document.hidden && document.hasFocus()
            && Date.now() - lastInputAt <= 5 * 60 * 1000;
    }

    function iso(ms) { return new Date(ms).toISOString(); }

    function send(eventType, keepalive = false) {
        if (!scope) return;
        const now = Date.now();
        fetch('/api/owner-activity/events', {
            method: 'POST',
            credentials: 'same-origin',
            keepalive,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                event_id: `${token}:${++sequence}:${now}`,
                tab_token: token,
                event_type: eventType,
                scope,
                ts: iso(now),
                visible: !document.hidden,
                focused: document.hasFocus(),
                last_input_at: iso(lastInputAt),
            }),
        }).catch(() => {});
    }

    function setScope(next) {
        next = String(next || '').replace(/\/+$/, '');
        if (next === scope) return;
        scope = next;
        send('scope');
    }

    function noteInput() {
        const now = Date.now();
        const previousInputAt = lastInputAt;
        lastInputAt = now;
        if (scope && ownerActivityShouldSendInput(now, previousInputAt, lastSentInputAt)) {
            lastSentInputAt = now;
            send('input');
        }
    }

    function init() {
        for (const type of ['mousemove', 'keydown', 'scroll', 'touchstart', 'pointerdown']) {
            document.addEventListener(type, noteInput, {passive: true, capture: true});
        }
        window.addEventListener('focus', () => send('focus'));
        window.addEventListener('blur', () => send('blur'));
        document.addEventListener('visibilitychange', () => send('visibility'));
        pingTimer = setInterval(() => { if (activeState()) send('ping'); }, 60000);
        window.addEventListener('beforeunload', () => send('blur', true));
    }

    window.OrchestraOwnerActivity = {init, setScope};
})();
