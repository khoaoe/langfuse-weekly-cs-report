from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from tests.fixtures.traces import trace
from tests.test_dashboard_schema import _snapshot as schema_snapshot
from weekly_cs_report.cli import (
    ConfigurationError,
    EnvironmentSettings,
    PROJECT_ROOT,
    TARGET_BASE_URL,
)
from weekly_cs_report.dashboard_cache import ProtectedSnapshotStore, SnapshotManager
from weekly_cs_report.dashboard_schema import (
    DashboardSnapshot,
    TicketRow,
    _ticket_public_dict,
    project_dashboard,
)
from weekly_cs_report.entry_coverage_cache import EntryCoverageRecord
from weekly_cs_report.report import compute_report
from weekly_cs_report.web import (
    WebSettings,
    _parse_ticket_query,
    _validated_runtime_directory,
    create_app,
    main,
)


NOW = datetime(2026, 7, 29, 5, tzinfo=timezone.utc)
IDENTITY_HEADER = "X-Forwarded-User"
REFRESH_ACTION_HEADERS = {"X-Dashboard-Action": "refresh"}
COOKIE_ACTION_HEADERS = {"X-Dashboard-Action": "update_freshdesk_cookie"}


def _empty_transfer_reasons() -> dict[str, object]:
    return {
        "observed_transfer_denominator": 0,
        "triggers": [],
        "tpe": [],
        "step_result_missing": {"count": 0, "denominator": 0},
        "guardrail": [],
        "escalation_guard_blocked": {"count": 0, "denominator": 0},
    }


def _dashboard(generated_at: datetime, eligible: int = 3) -> dict[str, object]:
    generated_at_text = generated_at.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "generated_at": generated_at_text,
        "source": {"traces_fetched": eligible, "traces_deduplicated": eligible, "observations_fetched": 0},
        "enrichment_status": "partial",
        "data_range": {"first_week_with_data": None, "weeks_without_data": []},
        "views": {
            view: {
                "totals": {"eligible_ticket_count": 0, "transfer_total": 0, "gt4_turn_total": 0, "weekend_start_count": 0},
                "outcomes": {"ai_end_to_end": 0, "ai_then_cs": 0, "direct_cs": 0, "unclassified": 0},
                "ai_first": {"count": 0, "rate": 0.0},
                "reopen": {"lifetime": {"numerator": 0, "denominator": 0}, "within_7d": {"numerator": 0, "denominator": 0}},
                "weekly": [],
                "segments": {name: {("Chưa ghi nhận" if name == "skill" else "Không xác định"): {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0}} for name in ("issue_category", "app", "product_code", "skill", "intent", "tpe", "guardrail_rule", "entry_point", "model_core")},
                "transfer_reasons": _empty_transfer_reasons(),
                "by_week": {},
                "same_period": None,
                "csat": None,
                "outcome_reconciliation": None,
                "entry_coverage": None,
                "rule_gt4": {"gt4_turn_total": 0, "gt4_turn_with_cs": 0, "gt4_turn_without_cs": 0, "max_replies_rule_fired": 0},
            }
            for view in ("mon_sun", "mon_fri")
        },
        "coverage": {"issue_category": 0.0, "app": 0.0, "tpe": 0.0, "intent": 0.0, "skill": 0.0},
        "unmapped_tpe_codes": [],
        "gate_status": {"allowed": True, "structural_invalid_rate": 0.0, "reasons": []},
        "data_quality": {"counts": {}, "weekend_start_count": 0, "left_censored_count": 0, "pre_window_start_count": 0, "invalid_keyed_session_count": 0, "unkeyed_trace_count": 0},
    }


def _ticket(ticket_id: str, outcome: str) -> TicketRow:
    return TicketRow(
        ticket_id=ticket_id,
        opened_at="2026-07-20T02:00:00Z",
        cohort_week="2026-07-20",
        cohort_status="complete",
        is_weekend_start=False,
        outcome=outcome,
        ai_first=outcome != "direct_cs",
        transferred=outcome != "ai_end_to_end",
        reopen_lifetime=0,
        reopen_within_7d=0,
        ai_reply_count=0 if outcome == "direct_cs" else 1,
        turn_count=1,
        gt4_turn=False,
        issue_category="Thanh toán-IBFT",
        app="241 - Chuyển Tiền ATM",
        product_code="TF007 - IBFT",
        skill=None,
        intent=None,
        tpe_code="-217",
        tpe_status=None,
        guardrail_rule=None,
        transfer_reason=("unknown" if outcome != "ai_end_to_end" else None),
        escalation_guard_blocked=False,
        csat_satisfaction=None,
        data_quality="valid",
    )


def _snapshot(
    generated_at: datetime = NOW,
    *,
    ticket_ids: tuple[str, ...] = ("300", "100", "200"),
) -> DashboardSnapshot:
    outcomes = ("direct_cs", "ai_end_to_end", "ai_then_cs")
    return DashboardSnapshot(
        generated_at=generated_at,
        dashboard=_dashboard(generated_at, len(ticket_ids)),
        tickets=tuple(
            _ticket(ticket_id, outcomes[index % len(outcomes)])
            for index, ticket_id in enumerate(ticket_ids)
        ),
    )


def _entry_coverage_snapshot() -> DashboardSnapshot:
    base = schema_snapshot()
    records = (
        EntryCoverageRecord(
            ticket_id="700",
            opened_at="2026-07-14T02:00:00Z",
            cohort_week="2026-07-13",
            status="ai_replied_only",
            human_replied=None,
        ),
        EntryCoverageRecord(
            ticket_id="701",
            opened_at="2026-07-21T02:00:00Z",
            cohort_week="2026-07-20",
            status="not_observed_invoked",
            human_replied=True,
        ),
        EntryCoverageRecord(
            ticket_id="702",
            opened_at="2026-07-24T18:00:00Z",
            cohort_week="2026-07-20",
            status="not_observed_invoked",
            human_replied=False,
        ),
        EntryCoverageRecord(
            ticket_id="703",
            opened_at="2026-07-28T02:00:00Z",
            cohort_week="2026-07-27",
            status="unresolved",
            human_replied=None,
        ),
    )
    dashboard = deepcopy(base.dashboard)
    counts = {
        "2026-07-13": {
            "freshdesk_ticket_count": 1,
            "ai_replied_only": 1,
            "ai_replied_then_transferred": 0,
            "transferred_without_ai_reply": 0,
            "invoked_no_result": 0,
            "not_observed_invoked": 0,
            "not_observed_human_replied": 0,
            "not_observed_no_human_reply": 0,
            "unresolved": 0,
        },
        "2026-07-20": {
            "freshdesk_ticket_count": 2,
            "ai_replied_only": 0,
            "ai_replied_then_transferred": 0,
            "transferred_without_ai_reply": 0,
            "invoked_no_result": 0,
            "not_observed_invoked": 2,
            "not_observed_human_replied": 1,
            "not_observed_no_human_reply": 1,
            "unresolved": 0,
        },
        "2026-07-27": {
            "freshdesk_ticket_count": 1,
            "ai_replied_only": 0,
            "ai_replied_then_transferred": 0,
            "transferred_without_ai_reply": 0,
            "invoked_no_result": 0,
            "not_observed_invoked": 0,
            "not_observed_human_replied": 0,
            "not_observed_no_human_reply": 0,
            "unresolved": 1,
        },
    }
    for view in dashboard["views"].values():
        view["entry_coverage"] = {
            "source": "freshdesk",
            "source_start_week": "2026-07-06",
            "fetched_at": "2026-08-04T03:00:00Z",
            "by_week": deepcopy(counts),
        }
    return DashboardSnapshot(
        generated_at=base.generated_at,
        dashboard=dashboard,
        tickets=base.tickets,
        entry_coverage_tickets=records,
    )


def _aggregate_only_snapshot() -> DashboardSnapshot:
    class AggregateOnlyClient:
        def iter_traces(
            self,
            _from: datetime,
            _to: datetime,
            *,
            deadline: float | None = None,
            cancel_event: threading.Event | None = None,
            max_pages: int = 500,
        ):
            raw = trace(
                "aggregate-only-trace",
                "aggregate-only-session",
                0,
                "2026-07-21T02:00:00Z",
                "AI reply",
            )
            raw["input"]["other_info"]["meta"] = {
                "Thông tin thêm": {
                    "category": "Thanh toán QR",
                    "sub_source": "payment-detail",
                },
                "App": "Ứng dụng Zalopay",
                "Product Code": "PAYMENT",
                "Mã lỗi TPE": "-404 Đang xử lý",
                "Step result": "-1|20|700212|mô tả không được xuất",
            }
            yield raw

        def iter_observations_by_name(self, name, *_args, **_kwargs):
            if name != "tool:get_transaction_processing_engine_data":
                return iter(())
            return iter(
                (
                    {
                        "traceId": "aggregate-only-trace",
                        "output": {
                            "result": {
                                "transstatus": "-404",
                                "stepresult": "-1013",
                            }
                        },
                    },
                )
            )

    run = compute_report(
        AggregateOnlyClient(),
        as_of=NOW,
        weeks=2,
        include_current_wtd=True,
        taxonomy_path=PROJECT_ROOT / "config" / "taxonomy.v2.json",
    )
    snapshot = project_dashboard(run)
    assert snapshot.tickets == ()
    return snapshot


@pytest.fixture
def manager_factory(tmp_path: Path):
    managers: list[SnapshotManager] = []

    def make(
        *,
        initial: DashboardSnapshot | None = None,
        loader=None,
        clock=None,
    ) -> SnapshotManager:
        store = ProtectedSnapshotStore(tmp_path / f"runtime-{len(managers)}")
        if initial is not None:
            store.save(initial)
        manager = SnapshotManager(
            loader or (lambda: _snapshot()),
            store,
            clock=clock or (lambda: NOW),
        )
        managers.append(manager)
        return manager

    yield make

    for manager in managers:
        manager.close()


def _state(snapshot: DashboardSnapshot, *, status: str = "ready", refreshing=False):
    return {
        "status": status,
        "refreshing": refreshing,
        "last_error_code": None,
        "last_error_at": None,
        "snapshot": snapshot.dashboard_dict(),
    }


def test_dashboard_returns_ready_snapshot_with_exact_state_envelope(manager_factory):
    """Dropping cache state or serving storage-only fields breaks the browser contract."""
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert response.json() == _state(snapshot)
    assert set(response.json()) == {
        "status",
        "refreshing",
        "last_error_code",
        "last_error_at",
        "snapshot",
    }


def test_dashboard_first_load_returns_fixed_202_state(manager_factory):
    """Returning 200 or a partial snapshot before the first load misstates readiness."""
    manager = manager_factory()

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 202
    assert response.json() == {
        "status": "loading",
        "refreshing": True,
        "last_error_code": None,
        "last_error_at": None,
        "snapshot": None,
    }


def test_v2_snapshot_starts_not_ready_then_becomes_ready_after_refresh(tmp_path):
    """P2 must ignore, never convert, a persisted metric-v2 snapshot."""
    runtime = tmp_path / "runtime"
    store = ProtectedSnapshotStore(runtime)
    legacy = _snapshot().storage_dict()
    legacy["schema_version"] = 2
    runtime.mkdir(mode=0o700)
    (runtime / "dashboard_snapshot.json").write_text(json.dumps(legacy), encoding="utf-8")
    manager = SnapshotManager(lambda: _snapshot(), store, clock=lambda: NOW)

    with TestClient(create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))) as client:
        assert client.get("/readyz").status_code == 503
        assert client.get("/api/dashboard").status_code == 202
        assert manager.wait_for_idle(2)
        assert client.get("/readyz").status_code == 200


def test_proxy_auth_rejects_missing_identity_and_never_echoes_identity(manager_factory):
    """Trusting an absent header or serializing its value exposes a protected dashboard."""
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)
    app = create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))

    with TestClient(app) as client:
        missing = client.get("/api/dashboard")
        authorized = client.get(
            "/api/dashboard",
            headers={IDENTITY_HEADER: "person-secret@example.test"},
        )

    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "authentication_required"}}
    assert authorized.status_code == 200
    assert "person-secret@example.test" not in authorized.text


@pytest.mark.parametrize(
    "headers",
    [
        [(IDENTITY_HEADER, "operator"), (IDENTITY_HEADER, "operator")],
        {IDENTITY_HEADER: "operator,second"},
        {IDENTITY_HEADER: " operator"},
        {IDENTITY_HEADER: "operator "},
        {IDENTITY_HEADER: "operator name"},
        {IDENTITY_HEADER: "operator\x01"},
        {IDENTITY_HEADER: ""},
        {IDENTITY_HEADER: "x" * 257},
    ],
)
def test_proxy_auth_rejects_ambiguous_or_invalid_identity_values(manager_factory, headers):
    manager = manager_factory(initial=_snapshot())
    app = create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))

    with TestClient(app) as client:
        response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_required"}}


def test_one_valid_identity_authorizes_document_api_and_assets(manager_factory):
    manager = manager_factory(initial=_snapshot())
    app = create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))
    headers = {IDENTITY_HEADER: "operator-123"}

    with TestClient(app) as client:
        document = client.get("/", headers=headers)
        api = client.get("/api/dashboard", headers=headers)
        asset = client.get("/assets/langfuse-icon-BDc85awm.svg", headers=headers)

    assert [response.status_code for response in (document, api, asset)] == [200, 200, 200]


def test_application_lifecycle_emits_json_service_events(manager_factory, caplog):
    manager = manager_factory(initial=_snapshot())
    app = create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))

    with TestClient(app):
        pass

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]
    assert {"event": "service_start"} in events
    assert {"event": "service_stop"} in events


def test_ticket_endpoint_uses_last_good_snapshot_and_paginates(manager_factory):
    """Ignoring server-side pagination can return the complete ticket population."""
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets?page=2&page_size=2")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            _ticket_public_dict(
                next(row for row in snapshot.tickets if row.ticket_id == "300")
            )
        ],
        "page": 2,
        "page_size": 2,
        "total": 3,
    }


def test_ticket_endpoint_applies_allowlisted_sort_before_pagination(manager_factory):
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(
            "/api/tickets?sort_by=ticket_id&sort_direction=desc&page=1&page_size=2"
        )

    assert response.status_code == 200
    assert [item["ticket_id"] for item in response.json()["items"]] == [
        "300",
        "200",
    ]


def test_ticket_endpoint_never_leaks_day_grain_diagnostic_fields(manager_factory):
    """§4.1 privacy contract: `transfer_rule`/`transfer_source`/`transfer_stage`/
    `transfer_skill`/`guardrail_rules`/`tpe_signals` exist on `TicketRow` only
    to let day aggregates reconstruct the weekly transfer/TPE grain -- the
    non-aggregate ticket page must never expose them to the browser."""
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets?page=1&page_size=50")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    for item in body["items"]:
        for private_field in (
            "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
            "guardrail_rules", "tpe_signals",
        ):
            assert private_field not in item
    # sort_by must not accept those fields as a Ticket Explorer column either.
    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        rejected = client.get("/api/tickets?sort_by=tpe_signals&sort_direction=asc")
    assert rejected.status_code == 422


def test_ticket_endpoint_aggregate_returns_day_buckets_instead_of_ticket_list(
    manager_factory,
):
    """aggregate=1 must never return a page-limited item list -- callers use
    it precisely to avoid paginating thousands of tickets client-side."""
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(
            "/api/tickets?aggregate=1&opened_from=2026-07-20&opened_to=2026-07-20"
        )

    assert response.status_code == 200
    body = response.json()
    assert "items" not in body
    assert body == {
        "days": [
            {
                "day": "2026-07-20",
                "total_tickets": 3,
                "ai_first_count": 2,
                "transferred_count": 2,
                "direct_cs_count": 1,
                "outcomes": {
                    "ai_end_to_end": 1,
                    "ai_then_cs": 1,
                    "direct_cs": 1,
                    "unclassified": 0,
                },
                "reopen_lifetime_numerator": 0,
                "reopen_lifetime_denominator": 3,
                "gt4_turn_with_cs": 0,
                "gt4_turn_without_cs": 0,
                "resolved_first_reply_count": 1,
                "ai_reply_sum_ai_first": 2,
                "segments": {
                    "skill": {},
                    "app": {
                        "241 - Chuyển Tiền ATM": {
                            "total": 3,
                            "ai_first": 2,
                            "transferred": 2,
                            "reopen": 0,
                        }
                    },
                    "issue_category": {
                        "Thanh toán-IBFT": {
                            "total": 3,
                            "ai_first": 2,
                            "transferred": 2,
                            "reopen": 0,
                        }
                    },
                },
                "transfer_reasons": {
                    "observed_transfer_denominator": 2,
                    "triggers": [
                        {
                            "reason": "unknown",
                            "rule": None,
                            "source": None,
                            "stage": None,
                            "skill": None,
                            "count": 2,
                        }
                    ],
                    "tpe": [],
                    "step_result_missing": {"count": 2, "denominator": 2},
                    "guardrail": [],
                    "escalation_guard_blocked": {"count": 0, "denominator": 2},
                },
            }
        ],
    }


def test_ticket_endpoint_aggregate_requires_opened_from_and_opened_to(
    manager_factory,
):
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        missing_to = client.get("/api/tickets?aggregate=1&opened_from=2026-07-20")
        missing_both = client.get("/api/tickets?aggregate=1")

    assert missing_to.status_code == 422
    assert missing_to.json()["detail"]["code"] == "invalid_query"
    assert missing_both.status_code == 422


def test_ticket_endpoint_aggregate_forwards_week_definition_to_exclude_weekend_days(
    manager_factory,
):
    snapshot = _snapshot()
    weekend_ticket = replace(
        snapshot.tickets[0],
        ticket_id="900",
        opened_at="2026-07-25T18:00:00Z",
        is_weekend_start=True,
    )
    manager = manager_factory(
        initial=replace(snapshot, tickets=(*snapshot.tickets, weekend_ticket))
    )

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        both = client.get(
            "/api/tickets?aggregate=1&opened_from=2026-07-20&opened_to=2026-07-26"
        )
        mon_fri_only = client.get(
            "/api/tickets?aggregate=1&opened_from=2026-07-20&opened_to=2026-07-26"
            "&week_definition=mon_fri"
        )

    assert both.status_code == 200
    assert mon_fri_only.status_code == 200
    both_total = sum(day["total_tickets"] for day in both.json()["days"])
    mon_fri_total = sum(day["total_tickets"] for day in mon_fri_only.json()["days"])
    assert both_total == 4
    assert mon_fri_total == 3


def test_entry_coverage_endpoint_filters_multiple_weeks_and_keeps_safe_projection(
    manager_factory,
):
    snapshot = _entry_coverage_snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(
            "/api/freshdesk-entry-coverage/tickets",
            params={
                "week_definition": "mon_sun",
                "cohort_weeks": "2026-07-13,2026-07-20",
                "sort_by": "opened_at",
                "sort_dir": "desc",
                "page": 1,
                "page_size": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["ticket_id"] for item in payload["items"]] == ["702", "701", "700"]
    assert payload["total"] == 3
    assert set(payload["items"][0]) == {
        "ticket_id",
        "opened_at",
        "cohort_week",
        "status",
        "human_replied",
    }
    assert "agent_id" not in response.text
    assert "requester" not in response.text


def test_entry_coverage_endpoint_filters_status_paginates_and_excludes_weekend_for_mon_fri(
    manager_factory,
):
    manager = manager_factory(initial=_entry_coverage_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        status_page = client.get(
            "/api/freshdesk-entry-coverage/tickets",
            params={
                "cohort_weeks": "2026-07-20",
                "status": "not_observed_invoked",
                "sort_by": "ticket_id",
                "sort_dir": "asc",
                "page": 1,
                "page_size": 1,
            },
        )
        friday_only = client.get(
            "/api/freshdesk-entry-coverage/tickets",
            params={
                "week_definition": "mon_fri",
                "cohort_weeks": "2026-07-20",
                "status": "not_observed_invoked",
            },
        )

    assert status_page.status_code == 200
    assert status_page.json()["total"] == 2
    assert [item["ticket_id"] for item in status_page.json()["items"]] == ["701"]
    assert friday_only.status_code == 200
    assert friday_only.json()["total"] == 1
    assert [item["ticket_id"] for item in friday_only.json()["items"]] == ["701"]


def test_entry_coverage_endpoint_has_same_auth_boundary_and_sanitized_queries(
    manager_factory,
):
    manager = manager_factory(initial=_entry_coverage_snapshot())
    app = create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))

    with TestClient(app) as client:
        missing = client.get("/api/freshdesk-entry-coverage/tickets")
        malformed = client.get(
            "/api/freshdesk-entry-coverage/tickets?status=not-a-status",
            headers={IDENTITY_HEADER: "operator"},
        )

    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "authentication_required"}}
    assert malformed.status_code == 422
    assert malformed.json() == {
        "detail": {"code": "invalid_query", "parameter": "status"}
    }


def test_ticket_endpoint_filters_strict_csat_satisfaction_states(manager_factory):
    snapshot = _snapshot()
    snapshot = DashboardSnapshot(
        generated_at=snapshot.generated_at,
        dashboard=snapshot.dashboard,
        tickets=(
            replace(snapshot.tickets[0], csat_satisfaction="negative"),
            replace(snapshot.tickets[1], csat_satisfaction="unrated"),
            snapshot.tickets[2],
        ),
    )
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        negative = client.get("/api/tickets?csat_satisfaction=negative")
        unrated = client.get("/api/tickets?csat_satisfaction=unrated")

    assert [item["ticket_id"] for item in negative.json()["items"]] == ["300"]
    assert [item["ticket_id"] for item in unrated.json()["items"]] == ["100"]


def test_ticket_endpoint_filters_strict_transfer_reason(manager_factory):
    snapshot = _snapshot()
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets?transfer_reason=unknown")

    assert response.status_code == 200
    assert [item["ticket_id"] for item in response.json()["items"]] == [
        "200",
        "300",
    ]


def test_browser_json_boundaries_recursively_exclude_pii_patterns_and_deny_keys(
    manager_factory,
):
    manager = manager_factory(initial=_snapshot())
    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        responses = (
            client.get("/api/dashboard"),
            client.get("/api/tickets?page=1&page_size=100&week_definition=mon_sun"),
        )

    deny_keys = {
        "UserID", "App user", "Số điện thoại người dùng", "TransID",
        "AppTransId", "Mã giao dịch", "Zalopay chat keys", "System Info",
        "UserAgent", "Ghi chú", "Ghi chú bên thứ ba", "Mô tả", "Vấn đề",
        "Thông tin thêm", "title", "user_input", "comments",
        "Số tài khoản ngân hàng", "SĐT đăng ký NH", "Thời gian giao dịch",
        "Thời điểm giao dịch", "trace_id", "observation_id", "score_id",
    }
    phone = re.compile(r"(?<!\d)(?:0|84|\+84)[0-9]{8,10}(?!\d)")
    uuid = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    )

    def inspect(value):
        if isinstance(value, dict):
            assert not (set(value) & deny_keys)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for response in responses:
        assert response.status_code == 200
        assert phone.search(response.text) is None
        assert uuid.search(response.text) is None
        inspect(response.json())


def test_ticket_endpoint_is_fixed_503_before_first_snapshot(manager_factory):
    """Passing a missing snapshot into the paginator leaks an internal exception."""
    started = threading.Event()
    release = threading.Event()

    def loader() -> DashboardSnapshot:
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot()

    manager = manager_factory(loader=loader)
    try:
        with TestClient(
            create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
        ) as client:
            response = client.get("/api/tickets")
            assert started.wait(2)
    finally:
        release.set()

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "dashboard_not_ready"}}


@pytest.mark.parametrize(
    ("query", "parameter"),
    [
        ("page_size=101", "page_size"),
        ("cohort_week=sk-secret-value", "cohort_week"),
        ("cohort_weeks=2026-07-20", "cohort_weeks"),
        ("opened_from=sk-secret-value", "opened_from"),
        ("opened_to=sk-secret-value", "opened_to"),
        ("opened_from=2026-07-30&opened_to=2026-07-20", "opened_from"),
        ("opened_from=2026-07-20&cohort_week=2026-07-20", "opened_from"),
        ("opened_to=2026-07-20&cohort_weeks=2026-07-13,2026-07-20", "opened_from"),
        ("outcome=sk-secret-value", "outcome"),
        ("ticket_id=0901234567%21", "ticket_id"),
        ("page=1&page=0901234567", "page"),
        ("sort_by=sk-secret-value", "sort_by"),
        ("sort_direction=sk-secret-value", "sort_direction"),
        ("csat_satisfaction=" + ("x" * 129), "csat_satisfaction"),
        ("csat_satisfaction=negative&csat_satisfaction=positive", "csat_satisfaction"),
        ("sk-secret-value=0901234567", "unknown"),
    ],
)
def test_ticket_query_errors_are_fixed_sanitized_422(
    manager_factory, query: str, parameter: str
):
    """Echoing invalid names or values can disclose credentials and customer data."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(f"/api/tickets?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_query", "parameter": parameter}
    }
    assert "sk-secret-value" not in response.text
    assert "0901234567" not in response.text


@pytest.mark.parametrize(
    ("query", "parameter"),
    [
        ("issue_category=not-in-snapshot", "issue_category"),
        ("app=not-in-snapshot", "app"),
        ("product_code=not-in-snapshot", "product_code"),
        ("skill=not-in-snapshot", "skill"),
        ("intent=not-in-snapshot", "intent"),
        ("tpe_code=not-in-snapshot", "tpe_code"),
        ("transfer_reason=not-in-snapshot", "transfer_reason"),
        ("gt4_turn=TRUE", "gt4_turn"),
        ("transferred=TRUE", "transferred"),
        ("is_weekend_start=yes", "is_weekend_start"),
        ("week_definition=weekend", "week_definition"),
        ("sort_by=raw_payload", "sort_by"),
        ("sort_direction=sideways", "sort_direction"),
        ("sort_direction=desc", "sort_direction"),
        ("csat_satisfaction=unknown", "csat_satisfaction"),
        ("skill=" + ("x" * 129), "skill"),
        ("intent=a&intent=b", "intent"),
    ],
)
def test_p5_ticket_filters_fail_closed_without_echoing_values(
    manager_factory, query: str, parameter: str
):
    manager = manager_factory(initial=_snapshot())
    with TestClient(create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))) as client:
        response = client.get(f"/api/tickets?{query}")
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_query", "parameter": parameter}}
    assert "not-in-snapshot" not in response.text


@pytest.mark.parametrize(
    ("query_parameter", "segment_dimension", "value"),
    [
        ("issue_category", "issue_category", "Thanh toán QR"),
        ("app", "app", "Ứng dụng Zalopay"),
        ("product_code", "product_code", "PAYMENT"),
        ("skill", "skill", "Chưa ghi nhận"),
        ("intent", "intent", "Không xác định"),
        ("tpe_code", "tpe", "-404"),
    ],
)
def test_p5_ticket_filters_accept_browser_visible_aggregate_values_without_ticket_rows(
    manager_factory,
    query_parameter: str,
    segment_dimension: str,
    value: str,
):
    """A visible aggregate filter can honestly return an empty safe ticket page."""
    snapshot = _aggregate_only_snapshot()
    mon_sun_segments = snapshot.dashboard["views"]["mon_sun"]["segments"]
    assert value in mon_sun_segments[segment_dimension]
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets", params={query_parameter: value})

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 50,
        "total": 0,
    }


def test_p5_intent_filter_does_not_accept_other_aggregate_dimensions(
    manager_factory,
):
    """Only the privacy-approved intent segment may broaden the intent allowlist."""
    snapshot = _aggregate_only_snapshot()
    value = "Thanh toán QR"
    assert value in snapshot.dashboard["views"]["mon_sun"]["segments"][
        "issue_category"
    ]
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets", params={"intent": value})

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_query", "parameter": "intent"}
    }
    assert value not in response.text


def test_p5_ticket_filters_accept_strict_booleans_and_week_definition(manager_factory):
    manager = manager_factory(initial=_snapshot())
    with TestClient(create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))) as client:
        response = client.get("/api/tickets?gt4_turn=false&transferred=true&week_definition=mon_fri")
    assert response.status_code == 200
    assert all(item["gt4_turn"] is False and item["transferred"] is True for item in response.json()["items"])


def test_ticket_endpoint_accepts_multiple_report_weeks(manager_factory):
    base = _snapshot()
    snapshot = replace(
        base,
        tickets=(
            replace(base.tickets[0], cohort_week="2026-07-13"),
            replace(base.tickets[1], cohort_week="2026-07-20"),
            replace(base.tickets[2], cohort_week="2026-07-27"),
        ),
    )
    manager = manager_factory(initial=snapshot)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(
            "/api/tickets",
            params={"cohort_weeks": "2026-07-13,2026-07-20"},
        )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["cohort_week"] for item in response.json()["items"]} == {
        "2026-07-13",
        "2026-07-20",
    }


def test_ticket_endpoint_accepts_the_full_18_unique_query_pair_contract(manager_factory):
    snapshot = _snapshot()
    selected = snapshot.tickets[0]
    params = [
        ("cohort_week", selected.cohort_week),
        ("outcome", selected.outcome),
        ("ticket_id", selected.ticket_id),
        ("issue_category", selected.issue_category),
        ("app", selected.app),
        ("product_code", selected.product_code),
        ("skill", selected.skill or "Chưa ghi nhận"),
        ("intent", selected.intent or "Không xác định"),
        ("tpe_code", selected.tpe_code or "Không xác định"),
        ("transfer_reason", selected.transfer_reason or "unknown"),
        ("gt4_turn", str(selected.gt4_turn).lower()),
        ("transferred", str(selected.transferred).lower()),
        ("is_weekend_start", str(selected.is_weekend_start).lower()),
        ("week_definition", "mon_sun"),
        ("sort_by", "ticket_id"),
        ("sort_direction", "asc"),
        ("page", "1"),
        ("page_size", "100"),
    ]
    manager = manager_factory(initial=snapshot)
    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/api/tickets", params=params)
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize(
    ("query", "parameter"),
    [
        ("page=" + ("9" * 5000), "page"),
        ("page=1234567890", "page"),
        ("&".join(["page=1"] * 25), "unknown"),
    ],
    ids=("five-thousand-digit-value", "ten-digit-number", "more-pairs-than-allowlisted-names"),
)
def test_ticket_query_resource_bounds_fail_fast_with_sanitized_422(
    manager_factory, query: str, parameter: str
):
    """Unbounded pairs or values permit disproportionate parsing work per request."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(f"/api/tickets?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_query", "parameter": parameter}
    }
    assert "99999999999999999999" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        ("x" * 20000) + "=1",
        "&".join(f"x{index}=1" for index in range(1000)),
        "page=" + ("9" * 20000),
    ],
    ids=("extreme-name", "many-pairs", "oversize-raw-value"),
)
def test_raw_query_bounds_reject_before_query_params_materialization(
    manager_factory, monkeypatch, query: str
):
    """Parsing an unbounded raw query defeats limits applied to parsed values."""
    query_param_accesses: list[str] = []

    def reject_materialization(_request):
        query_param_accesses.append("accessed")
        raise AssertionError("query_params must not be materialized")

    request = StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/tickets",
            "query_string": query.encode("ascii"),
            "headers": [],
        }
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            StarletteRequest,
            "query_params",
            property(reject_materialization),
        )
        parsed, invalid_parameter = _parse_ticket_query(request)

    assert parsed == {}
    assert invalid_parameter == "unknown"
    assert query_param_accesses == []

    manager = manager_factory(initial=_snapshot())
    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get(f"/api/tickets?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_query", "parameter": "unknown"}
    }
    assert "99999999999999999999" not in response.text


def test_refresh_returns_202_and_real_manager_joins_active_refresh(manager_factory):
    """Starting a second forced loader violates the manager's single-flight guarantee."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    initial = _snapshot()
    refreshed = _snapshot(ticket_ids=("400",))

    def loader() -> DashboardSnapshot:
        calls.append("refresh")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return refreshed

    manager = manager_factory(initial=initial, loader=loader)
    try:
        with TestClient(
            create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
        ) as client:
            first = client.post("/api/refresh", headers=REFRESH_ACTION_HEADERS)
            second = client.post("/api/refresh", headers=REFRESH_ACTION_HEADERS)
            assert started.wait(2)
            assert calls == ["refresh"]
            assert first.status_code == second.status_code == 202
            assert first.json() == _state(
                initial, status="refreshing", refreshing=True
            )
            release.set()
            assert manager.wait_for_idle(2) is True
            assert manager.get().snapshot == refreshed
    finally:
        release.set()


@pytest.mark.parametrize("action_value", (None, "", "Refresh", "refresh "))
def test_refresh_requires_exact_custom_action_header_without_starting_loader(
    manager_factory,
    action_value: str | None,
):
    """Accepting a missing or approximate action header leaves the mutation CSRF-able."""
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("refresh")
        return _snapshot(ticket_ids=("400",))

    manager = manager_factory(initial=_snapshot(), loader=loader)
    headers = (
        {}
        if action_value is None
        else {"X-Dashboard-Action": action_value}
    )

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.post("/api/refresh", headers=headers)
        assert manager.wait_for_idle(2) is True

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "refresh_action_required"}}
    assert calls == []


def test_cross_origin_simple_form_post_cannot_start_refresh(manager_factory):
    """A browser form can submit cross-site unless the endpoint requires a custom header."""
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("refresh")
        return _snapshot(ticket_ids=("400",))

    manager = manager_factory(initial=_snapshot(), loader=loader)

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.post(
            "/api/refresh",
            headers={
                "Origin": "https://attacker.invalid",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content="refresh=1",
        )
        assert manager.wait_for_idle(2) is True

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "refresh_action_required"}}
    assert "access-control-allow-origin" not in response.headers
    assert calls == []


def test_health_is_unprotected_liveness_only(manager_factory):
    """Coupling liveness to snapshot state can restart a healthy refreshing process."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))
    ) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_and_readiness_without_snapshot_do_not_start_loader(manager_factory):
    """Reporting ready or refreshing from a probe can route traffic too early."""
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        return _snapshot()

    manager = manager_factory(loader=loader)

    with TestClient(
        create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))
    ) as client:
        health = client.get("/healthz")
        readiness = client.get("/readyz")
        assert manager.wait_for_idle(2) is True

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}
    assert calls == []


def test_readiness_is_unprotected_when_last_good_snapshot_exists(manager_factory):
    """Protecting the probe or requiring a fresh refresh breaks ingress readiness."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER))
    ) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_fastapi_interactive_docs_and_schema_are_not_exposed(manager_factory):
    """Default FastAPI routes disclose the internal endpoint contract without auth."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        responses = [
            client.get("/docs"),
            client.get("/redoc"),
            client.get("/openapi.json"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404]


def test_favicon_is_an_empty_local_response(manager_factory):
    """A browser favicon lookup must not create a noisy failed-resource error."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = client.get("/favicon.ico")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/dashboard"),
        ("get", "/api/tickets"),
        ("post", "/api/refresh"),
        ("get", "/api/tickets?page_size=101"),
    ],
)
def test_every_api_response_disables_caching_and_content_sniffing(
    manager_factory, method: str, path: str
):
    """Missing security headers allows sensitive responses to be cached or sniffed."""
    manager = manager_factory(initial=_snapshot())

    with TestClient(
        create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))
    ) as client:
        response = getattr(client, method)(path)

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers


def test_unexpected_api_error_is_fixed_sanitized_and_has_security_headers(
    manager_factory,
):
    """Letting framework errors escape can expose exception text and omit safe headers."""
    secret = "upstream sk-secret-value for 0901234567"

    def broken_clock():
        raise RuntimeError(secret)

    manager = manager_factory(initial=_snapshot(), clock=broken_clock)
    app = create_app(manager, settings=WebSettings("off", IDENTITY_HEADER))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert secret not in response.text
    assert "sk-secret-value" not in response.text
    assert "0901234567" not in response.text


def test_root_is_authenticated_and_serves_live_page_without_echoing_identity(
    manager_factory,
):
    """Serving the shell without proxy identity or reflecting it weakens deployment."""
    manager = manager_factory(initial=_snapshot())
    # The shipped shell is the SPA; `legacy` pins the inline page this test was
    # originally written against, so the assertion stays about authentication
    # rather than about which frontend happens to be selected.
    app = create_app(manager, settings=WebSettings("proxy", IDENTITY_HEADER, "legacy"))

    with TestClient(app) as client:
        missing = client.get("/")
        authorized = client.get("/", headers={IDENTITY_HEADER: "private-user"})

    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "authentication_required"}}
    assert authorized.status_code == 200
    assert authorized.headers["content-type"].startswith("text/html")
    assert "Hiệu quả CS Agent" in authorized.text
    assert "private-user" not in authorized.text
    assert "sk-secret-value" not in authorized.text


def test_root_serves_without_identity_header_when_platform_gates_at_the_edge(
    manager_factory,
):
    """Basic mode trusts the platform's own HTTP Basic Auth, not an SSO header."""
    manager = manager_factory(initial=_snapshot())
    app = create_app(manager, settings=WebSettings("basic", IDENTITY_HEADER, "legacy"))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Hiệu quả CS Agent" in response.text


def test_web_settings_accepts_basic_mode_with_an_approved_identity_header():
    """Basic mode must still validate identity_header even though it goes unused."""
    settings = WebSettings("basic", IDENTITY_HEADER)

    assert settings.auth_mode == "basic"


@pytest.mark.parametrize(
    ("auth_mode", "identity_header"),
    [
        ("none", IDENTITY_HEADER),
        ("proxy", ""),
        ("proxy", "bad header"),
        ("proxy", "bad\nheader"),
    ],
)
def test_web_settings_reject_unsupported_auth_or_invalid_header_names(
    auth_mode: str, identity_header: str
):
    """Accepting ambiguous authentication configuration can bypass the proxy boundary."""
    with pytest.raises(ValueError):
        WebSettings(auth_mode, identity_header)


@pytest.mark.parametrize(
    "identity_header",
    (
        "Host",
        "host",
        "Cookie",
        "Authorization",
        "User-Agent",
        "X-Dashboard-Action",
        "Accept",
        "Content-Type",
        "Connection",
        "Origin",
        "Referer",
        "X-Forwarded-For",
    ),
)
def test_web_settings_reject_headers_with_ambient_or_conflicting_values(
    identity_header: str,
):
    """Using an ambient request header as identity makes ordinary clients authenticated."""
    with pytest.raises(ValueError, match="identity_header"):
        WebSettings("proxy", identity_header)


def test_help_exits_before_loading_environment(monkeypatch, capsys):
    """Loading dotenv for help can make an offline introspection command fail."""
    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: pytest.fail("help must not load environment"),
    )

    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    assert "--local" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "environment", "message"),
    [
        (
            ["--local", "--host", "0.0.0.0"],
            {},
            "local mode requires a loopback host",
        ),
        (
            [],
            {"DASHBOARD_AUTH_MODE": "off"},
            "production requires DASHBOARD_AUTH_MODE=proxy or basic",
        ),
    ],
)
def test_main_rejects_unsafe_binding_before_langfuse_environment(
    monkeypatch, capsys, argv, environment, message
):
    for name in (
        "DASHBOARD_AUTH_MODE",
        "DASHBOARD_IDENTITY_HEADER",
        "DASHBOARD_RUNTIME_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: pytest.fail("unsafe configuration must fail before Langfuse setup"),
    )

    exit_code = main(argv)

    assert exit_code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == message + "\n"


def test_runtime_directory_rejects_sensitive_and_relative_paths_without_echo():
    """A broad or relative cache target can overwrite unrelated application data."""
    static_directory = Path(__file__).parents[1] / "src" / "weekly_cs_report" / "static"
    unsafe_paths = (
        Path("/"),
        Path.home(),
        PROJECT_ROOT.parent,
        PROJECT_ROOT,
        static_directory,
        static_directory / "nested",
        Path("relative-runtime"),
    )

    for unsafe in unsafe_paths:
        with pytest.raises(ConfigurationError) as error:
            _validated_runtime_directory(unsafe)

        assert str(error.value) == "dashboard runtime directory is unsafe"
        assert str(unsafe) not in str(error.value)


def test_runtime_directory_rejects_symlinks_files_modes_and_unrelated_contents(
    tmp_path: Path,
):
    """Following links or reusing a permissive/non-dedicated target exposes other files."""
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    target_link = tmp_path / "target-link"
    target_link.symlink_to(real_parent, target_is_directory=True)
    regular_file = tmp_path / "regular-file"
    regular_file.write_text("not a directory", encoding="utf-8")
    permissive = tmp_path / "permissive"
    permissive.mkdir(mode=0o755)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)
    (unrelated / "customer-export.csv").write_text("secret", encoding="utf-8")

    for unsafe in (
        linked_parent / "runtime",
        target_link,
        regular_file,
        permissive,
        unrelated,
    ):
        with pytest.raises(ConfigurationError) as error:
            _validated_runtime_directory(unsafe)

        assert str(error.value) == "dashboard runtime directory is unsafe"
        assert str(unsafe) not in str(error.value)


def test_runtime_directory_rejects_attacker_swappable_parent(
    tmp_path: Path,
):
    """A mode-700 target is still replaceable when its parent is attacker-writable."""
    shared_parent = tmp_path / "shared"
    shared_parent.mkdir(mode=0o777)
    shared_parent.chmod(0o777)
    runtime = shared_parent / "runtime"
    runtime.mkdir(mode=0o700)

    with pytest.raises(ConfigurationError) as error:
        _validated_runtime_directory(runtime)

    assert str(error.value) == "dashboard runtime directory is unsafe"
    assert str(runtime) not in str(error.value)


def test_runtime_directory_allows_absent_default_and_dedicated_private_cache(
    tmp_path: Path, monkeypatch
):
    """Validation must create a private default and permit known cache files."""
    fake_project = tmp_path / "project"
    fake_project.mkdir(mode=0o755)
    monkeypatch.setattr("weekly_cs_report.web.PROJECT_ROOT", fake_project)
    default_runtime = fake_project / "runtime"
    dedicated = tmp_path / "dedicated"
    dedicated.mkdir(mode=0o700)
    (dedicated / "dashboard_snapshot.json").write_text("{}", encoding="utf-8")
    (dedicated / ".dashboard_snapshot.recovery.tmp").write_text(
        "{}", encoding="utf-8"
    )
    (dedicated / "csat_cache.json").write_text("{}", encoding="utf-8")
    (dedicated / "outcome_reconciliation_cache.json").write_text(
        "{}", encoding="utf-8"
    )
    (dedicated / "dashboard_snapshot.json").chmod(0o600)
    (dedicated / ".dashboard_snapshot.recovery.tmp").chmod(0o600)
    (dedicated / "csat_cache.json").chmod(0o600)
    (dedicated / "outcome_reconciliation_cache.json").chmod(0o600)

    assert _validated_runtime_directory(default_runtime) == default_runtime
    assert default_runtime.is_dir()
    assert default_runtime.stat().st_mode & 0o777 == 0o700
    assert _validated_runtime_directory(dedicated) == dedicated


def test_runtime_directory_allows_freshdesk_cookie_files(tmp_path: Path):
    """The cookie-transport dialog (spec 2026-08-12) writes these two files
    directly into the runtime directory; a redeploy must not crash-loop
    because the allowlist doesn't know about them yet."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    cookie = runtime / "freshdesk_cookie"
    cookie.write_text("cs_session=abc123", encoding="utf-8")
    cookie.chmod(0o600)
    state = runtime / "freshdesk_cookie_state.json"
    state.write_text('{"state":"ok"}', encoding="utf-8")
    state.chmod(0o600)

    assert _validated_runtime_directory(runtime) == runtime


def test_runtime_directory_rejects_permissive_or_linked_csat_cache(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    cache = runtime / "csat_cache.json"
    cache.write_text("{}", encoding="utf-8")
    cache.chmod(0o640)

    with pytest.raises(ConfigurationError, match="runtime directory is unsafe"):
        _validated_runtime_directory(runtime)

    cache.unlink()
    target = tmp_path / "private-cache.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    cache.symlink_to(target)
    with pytest.raises(ConfigurationError, match="runtime directory is unsafe"):
        _validated_runtime_directory(runtime)


def test_runtime_directory_rejects_retired_dimension_backfill_filename(
    tmp_path: Path,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    backfill = runtime / "dimension_backfill.json"
    backfill.write_text("{}", encoding="utf-8")
    backfill.chmod(0o600)

    with pytest.raises(ConfigurationError) as error:
        _validated_runtime_directory(runtime)
    assert str(error.value) == "dashboard runtime directory is unsafe"


def test_runtime_directory_rejects_permissive_existing_snapshot(
    tmp_path: Path,
):
    """Accepting a readable persisted snapshot exposes browser-approved ticket data."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    snapshot = runtime / "dashboard_snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")
    snapshot.chmod(0o640)

    with pytest.raises(ConfigurationError) as error:
        _validated_runtime_directory(runtime)

    assert str(error.value) == "dashboard runtime directory is unsafe"
    assert str(snapshot) not in str(error.value)


def test_main_closes_client_when_snapshot_manager_construction_fails(
    tmp_path: Path, monkeypatch
):
    """A cache-construction failure after client creation must not leak the HTTP client."""
    clients: list[FakeClient] = []

    class FakeClient:
        def __init__(self, *_args):
            self.close_calls = 0
            clients.append(self)

        def close(self):
            self.close_calls += 1

    def fail_manager(*_args, **_kwargs):
        raise RuntimeError("manager construction failed")

    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.web.LangfuseClient", FakeClient)
    monkeypatch.setattr("weekly_cs_report.web.SnapshotManager", fail_manager)
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_RUNTIME_DIR", str(tmp_path / "runtime"))

    with pytest.raises(RuntimeError, match="manager construction failed"):
        main([])

    assert len(clients) == 1
    assert clients[0].close_calls == 1


def test_main_closes_client_when_timezone_construction_fails(
    tmp_path: Path, monkeypatch
):
    """Timezone setup is fallible and must be inside client cleanup ownership."""
    clients: list[FakeClient] = []

    class FakeClient:
        def __init__(self, *_args):
            self.close_calls = 0
            clients.append(self)

        def close(self):
            self.close_calls += 1

    def fail_timezone(_name):
        raise RuntimeError("timezone database unavailable")

    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.web.LangfuseClient", FakeClient)
    monkeypatch.setattr("weekly_cs_report.web.ZoneInfo", fail_timezone)
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_RUNTIME_DIR", str(tmp_path / "runtime"))

    with pytest.raises(RuntimeError, match="timezone database unavailable"):
        main([])

    assert len(clients) == 1
    assert clients[0].close_calls == 1


def test_main_closes_manager_and_client_when_app_construction_fails(
    tmp_path: Path, monkeypatch
):
    """An app-construction failure must release both resources created before it."""
    clients: list[FakeClient] = []
    managers: list[FakeManager] = []

    class FakeClient:
        def __init__(self, *_args):
            self.close_calls = 0
            clients.append(self)

        def close(self):
            self.close_calls += 1

    class FakeManager:
        def __init__(self, *_args, **_kwargs):
            self.close_calls = 0
            managers.append(self)

        def close(self):
            self.close_calls += 1

    def fail_app(*_args, **_kwargs):
        raise RuntimeError("app construction failed")

    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.web.LangfuseClient", FakeClient)
    monkeypatch.setattr("weekly_cs_report.web.SnapshotManager", FakeManager)
    monkeypatch.setattr("weekly_cs_report.web.create_app", fail_app)
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_RUNTIME_DIR", str(tmp_path / "runtime"))

    with pytest.raises(RuntimeError, match="app construction failed"):
        main([])

    assert len(clients) == len(managers) == 1
    assert clients[0].close_calls == 1
    assert managers[0].close_calls == 1


def test_main_composes_fresh_vietnam_time_loader_and_one_worker(
    tmp_path, monkeypatch
):
    clients: list[FakeLangfuseClient] = []
    report_calls: list[dict[str, object]] = []
    uvicorn_calls: list[dict[str, object]] = []

    class FakeLangfuseClient:
        def __init__(self, base_url, public_key, secret_key):
            self.arguments = (base_url, public_key, secret_key)
            self.close_calls = 0
            clients.append(self)

        def close(self):
            self.close_calls += 1

    def fake_compute_report(client, **kwargs):
        report_calls.append({"client": client, **kwargs})
        return object()

    def fake_uvicorn_run(app, **kwargs):
        uvicorn_calls.append({"app": app, **kwargs})
        with TestClient(app) as browser:
            first = browser.get(
                "/api/dashboard", headers={IDENTITY_HEADER: "authorized-user"}
            )
            assert first.status_code == 202
            assert app.state.snapshot_manager.wait_for_idle(2)
            second = browser.post(
                "/api/refresh",
                headers={
                    IDENTITY_HEADER: "authorized-user",
                    **REFRESH_ACTION_HEADERS,
                },
            )
            assert second.status_code == 202
            assert app.state.snapshot_manager.wait_for_idle(2)

    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr(
        "weekly_cs_report.web.LangfuseClient", FakeLangfuseClient
    )
    monkeypatch.setattr(
        "weekly_cs_report.web.compute_report", fake_compute_report
    )
    monkeypatch.setattr(
        "weekly_cs_report.web.project_dashboard",
        lambda _run, **_kwargs: _snapshot(),
    )
    monkeypatch.setattr("weekly_cs_report.web.uvicorn.run", fake_uvicorn_run)
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_IDENTITY_HEADER", IDENTITY_HEADER)
    monkeypatch.setenv("DASHBOARD_RUNTIME_DIR", str(tmp_path / "runtime"))

    exit_code = main([])

    assert exit_code == 0
    assert len(clients) == 1
    assert clients[0].arguments == (TARGET_BASE_URL, "pk-test", "sk-test")
    assert clients[0].close_calls == 1
    assert len(report_calls) == 1
    assert all(call["client"] is clients[0] for call in report_calls)
    assert all(call["weeks"] == 12 for call in report_calls)
    assert all(call["include_current_wtd"] is True for call in report_calls)
    assert all(
        str(call["taxonomy_path"]).endswith("config/taxonomy.v2.json")
        for call in report_calls
    )
    assert all(
        call["as_of"].tzinfo is not None
        and getattr(call["as_of"].tzinfo, "key", None) == "Asia/Ho_Chi_Minh"
        for call in report_calls
    )
    assert all(call.get("refresh_timeout_seconds") == 120.0 for call in report_calls)
    assert all(call.get("max_trace_pages") == 500 for call in report_calls)
    assert all(
        isinstance(call.get("cancel_event"), threading.Event)
        for call in report_calls
    )
    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["host"] == "0.0.0.0"
    assert uvicorn_calls[0]["port"] == 8080
    assert uvicorn_calls[0]["workers"] == 1
    assert uvicorn_calls[0]["access_log"] is False
    assert uvicorn_calls[0]["timeout_graceful_shutdown"] == 45


def test_main_forwards_in_range_refresh_control_overrides(tmp_path, monkeypatch):
    """Production startup must apply valid non-default refresh controls."""
    report_calls: list[dict[str, object]] = []

    class FakeLangfuseClient:
        def __init__(self, *_args):
            pass

        def close(self):
            pass

    def fake_compute_report(_client, **kwargs):
        report_calls.append(kwargs)
        return object()

    def fake_uvicorn_run(app, **_kwargs):
        with TestClient(app) as browser:
            assert browser.get(
                "/api/dashboard",
                headers={IDENTITY_HEADER: "authorized-user"},
            ).status_code == 202
            assert app.state.snapshot_manager.wait_for_idle(2)

    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.web.LangfuseClient", FakeLangfuseClient)
    monkeypatch.setattr("weekly_cs_report.web.compute_report", fake_compute_report)
    monkeypatch.setattr(
        "weekly_cs_report.web.project_dashboard",
        lambda _run, **_kwargs: _snapshot(),
    )
    monkeypatch.setattr("weekly_cs_report.web.uvicorn.run", fake_uvicorn_run)
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_IDENTITY_HEADER", IDENTITY_HEADER)
    monkeypatch.setenv("DASHBOARD_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DASHBOARD_REFRESH_DEADLINE_SECONDS", "30")
    monkeypatch.setenv("DASHBOARD_MAX_TRACE_PAGES", "7")

    assert main([]) == 0
    assert len(report_calls) == 1
    assert report_calls[0]["refresh_timeout_seconds"] == 30.0
    assert report_calls[0]["max_trace_pages"] == 7


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "DASHBOARD_REFRESH_DEADLINE_SECONDS",
            "29",
            "DASHBOARD_REFRESH_DEADLINE_SECONDS must be between 30 and 300",
        ),
        (
            "DASHBOARD_REFRESH_DEADLINE_SECONDS",
            "301",
            "DASHBOARD_REFRESH_DEADLINE_SECONDS must be between 30 and 300",
        ),
        (
            "DASHBOARD_MAX_TRACE_PAGES",
            "0",
            "DASHBOARD_MAX_TRACE_PAGES must be an integer between 1 and 500",
        ),
        (
            "DASHBOARD_MAX_TRACE_PAGES",
            "501",
            "DASHBOARD_MAX_TRACE_PAGES must be an integer between 1 and 500",
        ),
    ],
)
def test_main_rejects_out_of_range_refresh_controls_before_loading_secrets(
    monkeypatch, capsys, name: str, value: str, message: str,
):
    """Invalid refresh settings must fail startup without reading any credentials."""
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.setenv("DASHBOARD_FRONTEND_MODE", "legacy")
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: pytest.fail("startup read credentials after invalid refresh setting"),
    )

    assert main([]) == 2
    assert capsys.readouterr().err == f"{message}\n"


def _cookie_app(tmp_path: Path):
    runtime = tmp_path / "runtime"
    store = ProtectedSnapshotStore(runtime)
    manager = SnapshotManager(lambda: _snapshot(), store, clock=lambda: NOW)
    app = create_app(
        manager,
        settings=WebSettings("off", IDENTITY_HEADER),
        runtime_directory=runtime,
    )
    return app, runtime


def test_freshdesk_cookie_get_returns_missing_when_unconfigured(tmp_path: Path):
    app, _runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/freshdesk-cookie")

    assert response.status_code == 200
    assert response.json() == {
        "state": "missing",
        "updated_at": None,
        "last_verified_at": None,
    }


def test_freshdesk_cookie_post_requires_action_header(tmp_path: Path):
    app, _runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/freshdesk-cookie", json={"cookie": "cs_session=abc"}
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "cookie_action_required"}}


def test_freshdesk_cookie_post_rejects_blank_cookie(tmp_path: Path):
    app, runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/freshdesk-cookie",
            headers=COOKIE_ACTION_HEADERS,
            json={"cookie": "   "},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "cookie_invalid"}}
    assert not (runtime / "freshdesk_cookie").exists()


def test_freshdesk_cookie_post_rejects_oversized_body(tmp_path: Path):
    app, runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/freshdesk-cookie",
            headers=COOKIE_ACTION_HEADERS,
            content=json.dumps({"cookie": "x" * 9000}),
        )

    assert response.status_code == 413
    assert not (runtime / "freshdesk_cookie").exists()


def test_freshdesk_cookie_post_never_writes_a_cookie_that_fails_live_verification(
    tmp_path: Path, monkeypatch
):
    class RejectingClient:
        def __init__(self, _cookie):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify(self):
            from weekly_cs_report.freshdesk_csat import FreshdeskCookieExpired

            raise FreshdeskCookieExpired("stale")

    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskUIClient", RejectingClient
    )
    app, runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/freshdesk-cookie",
            headers=COOKIE_ACTION_HEADERS,
            json={"cookie": "cs_session=stale-value"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "cookie_invalid"}}
    assert not (runtime / "freshdesk_cookie").exists()
    assert "stale-value" not in json.dumps(response.json())


def test_freshdesk_cookie_post_persists_and_verifies_a_valid_cookie(
    tmp_path: Path, monkeypatch
):
    class AcceptingClient:
        def __init__(self, cookie):
            self.cookie = cookie

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify(self):
            return None

    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskUIClient", AcceptingClient
    )
    app, runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/freshdesk-cookie",
            headers=COOKIE_ACTION_HEADERS,
            json={"cookie": "cs_session=fresh-value"},
        )
        assert response.status_code == 202
        assert response.json()["state"] == "ok"
        assert "fresh-value" not in json.dumps(response.json())

        get_response = client.get("/api/freshdesk-cookie")
        assert get_response.json()["state"] == "ok"
        assert get_response.json()["last_verified_at"] is not None

    saved = runtime / "freshdesk_cookie"
    assert saved.read_text(encoding="utf-8") == "cs_session=fresh-value"
    import stat as _stat

    assert _stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_freshdesk_cookie_post_is_rate_limited(tmp_path: Path, monkeypatch):
    class RejectingClient:
        def __init__(self, _cookie):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify(self):
            from weekly_cs_report.freshdesk_csat import FreshdeskCookieExpired

            raise FreshdeskCookieExpired("stale")

    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskUIClient", RejectingClient
    )
    app, _runtime = _cookie_app(tmp_path)
    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/freshdesk-cookie",
                headers=COOKIE_ACTION_HEADERS,
                json={"cookie": "cs_session=abc"},
            ).status_code
            for _ in range(6)
        ]

    assert statuses[:5] == [400, 400, 400, 400, 400]
    assert statuses[5] == 429
