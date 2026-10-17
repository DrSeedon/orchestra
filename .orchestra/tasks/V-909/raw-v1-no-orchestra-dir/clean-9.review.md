## Summary

Reviewed the complete diff from `2c98c99a5299d00ca3e4b22b7c45c724f73dc67a` to `cc03919915cb50e7f442dd447fd0f103ee8310d7`. The cache policy is coherent for the dashboard and normal login page: versioned static responses get long-lived caching, and unversioned static responses get revalidated.

## Findings (blocking/suggestion/question)

### Suggestion

- **Failed login responses omit the HTML cache policy.** In `login_submit`, invalid credentials return `login.html` without `Cache-Control: no-cache`, unlike `login_page`. A cached page could therefore keep old static asset URLs after a deployment. Add the same header to that response. [app/routes/system.py](/home/kesha/v909-work/v909-clean-9-2ovojb4v/app/routes/system.py:87)

- **Existing frontend assertions still expect unversioned static URLs.** For example, `tests/test_usage_analytics_frontend.py` asserts exact `/static/js/...` script tags, which the template changes replace with `?v=...`. Update these expectations so the tests continue to check script presence and ordering. [tests/test_usage_analytics_frontend.py](/home/kesha/v909-work/v909-clean-9-2ovojb4v/tests/test_usage_analytics_frontend.py:281)

## Verdict

NEEDS WORK — add the missing cache header to failed-login HTML and update assertions that depend on the old asset URLs.