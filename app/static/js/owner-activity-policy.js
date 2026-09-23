/* Pure timing policy shared by the browser and the node-level regression test. */
(function (root) {
    const IDLE_MS = 5 * 60 * 1000;
    const MIN_EVENT_GAP_MS = 60 * 1000;

    function shouldSendInputEvent(now, previousInputAt, lastSentAt) {
        if (!Number.isFinite(now) || !Number.isFinite(previousInputAt)) return false;
        const returnedFromIdle = now - previousInputAt > IDLE_MS;
        const periodic = lastSentAt == null
            || (Number.isFinite(lastSentAt) && now - lastSentAt >= MIN_EVENT_GAP_MS);
        return returnedFromIdle || periodic;
    }

    root.ownerActivityShouldSendInput = shouldSendInputEvent;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {shouldSendInputEvent};
    }
})(typeof window === 'undefined' ? globalThis : window);
