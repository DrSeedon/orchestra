def search_logs(query: str, *, scope: str | None, agent: str | None = None,
                date_from: str | None = None, date_to: str | None = None,
                limit: int = 20) -> dict:
    """Search a bounded newest-first slice of project logs, including voice transcripts."""
    clauses = []
    params: list[object] = []
    if scope is not None:
        clauses.append("s.scope = ?")
        params.append(scope)
    if agent:
        clauses.append("s.name = ?")
        params.append(agent)
    if date_from and date_from == date_to:
        # Equality on the expression index also supplies descending rowid order.
        # Two range predicates make SQLite sort even for a single UTC day.
        clauses.append("date(l.ts) = date(?)")
        params.append(date_from)
    elif date_from:
        clauses.append("date(l.ts) >= date(?)")
        params.append(date_from)
    if date_to and date_to != date_from:
        clauses.append("date(l.ts) <= date(?)")
        params.append(date_to)
    where = " AND ".join(clauses) or "1"
    needle = query.casefold()
    results = []
    scanned = 0
    # Keep payloads out of any range-query sorter. Load only the bounded ids, then
    # fetch content on demand so an early result limit never materializes old blobs.
    # CROSS JOIN keeps logs outer so unfiltered scans can stop at the candidate bound.
    # One explicit read transaction keeps both phases in the same WAL snapshot.
    with _conn() as c:
        c.execute("BEGIN")
        candidates = c.execute(
            f"""SELECT l.id
                FROM logs AS l CROSS JOIN sessions AS s
                WHERE s.id = l.session_id AND {where}
                ORDER BY l.id DESC LIMIT ?""",
            (*params, LOG_SEARCH_SCAN_LIMIT + 1),
        )
        while scanned < LOG_SEARCH_SCAN_LIMIT and (candidate := candidates.fetchone()) is not None:
            row = c.execute(
                """SELECT l.id, l.ts, l.type, l.content, l.origin,
                          s.name AS agent, s.scope AS project
                   FROM logs AS l JOIN sessions AS s ON s.id = l.session_id
                   WHERE l.id = ?""",
                (candidate["id"],),
            ).fetchone()
            scanned += 1
            content = str(row["content"] or "")
            folded = content.casefold()
            at = folded.find(needle)
            if at < 0:
                continue
            # casefold may expand characters (ß → ss, İ → i + combining dot).
            # Convert folded offsets back before slicing the original transcript.
            match_end = at + len(needle)
            if len(folded) != len(content):
                offset = 0
                for index, char in enumerate(content):
                    next_offset = offset + len(char.casefold())
                    if offset <= at < next_offset:
                        original_at = index
                    if next_offset >= match_end:
                        at, match_end = original_at, index + 1
                        break
                    offset = next_offset
            start = max(0, at - 120)
            end = min(len(content), match_end + 180)
            snippet = ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")
            log_type = row["type"]
            if log_type == "user_message" and row["origin"] == "agent":
                kind = "agent message"
            elif log_type == "user_message":
                kind = "user message"
            elif log_type == "text":
                kind = "assistant text"
            else:
                kind = "tool"
            results.append({
                "id": row["id"], "timestamp": row["ts"], "agent": row["agent"],
                "project": row["project"], "type": kind, "snippet": snippet,
            })
            if len(results) >= limit:
                break
        scan_truncated = scanned == LOG_SEARCH_SCAN_LIMIT and candidates.fetchone() is not None
    return {
        "results": results,
        "scanned": scanned,
        "scan_truncated": scan_truncated,
        "limit": limit,
        "result_limit_reached": len(results) == limit,
    }

