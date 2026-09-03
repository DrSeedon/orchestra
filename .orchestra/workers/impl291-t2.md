# impl291-t2

- The #291 controller schema is initialized by `app.db._create_quota_controller_schema`; custom SQLite test databases should use `app.db.quota_controller_connection()` so they receive the same schema and WAL/busy-timeout settings.
