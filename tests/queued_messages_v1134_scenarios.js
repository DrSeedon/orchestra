function check(value, message) { if (!value) throw new Error(message); }
function same(actual, expected) {
    check(JSON.stringify(actual) === JSON.stringify(expected),
        `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}
async function tick() { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); }
function switchView(name, scope = currentScope) {
    // Mirrors app.js selection: production saveDraft/restoreDraft are loaded by the harness.
    saveDraft();
    resetChatTransientState();
    selectedAgent = name;
    currentScope = scope;
    restoreDraft();
}
async function runQueueScenario(scenario) {
    if (scenario === 'queued_send_is_not_delivered') {
        $('#chat-input').value = 'synthetic after-turn';
        const pending = sendChat({afterTurn: true});
        same($('#chat').children.length, 0);
        check(!localMessages.has('synthetic after-turn'), 'pending message will suppress delivery echo');
        const send = requests.shift();
        check(JSON.parse(send.options.body).after_turn === true, 'lost after-turn mode');
        send.resolve({queued: true}); await pending;
        same($('#chat').children.length, 0);
        same($('#chat-input').value, '');
        same(requests.length, 0); // no extra immediate send and no queue polling
    } else if (scenario === 'after_turn_followup_draft') {
        $('#chat-input').value = 'synthetic queued';
        const pending = sendChat({afterTurn: true});
        const send = requests.shift();
        $('#chat-input').value += '\n\nsynthetic followup';
        send.resolve({queued: true}); await pending;
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
        $('#chat-input').value += '\n\nsynthetic later';
        send.resolve({queued: true}); await pending;
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
    } else throw new Error(`unknown scenario ${scenario}`);
    return scenario;
}
