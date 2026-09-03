# T01 — route switch smoke test

The old smoke test asserted only `len(default_gateway().cards()) == 3`. It stayed green when an unavailable route could be selected or when a successful switch failed to drop the four existing connections; adding another valid route would make it red.

Write the smallest regression test(s) for the observable switch behavior. A future fourth healthy route/card is valid and must not break the test. Use the public gateway path, not a helper implementation detail.

