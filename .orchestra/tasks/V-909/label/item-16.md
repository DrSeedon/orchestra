# item-16

Commit under review (in /home/kesha/orchestra, read-only): `a755646c6afdb940f7a1d2e1f71d4768c5ac5d35`
Subject / date:
#91: client info page + proxy-only models + connection indicator
2026-06-13

The diff reviewed is `git -C /home/kesha/orchestra show a755646c6afdb940f7a1d2e1f71d4768c5ac5d35 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `7483029` to `c001fae`. No files were changed.

## Findings

### Blocking

- [app/models.py](app/models.py:129): The model fetch always sends `ANTHROPIC_API_KEY` as `Authorization: Bearer` and defaults to `https://api.anthropic.com`. Anthropic’s API examples use `x-api-key` for API key authentication ([Anthropic docs](https://docs.anthropic.com/en/api/claude-on-amazon-bedrock)). With the default URL and a normal Anthropic key, the fetch can fail; in auth-enabled mode that failure clears all models, leaving users unable to select one.

### Suggestion

- [app/models.py](app/models.py:102): `_infer_backend()` recognizes Codex models only when the ID starts with `gpt-`. For namespaced IDs such as `openai/gpt-5.5`—a format this code otherwise explicitly handles—the model is assigned to the Claude backend. Selecting it will therefore route it through the wrong runtime.

## Verdict

NEEDS WORK
