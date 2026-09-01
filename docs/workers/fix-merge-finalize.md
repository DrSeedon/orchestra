# fix-merge-finalize

- Исторический state snapshot якорю к timestamp наблюдаемого side effect/error из `logs.ts`, а не к `operation.created_at`: операция создаётся до post-commit финализации, и более ранний снимок не доказывает состояние в момент исключения.
