from __future__ import annotations

from datetime import datetime, timezone

from weekly_cs_report.model_discovery import list_recent_models


NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


def _ticket_trace(
    trace_id: str,
    session_id: str,
    turn: int,
    model_core: str | None,
    *,
    source: str = "ticket",
) -> dict:
    input_data: dict = {"source": source}
    if model_core is not None:
        input_data["model_info"] = {
            "model_core": model_core,
            "model_guardrail": model_core,
        }
    return {
        "id": trace_id,
        "sessionId": session_id,
        "timestamp": "2026-08-20T02:00:00Z",
        "metadata": {"turn": turn},
        "input": input_data,
    }


class FakeClient:
    def __init__(self, traces: list[dict]) -> None:
        self.traces = traces
        self.bounds: list[tuple[datetime, datetime]] = []

    def iter_traces(self, from_timestamp, to_timestamp, *, deadline=None, fields=None):
        self.bounds.append((from_timestamp, to_timestamp))
        yield from self.traces


def test_counts_distinct_tickets_not_raw_trace_rows():
    # ticket-a has two turns on the same arm -- must count as one ticket.
    traces = [
        _ticket_trace("t1", "ticket-a", 0, "google/gemma-4-31B-it"),
        _ticket_trace("t2", "ticket-a", 1, "google/gemma-4-31B-it"),
        _ticket_trace("t3", "ticket-b", 0, "gemini/gemini-3-flash-preview-no-cache"),
        _ticket_trace("t4", "ticket-c", 0, "gemini/gemini-3-flash-preview-no-cache"),
    ]
    client = FakeClient(traces)

    result = list_recent_models(client, now=NOW)

    assert result == [
        "gemini/gemini-3-flash-preview-no-cache",
        "google/gemma-4-31B-it",
    ]


def test_excludes_models_that_never_answer_a_ticket():
    # A model that only appears on a non-ticket trace (e.g. an internal
    # guardrail/labeling call) must never become a candidate arm -- selecting
    # it would filter every ticket out, since no ticket's model_core matches.
    traces = [
        _ticket_trace("t1", "ticket-a", 0, "google/gemma-4-31B-it"),
        _ticket_trace("t2", "internal-1", 0, "gemma-3-27b", source="internal"),
    ]
    client = FakeClient(traces)

    result = list_recent_models(client, now=NOW)

    assert result == ["google/gemma-4-31B-it"]


def test_excludes_tickets_without_model_info():
    traces = [
        _ticket_trace("t1", "ticket-a", 0, "google/gemma-4-31B-it"),
        _ticket_trace("t2", "ticket-b", 0, None),
    ]
    client = FakeClient(traces)

    result = list_recent_models(client, now=NOW)

    assert result == ["google/gemma-4-31B-it"]


def test_empty_when_no_tickets_carry_model_info():
    client = FakeClient([])

    result = list_recent_models(client, now=NOW)

    assert result == []
