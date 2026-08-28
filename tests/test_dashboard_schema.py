from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

import pytest

from tests.fixtures.traces import TRANSFER_HTML, TRANSFER_TEXT, trace
from weekly_cs_report.dashboard_schema import (
    DashboardSnapshot,
    TicketRow,
    _TICKET_EXPLORER_PUBLIC_KEYS,
    _safe_string,
    _shape_transfer_reasons,
    _ticket_public_dict,
    _ticket_sort_value,
    _tpe_rows_from_signals,
    project_dashboard,
    ticket_day_aggregate,
    ticket_page,
)
from weekly_cs_report.entry_coverage_cache import EntryCoverageRecord
from weekly_cs_report.csat_cache import (
    CSATCache,
    CSATCacheStats,
    CachedCSATResponse,
)
from weekly_cs_report.reconciliation_cache import (
    ReconciliationCache,
    ReconciliationRecord,
)
from weekly_cs_report.models import TransferTrigger
from weekly_cs_report.report import compute_report


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


class FakeClient:
    def __init__(self, traces: list[dict]) -> None:
        self.traces = traces
        self.observation_calls: list[str] = []

    def iter_traces(self, _from: datetime, _to: datetime, **_controls):
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
    run = _run([monday, weekend, transfer])
    sessions = tuple(
        replace(
            session,
            dimensions=replace(
                session.dimensions,
                tpe_signals=(("-365", "-1013"),),
            ),
        )
        for session in run.result.sessions
    )
    return project_dashboard(
        replace(run, result=replace(run.result, sessions=sessions))
    )


def _same_period_snapshot() -> DashboardSnapshot:
    return project_dashboard(
        _run(
            [
                _meta(
                    trace(
                        "baseline-a",
                        "145701",
                        0,
                        "2026-07-14T02:00:00Z",
                        "AI reply",
                    )
                ),
                _meta(
                    trace(
                        "baseline-b",
                        "145702",
                        0,
                        "2026-07-21T02:00:00Z",
                        TRANSFER_HTML,
                    )
                ),
                _meta(
                    trace(
                        "current",
                        "145703",
                        0,
                        "2026-07-28T02:00:00Z",
                        "AI reply",
                    )
                ),
            ]
        )
    )


def test_v15_has_exact_top_level_contract_and_25_ticket_allowlist():
    snapshot = _snapshot()
    dashboard = snapshot.dashboard_dict()

    assert snapshot.storage_dict()["schema_version"] == 24
    assert set(dashboard) == {
        "generated_at", "source", "enrichment_status", "data_range", "views",
        "coverage", "unmapped_tpe_codes", "gate_status", "data_quality",
    }
    assert dashboard["source"]["observations_fetched"] == 0
    assert dashboard["enrichment_status"] == "partial"
    assert set(asdict(snapshot.tickets[0])) == {
        "ticket_id", "opened_at", "cohort_week", "cohort_status", "is_weekend_start", "outcome",
        "ai_first", "transferred", "reopen_lifetime", "reopen_within_7d",
        "ai_reply_count", "turn_count", "gt4_turn", "issue_category", "app",
        "product_code", "skill", "intent", "tpe_code", "tpe_status",
        "guardrail_rule", "transfer_reason", "escalation_guard_blocked", "csat_satisfaction",
        "data_quality", "model_core",
        # Day-grain diagnostic fields (§4.1) -- server-only.
        "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
        "guardrail_rules", "tpe_signals",
    }
    assert {
        ticket.ticket_id: getattr(ticket, "opened_at", None)
        for ticket in snapshot.tickets
    } == {
        "145665": "2026-07-20T02:00:00Z",
        "145666": "2026-07-24T18:00:00Z",
        "145667": "2026-07-22T02:00:00Z",
    }
    assert "mô tả tuyệt đối" not in json.dumps(snapshot.storage_dict(), ensure_ascii=False)


def test_entry_coverage_storage_is_v18_and_rejects_v17_or_unknown_record_fields():
    snapshot = _snapshot()
    record = EntryCoverageRecord(
        ticket_id="7043723",
        opened_at="2026-07-20T02:00:00Z",
        cohort_week="2026-07-20",
        status="not_observed_invoked",
        human_replied=True,
    )
    value = snapshot.storage_dict()
    value["entry_coverage_tickets"] = [asdict(record)]

    restored = DashboardSnapshot.from_storage_dict(value)
    assert restored.entry_coverage_tickets == (record,)

    value["schema_version"] = 16
    with pytest.raises(ValueError, match="unsupported dashboard storage"):
        DashboardSnapshot.from_storage_dict(value)

    value["schema_version"] = 24
    value["entry_coverage_tickets"][0]["raw_body"] = "must not be accepted"
    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)


def test_same_period_storage_is_per_view_and_rejects_top_level_placement():
    value = _same_period_snapshot().storage_dict()
    same_period = value["dashboard"]["views"]["mon_sun"]["same_period"]

    assert same_period["current"]["cohort_week"] == "2026-07-27"
    assert same_period["current"] == same_period["by_week"]["2026-07-27"]
    assert set(same_period["by_week"]) == set(
        value["dashboard"]["views"]["mon_sun"]["by_week"]
    )
    value["dashboard"]["same_period"] = same_period
    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)


def _csat_v11_snapshot(
    reconciliation_cache: ReconciliationCache | None = None,
) -> DashboardSnapshot:
    raw_sessions = [
        _meta(trace("ai-negative", "145665", 0, "2026-07-21T02:00:00Z", "AI reply")),
        _meta(trace("ai-neutral", "145666", 0, "2026-07-22T02:00:00Z", "AI reply")),
        _meta(
            trace(
                "direct-positive",
                "145667",
                0,
                "2026-07-23T02:00:00Z",
                TRANSFER_HTML,
            )
        ),
        _meta(trace("unrated", "145668", 0, "2026-07-24T02:00:00Z", "AI reply")),
        _meta(trace("unfetched", "145669", 0, "2026-07-14T02:00:00Z", "AI reply")),
        _meta(trace("weekend", "145670", 0, "2026-07-24T18:00:00Z", "AI reply")),
    ]
    run = _run(raw_sessions)
    dimensions = {
        "145665": {
            "issue_category": "Chuyển tiền",
            "skill": "interbank-fund-transfer",
            "skill_count": 1,
            "skill_set": ("interbank-fund-transfer",),
        },
        "145666": {
            "issue_category": "",
            "skill": None,
            "skill_count": 2,
            "skill_set": ("topup", "withdraw"),
        },
        "145667": {
            "issue_category": "Rút tiền",
            "skill": "withdraw",
            "skill_count": 1,
            "skill_set": ("withdraw",),
        },
    }
    sessions = []
    for session in run.result.sessions:
        overrides = dimensions.get(session.session_id, {})
        outcome = "direct_cs" if session.session_id == "145667" else "ai_end_to_end"
        sessions.append(
            replace(
                session,
                outcome=outcome,
                ai_first=outcome != "direct_cs",
                transferred=outcome == "direct_cs",
                dimensions=replace(session.dimensions, **overrides),
            )
        )
    cache = CSATCache(
        fetched_weeks={"2026-07-20": "2026-08-02T01:00:00Z"},
        fetch_stats=CSATCacheStats(6, 6, 0, 0),
        responses=(
            CachedCSATResponse(
                response_key=f"sha256:{'a' * 64}",
                ticket_id="145665",
                survey_id=43000076179,
                responded_at="2026-07-21T01:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=True,
                comment_redacted="Nhanh và rõ ràng",
            ),
            CachedCSATResponse(
                response_key=f"sha256:{'b' * 64}",
                ticket_id="145665",
                survey_id=43000076179,
                responded_at="2026-07-22T01:00:00Z",
                rating_raw=-103,
                satisfaction_bucket="negative",
                comment_present=True,
                comment_redacted="Chưa giải quyết được",
            ),
            CachedCSATResponse(
                response_key=f"sha256:{'c' * 64}",
                ticket_id="145666",
                survey_id=43000076179,
                responded_at="2026-07-23T01:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=True,
                comment_redacted="Đã hỗ trợ",
            ),
            CachedCSATResponse(
                response_key=f"sha256:{'d' * 64}",
                ticket_id="145666",
                survey_id=43000076179,
                responded_at="2026-07-23T01:00:00Z",
                rating_raw=100,
                satisfaction_bucket="neutral",
                comment_present=False,
                comment_redacted=None,
            ),
            CachedCSATResponse(
                response_key=f"sha256:{'e' * 64}",
                ticket_id="145667",
                survey_id=43000076179,
                responded_at="2026-07-24T01:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=True,
                comment_redacted="Rất hài lòng",
            ),
            CachedCSATResponse(
                response_key=f"sha256:{'f' * 64}",
                ticket_id="145670",
                survey_id=43000076179,
                responded_at="2026-07-25T03:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=False,
                comment_redacted=None,
            ),
        ),
    )
    return project_dashboard(
        replace(run, result=replace(run.result, sessions=tuple(sessions))),
        csat_cache=cache,
        reconciliation_cache=reconciliation_cache,
    )


def _reconciliation_cache() -> ReconciliationCache:
    return ReconciliationCache(
        fetched_weeks={"2026-07-20": "2026-08-03T01:00:00Z"},
        records=(
            ReconciliationRecord("145665", "2026-07-20", True),
            ReconciliationRecord("145666", "2026-07-20", False),
            ReconciliationRecord("145668", "2026-07-20", None),
            ReconciliationRecord("145670", "2026-07-20", True),
        ),
    )


def test_v12_projects_reconciliation_per_view_without_rewriting_langfuse_outcome():
    snapshot = _csat_v11_snapshot(_reconciliation_cache())
    dashboard = snapshot.dashboard_dict()

    mon_fri = dashboard["views"]["mon_fri"]["outcome_reconciliation"]
    mon_sun = dashboard["views"]["mon_sun"]["outcome_reconciliation"]
    assert mon_fri["fetched_at"] == "2026-08-03T01:00:00Z"
    assert mon_fri["by_week"]["2026-07-20"] == {
        "langfuse_ai_end_to_end": 3,
        "checked_ticket_count": 2,
        "human_replied_after_ai": 1,
        "unresolved_ticket_count": 1,
        "mismatch_rate": 0.5,
    }
    assert mon_sun["by_week"]["2026-07-20"] == {
        "langfuse_ai_end_to_end": 4,
        "checked_ticket_count": 3,
        "human_replied_after_ai": 2,
        "unresolved_ticket_count": 1,
        "mismatch_rate": pytest.approx(2 / 3),
    }
    assert dashboard["views"]["mon_fri"]["outcomes"]["ai_end_to_end"] == 4


def test_v12_reconciliation_denominator_excludes_unfetchable_session_ids():
    safe = _meta(
        trace(
            "safe-trace",
            "145665",
            0,
            "2026-07-21T02:00:00Z",
            "AI reply",
        )
    )
    unsafe = _meta(
        trace(
            "unsafe-trace",
            "8490123456",
            0,
            "2026-07-21T03:00:00Z",
            "AI reply",
        )
    )
    cache = ReconciliationCache(
        fetched_weeks={"2026-07-20": "2026-08-03T01:00:00Z"},
        records=(ReconciliationRecord("145665", "2026-07-20", False),),
    )

    dashboard = project_dashboard(
        _run([safe, unsafe]),
        reconciliation_cache=cache,
    ).dashboard_dict()
    row = dashboard["views"]["mon_sun"]["outcome_reconciliation"]["by_week"][
        "2026-07-20"
    ]

    # The Langfuse outcome remains unchanged, while the Freshdesk denominator
    # contains only identifiers the reconciliation job is allowed to fetch.
    assert dashboard["views"]["mon_sun"]["outcomes"]["ai_end_to_end"] == 2
    assert row == {
        "langfuse_ai_end_to_end": 1,
        "checked_ticket_count": 1,
        "human_replied_after_ai": 0,
        "unresolved_ticket_count": 0,
        "mismatch_rate": 0.0,
    }


def test_v12_reconciliation_is_null_when_private_cache_is_unavailable():
    dashboard = _csat_v11_snapshot().dashboard_dict()

    assert dashboard["views"]["mon_fri"]["outcome_reconciliation"] is None
    assert dashboard["views"]["mon_sun"]["outcome_reconciliation"] is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda row: row.__setitem__("checked_ticket_count", 99),
            "reconciliation",
        ),
        (
            lambda row: row.__setitem__("mismatch_rate", None),
            "reconciliation",
        ),
        (
            lambda row: row.__setitem__("agent_id", 42),
            "unsupported or missing fields",
        ),
    ],
)
def test_v12_rejects_invalid_reconciliation_rollups(mutate, message):
    value = _csat_v11_snapshot(_reconciliation_cache()).storage_dict()
    row = value["dashboard"]["views"]["mon_fri"]["outcome_reconciliation"][
        "by_week"
    ]["2026-07-20"]
    mutate(row)

    with pytest.raises(ValueError, match=message):
        DashboardSnapshot.from_storage_dict(value)


def test_csat_v11_projects_latest_ticket_rating_outcomes_dimensions_and_feedback():
    snapshot = _csat_v11_snapshot()
    dashboard = snapshot.dashboard_dict()

    mon_sun = dashboard["views"]["mon_sun"]["csat"]
    mon_fri = dashboard["views"]["mon_fri"]["csat"]
    assert mon_sun is not None
    assert mon_fri is not None
    week = mon_fri["by_week"]["2026-07-20"]
    assert week["response_count"] == 5
    assert week["ticket_count"] == 3
    assert week["ticket_count"] == (
        week["positive"] + week["neutral"] + week["negative"]
    )
    assert sum(row["ticket_count"] for row in week["by_outcome"].values()) == 3
    assert week["by_outcome"]["ai_end_to_end"] == {
        "ticket_count": 2,
        "positive": 0,
        "neutral": 1,
        "negative": 1,
    }
    assert week["response_by_outcome"]["ai_end_to_end"] == {
        "ticket_count": 4,
        "positive": 2,
        "neutral": 1,
        "negative": 1,
    }
    assert week["response_by_outcome"]["direct_cs"] == {
        "ticket_count": 1,
        "positive": 1,
        "neutral": 0,
        "negative": 0,
    }
    assert next(
        row
        for row in week["response_by_dimension"]["skill"]
        if row["value"] == "interbank-fund-transfer"
    )["ticket_count"] == 2
    assert sum(row["ticket_count"] for row in week["by_dimension"]["skill"]) == 3
    assert sum(
        row["ticket_count"] for row in week["by_dimension"]["issue_category"]
    ) == 3
    assert next(
        row
        for row in week["by_dimension"]["skill"]
        if row["value"] == "Nhiều skill"
    )["ticket_count"] == 1
    assert [
        (
            item["ticket_id"],
            item["response_number"],
            item["response_total"],
            item["is_latest_for_ticket"],
            item["outcome"],
            item["skill"],
            item["issue_category"],
        )
        for item in week["feedback_entries"]
    ] == [
        ("145665", 1, 2, False, "ai_end_to_end", "interbank-fund-transfer", "Chuyển tiền"),
        ("145665", 2, 2, True, "ai_end_to_end", "interbank-fund-transfer", "Chuyển tiền"),
        ("145666", 1, 2, False, "ai_end_to_end", "Nhiều skill", "Không xác định"),
        ("145667", 1, 1, True, "direct_cs", "withdraw", "Rút tiền"),
    ]
    assert mon_sun["by_week"]["2026-07-20"]["ticket_count"] == 4

    rows = {row.ticket_id: row for row in snapshot.tickets}
    assert rows["145665"].csat_satisfaction == "negative"
    assert rows["145666"].csat_satisfaction == "neutral"
    assert rows["145666"].skill == "Nhiều skill"
    assert rows["145667"].csat_satisfaction == "positive"
    assert rows["145668"].csat_satisfaction == "unrated"
    assert rows["145669"].csat_satisfaction is None
    assert ticket_page(snapshot, skill="Nhiều skill")["items"] == [
        _ticket_public_dict(rows["145666"])
    ]
    assert ticket_page(snapshot, skill="Chưa ghi nhận")["total"] == 3
    assert ticket_page(snapshot, csat_satisfaction="negative")["total"] == 1
    assert ticket_page(snapshot, csat_satisfaction="unrated")["total"] == 1
    serialized = json.dumps(dashboard)
    for forbidden in ("agent_id", "agent_name", "survey_id", "rating_raw", "response_key", "body_text"):
        assert forbidden not in serialized


def test_missing_csat_cache_projects_explicit_null_in_both_views():
    dashboard = _snapshot().dashboard_dict()

    assert dashboard["views"]["mon_sun"]["csat"] is None
    assert dashboard["views"]["mon_fri"]["csat"] is None


def test_safe_dashboard_label_allows_a_dotted_product_name():
    assert _safe_string("19 - TIX.VN", "segments.app label") == "19 - TIX.VN"


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "email private@example.test",
        "Xem example.test/help?token=private",
        "Xem vídụ.vn/help?token=private",
        "Xem 192.168.1.1/help?token=private",
        "Xem [2001:db8::1]/help?token=private",
        "Xem 2001:db8::1/help?token=private",
        "Xem zalo://open/ticket/12345",
        "Xem zalo:open/ticket/12345",
    ],
)
def test_csat_payload_rejects_unredacted_comment_text(unsafe_text: str):
    value = _csat_v11_snapshot().storage_dict()
    entry = value["dashboard"]["views"]["mon_sun"]["csat"]["by_week"][
        "2026-07-20"
    ]["feedback_entries"][0]
    entry["text"] = unsafe_text

    with pytest.raises(ValueError, match="unsafe"):
        DashboardSnapshot.from_storage_dict(value)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda week: week.__setitem__("ticket_count", 999), "ticket count"),
        (
            lambda week: week["by_outcome"]["ai_end_to_end"].__setitem__(
                "positive", 999
            ),
            "outcome",
        ),
        (
            lambda week: week["feedback_entries"][0].__setitem__(
                "response_number", 0
            ),
            "response number",
        ),
        (
            lambda week: week["by_dimension"]["skill"][0].__setitem__(
                "ticket_count", 999
            ),
            "dimension",
        ),
        (
            lambda week: week["feedback_entries"][0].__setitem__("agent_id", 42),
            "unsupported or missing fields",
        ),
    ],
)
def test_csat_v11_rejects_nonreconciling_or_extra_fields(mutate, message):
    value = _csat_v11_snapshot().storage_dict()
    week = value["dashboard"]["views"]["mon_sun"]["csat"]["by_week"][
        "2026-07-20"
    ]
    mutate(week)

    with pytest.raises(ValueError, match=message):
        DashboardSnapshot.from_storage_dict(value)


@pytest.mark.parametrize(
    "private_field",
    ["survey_id", "rating_raw", "comment_present", "response_key"],
)
def test_csat_feedback_rejects_private_cache_fields(private_field: str):
    value = _csat_v11_snapshot().storage_dict()
    entry = value["dashboard"]["views"]["mon_sun"]["csat"]["by_week"][
        "2026-07-20"
    ]["feedback_entries"][0]
    entry[private_field] = "private"

    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)


def test_csat_satisfaction_is_required_and_strict_in_v11_storage():
    value = _csat_v11_snapshot().storage_dict()
    value["tickets"][0]["csat_satisfaction"] = "unknown"
    with pytest.raises(ValueError, match="csat_satisfaction"):
        DashboardSnapshot.from_storage_dict(value)

    value = _csat_v11_snapshot().storage_dict()
    del value["tickets"][0]["csat_satisfaction"]
    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)


def test_v14_snapshot_is_rejected_after_v15_storage_bump():
    value = _csat_v11_snapshot().storage_dict()
    value["schema_version"] = 14
    with pytest.raises(ValueError, match="unsupported dashboard storage schema_version"):
        DashboardSnapshot.from_storage_dict(value)


def test_v15_rejects_noncanonical_ticket_opened_at():
    value = _snapshot().storage_dict()
    value["tickets"][0]["opened_at"] = "2026-07-20T09:00:00+07:00"

    with pytest.raises(ValueError, match="opened_at.*UTC ISO"):
        DashboardSnapshot.from_storage_dict(value)


def test_csat_payload_rejects_noncanonical_utc_timestamp():
    value = _csat_v11_snapshot().storage_dict()
    value["dashboard"]["views"]["mon_sun"]["csat"]["fetched_at"] = (
        "2026-08-02 01:00:00Z"
    )

    with pytest.raises(ValueError, match="UTC ISO"):
        DashboardSnapshot.from_storage_dict(value)


def test_same_period_rejects_current_row_drift_from_by_week():
    value = _same_period_snapshot().storage_dict()
    current = value["dashboard"]["views"]["mon_sun"]["same_period"]["current"]
    current["total_tickets"] = 2
    current["ai_first_count"] = 1
    current["ai_first_rate"] = 0.5

    with pytest.raises(ValueError, match="current"):
        DashboardSnapshot.from_storage_dict(value)


def test_same_period_rejects_more_than_four_baseline_weeks():
    value = _same_period_snapshot().storage_dict()
    value["dashboard"]["views"]["mon_sun"]["same_period"]["baseline"][
        "weeks_used"
    ] = 5

    with pytest.raises(ValueError, match="weeks_used"):
        DashboardSnapshot.from_storage_dict(value)


def test_same_period_rejects_current_week_that_is_not_running():
    value = _same_period_snapshot().storage_dict()
    view = value["dashboard"]["views"]["mon_sun"]
    current_week = view["same_period"]["current"]["cohort_week"]
    current = next(
        row for row in view["weekly"] if row["cohort_week"] == current_week
    )
    current["cohort_status"] = "complete"

    with pytest.raises(ValueError, match="running"):
        DashboardSnapshot.from_storage_dict(value)


def test_same_period_rejects_cutoff_weekday_drift_and_unknown_week():
    value = _same_period_snapshot().storage_dict()
    same_period = value["dashboard"]["views"]["mon_sun"]["same_period"]
    same_period["cutoff_weekday"] = 7
    with pytest.raises(ValueError, match="cutoff weekday"):
        DashboardSnapshot.from_storage_dict(value)

    value = _same_period_snapshot().storage_dict()
    same_period = value["dashboard"]["views"]["mon_sun"]["same_period"]
    same_period["by_week"]["2026-06-29"] = {
        **same_period["current"],
        "cohort_week": "2026-06-29",
    }
    with pytest.raises(ValueError, match="outside view.by_week"):
        DashboardSnapshot.from_storage_dict(value)


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
        assert "same_period" in view
        assert set(view["by_week"]) == {
            row["cohort_week"] for row in view["weekly"]
        }
        assert set(view["segments"]) == {"issue_category", "app", "product_code", "skill", "intent", "tpe", "guardrail_rule", "entry_point", "model_core"}
        for dimension, buckets in view["segments"].items():
            expected_label = "Chưa ghi nhận" if dimension == "skill" else "Không xác định"
            assert expected_label in buckets
            assert sum(bucket["total"] for bucket in buckets.values()) == view["totals"]["eligible_ticket_count"]
        for row in view["weekly"]:
            weekly_detail = view["by_week"][row["cohort_week"]]
            for dimension, buckets in weekly_detail["segments"].items():
                expected_label = "Chưa ghi nhận" if dimension == "skill" else "Không xác định"
                assert expected_label in buckets
                assert sum(bucket["total"] for bucket in buckets.values()) == row["total_tickets"]
            assert (
                weekly_detail["transfer_reasons"]["observed_transfer_denominator"]
                == sum(
                    bucket["transferred"]
                    for bucket in weekly_detail["segments"]["issue_category"].values()
                )
            )


def test_skill_segment_splits_named_multi_and_unrecorded():
    """A named single skill, a triple-skill ticket, and a ticket with no
    `execute` observation used to collapse into one "Không xác định" bucket.
    They must now land in three distinct, honestly labelled buckets."""
    monday = _meta(trace("zero-skill", "145665", 0, "2026-07-20T02:00:00Z", "AI reply"))
    single = _meta(trace("single-skill", "145666", 0, "2026-07-20T03:00:00Z", "AI reply"))
    multi = _meta(trace("multi-skill", "145667", 0, "2026-07-20T04:00:00Z", "AI reply"))
    run = _run([monday, single, multi])
    sessions = []
    for session in run.result.sessions:
        if session.session_id == "145666":
            sessions.append(replace(session, dimensions=replace(
                session.dimensions, skill="topup", skill_count=1, skill_set=("topup",),
            )))
        elif session.session_id == "145667":
            sessions.append(replace(session, dimensions=replace(
                session.dimensions, skill=None, skill_count=2, skill_set=("topup", "withdraw"),
            )))
        else:
            sessions.append(session)

    dashboard = project_dashboard(
        replace(run, result=replace(run.result, sessions=tuple(sessions)))
    ).dashboard_dict()
    skill_buckets = dashboard["views"]["mon_sun"]["segments"]["skill"]

    assert skill_buckets["topup"]["total"] == 1
    assert skill_buckets["Nhiều skill"]["total"] == 1
    assert skill_buckets["Chưa ghi nhận"]["total"] == 1
    assert "Không xác định" not in skill_buckets
    # Coverage counts both the one-skill and multi-skill ticket as recorded;
    # only the zero-skill ticket is missing.
    assert dashboard["coverage"]["skill"] == pytest.approx(2 / 3)


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
                    dimensions=replace(
                        session.dimensions,
                        tpe_signals=(
                            ("-365", "-1013"),
                            ("-365", "-1006"),
                        ),
                    ),
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
                        tpe_signals=(("-365", "-1013"),),
                    ),
                    guardrail_rules=("missing_transaction_id",),
                )
            )
        elif session.session_id == "145667":
            enriched.append(
                replace(
                    session,
                    dimensions=replace(
                        session.dimensions,
                        tpe_signals=(
                            ("-383", None),
                            ("-365", None),
                        ),
                    ),
                )
            )
        else:
            enriched.append(session)
    run = replace(run, result=replace(run.result, sessions=tuple(enriched)))

    view = project_dashboard(run).dashboard_dict()["views"]["mon_sun"]
    reasons = view["transfer_reasons"]

    assert reasons == {
        "observed_transfer_denominator": 4,
        "triggers": [
            {
                "reason": "unknown",
                "rule": None,
                "source": None,
                "stage": None,
                "skill": None,
                "count": 4,
            }
        ],
        "tpe": [
            {
                "transstatus": "-365",
                "step_result": "-1013",
                "count": 2,
                "status": "FAILED_FACE_AUTH",
            },
            {
                "transstatus": "-365",
                "step_result": "-1006",
                "count": 1,
                "status": "FAILED_NFC",
            },
            {
                "transstatus": "-365",
                "step_result": None,
                "count": 1,
                "status": None,
            },
            {
                "transstatus": "-383",
                "step_result": None,
                "count": 1,
                "status": "PENDING",
            },
        ],
        "step_result_missing": {"count": 2, "denominator": 4},
        "guardrail": [
            {"rule": "missing_transaction_id", "count": 2},
            {"rule": "off_topic", "count": 1},
        ],
        "escalation_guard_blocked": {"count": 1, "denominator": 4},
    }
    assert sum(row["count"] for row in reasons["tpe"]) == 5
    assert "top_reason" not in reasons
    week_reasons = view["by_week"]["2026-07-20"]["transfer_reasons"]
    assert week_reasons == reasons
    empty_week = view["by_week"]["2026-07-13"]
    assert empty_week["transfer_reasons"] == {
        "observed_transfer_denominator": 0,
        "triggers": [],
        "tpe": [],
        "step_result_missing": {"count": 0, "denominator": 0},
        "guardrail": [],
        "escalation_guard_blocked": {"count": 0, "denominator": 0},
    }
    zero_bucket = {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0}
    assert all(
        buckets == {("Chưa ghi nhận" if dimension == "skill" else "Không xác định"): zero_bucket}
        for dimension, buckets in empty_week["segments"].items()
    )


def _merge_full_shape_transfer_reasons(
    days: list[dict[str, object]],
) -> dict[str, object]:
    """Sum a list of day-grain `transfer_reasons` payloads into one.

    Mirrors what the frontend's `aggregateTransferReasonsFromDays` does when
    rolling several day buckets back up into a week -- used here only to
    prove the backend day-grain aggregator (`_day_transfer_reasons`) carries
    exactly the same information as the weekly one (`_transfer_reasons`),
    independent of how the days happen to be split (§6 test #7)."""
    denominator = 0
    triggers: Counter[tuple[str, str | None, str | None, str | None, str | None]] = Counter()
    tpe: Counter[tuple[str, str | None]] = Counter()
    tpe_status: dict[tuple[str, str | None], str] = {}
    guardrail: Counter[str] = Counter()
    step_result_missing = 0
    escalation_blocked = 0
    for day in days:
        reasons = day["transfer_reasons"]
        denominator += reasons["observed_transfer_denominator"]
        for row in reasons["triggers"]:
            triggers[(row["reason"], row["rule"], row["source"], row["stage"], row["skill"])] += row["count"]
        for row in reasons["tpe"]:
            key = (row["transstatus"], row["step_result"])
            tpe[key] += row["count"]
            if row["status"] is not None:
                tpe_status[key] = row["status"]
        for row in reasons["guardrail"]:
            guardrail[row["rule"]] += row["count"]
        step_result_missing += reasons["step_result_missing"]["count"]
        escalation_blocked += reasons["escalation_guard_blocked"]["count"]
    return _shape_transfer_reasons(
        denominator=denominator,
        trigger_counts=triggers,
        tpe_rows=_tpe_rows_from_signals(tpe, tpe_status),
        guardrail_counts=guardrail,
        escalation_blocked=escalation_blocked,
        step_result_missing=step_result_missing,
    )


def test_day_grain_transfer_reasons_summed_across_days_reconciles_exactly_with_weekly():
    """§6 test #7: summing the day-grain aggregator across every day of a
    full week must reproduce the weekly aggregator's output exactly -- same
    triggers, same TPE grain/status, same guardrail counts, no rounding."""
    traces = [
        _meta(
            trace("first-a", "145665", 0, "2026-07-21T02:00:00Z", TRANSFER_HTML),
            tpe="-217 Thất bại",
        ),
        _meta(
            trace("first-b", "145666", 0, "2026-07-22T03:00:00Z", TRANSFER_HTML),
            tpe="-217 Đang xử lý",
        ),
        _meta(
            trace("first-c", "145667", 0, "2026-07-23T04:00:00Z", TRANSFER_HTML),
            tpe="-383 Đang xử lý",
        ),
        _meta(
            trace("first-d", "145668", 0, "2026-07-24T05:00:00Z", TRANSFER_HTML),
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
                    dimensions=replace(
                        session.dimensions,
                        tpe_signals=(
                            ("-365", "-1013"),
                            ("-365", "-1006"),
                        ),
                    ),
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
                        tpe_signals=(("-365", "-1013"),),
                    ),
                    guardrail_rules=("missing_transaction_id",),
                )
            )
        elif session.session_id == "145667":
            enriched.append(
                replace(
                    session,
                    dimensions=replace(
                        session.dimensions,
                        tpe_signals=(
                            ("-383", None),
                            ("-365", None),
                        ),
                    ),
                )
            )
        else:
            enriched.append(session)
    run = replace(run, result=replace(run.result, sessions=tuple(enriched)))

    snapshot = project_dashboard(run)
    weekly_reasons = snapshot.dashboard_dict()["views"]["mon_sun"]["by_week"]["2026-07-20"]["transfer_reasons"]

    days = ticket_day_aggregate(
        snapshot, opened_from="2026-07-20", opened_to="2026-07-26"
    )
    day_summed_reasons = _merge_full_shape_transfer_reasons(days)

    assert day_summed_reasons == weekly_reasons


def test_tpe_rows_carry_resolved_status_and_leave_unmapped_null():
    """Status phai di kem tung dong, va cap chua map phai la None."""
    rows = _tpe_rows_from_signals(
        {("1", "1"): 19, ("-217", "-5025"): 2},
        {("1", "1"): "SUCCESSFUL"},
    )
    by_pair = {(r["transstatus"], r["step_result"]): r for r in rows}
    assert by_pair[("1", "1")]["status"] == "SUCCESSFUL"
    assert by_pair[("-217", "-5025")]["status"] is None


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


def test_transfer_triggers_are_an_exclusive_partition_and_keep_both_cs_escalation_sources():
    traces = [
        _meta(
            trace(
                f"transfer-{index}",
                str(145665 + index),
                0,
                f"2026-07-21T0{index + 2}:00:00Z",
                TRANSFER_HTML,
            )
        )
        for index in range(4)
    ]
    run = _run(traces)
    skill_trigger = TransferTrigger(
        reason="skill_suggested_transfer",
        rule="cs_escalation",
        source="skill_guardrail_checked",
        stage="output",
        skill="interbank-fund-transfer",
    )
    response_trigger = TransferTrigger(
        reason="ai_response_requires_transfer",
        rule="cs_escalation",
        source="output_guardrail",
    )
    sessions = tuple(
        replace(
            session,
            transfer_trigger=(
                skill_trigger
                if session.session_id in {"145665", "145666"}
                else response_trigger
                if session.session_id == "145667"
                else None
            ),
        )
        for session in run.result.sessions
    )

    snapshot = project_dashboard(
        replace(run, result=replace(run.result, sessions=sessions))
    )
    reasons = snapshot.dashboard_dict()["views"]["mon_sun"]["transfer_reasons"]

    assert reasons["triggers"] == [
        {
            "reason": "skill_suggested_transfer",
            "rule": "cs_escalation",
            "source": "skill_guardrail_checked",
            "stage": "output",
            "skill": "interbank-fund-transfer",
            "count": 2,
        },
        {
            "reason": "ai_response_requires_transfer",
            "rule": "cs_escalation",
            "source": "output_guardrail",
            "stage": None,
            "skill": None,
            "count": 1,
        },
        {
            "reason": "unknown",
            "rule": None,
            "source": None,
            "stage": None,
            "skill": None,
            "count": 1,
        },
    ]
    assert sum(row["count"] for row in reasons["triggers"]) == 4
    assert reasons["observed_transfer_denominator"] == 4
    assert {
        ticket.ticket_id: ticket.transfer_reason
        for ticket in snapshot.tickets
    } == {
        "145665": "skill_suggested_transfer",
        "145666": "skill_suggested_transfer",
        "145667": "ai_response_requires_transfer",
        "145668": "unknown",
    }


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

    with pytest.raises(ValueError, match="unsupported or missing fields"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["transstatus"] = "gọi 0901234567"
    with pytest.raises(ValueError, match="transstatus"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["transstatus"] = "-365\n"
    with pytest.raises(ValueError, match="transstatus"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["step_result"] = "700212|raw"
    with pytest.raises(ValueError, match="step_result"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    row = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    row["step_result"] = "-1013\n"
    with pytest.raises(ValueError, match="step_result"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    missing = value["dashboard"]["views"]["mon_sun"]["transfer_reasons"][
        "step_result_missing"
    ]
    missing["count"] = missing["denominator"] + 1
    with pytest.raises(ValueError, match="step_result_missing"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_rejects_transfer_reason_weekly_rollup_drift_and_new_fields():
    value = _snapshot().storage_dict()
    view = value["dashboard"]["views"]["mon_sun"]
    view["by_week"]["2026-07-20"]["transfer_reasons"]["tpe"] = []

    with pytest.raises(ValueError, match="weekly rows do not reconcile"):
        DashboardSnapshot.from_storage_dict(value)

    value = _snapshot().storage_dict()
    view = value["dashboard"]["views"]["mon_sun"]
    view["by_week"]["2026-07-20"]["transfer_reasons"][
        "step_result_missing"
    ]["count"] += 1
    with pytest.raises(
        ValueError,
        match="weekly step_result_missing does not reconcile",
    ):
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
    with pytest.raises(ValueError, match="weekly lifetime does not reconcile"):
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


def test_meta_tpe_and_pipe_step_never_enter_public_transfer_diagnostics():
    transfer = _meta(
        trace(
            "transfer",
            "145665",
            0,
            "2026-07-21T02:00:00Z",
            TRANSFER_HTML,
        ),
        tpe="-217 Thất bại",
    )
    snapshot = project_dashboard(_run([transfer]))
    dashboard = snapshot.dashboard_dict()
    reasons = dashboard["views"]["mon_sun"]["transfer_reasons"]

    assert reasons["tpe"] == []
    assert reasons["step_result_missing"] == {"count": 1, "denominator": 1}
    assert dashboard["coverage"]["tpe"] == 0.0
    assert dashboard["unmapped_tpe_codes"] == []
    assert snapshot.tickets[0].tpe_code is None
    assert snapshot.tickets[0].tpe_status is None
    encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)
    assert "700212" not in encoded
    assert "-217" not in encoded
    assert "Thất bại" not in encoded


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


def test_public_dashboard_does_not_project_meta_tpe_taxonomy_mapping():
    dashboard = _snapshot().dashboard_dict()
    assert dashboard["unmapped_tpe_codes"] == []
    tpe_row = dashboard["views"]["mon_sun"]["transfer_reasons"]["tpe"][0]
    assert set(tpe_row) == {"transstatus", "step_result", "count", "status"}

    value = _snapshot().storage_dict()
    value["dashboard"]["unmapped_tpe_codes"] = [
        {"code": "-217", "status": "Thất bại", "count": 1}
    ]
    with pytest.raises(ValueError, match="unmapped_tpe_codes must be empty"):
        DashboardSnapshot.from_storage_dict(value)


def test_ticket_page_filters_all_p5_dimensions_at_ticket_grain_and_preserves_24_fields():
    snapshot = _snapshot()
    page = ticket_page(snapshot, cohort_week="2026-07-20", page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert set(page["items"][0]) == _TICKET_EXPLORER_PUBLIC_KEYS
    for private_key in (
        "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
        "guardrail_rules", "tpe_signals",
    ):
        assert private_key not in page["items"][0]
    with pytest.raises(ValueError, match="ticket_id is invalid"):
        ticket_page(snapshot, ticket_id="internal-trace-id")
    assert ticket_page(snapshot, issue_category="Thanh toán-IBFT")["total"] == 3
    assert ticket_page(snapshot, app="241 - Chuyển Tiền ATM")["total"] == 3
    assert ticket_page(snapshot, product_code="TF007 - IBFT")["total"] == 3
    assert ticket_page(snapshot, tpe_code="-365")["total"] == 3
    assert ticket_page(snapshot, skill="Chưa ghi nhận")["total"] == 3
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
        skill=selected.skill or "Chưa ghi nhận",
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


def test_ticket_page_filters_an_explicit_set_of_report_weeks():
    snapshot = _same_period_snapshot()
    selected_weeks = {"2026-07-13", "2026-07-20"}

    page = ticket_page(
        snapshot,
        cohort_weeks=",".join(sorted(selected_weeks)),
        page_size=100,
    )

    assert page["total"] == sum(
        row.cohort_week in selected_weeks for row in snapshot.tickets
    )
    assert {item["cohort_week"] for item in page["items"]} == selected_weeks


@pytest.mark.parametrize(
    "cohort_weeks",
    [
        "2026-07-13",
        "2026-07-13,2026-07-13",
        "2026-07-14,2026-07-20",
        "invalid,2026-07-20",
    ],
)
def test_ticket_page_rejects_invalid_multi_week_filters(cohort_weeks: str):
    with pytest.raises(ValueError, match="cohort_weeks"):
        ticket_page(_same_period_snapshot(), cohort_weeks=cohort_weeks)

    with pytest.raises(ValueError, match="cannot be combined"):
        ticket_page(
            _same_period_snapshot(),
            cohort_week="2026-07-20",
            cohort_weeks="2026-07-13,2026-07-20",
        )


def test_ticket_page_filters_by_opened_date_range_using_vietnam_calendar_days():
    """opened_from/opened_to are Asia/Ho_Chi_Minh calendar days, matching
    every other date-derived field in this module (cohort_week,
    is_weekend_start, ...). Bounding in UTC instead would leak up to 7 hours
    into the neighbouring local day -- regression for that exact bug."""
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            # 2026-07-19 23:59 ICT -- last instant still inside 19/07 ICT.
            replace(base, ticket_id="10", opened_at="2026-07-19T16:59:59Z"),
            # 2026-07-20 00:00:00 ICT -- first instant of 20/07 ICT.
            replace(base, ticket_id="20", opened_at="2026-07-19T17:00:00Z"),
            replace(base, ticket_id="30", opened_at="2026-07-25T05:00:00Z"),
            # 2026-07-30 23:59:59.999999 ICT -- last instant of 30/07 ICT.
            replace(base, ticket_id="40", opened_at="2026-07-30T16:59:59.999999Z"),
            # 2026-07-31 00:00:00 ICT -- first instant of the NEXT day.
            replace(base, ticket_id="50", opened_at="2026-07-30T17:00:00Z"),
        ),
    )

    page = ticket_page(
        ranged_snapshot,
        opened_from="2026-07-20",
        opened_to="2026-07-30",
        page_size=100,
    )

    assert {item["ticket_id"] for item in page["items"]} == {"20", "30", "40"}

    from_only = ticket_page(ranged_snapshot, opened_from="2026-07-25", page_size=100)
    assert {item["ticket_id"] for item in from_only["items"]} == {"30", "40", "50"}

    to_only = ticket_page(ranged_snapshot, opened_to="2026-07-20", page_size=100)
    assert {item["ticket_id"] for item in to_only["items"]} == {"10", "20"}


def test_ticket_page_rejects_invalid_or_conflicting_opened_date_range():
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="opened_from is invalid"):
        ticket_page(snapshot, opened_from="not-a-date")

    with pytest.raises(ValueError, match="opened_to is invalid"):
        ticket_page(snapshot, opened_to="2026-13-40")

    with pytest.raises(ValueError, match="opened_from must not be after opened_to"):
        ticket_page(snapshot, opened_from="2026-07-30", opened_to="2026-07-20")

    with pytest.raises(ValueError, match="cannot be combined"):
        ticket_page(snapshot, opened_from="2026-07-20", cohort_week="2026-07-20")

    with pytest.raises(ValueError, match="cannot be combined"):
        ticket_page(snapshot, opened_to="2026-07-20", cohort_weeks="2026-07-13,2026-07-20")


def test_ticket_day_aggregate_returns_empty_list_for_a_range_touching_no_ticket():
    snapshot = _snapshot()

    days = ticket_day_aggregate(snapshot, opened_from="2020-01-01", opened_to="2020-01-02")

    assert days == []


def test_ticket_day_aggregate_buckets_by_vietnam_local_day_not_utc():
    """opened_at is UTC; day-bucketing must use Asia/Ho_Chi_Minh, matching
    cohort_week/is_weekend_start elsewhere in this module. A ticket opened at
    17:00 UTC or later has already rolled into the next Vietnam-local day."""
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            # 2026-07-19 23:59:59 ICT -- last instant still inside 19/07 ICT.
            replace(base, ticket_id="10", opened_at="2026-07-19T16:59:59Z"),
            # 2026-07-20 00:00:00 ICT -- first instant of 20/07 ICT.
            replace(base, ticket_id="20", opened_at="2026-07-19T17:00:00Z"),
        ),
    )

    days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-19", opened_to="2026-07-20"
    )

    by_day = {day["day"]: day["total_tickets"] for day in days}
    assert by_day == {"2026-07-19": 1, "2026-07-20": 1}


def test_ticket_day_aggregate_sums_multiple_days_and_reports_a_single_day():
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            replace(base, ticket_id="1", opened_at="2026-07-20T02:00:00Z", outcome="ai_end_to_end", ai_first=True, transferred=False),
            replace(base, ticket_id="2", opened_at="2026-07-20T03:00:00Z", outcome="ai_end_to_end", ai_first=True, transferred=False),
            replace(base, ticket_id="3", opened_at="2026-07-21T02:00:00Z", outcome="direct_cs", ai_first=False, transferred=False),
        ),
    )

    days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-21"
    )

    assert [day["day"] for day in days] == ["2026-07-20", "2026-07-21"]
    first, second = days
    assert first["total_tickets"] == 2
    assert first["ai_first_count"] == 2
    assert second["total_tickets"] == 1
    assert second["ai_first_count"] == 0

    single = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-20"
    )
    assert len(single) == 1
    assert single[0]["day"] == "2026-07-20"
    assert single[0]["total_tickets"] == 2


def test_ticket_day_aggregate_reopen_lifetime_denominator_does_not_divide_by_zero():
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            replace(base, ticket_id="1", opened_at="2026-07-20T02:00:00Z", reopen_lifetime=None),
        ),
    )

    days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-20"
    )

    assert days[0]["reopen_lifetime_denominator"] == 0
    assert days[0]["reopen_lifetime_numerator"] == 0


def test_ticket_day_aggregate_includes_segments_and_full_shape_transfer_reasons():
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            replace(base, ticket_id="1", opened_at="2026-07-20T02:00:00Z", skill="interbank-fund-transfer", app="241 - Chuyển Tiền ATM", issue_category="Thanh toán-IBFT", transferred=True, transfer_reason="unknown"),
            replace(base, ticket_id="2", opened_at="2026-07-20T03:00:00Z", skill="interbank-fund-transfer", app="241 - Chuyển Tiền ATM", issue_category="Thanh toán-IBFT", transfer_reason=None),
        ),
    )

    days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-20"
    )

    day = days[0]
    assert day["segments"]["skill"]["interbank-fund-transfer"]["total"] == 2
    assert day["segments"]["app"]["241 - Chuyển Tiền ATM"]["total"] == 2
    assert day["segments"]["issue_category"]["Thanh toán-IBFT"]["total"] == 2
    # Day-grain transfer_reasons is full-shape (§4.2), not a flat reason->count
    # dict -- it must be able to reconstruct exactly what the weekly
    # aggregator would have produced for the same rows.
    assert day["transfer_reasons"] == {
        "observed_transfer_denominator": 1,
        "triggers": [
            {
                "reason": "unknown",
                "rule": None,
                "source": None,
                "stage": None,
                "skill": None,
                "count": 1,
            }
        ],
        # The base fixture ticket already carries one real TPE signal, so it
        # rides along on the transferred row copied into this test.
        "tpe": [
            {
                "transstatus": "-365",
                "step_result": "-1013",
                "count": 1,
                "status": "FAILED_FACE_AUTH",
            }
        ],
        "step_result_missing": {"count": 0, "denominator": 1},
        "guardrail": [],
        "escalation_guard_blocked": {"count": 0, "denominator": 1},
    }


def test_ticket_day_aggregate_sums_resolved_first_reply_and_ai_reply_counts():
    """These two feed selectScope()'s no-week branch (aggregateDays()) the
    same way `resolved_first_reply`/`ai_reply_mean_ai_first` feed it at week
    grain in pipeline.py -- summed here, divided once by the caller, never
    averaged per ticket."""
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            # ai_end_to_end + exactly 1 reply -> counts toward resolved_first_reply.
            replace(base, ticket_id="1", opened_at="2026-07-20T02:00:00Z", outcome="ai_end_to_end", ai_first=True, ai_reply_count=1),
            # ai_end_to_end but 2 replies -> does not count toward resolved_first_reply.
            replace(base, ticket_id="2", opened_at="2026-07-20T03:00:00Z", outcome="ai_end_to_end", ai_first=True, ai_reply_count=2),
            # ai_then_cs, not ai_first -> ai_reply_count excluded from the ai_first sum.
            replace(base, ticket_id="3", opened_at="2026-07-20T04:00:00Z", outcome="ai_then_cs", ai_first=False, transferred=True, transfer_reason="unknown", ai_reply_count=5),
        ),
    )

    days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-20"
    )

    day = days[0]
    assert day["resolved_first_reply_count"] == 1
    assert day["ai_reply_sum_ai_first"] == 3


def test_ticket_day_aggregate_week_definition_mon_fri_excludes_weekend_start_tickets():
    """Same exclusion rule ticket_page already applies for mon_fri, so
    rolling day-aggregates into mon_fri weeks doesn't need its own copy of
    the weekend rule -- the days handed to it are already narrowed."""
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    ranged_snapshot = replace(
        snapshot,
        tickets=(
            replace(base, ticket_id="1", opened_at="2026-07-20T02:00:00Z", is_weekend_start=False),
            # Saturday Vietnam-local -- excluded from mon_fri.
            replace(base, ticket_id="2", opened_at="2026-07-24T18:00:00Z", is_weekend_start=True),
        ),
    )

    all_days = ticket_day_aggregate(
        ranged_snapshot, opened_from="2026-07-20", opened_to="2026-07-25"
    )
    mon_fri_days = ticket_day_aggregate(
        ranged_snapshot,
        opened_from="2026-07-20",
        opened_to="2026-07-25",
        week_definition="mon_fri",
    )

    assert sum(day["total_tickets"] for day in all_days) == 2
    assert sum(day["total_tickets"] for day in mon_fri_days) == 1
    assert [day["day"] for day in mon_fri_days] == ["2026-07-20"]


def test_ticket_page_filters_by_strict_transfer_reason_enum():
    snapshot = _snapshot()
    expected = [
        row.ticket_id
        for row in snapshot.tickets
        if row.transfer_reason == "unknown"
    ]

    page = ticket_page(snapshot, transfer_reason="unknown", page_size=100)

    assert [item["ticket_id"] for item in page["items"]] == sorted(expected)
    assert page["total"] == len(expected)
    with pytest.raises(ValueError, match="transfer_reason is invalid"):
        ticket_page(snapshot, transfer_reason="invented_reason")


def test_ticket_page_sorts_globally_before_pagination_with_nulls_last_and_ticket_id_ties():
    snapshot = _snapshot()
    base = snapshot.tickets[0]
    sorted_snapshot = replace(
        snapshot,
        tickets=(
            replace(
                base,
                ticket_id="40",
                opened_at="2026-07-20T02:00:00Z",
                turn_count=2,
                gt4_turn=False,
                skill=None,
                tpe_code=None,
                reopen_lifetime=None,
                csat_satisfaction=None,
            ),
            replace(
                base,
                ticket_id="30",
                opened_at="2026-07-20T02:00:00.500000Z",
                turn_count=99,
                gt4_turn=True,
                skill="beta",
                tpe_code="-383",
                reopen_lifetime=1,
                csat_satisfaction="positive",
            ),
            replace(
                base,
                ticket_id="20",
                opened_at="2026-07-20T02:00:01Z",
                turn_count=5,
                gt4_turn=True,
                skill="alpha",
                reopen_lifetime=0,
                csat_satisfaction="neutral",
            ),
            replace(
                base,
                ticket_id="10",
                opened_at="2026-07-20T01:59:59Z",
                turn_count=5,
                gt4_turn=True,
                skill="alpha",
                reopen_lifetime=0,
                csat_satisfaction="negative",
            ),
            replace(
                base,
                ticket_id="50",
                opened_at="2026-07-21T02:00:00Z",
                skill="gamma",
                csat_satisfaction="unrated",
            ),
        ),
    )

    first_page = ticket_page(
        sorted_snapshot,
        sort_by="turn_count",
        sort_direction="desc",
        page=1,
        page_size=2,
    )
    second_page = ticket_page(
        sorted_snapshot,
        sort_by="turn_count",
        sort_direction="desc",
        page=2,
        page_size=2,
    )
    skill_ascending = ticket_page(
        sorted_snapshot,
        sort_by="skill",
        sort_direction="asc",
        page_size=100,
    )
    skill_descending = ticket_page(
        sorted_snapshot,
        sort_by="skill",
        sort_direction="desc",
        page_size=100,
    )
    tpe_ascending = ticket_page(
        sorted_snapshot,
        sort_by="tpe_code",
        sort_direction="asc",
        page_size=100,
    )
    tpe_descending = ticket_page(
        sorted_snapshot,
        sort_by="tpe_code",
        sort_direction="desc",
        page_size=100,
    )
    reopen_ascending = ticket_page(
        sorted_snapshot,
        sort_by="reopen_lifetime",
        sort_direction="asc",
        page_size=100,
    )
    reopen_descending = ticket_page(
        sorted_snapshot,
        sort_by="reopen_lifetime",
        sort_direction="desc",
        page_size=100,
    )
    csat_ascending = ticket_page(
        sorted_snapshot,
        sort_by="csat_satisfaction",
        sort_direction="asc",
        page_size=100,
    )
    csat_descending = ticket_page(
        sorted_snapshot,
        sort_by="csat_satisfaction",
        sort_direction="desc",
        page_size=100,
    )
    opened_ascending = ticket_page(
        sorted_snapshot,
        sort_by="opened_at",
        sort_direction="asc",
        page_size=100,
    )
    opened_descending = ticket_page(
        sorted_snapshot,
        sort_by="opened_at",
        sort_direction="desc",
        page_size=100,
    )

    # The largest value starts beyond the default first page but must become the
    # first globally sorted row. Equal values use numeric Ticket ID ascending.
    assert [item["ticket_id"] for item in first_page["items"]] == ["30", "10"]
    assert [item["ticket_id"] for item in second_page["items"]] == ["20", "40"]
    # Nullable columns keep missing values last in both directions.
    assert [item["ticket_id"] for item in skill_ascending["items"]] == [
        "10",
        "20",
        "30",
        "50",
        "40",
    ]
    assert [item["ticket_id"] for item in skill_descending["items"]] == [
        "50",
        "30",
        "10",
        "20",
        "40",
    ]
    assert [item["ticket_id"] for item in tpe_ascending["items"]] == [
        "30",
        "10",
        "20",
        "50",
        "40",
    ]
    assert [item["ticket_id"] for item in tpe_descending["items"]] == [
        "10",
        "20",
        "50",
        "30",
        "40",
    ]
    assert [item["ticket_id"] for item in reopen_ascending["items"]] == [
        "10",
        "20",
        "50",
        "30",
        "40",
    ]
    assert [item["ticket_id"] for item in reopen_descending["items"]] == [
        "30",
        "10",
        "20",
        "50",
        "40",
    ]
    assert [item["ticket_id"] for item in csat_ascending["items"]] == [
        "10",
        "20",
        "30",
        "50",
        "40",
    ]
    assert [item["ticket_id"] for item in csat_descending["items"]] == [
        "30",
        "20",
        "10",
        "50",
        "40",
    ]
    assert [item["ticket_id"] for item in opened_ascending["items"]] == [
        "10",
        "40",
        "30",
        "20",
        "50",
    ]
    assert [item["ticket_id"] for item in opened_descending["items"]] == [
        "50",
        "20",
        "30",
        "40",
        "10",
    ]


def test_ticket_page_sort_contract_rejects_unknown_field_direction_and_orphan_direction():
    snapshot = _snapshot()
    projected_fields = set(asdict(snapshot.tickets[0]))

    assert len(projected_fields) == 32
    assert projected_fields - _TICKET_EXPLORER_PUBLIC_KEYS == {
        "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
        "guardrail_rules", "tpe_signals",
    }
    for sort_by in _TICKET_EXPLORER_PUBLIC_KEYS:
        page = ticket_page(snapshot, sort_by=sort_by, sort_direction="asc")
        assert page["total"] == len(snapshot.tickets)
    assert [
        item["ticket_id"]
        for item in ticket_page(snapshot, sort_by="ticket_id")["items"]
    ] == ["145665", "145666", "145667"]

    # Day-grain-only diagnostic fields must never be a sortable Ticket Explorer
    # column -- they never reach the public projection either (§4.1).
    for private_field in (
        "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
        "guardrail_rules", "tpe_signals",
    ):
        with pytest.raises(ValueError, match="sort_by is invalid"):
            ticket_page(snapshot, sort_by=private_field, sort_direction="asc")

    with pytest.raises(ValueError, match="sort_by is invalid"):
        ticket_page(snapshot, sort_by="raw_payload", sort_direction="asc")
    with pytest.raises(ValueError, match="sort_direction is invalid"):
        ticket_page(snapshot, sort_by="turn_count", sort_direction="sideways")
    with pytest.raises(ValueError, match="sort_direction is invalid"):
        ticket_page(snapshot, sort_direction="desc")


def test_ticket_sort_value_falls_back_safely_for_alphanumeric_tpe_code():
    class ProjectedTicket:
        tpe_code = "ERR42"

    assert _ticket_sort_value(  # type: ignore[arg-type]
        ProjectedTicket(),
        "tpe_code",
    ) == ((1, "err"), (0, 42))


def test_storage_rejects_phone_in_a_new_dimension_field_and_schema_v5():
    value = _snapshot().storage_dict()
    value["tickets"][0]["issue_category"] = "gọi 0901234567"
    with pytest.raises(ValueError):
        DashboardSnapshot.from_storage_dict(value)
    value = _snapshot().storage_dict()
    value["schema_version"] = 5
    with pytest.raises(ValueError, match="unsupported dashboard storage schema_version"):
        DashboardSnapshot.from_storage_dict(value)


def test_ticket_row_reopen_is_a_nonnegative_count_and_gt4_is_cross_field_checked():
    fields = asdict(_snapshot().tickets[0])
    fields["reopen_lifetime"] = 2
    TicketRow(**fields)
    fields = asdict(_snapshot().tickets[0])
    fields["reopen_lifetime"] = -1
    with pytest.raises(ValueError, match="reopen_lifetime"):
        TicketRow(**fields)
    fields = asdict(_snapshot().tickets[0])
    fields["turn_count"] = 5
    fields["gt4_turn"] = False
    with pytest.raises(ValueError, match="gt4_turn"):
        TicketRow(**fields)


def test_ticket_row_transfer_reason_is_required_for_transfers_and_absent_otherwise():
    transferred = asdict(_snapshot().tickets[1])
    transferred["transferred"] = True
    transferred["transfer_reason"] = None
    with pytest.raises(ValueError, match="transfer_reason"):
        TicketRow(**transferred)

    not_transferred = asdict(_snapshot().tickets[0])
    not_transferred["transferred"] = False
    not_transferred["transfer_reason"] = "unknown"
    with pytest.raises(ValueError, match="transfer_reason"):
        TicketRow(**not_transferred)

    invalid = asdict(_snapshot().tickets[1])
    invalid["transfer_reason"] = "invented_reason"
    with pytest.raises(ValueError, match="transfer_reason"):
        TicketRow(**invalid)


def test_weekly_ai_mean_excludes_direct_cs_and_long_turns_use_strictly_more_than_three():
    four = [_meta(trace(f"four-{turn}", "145665", turn, f"2026-07-21T0{turn}:00:00Z", "AI reply")) for turn in range(4)]
    five = [_meta(trace(f"five-{turn}", "145666", turn, f"2026-07-22T0{turn}:00:00Z", "AI reply")) for turn in range(5)]
    direct = [_meta(trace("direct", "145667", 0, "2026-07-23T02:00:00Z", TRANSFER_TEXT))]
    view = project_dashboard(_run([*four, *five, *direct])).dashboard_dict()["views"]["mon_sun"]
    week = next(row for row in view["weekly"] if row["cohort_week"] == "2026-07-20")

    assert week["ai_reply_mean_ai_first"] == pytest.approx((4 + 5) / 2)
    assert week["gt4_turn_with_cs"] == 0
    assert week["gt4_turn_without_cs"] == 2


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
    fields = asdict(_snapshot().tickets[0])
    fields["tpe_status"] = "Thất bại"
    with pytest.raises(ValueError, match="tpe_status"):
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


def test_later_transfer_without_prior_ai_is_direct_cs_and_counts_as_transfer():
    first = _meta(trace("empty-first", "145665", 0, "2026-07-21T02:00:00Z", ""))
    later_transfer = _meta(trace("later-transfer", "145665", 1, "2026-07-21T03:00:00Z", TRANSFER_TEXT))
    snapshot = project_dashboard(_run([first, later_transfer]))

    row = snapshot.tickets[0]
    assert row.outcome == "direct_cs"
    assert row.transferred is True
    dashboard = snapshot.dashboard_dict()
    for view in dashboard["views"].values():
        assert view["totals"]["transfer_total"] == 1
        assert view["outcomes"]["direct_cs"] == 1
    assert DashboardSnapshot.from_storage_dict(snapshot.storage_dict()) == snapshot
