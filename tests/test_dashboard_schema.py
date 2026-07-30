from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

import pytest

from tests.fixtures.traces import TRANSFER_HTML, TRANSFER_TEXT, trace
from weekly_cs_report.dashboard_schema import DashboardSnapshot, TicketRow, project_dashboard, ticket_page
from weekly_cs_report.report import compute_report


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


class FakeClient:
    def __init__(self, traces: list[dict]) -> None:
        self.traces = traces
        self.observation_calls: list[str] = []

    def iter_traces(self, _from: datetime, _to: datetime):
        yield from self.traces

    def list_observations(self, trace_id: str) -> list[dict]:
        self.observation_calls.append(trace_id)
        return []


def _run(traces: list[dict], *, as_of: datetime = AS_OF):
    return compute_report(
        FakeClient(traces), as_of=as_of, weeks=2, include_current_wtd=True,
        taxonomy_path=TAXONOMY_V2_PATH,
    )


def _meta(raw: dict, *, category: str = "Thanh toán-IBFT", app: str = "241 - Chuyển Tiền ATM", product: str = "TF007 - IBFT", entry: str = "tranxdetail", tpe: str = "-217 Thất bại") -> dict:
    raw["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": category, "sub_source": entry},
        "App": app, "Product Code": product, "Mã lỗi TPE": tpe,
        "Step result": "-1|20|700212|mô tả tuyệt đối không được xuất",
    }
    return raw


def _snapshot() -> DashboardSnapshot:
    monday = _meta(trace("ai", "145665", 0, "2026-07-20T02:00:00Z", "AI reply"))
    # Saturday Vietnam: only mon_sun includes this row.
    weekend = _meta(trace("weekend", "145666", 3, "2026-07-24T18:00:00Z", "AI reply"))
    transfer = _meta(trace("transfer", "145667", 0, "2026-07-22T02:00:00Z", TRANSFER_HTML))
    return project_dashboard(_run([monday, weekend, transfer]))


def test_v3_has_exact_top_level_contract_and_22_ticket_allowlist():
    snapshot = _snapshot()
    dashboard = snapshot.dashboard_dict()

    assert set(dashboard) == {
        "generated_at", "source", "enrichment_status", "data_range", "views",
        "coverage", "unmapped_tpe_codes", "gate_status", "data_quality",
    }
    assert dashboard["source"]["observations_fetched"] == 0
    assert dashboard["enrichment_status"] == "partial"
    assert set(asdict(snapshot.tickets[0])) == {
        "ticket_id", "cohort_week", "cohort_status", "is_weekend_start", "outcome",
        "ai_first", "transferred", "reopen_lifetime", "reopen_within_7d",
        "ai_reply_count", "turn_count", "gt4_turn", "issue_category", "app",
        "product_code", "skill", "intent", "tpe_code", "tpe_status",
        "guardrail_rule", "escalation_guard_blocked", "data_quality",
    }
    assert "mô tả tuyệt đối" not in json.dumps(snapshot.storage_dict(), ensure_ascii=False)


def test_v3_dual_views_are_closed_and_mon_fri_excludes_only_weekend_starts():
    dashboard = _snapshot().dashboard_dict()
    mon_sun = dashboard["views"]["mon_sun"]
    mon_fri = dashboard["views"]["mon_fri"]

    assert mon_sun["totals"]["eligible_ticket_count"] == 3
    assert mon_fri["totals"]["eligible_ticket_count"] == 2
    assert mon_fri["totals"]["eligible_ticket_count"] + mon_sun["totals"]["weekend_start_count"] == mon_sun["totals"]["eligible_ticket_count"]
    for view in (mon_sun, mon_fri):
        assert sum(view["outcomes"].values()) == view["totals"]["eligible_ticket_count"]
        assert view["ai_first"]["count"] == view["outcomes"]["ai_end_to_end"] + view["outcomes"]["ai_then_cs"]
        assert view["totals"]["transfer_total"] == view["outcomes"]["ai_then_cs"] + view["outcomes"]["direct_cs"]
        assert view["rule_gt4"]["gt4_turn_total"] == view["rule_gt4"]["gt4_turn_with_cs"] + view["rule_gt4"]["gt4_turn_without_cs"]
        assert sum(row["total_tickets"] for row in view["weekly"]) == view["totals"]["eligible_ticket_count"]
        assert set(view["by_week"]) == {
            row["cohort_week"] for row in view["weekly"]
        }
        assert set(view["segments"]) == {"issue_category", "app", "product_code", "skill", "intent", "tpe", "guardrail_rule", "entry_point"}
        for buckets in view["segments"].values():
            assert "Không xác định" in buckets
            assert sum(bucket["total"] for bucket in buckets.values()) == view["totals"]["eligible_ticket_count"]
        for row in view["weekly"]:
            weekly_detail = view["by_week"][row["cohort_week"]]
            for buckets in weekly_detail["segments"].values():
                assert "Không xác định" in buckets
                assert sum(bucket["total"] for bucket in buckets.values()) == row["total_tickets"]
            assert (
                weekly_detail["transfer_reasons"]["observed_transfer_denominator"]
                == sum(
                    bucket["transferred"]
                    for bucket in weekly_detail["segments"]["issue_category"].values()
                )
            )


def test_transfer_reasons_keep_exact_tpe_grain_and_distinct_guardrails_without_causal_top_reason():
    traces = [
        _meta(
            trace("first-a", "145665", 0, "2026-07-21T02:00:00Z", TRANSFER_HTML),
            tpe="-217 Thất bại",
        ),
        _meta(
            trace("first-b", "145666", 0, "2026-07-21T03:00:00Z", TRANSFER_HTML),
            tpe="-217 Đang xử lý",
        ),
        _meta(
            trace("first-c", "145667", 0, "2026-07-21T04:00:00Z", TRANSFER_HTML),
            tpe="-383 Đang xử lý",
        ),
        _meta(
            trace("first-d", "145668", 0, "2026-07-21T05:00:00Z", TRANSFER_HTML),
            tpe="",
        ),
    ]
    run = _run(traces)
    enriched = []
    for session in run.result.sessions:
        if session.session_id == "145665":
            enriched.append(
                replace(
                    session,
                    guardrail_rules=("missing_transaction_id", "off_topic"),
                )
            )
        elif session.session_id == "145666":
            enriched.append(
                replace(
                    session,
                    dimensions=replace(
                        session.dimensions,
                        escalation_guard_blocked=True,
                    ),
                    guardrail_rules=("missing_transaction_id",),
                )
            )
        else:
            enriched.append(session)
    run = replace(run, result=replace(run.result, sessions=tuple(enriched)))

    view = project_dashboard(run).dashboard_dict()["views"]["mon_sun"]
    reasons = view["transfer_reasons"]

    assert reasons == {
        "observed_transfer_denominator": 4,
        "tpe": [
            {
                "code": "-217",
                "status": "Thất bại",
                "case": None,
                "mapped": False,
                "count": 1,
            },
            {
                "code": "-217",
                "status": "Đang xử lý",
                "case": None,
                "mapped": False,
                "count": 1,
            },
            {
                "code": "-383",
                "status": "Đang xử lý",
                "case": 2,
                "mapped": True,
                "count": 1,
            },
        ],
        "guardrail": [
            {"rule": "missing_transaction_id", "count": 2},
            {"rule": "off_topic", "count": 1},
        ],
        "escalation_guard_blocked": {"count": 1, "denominator": 4},
    }
    assert "top_reason" not in reasons
    week_reasons = view["by_week"]["2026-07-20"]["transfer_reasons"]
    assert week_reasons == reasons
    empty_week = view["by_week"]["2026-07-13"]
    assert empty_week["transfer_reasons"] == {
        "observed_transfer_denominator": 0,
        "tpe": [],
        "guardrail": [],
        "escalation_guard_blocked": {"count": 0, "denominator": 0},
    }
    assert all(
        buckets == {
            "Không xác định": {
                "total": 0,
                "ai_first": 0,
                "transferred": 0,
                "reopen": 0,
            }
        }
        for buckets in empty_week["segments"].values()
    )


def test_guardrail_reason_counts_are_overlapping_not_a_partition():
    traces = [
        _meta(
            trace(f"transfer-{index}", str(145665 + index), 0, f"2026-07-21T0{index + 2}:00:00Z", TRANSFER_HTML)
        )
        for index in range(2)
    ]
    run = _run(traces)
    sessions = tuple(
        replace(
            session,
            guardrail_rules=("missing_transaction_id", "off_topic"),
        )
        for session in run.result.sessions
    )
    reasons = project_dashboard(
        replace(run, result=replace(run.result, sessions=sessions))
    ).dashboard_dict()["views"]["mon_sun"]["transfer_reasons"]

    assert reasons["observed_transfer_denominator"] == 2
    assert reasons["guardrail"] == [
        {"rule": "missing_transaction_id", "count": 2},
        {"rule": "off_topic", "count": 2},
    ]
    assert sum(row["count"] for row in reasons["guardrail"]) == 4


def test_by_week_intents_are_revalidated_against_global_frequency():
    value = _snapshot().storage_dict()
    detail = value["dashboard"]["views"]["mon_sun"]["by_week"]["2026-07-20"]
    detail["segments"]["intent"]["rare_intent"] = {
        "total": 0,
        "ai_first": 0,
        "transferred": 0,
        "reopen": 0,
    }

    with pytest.raises(ValueError, match="intent"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_transfer_reason_denominator_drift_from_segments():
    value = _snapshot().storage_dict()
    reasons = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]
    reasons["observed_transfer_denominator"] += 1

    with pytest.raises(ValueError, match="denominator does not reconcile"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_transfer_reason_tpe_contract_drift_and_pii():
    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["case"] = 1
    row["mapped"] = False

    with pytest.raises(ValueError, match="mapped is invalid"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["status"] = "gọi 0901234567"
    with pytest.raises(ValueError, match="status"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_transfer_reason_weekly_rollup_drift_and_new_fields():
    value = _snapshot().storage_dict()
    view = value["dashboard"]["views"]["mon_sun"]
    view["by_week"]["2026-07-20"]["transfer_reasons"]["tpe"] = []

    with pytest.raises(ValueError, match="weekly rows do not reconcile"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["top_reason"] = {
        "kind": "tpe"
    }
    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_segment_weekly_rollup_drift_even_when_closure_holds():
    value = _snapshot().storage_dict()
    buckets = value["dashboard"]["views"]["mon_sun"]["by_week"]["2026-07-20"][
        "segments"
    ]["issue_category"]
    buckets["Thanh toán-IBFT"]["total"] -= 1
    buckets["Thanh toán-IBFT"]["ai_first"] -= 1
    buckets["Khác"] = {
        "total": 1,
        "ai_first": 1,
        "transferred": 0,
        "reopen": 0,
    }

    with pytest.raises(ValueError, match="segment weekly rows do not reconcile"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_weekly_rule_rollup_drift():
    value = _snapshot().storage_dict()
    active_week = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    active_week["max_replies_rule_fired"] += 1

    with pytest.raises(ValueError, match="weekly rule_gt4 does not reconcile"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_reopen_count_and_displayed_rate_drift():
    value = _snapshot().storage_dict()
    value["dashboard"]["views"]["mon_sun"]["ai_first"]["rate"] = 0.5
    with pytest.raises(ValueError, match="ai_first rate does not match"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    lifetime = value["dashboard"]["views"]["mon_sun"]["reopen"]["lifetime"]
    lifetime["numerator"] = lifetime["denominator"] + 1
    with pytest.raises(ValueError, match="reopen numerator exceeds denominator"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    active_week = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    active_week["reopen_lifetime_rate"] = 0.5
    with pytest.raises(ValueError, match="reopen_lifetime_rate does not match"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    active_week = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    active_week["reopen_lifetime_numerator"] = 1
    active_week["reopen_lifetime_rate"] = 0.5
    with pytest.raises(ValueError, match="weekly lifetime does not reconcile"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    empty_mature_week = value["dashboard"]["views"]["mon_sun"]["weekly"][0]
    empty_mature_week["reopen_7d_rate"] = 0.5
    with pytest.raises(ValueError, match="reopen_7d_rate does not match"):
        DashboardSnapshot.from_storage_dict(value)


def test_mature_week_has_distinct_reopen_7d_semantics_per_view_boundary():
    as_of = datetime(2026, 7, 25, 12, tzinfo=VIETNAM)
    item = _meta(trace("ai", "145665", 0, "2026-07-13T02:00:00Z", "AI reply"))
    snapshot = project_dashboard(_run([item], as_of=as_of)).dashboard_dict()
    sun = next(row for row in snapshot["views"]["mon_sun"]["weekly"] if row["cohort_week"] == "2026-07-13")
    fri = next(row for row in snapshot["views"]["mon_fri"]["weekly"] if row["cohort_week"] == "2026-07-13")

    # Monday-to-Sunday needs seven days after Sunday; Monday-to-Friday matures
    # two days earlier.  At 25 Jul noon only the latter is eligible.
    assert sun["reopen_7d_rate"] is None
    assert sun["reopen_7d_denominator"] is None
    assert fri["reopen_7d_denominator"] is not None


def test_projection_is_allowlisted_and_never_serializes_pii_or_trace_id():
    unsafe = _meta(trace("internal-trace-id", "145665", 0, "2026-07-21T02:00:00Z", "model response"))
    unsafe["input"].update({"phone": "0901234567", "user_id": "user-secret", "trans_id": "trans-secret"})
    encoded = json.dumps(project_dashboard(_run([unsafe])).storage_dict(), ensure_ascii=False)
    for forbidden in ("internal-trace-id", "0901234567", "user-secret", "trans-secret", "model response"):
        assert forbidden not in encoded


def test_phone_shaped_numeric_session_id_is_not_exposed_as_a_ticket_id():
    unsafe_id = "8490123456"
    unsafe = _meta(
        trace(
            "internal-trace-id",
            unsafe_id,
            0,
            "2026-07-21T02:00:00Z",
            "AI reply",
        )
    )

    snapshot = project_dashboard(_run([unsafe]))
    encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)

    assert snapshot.tickets == ()
    assert unsafe_id not in encoded
    with pytest.raises(ValueError, match="ticket_id is invalid"):
        ticket_page(snapshot, ticket_id=unsafe_id)


def test_pii_shaped_meta_values_are_replaced_by_missing_bucket_before_browser_projection():
    unsafe = _meta(
        trace("internal-trace-id", "145665", 0, "2026-07-21T02:00:00Z", "AI reply"),
        category="Nguyễn Văn An", app="person@example.com", product="123456789",
    )
    snapshot = project_dashboard(_run([unsafe]))
    row = snapshot.tickets[0]
    assert (row.issue_category, row.app, row.product_code) == ("Không xác định", "Không xác định", "Không xác định")
    encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)
    for forbidden in ("Nguyễn Văn An", "person@example.com", "123456789"):
        assert forbidden not in encoded


def test_unmapped_tpe_is_passthrough_without_unknown_keyword_bucket():
    dashboard = _snapshot().dashboard_dict()
    assert dashboard["unmapped_tpe_codes"] == [{"code": "-217", "status": "Thất bại", "count": 3}]
    assert "unknown" not in json.dumps(dashboard, ensure_ascii=False).casefold()


def test_ticket_page_filters_all_p5_dimensions_at_ticket_grain_and_preserves_22_fields():
    snapshot = _snapshot()
    page = ticket_page(snapshot, cohort_week="2026-07-20", page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert set(page["items"][0]) == set(asdict(snapshot.tickets[0]))
    with pytest.raises(ValueError, match="ticket_id is invalid"):
        ticket_page(snapshot, ticket_id="internal-trace-id")
    assert ticket_page(snapshot, issue_category="Thanh toán-IBFT")["total"] == 3
    assert ticket_page(snapshot, app="241 - Chuyển Tiền ATM")["total"] == 3
    assert ticket_page(snapshot, product_code="TF007 - IBFT")["total"] == 3
    assert ticket_page(snapshot, tpe_code="-217")["total"] == 3
    assert ticket_page(snapshot, skill="Không xác định")["total"] == 3
    assert ticket_page(snapshot, intent="Không xác định")["total"] == 3
    assert ticket_page(snapshot, is_weekend_start=True)["total"] == 1
    assert ticket_page(snapshot, week_definition="mon_fri")["total"] == 2
    selected = snapshot.tickets[0]
    intersection = ticket_page(
        snapshot,
        cohort_week=selected.cohort_week,
        outcome=selected.outcome,
        ticket_id=selected.ticket_id,
        issue_category=selected.issue_category,
        app=selected.app,
        product_code=selected.product_code,
        skill=selected.skill or "Không xác định",
        intent=selected.intent or "Không xác định",
        tpe_code=selected.tpe_code or "Không xác định",
        gt4_turn=selected.gt4_turn,
        transferred=selected.transferred,
        is_weekend_start=selected.is_weekend_start,
        week_definition="mon_sun",
        page=1,
        page_size=100,
    )
    assert intersection["total"] == 1
    assert intersection["items"][0]["ticket_id"] == selected.ticket_id
    with pytest.raises(ValueError, match="app is invalid"):
        ticket_page(snapshot, app="person@example.com")
    with pytest.raises(ValueError, match="transferred is invalid"):
        ticket_page(snapshot, transferred="true")  # type: ignore[arg-type]


def test_storage_rejects_phone_in_a_new_dimension_field_and_schema_v2():
    value = _snapshot().storage_dict()
    value["tickets"][0]["issue_category"] = "gọi 0901234567"
    with pytest.raises(ValueError):
        DashboardSnapshot.from_storage_dict(value)
    value = _snapshot().storage_dict()
    value["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported dashboard storage schema_version"):
        DashboardSnapshot.from_storage_dict(value)


def test_ticket_row_reopen_is_binary_and_gt4_is_cross_field_checked():
    fields = asdict(_snapshot().tickets[0])
    fields["reopen_lifetime"] = 2
    with pytest.raises(ValueError, match="reopen_lifetime"):
        TicketRow(**fields)
    fields = asdict(_snapshot().tickets[0])
    fields["turn_count"] = 5
    fields["gt4_turn"] = False
    with pytest.raises(ValueError, match="gt4_turn"):
        TicketRow(**fields)


def test_weekly_ai_mean_excludes_direct_cs_and_gt4_uses_strictly_more_than_four():
    four = [_meta(trace(f"four-{turn}", "145665", turn, f"2026-07-21T0{turn}:00:00Z", "AI reply")) for turn in range(4)]
    five = [_meta(trace(f"five-{turn}", "145666", turn, f"2026-07-22T0{turn}:00:00Z", "AI reply")) for turn in range(5)]
    direct = [_meta(trace("direct", "145667", 0, "2026-07-23T02:00:00Z", TRANSFER_TEXT))]
    view = project_dashboard(_run([*four, *five, *direct])).dashboard_dict()["views"]["mon_sun"]
    week = next(row for row in view["weekly"] if row["cohort_week"] == "2026-07-20")

    assert week["ai_reply_mean_ai_first"] == pytest.approx((4 + 5) / 2)
    assert week["gt4_turn_with_cs"] == 0
    assert week["gt4_turn_without_cs"] == 1


def _snapshot_with_intents(
    values: list[str | None],
    *,
    session_ids: list[str] | None = None,
) -> DashboardSnapshot:
    traces = [
        _meta(trace(f"trace-{index}", (session_ids or [str(145665 + item) for item in range(len(values))])[index], 0, f"2026-07-21T{index:02d}:00:00Z", "AI reply"))
        for index in range(len(values))
    ]
    run = _run(traces)
    sessions = tuple(
        replace(session, dimensions=replace(session.dimensions, intent=values[index]))
        for index, session in enumerate(run.result.sessions)
    )
    return project_dashboard(replace(run, result=replace(run.result, sessions=sessions)))


@pytest.mark.parametrize(
    "value",
    ["ý định tự do", "valid_once", "0901234567", "c7534640-c83e-48ef-9104-b1cad2183950", "123456789"],
)
def test_unsafe_or_rare_intent_is_collapsed_without_serializing_raw_value(value: str):
    snapshot = _snapshot_with_intents([value])
    encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)

    assert snapshot.tickets[0].intent == "khác"
    assert value not in encoded
    assert snapshot.dashboard_dict()["coverage"]["intent"] == 1.0
    assert set(snapshot.dashboard_dict()["views"]["mon_sun"]["segments"]["intent"]) == {"Không xác định", "khác"}


def test_intent_requires_five_global_occurrences_then_is_reused_everywhere():
    rare = _snapshot_with_intents(["recovery_intent"] * 4 + [None])
    assert {row.intent for row in rare.tickets} == {"khác", None}
    assert set(rare.dashboard_dict()["views"]["mon_sun"]["segments"]["intent"]) == {"Không xác định", "khác"}

    preserved = _snapshot_with_intents(["recovery_intent"] * 5 + [None])
    assert {row.intent for row in preserved.tickets} == {"recovery_intent", None}
    assert set(preserved.dashboard_dict()["views"]["mon_sun"]["segments"]["intent"]) == {"Không xác định", "recovery_intent"}
    assert DashboardSnapshot.from_storage_dict(preserved.storage_dict()) == preserved


def test_storage_rejects_rare_or_free_text_intent_even_if_ticket_row_is_constructed_manually():
    snapshot = _snapshot_with_intents([None])
    value = snapshot.storage_dict()
    value["tickets"][0]["intent"] = "rare_valid"
    with pytest.raises(ValueError, match="intent"):
        DashboardSnapshot.from_storage_dict(value)

    value = snapshot.storage_dict()
    value["tickets"][0]["intent"] = "ý định tự do"
    with pytest.raises(ValueError, match="intent"):
        DashboardSnapshot.from_storage_dict(value)


def test_ticket_row_requires_positive_turn_count_and_signed_short_tpe_code():
    fields = asdict(_snapshot().tickets[0])
    fields["turn_count"] = 0
    with pytest.raises(ValueError, match="turn_count"):
        TicketRow(**fields)
    fields = asdict(_snapshot().tickets[0])
    fields["tpe_code"] = "1234567"
    with pytest.raises(ValueError, match="tpe_code"):
        TicketRow(**fields)


@pytest.mark.parametrize(
    "value",
    [
        "0901234567",
        "c7534640-c83e-48ef-9104-b1cad2183950",
        "123456789",
        "person@example.com",
        "https://customer.example",
    ],
)
def test_five_identical_unsafe_intents_never_survive_the_frequency_threshold(value: str):
    snapshot = _snapshot_with_intents([value] * 5)
    dashboard = snapshot.dashboard_dict()
    encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)

    assert {row.intent for row in snapshot.tickets} == {"khác"}
    assert set(dashboard["views"]["mon_sun"]["segments"]["intent"]) == {"Không xác định", "khác"}
    assert value not in encoded


def test_storage_rejects_unsafe_intent_even_when_five_ticket_rows_and_segment_totals_match():
    unsafe = "0901234567"
    value = _snapshot_with_intents([None] * 5).storage_dict()
    for ticket in value["tickets"]:
        ticket["intent"] = unsafe
    for view in value["dashboard"]["views"].values():
        bucket = dict(view["segments"]["intent"]["Không xác định"])
        view["segments"]["intent"]["Không xác định"] = {
            "total": 0, "ai_first": 0, "transferred": 0, "reopen": 0,
        }
        view["segments"]["intent"][unsafe] = bucket
    with pytest.raises(ValueError, match="intent"):
        DashboardSnapshot.from_storage_dict(value)


def test_global_mon_sun_intent_count_allows_explorer_to_omit_one_nonnumeric_session():
    snapshot = _snapshot_with_intents(
        ["recovery_intent"] * 5,
        session_ids=["145665", "145666", "145667", "145668", "not-an-explorer-ticket"],
    )

    assert len(snapshot.tickets) == 4
    assert DashboardSnapshot.from_storage_dict(snapshot.storage_dict()) == snapshot


def test_later_transfer_on_an_unclassified_ticket_does_not_inflate_outcome_transfer_total():
    first = _meta(trace("empty-first", "145665", 0, "2026-07-21T02:00:00Z", ""))
    later_transfer = _meta(trace("later-transfer", "145665", 1, "2026-07-21T03:00:00Z", TRANSFER_TEXT))
    snapshot = project_dashboard(_run([first, later_transfer]))

    row = snapshot.tickets[0]
    assert row.outcome == "unclassified"
    assert row.transferred is True
    dashboard = snapshot.dashboard_dict()
    for view in dashboard["views"].values():
        assert view["totals"]["transfer_total"] == (
            view["outcomes"]["ai_then_cs"] + view["outcomes"]["direct_cs"]
        )
    assert DashboardSnapshot.from_storage_dict(snapshot.storage_dict()) == snapshot
