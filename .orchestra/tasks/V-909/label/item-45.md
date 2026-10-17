# item-45

Commit under review (in /home/kesha/orchestra, read-only): `951d0d470408f6248993eb2915efe29db67367cc`
Subject / date:
V-680: durable сигнал конца хода воркера родителю вместо idle-сторожа
2026-10-02

The diff reviewed is `git -C /home/kesha/orchestra show 951d0d470408f6248993eb2915efe29db67367cc -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between `ca11458bff4b865ae5604d57403f892a9837bbda` and `12e31f29b8ac36ed989402dd2255520fba45dcb6`. I did not edit files or run tests.

## Findings

### suggestion

- **A delayed auto-report can be recorded under the next turn’s key.** `fire_auto_report()` schedules the callback asynchronously, but `make_key()` reads `_turn_gen` only when that callback runs. Since `bump_turn_gen()` no longer cancels the pending callback, a new turn can start first. The previous turn’s signal then takes the new turn’s key; if that turn also needs an auto-report, its signal can be deduplicated against the previous one. Capture the generation when scheduling the report and use it to build the key. See [session_turns.py](app/session_turns.py:188) and [turn_signals.py](app/turn_signals.py:67).

## Verdict

NEEDS WORK — fix the turn-key race so two successive unreported turns cannot collapse into one signal.
