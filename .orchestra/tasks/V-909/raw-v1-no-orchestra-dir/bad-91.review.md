## Summary

Reviewed the complete diff between the pinned commits. The enterprise model-discovery path has a blocking authentication mismatch when it uses the configured default upstream URL.

## Findings

### Blocking

- [app/models.py](/home/kesha/v909-work/v909-bad-91-wm8szv5b/app/models.py:119): With `UPSTREAM_API` unset, model discovery calls `https://api.anthropic.com/v1/models` and sends `ANTHROPIC_API_KEY` as a Bearer token. Anthropic’s API expects its API key in `x-api-key` and requires an `anthropic-version` header. The request therefore fails for a standard Anthropic API key; in enterprise mode the exception handler clears the model and backend dictionaries, leaving the service with no available models.

## Findings (suggestion/question)

None.

## Verdict

NEEDS WORK — fix the authentication headers for the default Anthropic endpoint, or make the supported upstream contract explicit and ensure the default configuration matches it.