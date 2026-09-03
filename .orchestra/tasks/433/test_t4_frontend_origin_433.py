"""Frozen RED browser oracle for #433 T4: only explicit user origin renders right."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _add_chat_entry_source() -> str:
    source = (ROOT / "app/static/js/chat.js").read_text()
    marker = "function addChatEntry"
    assert marker in source, "#433 T4 oracle broken: addChatEntry is absent"
    return marker + source.split(marker, 1)[1]


def test_t4_missing_invalid_and_nonuser_origins_render_left_with_labels(browser):
    page = browser.new_page(viewport={"width": 900, "height": 700})
    page.set_content('<div id="chat"></div>')
    page.add_style_tag(
        content=":root{--accent:#6366f1}.ml-16{margin-left:4rem}"
    )
    page.add_style_tag(path=str(ROOT / "app/static/css/style.css"))
    page.add_script_tag(
        content="""
        const $ = selector => document.querySelector(selector);
        const DOMPurify = {sanitize: value => value};
        const marked = {parse: value => value};
        const agentColors = {};
        let selectedAgent = 'target-agent';
        let HIDE_THINKING = false;
        let streamBubble = null;
        let scrollAfterLoad = true;
        const _isSilentTurnMarker = () => false;
        const removeWaitingIndicator = () => {};
        const appendSubagentLog = () => {};
        const _tagChatTimelineNode = () => {};
        const _stampChatLogNode = () => {};
        const _attachTruncNotice = () => {};
        const _chatAtBottom = () => false;
        const _markChatHasNewBelow = () => {};
        const _renderCompactToolEntry = () => false;
        const renderSystemChatEntry = () => null;
        const _renderStatusEntry = () => false;
        const _renderSubagentLifecycleEntry = () => false;
        const _senderColor = () => '#22c55e';
        const renderImages = () => {};
        const addCopyBtn = () => {};
        const addTimestamp = () => {};
        const _trimChatNodes = () => {};
        const _adoptOrphanResults = () => {};
        """ + _add_chat_entry_source()
    )

    result = page.evaluate(
        """() => {
            const cases = [
                ['user', {origin:'user', origin_detail:{senders:['user']}}],
                ['agent', {origin:'agent', origin_detail:{senders:['a','b']}}],
                ['background', {origin:'background_task', origin_detail:{senders:['bg-1'], ref:'bg-1'}}],
                ['platform', {origin:'platform', origin_detail:{senders:['Orchestra']}}],
                ['system', {origin:'system', origin_detail:{senders:['system'], subtype:'retry'}}],
                ['unknown', {origin:'unknown', origin_detail:{senders:['unknown']}}],
                ['missing', {}],
                ['invalid', {origin:'bogus', origin_detail:{senders:[]}}],
                ['user-missing-detail', {origin:'user'}],
                ['user-string-detail', {origin:'user', origin_detail:'not-an-object'}],
                ['user-empty-senders', {origin:'user', origin_detail:{senders:[]}}],
                ['user-extra-detail-key', {origin:'user', origin_detail:{senders:['user'], unexpected:true}}],
                ['user-number-subtype', {origin:'user', origin_detail:{senders:['user'], subtype:7}}],
                ['user-blank-subtype', {origin:'user', origin_detail:{senders:['user'], subtype:'   '}}],
                ['user-number-ref', {origin:'user', origin_detail:{senders:['user'], ref:7}}],
            ];
            for (const [_label, payload] of cases) {
                addChatEntry('user_message', 'NEUTRAL-BODY', null, null, payload);
            }
            return [...document.querySelector('#chat').children].map(node => {
                const style = getComputedStyle(node);
                return {
                    classes: [...node.classList],
                    text: node.textContent,
                    backgroundColor: style.backgroundColor,
                    borderLeftColor: style.borderLeftColor,
                    marginLeft: style.marginLeft,
                };
            });
        }"""
    )
    page.close()

    assert len(result) == 15, "#433 T4 oracle broken: renderer dropped a control row"
    explicit_user = result[0]
    assert "chat-user" in explicit_user["classes"]
    for label, expected_label, row in zip(
        (
            "agent", "background", "platform", "system", "unknown", "missing", "invalid",
            "user-missing-detail", "user-string-detail", "user-empty-senders",
            "user-extra-detail-key", "user-number-subtype", "user-blank-subtype",
            "user-number-ref",
        ),
        (
            "a", "bg-1", "orchestra", "system", "unknown", "unknown", "unknown",
            "unknown", "unknown", "unknown",
            "unknown", "unknown", "unknown", "unknown",
        ),
        result[1:],
    ):
        assert "chat-user" not in row["classes"], (
            f"#433 T4 unsafe fallback: {label} origin rendered as the user"
        )
        assert "chat-bot" in row["classes"], (
            f"#433 T4 missing left-bubble class for {label} origin"
        )
        assert row["backgroundColor"] != explicit_user["backgroundColor"], (
            f"#433 T4 computed style did not separate {label} from the user"
        )
        assert expected_label in row["text"].lower(), (
            f"#433 T4 missing visible provenance label for {label}"
        )
