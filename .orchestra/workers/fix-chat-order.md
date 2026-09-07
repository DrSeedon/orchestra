# fix-chat-order

- Frontend tests using `_open_chat_snapshot_page` should wait for its asynchronous snapshot to settle, then call `resetChatTransientState()` and clear `#chat` before asserting a synthetic DOM sequence.
