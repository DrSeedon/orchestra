function check(value, message) { if (!value) throw new Error(message); }
function same(actual, expected) {
    check(JSON.stringify(actual) === JSON.stringify(expected),
        `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}
function entry(id, state = 'after_turn') {
    return {id, body: `synthetic message ${id}`, state,
        claimed: state === 'handing_off', cancellable: state === 'after_turn'};
}
function rows() { return [...$('#queued-messages').querySelectorAll('[data-queue-state]')]; }
async function tick() { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); }
async function render(messages) {
    const pending = refreshQueuedMessages();
    requests.shift().resolve({messages});
    await pending;
}
function switchView(name, scope = currentScope) {
    // Mirror app.js: saveDraft, reset transient state, select, restoreDraft.
    if (selectedAgent) drafts[selectedAgent] = {text: $('#chat-input').value, images: [...pastedImages]};
    resetChatTransientState();
    selectedAgent = name;
    currentScope = scope;
    $('#chat-input').value = drafts[name]?.text || '';
    clearPastePreview();
}
async function runQueueScenario(scenario) {
    if (scenario === 'states_order_content') {
        const data = [entry(4), entry(2, 'handing_off'), entry(8, 'current_turn'), entry(9, 'current_turn_unconfirmed')];
        data[0].body = '<img src=x onerror="throw 1">\nsynthetic long '.repeat(20);
        await render(data);
        same(rows().map(r => r.dataset.queueState), data.map(r => r.state));
        same(rows().map(r => r.firstChild.firstChild.textContent), data.map(r => r.body));
        same(rows().map(r => r.querySelectorAll('button').length), [1, 0, 0, 0]);
        check(!$('#queued-messages').querySelector('img'), 'body was interpreted as HTML');
        check(rows().every(r => r.firstChild.children[1].textContent.length > 0), 'missing state description');
        await render([]);
        same($('#queued-messages').children.length, 0);
    } else if (scenario === 'out_of_order') {
        const old = refreshQueuedMessages();
        const recent = refreshQueuedMessages();
        requests[1].resolve({messages: []}); await recent;
        requests[0].resolve({messages: [entry(1)]}); await old;
        same(rows().length, 0);
    } else if (scenario === 'selection_scope_aba') {
        await render([entry(1)]);
        const old = refreshQueuedMessages();
        const stale = requests.shift();
        switchView('other-agent');
        const other = refreshQueuedMessages();
        same(rows().length, 0);
        requests.shift().resolve({messages: [entry(2)]}); await other;
        switchView('synthetic-agent', '/other-scope');
        await render([entry(3)]);
        switchView('synthetic-agent', '/synthetic-scope');
        await render([]);
        stale.resolve({messages: [entry(1)]}); await old;
        same(rows().length, 0);
        selectedAgent = null;
        await refreshQueuedMessages();
        same($('#queued-messages').children.length, 0);
    } else if (scenario === 'overlapping_slow_polls') {
        const first = refreshQueuedMessages();
        const second = refreshQueuedMessages();
        requests[0].resolve({messages: [entry(1)]}); await first;
        same(rows().length, 1); // a newer pending request must not starve updates
        requests[1].resolve({messages: []}); await second;
        same(rows().length, 0);
    } else if (scenario === 'stale_404') {
        const old = refreshQueuedMessages();
        const stale = requests.shift();
        switchView('other-agent');
        await render([entry(2)]);
        stale.reject(new Error('404 missing route')); await old;
        check(!_queuedUnsupported, 'old request disabled all polling');
        same(rows().length, 1);
    } else if (scenario === 'cancel_success_stale_get') {
        await render([entry(1), entry(2)]);
        const old = refreshQueuedMessages();
        const stale = requests.shift();
        rows()[0].querySelector('button').click();
        const deletion = requests.shift();
        same(deletion.options.method, 'DELETE');
        check(deletion.url.includes('/synthetic-agent/queued-messages/1?'), 'wrong cancel target');
        deletion.resolve({cancelled: true}); await tick();
        same(rows().length, 1);
        requests.shift().resolve({messages: [entry(2)]}); await tick();
        stale.resolve({messages: [entry(1), entry(2)]}); await old;
        same(rows().map(r => r.firstChild.firstChild.textContent), ['synthetic message 2']);
    } else if (scenario === 'cancel_success_poll_refresh_failure') {
        await render([entry(1), entry(2)]);
        rows()[0].querySelector('button').click();
        const deletion = requests.shift();
        await render([entry(1), entry(2)]);
        deletion.resolve({cancelled: true}); await tick();
        same(rows().map(r => r.dataset.queueId), ['2']);
        requests.shift().reject(new Error('synthetic offline')); await tick();
        same(rows().map(r => r.dataset.queueId), ['2']);
    } else if (scenario === 'cancel_loses_claim') {
        await render([entry(1)]);
        rows()[0].querySelector('button').click();
        requests.shift().resolve({cancelled: false}); await tick();
        requests.shift().resolve({messages: [entry(1, 'handing_off')]}); await tick();
        same(rows()[0].dataset.queueState, 'handing_off');
        same(rows()[0].querySelectorAll('button').length, 0);
        check([...$('#queued-messages').querySelectorAll('[role="status"]')].some(el => el.textContent), 'cancel failure was silent');
    } else if (scenario === 'cancel_error_and_poll') {
        await render([entry(1)]);
        rows()[0].querySelector('button').click();
        const deletion = requests.shift();
        await render([entry(1)]);
        check(rows()[0].querySelector('button').disabled, 'poll re-enabled in-flight cancellation');
        deletion.reject(new Error('synthetic offline')); await tick();
        check(!rows()[0].querySelector('button').disabled, 'cancel cannot be retried');
        check([...$('#queued-messages').querySelectorAll('[role="status"]')].some(el => el.textContent), 'error notice detached after poll');
        same(rows().length, 1);
    } else if (scenario === 'cancel_after_switch') {
        await render([entry(1)]);
        rows()[0].querySelector('button').click();
        const deletion = requests.shift();
        switchView('other-agent');
        await render([entry(2)]);
        deletion.resolve({cancelled: false}); await tick();
        same(rows().map(r => r.firstChild.firstChild.textContent), ['synthetic message 2']);
        same(requests.length, 0);
        check(![...$('#queued-messages').querySelectorAll('[role="status"]')].some(el => el.textContent), 'wrong view received cancellation notice');
    } else if (scenario === 'refresh_failure_recovery') {
        await render([entry(1)]);
        const pending = refreshQueuedMessages();
        requests.shift().reject(new Error('synthetic offline')); await pending;
        same(rows().length, 1);
        check($('#queued-messages').querySelector('[data-queue-error]'), 'stale data was not labelled');
        await render([]);
        same($('#queued-messages').children.length, 0);
    } else if (scenario === 'queued_send_is_not_delivered') {
        $('#chat-input').value = 'synthetic after-turn';
        const pending = sendChat({afterTurn: true});
        same($('#chat').children.length, 0);
        check(!localMessages.has('synthetic after-turn'), 'pending message will suppress delivery echo');
        const send = requests.shift();
        check(JSON.parse(send.options.body).after_turn === true, 'lost after-turn mode');
        send.resolve({queued: true}); await tick();
        requests.shift().resolve({messages: [entry(1)]}); await pending;
        same($('#chat').children.length, 0);
        same($('#chat-input').value, '');
        same(rows().length, 1);
        same(requests.length, 0); // no extra immediate send
    } else if (scenario === 'after_turn_followup_draft') {
        $('#chat-input').value = 'synthetic queued';
        const pending = sendChat({afterTurn: true});
        const send = requests.shift();
        $('#chat-input').value += '\n\nsynthetic followup';
        send.resolve({queued: true}); await tick();
        requests.shift().resolve({messages: [entry(1)]}); await pending;
        same($('#chat-input').value, 'synthetic followup');
    } else if (scenario === 'after_turn_failure_draft') {
        addChatEntry = (type, message) => errors.push({type, message});
        $('#chat-input').value = 'synthetic retained';
        const pending = sendChat({afterTurn: true});
        requests.shift().reject(new Error('synthetic failed')); await pending;
        same($('#chat-input').value, 'synthetic retained');
        same(errors.length, 1);
        same($('#chat').children.length, 0);
    } else if (scenario === 'send_response_after_switch') {
        $('#chat-input').value = 'synthetic after-turn';
        const pending = sendChat({afterTurn: true});
        const send = requests.shift();
        switchView('other-agent');
        $('#chat-input').value = 'synthetic other draft';
        $('#send-after-turn-btn').disabled = true; // new target can be archived
        const sentinel = document.createElement('div');
        sentinel.textContent = 'synthetic other bubble';
        $('#chat').appendChild(sentinel);
        send.resolve({queued: true}); await pending;
        same($('#chat-input').value, 'synthetic other draft');
        same(drafts['synthetic-agent'].text, ''); // accepted old input must not be offered again
        same($('#chat').children.length, 1);
        check($('#send-after-turn-btn').disabled, 'late send enabled another target composer');
        same(requests.length, 0);
    } else if (scenario === 'accepted_saved_draft_aba') {
        $('#chat-input').value = 'synthetic original';
        const pending = sendChat({afterTurn: true});
        const send = requests.shift();
        switchView('other-agent');
        switchView('synthetic-agent');
        await render([]);
        $('#chat-input').value += '\n\nsynthetic later';
        send.resolve({queued: true}); await tick();
        requests.shift().resolve({messages: [entry(1)]}); await pending;
        same($('#chat-input').value, 'synthetic later');
        same(drafts['synthetic-agent'].text, '');
    } else if (scenario === 'failed_saved_draft') {
        $('#chat-input').value = 'synthetic recoverable';
        const pending = sendChat({afterTurn: true});
        const send = requests.shift();
        switchView('other-agent');
        $('#chat-input').value = 'synthetic other draft';
        send.reject(new Error('synthetic failed')); await pending;
        same($('#chat-input').value, 'synthetic other draft');
        same(drafts['synthetic-agent'].text, 'synthetic recoverable');
        switchView('synthetic-agent');
        same($('#chat-input').value, 'synthetic recoverable');
    } else if (scenario === 'upload_switch_and_double_click') {
        let finishUpload;
        _pendingUploads.add(new Promise(resolve => {finishUpload = resolve;}));
        $('#chat-input').value = 'synthetic attachment';
        const pending = sendChat({afterTurn: true});
        await sendChat({afterTurn: true});
        switchView('other-agent');
        $('#chat-input').value = 'synthetic other draft';
        finishUpload(); await pending;
        same(requests.length, 0);
        same($('#chat-input').value, 'synthetic other draft');
    } else if (scenario === 'old_backend') {
        await render([{id: 1, body: 'synthetic old server', claimed: false}]);
        same(rows().length, 1);
        same(rows()[0].dataset.queueState, 'pending');
        same(rows()[0].querySelectorAll('button').length, 0);
    } else throw new Error(`unknown scenario ${scenario}`);
    return scenario;
}
