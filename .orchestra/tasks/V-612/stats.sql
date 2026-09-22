.headers on
.mode tabs
-- Deploy boundaries (UTC), from journalctl Uvicorn-restart timestamps matched to git commit times:
--   D1 = 2026-09-20T16:31:58Z: restart that first served f6d969c1 (V-602: descriptions + parallel list_agents)
--        and 88c25b2a (V-599: merge_worker synchronous wait)
--   D2 = 2026-09-21T04:43:07Z: restart that first served 4bd1a536 (V-603: expanded bg_create receipt)
-- "before" window matches V-600's own start bound (ts > '2026-09-13') and ends exactly at the relevant deploy.
-- "after" window runs from that deploy to now. Window lengths are reported alongside the numbers.
WITH names(name) AS (VALUES
 ('list_agents'),('merge_worker'),('worker_wip'),('bg_create'),('bg_list'),
 ('send_file'),('send_files'),('file_delivery_status')
),
bounds(name, d) AS (VALUES
 ('list_agents','2026-09-20T16:31:58'),
 ('merge_worker','2026-09-20T16:31:58'),
 ('worker_wip','2026-09-20T16:31:58'),
 ('bg_create','2026-09-21T04:43:07'),
 ('bg_list','2026-09-21T04:43:07'),
 ('send_file','2026-09-21T04:43:07'),
 ('send_files','2026-09-21T04:43:07'),
 ('file_delivery_status','2026-09-21T04:43:07')
),
calls AS (
 SELECT replace(l.tool_name,'mcp__orchestra__','') name, l.tool_use_id, l.ts,
        CASE WHEN l.ts < b.d THEN 'before' ELSE 'after' END period
 FROM logs l JOIN bounds b ON b.name = replace(l.tool_name,'mcp__orchestra__','')
 WHERE l.type='tool' AND l.ts > '2026-09-13' AND l.tool_name LIKE 'mcp__orchestra__%'
), results AS (
 SELECT tool_use_id, min(ts) ts FROM logs WHERE type='tool_result' AND ts > '2026-09-13' GROUP BY tool_use_id
), pairs AS (
 SELECT c.name,c.period,c.tool_use_id,(julianday(r.ts)-julianday(c.ts))*86400.0 delay
 FROM calls c JOIN results r USING(tool_use_id)
), ranked AS (
 SELECT name,period,delay,row_number() OVER(PARTITION BY name,period ORDER BY delay) rn,
        count(*) OVER(PARTITION BY name,period) n
 FROM pairs
), agg AS (
 SELECT name,period, count(*) paired,
        avg(CASE WHEN rn IN ((n+1)/2,(n+2)/2) THEN delay END) median_s,
        max(CASE WHEN rn=cast(ceil(n*0.95) AS INTEGER) THEN delay END) p95_s
 FROM ranked GROUP BY name,period
), ec AS (
 SELECT replace(te.tool_name,'mcp__orchestra__','') name,
        CASE WHEN te.ts < b.d THEN 'before' ELSE 'after' END period,
        count(*) failures
 FROM tool_errors te JOIN bounds b ON b.name = replace(te.tool_name,'mcp__orchestra__','')
 WHERE te.ts > '2026-09-13' AND te.tool_name LIKE 'mcp__orchestra__%'
 GROUP BY 1,2
), callcounts AS (
 SELECT name,period,count(*) n FROM calls GROUP BY 1,2
)
SELECT n.name, cc.period,
       cc.n calls,
       coalesce(a.median_s,'') median_s,
       coalesce(a.p95_s,'') p95_s,
       coalesce(ec.failures,0) failures,
       round(coalesce(ec.failures,0)*100.0/cc.n, 2) failures_per_100
FROM names n
JOIN callcounts cc ON cc.name=n.name
LEFT JOIN agg a ON a.name=n.name AND a.period=cc.period
LEFT JOIN ec ON ec.name=n.name AND ec.period=cc.period
ORDER BY n.name, cc.period;
