# research-quota-map-sol

- `PerformanceResourceTiming.requestStart == 0` plus an absent **completion** log does not prove a request never reached the server. For pre-wire claims, add a marker-bearing ingress log/control; completion and arrival are different events.
- `Promise.allSettled()` does not enter `catch` for rejected children. When auditing stale-data fallback, trace every result branch and verify that failure neither clears nor re-saves the last good value.
