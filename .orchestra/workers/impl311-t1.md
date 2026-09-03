# impl311-t1 memory

- For durable acceptance APIs, construct the response from the row inside the committing transaction; a post-commit reread can mistake a concurrent cascade/delete for rollback and emit a false retry-safe outcome.
