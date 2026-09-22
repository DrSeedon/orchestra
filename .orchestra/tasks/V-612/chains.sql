.headers on
.mode tabs
WITH ordered AS (
 SELECT session_id, ts,
        replace(tool_name,'mcp__orchestra__','') name,
        LAG(replace(tool_name,'mcp__orchestra__','')) OVER (PARTITION BY session_id ORDER BY ts, id) prev,
        LAG(ts) OVER (PARTITION BY session_id ORDER BY ts, id) prev_ts
 FROM logs
 WHERE type='tool' AND ts > '2026-09-13' AND tool_name LIKE 'mcp__orchestra__%'
),
pairs AS (
 SELECT prev, name, ts FROM ordered WHERE prev IS NOT NULL
),
target(prev,name,bound) AS (VALUES
 ('merge_worker','merge_worker','2026-09-20T16:31:58'),
 ('merge_worker','worker_wip','2026-09-20T16:31:58'),
 ('bg_create','bg_list','2026-09-21T04:43:07'),
 ('send_file','file_delivery_status','2026-09-21T04:43:07')
)
SELECT t.prev || ' -> ' || t.name chain,
       CASE WHEN p.ts < t.bound THEN 'before' ELSE 'after' END period,
       count(*) n
FROM target t
JOIN pairs p ON p.prev=t.prev AND p.name=t.name
GROUP BY 1,2
ORDER BY 1,2;
