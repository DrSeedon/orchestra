#!/usr/bin/env python3
"""Историческая проба реализации #504; текущий main не проверяет.

RETRACTED: применимость к main отменена в 264daeb7. Старые импорты и типы
сохранены как доказательство ветки #504, не как исполняемая приёмка #530.
"""

import json
from datetime import datetime, timezone

from app.bg_jobs import _blind_review_error
from app.events import AgentEvent
from app.session import AgentSession


def main() -> None:
    live_timed = (
        "The defect appears whenever an agent discusses the phrase session limit "
        "in its own answer."
    )
    live_monthly = (
        "We are debugging a monthly spend limit false positive; the provider did "
        "not limit this turn."
    )
    session = AgentSession(
        id="blast-504",
        name="blast-504",
        scope="/blast",
        cwd="/tmp",
        model="claude-sonnet-5[1m]",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
    )
    session._log = lambda *_args, **_kwargs: None
    session._handle_event(AgentEvent("text", live_timed))
    timed_text_limited = session._session_limit_hit
    session._handle_event(AgentEvent("text", live_monthly))
    monthly_text_limited = session._session_limit_hit
    session._handle_event(AgentEvent(
        "rate_limit",
        metadata={
            "status": "rejected",
            "rate_limit_type": "future_window",
            "resets_at": None,
            "raw": {},
        },
    ))
    review = (
        "## Summary\nThe code matches a phrase.\n\n"
        "## Findings\nblocking: app/bg_jobs.py:54 — the phrase Unable to "
        "perform an evidence-backed review can appear in a valid finding.\n\n"
        "## Verdict\nNEEDS WORK"
    )
    results = {
        "timed_text_limited": timed_text_limited,
        "monthly_text_limited": monthly_text_limited,
        "typed_unknown_limited": session._session_limit_hit,
        "typed_unknown_kind": session._session_limit_kind,
        "blind_review": _blind_review_error(review, ""),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    assert results["timed_text_limited"] is False
    assert results["monthly_text_limited"] is False
    assert results["typed_unknown_limited"] is True
    assert results["typed_unknown_kind"] == "unknown"
    assert results["blind_review"] == ""


if __name__ == "__main__":
    main()
