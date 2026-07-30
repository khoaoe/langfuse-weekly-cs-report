from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import pytest
from tests.fixtures.traces import TRANSFER_HTML, trace
from weekly_cs_report.dashboard_schema import project_dashboard
from weekly_cs_report.report import compute_report


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


class FakeClient:
    def __init__(self) -> None:
        self.traces = [
            trace(
                "ai-0",
                "ticket-ai",
                0,
                "2026-07-20T02:00:00Z",
                "A safe synthetic AI reply",
            ),
            trace(
                "transfer-0",
                "ticket-transfer",
                0,
                "2026-07-21T02:00:00Z",
                TRANSFER_HTML,
                title="Topup synthetic",
            ),
            trace(
                "weekend-0",
                "ticket-weekend",
                0,
                "2026-07-25T02:00:00Z",
                "Excluded weekend reply",
            ),
        ]
        self.bounds: list[tuple[datetime, datetime]] = []
        self.observation_trace_ids: list[str] = []
        self.enrichment: dict[str, list[dict]] = {}
        self.enrichment_calls: list[str] = []
        self.fail_enrichment_name: str | None = None

    def iter_traces(self, from_timestamp: datetime, to_timestamp: datetime):
        self.bounds.append((from_timestamp, to_timestamp))
        yield from self.traces

    def list_observations(self, trace_id: str) -> list[dict]:
        self.observation_trace_ids.append(trace_id)
        return []

    def iter_observations_by_name(
        self,
        name: str,
        _from_start_time: datetime,
        _to_start_time: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.enrichment_calls.append(name)
        if name == self.fail_enrichment_name:
            raise RuntimeError("synthetic observation failure")
        yield from self.enrichment.get(name, [])


def test_compute_report_reads_and_analyzes_without_writing_artifacts(tmp_path):
    client = FakeClient()

    run = compute_report(
        client,
        as_of=AS_OF,
        weeks=2,
        include_current_wtd=True,
        taxonomy_path=TAXONOMY_PATH,
    )

    assert run.traces_fetched == 3
    assert run.traces_deduplicated == 3
    assert [item.session_id for item in run.result.sessions] == [
        "ticket-ai",
        "ticket-transfer",
        "ticket-weekend",
    ]
    assert client.observation_trace_ids == []
    assert set(client.enrichment_calls) == {
        "route", "execute", "input_guardrail", "skill_guardrail_checked", "escalation_history_guard"
    }
    assert run.enrichment_status == "complete"
    assert run.observations_fetched == 0
    assert not (tmp_path / "artifacts").exists()


def test_compute_report_keeps_only_exact_ticket_source_before_deduplication_and_analysis():
    """A chat trace must not win dedupe or become a ticket lifecycle turn."""
    client = FakeClient()
    chat_collision = trace(
        "ticket-0",
        "c7534640-c83e-48ef-9104-b1cad2183950",
        0,
        "2026-07-20T01:00:00Z",
        "Chat reply",
    )
    chat_collision["input"]["source"] = "chat"
    ticket_turn0 = trace(
        "ticket-0",
        "145665",
        0,
        "2026-07-20T02:00:00Z",
        "Ticket reply",
    )
    chat_followup = trace(
        "chat-followup",
        "145665",
        1,
        "2026-07-21T02:00:00Z",
        TRANSFER_HTML,
    )
    chat_followup["input"]["source"] = "chat"
    wrong_case = trace(
        "wrong-case",
        "c9534640-c83e-48ef-9104-b1cad2183950",
        0,
        "2026-07-21T02:00:00Z",
        "Wrong source",
    )
    wrong_case["input"]["source"] = "Ticket"
    missing_source = trace(
        "missing-source",
        "d0534640-c83e-48ef-9104-b1cad2183950",
        0,
        "2026-07-22T02:00:00Z",
        "Missing source",
    )
    del missing_source["input"]["source"]
    legacy_ticket = trace(
        "legacy-ticket",
        "145666",
        0,
        "2026-07-23T02:00:00Z",
        "Legacy ticket reply",
    )
    del legacy_ticket["input"]["other_info"]["freshdesk_id"]
    client.traces = [
        chat_collision,
        ticket_turn0,
        chat_followup,
        wrong_case,
        missing_source,
        legacy_ticket,
    ]

    run = compute_report(
        client,
        as_of=AS_OF,
        weeks=2,
        include_current_wtd=True,
        taxonomy_path=TAXONOMY_PATH,
    )

    assert run.traces_fetched == 2
    assert run.traces_deduplicated == 2
    assert [
        (item.session_id, item.outcome)
        for item in run.result.sessions
    ] == [
        ("145665", "ai_end_to_end"),
        ("145666", "ai_end_to_end"),
    ]
    assert run.result.selection.invalid_keyed == ()
    assert run.result.selection.unkeyed == ()
    assert client.observation_trace_ids == []


def test_compute_report_applies_complete_bulk_enrichment_without_per_ticket_observation_calls():
    client = FakeClient()
    client.enrichment = {
        "route": [{"traceId": "ai-0", "metadata": {"intent": "refund_request"}}],
        "execute": [{"traceId": "ai-0", "metadata": {"skills_used": "customer-service/topup"}}],
        "input_guardrail": [{"traceId": "ai-0", "output": {"rule": "missing_transaction_id"}}],
        "skill_guardrail_checked": [],
        "escalation_history_guard": [{"traceId": "ai-0", "output": {"blocked": True}}],
    }

    run = compute_report(client, as_of=AS_OF, weeks=2, include_current_wtd=True, taxonomy_path=TAXONOMY_PATH)
    session = next(item for item in run.result.sessions if item.session_id == "ticket-ai")

    assert client.observation_trace_ids == []
    assert run.enrichment_status == "complete"
    assert run.observations_fetched == 4
    assert session.dimensions.intent == "refund_request"
    assert session.dimensions.skill == "topup"
    assert session.dimensions.guardrail_rule == "missing_transaction_id"
    assert session.dimensions.escalation_guard_blocked is True
    snapshot = project_dashboard(run).dashboard_dict()
    assert snapshot["enrichment_status"] == "complete"
    assert snapshot["source"]["observations_fetched"] == 4


def test_one_enrichment_class_failure_discards_all_partial_signals_but_keeps_core_report():
    client = FakeClient()
    client.enrichment = {
        "route": [{"traceId": "ai-0", "metadata": {"intent": "refund_request"}}],
    }
    client.fail_enrichment_name = "execute"

    run = compute_report(client, as_of=AS_OF, weeks=2, include_current_wtd=True, taxonomy_path=TAXONOMY_PATH)
    session = next(item for item in run.result.sessions if item.session_id == "ticket-ai")

    assert run.enrichment_status == "partial"
    assert run.observations_fetched == 1
    assert session.dimensions.intent is None
    assert session.dimensions.skill is None
    assert session.dimensions.guardrail_rule is None
    assert session.dimensions.escalation_guard_blocked is False
    assert [item.session_id for item in run.result.sessions] == ["ticket-ai", "ticket-transfer", "ticket-weekend"]
    snapshot = project_dashboard(run).dashboard_dict()
    assert snapshot["enrichment_status"] == "partial"
    assert snapshot["source"]["observations_fetched"] == 1


def test_conflicting_guardrail_scalars_fail_closed_without_losing_max_replies_count():
    client = FakeClient()
    client.enrichment = {
        "input_guardrail": [
            {"traceId": "ai-0", "output": {"rule": "max_replies_exceeded"}},
        ],
        "skill_guardrail_checked": [
            {"traceId": "ai-0", "output": {"rule": "off_topic"}},
        ],
    }

    run = compute_report(
        client, as_of=AS_OF, weeks=2,
        include_current_wtd=True, taxonomy_path=TAXONOMY_PATH,
    )
    session = next(item for item in run.result.sessions if item.session_id == "ticket-ai")
    dashboard = project_dashboard(run).dashboard_dict()

    assert session.dimensions.guardrail_rule is None
    assert session.guardrail_rules == ("max_replies_exceeded", "off_topic")
    assert dashboard["views"]["mon_sun"]["rule_gt4"]["max_replies_rule_fired"] == 1
    assert "guardrail_rules" not in str(dashboard)


def test_observation_lanes_start_before_trace_pagination():
    class ConcurrentClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.observation_started = threading.Event()

        def iter_traces(self, from_timestamp: datetime, to_timestamp: datetime):
            assert self.observation_started.wait(timeout=1)
            yield from super().iter_traces(from_timestamp, to_timestamp)

        def iter_observations_by_name(self, *args, **kwargs):
            self.observation_started.set()
            yield from super().iter_observations_by_name(*args, **kwargs)

    run = compute_report(
        ConcurrentClient(), as_of=AS_OF, weeks=2,
        include_current_wtd=True, taxonomy_path=TAXONOMY_PATH,
    )

    assert run.enrichment_status == "complete"


def test_trace_failure_cancels_and_drains_observation_workers_before_reraising():
    class FailingTraceClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.observation_started = threading.Event()
            self.observation_stopped = threading.Event()

        def iter_traces(self, _from_timestamp: datetime, _to_timestamp: datetime):
            assert self.observation_started.wait(timeout=1)
            raise RuntimeError("synthetic trace failure")
            yield  # pragma: no cover - makes this a generator for the protocol

        def iter_observations_by_name(self, *args, cancel_event=None, **kwargs):
            self.observation_started.set()
            limit = time.monotonic() + 0.05
            while time.monotonic() < limit and not (cancel_event and cancel_event.is_set()):
                time.sleep(0.001)
            if cancel_event and cancel_event.is_set():
                self.observation_stopped.set()
            return
            yield  # pragma: no cover - generator protocol

    client = FailingTraceClient()

    with pytest.raises(RuntimeError, match="synthetic trace failure"):
        compute_report(
            client, as_of=AS_OF, weeks=2,
            include_current_wtd=True, taxonomy_path=TAXONOMY_PATH,
        )

    assert client.observation_stopped.is_set()
