from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from .models import CohortWindow

VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
WeekDefinition = Literal["mon_sun", "mon_fri"]
_LOOKBACK_DAYS = 14


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _monday_start_local(value: datetime) -> datetime:
    local_value = value.astimezone(VIETNAM_TIMEZONE)
    monday = local_value.date() - timedelta(days=local_value.weekday())
    return datetime.combine(monday, time.min, tzinfo=VIETNAM_TIMEZONE)


def build_cohort_window(as_of: datetime, weeks: int, include_wtd: bool) -> CohortWindow:
    _require_aware(as_of, "as_of")
    if weeks < 1:
        raise ValueError("weeks must be at least 1")

    complete_end_exclusive_local = _monday_start_local(as_of)
    complete_start_local = complete_end_exclusive_local - timedelta(weeks=weeks)
    wtd_start_local = complete_end_exclusive_local if include_wtd else None
    query_to_utc = (
        as_of.astimezone(timezone.utc)
        if include_wtd
        else complete_end_exclusive_local.astimezone(timezone.utc)
    )
    return CohortWindow(
        as_of=as_of,
        complete_start_local=complete_start_local,
        complete_end_exclusive_local=complete_end_exclusive_local,
        wtd_start_local=wtd_start_local,
        # A session can begin before the reporting range and continue inside it.
        # Fetching this fixed lookback makes its canonical first trace visible,
        # so it cannot be assigned to the wrong reporting week.
        query_from_utc=(
            complete_start_local - timedelta(days=_LOOKBACK_DAYS)
        ).astimezone(timezone.utc),
        query_to_utc=query_to_utc,
    )


def cohort_week_for(timestamp: datetime) -> date:
    _require_aware(timestamp, "timestamp")
    return _monday_start_local(timestamp).date()


def score_anchor_for(cohort_week: date) -> datetime:
    local_anchor = datetime.combine(cohort_week, time(12), tzinfo=VIETNAM_TIMEZONE)
    return local_anchor.astimezone(timezone.utc)


def is_week_fully_mature(
    cohort_week: date,
    as_of: datetime,
    week_definition: WeekDefinition = "mon_fri",
) -> bool:
    _require_aware(as_of, "as_of")
    if week_definition not in {"mon_sun", "mon_fri"}:
        raise ValueError("week_definition must be mon_sun or mon_fri")
    end_exclusive = datetime.combine(
        cohort_week + timedelta(days=7 if week_definition == "mon_sun" else 5),
        time.min,
        tzinfo=VIETNAM_TIMEZONE,
    )
    maturity_boundary = end_exclusive - timedelta(microseconds=1) + timedelta(hours=168)
    return as_of.astimezone(VIETNAM_TIMEZONE) >= maturity_boundary
