# Worker memory

- Dashboard voice delivery can reuse `app.transcription.transcribe_audio`; durable accepted uploads need a DB queue and startup resume because request-scoped tasks do not survive process restart.
