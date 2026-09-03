-- Reproduce the 2026-07-18 read-only latency microbench from Orchestra logs.
-- Run:
-- sqlite3 -header -column /mnt/data/Projects/Python/orchestra/data/orchestra.db \
--   < docs/tasks/spark-comparison/microbench.sql
--
-- first_s: user_message -> first visible text event, including stale text from an
-- already in-flight turn. This deliberately exposes the contaminated Sol A1 run.
-- total_s: user_message -> first subsequent "turn ended" before the next trial.
-- tools: tool calls in the same interval.

WITH bench AS (
    SELECT
        s.id AS session_id,
        s.name,
        s.model,
        s.effort,
        l.id AS user_id,
        l.ts AS user_ts,
        CASE
            WHEN l.content LIKE '%A1%' THEN 'A1'
            WHEN l.content LIKE '%A2%' THEN 'A2'
            WHEN l.content LIKE '%A3%' THEN 'A3'
        END AS trial
    FROM logs AS l
    JOIN sessions AS s ON s.id = l.session_id
    WHERE s.name IN ('spark-pilot', 'spark-bench', 'spark-official')
      AND l.type = 'user_message'
      AND l.content LIKE '%Контрольный микробенч A%'
),
bounds AS (
    SELECT
        bench.*,
        COALESCE(
            (
                SELECT MIN(next_log.id)
                FROM logs AS next_log
                WHERE next_log.session_id = bench.session_id
                  AND next_log.type = 'user_message'
                  AND next_log.id > bench.user_id
                  AND next_log.content LIKE '%Контрольный микробенч A%'
            ),
            9223372036854775807
        ) AS next_user_id
    FROM bench
),
events AS (
    SELECT
        bounds.*,
        (
            SELECT MIN(first_log.id)
            FROM logs AS first_log
            WHERE first_log.session_id = bounds.session_id
              AND first_log.type = 'text'
              AND first_log.id > bounds.user_id
              AND first_log.id < bounds.next_user_id
        ) AS first_id,
        (
            SELECT MIN(end_log.id)
            FROM logs AS end_log
            WHERE end_log.session_id = bounds.session_id
              AND end_log.type = 'status'
              AND end_log.content LIKE 'turn ended%'
              AND end_log.id > bounds.user_id
              AND end_log.id < bounds.next_user_id
        ) AS end_id
    FROM bounds
)
SELECT
    events.name,
    events.model,
    events.effort,
    events.trial,
    events.user_id,
    events.first_id,
    events.end_id,
    ROUND((julianday(first_log.ts) - julianday(events.user_ts)) * 86400, 3)
        AS first_s,
    ROUND((julianday(end_log.ts) - julianday(events.user_ts)) * 86400, 3)
        AS total_s,
    (
        SELECT COUNT(*)
        FROM logs AS tool_log
        WHERE tool_log.session_id = events.session_id
          AND tool_log.type = 'tool'
          AND tool_log.id > events.user_id
          AND tool_log.id <= events.end_id
    ) AS tools,
    substr(replace(first_log.content, char(10), ' '), 1, 70)
        AS first_content
FROM events
JOIN logs AS first_log ON first_log.id = events.first_id
JOIN logs AS end_log ON end_log.id = events.end_id
ORDER BY events.name, events.trial;
