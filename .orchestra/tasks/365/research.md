# #365: dashboard voice delivery

- The dashboard previously waited for `/api/transcribe` before putting text into the input; it never sent a voice recording itself.
- The existing `app.transcription.transcribe_audio` is the single Deepgram implementation and remains the only transcription path.
- Accepted recordings are stored under `data/uploads/` and tracked in `dashboard_voice_transcriptions` before the HTTP response. The background task sends the resulting text as one ordinary `user_message`.
- `QUEUED` and `RUNNING` rows are resumed during application startup. Failed rows remain `FAILED` with their audio file intact; the existing `report_undelivered` path routes the failure and retained path to the scope orchestrator.
- `logs` remains append-only; no log update or replacement event was introduced.
