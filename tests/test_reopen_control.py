from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.fixtures.traces import TRANSFER_TEXT, trace
from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.classification import classify_session, normalize_trace
from weekly_cs_report.cohort import build_cohort_window
from weekly_cs_report.models import TraceRecord
from weekly_cs_report.pipeline import analyze_sessions, select_candidate_sessions


TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v1.json"
WINDOW = build_cohort_window(
    datetime(2026, 8, 4, 12, tzinfo=TZ), weeks=2, include_wtd=True
)


def _record(
    trace_id: str,
    session_id: str,
    turn: int,
    timestamp: str,
    response: object,
) -> TraceRecord:
    normalized = normalize_trace(trace(trace_id, session_id, turn, timestamp, response))
    assert isinstance(normalized, TraceRecord)
    return normalized


def _classify(*records: TraceRecord):
    return classify_session(records, WINDOW, TRANSFER_TEXT)


def _summary_for_july_20(records: list[TraceRecord]):
    selection = select_candidate_sessions(records, (), WINDOW)
    result = analyze_sessions(selection, load_taxonomy(TAXONOMY_PATH))
    summary = next(item for item in result.weekly_mon_sun if str(item.cohort_week) == "2026-07-20")
    return result, summary


def test_direct_cs_control_reopen_uses_canonical_first_without_turn_zero():
    within_seven_days = _classify(
        _record("direct-first", "direct-within", 7, "2026-07-20T02:00:00Z", TRANSFER_TEXT),
        _record("direct-later", "direct-within", 9, "2026-07-27T02:00:00Z", "Đã xử lý"),
    )
    after_seven_days = _classify(
        _record("late-first", "direct-late", 4, "2026-07-20T02:00:00Z", TRANSFER_TEXT),
        _record("late-later", "direct-late", 8, "2026-07-27T02:00:00.000001Z", "Đã xử lý"),
    )
    ai_first = _classify(
        _record("ai-first", "ai", 3, "2026-07-20T02:00:00Z", "Đã xử lý"),
        _record("ai-later", "ai", 4, "2026-07-21T02:00:00Z", "Đã xử lý tiếp"),
    )

    assert within_seven_days.outcome == "direct_cs"
    assert within_seven_days.turn0_trace_id == "direct-first"
    assert within_seven_days.control_reopen_within_7d == 1
    assert after_seven_days.control_reopen_within_7d == 0
    assert ai_first.control_reopen_within_7d is None


def test_direct_cs_control_does_not_change_published_reopen_metrics():
    ai_records = [
        _record("ai-first", "ai", 3, "2026-07-20T02:00:00Z", "Đã xử lý"),
        _record("ai-later", "ai", 4, "2026-07-21T02:00:00Z", "Đã xử lý tiếp"),
    ]
    direct_records = [
        _record("direct-first", "direct", 7, "2026-07-20T03:00:00Z", TRANSFER_TEXT),
        _record("direct-later", "direct", 9, "2026-07-21T03:00:00Z", "CS đã tiếp nhận"),
    ]

    _, baseline = _summary_for_july_20(ai_records)
    result, with_control = _summary_for_july_20(ai_records + direct_records)
    direct = next(item for item in result.sessions if item.session_id == "direct")

    assert (
        with_control.reopen_7d_rate,
        with_control.reopen_7d_denominator,
        with_control.reopen_lifetime_rate,
    ) == (
        baseline.reopen_7d_rate,
        baseline.reopen_7d_denominator,
        baseline.reopen_lifetime_rate,
    ) == (1.0, 1, 1.0)
    assert direct.reopen_within_7d is None
    assert direct.reopen_lifetime is None
    assert direct.control_reopen_within_7d == 1
