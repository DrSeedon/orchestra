## Summary

Reviewed the complete diff from `c7b7409ba50dd4b99474f29596580fc5b6d2e852` to `876915709e27d8c721336372e7fb58f0fe514544`. Found one issue that can suppress a required parent notification.

## Findings

### Blocking

- **A delayed signal can be recorded under the next turn’s key and then deduplicated away.** `fire_auto_report()` schedules the idle callback asynchronously. The callback later calls `make_key()`, which reads the worker’s current `_turn_gen`. If another turn starts first, the old turn’s signal gets the new turn’s key. When that turn ends, its signal can collide with the same key and be discarded by the unique constraint. This can leave the parent without either notification. Capture the turn generation when the end is detected and pass that captured value through to `record()`.

## Verdict

NEEDS WORK — capture the ended turn’s identity before scheduling asynchronous delivery.