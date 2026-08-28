from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from inspect import signature
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.traces import TRANSFER_TEXT, trace
from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.classification import normalize_trace
from weekly_cs_report.cohort import build_cohort_window
from weekly_cs_report.enrichment import TraceEnrichment
from weekly_cs_report.models import (
    AnalysisResult,
    CategoryResult,
    InvariantError,
    QualityIssue,
    TraceRecord,
    TransferCategories,
)
from weekly_cs_report.pipeline import (
    analyze_sessions,
    evaluate_gates,
    normalize_raw_traces,
    select_candidate_sessions,
    summarize_same_period,
    summarize_weeks,
    validate_invariants,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v1.json"
TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


@pytest.fixture()
def taxonomy():
    return load_taxonomy(TAXONOMY_PATH)


@pytest.fixture()
def window():
    return build_cohort_window(
        datetime(2026, 7, 29, 12, tzinfo=TZ),
        weeks=2,
        include_wtd=True,
    )


def record(
    trace_id: str,
    session_id: str,
    turn_number: int,
    timestamp: str,
    response: object = "AI reply",
    *,
    title: object = "IBFT synthetic",
) -> TraceRecord:
    raw = trace(trace_id, session_id, turn_number, timestamp, response)
    raw["input"]["other_info"]["title"] = title
    if not isinstance(title, str):
        raw["input"]["other_info"]["meta"] = []
    normalized = normalize_trace(raw)
    assert isinstance(normalized, TraceRecord)
    return normalized


def select(records: list[TraceRecord], issues: list[QualityIssue], window):
    return select_candidate_sessions(records, issues, window)


def analyze(records: list[TraceRecord], issues: list[QualityIssue], window, taxonomy, loader=None):
    selection = select(records, issues, window)
    return analyze_sessions(selection, taxonomy)


def test_selection_keeps_no_turn_zero_and_weekend_starts_eligible(window):
    records = [
        record("weekday-0", "weekday", 0, "2026-07-24T02:00:00Z"),
        record("weekday-1", "weekday", 1, "2026-07-25T02:00:00Z"),
        record("weekend-0", "weekend", 0, "2026-07-25T02:00:00Z"),
        record("left-3", "left", 3, "2026-07-20T02:00:00Z"),
        record("invalid-0", "invalid", 0, "2026-07-21T02:00:00Z"),
        record("old-0", "old", 0, "2026-07-10T02:00:00Z"),
    ]
    issues = [
        QualityIssue("invalid_turn", "invalid", "invalid-bad", records[4].timestamp),
        QualityIssue("missing_session_id", None, "unkeyed", records[0].timestamp),
    ]

    result = select(records, issues, window)

    assert result.window is window
    assert tuple(result.eligible) == ("left", "weekday", "weekend")
    assert tuple(item.id for item in result.eligible["weekday"]) == ("weekday-0", "weekday-1")
    assert result.weekend_start == ()
    assert result.left_censored == ()
    assert tuple(issue.session_id for issue in result.invalid_keyed) == ("invalid",)
    assert tuple(issue.trace_id for issue in result.unkeyed) == ("unkeyed",)
    assert "old" not in {
        *result.eligible,
        *result.weekend_start,
        *result.left_censored,
        *(issue.session_id for issue in result.invalid_keyed),
    }


def test_keyed_issues_are_deduplicated_at_session_grain_and_override_other_groups(window):
    candidate = record("bad-0", "bad", 0, "2026-07-21T02:00:00Z")
    issues = [
        QualityIssue("invalid_turn", "bad", "bad-a", candidate.timestamp),
        QualityIssue("malformed_output", "bad", "bad-b", candidate.timestamp),
    ]

    result = select([candidate], issues, window)

    assert result.eligible == {}
    assert len(result.invalid_keyed) == 1
    assert result.invalid_keyed[0].session_id == "bad"


def test_keyed_issue_canonicalization_is_independent_of_input_order(window):
    candidate = record("bad-0", "bad", 0, "2026-07-21T02:00:00Z")
    later_reason = QualityIssue(
        "z_reason", "bad", "trace-z", candidate.timestamp + timedelta(hours=1)
    )
    canonical = QualityIssue("a_reason", "bad", "trace-a", candidate.timestamp)

    forward = select([candidate], [later_reason, canonical], window)
    reverse = select([candidate], [canonical, later_reason], window)

    assert forward.invalid_keyed == reverse.invalid_keyed == (canonical,)


def test_canonical_first_before_complete_start_is_counted_separately(window):
    records = [
        record("before", "continued", 0, "2026-07-12T16:00:00Z"),
        record("inside", "continued", 7, "2026-07-21T02:00:00Z"),
    ]

    result = select(records, [], window)

    assert result.eligible == {}
    assert result.pre_window_start == ("continued",)
    assert result.left_censored == ()


def test_session_wholly_inside_lookback_is_not_pre_window_start(window):
    records = [
        record("old-first", "old", 0, "2026-07-10T02:00:00Z"),
        record("old-last", "old", 1, "2026-07-11T02:00:00Z"),
    ]

    result = select(records, [], window)

    assert result.eligible == {}
    assert result.pre_window_start == ()


def test_pipeline_injects_v2_dimensions_from_canonical_first_trace(window):
    raw = trace("dimension-first", "dimension", 3, "2026-07-21T02:00:00Z", "AI reply")
    raw["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": "Thanh toán-IBFT", "sub_source": "tranxdetail"},
        "App": "241 - Chuyển Tiền ATM",
        "Product Code": "TF007 - IBFT",
        "Kênh thanh toán": "38 - TK Zalo Pay",
        "Mã lỗi TPE": "-217 Thất bại",
        "Step result": "-1|20|700212|mô tả không được xuất",
    }
    normalized = normalize_trace(raw)
    assert isinstance(normalized, TraceRecord)

    result = analyze([normalized], [], window, load_taxonomy(TAXONOMY_V2_PATH))
    metrics = result.sessions[0]

    assert metrics.data_quality == "no_turn_zero"
    assert metrics.dimensions.issue_category == "Thanh toán-IBFT"
    assert metrics.dimensions.tpe_code == "-217"
    assert metrics.dimensions.tpe_step is None
    assert metrics.dimensions.tpe_case is None
    assert metrics.dimensions.tpe_status_canonical is None
    assert metrics.dimensions.tpe_signals == ()


def test_pipeline_uses_only_exact_source_tpe_signals_from_trace_enrichment(window):
    raw = trace(
        "dimension-first",
        "dimension",
        0,
        "2026-07-21T02:00:00Z",
        TRANSFER_TEXT,
    )
    raw["input"]["other_info"]["meta"] = {
        "Mã lỗi TPE": "-217 Thất bại",
        "Step result": "-1|20|700212|không được dùng",
    }
    normalized = normalize_trace(raw)
    assert isinstance(normalized, TraceRecord)

    result = analyze_sessions(
        select([normalized], [], window),
        load_taxonomy(TAXONOMY_V2_PATH),
        trace_enrichment={
            "dimension-first": TraceEnrichment(
                tpe_signals=(("-365", "-1013"),)
            )
        },
    )
    dimensions = result.sessions[0].dimensions

    assert dimensions.tpe_signals == (("-365", "-1013"),)
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None
    assert dimensions.tpe_status_canonical is None


def test_pipeline_has_no_backfill_argument_and_uses_raw_first_trace(window):
    raw = trace("overlay", "145665", 4, "2026-07-21T02:00:00Z", "AI reply")
    raw["input"]["other_info"]["meta"] = {"Thông tin thêm": {}}
    normalized = normalize_trace(raw)
    assert isinstance(normalized, TraceRecord)

    assert "dimension_backfill" not in signature(analyze_sessions).parameters
    result = analyze_sessions(
        select([normalized], [], window),
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert result.sessions[0].dimensions.issue_category == "Không xác định"
    assert result.sessions[0].dimensions.tpe_code is None


def test_v2_pipeline_does_not_request_legacy_observations_or_emit_keyword_fallbacks(window):
    raw = trace("transfer", "145665", 0, "2026-07-21T02:00:00Z", TRANSFER_TEXT)
    raw["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": "Thanh toán-IBFT"},
        "Mã lỗi TPE": "-217 Thất bại",
        "Step result": "-1|20|700212|không xuất",
    }
    normalized = normalize_trace(raw)
    assert isinstance(normalized, TraceRecord)
    result = analyze_sessions(
        select([normalized], [], window),
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    categories = result.transfers["145665"]
    assert categories.business.value == "not_applicable"
    assert categories.tpe.value == "not_applicable"
    assert categories.guardrail_rule.value == "not_applicable"
    assert {categories.business.value, categories.tpe.value, categories.guardrail_rule.value}.isdisjoint({"other", "unknown"})


def test_no_turn_zero_followups_and_tie_break_use_full_canonical_key(window):
    records = [
        record("z", "no-zero", 3, "2026-07-21T03:00:00Z", "later AI"),
        record("b", "no-zero", 2, "2026-07-21T02:00:00Z", "first AI"),
        record("a", "tie", 4, "2026-07-21T02:00:00Z", "first by id"),
        record("b", "tie", 4, "2026-07-21T02:00:00Z", "second by id"),
    ]

    result = analyze(records, [], window, taxonomy=load_taxonomy(TAXONOMY_PATH))
    no_zero = next(item for item in result.sessions if item.session_id == "no-zero")
    tie = next(item for item in result.sessions if item.session_id == "tie")

    assert no_zero.turn0_trace_id == "b"
    assert no_zero.data_quality == "no_turn_zero"
    assert no_zero.reopen_lifetime == 1
    assert tie.turn0_trace_id == "a"


def test_normalizer_deduplicates_a_repeated_trace_id_before_turn_count(window):
    raw = trace("same", "dedup", 3, "2026-07-21T02:00:00Z", "AI reply")
    records, issues, deduplicated = normalize_raw_traces([raw, dict(raw)])

    result = analyze(list(records), list(issues), window, load_taxonomy(TAXONOMY_PATH))

    assert deduplicated == 1
    assert result.sessions[0].turn_count == 1


def test_maturity_masks_only_summary_for_the_requested_week_definition():
    maturity_window = build_cohort_window(
        datetime(2026, 8, 2, 23, tzinfo=TZ), weeks=1, include_wtd=False
    )
    records = [
        record("friday-first", "friday", 3, "2026-07-24T02:00:00Z", "AI reply"),
        record("friday-later", "friday", 4, "2026-07-25T02:00:00Z", "AI reply"),
    ]
    result = analyze(records, [], maturity_window, load_taxonomy(TAXONOMY_PATH))

    mon_sun = summarize_weeks(result, maturity_window, "mon_sun")
    mon_fri = summarize_weeks(result, maturity_window, "mon_fri")

    assert result.sessions[0].reopen_within_7d == 1
    assert mon_sun[0].reopen_7d_rate is None
    assert mon_fri[0].reopen_7d_rate == 1.0


def test_duplicate_positive_turn_remains_eligible_with_a_diagnostic(window):
    records = [
        record("left-3a", "left", 3, "2026-07-20T02:00:00Z"),
        record("left-3b", "left", 3, "2026-07-20T03:00:00Z"),
    ]

    result = select(records, [], window)

    assert result.left_censored == ()
    assert tuple(result.eligible) == ("left",)
    assert result.invalid_keyed == ()


def test_left_censored_and_unkeyed_issues_do_not_dilute_the_structural_rate(
    window, taxonomy
):
    records = [
        record(f"valid-{index}-0", f"valid-{index}", 0, "2026-07-21T02:00:00Z")
        for index in range(19)
    ]
    records.extend(
        record(f"left-{index}-3", f"left-{index}", 3, "2026-07-21T03:00:00Z")
        for index in range(50)
    )
    issues = [
        QualityIssue("invalid_turn", "invalid", "invalid-trace", records[0].timestamp),
        *(
            QualityIssue("missing_session_id", None, f"unkeyed-{index}", records[0].timestamp)
            for index in range(50)
        ),
    ]

    result = analyze(records, issues, window, taxonomy)

    assert len(result.sessions) == 69
    assert len(result.selection.left_censored) == 0
    assert len(result.selection.unkeyed) == 50
    assert result.gate_status.core_allowed is True


def test_analysis_quarantines_classification_issues_without_per_transfer_observation_reads(
    window, taxonomy
):
    records = [
        record("valid-0", "valid", 0, "2026-07-21T02:00:00Z"),
        record("transfer-0", "transfer", 0, "2026-07-21T03:00:00Z", TRANSFER_TEXT),
        record("duplicate-0", "duplicate", 0, "2026-07-21T04:00:00Z"),
        record("duplicate-1a", "duplicate", 1, "2026-07-21T05:00:00Z"),
        record("duplicate-1b", "duplicate", 1, "2026-07-21T06:00:00Z"),
    ]
    calls: list[str] = []

    def loader(trace_id: str):
        calls.append(trace_id)
        return []

    result = analyze(records, [], window, taxonomy, loader)

    assert tuple(session.session_id for session in result.sessions) == ("duplicate", "transfer", "valid")
    duplicate = next(item for item in result.sessions if item.session_id == "duplicate")
    assert duplicate.data_quality == "duplicate_turn"
    assert result.selection.invalid_keyed == ()
    assert calls == []
    assert set(result.transfers) == {"transfer"}


def test_weekly_summaries_reconcile_use_nearest_rank_and_include_empty_weeks(
    window, taxonomy
):
    records = [
        record("direct-0", "direct", 0, "2026-07-14T02:00:00Z", TRANSFER_TEXT),
        record("one-0", "one", 0, "2026-07-14T03:00:00Z"),
        record("two-0", "two", 0, "2026-07-14T04:00:00Z"),
        record("two-1", "two", 1, "2026-07-14T05:00:00Z", TRANSFER_TEXT),
        record("ten-0", "ten", 0, "2026-07-14T06:00:00Z"),
        *[
            record(
                f"ten-{turn_number}",
                "ten",
                turn_number,
                f"2026-07-{14 + turn_number:02d}T06:00:00Z",
            )
            for turn_number in range(1, 10)
        ],
        record("immature-0", "immature", 0, "2026-07-21T02:00:00Z"),
        record("immature-1", "immature", 1, "2026-07-22T02:00:00Z"),
    ]

    result = analyze(records, [], window, taxonomy)
    summaries = summarize_weeks(result, window)
    mature, immature, wtd = summaries

    assert [summary.cohort_week for summary in summaries] == [
        date(2026, 7, 13),
        date(2026, 7, 20),
        date(2026, 7, 27),
    ]
    assert mature.ai_first_count == mature.ai_end_to_end_count + mature.ai_then_cs_count
    assert mature.total_tickets == (
        mature.ai_end_to_end_count
        + mature.ai_then_cs_count
        + mature.direct_cs_count
        + mature.unclassified_count
    )
    assert mature.ai_reply_p50 == 1
    assert mature.ai_reply_p90 == 10
    assert mature.ai_reply_max == 10
    assert mature.reopen_7d_denominator == 3
    assert mature.reopen_7d_rate == pytest.approx(2 / 3)
    assert immature.reopen_7d_rate is None
    assert immature.reopen_7d_denominator is None
    immature_session = next(item for item in result.sessions if item.session_id == "immature")
    assert immature_session.reopen_lifetime == 1
    assert immature_session.reopen_within_7d == 1
    assert wtd.total_tickets == 0
    assert wtd.ai_first_rate == 0.0
    assert wtd.reopen_lifetime_rate is None


def test_resolved_first_reply_counts_only_ai_end_to_end_with_exactly_one_reply(
    window, taxonomy
):
    records = [
        # ai_end_to_end, ai_reply_count == 1 -> counted
        record("one-reply-0", "one-reply", 0, "2026-07-21T02:00:00Z"),
        # ai_end_to_end, ai_reply_count == 2 -> NOT counted
        record("two-reply-0", "two-reply", 0, "2026-07-21T02:00:00Z"),
        record("two-reply-1", "two-reply", 1, "2026-07-21T03:00:00Z"),
        # ai_then_cs with exactly one AI reply before transfer -> NOT counted
        # (wrong outcome, even though ai_reply_count == 1)
        record(
            "then-cs-0", "then-cs", 0, "2026-07-21T02:00:00Z"
        ),
        record(
            "then-cs-1", "then-cs", 1, "2026-07-21T03:00:00Z", TRANSFER_TEXT
        ),
    ]

    result = analyze(records, [], window, taxonomy)
    summaries = summarize_weeks(result, window)
    mature = next(
        summary
        for summary in summaries
        if summary.cohort_week == date(2026, 7, 20)
    )

    one_reply = next(s for s in result.sessions if s.session_id == "one-reply")
    two_reply = next(s for s in result.sessions if s.session_id == "two-reply")
    then_cs = next(s for s in result.sessions if s.session_id == "then-cs")
    assert one_reply.outcome == "ai_end_to_end" and one_reply.ai_reply_count == 1
    assert two_reply.outcome == "ai_end_to_end" and two_reply.ai_reply_count == 2
    assert then_cs.outcome == "ai_then_cs" and then_cs.ai_reply_count == 1

    assert mature.resolved_first_reply == 1


def test_resolved_first_reply_is_zero_not_none_for_empty_week(window, taxonomy):
    result = analyze([], [], window, taxonomy)
    summaries = summarize_weeks(result, window)

    assert all(summary.resolved_first_reply == 0 for summary in summaries)


def test_summarize_rejects_a_window_that_differs_from_the_analysis_window(
    window, taxonomy
):
    result = analyze([], [], window, taxonomy)
    drifted_window = replace(window, as_of=window.as_of + timedelta(minutes=1))

    with pytest.raises(InvariantError):
        summarize_weeks(result, drifted_window)


def test_twelve_week_contract_emits_twelve_complete_rows_and_one_wtd(taxonomy):
    production_window = build_cohort_window(
        datetime(2026, 7, 29, 12, tzinfo=TZ),
        weeks=12,
        include_wtd=True,
    )
    result = analyze([], [], production_window, taxonomy)

    summaries = summarize_weeks(result, production_window)

    assert len(summaries) == 13
    assert [summary.cohort_status for summary in summaries].count("complete") == 12
    assert [summary.cohort_status for summary in summaries].count("wtd") == 1


def _same_period_result(
    taxonomy,
    *,
    as_of: datetime = datetime(2026, 7, 30, 10, tzinfo=TZ),
    weeks: int = 4,
    records: list[TraceRecord] | None = None,
) -> AnalysisResult:
    period_window = build_cohort_window(as_of, weeks=weeks, include_wtd=True)
    return analyze(records or [], [], period_window, taxonomy)


def _ai_session(
    week: date,
    suffix: str,
    local_day: int,
    taxonomy,
    *,
    as_of: datetime = datetime(2026, 7, 30, 10, tzinfo=TZ),
    response: object = "AI reply",
) -> TraceRecord:
    local_timestamp = datetime.combine(
        week + timedelta(days=local_day),
        datetime.min.time().replace(hour=9),
        tzinfo=TZ,
    )
    return record(
        f"{week.isoformat()}-{suffix}",
        f"{week.isoformat()}-{suffix}",
        0,
        local_timestamp.astimezone(ZoneInfo("UTC")).isoformat(),
        response,
    )


def test_same_period_truncates_every_week_at_the_same_completed_day(taxonomy):
    weeks = [date(2026, 6, 29), date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20)]
    records: list[TraceRecord] = []
    for week in weeks:
        records.extend(
            [
                _ai_session(week, "mon", 0, taxonomy),
                _ai_session(week, "wed", 2, taxonomy, response=TRANSFER_TEXT),
                _ai_session(week, "fri", 4, taxonomy),
            ]
        )
    records.extend(
        [
            _ai_session(date(2026, 7, 27), "mon", 0, taxonomy),
            _ai_session(date(2026, 7, 27), "wed", 2, taxonomy, response=TRANSFER_TEXT),
            _ai_session(date(2026, 7, 27), "thu", 3, taxonomy),
        ]
    )
    result = _same_period_result(taxonomy, records=records)

    same_period = summarize_same_period(result, "mon_sun")

    assert same_period is not None
    assert same_period.cutoff_date == date(2026, 7, 29)
    assert same_period.cutoff_weekday == 3
    assert same_period.current.total_tickets == 2
    assert same_period.current.ai_first_count == 1
    assert same_period.baseline.weeks_used == 4
    assert same_period.baseline.ai_first_rate == pytest.approx(0.5)
    assert set(same_period.by_week) == {
        date(2026, 6, 29),
        date(2026, 7, 6),
        date(2026, 7, 13),
        date(2026, 7, 20),
        date(2026, 7, 27),
    }
    assert all(summary.total_tickets == 2 for summary in same_period.by_week.values())


def test_same_period_is_null_on_monday_when_no_day_has_completed(taxonomy):
    result = _same_period_result(
        taxonomy,
        as_of=datetime(2026, 7, 27, 10, tzinfo=TZ),
        records=[
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
            _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        ],
    )

    assert summarize_same_period(result, "mon_sun") is None


def test_same_period_is_null_when_the_current_week_is_complete(taxonomy):
    result = _same_period_result(
        taxonomy,
        as_of=datetime(2026, 8, 1, 10, tzinfo=TZ),
        records=[
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
            _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        ],
    )

    assert summarize_same_period(result, "mon_fri") is None


def test_same_period_by_week_includes_the_running_truncated_week(taxonomy):
    result = _same_period_result(
        taxonomy,
        records=[
            _ai_session(date(2026, 7, 27), "current", 0, taxonomy),
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
            _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        ],
    )

    same_period = summarize_same_period(result, "mon_sun")

    assert same_period is not None
    assert same_period.current.cohort_week == date(2026, 7, 27)
    assert date(2026, 7, 27) in same_period.by_week


def test_same_period_is_computed_independently_for_mon_fri_and_mon_sun(taxonomy):
    result = _same_period_result(
        taxonomy,
        as_of=datetime(2026, 8, 1, 10, tzinfo=TZ),
        records=[
            _ai_session(date(2026, 7, 27), "current", 0, taxonomy),
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
            _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        ],
    )

    assert summarize_same_period(result, "mon_fri") is None
    assert summarize_same_period(result, "mon_sun") is not None


def test_mon_fri_current_row_is_complete_after_friday_has_finished(taxonomy):
    result = _same_period_result(
        taxonomy,
        as_of=datetime(2026, 8, 2, 10, tzinfo=TZ),  # Sunday in Vietnam
        records=[
            _ai_session(date(2026, 7, 27), "current", 4, taxonomy),
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
        ],
    )

    mon_fri = summarize_weeks(result, result.selection.window, "mon_fri")
    mon_sun = summarize_weeks(result, result.selection.window, "mon_sun")

    assert mon_fri[-1].cohort_week == date(2026, 7, 27)
    assert mon_fri[-1].cohort_status == "complete"
    assert mon_sun[-1].cohort_status == "wtd"


def test_same_period_baseline_skips_empty_weeks_rather_than_counting_them_as_zero(taxonomy):
    records = [
        _ai_session(date(2026, 7, 27), "current", 0, taxonomy),
        _ai_session(date(2026, 7, 20), "after-cutoff", 4, taxonomy, response=TRANSFER_TEXT),
        _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        _ai_session(date(2026, 7, 6), "baseline", 0, taxonomy),
        _ai_session(date(2026, 6, 29), "baseline", 0, taxonomy),
    ]
    result = _same_period_result(taxonomy, weeks=5, records=records)

    same_period = summarize_same_period(result, "mon_sun")

    assert same_period is not None
    assert same_period.baseline.weeks_used == 3
    assert same_period.baseline.ai_first_rate == pytest.approx(1.0)
    assert same_period.by_week[date(2026, 7, 20)].total_tickets == 0


def test_same_period_keeps_an_empty_running_week_when_baselines_qualify(taxonomy):
    result = _same_period_result(
        taxonomy,
        records=[
            _ai_session(date(2026, 7, 20), "baseline", 0, taxonomy),
            _ai_session(date(2026, 7, 13), "baseline", 0, taxonomy),
        ],
    )

    same_period = summarize_same_period(result, "mon_sun")

    assert same_period is not None
    assert same_period.current.cohort_week == date(2026, 7, 27)
    assert same_period.current.total_tickets == 0


def known_observations(taxonomy):
    mapping = taxonomy.tpe_mappings[0]
    return [
        {
            "metadata": {
                "tool_name": "get_transaction_processing_engine_data",
                "blocked": True,
                "rule": "synthetic_policy",
            },
            "output": {
                "result": {
                    "transstatus": mapping["code"],
                    "stepresult": mapping["step"],
                }
            },
        }
    ]


def transferred_records(count: int, *, unknown_business: set[int] = frozenset()):
    return [
        record(
            f"transfer-{index}-0",
            f"transfer-{index}",
            0,
            f"2026-07-21T{index:02d}:00:00Z",
            TRANSFER_TEXT,
            title=7 if index in unknown_business else "IBFT synthetic",
        )
        for index in range(count)
    ]


def test_structural_invalid_rate_above_five_percent_blocks_every_family(window, taxonomy):
    records = transferred_records(18)
    issues = [QualityIssue("invalid_turn", "invalid", "bad", records[0].timestamp)]

    result = analyze(
        records,
        issues,
        window,
        taxonomy,
        lambda _trace_id: known_observations(taxonomy),
    )

    assert result.gate_status.core_allowed is False
    assert result.gate_status.business_allowed is False
    assert result.gate_status.tpe_allowed is False
    assert result.gate_status.guardrail_allowed is False
    assert "structural_invalid_rate_gt_5pct" in result.gate_status.reasons


def test_structural_invalid_rate_at_exactly_five_percent_does_not_block(window, taxonomy):
    records = transferred_records(19)
    issues = [QualityIssue("invalid_turn", "invalid", "bad", records[0].timestamp)]

    result = analyze(records, issues, window, taxonomy, lambda _trace_id: known_observations(taxonomy))

    assert result.gate_status.structural_invalid_rate == pytest.approx(0.05)
    assert result.gate_status.core_allowed is True
    assert result.gate_status.reasons == ()


def test_legacy_business_unknown_rate_never_blocks_v3_display(window, taxonomy):
    records = transferred_records(6, unknown_business={0, 1})

    result = analyze(
        records,
        [],
        window,
        taxonomy,
        lambda _trace_id: known_observations(taxonomy),
    )

    assert result.gate_status.core_allowed is True
    assert result.gate_status.business_allowed is True
    assert result.gate_status.tpe_allowed is True
    assert result.gate_status.guardrail_allowed is True
    assert result.gate_status.reasons == ()


def test_legacy_joint_unknown_rate_never_blocks_v3_display(
    window, taxonomy
):
    records = transferred_records(3)

    result = analyze(
        records,
        [],
        window,
        taxonomy,
        lambda trace_id: (
            known_observations(taxonomy) if trace_id == "transfer-2-0" else []
        ),
    )

    assert result.gate_status.core_allowed is True
    assert result.gate_status.business_allowed is True
    assert result.gate_status.tpe_allowed is True
    assert result.gate_status.guardrail_allowed is True
    assert result.gate_status.reasons == ()


def test_family_gate_thresholds_are_strict(window, taxonomy):
    records = transferred_records(20, unknown_business={0, 1, 2, 3})
    issues = [QualityIssue("invalid_turn", "invalid", "bad", records[0].timestamp)]

    result = analyze(
        records,
        issues,
        window,
        taxonomy,
        lambda trace_id: (
            [] if int(trace_id.split("-")[1]) < 10 else known_observations(taxonomy)
        ),
    )

    assert evaluate_gates(result).core_allowed is True
    assert evaluate_gates(result).business_allowed is True
    assert evaluate_gates(result).tpe_allowed is True
    assert evaluate_gates(result).guardrail_allowed is True
    assert evaluate_gates(result).reasons == ()


def valid_result(window, taxonomy) -> AnalysisResult:
    records = [
        record("plain-0", "plain", 0, "2026-07-14T02:00:00Z"),
        record("transfer-0", "transfer", 0, "2026-07-14T03:00:00Z", TRANSFER_TEXT),
    ]
    return analyze(
        records,
        [],
        window,
        taxonomy,
        lambda _trace_id: known_observations(taxonomy),
    )


def test_analysis_captures_one_fixed_as_of_on_sessions_and_weekly_summaries(
    window, taxonomy
):
    result = valid_result(window, taxonomy)

    assert {session.as_of for session in result.sessions} == {window.as_of}
    assert {summary.as_of for summary in result.weekly} == {window.as_of}


def test_invariants_check_every_weekly_reconciliation(window, taxonomy):
    result = valid_result(window, taxonomy)
    broken_week = replace(result.weekly[-1], total_tickets=1)
    broken = replace(result, weekly=(*result.weekly[:-1], broken_week))

    with pytest.raises(InvariantError):
        validate_invariants(broken)


def test_invariants_accept_weekend_sessions_when_the_flag_matches(window, taxonomy):
    result = valid_result(window, taxonomy)
    weekend = replace(
        result.sessions[0],
        session_id="weekend",
        cohort_status="complete",
        cohort_week=date(2026, 7, 20),
        is_weekend_start=True,
        turn0_timestamp=datetime(2026, 7, 25, 2, tzinfo=ZoneInfo("UTC")),
    )
    eligible = dict(result.selection.eligible)
    eligible["weekend"] = result.selection.eligible["plain"]
    expanded = replace(
        result,
        sessions=(*result.sessions, weekend),
        selection=replace(result.selection, eligible=eligible),
    )
    expanded = replace(
        expanded,
        weekly=summarize_weeks(expanded, window),
        gate_status=evaluate_gates(expanded),
    )
    validate_invariants(expanded)


def test_invariants_require_categories_exactly_for_transferred_sessions(window, taxonomy):
    result = valid_result(window, taxonomy)

    with pytest.raises(InvariantError):
        validate_invariants(replace(result, transfers={}))

    extra = dict(result.transfers)
    extra["plain"] = TransferCategories(
        business=CategoryResult("other"),
        tpe=CategoryResult("unknown"),
        guardrail_rule=CategoryResult("unknown"),
    )
    with pytest.raises(InvariantError):
        validate_invariants(replace(result, transfers=extra))


def test_invariants_require_analyzed_session_ids_to_equal_eligible_ids(window, taxonomy):
    result = valid_result(window, taxonomy)
    retained_sessions = tuple(
        session for session in result.sessions if session.session_id != "plain"
    )
    interim = replace(result, sessions=retained_sessions)
    broken = replace(
        interim,
        weekly=summarize_weeks(interim, window),
        gate_status=evaluate_gates(interim),
    )

    with pytest.raises(InvariantError):
        validate_invariants(broken)


def test_invariants_reject_candidate_group_overlap(window, taxonomy):
    result = valid_result(window, taxonomy)
    overlapping_selection = replace(
        result.selection,
        weekend_start=(*result.selection.weekend_start, "plain"),
    )

    with pytest.raises(InvariantError):
        validate_invariants(replace(result, selection=overlapping_selection))


def test_invariants_require_unkeyed_issues_to_have_no_session_id(window, taxonomy):
    result = valid_result(window, taxonomy)
    malformed_unkeyed = QualityIssue(
        "missing_session_id",
        "plain",
        "trace-with-session",
        result.sessions[0].turn0_timestamp,
    )
    broken_selection = replace(result.selection, unkeyed=(malformed_unkeyed,))

    with pytest.raises(InvariantError):
        validate_invariants(replace(result, selection=broken_selection))


def test_invariants_reject_duplicate_tuple_ids(window, taxonomy):
    result = valid_result(window, taxonomy)
    duplicate_weekend = replace(
        result.selection, weekend_start=("weekend", "weekend")
    )
    with pytest.raises(InvariantError):
        validate_invariants(replace(result, selection=duplicate_weekend))

    duplicate_left = replace(result.selection, left_censored=("left", "left"))
    with pytest.raises(InvariantError):
        validate_invariants(replace(result, selection=duplicate_left))

    duplicate_issue = QualityIssue(
        "invalid_turn",
        "invalid",
        "invalid-trace",
        result.sessions[0].turn0_timestamp,
    )
    duplicate_invalid = replace(
        result.selection, invalid_keyed=(duplicate_issue, duplicate_issue)
    )
    duplicate_invalid_result = replace(
        result,
        selection=duplicate_invalid,
        gate_status=evaluate_gates(replace(result, selection=duplicate_invalid)),
    )
    with pytest.raises(InvariantError):
        validate_invariants(duplicate_invalid_result)
