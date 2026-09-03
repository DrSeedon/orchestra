# impl380-t6

- When translating a SQLite write exception into a retryable rejection, distinguish a successful lookup proving no row from a failed reconciliation lookup; the latter is an unknown outcome and must not invite retry.
