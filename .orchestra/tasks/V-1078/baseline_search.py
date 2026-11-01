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
    if date_from:
        clauses.append("date(l.ts) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(l.ts) <= date(?)")
        params.append(date_to)
    where = " AND ".join(clauses) or "1"
    needle = query.casefold()
    results = []
    scanned = 0
    # CROSS JOIN fixes logs as the outer loop, allowing the rowid index to stop after
    # the bounded candidate slice instead of sorting all sessions' logs first.
    with _conn() as c:
        candidates = c.execute(
            f"""SELECT l.id, l.session_id, l.ts, l.type, l.content, l.origin,
                       s.name AS agent, s.scope AS project
                FROM logs AS l CROSS JOIN sessions AS s
                WHERE s.id = l.session_id AND {where}
                ORDER BY l.id DESC LIMIT ?""",
            (*params, LOG_SEARCH_SCAN_LIMIT + 1),
        )
        while scanned < LOG_SEARCH_SCAN_LIMIT and (row := candidates.fetchone()) is not None:
            scanned += 1
            content = str(row["content"] or "")
            at = content.casefold().find(needle)
            if at < 0:
                continue
            start = max(0, at - 120)
            end = min(len(content), at + len(query) + 180)
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

