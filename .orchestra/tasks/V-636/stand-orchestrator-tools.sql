-- V-636: оркестратору стенда не предлагаются инструменты, которыми GigaChat промахивался:
-- task_update вместо task_list, опрос воркера через get_worker_logs, поштучное чтение задач
-- через task_get, англоязычный ревьюер review вместо ответа по task_list, send_message самому себе
-- вместо работы (воркер отчитывается автоматически, демо писать воркеру не нужно).
update sessions set disabled_tools = (
  select json_group_array(value) from (
    select value from json_each(sessions.disabled_tools)
    union select value from json_each('["task_update","get_worker_logs","kill_worker","task_get","review","send_message"]')
  )
) where name = 'orchestrator';
