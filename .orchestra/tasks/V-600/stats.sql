.headers on
.mode tabs
WITH names(name) AS (VALUES
('spawn_worker'),('delivery_status'),('retry_initial_delivery'),('acquire_test_lock'),('release_test_lock'),('test_lock_status'),('send_message'),('message_delivery_status'),('open_fan'),('list_agents'),('list_orchestrators'),('get_worker_logs'),('compact_worker'),('kill_worker'),('stop_worker'),('rename_worker'),('file_delivery_status'),('send_file'),('send_files'),('publish_artifact'),('send_chart'),('notify_user'),('update_progress'),('change_worker_model'),('merge_worker'),('resolve_merge_operation'),('switch_worker_branch'),('check_conflict'),('worker_wip'),('report_bug'),('update_worker_description'),('set_worker_owned_dirs'),('update_worker_prompt'),('get_worker_info'),('project_goal'),('project_wait'),('task_create'),('task_create_status'),('task_update'),('task_list'),('task_get'),('bg_create'),('bg_list'),('bg_cancel'),('search_memory')),
calls AS (
 SELECT replace(tool_name,'mcp__orchestra__','') name, tool_use_id, ts
 FROM logs WHERE type='tool' AND ts > '2026-09-13' AND tool_name LIKE 'mcp__orchestra__%'
), results AS (
 SELECT tool_use_id, min(ts) ts FROM logs WHERE type='tool_result' AND ts > '2026-09-13' GROUP BY tool_use_id
), pairs AS (
 SELECT c.name,c.tool_use_id,(julianday(r.ts)-julianday(c.ts))*86400.0 delay
 FROM calls c JOIN results r USING(tool_use_id)
), ranked AS (
 SELECT name,delay,row_number() OVER(PARTITION BY name ORDER BY delay) rn,count(*) OVER(PARTITION BY name) n
 FROM pairs
), agg AS (
 SELECT name, count(*) paired,
        avg(CASE WHEN rn IN ((n+1)/2,(n+2)/2) THEN delay END) median_s,
        max(CASE WHEN rn=cast(ceil(n*0.95) AS INTEGER) THEN delay END) p95_s,
        sum(delay <= 10.0) within_10s
 FROM ranked GROUP BY name
), ec AS (
 SELECT replace(tool_name,'mcp__orchestra__','') name,count(*) failures
 FROM tool_errors WHERE ts > '2026-09-13' AND tool_name LIKE 'mcp__orchestra__%' GROUP BY 1
)
SELECT n.name,
       (SELECT count(*) FROM calls c WHERE c.name=n.name) calls,
       coalesce(a.median_s,'') median_s,
       coalesce(a.p95_s,'') p95_s,
       coalesce((SELECT count(*) FROM calls c WHERE c.name=n.name)-(a.paired), (SELECT count(*) FROM calls c WHERE c.name=n.name)) no_response,
       coalesce(a.within_10s,'') within_10s,
       coalesce(ec.failures,0) failures
FROM names n LEFT JOIN agg a USING(name) LEFT JOIN ec USING(name)
ORDER BY n.name;
