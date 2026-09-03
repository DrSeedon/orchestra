# fix-tg-ingress

- aiogram 3.28 keeps unknown top-level Telegram message fields in `Message.model_extra` (`extra="allow"`) even when `Message.content_type` returns `UNKNOWN`; aiogram 3.30 may expose the same field as a typed model. A fallback can support both by serializing either the extra value or `model_dump_json()`.
- aiogram 3.28 has no `Message`/`ContentType` service-message predicate or installed-source grouping; service-event suppression must use verified enum members and must happen after logging but before session resolution.
