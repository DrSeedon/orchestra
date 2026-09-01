# fix-merge-finalize

- Исторический state snapshot якорю к timestamp наблюдаемого side effect/error из `logs.ts`, а не к `operation.created_at`: операция создаётся до post-commit финализации, и более ранний снимок не доказывает состояние в момент исключения.
- Компенсацию split-write проверяю матрицей: decoy-сосед, bound/revised/committed/reserved target, post-write ambiguous success, unreadable/malformed probe и падение secondary debt writer; один пустой store доказывает только happy cleanup и пропускает data loss.
