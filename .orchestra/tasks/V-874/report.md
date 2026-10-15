# V-874 — compact voice input and automatic send

The dashboard voice status is now a short row above the input, using the dashboard color and radius tokens. It reports upload, transcription, and sending progress; transcription and send failures retain the IndexedDB audio and expose retry/delete actions. Browser contexts test and screenshot the row at desktop and phone widths.

After transcription, the client combines the draft for the agent captured at recording start with `🎙 Voice transcription:` and posts exactly one `/api/sessions/{agent}/send` request. A successful response clears the sent draft and then removes the saved recording. A failed send keeps the exact message for retry without retranscribing; a recovered recording uses the same auto-send path. The same behavior works when the user has switched to another agent while transcription runs.

## Verification

`uv run --frozen pytest --rootdir=. -n 2 --dist=loadscope -v -rf --timeout=30 -m browser tests/test_frontend.py -k dashboard_voice` ran in Chromium with the fake microphone: **7 passed in 42.73s**. The tests assert one send with the typed text and transcript to the selected agent, one send to the recording agent after switching, automatic send after reload recovery, transcription retry/delete availability, IndexedDB failure behavior, and compact status placement on desktop and phone. Screenshots: `screenshots/desktop-sending-chip.png` and `screenshots/phone-sending-chip.png`.

The full CI browser command `uv run --frozen pytest --rootdir=. -n 2 --dist=loadscope -v -rf --timeout=30 -m 'browser' tests/` completed: **201 passed, 7 skipped, 208 collected, 310.08s**, exit status 0.

The dashboard template now declares a mobile viewport; the running Jinja environment reports `auto_reload=True`, so the template update is picked up on the next page request. No Python source changed and no service restart is needed.
