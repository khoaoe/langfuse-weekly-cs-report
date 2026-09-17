from __future__ import annotations

"""Storage-shape validation for the dashboard payload.

Every ``_X_payload`` builder in ``dashboard_schema`` has a ``_validate_X``
mirror here: the two are halves of one contract, and keeping them in separate
files makes that symmetry visible instead of burying it in a 4,400-line
module. Validation only ever reads a payload, so nothing here is imported by
the projector except through ``dashboard_schema``'s own re-exports.
"""

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
import re
from typing import AbstractSet, Mapping

from .ai_tag_cache import AiTagCache, AiTagCacheError, AiTagRecord
from .entry_coverage_cache import (
    ENTRY_COVERAGE_START_WEEK,
    EntryCoverageCache,
    EntryCoverageCacheError,
    EntryCoverageRecord,
)
from .dashboard_rows import (
    TicketRow,
    _AI_REVIEW_COUNT_KEYS,
    _COMMENT_URL,
    _DASHBOARD_KEYS,
    _MISSING,
    _NO_SKILL,
    _SEGMENTS,
    _TICKET_EXPLORER_PUBLIC_KEYS,
    _TICKET_SORT_DIRECTIONS,
    _TRANSFER_TRIGGER_SOURCES,
    _VIEWS,
    _WEEKLY_KEYS,
    _expected_transfer_reason,
    _AI_REVIEW_RATING_BUCKETS,
    _CSAT_BUCKETS,
    _GUARDRAIL_RULES,
    _INTENT_PATTERN,
    _OUTCOMES,
    _QUALITY_LABELS,
    _TICKET_ID_PATTERN,
    _TOOL_ERROR_CODE_PATTERN,
    _TPE_CODE_PATTERN,
    _TRANSFER_TRIGGER_REASONS,
    _is_safe_intent_label,
    _is_safe_ticket_id,
    _nonnegative_int,
    _nullable_nonnegative_int,
    _parse_utc_iso,
    _positive_int,
    _safe_string,
    _utc_iso,
    _validate_ticket_values,
)

def _validate_ticket_sort(
    sort_by: str | None,
    sort_direction: str | None,
) -> str | None:
    if sort_by is None:
        if sort_direction is not None:
            raise ValueError("sort_direction is invalid")
        return None
    if not isinstance(sort_by, str) or sort_by not in _TICKET_EXPLORER_PUBLIC_KEYS:
        raise ValueError("sort_by is invalid")
    if sort_direction is None:
        return "asc"
    if (
        not isinstance(sort_direction, str)
        or sort_direction not in _TICKET_SORT_DIRECTIONS
    ):
        raise ValueError("sort_direction is invalid")
    return sort_direction


def _validated_ticket_dict(ticket: object) -> dict[str, object]:
    if not isinstance(ticket, TicketRow):
        raise ValueError("tickets must contain TicketRow values")
    _validate_ticket_values(ticket)
    return asdict(ticket)


def _validate_entry_coverage_records(
    records: tuple[EntryCoverageRecord, ...],
) -> None:
    try:
        EntryCoverageCache(fetched_weeks={}, records=records)
    except EntryCoverageCacheError as error:
        raise ValueError("entry coverage tickets are invalid") from error


def _validate_ai_tag_records(records: tuple[AiTagRecord, ...]) -> None:
    try:
        AiTagCache(fetched_weeks={}, records=records)
    except AiTagCacheError as error:
        raise ValueError("ai tag tickets are invalid") from error


def _validate_dashboard(value: Mapping[str, object], *, generated_at: datetime) -> None:
    _require_exact_keys(value, _DASHBOARD_KEYS, "dashboard")
    if value["generated_at"] != _utc_iso(generated_at):
        raise ValueError("dashboard generated_at must match storage generated_at")
    _validate_count_map(value["source"], {"traces_fetched", "traces_deduplicated", "observations_fetched"}, "source")
    if value["enrichment_status"] not in {"complete", "partial"}:
        raise ValueError("enrichment_status is invalid")
    _validate_data_range(value["data_range"])
    coverage = _require_mapping(value["coverage"], "coverage")
    _require_exact_keys(coverage, {"issue_category", "app", "tpe", "intent", "skill"}, "coverage")
    for key, rate in coverage.items(): _rate(rate, f"coverage.{key}")
    _validate_unmapped(value["unmapped_tpe_codes"])
    _validate_tool_error_code_counts(value["tool_error_codes"])
    _validate_gate(value["gate_status"])
    _validate_quality(value["data_quality"])
    views = _require_mapping(value["views"], "views")
    _require_exact_keys(views, set(_VIEWS), "views")
    for name in _VIEWS: _validate_view(views[name], name)
    if (
        views["mon_fri"]["totals"]["eligible_ticket_count"]
        + views["mon_sun"]["totals"]["weekend_start_count"]
        != views["mon_sun"]["totals"]["eligible_ticket_count"]
    ):
        raise ValueError("weekend view totals do not reconcile")


def _validate_data_range(value: object) -> None:
    mapping = _require_mapping(value, "data_range")
    _require_exact_keys(mapping, {"first_week_with_data", "weeks_without_data"}, "data_range")
    first = mapping["first_week_with_data"]
    if first is not None: _week_string(first, "data_range.first_week_with_data")
    weeks = mapping["weeks_without_data"]
    if not isinstance(weeks, list): raise ValueError("data_range.weeks_without_data is invalid")
    for week in weeks: _week_string(week, "data_range.weeks_without_data")


def _validate_unmapped(value: object) -> None:
    if not isinstance(value, list):
        raise ValueError("unmapped_tpe_codes must be a list")
    if value:
        raise ValueError("unmapped_tpe_codes must be empty")


def _validate_tool_error_code_counts(value: object) -> None:
    if not isinstance(value, list):
        raise ValueError("tool_error_codes must be a list")
    seen: set[str] = set()
    previous: tuple[int, str] | None = None
    for item in value:
        mapping = _require_mapping(item, "tool_error_codes entry")
        _require_exact_keys(mapping, {"code", "total"}, "tool_error_codes entry")
        code = mapping["code"]
        if (
            not isinstance(code, str)
            or _TOOL_ERROR_CODE_PATTERN.fullmatch(code) is None
            or code in seen
        ):
            raise ValueError("tool_error_codes code is invalid")
        seen.add(code)
        total = _positive_int(mapping["total"], "tool_error_codes total")
        current = (-total, code)
        if previous is not None and current < previous:
            raise ValueError("tool_error_codes must be ordered by count")
        previous = current


def _validate_gate(value: object) -> None:
    mapping = _require_mapping(value, "gate_status")
    _require_exact_keys(mapping, {"allowed", "structural_invalid_rate", "reasons"}, "gate_status")
    if not isinstance(mapping["allowed"], bool): raise ValueError("gate_status.allowed is invalid")
    _rate(mapping["structural_invalid_rate"], "gate_status.structural_invalid_rate")
    reasons = mapping["reasons"]
    if reasons != [] and reasons != ["structural_invalid_rate_gt_5pct"]:
        raise ValueError("gate_status.reasons is invalid")


def _validate_quality(value: object) -> None:
    mapping = _require_mapping(value, "data_quality")
    _require_exact_keys(mapping, {"counts", "weekend_start_count", "left_censored_count", "pre_window_start_count", "invalid_keyed_session_count", "unkeyed_trace_count"}, "data_quality")
    counts = _require_mapping(mapping["counts"], "data_quality.counts")
    for label, count in counts.items():
        if label not in _QUALITY_LABELS: raise ValueError("data_quality label is invalid")
        _nonnegative_int(count, "data_quality count")
    for key in set(mapping) - {"counts"}: _nonnegative_int(mapping[key], f"data_quality.{key}")


def _validate_view(value: object, expected_definition: str) -> None:
    view = _require_mapping(value, "view")
    _require_exact_keys(
        view,
        {
            "totals",
            "outcomes",
            "ai_first",
            "reopen",
            "weekly",
            "segments",
            "transfer_reasons",
            "by_week",
            "same_period",
            "csat",
            "outcome_reconciliation",
            "entry_coverage",
            "ai_tag_coverage",
            "ai_review",
            "rule_gt4",
        },
        "view",
    )
    _validate_count_map(view["totals"], {"eligible_ticket_count", "transfer_total", "gt4_turn_total", "weekend_start_count"}, "view.totals")
    _validate_count_map(view["outcomes"], set(_OUTCOMES), "view.outcomes")
    if sum(view["outcomes"].values()) != view["totals"]["eligible_ticket_count"]: raise ValueError("view outcomes do not reconcile")
    if view["totals"]["transfer_total"] != view["outcomes"]["ai_then_cs"] + view["outcomes"]["direct_cs"]: raise ValueError("view transfer total does not reconcile")
    ai = _require_mapping(view["ai_first"], "view.ai_first")
    _require_exact_keys(ai, {"count", "rate"}, "view.ai_first")
    _nonnegative_int(ai["count"], "view.ai_first.count"); _rate(ai["rate"], "view.ai_first.rate")
    if ai["count"] != view["outcomes"]["ai_end_to_end"] + view["outcomes"]["ai_then_cs"]: raise ValueError("view ai_first does not reconcile")
    expected_ai_rate = (
        ai["count"] / view["totals"]["eligible_ticket_count"]
        if view["totals"]["eligible_ticket_count"]
        else 0.0
    )
    if abs(ai["rate"] - expected_ai_rate) > 1e-12:
        raise ValueError("view ai_first rate does not match division")
    reopen = _require_mapping(view["reopen"], "view.reopen")
    _require_exact_keys(reopen, {"lifetime", "within_7d"}, "view.reopen")
    for name in ("lifetime", "within_7d"):
        _validate_count_map(
            reopen[name],
            {"numerator", "denominator"},
            f"view.reopen.{name}",
        )
        counts = _require_mapping(reopen[name], f"view.reopen.{name}")
        if name == "within_7d" and counts["numerator"] > counts["denominator"]:
            raise ValueError("reopen numerator exceeds denominator")
    _validate_weekly(view["weekly"], expected_definition)
    lifetime_counts = _require_mapping(
        reopen["lifetime"],
        "view.reopen.lifetime",
    )
    if (
        lifetime_counts["numerator"]
        != sum(item["reopen_lifetime_numerator"] for item in view["weekly"])
        or lifetime_counts["denominator"]
        != sum(item["reopen_lifetime_denominator"] for item in view["weekly"])
    ):
        raise ValueError("weekly lifetime does not reconcile")
    _validate_segments(view["segments"], view["totals"]["eligible_ticket_count"])
    _validate_transfer_reasons(view["transfer_reasons"], view["segments"])
    by_week = _require_mapping(view["by_week"], "view.by_week")
    weekly_by_key = {
        item["cohort_week"]: item
        for item in view["weekly"]
    }
    _require_exact_keys(by_week, set(weekly_by_key), "view.by_week")
    for cohort_week, detail_value in by_week.items():
        detail = _require_mapping(detail_value, f"view.by_week.{cohort_week}")
        _require_exact_keys(
            detail,
            {"segments", "transfer_reasons"},
            f"view.by_week.{cohort_week}",
        )
        weekly_total_for_key = weekly_by_key[cohort_week]["total_tickets"]
        _validate_segments(detail["segments"], weekly_total_for_key)
        _validate_transfer_reasons(
            detail["transfer_reasons"],
            detail["segments"],
        )
    _validate_same_period(view["same_period"], weekly_by_key)
    _validate_csat(view["csat"], weekly_by_key)
    _validate_outcome_reconciliation(
        view["outcome_reconciliation"],
        weekly_by_key,
    )
    _validate_entry_coverage(view["entry_coverage"], weekly_by_key)
    _validate_ai_tag_coverage(view["ai_tag_coverage"], weekly_by_key)
    _validate_ai_review(view["ai_review"], weekly_by_key)
    _validate_segment_rollup(
        view["segments"],
        tuple(
            _require_mapping(detail, "view.by_week item")["segments"]
            for detail in by_week.values()
        ),
    )
    _validate_transfer_reason_rollup(
        view["transfer_reasons"],
        tuple(
            _require_mapping(detail, "view.by_week item")["transfer_reasons"]
            for detail in by_week.values()
        ),
    )
    rule = _require_mapping(view["rule_gt4"], "view.rule_gt4")
    _validate_count_map(rule, {"gt4_turn_total", "gt4_turn_with_cs", "gt4_turn_without_cs", "max_replies_rule_fired"}, "view.rule_gt4")
    if rule["gt4_turn_total"] != rule["gt4_turn_with_cs"] + rule["gt4_turn_without_cs"]: raise ValueError("rule_gt4 does not reconcile")
    if rule["gt4_turn_total"] != view["totals"]["gt4_turn_total"]: raise ValueError("rule_gt4 total does not reconcile")
    if (
        rule["gt4_turn_with_cs"]
        != sum(item["gt4_turn_with_cs"] for item in view["weekly"])
        or rule["gt4_turn_without_cs"]
        != sum(item["gt4_turn_without_cs"] for item in view["weekly"])
        or rule["max_replies_rule_fired"]
        != sum(item["max_replies_rule_fired"] for item in view["weekly"])
    ):
        raise ValueError("weekly rule_gt4 does not reconcile")
    weekly_total = sum(item["total_tickets"] for item in view["weekly"])
    if weekly_total != view["totals"]["eligible_ticket_count"]: raise ValueError("view weekly does not reconcile")


def _validate_entry_coverage(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    coverage = _require_mapping(value, "view.entry_coverage")
    # `by_day` arrived with day-range coverage scoping. A snapshot written
    # before that is still valid and simply carries no day grain.
    _require_exact_keys(
        coverage,
        {"source", "source_start_week", "fetched_at", "by_week"}
        | ({"by_day"} if "by_day" in coverage else set()),
        "view.entry_coverage",
    )
    if coverage["source"] != "freshdesk":
        raise ValueError("view.entry_coverage source is invalid")
    if coverage["source_start_week"] != ENTRY_COVERAGE_START_WEEK:
        raise ValueError("view.entry_coverage source start week is invalid")
    _parse_utc_iso(coverage["fetched_at"], "view.entry_coverage.fetched_at")
    by_week = _require_mapping(coverage["by_week"], "view.entry_coverage.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.entry_coverage contains a week outside this view")
    count_keys = {
        "freshdesk_ticket_count",
        "ai_replied_only",
        "ai_replied_then_transferred",
        "transferred_without_ai_reply",
        "invoked_no_result",
    }
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.entry_coverage.by_week key")
        _validate_entry_coverage_bucket(
            raw_counts,
            count_keys,
            f"view.entry_coverage.by_week.{cohort_week}",
        )
    if "by_day" not in coverage:
        return
    by_day = _require_mapping(coverage["by_day"], "view.entry_coverage.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.entry_coverage.by_day key")
        # A day belongs to exactly one cohort week, and only weeks this view
        # observed may appear -- the same containment rule `by_week` gets,
        # applied one grain down.
        if (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat() not in weekly_by_key:
            raise ValueError("view.entry_coverage contains a day outside this view")
        _validate_entry_coverage_bucket(
            raw_counts,
            count_keys,
            f"view.entry_coverage.by_day.{day}",
        )


def _validate_entry_coverage_bucket(
    raw_counts: object,
    count_keys: AbstractSet[str],
    path: str,
) -> None:
    """Validate one coverage bucket. Grain-agnostic, like `_entry_coverage_bucket()`."""
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(counts, count_keys, path)
    for key in count_keys:
        _nonnegative_int(counts[key], f"{path}.{key}")
    status_total = sum(
        counts[key]
        for key in (
            "ai_replied_only",
            "ai_replied_then_transferred",
            "transferred_without_ai_reply",
            "invoked_no_result",
        )
    )
    if counts["freshdesk_ticket_count"] != status_total:
        raise ValueError("entry coverage status counts do not reconcile")


def _validate_ai_tag_coverage(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    coverage = _require_mapping(value, "view.ai_tag_coverage")
    _require_exact_keys(
        coverage,
        {"source", "source_start_week", "fetched_at", "by_week", "by_day"},
        "view.ai_tag_coverage",
    )
    if coverage["source"] != "freshdesk":
        raise ValueError("view.ai_tag_coverage source is invalid")
    if coverage["source_start_week"] != ENTRY_COVERAGE_START_WEEK:
        raise ValueError("view.ai_tag_coverage source start week is invalid")
    _parse_utc_iso(coverage["fetched_at"], "view.ai_tag_coverage.fetched_at")
    by_week = _require_mapping(coverage["by_week"], "view.ai_tag_coverage.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.ai_tag_coverage contains a week outside this view")
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.ai_tag_coverage.by_week key")
        _validate_ai_tag_coverage_bucket(
            raw_counts, f"view.ai_tag_coverage.by_week.{cohort_week}"
        )
    by_day = _require_mapping(coverage["by_day"], "view.ai_tag_coverage.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.ai_tag_coverage.by_day key")
        if (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat() not in weekly_by_key:
            raise ValueError("view.ai_tag_coverage contains a day outside this view")
        _validate_ai_tag_coverage_bucket(
            raw_counts, f"view.ai_tag_coverage.by_day.{day}"
        )


def _validate_ai_tag_coverage_bucket(raw_counts: object, path: str) -> None:
    count_keys = {
        "ai_tagged_count",
        "langfuse_count",
        "union_count",
        "missed_count",
        "untagged_count",
        "missed_ticket_ids",
        "untagged_ticket_ids",
    }
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(counts, count_keys, path)
    for key in (
        "ai_tagged_count",
        "langfuse_count",
        "union_count",
        "missed_count",
        "untagged_count",
    ):
        _nonnegative_int(counts[key], f"{path}.{key}")
    missed_ids = counts["missed_ticket_ids"]
    untagged_ids = counts["untagged_ticket_ids"]
    if not isinstance(missed_ids, list) or not isinstance(untagged_ids, list):
        raise ValueError(f"{path} ticket id lists are invalid")
    for ticket_id in (*missed_ids, *untagged_ids):
        if not isinstance(ticket_id, str) or _TICKET_ID_PATTERN.fullmatch(ticket_id) is None:
            raise ValueError(f"{path} ticket id is invalid")
    if missed_ids != sorted(missed_ids) or untagged_ids != sorted(untagged_ids):
        raise ValueError(f"{path} ticket id lists are not sorted")
    if counts["union_count"] != counts["langfuse_count"] + counts["missed_count"]:
        raise ValueError(f"{path} union count does not reconcile")
    if len(missed_ids) != counts["missed_count"]:
        raise ValueError(f"{path} missed count does not reconcile")
    if len(untagged_ids) != counts["untagged_count"]:
        raise ValueError(f"{path} untagged count does not reconcile")


def _validate_ai_review(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    ai_review = _require_mapping(value, "view.ai_review")
    _require_exact_keys(
        ai_review,
        {"source", "fetched_at", "by_week", "by_day"},
        "view.ai_review",
    )
    if ai_review["source"] != "freshdesk":
        raise ValueError("view.ai_review source is invalid")
    _parse_utc_iso(ai_review["fetched_at"], "view.ai_review.fetched_at")
    by_week = _require_mapping(ai_review["by_week"], "view.ai_review.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.ai_review contains a week outside this view")
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.ai_review.by_week key")
        _validate_ai_review_bucket(
            raw_counts,
            f"view.ai_review.by_week.{cohort_week}",
            weekly_by_key[cohort_week]["total_tickets"],
        )
    by_day = _require_mapping(ai_review["by_day"], "view.ai_review.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.ai_review.by_day key")
        cohort_week = (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat()
        if cohort_week not in weekly_by_key:
            raise ValueError("view.ai_review contains a day outside this view")
        _validate_ai_review_bucket(
            raw_counts,
            f"view.ai_review.by_day.{day}",
            weekly_by_key[cohort_week]["total_tickets"],
        )


def _validate_ai_review_bucket(
    raw_counts: object,
    path: str,
    population_cap: object,
) -> None:
    """Validate one AI-review bucket. Grain-agnostic, like `_ai_review_bucket()`.

    `reviewed_ticket_count` is a SUM of `cf_s_ln_hu_kim_ai` over rated
    tickets, not a ticket count, so it can legitimately exceed
    `population_cap` (one ticket can contribute more than 1) -- the other
    three, `rated_ticket_count`, `evaluated_ticket_count`, and
    `unrated_reviewed_ticket_count`, are actual ticket counts and are bounded
    by it.

    The two source fields don't nest either: `cf_rating_ai` and
    `cf_s_ln_hu_kim_ai` are filled independently by CS. Measured 2026-09-05
    over the live cache, 3.574 tickets are rated with no review count and
    1.534 have a count but no rating.
    """
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(
        counts,
        {*_AI_REVIEW_COUNT_KEYS, "by_outcome", "by_dimension", "by_review_count"},
        path,
    )
    for key in _AI_REVIEW_COUNT_KEYS:
        _nonnegative_int(counts[key], f"{path}.{key}")
    if counts["rated_ticket_count"] != sum(
        counts[key] for key in _AI_REVIEW_RATING_BUCKETS
    ):
        raise ValueError("view.ai_review rating counts do not reconcile")
    if counts["evaluated_ticket_count"] != (
        counts["rated_ticket_count"] + counts["unrated_reviewed_ticket_count"]
    ):
        raise ValueError("view.ai_review evaluated count does not reconcile")
    if counts["rated_ticket_count"] > population_cap:
        raise ValueError("view.ai_review rated count exceeds weekly population")
    if counts["evaluated_ticket_count"] > population_cap:
        raise ValueError("view.ai_review evaluated count exceeds weekly population")
    if counts["unrated_reviewed_ticket_count"] > population_cap:
        raise ValueError(
            "view.ai_review unrated-reviewed count exceeds weekly population"
        )

    by_outcome = _require_mapping(counts["by_outcome"], f"{path}.by_outcome")
    _require_exact_keys(by_outcome, set(_OUTCOMES), f"{path}.by_outcome")
    outcome_rows = [
        _validate_ai_review_count_row(
            by_outcome[outcome],
            f"view.ai_review outcome {outcome}",
        )
        for outcome in _OUTCOMES
    ]
    _validate_ai_review_rollup(counts, outcome_rows, "outcome")

    by_dimension = _require_mapping(counts["by_dimension"], f"{path}.by_dimension")
    _require_exact_keys(by_dimension, {"skill", "issue_category", "app"}, f"{path}.by_dimension")
    for dimension in ("skill", "issue_category", "app"):
        raw_rows = by_dimension[dimension]
        if not isinstance(raw_rows, list):
            raise ValueError("view.ai_review dimension rows are invalid")
        labels: set[str] = set()
        dimension_rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            row = _require_mapping(raw_row, "view.ai_review dimension row")
            _require_exact_keys(
                row,
                {"value", *_AI_REVIEW_COUNT_KEYS},
                "view.ai_review dimension row",
            )
            label = _safe_string(row["value"], "view.ai_review dimension value")
            if label in labels:
                raise ValueError("view.ai_review dimension values are duplicated")
            labels.add(label)
            dimension_rows.append(
                _validate_ai_review_count_row(
                    {key: row[key] for key in _AI_REVIEW_COUNT_KEYS},
                    "view.ai_review dimension row",
                )
            )
        _validate_ai_review_rollup(counts, dimension_rows, "dimension")

    raw_review_count_rows = counts["by_review_count"]
    if not isinstance(raw_review_count_rows, list):
        raise ValueError("view.ai_review review-count rows are invalid")
    review_count_labels: set[str] = set()
    review_count_rows: list[Mapping[str, object]] = []
    for raw_row in raw_review_count_rows:
        row = _require_mapping(raw_row, "view.ai_review review-count row")
        _require_exact_keys(
            row,
            {"value", *_AI_REVIEW_COUNT_KEYS},
            "view.ai_review review-count row",
        )
        value = row["value"]
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("view.ai_review review-count value is invalid")
        if value in review_count_labels:
            raise ValueError("view.ai_review review-count values are duplicated")
        review_count_labels.add(value)
        review_count_rows.append(
            _validate_ai_review_count_row(
                {key: row[key] for key in _AI_REVIEW_COUNT_KEYS},
                "view.ai_review review-count row",
            )
        )
    # Every reviewed ticket falls into exactly one review-count bucket, so
    # this rollup uses `reviewed_ticket_count` as its anchor instead of the
    # rating-only reconciliation `_validate_ai_review_rollup` checks share
    # with outcome/dimension. A rated ticket is NOT necessarily a reviewed
    # one, so a rating-anchored rollup would not close here.
    if sum(row["reviewed_ticket_count"] for row in review_count_rows) != counts[
        "reviewed_ticket_count"
    ]:
        raise ValueError("view.ai_review review-count counts do not reconcile")


def _validate_ai_review_count_row(
    value: object,
    name: str,
) -> Mapping[str, object]:
    row = _require_mapping(value, name)
    _require_exact_keys(row, set(_AI_REVIEW_COUNT_KEYS), name)
    for key in _AI_REVIEW_COUNT_KEYS:
        _nonnegative_int(row[key], f"{name}.{key}")
    if row["rated_ticket_count"] != sum(row[key] for key in _AI_REVIEW_RATING_BUCKETS):
        raise ValueError(f"{name} rating buckets do not reconcile")
    if row["evaluated_ticket_count"] != (
        row["rated_ticket_count"] + row["unrated_reviewed_ticket_count"]
    ):
        raise ValueError(f"{name} evaluated count does not reconcile")
    return row


def _validate_ai_review_rollup(
    totals: Mapping[str, object],
    rows: list[Mapping[str, object]],
    name: str,
) -> None:
    for key in _AI_REVIEW_COUNT_KEYS:
        if sum(row[key] for row in rows) != totals[key]:
            raise ValueError(f"view.ai_review {name} counts do not reconcile")


def _validate_csat(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    csat = _require_mapping(value, "view.csat")
    # `by_day` arrived with day-range CSAT scoping. A snapshot written before
    # that is still valid and simply carries no day grain.
    _require_exact_keys(
        csat,
        {"source", "fetched_at", "by_week", "feedback_pool"}
        | ({"by_day"} if "by_day" in csat else set()),
        "view.csat",
    )
    if csat["source"] != "freshdesk":
        raise ValueError("view.csat source is invalid")
    _parse_utc_iso(csat["fetched_at"], "view.csat.fetched_at")
    # Entries live once per view; buckets only reference them by key. Validated
    # here so every per-entry safety rule (PII, URL, length) runs exactly once
    # instead of once per bucket the entry appears in.
    feedback_pool = _validate_csat_feedback_pool(csat["feedback_pool"])
    by_week = _require_mapping(csat["by_week"], "view.csat.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.csat contains a week outside this view")
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.csat.by_week key")
        _validate_csat_bucket(
            raw_counts,
            f"view.csat.by_week.{cohort_week}",
            weekly_by_key[cohort_week]["total_tickets"],
            feedback_pool,
        )
    if "by_day" not in csat:
        return
    by_day = _require_mapping(csat["by_day"], "view.csat.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.csat.by_day key")
        # A day belongs to exactly one cohort week, and only weeks this view
        # observed may appear -- the same containment rule `by_week` gets,
        # applied one grain down.
        cohort_week = (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat()
        if cohort_week not in weekly_by_key:
            raise ValueError("view.csat contains a day outside this view")
        _validate_csat_bucket(
            raw_counts,
            f"view.csat.by_day.{day}",
            weekly_by_key[cohort_week]["total_tickets"],
            feedback_pool,
        )


def _day_string(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} is invalid") from None


def _validate_csat_bucket(
    raw_counts: object,
    path: str,
    population_cap: object,
    feedback_pool: Mapping[str, Mapping[str, object]],
) -> None:
    """Validate one CSAT bucket. Grain-agnostic, like `_csat_bucket()`.

    `population_cap` is the ticket population the bucket may not exceed: its
    own week at week grain, and its containing week at day grain -- a day can
    never hold more rated tickets than the week it sits in.
    """
    count_keys = {"response_count", "ticket_count", *_CSAT_BUCKETS}
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(
        counts,
        count_keys
        | {
            "by_outcome",
            "by_dimension",
            "response_by_outcome",
            "response_by_dimension",
            "feedback_entry_keys",
        },
        path,
    )
    for key in count_keys:
        _nonnegative_int(
            counts[key],
            f"{path}.{key}",
        )
    if counts["response_count"] < counts["ticket_count"]:
        raise ValueError("view.csat ticket count exceeds response count")
    if counts["ticket_count"] != sum(counts[key] for key in _CSAT_BUCKETS):
        raise ValueError("view.csat ticket counts do not reconcile")
    if counts["ticket_count"] > population_cap:
        raise ValueError("view.csat ticket count exceeds weekly population")

    by_outcome = _require_mapping(
        counts["by_outcome"],
        f"{path}.by_outcome",
    )
    _require_exact_keys(
        by_outcome,
        set(_OUTCOMES),
        f"{path}.by_outcome",
    )
    outcome_rows = [
        _validate_csat_count_row(
            by_outcome[outcome],
            f"view.csat outcome {outcome}",
        )
        for outcome in _OUTCOMES
    ]
    _validate_csat_rollup(counts, outcome_rows, "outcome")

    by_dimension = _require_mapping(
        counts["by_dimension"],
        f"{path}.by_dimension",
    )
    _require_exact_keys(
        by_dimension,
        {"skill", "issue_category", "app"},
        f"{path}.by_dimension",
    )
    for dimension in ("skill", "issue_category", "app"):
        raw_rows = by_dimension[dimension]
        if not isinstance(raw_rows, list):
            raise ValueError("view.csat dimension rows are invalid")
        labels: set[str] = set()
        dimension_rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            row = _require_mapping(raw_row, "view.csat dimension row")
            _require_exact_keys(
                row,
                {"value", "ticket_count", *_CSAT_BUCKETS},
                "view.csat dimension row",
            )
            label = _safe_string(row["value"], "view.csat dimension value")
            if label in labels:
                raise ValueError("view.csat dimension values are duplicated")
            labels.add(label)
            dimension_rows.append(
                _validate_csat_count_row(
                    {
                        key: row[key]
                        for key in ("ticket_count", *_CSAT_BUCKETS)
                    },
                    "view.csat dimension row",
                )
            )
        _validate_csat_rollup(counts, dimension_rows, "dimension")

    response_by_outcome = _require_mapping(
        counts["response_by_outcome"],
        f"{path}.response_by_outcome",
    )
    _require_exact_keys(
        response_by_outcome,
        set(_OUTCOMES),
        f"{path}.response_by_outcome",
    )
    response_outcome_rows = [
        _validate_csat_count_row(
            response_by_outcome[outcome],
            f"view.csat response outcome {outcome}",
        )
        for outcome in _OUTCOMES
    ]
    response_totals = {
        "ticket_count": counts["response_count"],
        **{
            bucket: sum(row[bucket] for row in response_outcome_rows)
            for bucket in _CSAT_BUCKETS
        },
    }
    _validate_csat_rollup(response_totals, response_outcome_rows, "response outcome")

    response_by_dimension = _require_mapping(
        counts["response_by_dimension"],
        f"{path}.response_by_dimension",
    )
    _require_exact_keys(
        response_by_dimension,
        {"skill", "issue_category", "app"},
        f"{path}.response_by_dimension",
    )
    for dimension in ("skill", "issue_category", "app"):
        raw_rows = response_by_dimension[dimension]
        if not isinstance(raw_rows, list):
            raise ValueError("view.csat response dimension rows are invalid")
        labels: set[str] = set()
        response_dimension_rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            row = _require_mapping(raw_row, "view.csat response dimension row")
            _require_exact_keys(
                row,
                {"value", "ticket_count", *_CSAT_BUCKETS},
                "view.csat response dimension row",
            )
            label = _safe_string(
                row["value"], "view.csat response dimension value"
            )
            if label in labels:
                raise ValueError(
                    "view.csat response dimension values are duplicated"
                )
            labels.add(label)
            response_dimension_rows.append(
                _validate_csat_count_row(
                    {
                        key: row[key]
                        for key in ("ticket_count", *_CSAT_BUCKETS)
                    },
                    "view.csat response dimension row",
                )
            )
        _validate_csat_rollup(
            response_totals,
            response_dimension_rows,
            "response dimension",
        )

    feedback_entry_keys = counts["feedback_entry_keys"]
    if (
        not isinstance(feedback_entry_keys, list)
        or len(feedback_entry_keys) > counts["response_count"]
    ):
        raise ValueError("view.csat feedback entries are invalid")
    seen: set[str] = set()
    for key in feedback_entry_keys:
        if not isinstance(key, str) or key not in feedback_pool:
            raise ValueError("view.csat feedback key is unknown")
        if key in seen:
            raise ValueError("view.csat feedback key is duplicated")
        seen.add(key)


def _validate_csat_feedback_pool(
    value: object,
) -> Mapping[str, Mapping[str, object]]:
    """Validate every distinct CSAT comment in this view exactly once.

    Holds the per-entry safety rules that used to run inside each bucket: an
    entry appearing in both its week and its day bucket was previously checked
    -- and stored -- twice.
    """
    pool = _require_mapping(value, "view.csat.feedback_pool")
    ticket_metadata: dict[str, tuple[object, ...]] = {}
    ticket_numbers: dict[str, set[int]] = defaultdict(set)
    validated: dict[str, Mapping[str, object]] = {}
    for raw_key, raw_entry in pool.items():
        entry = _require_mapping(raw_entry, "view.csat feedback entry")
        _require_exact_keys(
            entry,
            {
                "ticket_id",
                "responded_at",
                "satisfaction_bucket",
                "outcome",
                "skill",
                "issue_category",
                "app",
                "text",
                "response_number",
                "response_total",
                "is_latest_for_ticket",
            },
            "view.csat feedback entry",
        )
        if not _is_safe_ticket_id(entry["ticket_id"]):
            raise ValueError("view.csat feedback ticket_id is invalid")
        _parse_utc_iso(
            entry["responded_at"],
            "view.csat feedback responded_at",
        )
        if entry["satisfaction_bucket"] not in _CSAT_BUCKETS:
            raise ValueError("view.csat feedback bucket is invalid")
        if entry["outcome"] not in _OUTCOMES:
            raise ValueError("view.csat feedback outcome is invalid")
        skill = _safe_string(entry["skill"], "view.csat feedback skill")
        issue_category = _safe_string(
            entry["issue_category"],
            "view.csat feedback issue_category",
        )
        app = _safe_string(entry["app"], "view.csat feedback app")
        text = _safe_string(entry["text"], "view.csat feedback text")
        if _COMMENT_URL.search(text):
            raise ValueError("view.csat feedback text is unsafe")
        if len(text) > 200:
            raise ValueError("view.csat feedback text is invalid")
        response_number = _positive_int(
            entry["response_number"],
            "view.csat feedback response number",
        )
        response_total = _positive_int(
            entry["response_total"],
            "view.csat feedback response total",
        )
        if response_number > response_total:
            raise ValueError("view.csat feedback response number exceeds total")
        if not isinstance(entry["is_latest_for_ticket"], bool):
            raise ValueError("view.csat feedback latest marker is invalid")
        if entry["is_latest_for_ticket"] != (response_number == response_total):
            raise ValueError("view.csat feedback latest marker is inconsistent")
        ticket_id = entry["ticket_id"]
        if raw_key != f"{ticket_id}:{response_number}":
            raise ValueError("view.csat feedback key does not match its entry")
        metadata = (
            response_total,
            entry["outcome"],
            skill,
            issue_category,
            app,
        )
        if ticket_id in ticket_metadata and ticket_metadata[ticket_id] != metadata:
            raise ValueError("view.csat feedback ticket metadata is inconsistent")
        if response_number in ticket_numbers[ticket_id]:
            raise ValueError("view.csat feedback response number is duplicated")
        ticket_metadata[ticket_id] = metadata
        ticket_numbers[ticket_id].add(response_number)
        validated[raw_key] = entry
    return validated


def _validate_outcome_reconciliation(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    reconciliation = _require_mapping(value, "view.outcome_reconciliation")
    _require_exact_keys(
        reconciliation,
        {"source", "fetched_at", "by_week"},
        "view.outcome_reconciliation",
    )
    if reconciliation["source"] != "freshdesk":
        raise ValueError("view outcome reconciliation source is invalid")
    _parse_utc_iso(
        reconciliation["fetched_at"],
        "view.outcome_reconciliation.fetched_at",
    )
    by_week = _require_mapping(
        reconciliation["by_week"],
        "view.outcome_reconciliation.by_week",
    )
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view outcome reconciliation contains an unknown week")
    keys = {
        "langfuse_ai_end_to_end",
        "checked_ticket_count",
        "human_replied_after_ai",
        "unresolved_ticket_count",
        "mismatch_rate",
    }
    for cohort_week, raw_row in by_week.items():
        _week_string(cohort_week, "view.outcome_reconciliation.by_week key")
        row = _require_mapping(
            raw_row,
            f"view.outcome_reconciliation.by_week.{cohort_week}",
        )
        _require_exact_keys(
            row,
            keys,
            f"view.outcome_reconciliation.by_week.{cohort_week}",
        )
        for key in keys - {"mismatch_rate"}:
            _nonnegative_int(
                row[key],
                f"view outcome reconciliation {key}",
            )
        population = row["langfuse_ai_end_to_end"]
        checked = row["checked_ticket_count"]
        human_replied = row["human_replied_after_ai"]
        unresolved = row["unresolved_ticket_count"]
        if checked + unresolved > population or human_replied > checked:
            raise ValueError("view outcome reconciliation counts do not reconcile")
        mismatch_rate = row["mismatch_rate"]
        if checked == 0:
            if mismatch_rate is not None:
                raise ValueError("view outcome reconciliation rate is invalid")
        else:
            _rate(mismatch_rate, "view outcome reconciliation mismatch rate")
            if abs(mismatch_rate - human_replied / checked) > 1e-12:
                raise ValueError("view outcome reconciliation rate does not reconcile")
        weekly_ai_end_to_end = weekly_by_key[cohort_week][
            "ai_end_to_end_count"
        ]
        if population > weekly_ai_end_to_end:
            raise ValueError("view outcome reconciliation population does not reconcile")


def _validate_csat_count_row(
    value: object,
    name: str,
) -> Mapping[str, object]:
    row = _require_mapping(value, name)
    _require_exact_keys(row, {"ticket_count", *_CSAT_BUCKETS}, name)
    for key in ("ticket_count", *_CSAT_BUCKETS):
        _nonnegative_int(row[key], f"{name}.{key}")
    if row["ticket_count"] != sum(row[key] for key in _CSAT_BUCKETS):
        raise ValueError(f"{name} buckets do not reconcile")
    return row


def _validate_csat_rollup(
    totals: Mapping[str, object],
    rows: list[Mapping[str, object]],
    name: str,
) -> None:
    for key in ("ticket_count", *_CSAT_BUCKETS):
        if sum(row[key] for row in rows) != totals[key]:
            raise ValueError(f"view.csat {name} counts do not reconcile")


def _validate_same_period(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    same_period = _require_mapping(value, "view.same_period")
    _require_exact_keys(
        same_period,
        {"cutoff_date", "cutoff_weekday", "current", "baseline", "by_week"},
        "view.same_period",
    )
    cutoff = _date_string(same_period["cutoff_date"], "view.same_period.cutoff_date")
    weekday = _positive_int(
        same_period["cutoff_weekday"],
        "view.same_period.cutoff_weekday",
    )
    if weekday > 7:
        raise ValueError("view.same_period.cutoff_weekday is invalid")
    if weekday != cutoff.isoweekday():
        raise ValueError("view.same_period cutoff weekday does not match date")
    current = _validate_same_period_week(
        same_period["current"],
        "view.same_period.current",
    )
    current_weekly = weekly_by_key.get(current["cohort_week"])
    if current_weekly is None or current_weekly["cohort_status"] != "wtd":
        raise ValueError("view.same_period.current must identify the running week")
    baseline = _require_mapping(same_period["baseline"], "view.same_period.baseline")
    _require_exact_keys(
        baseline,
        {"weeks_used", "ai_first_rate", "reopen_lifetime_rate"},
        "view.same_period.baseline",
    )
    weeks_used = _positive_int(
        baseline["weeks_used"],
        "view.same_period.baseline.weeks_used",
    )
    if weeks_used < 2:
        raise ValueError("view.same_period baseline needs at least two weeks")
    if weeks_used > 4:
        raise ValueError("view.same_period.baseline.weeks_used exceeds four")
    baseline_ai_rate = _rate(
        baseline["ai_first_rate"],
        "view.same_period.baseline.ai_first_rate",
    )
    baseline_reopen_rate = _nullable_nonnegative_ratio(
        baseline["reopen_lifetime_rate"],
        "view.same_period.baseline.reopen_lifetime_rate",
    )
    by_week = _require_mapping(same_period["by_week"], "view.same_period.by_week")
    if current["cohort_week"] not in by_week:
        raise ValueError("view.same_period.by_week must include current week")
    current_week = date.fromisoformat(current["cohort_week"])
    validated_by_week: dict[date, Mapping[str, object]] = {}
    for cohort_week, detail_value in by_week.items():
        _week_string(cohort_week, "view.same_period.by_week key")
        if cohort_week not in weekly_by_key:
            raise ValueError("view.same_period.by_week key is outside view.by_week")
        detail = _validate_same_period_week(
            detail_value,
            f"view.same_period.by_week.{cohort_week}",
        )
        if detail["cohort_week"] != cohort_week:
            raise ValueError("view.same_period by_week key does not match cohort_week")
        parsed_week = date.fromisoformat(cohort_week)
        if parsed_week > current_week:
            raise ValueError("view.same_period.by_week cannot extend past current")
        validated_by_week[parsed_week] = detail

    current_detail = validated_by_week[current_week]
    if dict(current_detail) != dict(current):
        raise ValueError("view.same_period.current must match its by_week row")

    contributors = [
        detail
        for week, detail in sorted(validated_by_week.items())
        if week < current_week and detail["total_tickets"] > 0
    ][-4:]
    if len(contributors) != weeks_used:
        raise ValueError("view.same_period.baseline.weeks_used is inconsistent")
    expected_ai_rate = sum(
        float(detail["ai_first_rate"]) for detail in contributors
    ) / weeks_used
    if abs(baseline_ai_rate - expected_ai_rate) > 1e-12:
        raise ValueError("view.same_period.baseline.ai_first_rate is inconsistent")
    contributor_reopen_rates = [
        float(detail["reopen_lifetime_rate"])
        for detail in contributors
        if detail["reopen_lifetime_rate"] is not None
    ]
    expected_reopen_rate = (
        sum(contributor_reopen_rates) / len(contributor_reopen_rates)
        if contributor_reopen_rates
        else None
    )
    if (
        (baseline_reopen_rate is None) != (expected_reopen_rate is None)
        or (
            baseline_reopen_rate is not None
            and expected_reopen_rate is not None
            and abs(baseline_reopen_rate - expected_reopen_rate) > 1e-12
        )
    ):
        raise ValueError(
            "view.same_period.baseline.reopen_lifetime_rate is inconsistent"
        )


def _validate_same_period_week(
    value: object,
    name: str,
) -> Mapping[str, object]:
    item = _require_mapping(value, name)
    _require_exact_keys(
        item,
        {
            "cohort_week",
            "total_tickets",
            "ai_first_count",
            "ai_first_rate",
            "reopen_lifetime_rate",
            "reopen_lifetime_numerator",
            "reopen_lifetime_denominator",
        },
        name,
    )
    _week_string(item["cohort_week"], f"{name}.cohort_week")
    total = _nonnegative_int(item["total_tickets"], f"{name}.total_tickets")
    ai_first = _nonnegative_int(item["ai_first_count"], f"{name}.ai_first_count")
    if ai_first > total:
        raise ValueError(f"{name}.ai_first_count exceeds total")
    ai_rate = _rate(item["ai_first_rate"], f"{name}.ai_first_rate")
    expected_ai_rate = ai_first / total if total else 0.0
    if abs(ai_rate - expected_ai_rate) > 1e-12:
        raise ValueError(f"{name}.ai_first_rate does not match division")
    reopen_numerator = _nonnegative_int(
        item["reopen_lifetime_numerator"],
        f"{name}.reopen_lifetime_numerator",
    )
    reopen_denominator = _nonnegative_int(
        item["reopen_lifetime_denominator"],
        f"{name}.reopen_lifetime_denominator",
    )
    reopen_rate = _nullable_nonnegative_ratio(
        item["reopen_lifetime_rate"],
        f"{name}.reopen_lifetime_rate",
    )
    expected_reopen_rate = (
        reopen_numerator / reopen_denominator if reopen_denominator else None
    )
    if (
        (expected_reopen_rate is None) != (reopen_rate is None)
        or (
            expected_reopen_rate is not None
            and reopen_rate is not None
            and abs(reopen_rate - expected_reopen_rate) > 1e-12
        )
    ):
        raise ValueError(f"{name}.reopen_lifetime_rate does not match division")
    return item


def _validate_transfer_reasons(
    value: object,
    segments_value: object,
) -> None:
    reasons = _require_mapping(value, "transfer_reasons")
    _require_exact_keys(
        reasons,
        {
            "observed_transfer_denominator",
            "triggers",
            "tpe",
            "step_result_missing",
            "guardrail",
            "escalation_guard_blocked",
        },
        "transfer_reasons",
    )
    denominator = _nonnegative_int(
        reasons["observed_transfer_denominator"],
        "transfer_reasons.observed_transfer_denominator",
    )
    segments = _require_mapping(segments_value, "segments")
    for dimension in _SEGMENTS:
        buckets = _require_mapping(
            segments[dimension],
            f"segments.{dimension}",
        )
        transferred_total = sum(
            _require_mapping(counts, "segment counts")["transferred"]
            for counts in buckets.values()
        )
        if transferred_total != denominator:
            raise ValueError("transfer reason denominator does not reconcile")

    trigger_rows = reasons["triggers"]
    if not isinstance(trigger_rows, list):
        raise ValueError("transfer_reasons.triggers must be a list")
    seen_triggers: set[
        tuple[str, str | None, str | None, str | None, str | None]
    ] = set()
    trigger_total = 0
    for raw_row in trigger_rows:
        row = _require_mapping(raw_row, "transfer_reasons.triggers item")
        _require_exact_keys(
            row,
            {"reason", "rule", "source", "stage", "skill", "count"},
            "transfer_reasons.triggers item",
        )
        reason = row["reason"]
        rule = row["rule"]
        source = row["source"]
        stage = row["stage"]
        skill = row["skill"]
        if reason not in _TRANSFER_TRIGGER_REASONS:
            raise ValueError("transfer_reasons trigger reason is invalid")
        if reason == "unknown":
            if any(value is not None for value in (rule, source, stage, skill)):
                raise ValueError("transfer_reasons unknown trigger is invalid")
        else:
            if rule not in _GUARDRAIL_RULES:
                raise ValueError("transfer_reasons trigger rule is invalid")
            if source not in _TRANSFER_TRIGGER_SOURCES:
                raise ValueError("transfer_reasons trigger source is invalid")
            if source == "skill_guardrail_checked":
                if stage not in {"input", "output"}:
                    raise ValueError("transfer_reasons trigger stage is invalid")
            elif stage is not None or skill is not None:
                raise ValueError("transfer_reasons global trigger metadata is invalid")
            if skill is not None and (
                not isinstance(skill, str)
                or not _is_safe_intent_label(skill)
            ):
                raise ValueError("transfer_reasons trigger skill is invalid")
            if reason != _expected_transfer_reason(rule, source, stage):
                raise ValueError("transfer_reasons trigger reason does not match source")
        key = (reason, rule, source, stage, skill)
        if key in seen_triggers:
            raise ValueError("transfer_reasons trigger rows must be unique")
        seen_triggers.add(key)
        trigger_total += _positive_int(
            row["count"],
            "transfer_reasons trigger count",
        )
    if trigger_total != denominator:
        raise ValueError("transfer_reasons triggers do not partition transfers")

    tpe_rows = reasons["tpe"]
    if not isinstance(tpe_rows, list):
        raise ValueError("transfer_reasons.tpe must be a list")
    seen_tpe: set[tuple[str, str | None]] = set()
    for raw_row in tpe_rows:
        row = _require_mapping(raw_row, "transfer_reasons.tpe item")
        _require_exact_keys(
            row,
            {"transstatus", "step_result", "count", "status"},
            "transfer_reasons.tpe item",
        )
        transstatus = row["transstatus"]
        if (
            not isinstance(transstatus, str)
            or _TPE_CODE_PATTERN.fullmatch(transstatus) is None
        ):
            raise ValueError("transfer_reasons.tpe transstatus is invalid")
        step_result = row["step_result"]
        if step_result is not None:
            if (
                not isinstance(step_result, str)
                or _TPE_CODE_PATTERN.fullmatch(step_result) is None
            ):
                raise ValueError("transfer_reasons.tpe step_result is invalid")
        status = row["status"]
        # None = cap chua co trong taxonomy TPE; khac None phai la chuoi khong
        # rong theo governed status tu resolve_tpe_status().
        if status is not None and (not isinstance(status, str) or status == ""):
            raise ValueError("transfer_reasons.tpe status is invalid")
        count = _positive_int(row["count"], "transfer_reasons.tpe count")
        key = (transstatus, step_result)
        if key in seen_tpe:
            raise ValueError("transfer_reasons.tpe rows must be unique")
        seen_tpe.add(key)
        if count > denominator:
            raise ValueError("transfer_reasons.tpe exceeds denominator")

    missing = _require_mapping(
        reasons["step_result_missing"],
        "transfer_reasons.step_result_missing",
    )
    _require_exact_keys(
        missing,
        {"count", "denominator"},
        "transfer_reasons.step_result_missing",
    )
    missing_count = _nonnegative_int(
        missing["count"],
        "transfer_reasons.step_result_missing.count",
    )
    missing_denominator = _nonnegative_int(
        missing["denominator"],
        "transfer_reasons.step_result_missing.denominator",
    )
    if missing_denominator != denominator or missing_count > denominator:
        raise ValueError("transfer_reasons step_result_missing does not reconcile")

    guardrail_rows = reasons["guardrail"]
    if not isinstance(guardrail_rows, list):
        raise ValueError("transfer_reasons.guardrail must be a list")
    # Each rule is bounded independently.  Rules can overlap on a session, so
    # their combined count is intentionally not bounded by the denominator.
    seen_rules: set[str] = set()
    for raw_row in guardrail_rows:
        row = _require_mapping(raw_row, "transfer_reasons.guardrail item")
        _require_exact_keys(
            row,
            {"rule", "count"},
            "transfer_reasons.guardrail item",
        )
        rule = row["rule"]
        if rule not in _GUARDRAIL_RULES or rule in seen_rules:
            raise ValueError("transfer_reasons.guardrail rule is invalid")
        seen_rules.add(rule)
        count = _positive_int(
            row["count"],
            "transfer_reasons.guardrail count",
        )
        if count > denominator:
            raise ValueError("transfer_reasons.guardrail exceeds denominator")

    escalation = _require_mapping(
        reasons["escalation_guard_blocked"],
        "transfer_reasons.escalation_guard_blocked",
    )
    _require_exact_keys(
        escalation,
        {"count", "denominator"},
        "transfer_reasons.escalation_guard_blocked",
    )
    count = _nonnegative_int(
        escalation["count"],
        "transfer_reasons.escalation_guard_blocked.count",
    )
    escalation_denominator = _nonnegative_int(
        escalation["denominator"],
        "transfer_reasons.escalation_guard_blocked.denominator",
    )
    if escalation_denominator != denominator or count > denominator:
        raise ValueError("transfer_reasons escalation does not reconcile")


def _validate_transfer_reason_rollup(
    aggregate_value: object,
    weekly_values: tuple[object, ...],
) -> None:
    aggregate = _require_mapping(aggregate_value, "transfer_reasons")
    weekly = tuple(
        _require_mapping(value, "weekly transfer_reasons")
        for value in weekly_values
    )
    if aggregate["observed_transfer_denominator"] != sum(
        value["observed_transfer_denominator"] for value in weekly
    ):
        raise ValueError("transfer reason weekly denominator does not reconcile")

    def row_counter(
        value: Mapping[str, object],
        field: str,
        keys: tuple[str, ...],
    ) -> Counter[tuple[object, ...]]:
        return Counter(
            {
                tuple(row[key] for key in keys): row["count"]
                for row in value[field]
            }
        )

    aggregate_tpe = row_counter(
        aggregate,
        "tpe",
        ("transstatus", "step_result"),
    )
    weekly_tpe: Counter[tuple[object, ...]] = Counter()
    aggregate_triggers = row_counter(
        aggregate,
        "triggers",
        ("reason", "rule", "source", "stage", "skill"),
    )
    weekly_triggers: Counter[tuple[object, ...]] = Counter()
    aggregate_guardrail = row_counter(
        aggregate,
        "guardrail",
        ("rule",),
    )
    weekly_guardrail: Counter[tuple[object, ...]] = Counter()
    for value in weekly:
        weekly_tpe.update(
            row_counter(value, "tpe", ("transstatus", "step_result"))
        )
        weekly_guardrail.update(
            row_counter(value, "guardrail", ("rule",))
        )
        weekly_triggers.update(
            row_counter(
                value,
                "triggers",
                ("reason", "rule", "source", "stage", "skill"),
            )
        )
    if (
        aggregate_tpe != weekly_tpe
        or aggregate_guardrail != weekly_guardrail
        or aggregate_triggers != weekly_triggers
    ):
        raise ValueError("transfer reason weekly rows do not reconcile")
    aggregate_missing = _require_mapping(
        aggregate["step_result_missing"],
        "transfer_reasons.step_result_missing",
    )
    if (
        aggregate_missing["count"]
        != sum(
            _require_mapping(
                value["step_result_missing"],
                "weekly step_result_missing",
            )["count"]
            for value in weekly
        )
        or aggregate_missing["denominator"]
        != sum(
            _require_mapping(
                value["step_result_missing"],
                "weekly step_result_missing",
            )["denominator"]
            for value in weekly
        )
    ):
        raise ValueError(
            "transfer reason weekly step_result_missing does not reconcile"
        )
    aggregate_escalation = _require_mapping(
        aggregate["escalation_guard_blocked"],
        "transfer_reasons.escalation_guard_blocked",
    )
    if aggregate_escalation["count"] != sum(
        _require_mapping(
            value["escalation_guard_blocked"],
            "weekly escalation_guard_blocked",
        )["count"]
        for value in weekly
    ):
        raise ValueError("transfer reason weekly escalation does not reconcile")


def _validate_segment_rollup(
    aggregate_value: object,
    weekly_values: tuple[object, ...],
) -> None:
    aggregate = _require_mapping(aggregate_value, "segments")
    weekly = tuple(
        _require_mapping(value, "weekly segments")
        for value in weekly_values
    )
    fields = ("total", "ai_first", "transferred", "reopen", "ai_end_to_end", "direct_cs")
    for dimension in _SEGMENTS:
        aggregate_buckets = _require_mapping(
            aggregate[dimension],
            f"segments.{dimension}",
        )
        weekly_labels: set[object] = set()
        weekly_counts: defaultdict[object, Counter[str]] = defaultdict(Counter)
        for segments in weekly:
            buckets = _require_mapping(
                segments[dimension],
                f"weekly segments.{dimension}",
            )
            weekly_labels.update(buckets)
            for label, raw_counts in buckets.items():
                counts = _require_mapping(raw_counts, "weekly segment counts")
                for field in fields:
                    weekly_counts[label][field] += counts[field]
        default_label = _NO_SKILL if dimension == "skill" else _MISSING
        expected_labels = weekly_labels or {default_label}
        if set(aggregate_buckets) != expected_labels:
            raise ValueError(
                f"segment weekly rows do not reconcile for {dimension}"
            )
        for label, raw_counts in aggregate_buckets.items():
            counts = _require_mapping(raw_counts, "segment counts")
            if any(
                counts[field] != weekly_counts[label][field]
                for field in fields
            ):
                raise ValueError(
                    f"segment weekly rows do not reconcile for {dimension}"
                )


def _validate_segments(value: object, total: object) -> None:
    segments = _require_mapping(value, "segments")
    _require_exact_keys(segments, set(_SEGMENTS), "segments")
    for name in _SEGMENTS:
        buckets = _require_mapping(segments[name], f"segments.{name}")
        required_missing_label = _NO_SKILL if name == "skill" else _MISSING
        if required_missing_label not in buckets:
            raise ValueError("segments must include missing bucket")
        summed = 0
        for label, counts in buckets.items():
            _validate_segment_label(name, label)
            _validate_count_map(
                counts,
                {"total", "ai_first", "transferred", "reopen", "ai_end_to_end", "direct_cs"},
                f"segments.{name}",
            )
            summed += counts["total"]
        if summed != total: raise ValueError("segment totals do not reconcile")


def _validate_segment_label(dimension: str, value: object) -> None:
    if dimension == "intent":
        if value == _MISSING or value == "khác":
            return
        if not _is_safe_intent_label(value):
            raise ValueError("intent segment label is invalid")
        return
    _safe_string(value, f"segments.{dimension} label")


def _validate_projected_intent_frequency(
    dashboard: Mapping[str, object],
    tickets: tuple[dict[str, object], ...],
) -> None:
    """Defence in depth for persisted/browser-ready intent values.

    Ticket Explorer deliberately excludes non-numeric session IDs, so its rows
    are not the cohort denominator.  The T2–CN intent segment is the full
    population and is therefore the authoritative global frequency source.
    """
    views = _require_mapping(dashboard["views"], "views")
    mon_sun = _require_mapping(views["mon_sun"], "views.mon_sun")
    mon_sun_segments = _require_mapping(mon_sun["segments"], "views.mon_sun.segments")
    global_buckets = _require_mapping(mon_sun_segments["intent"], "views.mon_sun.segments.intent")
    global_counts = {
        label: bucket["total"]
        for label, bucket in global_buckets.items()
        if label not in {_MISSING, "khác"}
        and isinstance(bucket, Mapping)
        and isinstance(bucket.get("total"), int)
    }
    for intent, count in global_counts.items():
        if not _is_safe_intent_label(intent) or count < 5:
            raise ValueError("intent is not approved for snapshot storage")
    for ticket in tickets:
        intent = ticket.get("intent")
        if intent is not None and intent != "khác" and (
            not isinstance(intent, str) or intent not in global_counts
        ):
            raise ValueError("intent is not approved for snapshot storage")
    for view in views.values():
        projected_view = _require_mapping(view, "view")
        segments = _require_mapping(projected_view["segments"], "segments")
        intent_buckets = _require_mapping(segments["intent"], "segments.intent")
        for label in intent_buckets:
            if label in {_MISSING, "khác"}:
                continue
            if not _is_safe_intent_label(label) or global_counts.get(label, 0) < 5:
                raise ValueError("intent segment is not approved for snapshot storage")
        by_week = _require_mapping(projected_view["by_week"], "view.by_week")
        for detail_value in by_week.values():
            detail = _require_mapping(detail_value, "view.by_week item")
            weekly_segments = _require_mapping(
                detail["segments"],
                "view.by_week segments",
            )
            weekly_intents = _require_mapping(
                weekly_segments["intent"],
                "view.by_week segments.intent",
            )
            for label in weekly_intents:
                if label in {_MISSING, "khác"}:
                    continue
                if (
                    not _is_safe_intent_label(label)
                    or global_counts.get(label, 0) < 5
                ):
                    raise ValueError(
                        "intent by-week segment is not approved for snapshot storage"
                    )


def _validate_weekly(value: object, expected_definition: str) -> None:
    if not isinstance(value, list): raise ValueError("weekly must be a list")
    for summary in value:
        item = _require_mapping(summary, "weekly item")
        _require_exact_keys(item, _WEEKLY_KEYS, "weekly item")
        _week_string(item["cohort_week"], "weekly cohort_week")
        if item["cohort_status"] not in {"complete", "wtd"}: raise ValueError("weekly cohort_status is invalid")
        if item["week_definition"] != expected_definition: raise ValueError("weekly week_definition is invalid")
        if not isinstance(item["has_data"], bool): raise ValueError("weekly has_data is invalid")
        for field in ("total_tickets", "ai_first_count", "ai_end_to_end_count", "ai_then_cs_count", "direct_cs_count", "unclassified_count", "reopen_lifetime_numerator", "reopen_lifetime_denominator", "gt4_turn_with_cs", "gt4_turn_without_cs", "max_replies_rule_fired", "resolved_first_reply"):
            _nonnegative_int(item[field], f"weekly {field}")
        if item["has_data"] != bool(item["total_tickets"]): raise ValueError("weekly has_data does not match total")
        if item["ai_first_count"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"]: raise ValueError("weekly ai_first does not reconcile")
        if item["total_tickets"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"] + item["direct_cs_count"] + item["unclassified_count"]: raise ValueError("weekly outcomes do not reconcile")
        if item["resolved_first_reply"] > item["ai_end_to_end_count"]: raise ValueError("weekly resolved_first_reply exceeds ai_end_to_end_count")
        _rate(item["ai_first_rate"], "weekly ai_first_rate")
        expected_ai_rate = (
            item["ai_first_count"] / item["total_tickets"]
            if item["total_tickets"]
            else 0.0
        )
        if abs(item["ai_first_rate"] - expected_ai_rate) > 1e-12:
            raise ValueError("weekly ai_first_rate does not match division")
        _nullable_rate(item["reopen_7d_rate"], "weekly reopen_7d_rate")
        _nullable_nonnegative_int(item["reopen_7d_denominator"], "weekly reopen_7d_denominator")
        _nullable_nonnegative_ratio(item["reopen_lifetime_rate"], "weekly reopen_lifetime_rate")
        reopen_7d_rate = item["reopen_7d_rate"]
        reopen_7d_denominator = item["reopen_7d_denominator"]
        if reopen_7d_denominator in {None, 0}:
            if reopen_7d_rate is not None:
                raise ValueError("weekly reopen_7d_rate does not match division")
        elif reopen_7d_rate is None or abs(
            reopen_7d_rate * reopen_7d_denominator
            - round(reopen_7d_rate * reopen_7d_denominator)
        ) > 1e-9:
            raise ValueError("weekly reopen_7d_rate does not match division")
        lifetime_numerator = item["reopen_lifetime_numerator"]
        lifetime_denominator = item["reopen_lifetime_denominator"]
        expected_lifetime_rate = (
            lifetime_numerator / lifetime_denominator
            if lifetime_denominator
            else None
        )
        if (
            (expected_lifetime_rate is None)
            != (item["reopen_lifetime_rate"] is None)
            or (
                expected_lifetime_rate is not None
                and abs(
                    item["reopen_lifetime_rate"] - expected_lifetime_rate
                )
                > 1e-12
            )
        ):
            raise ValueError(
                "weekly reopen_lifetime_rate does not match division"
            )
        _nonnegative_int(item["ai_reply_sum_ai_first"], "weekly ai_reply_sum_ai_first")
        _nullable_nonnegative_number(item["ai_reply_mean_ai_first"], "weekly ai_reply_mean_ai_first")
        # The dashboard shows both and the reader divides one by the other, so
        # a payload where they disagree is not merely odd -- it renders a ledger
        # that does not add up.
        if item["ai_first_count"] == 0:
            if item["ai_reply_sum_ai_first"] != 0:
                raise ValueError("weekly ai_reply_sum_ai_first must be 0 without ai_first tickets")
        elif (
            item["ai_reply_mean_ai_first"] is None
            or abs(
                item["ai_reply_sum_ai_first"]
                - item["ai_reply_mean_ai_first"] * item["ai_first_count"]
            )
            > 1e-6
        ):
            raise ValueError("weekly ai_reply_sum_ai_first does not match the mean")
        for field in ("ai_reply_p50", "ai_reply_p90", "ai_reply_max"): _nullable_nonnegative_int(item[field], f"weekly {field}")
        _parse_utc_iso(item["as_of"], "weekly as_of")
        _validate_reopen_reason(
            item["reopen_reason"],
            item["reopen_7d_rate"],
            item["reopen_7d_denominator"],
        )


def _validate_reopen_reason(
    value: object,
    reopen_7d_rate: object,
    reopen_7d_denominator: object,
) -> None:
    reason = _require_mapping(value, "reopen_reason")
    _require_exact_keys(
        reason,
        {"labels_version", "status", "counts", "by_business", "coverage", "control"},
        "reopen_reason",
    )
    if not isinstance(reason["labels_version"], str) or re.fullmatch(r"v[0-9]+", reason["labels_version"]) is None:
        raise ValueError("reopen_reason labels_version is invalid")
    status = reason["status"]
    if status not in {"pending", "labeled", "unavailable"}:
        raise ValueError("reopen_reason status is invalid")
    coverage = _require_mapping(reason["coverage"], "reopen_reason coverage")
    _require_exact_keys(
        coverage,
        {"population", "labeled", "abstained", "failed", "invalid"},
        "reopen_reason coverage",
    )
    for field in coverage:
        _nonnegative_int(coverage[field], f"reopen_reason coverage {field}")
    counts = _require_mapping(reason["counts"], "reopen_reason counts")
    businesses = _require_mapping(reason["by_business"], "reopen_reason by_business")
    count_total = 0
    abstained = 0
    for label, outcomes_value in counts.items():
        if not isinstance(label, str) or _INTENT_PATTERN.fullmatch(label) is None:
            raise ValueError("reopen_reason label is invalid")
        outcomes = _require_mapping(outcomes_value, "reopen_reason outcomes")
        if not outcomes or not set(outcomes).issubset({"ai_end_to_end", "ai_then_cs"}):
            raise ValueError("reopen_reason outcomes are invalid")
        for outcome_count in outcomes.values():
            count_total += _positive_int(outcome_count, "reopen_reason count")
            if label == "other":
                abstained += outcome_count
    business_by_label: Counter[str] = Counter()
    for business, labels_value in businesses.items():
        _safe_string(business, "reopen_reason business")
        labels = _require_mapping(labels_value, "reopen_reason business labels")
        if not labels:
            raise ValueError("reopen_reason business labels are invalid")
        for label, label_count in labels.items():
            if not isinstance(label, str) or _INTENT_PATTERN.fullmatch(label) is None:
                raise ValueError("reopen_reason label is invalid")
            business_by_label[label] += _positive_int(label_count, "reopen_reason business count")
    if status == "labeled":
        if (
            count_total != coverage["labeled"]
            or business_by_label
            != Counter(
                {
                    label: sum(_require_mapping(outcomes, "reopen_reason outcomes").values())
                    for label, outcomes in counts.items()
                }
            )
            or abstained != coverage["abstained"]
            or coverage["abstained"] > coverage["labeled"]
            or coverage["population"]
            != coverage["labeled"] + coverage["failed"] + coverage["invalid"]
        ):
            raise ValueError("reopen_reason coverage does not reconcile")
    elif counts or businesses or any(coverage[field] for field in ("labeled", "abstained", "failed", "invalid")):
        raise ValueError("reopen_reason non-labeled status must be empty")
    control = _require_mapping(reason["control"], "reopen_reason control")
    _require_exact_keys(
        control,
        {"direct_cs_reopen_7d_rate", "direct_cs_denominator"},
        "reopen_reason control",
    )
    denominator = _nonnegative_int(control["direct_cs_denominator"], "reopen_reason control denominator")
    rate = control["direct_cs_reopen_7d_rate"]
    _nullable_rate(rate, "reopen_reason control rate")
    if denominator == 0 and rate is not None:
        raise ValueError("reopen_reason control rate does not match denominator")
    if denominator > 0:
        if rate is None or abs(rate * denominator - round(rate * denominator)) > 1e-9:
            raise ValueError("reopen_reason control rate does not match denominator")
    if reopen_7d_denominator is None and (denominator != 0 or rate is not None):
        raise ValueError("reopen_reason immature control is invalid")


def _week_string(value: object, name: str) -> None:
    if not isinstance(value, str): raise ValueError(f"{name} is invalid")
    try: parsed = date.fromisoformat(value)
    except ValueError as error: raise ValueError(f"{name} is invalid") from error
    if parsed.weekday() != 0: raise ValueError(f"{name} must be a Monday")


def _date_string(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{name} is invalid")
    return parsed


def _validate_count_map(value: object, keys: set[str] | frozenset[str], name: str) -> None:
    mapping = _require_mapping(value, name); _require_exact_keys(mapping, keys, name)
    for count in mapping.values(): _nonnegative_int(count, name)


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value): raise ValueError(f"{name} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, object], keys: set[str] | frozenset[str], name: str) -> None:
    if set(value) != set(keys): raise ValueError(f"{name} has unsupported or missing fields")


def _rate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1: raise ValueError(f"{name} must be a rate")
    return float(value)


def _nullable_rate(value: object, name: str) -> float | None:
    return None if value is None else _rate(value, name)


def _nonnegative_ratio(value: object, name: str) -> float:
    """A ratio that, unlike ``_rate``, is not capped at 1 -- reopen_lifetime is
    now a per-ticket count, so its mean across tickets can exceed 1.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative ratio")
    return float(value)


def _nullable_nonnegative_ratio(value: object, name: str) -> float | None:
    return None if value is None else _nonnegative_ratio(value, name)


def _nullable_nonnegative_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)