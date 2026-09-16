from __future__ import annotations

"""Interface tests for the A/B comparison layer.

``ab_test`` carries 650 lines of arm-splitting and percentile arithmetic that
nothing else in the suite reaches directly -- the only prior coverage ran
through ``web._AbTestBackgroundCache``, a private of another module. These
tests pin the semantics that fail *silently* when broken: the Langfuse ``-1``
latency sentinel, nearest-rank percentiles, the ticket-only arm gate, and the
caller-chosen arm order.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.traces import trace
from weekly_cs_report.ab_test import (
    DIMENSIONS,
    AbTestSnapshot,
    _extract_arm,
    _percentile,
    _trace_latency,
    aggregate_ab_snapshot,
    default_window,
)
from weekly_cs_report.categories import load_taxonomy

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"

ARM_OLD = "gemma-3-27b"
ARM_NEW = "gemma-4-12b"


@pytest.fixture()
def taxonomy():
    return load_taxonomy(TAXONOMY_PATH)


def arm_trace(
    trace_id: str,
    session_id: str,
    timestamp: str,
    *,
    arm: str,
    turn: int = 0,
    response: str = "Đã xử lý xong.",
    latency: float | None = None,
) -> dict:
    """A ticket trace carrying an arm identity, as Langfuse returns it."""
    raw = trace(trace_id, session_id, turn, timestamp, response)
    raw["input"]["model_info"] = {"model_core": arm, "model_guardrail": arm}
    if latency is not None:
        raw["latency"] = latency
    return raw


class TestTraceLatency:
    """Langfuse answers -1 when `metrics` was not requested; it is not a duration."""

    def test_sentinel_is_not_a_duration(self):
        assert _trace_latency({"latency": -1}) is None

    def test_real_latency_passes_through(self):
        assert _trace_latency({"latency": 2.5}) == 2.5

    def test_zero_is_a_real_duration(self):
        assert _trace_latency({"latency": 0}) == 0.0

    def test_missing_and_non_numeric_are_absent(self):
        assert _trace_latency({}) is None
        assert _trace_latency({"latency": "2.5"}) is None

    def test_bool_is_not_a_duration(self):
        # bool is an int subclass; True must not become 1.0 seconds.
        assert _trace_latency({"latency": True}) is None


class TestPercentile:
    """Nearest-rank, matching `pipeline.nearest_rank`."""

    def test_empty_has_no_percentile(self):
        assert _percentile([], 0.5) is None

    def test_single_value(self):
        assert _percentile([4.0], 0.95) == 4.0

    def test_nearest_rank_p50_takes_lower_middle(self):
        assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0

    def test_rank_rounds_up_not_down(self):
        # An odd length is what separates ceil from floor: rank 1.5 must
        # resolve to the 2nd value, not the 1st. An even length hides the
        # difference, so this case is the one that pins the rule.
        assert _percentile([1.0, 2.0, 3.0], 0.5) == 2.0
        assert _percentile([10.0, 20.0, 30.0, 40.0, 50.0], 0.7) == 40.0

    def test_p95_reaches_the_top(self):
        assert _percentile([float(n) for n in range(1, 101)], 0.95) == 95.0

    def test_input_order_does_not_matter(self):
        assert _percentile([3.0, 1.0, 2.0], 0.5) == _percentile([1.0, 2.0, 3.0], 0.5)


class TestExtractArm:
    """The arm is read only from a real ticket trace."""

    def test_reads_model_core(self):
        payload = {"source": "ticket", "model_info": {"model_core": ARM_OLD}}
        assert _extract_arm(payload) == ARM_OLD

    def test_direct_chat_has_no_arm(self):
        payload = {"source": "chat", "model_info": {"model_core": ARM_OLD}}
        assert _extract_arm(payload) is None

    def test_missing_model_info_has_no_arm(self):
        assert _extract_arm({"source": "ticket"}) is None

    def test_empty_model_core_has_no_arm(self):
        payload = {"source": "ticket", "model_info": {"model_core": ""}}
        assert _extract_arm(payload) is None

    def test_non_mapping_has_no_arm(self):
        assert _extract_arm(None) is None
        assert _extract_arm("gemma") is None


class TestDefaultWindow:
    """Monday 00:00 Vietnam time through now."""

    def test_starts_on_monday_local_midnight(self):
        now = datetime(2026, 9, 17, 10, 30, tzinfo=TZ)  # a Thursday
        start, end = default_window(now)
        start_local = start.astimezone(TZ)
        assert start_local.weekday() == 0
        assert (start_local.hour, start_local.minute) == (0, 0)
        assert start_local.date() == datetime(2026, 9, 14, tzinfo=TZ).date()
        assert end == now.astimezone(timezone.utc)

    def test_monday_yields_same_day_start(self):
        now = datetime(2026, 9, 14, 9, 0, tzinfo=TZ)
        start, _ = default_window(now)
        assert start.astimezone(TZ).date() == now.date()

    def test_naive_now_is_rejected(self):
        with pytest.raises(ValueError):
            default_window(datetime(2026, 9, 17, 10, 30))


class TestAggregateWindowGuards:
    def test_naive_bounds_are_rejected(self, taxonomy):
        start = datetime(2026, 9, 14, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            aggregate_ab_snapshot([], datetime(2026, 9, 14), start, taxonomy)

    def test_end_must_follow_start(self, taxonomy):
        start = datetime(2026, 9, 14, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            aggregate_ab_snapshot([], start, start, taxonomy)


class TestAggregateArms:
    def _window(self):
        return (
            datetime(2026, 9, 14, tzinfo=timezone.utc),
            datetime(2026, 9, 18, tzinfo=timezone.utc),
        )

    def test_empty_window_yields_empty_snapshot(self, taxonomy):
        start, end = self._window()
        snapshot = aggregate_ab_snapshot([], start, end, taxonomy)
        assert isinstance(snapshot, AbTestSnapshot)
        assert snapshot.total_tickets == 0
        assert snapshot.arms == ()
        assert snapshot.window_start == start
        assert snapshot.window_end == end

    def test_tickets_split_by_arm(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD),
            arm_trace("t2", "s2", "2026-09-15T03:00:00Z", arm=ARM_OLD),
            arm_trace("t3", "s3", "2026-09-15T04:00:00Z", arm=ARM_NEW),
        ]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert snapshot.total_tickets == 3
        counts = {arm.arm: arm.ticket_count for arm in snapshot.arms}
        assert counts == {ARM_OLD: 2, ARM_NEW: 1}

    def test_shares_sum_to_one(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD),
            arm_trace("t2", "s2", "2026-09-15T03:00:00Z", arm=ARM_NEW),
        ]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert sum(arm.share for arm in snapshot.arms) == pytest.approx(1.0)

    def test_small_samples_are_flagged_low(self, taxonomy):
        start, end = self._window()
        raw = [arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD)]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert snapshot.arms[0].low_sample is True

    def test_arms_argument_filters_and_orders(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD),
            arm_trace("t2", "s2", "2026-09-15T03:00:00Z", arm=ARM_NEW),
            arm_trace("t3", "s3", "2026-09-15T04:00:00Z", arm="gemma-experiment"),
        ]
        snapshot = aggregate_ab_snapshot(
            raw, start, end, taxonomy, arms=[ARM_NEW, ARM_OLD]
        )
        # Chronological caller order wins over the alphabetical fallback,
        # and the unlisted arm leaves the totals entirely.
        assert [arm.arm for arm in snapshot.arms] == [ARM_NEW, ARM_OLD]
        assert snapshot.total_tickets == 2

    def test_unfiltered_arms_sort_alphabetically(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_NEW),
            arm_trace("t2", "s2", "2026-09-15T03:00:00Z", arm=ARM_OLD),
        ]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert [arm.arm for arm in snapshot.arms] == sorted([ARM_OLD, ARM_NEW])

    def test_traces_without_an_arm_are_unmatched(self, taxonomy):
        start, end = self._window()
        plain = trace("t1", "s1", 0, "2026-09-15T02:00:00Z", "Đã xử lý xong.")
        snapshot = aggregate_ab_snapshot([plain], start, end, taxonomy)
        assert snapshot.total_tickets == 0
        assert snapshot.unmatched_tickets == 1

    def test_dimensions_cover_the_declared_vocabulary(self, taxonomy):
        start, end = self._window()
        raw = [arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD)]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert set(snapshot.dimensions) <= set(DIMENSIONS)

    def test_csat_absent_by_default(self, taxonomy):
        start, end = self._window()
        raw = [arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD)]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        assert snapshot.csat_available is False

    def test_csat_counts_land_on_the_owning_arm(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD),
            arm_trace("t2", "s2", "2026-09-15T03:00:00Z", arm=ARM_NEW),
        ]
        snapshot = aggregate_ab_snapshot(
            raw,
            start,
            end,
            taxonomy,
            csat_by_ticket={"s1": "positive"},
        )
        assert snapshot.csat_available is True
        by_arm = {arm.arm: arm for arm in snapshot.arms}
        assert by_arm[ARM_OLD].csat_response_count == 1
        assert by_arm[ARM_NEW].csat_response_count == 0

    def test_daily_points_stay_inside_the_window(self, taxonomy):
        start, end = self._window()
        raw = [
            arm_trace("t1", "s1", "2026-09-15T02:00:00Z", arm=ARM_OLD),
            arm_trace("t2", "s2", "2026-09-16T02:00:00Z", arm=ARM_OLD),
        ]
        snapshot = aggregate_ab_snapshot(raw, start, end, taxonomy)
        dates = {point.date for point in snapshot.daily}
        assert dates
        for day in dates:
            parsed = datetime.fromisoformat(day).replace(tzinfo=TZ)
            assert start - timedelta(days=1) <= parsed <= end + timedelta(days=1)
