# T03 — explicit classifier signal with a legacy fallback

`local_bash` events must be hidden from the public subagent list. New events have an explicit `task_type`; legacy events may lack it and use a `bash-` id fallback. The incident was a test where every explicit-type fixture also had a `bash-` id, so breaking the primary signal stayed green.

Write the smallest tests that distinguish the explicit signal from the fallback without asserting implementation order. A future opaque id format is valid.

