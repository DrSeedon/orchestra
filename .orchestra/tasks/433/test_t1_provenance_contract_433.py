"""Frozen RED oracle for #433 T1: the lossless B1 provenance value."""

import pytest


def test_t1_b1_provenance_is_finite_nonempty_and_lossless():
    import app.events as events

    provenance_type = getattr(events, "MessageProvenance", None)
    assert provenance_type is not None, (
        "#433 T1 missing behavior: MessageProvenance B1 value object is absent"
    )

    value = provenance_type(
        origin="agent",
        senders=("worker-a", "worker-b", "worker-a"),
        subtype="mailbox",
        ref="mailbox:42",
    )
    assert value.origin == "agent"
    assert tuple(value.senders) == ("worker-a", "worker-b")
    assert value.subtype == "mailbox"
    assert value.ref == "mailbox:42"
    origin, detail = value.to_storage()
    assert origin == "agent"
    assert detail == (
        '{"ref":"mailbox:42","senders":["worker-a","worker-b"],'
        '"subtype":"mailbox"}'
    )
    assert provenance_type.from_storage(origin, detail) == value

    for bad in ("", "human", "bg", "other"):
        with pytest.raises(ValueError):
            provenance_type(origin=bad, senders=("source",))
    with pytest.raises(ValueError):
        provenance_type(origin="unknown", senders=())
    with pytest.raises(ValueError):
        provenance_type(origin="agent", senders=("",))
    with pytest.raises(ValueError):
        provenance_type(origin="agent", senders=("worker",), subtype=" ")
    with pytest.raises(ValueError):
        provenance_type(origin="agent", senders=("worker",), ref=" ")


def test_t1_injected_message_owns_structured_provenance_without_legacy_duplicates():
    import app.events as events

    provenance_type = getattr(events, "MessageProvenance", None)
    assert provenance_type is not None, (
        "#433 T1 missing behavior: InjectedMessage cannot receive B1 provenance"
    )
    provenance = provenance_type(
        origin="background_task",
        senders=("bg-433",),
        subtype="completed",
        ref="bg-433",
    )
    injected = events.InjectedMessage(
        text="finished",
        provenance=provenance,
        event_id="bgjob:v1:bg-433:completed",
    )
    assert injected.provenance == provenance
    assert injected.event_id == "bgjob:v1:bg-433:completed"
    assert not hasattr(injected, "job_id")
    assert not hasattr(injected, "origin")
