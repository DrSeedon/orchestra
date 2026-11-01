# Task S1 — include the causal exception chain

Update only `src/error_text.py`. `err_text(error)` already returns the outer exception's text. Extend it so explicit `__cause__` messages are included in outer-to-inner order, including nested causes. Preserve the current result for an exception with no explicit cause. Do not include implicit `__context__` messages. The fixture is synthetic; no provider pricing, project history, or prior model output is part of the task.
