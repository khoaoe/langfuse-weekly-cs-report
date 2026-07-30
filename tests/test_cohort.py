from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weekly_cs_report.cohort import (
    build_cohort_window,
    cohort_week_for,
    is_week_fully_mature,
    score_anchor_for,
)
from weekly_cs_report.models import (
    CohortWindow,
    QualityIssue,
    ScoreSpec,
    SessionMetrics,
    TraceRecord,
    TransferCategories,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def test_window_has_twelve_complete_weeks_and_wtd():
    window = build_cohort_window(
        datetime(2026, 7, 29, 12, tzinfo=TZ),
        weeks=12,
        include_wtd=True,
    )
    assert window.complete_start_local == datetime(2026, 5, 4, 0, tzinfo=TZ)
    assert window.complete_end_exclusive_local == datetime(2026, 7, 27, 0, tzinfo=TZ)
    assert window.wtd_start_local == datetime(2026, 7, 27, 0, tzinfo=TZ)
    assert window.query_from_utc == datetime(2026, 4, 19, 17, tzinfo=timezone.utc)


def test_score_anchor_stays_in_monday_utc_bucket():
    anchor = score_anchor_for(date(2026, 7, 27))
    assert anchor == datetime(2026, 7, 27, 5, tzinfo=timezone.utc)
    assert anchor.weekday() == 0


def test_week_maturity_waits_until_last_friday_ticket_has_168_hours():
    assert not is_week_fully_mature(
        date(2026, 7, 20),
        datetime(2026, 7, 31, 22, 59, 59, tzinfo=TZ),
    )
    assert is_week_fully_mature(
        date(2026, 7, 20),
        datetime(2026, 7, 31, 23, 59, 59, 999999, tzinfo=TZ),
    )


def test_week_maturity_uses_the_selected_view_boundary():
    as_of = datetime(2026, 8, 2, 22, 59, 59, tzinfo=TZ)
    assert is_week_fully_mature(date(2026, 7, 20), as_of, "mon_fri")
    assert not is_week_fully_mature(date(2026, 7, 20), as_of, "mon_sun")


def test_cohort_week_uses_vietnam_business_time():
    assert cohort_week_for(datetime(2026, 7, 26, 18, tzinfo=timezone.utc)) == date(2026, 7, 27)


def test_cohort_functions_reject_naive_datetimes():
    with pytest.raises(ValueError):
        build_cohort_window(datetime(2026, 7, 29, 12), weeks=12, include_wtd=True)
    with pytest.raises(ValueError):
        cohort_week_for(datetime(2026, 7, 26, 18))
    with pytest.raises(ValueError):
        is_week_fully_mature(date(2026, 7, 20), datetime(2026, 7, 31, 23, 59, 59))


def test_declared_models_are_immutable_value_records():
    as_of = datetime(2026, 7, 29, 12, tzinfo=TZ)
    window = CohortWindow(as_of, as_of, as_of, None, as_of.astimezone(timezone.utc), as_of.astimezone(timezone.utc))
    with pytest.raises(FrozenInstanceError):
        window.as_of = as_of  # type: ignore[misc]

    assert TraceRecord("trace", "session", as_of, 0, {}, {}, "production").id == "trace"
    assert QualityIssue("missing", None, None, None).reason == "missing"
    assert ScoreSpec("score", "event", "name", 1.0, "NUMERIC", "session", as_of, "production", {}).id == "score"
    assert SessionMetrics
    assert TransferCategories
