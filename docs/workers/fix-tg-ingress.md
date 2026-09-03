# fix-tg-ingress

- aiogram 3.28 keeps unknown top-level Telegram message fields in `Message.model_extra` (`extra="allow"`) even when `Message.content_type` returns `UNKNOWN`; aiogram 3.30 may expose the same field as a typed model. A fallback can support both by serializing either the extra value or `model_dump_json()`.
