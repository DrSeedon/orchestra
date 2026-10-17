## Summary

Reviewed the complete diff from `6646d263f19db55031b52d9d71b58085228472eb` to `340c6b11e33ccc1f43e0fd7870db1868a79eaa30`.

## Findings

### Suggestion

[app/static/js/app.js](/home/kesha/v918-work/v918-bad-cand-02.r0-x56w_zcd/app/static/js/app.js:4912): In `showTaskDetail`, the price and debt branches use single-quoted strings containing `${CUR}`. Those strings render the literal text `${CUR}` instead of the currency symbol whenever the value is positive. Interpolate `CUR` by concatenating it or using a nested template literal.

## Verdict

NEEDS WORK — task detail displays `${CUR}` for positive price and debt values.