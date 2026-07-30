from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

import pytest

from tests.fixtures.traces import TRANSFER_TEXT, trace
from weekly_cs_report.dashboard_cache import ProtectedSnapshotStore
from weekly_cs_report.dashboard_schema import DashboardSnapshot, project_dashboard
from weekly_cs_report.reopen_shadow import (
    ReopenReasonShadow,
    ShadowCoverageCount,
    ShadowReasonCount,
    pending_shadow,
)
from weekly_cs_report.report import compute_report


TZ = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=TZ)
TAXONOMY = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


class FakeClient:
    def __init__(self, traces):
        self.traces = traces

    def iter_traces(self, _from, _to):
        yield from self.traces

    def list_observations(self, _trace_id):
        return []


def _meta(raw: dict) -> dict:
    raw["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": "Thanh toán-IBFT"},
        "App": "241 - Chuyển Tiền ATM",
        "Product Code": "TF007 - IBFT",
    }
    return raw


def _run():
    traces = [
        _meta(trace("ai-first", "145665", 0, "2026-07-20T02:00:00Z", "AI reply")),
        _meta(trace("ai-later", "145665", 1, "2026-07-21T02:00:00Z", "AI reply again")),
        _meta(trace("direct-first", "145666", 0, "2026-07-20T03:00:00Z", TRANSFER_TEXT)),
        _meta(trace("direct-later", "145666", 1, "2026-07-21T03:00:00Z", "CS reply")),
    ]
    return compute_report(
        FakeClient(traces), as_of=AS_OF, weeks=2, include_current_wtd=True, taxonomy_path=TAXONOMY
    )


def test_shadow_pending_is_present_on_each_weekly_row_for_both_views_without_weekend_skip():
    dashboard = project_dashboard(_run()).dashboard_dict()

    for view in dashboard["views"].values():
        for weekly in view["weekly"]:
            reason = weekly["reopen_reason"]
            assert set(reason) == {
                "labels_version", "status", "counts", "by_business", "coverage", "control"
            }
            assert reason["labels_version"] == "v1"
            assert reason["status"] == "pending"
            assert reason["counts"] == {}
            assert reason["by_business"] == {}
            assert set(reason["coverage"]) == {"population", "labeled", "abstained", "failed", "invalid"}
            assert "skipped_weekend_start" not in reason["coverage"]
            assert reason["coverage"]["labeled"] == 0
            if weekly["reopen_7d_rate"] is None:
                assert reason["control"] == {
                    "direct_cs_reopen_7d_rate": None,
                    "direct_cs_denominator": 0,
                }


def test_injected_labeled_shadow_projects_counts_by_outcome_and_issue_category_only():
    run = _run()
    ai = next(item for item in run.result.sessions if item.session_id == "145665")
    shadow = ReopenReasonShadow(
        labels_version="v1",
        status="labeled",
        counts=(
            ShadowReasonCount(
                cohort_week=ai.cohort_week,
                outcome=ai.outcome,
                issue_category=ai.dimensions.issue_category,
                label="ai_wrong_content",
                count=1,
                is_weekend_start=False,
            ),
        ),
    )

    dashboard = project_dashboard(replace(run, reopen_shadow=shadow)).dashboard_dict()
    weekly = next(
        row for row in dashboard["views"]["mon_sun"]["weekly"]
        if row["cohort_week"] == "2026-07-20"
    )
    reason = weekly["reopen_reason"]

    assert reason["status"] == "labeled"
    assert reason["counts"] == {"ai_wrong_content": {"ai_end_to_end": 1}}
    assert reason["by_business"] == {"Thanh toán-IBFT": {"ai_wrong_content": 1}}
    assert reason["coverage"] == {
        "population": 1,
        "labeled": 1,
        "abstained": 0,
        "failed": 0,
        "invalid": 0,
    }
    assert "145665" not in json.dumps(reason, ensure_ascii=False)


def test_labeled_shadow_supports_partial_failed_invalid_coverage_and_mon_fri_filtering():
    run = _run_with_extra(
        _meta(trace("failed-first", "145668", 0, "2026-07-20T04:00:00Z", "AI reply")),
        _meta(trace("failed-later", "145668", 1, "2026-07-21T04:00:00Z", "AI reply")),
        _meta(trace("invalid-first", "145669", 0, "2026-07-25T02:00:00Z", "AI reply")),
        _meta(trace("invalid-later", "145669", 1, "2026-07-26T02:00:00Z", "AI reply")),
    )
    ai = next(item for item in run.result.sessions if item.session_id == "145665")
    shadow = ReopenReasonShadow(
        labels_version="v1",
        status="labeled",
        counts=(
            ShadowReasonCount(
                cohort_week=ai.cohort_week,
                outcome=ai.outcome,
                issue_category=ai.dimensions.issue_category,
                label="ai_wrong_content",
                count=1,
            ),
        ),
        coverage=(
            ShadowCoverageCount(cohort_week=ai.cohort_week, failed=1),
            ShadowCoverageCount(cohort_week=ai.cohort_week, invalid=1, is_weekend_start=True),
        ),
    )
    dashboard = project_dashboard(replace(run, reopen_shadow=shadow)).dashboard_dict()
    weekly = next(
        row for row in dashboard["views"]["mon_sun"]["weekly"]
        if row["cohort_week"] == "2026-07-20"
    )

    assert weekly["reopen_reason"]["coverage"] == {
        "population": 3,
        "labeled": 1,
        "abstained": 0,
        "failed": 1,
        "invalid": 1,
    }
    fri = next(
        row for row in dashboard["views"]["mon_fri"]["weekly"]
        if row["cohort_week"] == "2026-07-20"
    )
    assert fri["reopen_reason"]["coverage"] == {
        "population": 2,
        "labeled": 1,
        "abstained": 0,
        "failed": 1,
        "invalid": 0,
    }


def test_weekend_eligible_population_is_in_mon_sun_not_mon_fri_and_never_has_skip_counter():
    weekend_first = _meta(trace("weekend-first", "145667", 0, "2026-07-25T02:00:00Z", "AI reply"))
    weekend_later = _meta(trace("weekend-later", "145667", 1, "2026-07-26T02:00:00Z", "AI reply"))
    run = _run_with_extra(weekend_first, weekend_later)
    dashboard = project_dashboard(run).dashboard_dict()
    sun = next(row for row in dashboard["views"]["mon_sun"]["weekly"] if row["cohort_week"] == "2026-07-20")
    fri = next(row for row in dashboard["views"]["mon_fri"]["weekly"] if row["cohort_week"] == "2026-07-20")

    assert sun["reopen_reason"]["coverage"]["population"] == 2
    assert fri["reopen_reason"]["coverage"]["population"] == 1
    assert "skipped_weekend_start" not in sun["reopen_reason"]["coverage"]
    assert "skipped_weekend_start" not in fri["reopen_reason"]["coverage"]


def test_shadow_storage_validator_rejects_count_drift_and_recursive_pii():
    value = project_dashboard(_run()).storage_dict()
    weekly = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    weekly["reopen_reason"]["status"] = "labeled"
    weekly["reopen_reason"]["coverage"]["labeled"] = 1
    weekly["reopen_reason"]["coverage"]["population"] = 1
    weekly["reopen_reason"]["counts"] = {"ai_wrong_content": {"ai_end_to_end": 2}}
    with pytest.raises(ValueError, match="reopen_reason"):
        DashboardSnapshot.from_storage_dict(value)


def test_shadow_validator_reconciles_by_business_per_label_not_only_grand_total():
    run = _run_with_extra(
        _meta(trace("second-first", "145668", 0, "2026-07-20T04:00:00Z", "AI reply")),
        _meta(trace("second-later", "145668", 1, "2026-07-21T04:00:00Z", "AI reply")),
    )
    ai = next(item for item in run.result.sessions if item.session_id == "145665")
    shadow = ReopenReasonShadow(
        labels_version="v1",
        status="labeled",
        counts=(
            ShadowReasonCount(ai.cohort_week, ai.outcome, ai.dimensions.issue_category, "ai_wrong_content", 1),
            ShadowReasonCount(ai.cohort_week, ai.outcome, ai.dimensions.issue_category, "other", 1),
        ),
    )
    value = project_dashboard(replace(run, reopen_shadow=shadow)).storage_dict()
    weekly = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    weekly["reopen_reason"]["by_business"] = {
        "Thanh toán-IBFT": {"ai_wrong_content": 2}
    }

    with pytest.raises(ValueError, match="reopen_reason"):
        DashboardSnapshot.from_storage_dict(value)

    value = project_dashboard(_run()).storage_dict()
    weekly = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    weekly["reopen_7d_denominator"] = 1
    weekly["reopen_7d_rate"] = 1.0
    weekly["reopen_reason"]["control"] = {
        "direct_cs_reopen_7d_rate": None,
        "direct_cs_denominator": 1,
    }
    with pytest.raises(ValueError, match="reopen_reason"):
        DashboardSnapshot.from_storage_dict(value)

    value = project_dashboard(_run()).storage_dict()
    weekly = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    weekly["reopen_7d_denominator"] = 1
    weekly["reopen_7d_rate"] = 1.0
    weekly["reopen_reason"]["control"] = {
        "direct_cs_reopen_7d_rate": 0.5,
        "direct_cs_denominator": 1,
    }
    with pytest.raises(ValueError, match="reopen_reason"):
        DashboardSnapshot.from_storage_dict(value)

    value = project_dashboard(_run()).storage_dict()
    weekly = value["dashboard"]["views"]["mon_sun"]["weekly"][1]
    weekly["reopen_reason"]["counts"] = {"gọi 0901234567": {}}
    with pytest.raises(ValueError, match="reopen_reason"):
        DashboardSnapshot.from_storage_dict(value)


def test_storage_ignores_v3_disk_snapshot_after_v4_schema_change(tmp_path):
    snapshot = project_dashboard(_run())
    value = snapshot.storage_dict()
    value["schema_version"] = 3
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    (directory / "dashboard_snapshot.json").write_text(json.dumps(value), encoding="utf-8")

    assert ProtectedSnapshotStore(directory).load() is None


def test_shadow_systemic_failure_is_unavailable_without_changing_deterministic_dashboard(monkeypatch):
    normal = project_dashboard(_run()).dashboard_dict()

    def broken_shadow(_path):
        raise RuntimeError("shadow failure")

    monkeypatch.setattr("weekly_cs_report.report.pending_shadow", broken_shadow)
    unavailable = project_dashboard(_run()).dashboard_dict()

    assert all(
        row["reopen_reason"]["status"] == "unavailable"
        for view in unavailable["views"].values()
        for row in view["weekly"]
    )
    for dashboard in (normal, unavailable):
        for view in dashboard["views"].values():
            for row in view["weekly"]:
                del row["reopen_reason"]
    assert unavailable == normal


def test_compute_report_uses_unavailable_shadow_when_config_version_is_not_a_schema_version(
    tmp_path, monkeypatch
):
    """A syntactically valid but unsupported config must not break refresh."""
    malformed = tmp_path / "reopen_labels.v1.json"
    malformed.write_text('{"version":"not-a-version"}', encoding="utf-8")
    normal = project_dashboard(_run()).dashboard_dict()

    def malformed_shadow(_path):
        return pending_shadow(malformed)

    monkeypatch.setattr("weekly_cs_report.report.pending_shadow", malformed_shadow)
    unavailable = project_dashboard(_run()).dashboard_dict()

    assert all(
        row["reopen_reason"]["status"] == "unavailable"
        for view in unavailable["views"].values()
        for row in view["weekly"]
    )
    for dashboard in (normal, unavailable):
        for view in dashboard["views"].values():
            for row in view["weekly"]:
                del row["reopen_reason"]
    assert unavailable == normal


def test_pending_shadow_rejects_version_that_does_not_match_its_filename(tmp_path):
    mismatched = tmp_path / "reopen_labels.v2.json"
    mismatched.write_text('{"version":"v1"}', encoding="utf-8")

    with pytest.raises(ValueError, match="configuration"):
        pending_shadow(mismatched)


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: ReopenReasonShadow(labels_version="bad", status="pending"),
            "labels version",
        ),
        (
            lambda: ReopenReasonShadow(labels_version="v1", status="unknown"),
            "status",
        ),
        (
            lambda: ReopenReasonShadow(labels_version="v1", status=[]),  # type: ignore[arg-type]
            "status",
        ),
        (
            lambda: ShadowReasonCount(date(2026, 7, 20), "direct_cs", "ibft", "reason", 1),
            "outcome",
        ),
        (
            lambda: ShadowReasonCount(date(2026, 7, 20), "ai_end_to_end", "ibft", "Bad label", 1),
            "label",
        ),
        (
            lambda: ShadowReasonCount(date(2026, 7, 20), "ai_end_to_end", "ibft", "reason", 0),
            "count",
        ),
        (
            lambda: ShadowCoverageCount(date(2026, 7, 20), failed=-1),
            "failed",
        ),
        (
            lambda: ShadowCoverageCount(date(2026, 7, 20), is_weekend_start=1),
            "weekend",
        ),
    ],
)
def test_shadow_value_objects_reject_invalid_projection_fields(factory, match):
    """Invalid aggregates must not be constructible as a labeled shadow."""
    with pytest.raises(ValueError, match=match):
        factory()


def test_unsafe_shadow_dimension_falls_back_to_unavailable_without_touching_core_dashboard():
    run = _run()
    ai = next(item for item in run.result.sessions if item.session_id == "145665")
    unsafe_shadow = ReopenReasonShadow(
        labels_version="v1",
        status="labeled",
        counts=(
            ShadowReasonCount(
                cohort_week=ai.cohort_week,
                outcome="ai_end_to_end",
                issue_category="person@example.com",
                label="ai_wrong_content",
                count=1,
            ),
        ),
    )

    normal = project_dashboard(run).dashboard_dict()
    unavailable = project_dashboard(replace(run, reopen_shadow=unsafe_shadow)).dashboard_dict()

    assert all(
        row["reopen_reason"]["status"] == "unavailable"
        for view in unavailable["views"].values()
        for row in view["weekly"]
    )
    for dashboard in (normal, unavailable):
        for view in dashboard["views"].values():
            for row in view["weekly"]:
                del row["reopen_reason"]
    assert unavailable == normal


def test_shadow_coverage_drift_falls_back_to_unavailable_without_breaking_snapshot():
    run = _run()
    ai = next(item for item in run.result.sessions if item.session_id == "145665")
    drifted_shadow = ReopenReasonShadow(
        labels_version="v1",
        status="labeled",
        counts=(
            ShadowReasonCount(
                ai.cohort_week, "ai_end_to_end", ai.dimensions.issue_category,
                "ai_wrong_content", 1,
            ),
        ),
        coverage=(ShadowCoverageCount(ai.cohort_week, failed=1),),
    )

    normal = project_dashboard(run).dashboard_dict()
    unavailable = project_dashboard(replace(run, reopen_shadow=drifted_shadow)).dashboard_dict()

    assert all(
        row["reopen_reason"]["status"] == "unavailable"
        for view in unavailable["views"].values()
        for row in view["weekly"]
    )
    for dashboard in (normal, unavailable):
        for view in dashboard["views"].values():
            for row in view["weekly"]:
                del row["reopen_reason"]
    assert unavailable == normal


def _run_with_extra(*extra: dict):
    # The fixture helper's input is intentionally reconstructed here so the
    # test keeps exercising compute_report rather than mutating a result.
    traces = [
        _meta(trace("ai-first", "145665", 0, "2026-07-20T02:00:00Z", "AI reply")),
        _meta(trace("ai-later", "145665", 1, "2026-07-21T02:00:00Z", "AI reply again")),
        _meta(trace("direct-first", "145666", 0, "2026-07-20T03:00:00Z", TRANSFER_TEXT)),
        _meta(trace("direct-later", "145666", 1, "2026-07-21T03:00:00Z", "CS reply")),
        *extra,
    ]
    return compute_report(FakeClient(traces), as_of=AS_OF, weeks=2, include_current_wtd=True, taxonomy_path=TAXONOMY)
