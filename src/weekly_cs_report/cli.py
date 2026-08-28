from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Mapping, Sequence

from dotenv import dotenv_values, load_dotenv

from .artifacts import ProtectedArtifactRun, ProtectedArtifactStore
from .categories import Taxonomy
from .categories import load_taxonomy
from .cohort import WeekDefinition, build_cohort_window
from .dimension_verifier import (
    is_ticket_trace,
    validate_dimension_report_privacy,
    verify_raw_ticket_dimensions,
)
from .content_labeler import LabelConfigError, LabelSet, load_label_set
from .langfuse_client import IngestionReceipt, LangfuseAPIError, LangfuseClient
from .llm_client import LLMClient, PIIApprovalRequiredError
from .models import AnalysisResult, ScoreSpec
from .reopen_golden import (
    GoldenSampleError,
    load_discovery_session_ids,
    sample_golden,
    write_golden_sample,
)
from .reopen_eval import (
    GoldenEvaluationError,
    LabelPredictionClient,
    evaluate_labels,
    evaluation_payload,
    load_golden_evaluation,
)
from .reopen_pii_review import (
    PII_REVIEW_LIMIT,
    PIIReviewError,
    PIIReviewRow,
    build_pii_review_rows,
    write_pii_review_csv,
)
from .reopen_population import build_reopen_population
from .reopen_sampling import sample_reopen, write_reopen_discovery_csv
from .report import compute_report
from .scores import (
    build_session_scores,
    build_weekly_scores,
    chunk_events,
    score_to_event,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_BASE_URL = "https://langfuse.zalopay.vn"
TARGET_PROJECT_ID = "cmqubjzur000hz507ptubh2l9"
ANALYTICS_VERSION = "v1"
VERIFIER_TAXONOMY_PATH = PROJECT_ROOT / "config" / "taxonomy.v2.json"
REOPEN_LABELS_PATH = PROJECT_ROOT / "config" / "reopen_labels.v1.json"
REOPEN_DISCOVERY_PATH = (
    PROJECT_ROOT / "artifacts" / "reopen_discovery" / "reasons.csv"
)
FRESHDESK_AGENT_CONFIG_PATH = PROJECT_ROOT / "config" / "freshdesk_agents.v1.json"
FRESHDESK_RECONCILIATION_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "freshdesk_reconciliation_agents.v1.json"
)
FRESHDESK_RECONCILIATION_SOURCE_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "freshdesk_discovery"
    / "human_agent_candidates.v1.json"
)
CSAT_RUNTIME_PATH = PROJECT_ROOT / "runtime"
READBACK_SAMPLE_LIMIT = 25
READBACK_TIMEOUT_SECONDS = 30.0
_ENVIRONMENT_NAMES = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


class ConfigurationError(RuntimeError):
    pass


class WriteRequiredError(RuntimeError):
    pass


class ReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnvironmentSettings:
    public_key: str
    secret_key: str
    base_url: str


@dataclass(frozen=True)
class RunConfig:
    as_of: datetime
    weeks: int = 12
    include_current_wtd: bool = False
    artifact_root: Path = PROJECT_ROOT / "artifacts"
    taxonomy_path: Path = PROJECT_ROOT / "config" / "taxonomy.v2.json"
    week_definition: WeekDefinition = "mon_sun"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.weeks < 1:
            raise ValueError("weeks must be at least 1")
        if self.week_definition not in {"mon_sun", "mon_fri"}:
            raise ValueError("week_definition must be mon_sun or mon_fri")
        object.__setattr__(self, "artifact_root", Path(self.artifact_root))
        object.__setattr__(self, "taxonomy_path", Path(self.taxonomy_path))


@dataclass(frozen=True)
class ApprovedReopenRunConfig(RunConfig):
    """Process-private approval material for the controlled reopen runner."""

    approved_pii_review_rows: tuple[PIIReviewRow, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class ReconciliationResult:
    analysis: AnalysisResult
    requested_event_ids: tuple[str, ...]
    acknowledged_event_ids: tuple[str, ...]
    sampled_score_ids: tuple[str, ...]
    matched_score_ids: tuple[str, ...]
    success: bool
    run_directory: Path


@dataclass(frozen=True)
class _AnalysisRun:
    result: AnalysisResult
    taxonomy: Taxonomy
    scores: tuple[ScoreSpec, ...]
    artifact_run: ProtectedArtifactRun


def _parse_as_of(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("as-of must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("as-of must include a timezone offset")
    return parsed


def _parse_cohort_week(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("week must be YYYY-MM-DD") from error
    if parsed.weekday() != 0:
        raise argparse.ArgumentTypeError("week must start on Monday")
    return parsed


def _add_window_options(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool = False,
) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--weeks",
        type=int,
        default=default if suppress_defaults else 12,
    )
    parser.add_argument(
        "--include-current-wtd",
        action="store_true",
        default=default if suppress_defaults else False,
        help="include the current Monday-to-as-of cohort",
    )
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=default,
    )


def _add_run_options(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool = False,
) -> None:
    _add_window_options(parser, suppress_defaults=suppress_defaults)
    parser.add_argument(
        "--week-definition",
        choices=("mon_sun", "mon_fri"),
        default=argparse.SUPPRESS if suppress_defaults else "mon_sun",
        help="weekly inclusion boundary (default: mon_sun)",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=(
            argparse.SUPPRESS
            if suppress_defaults
            else Path("artifacts")
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weekly-cs-report")
    _add_run_options(parser)
    subparsers = parser.add_subparsers(dest="command")

    dry_run = subparsers.add_parser("dry-run")
    _add_run_options(dry_run, suppress_defaults=True)

    inspect = subparsers.add_parser("inspect-session")
    inspect.add_argument("session_id")
    _add_run_options(inspect, suppress_defaults=True)

    verify_dimensions = subparsers.add_parser("verify-dimensions")
    _add_window_options(verify_dimensions, suppress_defaults=True)
    verify_dimensions.add_argument("--require-p0", action="store_true")

    sample_reopen = subparsers.add_parser("sample-reopen")
    sample_reopen.add_argument("--weeks", type=int, required=True)
    sample_reopen.add_argument("--out", type=Path, required=True)

    sample_golden_parser = subparsers.add_parser("sample-golden")
    sample_golden_parser.add_argument("--n", type=int, required=True)
    sample_golden_parser.add_argument("--out", type=Path, required=True)

    eval_labels_parser = subparsers.add_parser("eval-labels")
    eval_labels_parser.add_argument("--golden", type=Path, required=True)
    eval_labels_parser.add_argument("--labels", type=Path, required=True)

    discover_agents = subparsers.add_parser("discover-agents")
    discover_agents.add_argument("--weeks", type=int, default=13)
    discover_agents.add_argument("--max-workers", type=int, default=2)
    discover_agents.add_argument("--max-duration", type=int, default=30 * 60)
    discover_agents.add_argument("--runtime-dir", type=Path, default=CSAT_RUNTIME_PATH)

    fetch_csat = subparsers.add_parser("fetch-csat")
    fetch_csat.add_argument("--weeks", type=int, default=13)
    fetch_csat.add_argument("--since-week", type=_parse_cohort_week)
    fetch_csat.add_argument("--max-workers", type=int, default=2)
    fetch_csat.add_argument("--max-duration", type=int, default=30 * 60)
    fetch_csat.add_argument("--runtime-dir", type=Path, default=CSAT_RUNTIME_PATH)
    fetch_csat.add_argument(
        "--auth", choices=("cookie", "rest"), default="cookie"
    )

    reconcile_freshdesk = subparsers.add_parser(
        "reconcile-freshdesk-outcomes"
    )
    reconcile_freshdesk.add_argument("--weeks", type=int, default=13)
    reconcile_freshdesk.add_argument("--max-workers", type=int, default=2)
    reconcile_freshdesk.add_argument(
        "--max-duration", type=int, default=30 * 60
    )
    reconcile_freshdesk.add_argument(
        "--runtime-dir", type=Path, default=CSAT_RUNTIME_PATH
    )
    reconcile_freshdesk.add_argument(
        "--auth", choices=("cookie", "rest"), default="cookie"
    )
    entry_coverage = subparsers.add_parser("fetch-freshdesk-entry-coverage")
    entry_coverage.add_argument("--weeks", type=int, default=13)
    entry_coverage.add_argument("--max-workers", type=int, default=1)
    entry_coverage.add_argument("--max-duration", type=int, default=30 * 60)
    entry_coverage.add_argument(
        "--runtime-dir", type=Path, default=CSAT_RUNTIME_PATH
    )
    entry_coverage.add_argument(
        "--auth", choices=("cookie", "rest"), default="cookie"
    )
    parser.set_defaults(command="dry-run")
    return parser


def load_environment(
    environ: Mapping[str, str] | None = None,
) -> EnvironmentSettings:
    if environ is None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        environ = os.environ
    missing = tuple(name for name in _ENVIRONMENT_NAMES if not environ.get(name))
    if missing:
        raise ConfigurationError(
            "Missing environment variables: " + ", ".join(missing)
        )
    if environ["LANGFUSE_BASE_URL"].rstrip("/") != TARGET_BASE_URL:
        raise ConfigurationError(
            "LANGFUSE_BASE_URL does not match the configured target"
        )
    return EnvironmentSettings(
        public_key=environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=environ["LANGFUSE_SECRET_KEY"],
        base_url=TARGET_BASE_URL,
    )


def _build_client(settings: EnvironmentSettings) -> LangfuseClient:
    return LangfuseClient(
        settings.base_url,
        settings.public_key,
        settings.secret_key,
    )


def _score_specs(
    result: AnalysisResult,
    taxonomy_version: str,
) -> tuple[ScoreSpec, ...]:
    scores: list[ScoreSpec] = []
    for session in result.sessions:
        scores.extend(
            build_session_scores(
                session,
                result.transfers.get(session.session_id),
                result.gate_status,
                TARGET_PROJECT_ID,
                ANALYTICS_VERSION,
                taxonomy_version,
            )
        )
    for summary in result.weekly:
        scores.extend(
            build_weekly_scores(
                summary,
                result.gate_status,
                TARGET_PROJECT_ID,
                ANALYTICS_VERSION,
                taxonomy_version,
            )
        )
    return tuple(scores)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary_payload(
    result: AnalysisResult,
    *,
    traces_fetched: int,
    traces_deduplicated: int,
) -> dict[str, object]:
    selection = result.selection
    outcomes = Counter(session.outcome or "none" for session in result.sessions)
    quality_reasons = Counter(
        issue.reason for issue in (*selection.invalid_keyed, *selection.unkeyed)
    )
    quality_reasons.update(
        session.data_quality
        for session in result.sessions
        if session.data_quality != "valid"
    )
    reopen_lifetime = [
        session.reopen_lifetime
        for session in result.sessions
        if session.reopen_lifetime is not None
    ]
    reopen_within_7d = [
        session.reopen_within_7d
        for session in result.sessions
        if session.reopen_within_7d is not None
    ]
    control_within_7d = [
        session.control_reopen_within_7d
        for session in result.sessions
        if session.control_reopen_within_7d is not None
    ]
    reply_distribution = Counter(
        session.ai_reply_count for session in result.sessions
    )
    transfer_coverage = {
        "business": dict(
            sorted(
                Counter(
                    categories.business.value
                    for categories in result.transfers.values()
                ).items()
            )
        ),
        "tpe": dict(
            sorted(
                Counter(
                    categories.tpe.value
                    for categories in result.transfers.values()
                ).items()
            )
        ),
        "guardrail_rule": dict(
            sorted(
                Counter(
                    categories.guardrail_rule.value
                    for categories in result.transfers.values()
                ).items()
            )
        ),
    }
    return {
        "as_of": _utc_iso(selection.window.as_of),
        "source": {
            "traces_fetched": traces_fetched,
            "traces_deduplicated": traces_deduplicated,
        },
        "counts": {
            "eligible_ticket_count": len(result.sessions),
            "unclassified_eligible_count": outcomes["unclassified"],
            "invalid_keyed_session_count": len(selection.invalid_keyed),
            "unkeyed_trace_count": len(selection.unkeyed),
            "weekend_start_count": sum(
                session.is_weekend_start for session in result.sessions
            ),
            "left_censored_count": len(selection.left_censored),
            "pre_window_start_count": len(selection.pre_window_start),
        },
        "outcomes": dict(sorted(outcomes.items())),
        "ai_first": {
            "true": sum(session.ai_first for session in result.sessions),
            "false": sum(not session.ai_first for session in result.sessions),
        },
        "reopen": {
            "lifetime": {
                "numerator": sum(reopen_lifetime),
                "denominator": len(reopen_lifetime),
            },
            "within_7d": {
                "numerator": sum(reopen_within_7d),
                "denominator": len(reopen_within_7d),
            },
            "control_within_7d": {
                "numerator": sum(control_within_7d),
                "denominator": len(control_within_7d),
                "rate": (
                    sum(control_within_7d) / len(control_within_7d)
                    if control_within_7d
                    else None
                ),
            },
        },
        "reply_count_distribution": dict(sorted(reply_distribution.items())),
        "transfer_coverage": transfer_coverage,
        "gate_status": asdict(result.gate_status),
        "quality_reasons": dict(sorted(quality_reasons.items())),
    }


_WEEKLY_COLUMNS = (
    "cohort_week",
    "cohort_status",
    "total_tickets",
    "ai_first_count",
    "ai_first_rate",
    "ai_end_to_end_count",
    "ai_then_cs_count",
    "direct_cs_count",
    "unclassified_count",
    "reopen_7d_rate",
    "reopen_7d_denominator",
    "reopen_lifetime_rate",
    "ai_reply_p50",
    "ai_reply_p90",
    "ai_reply_max",
    "as_of",
    "week_definition",
    "has_data",
    "reopen_lifetime_numerator",
    "reopen_lifetime_denominator",
    "ai_reply_mean_ai_first",
    "gt4_turn_with_cs",
    "gt4_turn_without_cs",
    "max_replies_rule_fired",
    "resolved_first_reply",
)


def _weekly_rows(
    result: AnalysisResult,
    week_definition: WeekDefinition = "mon_sun",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    summaries = (
        result.weekly_mon_sun or result.weekly
        if week_definition == "mon_sun"
        else result.weekly_mon_fri
    )
    for summary in summaries:
        row = asdict(summary)
        row["cohort_week"] = summary.cohort_week.isoformat()
        row["as_of"] = _utc_iso(summary.as_of) if summary.as_of else ""
        rows.append(row)
    return rows


_INVESTIGATION_COLUMNS = (
    "group",
    "session_id",
    "trace_id",
    "cohort_week",
    "outcome",
    "data_quality",
    "reason",
    "business_category",
    "tpe_category",
    "guardrail_rule",
)


def _investigation_rows(result: AnalysisResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for session in result.sessions:
        categories = result.transfers.get(session.session_id)
        rows.append(
            {
                "group": "eligible",
                "session_id": session.session_id,
                "trace_id": session.turn0_trace_id,
                "cohort_week": session.cohort_week.isoformat(),
                "outcome": session.outcome or "",
                "data_quality": session.data_quality,
                "reason": session.no_ai_first_reason or "",
                "business_category": categories.business.value if categories else "",
                "tpe_category": categories.tpe.value if categories else "",
                "guardrail_rule": (
                    categories.guardrail_rule.value if categories else ""
                ),
            }
        )
    for issue in result.selection.invalid_keyed:
        rows.append(
            {
                "group": "invalid_keyed",
                "session_id": issue.session_id or "",
                "trace_id": issue.trace_id or "",
                "cohort_week": "",
                "outcome": "",
                "data_quality": issue.reason,
                "reason": issue.reason,
                "business_category": "",
                "tpe_category": "",
                "guardrail_rule": "",
            }
        )
    for issue in result.selection.unkeyed:
        rows.append(
            {
                "group": "unkeyed",
                "session_id": "",
                "trace_id": issue.trace_id or "",
                "cohort_week": "",
                "outcome": "",
                "data_quality": issue.reason,
                "reason": issue.reason,
                "business_category": "",
                "tpe_category": "",
                "guardrail_rule": "",
            }
        )
    for group, session_ids in (
        ("weekend_start", result.selection.weekend_start),
        ("left_censored", result.selection.left_censored),
        ("pre_window_start", result.selection.pre_window_start),
    ):
        for session_id in session_ids:
            rows.append(
                {
                    "group": group,
                    "session_id": session_id,
                    "trace_id": "",
                    "cohort_week": "",
                    "outcome": "",
                    "data_quality": group,
                    "reason": group,
                    "business_category": "",
                    "tpe_category": "",
                    "guardrail_rule": "",
                }
            )
    return rows


def _manifest_payload(
    scores: Sequence[ScoreSpec],
    *,
    as_of: datetime,
    taxonomy_version: str,
) -> dict[str, object]:
    return {
        "as_of": _utc_iso(as_of),
        "project_id": TARGET_PROJECT_ID,
        "analytics_version": ANALYTICS_VERSION,
        "taxonomy_version": taxonomy_version,
        "score_count": len(scores),
        "scores": [
            {
                "id": score.id,
                "event_id": score.event_id,
                "name": score.name,
                "value": score.value,
                "data_type": score.data_type,
                "session_id": score.session_id,
                "timestamp": _utc_iso(score.timestamp),
                "environment": score.environment,
                "metadata": score.metadata,
            }
            for score in scores
        ],
    }


def _write_analysis_artifacts(
    config: RunConfig,
    result: AnalysisResult,
    taxonomy: Taxonomy,
    scores: tuple[ScoreSpec, ...],
    *,
    traces_fetched: int,
    traces_deduplicated: int,
) -> ProtectedArtifactRun:
    artifact_run = ProtectedArtifactStore(config.artifact_root).start_run(
        config.as_of
    )
    artifact_run.write_json(
        "summary.json",
        _summary_payload(
            result,
            traces_fetched=traces_fetched,
            traces_deduplicated=traces_deduplicated,
        ),
    )
    artifact_run.write_csv(
        "weekly_summary.csv",
        _weekly_rows(result, config.week_definition),
        fieldnames=_WEEKLY_COLUMNS,
    )
    artifact_run.write_csv(
        "investigation.csv",
        _investigation_rows(result),
        fieldnames=_INVESTIGATION_COLUMNS,
    )
    artifact_run.write_json(
        "score_manifest.json",
        _manifest_payload(
            scores,
            as_of=config.as_of,
            taxonomy_version=taxonomy.version,
        ),
    )
    artifact_run.publish_latest()
    return artifact_run


def _execute_analysis(config: RunConfig, client: LangfuseClient) -> _AnalysisRun:
    report_run = compute_report(
        client,
        as_of=config.as_of,
        weeks=config.weeks,
        include_current_wtd=config.include_current_wtd,
        taxonomy_path=config.taxonomy_path,
    )
    scores = _score_specs(report_run.result, report_run.taxonomy.version)
    artifact_run = _write_analysis_artifacts(
        config,
        report_run.result,
        report_run.taxonomy,
        scores,
        traces_fetched=report_run.traces_fetched,
        traces_deduplicated=report_run.traces_deduplicated,
    )
    return _AnalysisRun(
        report_run.result,
        report_run.taxonomy,
        scores,
        artifact_run,
    )


def _terminal_summary(result: AnalysisResult) -> dict[str, object]:
    return {
        "as_of": _utc_iso(result.selection.window.as_of),
        "eligible_ticket_count": len(result.sessions),
        "week_count": len(result.weekly),
        "gate_status": asdict(result.gate_status),
    }


def run_dry_run(config: RunConfig, client: LangfuseClient) -> AnalysisResult:
    analysis_run = _execute_analysis(config, client)
    print(json.dumps(_terminal_summary(analysis_run.result), sort_keys=True))
    return analysis_run.result


def run_sample_reopen(
    config: RunConfig,
    client: LangfuseClient,
    llm_client: LLMClient,
    output_directory: Path,
    *,
    pii_approved: bool = False,
) -> Path:
    """Run discovery through the existing read-only report path.

    This helper intentionally accepts an already-created LLM client, but still
    fails closed unless its caller explicitly carries the manual PII approval
    decision.  The command-line entrypoint does not expose that route today.
    """
    if (
        pii_approved is not True
        or not isinstance(config, ApprovedReopenRunConfig)
        or not config.approved_pii_review_rows
    ):
        raise PIIApprovalRequiredError()
    report_run = compute_report(
        client,
        as_of=config.as_of,
        weeks=config.weeks,
        include_current_wtd=config.include_current_wtd,
        taxonomy_path=config.taxonomy_path,
    )
    population = build_reopen_population(
        report_run.result.sessions,
        report_run.result.selection.eligible,
    )
    expected_review_rows = build_pii_review_rows(population)
    if (
        len(expected_review_rows) != PII_REVIEW_LIMIT
        or config.approved_pii_review_rows[:PII_REVIEW_LIMIT]
        != expected_review_rows
    ):
        raise PIIApprovalRequiredError()
    discovery = sample_reopen(population.sessions, llm_client)
    return write_reopen_discovery_csv(output_directory, discovery.rows)


def run_sample_reopen_pii_review(
    config: RunConfig,
    client: LangfuseClient,
    output_directory: Path,
) -> Path:
    """Export the manual PII review sample without constructing an LLM client."""
    report_run = compute_report(
        client,
        as_of=config.as_of,
        weeks=config.weeks,
        include_current_wtd=config.include_current_wtd,
        taxonomy_path=config.taxonomy_path,
    )
    population = build_reopen_population(
        report_run.result.sessions,
        report_run.result.selection.eligible,
    )
    return write_pii_review_csv(output_directory, population)


def run_sample_golden(
    config: RunConfig,
    client: LangfuseClient,
    output_directory: Path,
    *,
    n: int,
    labels: LabelSet,
    discovery_session_ids: frozenset[str],
) -> tuple[Path, Path]:
    """Build and persist a blinded golden sample without invoking a model."""
    report_run = compute_report(
        client,
        as_of=config.as_of,
        weeks=config.weeks,
        include_current_wtd=config.include_current_wtd,
        taxonomy_path=config.taxonomy_path,
    )
    population = build_reopen_population(
        report_run.result.sessions,
        report_run.result.selection.eligible,
    )
    sample = sample_golden(
        population,
        labels,
        discovery_session_ids=discovery_session_ids,
        n=n,
    )
    return write_golden_sample(output_directory, sample)


def run_eval_labels(
    golden,
    labels: LabelSet,
    client: LabelPredictionClient,
    *,
    pii_approved: bool = False,
):
    """Evaluate with an injected client and print aggregate metrics only."""
    if pii_approved is not True:
        raise PIIApprovalRequiredError()
    report = evaluate_labels(golden, labels, client)
    print(json.dumps(evaluation_payload(report), ensure_ascii=False, sort_keys=True))
    return report


def run_dimension_verification(
    *,
    as_of: datetime,
    weeks: int,
    include_current_wtd: bool,
    client: LangfuseClient,
) -> dict[str, object]:
    window = build_cohort_window(as_of, weeks, include_current_wtd)
    raw_ticket_traces = [
        raw
        for raw in client.iter_traces(
            window.query_from_utc,
            window.query_to_utc,
        )
        if is_ticket_trace(raw)
    ]
    report = verify_raw_ticket_dimensions(
        raw_ticket_traces,
        load_taxonomy(VERIFIER_TAXONOMY_PATH),
    )
    validate_dimension_report_privacy(report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report

def _score_matches(score: Mapping[str, object], spec: ScoreSpec) -> bool:
    actual_value = (
        score.get("stringValue")
        if spec.data_type == "CATEGORICAL"
        else score.get("value")
    )
    return (
        score.get("id") == spec.id
        and score.get("name") == spec.name
        and actual_value == spec.value
        and score.get("dataType") == spec.data_type
        and score.get("sessionId") == spec.session_id
    )


def _sample_scores(scores: Sequence[ScoreSpec]) -> tuple[ScoreSpec, ...]:
    ordered = sorted(
        scores,
        key=lambda score: (
            hashlib.sha256(score.id.encode("utf-8")).hexdigest(),
            score.id,
        ),
    )
    return tuple(ordered[:READBACK_SAMPLE_LIMIT])


def _reconciliation_payload(
    *,
    requested_ids: Sequence[str],
    acknowledged_ids: Sequence[str],
    sampled_ids: Sequence[str],
    matched_ids: Sequence[str],
    success: bool,
) -> dict[str, object]:
    return {
        "success": success,
        "requested_count": len(requested_ids),
        "acknowledged_count": len(acknowledged_ids),
        "readback_sample_count": len(sampled_ids),
        "readback_matched_count": len(matched_ids),
        "sampled_score_ids": list(sampled_ids),
        "matched_score_ids": list(matched_ids),
    }


def run_sync(
    config: RunConfig,
    client: LangfuseClient,
    *,
    write: bool,
) -> ReconciliationResult:
    if not write:
        raise WriteRequiredError("sync requires explicit --write")

    analysis_run = _execute_analysis(config, client)
    events = tuple(score_to_event(score) for score in analysis_run.scores)
    requested_ids = tuple(event["id"] for event in events)
    acknowledged_ids: list[str] = []
    for batch in chunk_events(events):
        receipt: IngestionReceipt = client.ingest_events(batch)
        expected_batch_ids = tuple(event["id"] for event in batch)
        if (
            len(receipt.requested_ids) != len(expected_batch_ids)
            or set(receipt.requested_ids) != set(expected_batch_ids)
            or len(receipt.success_ids) != len(expected_batch_ids)
            or set(receipt.success_ids) != set(expected_batch_ids)
        ):
            analysis_run.artifact_run.write_json(
                "reconciliation.json",
                _reconciliation_payload(
                    requested_ids=requested_ids,
                    acknowledged_ids=acknowledged_ids,
                    sampled_ids=(),
                    matched_ids=(),
                    success=False,
                ),
            )
            analysis_run.artifact_run.publish_latest()
            raise ReconciliationError(
                "ingestion acknowledgments do not match the local manifest"
            )
        acknowledged_ids.extend(expected_batch_ids)

    if len(acknowledged_ids) != len(requested_ids) or set(
        acknowledged_ids
    ) != set(requested_ids):
        raise ReconciliationError(
            "ingestion acknowledgments do not match the local manifest"
        )

    sampled = _sample_scores(analysis_run.scores)
    matched_ids: list[str] = []
    try:
        for spec in sampled:
            score = client.wait_for_score(
                spec.id,
                lambda candidate, expected=spec: _score_matches(
                    candidate, expected
                ),
                READBACK_TIMEOUT_SECONDS,
            )
            if not _score_matches(score, spec):
                raise ReconciliationError(
                    "score readback does not match the local manifest"
                )
            matched_ids.append(spec.id)
    except Exception:
        analysis_run.artifact_run.write_json(
            "reconciliation.json",
            _reconciliation_payload(
                requested_ids=requested_ids,
                acknowledged_ids=acknowledged_ids,
                sampled_ids=tuple(spec.id for spec in sampled),
                matched_ids=matched_ids,
                success=False,
            ),
        )
        analysis_run.artifact_run.publish_latest()
        raise

    sampled_ids = tuple(spec.id for spec in sampled)
    payload = _reconciliation_payload(
        requested_ids=requested_ids,
        acknowledged_ids=acknowledged_ids,
        sampled_ids=sampled_ids,
        matched_ids=matched_ids,
        success=True,
    )
    analysis_run.artifact_run.write_json("reconciliation.json", payload)
    analysis_run.artifact_run.publish_latest()
    print(
        json.dumps(
            {
                "success": True,
                "requested_count": len(requested_ids),
                "acknowledged_count": len(acknowledged_ids),
                "readback_sample_count": len(sampled_ids),
                "readback_matched_count": len(matched_ids),
            },
            sort_keys=True,
        )
    )
    return ReconciliationResult(
        analysis=analysis_run.result,
        requested_event_ids=requested_ids,
        acknowledged_event_ids=tuple(acknowledged_ids),
        sampled_score_ids=sampled_ids,
        matched_score_ids=tuple(matched_ids),
        success=True,
        run_directory=analysis_run.artifact_run.path,
    )


def inspect_session(
    result: AnalysisResult,
    session_id: str,
) -> dict[str, object]:
    session = next(
        (item for item in result.sessions if item.session_id == session_id),
        None,
    )
    if session is None:
        raise ConfigurationError("session is not in the selected cohort")
    categories = result.transfers.get(session_id)
    return {
        "session_id": session.session_id,
        "turn0_trace_id": session.turn0_trace_id,
        "cohort_week": session.cohort_week.isoformat(),
        "cohort_status": session.cohort_status,
        "ai_first": session.ai_first,
        "outcome": session.outcome,
        "reopen_lifetime": session.reopen_lifetime,
        "reopen_within_7d": session.reopen_within_7d,
        "ai_reply_count": session.ai_reply_count,
        "first_transfer_trace_id": session.first_transfer_trace_id,
        "data_quality": session.data_quality,
        "business_category": categories.business.value if categories else None,
        "tpe_category": categories.tpe.value if categories else None,
        "guardrail_rule": categories.guardrail_rule.value if categories else None,
    }


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    as_of = args.as_of or datetime.now(timezone.utc)
    artifact_root = args.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = PROJECT_ROOT / artifact_root
    return RunConfig(
        as_of=as_of,
        weeks=args.weeks,
        include_current_wtd=args.include_current_wtd,
        artifact_root=artifact_root,
        week_definition=args.week_definition,
    )


def _freshdesk_settings():
    from .freshdesk_csat import FreshdeskCSATError, FreshdeskSettings

    file_values = dotenv_values(PROJECT_ROOT / ".env")
    selected = {
        name: os.environ.get(name, file_values.get(name) or "")
        for name in ("FRESHDESK_BASE_URL", "FRESHDESK_API_KEY")
    }
    if not selected["FRESHDESK_BASE_URL"] or not selected["FRESHDESK_API_KEY"]:
        raise FreshdeskCSATError(
            "Missing environment variables: FRESHDESK_BASE_URL, FRESHDESK_API_KEY"
        )
    return FreshdeskSettings(
        base_url=str(selected["FRESHDESK_BASE_URL"]),
        api_key=str(selected["FRESHDESK_API_KEY"]),
    )


def _freshdesk_client(auth: str, runtime_directory: Path):
    from .freshdesk_csat import (
        FreshdeskClient,
        FreshdeskCSATError,
        FreshdeskUIClient,
        load_freshdesk_cookie,
    )

    if auth == "cookie":
        cookie = load_freshdesk_cookie(runtime_directory)
        return FreshdeskUIClient(cookie)
    if auth == "rest":
        return FreshdeskClient(_freshdesk_settings())
    raise FreshdeskCSATError("Freshdesk auth mode is invalid")


def _csat_population(runtime_directory: Path, weeks: int):
    from .dashboard_cache import ProtectedSnapshotStore
    from .freshdesk_csat import FreshdeskCSATError

    runtime_directory = Path(runtime_directory)
    if not runtime_directory.is_absolute() or not 1 <= weeks <= 52:
        raise FreshdeskCSATError("CSAT population options are invalid")
    snapshot = ProtectedSnapshotStore(runtime_directory).load()
    if snapshot is None:
        raise FreshdeskCSATError("Dashboard snapshot is unavailable for CSAT fetch")
    weekly_rows = snapshot.dashboard_dict()["views"]["mon_sun"]["weekly"]
    selected_weeks = tuple(
        row["cohort_week"] for row in weekly_rows[-weeks:]
    )
    selected = frozenset(selected_weeks)
    grouped = {
        week: tuple(
            sorted(
                ticket.ticket_id
                for ticket in snapshot.tickets
                if ticket.cohort_week == week
            )
        )
        for week in selected_weeks
        if week in selected
    }
    return grouped


def _reconciliation_population(runtime_directory: Path, weeks: int):
    """Select only safe Ticket IDs with the unchanged Langfuse AI-only outcome."""

    from .dashboard_cache import ProtectedSnapshotStore
    from .outcome_reconciliation import OutcomeReconciliationError

    runtime_directory = Path(runtime_directory)
    if not runtime_directory.is_absolute() or not 1 <= weeks <= 52:
        raise OutcomeReconciliationError(
            "Outcome reconciliation population options are invalid"
        )
    snapshot = ProtectedSnapshotStore(runtime_directory).load()
    if snapshot is None:
        raise OutcomeReconciliationError(
            "Dashboard snapshot is unavailable for outcome reconciliation"
        )
    weekly_rows = snapshot.dashboard_dict()["views"]["mon_sun"]["weekly"]
    selected_weeks = tuple(row["cohort_week"] for row in weekly_rows[-weeks:])
    return {
        week: tuple(
            sorted(
                (
                    ticket.ticket_id
                    for ticket in snapshot.tickets
                    if ticket.cohort_week == week
                    and ticket.outcome == "ai_end_to_end"
                ),
                key=int,
            )
        )
        for week in selected_weeks
    }


def _entry_coverage_population(runtime_directory: Path, weeks: int):
    from .entry_coverage_cache import ENTRY_COVERAGE_START_WEEK
    from .freshdesk_entry_coverage import FreshdeskEntryCoverageError, _cohort_week
    from .dashboard_cache import ProtectedSnapshotStore

    runtime_directory = Path(runtime_directory)
    if not runtime_directory.is_absolute() or not 1 <= weeks <= 52:
        raise FreshdeskEntryCoverageError("Entry coverage population options are invalid")
    snapshot = ProtectedSnapshotStore(runtime_directory).load()
    if snapshot is None:
        raise FreshdeskEntryCoverageError(
            "Dashboard snapshot is unavailable for entry coverage"
        )
    weekly_rows = snapshot.dashboard_dict()["views"]["mon_sun"]["weekly"]
    selected_weeks = tuple(
        row["cohort_week"]
        for row in weekly_rows[-weeks:]
        if row["cohort_week"] >= ENTRY_COVERAGE_START_WEEK
    )
    selected = frozenset(selected_weeks)
    langfuse_tickets = {
        ticket.ticket_id: ticket
        for ticket in snapshot.tickets
        if ticket.cohort_week in selected
    }
    return selected_weeks, langfuse_tickets


def _run_fetch_freshdesk_entry_coverage_command(
    args: argparse.Namespace,
) -> dict[str, object]:
    from .cohort import VIETNAM_TIMEZONE
    from .dashboard_cache import ProtectedSnapshotStore
    from .entry_coverage_cache import (
        ENTRY_COVERAGE_START_WEEK,
        EntryCoverageCacheError,
        EntryCoverageCache,
        load_entry_coverage_cache,
        write_entry_coverage_cache,
    )
    from .entry_coverage_checkpoint import (
        CoverageCheckpoint,
        EntryCoverageCheckpointError,
        InventoryCheckpoint,
        inventory_fingerprint,
        load_coverage_checkpoint,
        load_inventory_checkpoint,
        write_coverage_checkpoint,
        write_inventory_checkpoint,
    )
    from .freshdesk_entry_coverage import (
        FreshdeskEntryCoverageError,
        IncrementalEntryCoverageResult,
        fetch_entry_coverage_population,
        _cohort_week,
    )
    from .freshdesk_csat import (
        FreshdeskCookieExpired,
        FreshdeskFetchDeadline,
        FreshdeskPageLimitReached,
        FreshdeskRateLimitExhausted,
        mark_cookie_expired,
        mark_cookie_verified,
    )
    from .outcome_reconciliation import load_reconciliation_agent_config
    import time as monotonic_time

    runtime_directory = Path(args.runtime_dir)
    selected_weeks, langfuse_tickets = _entry_coverage_population(
        runtime_directory, args.weeks
    )
    if not selected_weeks:
        raise FreshdeskEntryCoverageError("Entry coverage has no report weeks")
    checkpoint_path = (
        runtime_directory.parent
        / "artifacts"
        / "freshdesk_entry_coverage"
        / "coverage_checkpoint.json"
    )
    inventory_checkpoint_path = checkpoint_path.parent / "inventory_checkpoint.json"
    try:
        config = load_reconciliation_agent_config(
            FRESHDESK_RECONCILIATION_CONFIG_PATH,
            source_path=FRESHDESK_RECONCILIATION_SOURCE_PATH,
        )
        try:
            published = load_entry_coverage_cache(
                runtime_directory / "entry_coverage_cache.json"
            )
        except EntryCoverageCacheError:
            # A cache from the pre-06/07 scope is not reusable, but it must not
            # block rebuilding a fresh private cache.
            published = None
        coverage_checkpoint = load_coverage_checkpoint(checkpoint_path)
        inventory_checkpoint = load_inventory_checkpoint(inventory_checkpoint_path)
    except (EntryCoverageCacheError, EntryCoverageCheckpointError, OSError) as error:
        raise FreshdeskEntryCoverageError(
            "Freshdesk entry coverage private state is invalid"
        ) from error

    if published is not None and any(
        item.cohort_week < ENTRY_COVERAGE_START_WEEK for item in published.records
    ):
        published = None

    started = monotonic_time.monotonic()
    deadline = started + args.max_duration
    updated_since = datetime.combine(
        date.fromisoformat(ENTRY_COVERAGE_START_WEEK),
        time.min,
        tzinfo=VIETNAM_TIMEZONE,
    )
    updated_since_utc = updated_since.astimezone(timezone.utc)
    source_start_week = ENTRY_COVERAGE_START_WEEK
    inventory_tickets: tuple[object, ...] = ()
    inventory_complete = False

    def should_stop() -> bool:
        return monotonic_time.monotonic() >= deadline

    def write_inventory_page(tickets, next_page: int, complete: bool) -> None:
        nonlocal inventory_tickets, inventory_complete
        inventory_tickets = tuple(tickets)
        inventory_complete = complete
        try:
            write_inventory_checkpoint(
                inventory_checkpoint_path,
                InventoryCheckpoint(
                    source_start_week=source_start_week,
                    updated_since=_utc_iso(updated_since_utc),
                    page_size=50,
                    next_page=next_page,
                    complete=complete,
                    tickets=inventory_tickets,
                    fingerprint=inventory_fingerprint(inventory_tickets),
                ),
            )
        except EntryCoverageCheckpointError as error:
            raise FreshdeskEntryCoverageError(
                "Freshdesk inventory checkpoint could not be written"
            ) from error

    if inventory_checkpoint is not None and (
        inventory_checkpoint.source_start_week == source_start_week
        and inventory_checkpoint.updated_since == _utc_iso(updated_since_utc)
        and inventory_checkpoint.complete
    ):
        inventory_tickets = inventory_checkpoint.tickets
        inventory_complete = True
    else:
        existing_inventory = (
            inventory_checkpoint.tickets
            if inventory_checkpoint is not None
            and inventory_checkpoint.source_start_week == source_start_week
            and inventory_checkpoint.updated_since == _utc_iso(updated_since_utc)
            and not inventory_checkpoint.complete
            else ()
        )
        start_page = (
            inventory_checkpoint.next_page
            if existing_inventory and inventory_checkpoint is not None
            else 1
        )
        try:
            with _freshdesk_client(args.auth, runtime_directory) as client:
                client.list_ticket_metadata(
                    updated_since=updated_since,
                    start_page=start_page,
                    existing=existing_inventory,
                    on_page=write_inventory_page,
                    should_stop=should_stop,
                )
        except FreshdeskCookieExpired:
            if args.auth == "cookie":
                mark_cookie_expired(runtime_directory)
            raise
        except (
            FreshdeskFetchDeadline,
            FreshdeskRateLimitExhausted,
            FreshdeskPageLimitReached,
        ):
            pass
        else:
            if args.auth == "cookie":
                mark_cookie_verified(runtime_directory)
        if not inventory_complete:
            selected_records = tuple(
                item
                for item in (published.records if published is not None else ())
                if item.cohort_week in selected_weeks
            )
            return _entry_coverage_command_result(
                "duration_limit_reached",
                selected_weeks,
                selected_records,
            )

    if should_stop():
        selected_records = tuple(
            item
            for item in (published.records if published is not None else ())
            if item.cohort_week in selected_weeks
        )
        return _entry_coverage_command_result(
            "duration_limit_reached",
            selected_weeks,
            selected_records,
        )

    from .freshdesk_entry_coverage import FreshdeskTicketMetadata

    filtered_inventory = tuple(
        item
        for item in inventory_tickets
        if isinstance(item, FreshdeskTicketMetadata)
        and item.created_at >= _utc_iso(updated_since_utc)
        and _cohort_week(item.created_at) in selected_weeks
    )
    fingerprint = inventory_fingerprint(tuple(inventory_tickets))
    resume_is_usable = coverage_checkpoint is not None and (
        coverage_checkpoint.source_start_week == source_start_week
        and coverage_checkpoint.inventory_fingerprint == fingerprint
        and coverage_checkpoint.target_weeks == tuple(selected_weeks)
    )
    resume_records = coverage_checkpoint.records if resume_is_usable else ()
    resume_week = coverage_checkpoint.active_week if resume_is_usable else None
    resume_index = coverage_checkpoint.next_ticket_index if resume_is_usable else 0
    completed_from_checkpoint = (
        coverage_checkpoint.completed_weeks if resume_is_usable else ()
    )
    checkpoint_as_of = _utc_iso(datetime.now(timezone.utc))
    checkpoint_fetched_weeks = {
        week: checkpoint_as_of for week in completed_from_checkpoint
    }
    checkpoint_records = tuple(resume_records)
    existing_candidates = tuple(
        cache
        for cache in (
            published,
            EntryCoverageCache(
                fetched_weeks=checkpoint_fetched_weeks,
                records=checkpoint_records,
            ),
        )
        if cache is not None
    )
    existing = max(
        existing_candidates,
        key=lambda cache: (cache.fetched_at or "", len(cache.fetched_weeks), len(cache.records)),
        default=None,
    )
    progress_state = {
        "week": resume_week or (selected_weeks[0] if selected_weeks else None),
        "index": resume_index,
    }
    last_checkpoint_write = monotonic_time.monotonic()

    def write_coverage_state(cache, week: str | None, index: int, *, force: bool = False) -> None:
        nonlocal last_checkpoint_write
        now = monotonic_time.monotonic()
        if not force and index % 25 != 0 and now - last_checkpoint_write < 30:
            return
        completed = tuple(sorted(set(cache.fetched_weeks).intersection(selected_weeks)))
        active = None if week in completed else week
        progress_state["week"] = active
        progress_state["index"] = 0 if active is None else index
        try:
            write_coverage_checkpoint(
                checkpoint_path,
                CoverageCheckpoint(
                    source_start_week=source_start_week,
                    inventory_fingerprint=fingerprint,
                    target_weeks=tuple(selected_weeks),
                    active_week=progress_state["week"],
                    next_ticket_index=progress_state["index"],
                    completed_weeks=completed,
                    records=cache.records,
                ),
            )
        except EntryCoverageCheckpointError as error:
            raise FreshdeskEntryCoverageError(
                "Freshdesk coverage checkpoint could not be written"
            ) from error
        last_checkpoint_write = now

    try:
        with _freshdesk_client(args.auth, runtime_directory) as client:
            result = fetch_entry_coverage_population(
                client,
                filtered_inventory,
                langfuse_tickets,
                selected_weeks,
                config,
                existing=existing,
                as_of=datetime.now(VIETNAM_TIMEZONE),
                max_workers=args.max_workers,
                max_duration_seconds=max(0.1, deadline - monotonic_time.monotonic()),
                on_week_complete=lambda cache: write_coverage_state(
                    cache,
                    None,
                    0,
                    force=True,
                ),
                resume_records=resume_records,
                resume_week=resume_week,
                resume_index=resume_index,
                on_progress=lambda cache, week, index: write_coverage_state(
                    cache,
                    week,
                    index,
                ),
            )
        if args.auth == "cookie":
            mark_cookie_verified(runtime_directory)
    except FreshdeskCookieExpired:
        if args.auth == "cookie":
            mark_cookie_expired(runtime_directory)
        raise
    except (FreshdeskFetchDeadline, FreshdeskRateLimitExhausted):
        try:
            checkpoint_after_interrupt = load_coverage_checkpoint(checkpoint_path)
        except EntryCoverageCheckpointError as error:
            raise FreshdeskEntryCoverageError(
                "Freshdesk coverage checkpoint is invalid"
            ) from error
        if checkpoint_after_interrupt is None:
            fallback_cache = existing or EntryCoverageCache(
                fetched_weeks={}, records=()
            )
            completed_after_interrupt: tuple[str, ...] = ()
        else:
            fallback_cache = EntryCoverageCache(
                fetched_weeks={
                    week: checkpoint_as_of
                    for week in checkpoint_after_interrupt.completed_weeks
                },
                records=checkpoint_after_interrupt.records,
            )
            completed_after_interrupt = checkpoint_after_interrupt.completed_weeks
        result = IncrementalEntryCoverageResult(
            cache=fallback_cache,
            completed_weeks=completed_after_interrupt,
            complete=False,
        )
    if not result.complete:
        write_coverage_state(
            result.cache,
            progress_state["week"],
            int(progress_state["index"]),
            force=True,
        )
    if result.complete:
        try:
            write_entry_coverage_cache(
                runtime_directory / "entry_coverage_cache.json",
                result.cache,
            )
            inventory_checkpoint_path.unlink(missing_ok=True)
            checkpoint_path.unlink(missing_ok=True)
        except (EntryCoverageCacheError, OSError) as error:
            raise FreshdeskEntryCoverageError(
                "Freshdesk entry coverage cache could not be published"
            ) from error

    selected_records = tuple(
        item for item in result.cache.records if item.cohort_week in selected_weeks
    )
    return _entry_coverage_command_result(
        "complete" if result.complete else "duration_limit_reached",
        selected_weeks,
        selected_records,
        fetched_weeks=result.cache.fetched_weeks,
    )


def _entry_coverage_command_result(
    status: str,
    selected_weeks: Sequence[str],
    selected_records: Sequence[object],
    *,
    fetched_weeks: Mapping[str, str] | None = None,
) -> dict[str, object]:
    counts = Counter(getattr(item, "status", "") for item in selected_records)
    return {
        "status": status,
        "weeks_fetched": sum(
            week in (fetched_weeks or {}) for week in selected_weeks
        ),
        "freshdesk_ticket_count": len(selected_records),
        "ai_replied_only_count": counts["ai_replied_only"],
        "ai_replied_then_transferred_count": counts["ai_replied_then_transferred"],
        "transferred_without_ai_reply_count": counts["transferred_without_ai_reply"],
        "invoked_no_result_count": counts["invoked_no_result"],
        "not_observed_invoked_count": counts["not_observed_invoked"],
        "not_observed_human_replied_count": sum(
            getattr(item, "status", None) == "not_observed_invoked"
            and getattr(item, "human_replied", None) is True
            for item in selected_records
        ),
        "not_observed_no_human_reply_count": sum(
            getattr(item, "status", None) == "not_observed_invoked"
            and getattr(item, "human_replied", None) is False
            for item in selected_records
        ),
        "unresolved_count": counts["unresolved"],
    }


def _run_fetch_csat_command(args: argparse.Namespace) -> dict[str, object]:
    from .cohort import VIETNAM_TIMEZONE
    from .csat_cache import CSATCacheError, load_csat_cache, write_csat_cache
    from .freshdesk_csat import (
        FreshdeskCSATError,
        FreshdeskCookieExpired,
        fetch_csat_population,
        load_agent_config,
        mark_cookie_expired,
        mark_cookie_verified,
    )

    runtime_directory = Path(args.runtime_dir)
    checkpoint_path = (
        runtime_directory.parent
        / "artifacts"
        / "freshdesk_csat"
        / "checkpoint.json"
    )
    population = _csat_population(runtime_directory, args.weeks)
    try:
        config = load_agent_config(FRESHDESK_AGENT_CONFIG_PATH)
        published = load_csat_cache(runtime_directory / "csat_cache.json")
        checkpoint = load_csat_cache(checkpoint_path)
    except (CSATCacheError, OSError) as error:
        raise FreshdeskCSATError("Freshdesk CSAT private state is invalid") from error
    candidates = tuple(
        cache for cache in (published, checkpoint) if cache is not None
    )
    existing = max(
        candidates,
        key=lambda cache: (
            cache.fetched_at or "",
            len(cache.fetched_weeks),
            len(cache.responses),
        ),
        default=None,
    )

    def write_checkpoint(cache) -> None:
        try:
            write_csat_cache(checkpoint_path, cache)
        except CSATCacheError as error:
            raise FreshdeskCSATError(
                "Freshdesk CSAT checkpoint could not be written"
            ) from error

    as_of = datetime.now(VIETNAM_TIMEZONE)
    try:
        with _freshdesk_client(args.auth, runtime_directory) as client:
            result = fetch_csat_population(
                client,
                population,
                config,
                existing=existing,
                as_of=as_of,
                since_week=args.since_week,
                max_workers=args.max_workers,
                max_duration_seconds=args.max_duration,
                on_week_complete=write_checkpoint,
            )
    except FreshdeskCookieExpired:
        if args.auth == "cookie":
            mark_cookie_expired(runtime_directory)
        raise
    if args.auth == "cookie":
        mark_cookie_verified(runtime_directory)
    if result.complete:
        try:
            write_csat_cache(runtime_directory / "csat_cache.json", result.cache)
        except CSATCacheError as error:
            raise FreshdeskCSATError("Freshdesk CSAT cache could not be published") from error
        try:
            checkpoint_path.unlink(missing_ok=True)
        except OSError as error:
            raise FreshdeskCSATError(
                "Freshdesk CSAT checkpoint could not be cleared"
            ) from error
    stats = result.cache.fetch_stats
    return {
        "status": "complete" if result.complete else "duration_limit_reached",
        "weeks_fetched": len(result.completed_weeks),
        "included_bot_response_count": stats.included_bot_response_count,
        "excluded_other_agent_response_count": (
            stats.excluded_other_agent_response_count
        ),
        "excluded_null_agent_response_count": stats.excluded_null_agent_response_count,
    }


def _run_discover_agents_command(args: argparse.Namespace) -> dict[str, object]:
    from .cohort import VIETNAM_TIMEZONE
    from .freshdesk_csat import (
        FreshdeskAgentConfig,
        FreshdeskCSATError,
        FreshdeskClient,
        fetch_csat_population,
        resolve_exact_agent_id,
        write_approved_agent_config,
    )

    population = _csat_population(Path(args.runtime_dir), args.weeks)
    settings = _freshdesk_settings()
    with FreshdeskClient(settings) as client:
        bot_agent_id = resolve_exact_agent_id(
            client.get_ticket_fields(),
            "Admin CS ZaloPay",
        )
        survey_scales = {
            "43000076179": {
                "positive": (103,),
                "neutral": (100,),
                "negative": (-103,),
            }
        }
        candidate = FreshdeskAgentConfig(
            bot_agent_ids=frozenset({bot_agent_id}),
            survey_scales=survey_scales,
        )
        result = fetch_csat_population(
            client,
            population,
            candidate,
            existing=None,
            as_of=datetime.now(VIETNAM_TIMEZONE),
            max_workers=args.max_workers,
            max_duration_seconds=args.max_duration,
        )
    if not result.complete:
        raise FreshdeskCSATError("Freshdesk agent discovery reached its duration limit")
    write_approved_agent_config(
        FRESHDESK_AGENT_CONFIG_PATH,
        bot_agent_id=bot_agent_id,
        approved_at=date.today(),
        survey_scales=survey_scales,
    )
    stats = result.cache.fetch_stats
    return {
        "status": "approved_config_written",
        "exact_name_match_count": 1,
        "ticket_count": sum(len(items) for items in population.values()),
        "all_response_count": stats.all_response_count,
        "known_bot_response_count": stats.included_bot_response_count,
        "other_agent_response_count": stats.excluded_other_agent_response_count,
        "null_agent_response_count": stats.excluded_null_agent_response_count,
    }


def _run_reconcile_freshdesk_outcomes_command(
    args: argparse.Namespace,
) -> dict[str, object]:
    from .cohort import VIETNAM_TIMEZONE
    from .freshdesk_csat import (
        FreshdeskCookieExpired,
        mark_cookie_expired,
        mark_cookie_verified,
    )
    from .outcome_reconciliation import (
        OutcomeReconciliationError,
        fetch_reconciliation_population,
        load_reconciliation_agent_config,
    )
    from .reconciliation_cache import (
        ReconciliationCacheError,
        load_reconciliation_cache,
        write_reconciliation_cache,
    )

    runtime_directory = Path(args.runtime_dir)
    checkpoint_path = (
        runtime_directory.parent
        / "artifacts"
        / "freshdesk_reconciliation"
        / "checkpoint.json"
    )
    population = _reconciliation_population(runtime_directory, args.weeks)
    try:
        config = load_reconciliation_agent_config(
            FRESHDESK_RECONCILIATION_CONFIG_PATH,
            source_path=FRESHDESK_RECONCILIATION_SOURCE_PATH,
        )
        published = load_reconciliation_cache(
            runtime_directory / "outcome_reconciliation_cache.json"
        )
        checkpoint = load_reconciliation_cache(checkpoint_path)
    except (ReconciliationCacheError, OSError) as error:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation private state is invalid"
        ) from error
    candidates = tuple(
        cache for cache in (published, checkpoint) if cache is not None
    )
    existing = max(
        candidates,
        key=lambda cache: (
            cache.fetched_at or "",
            len(cache.fetched_weeks),
            len(cache.records),
        ),
        default=None,
    )

    def write_checkpoint(cache) -> None:
        try:
            write_reconciliation_cache(checkpoint_path, cache)
        except ReconciliationCacheError as error:
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation checkpoint could not be written"
            ) from error

    try:
        with _freshdesk_client(args.auth, runtime_directory) as client:
            result = fetch_reconciliation_population(
                client,
                population,
                config,
                existing=existing,
                as_of=datetime.now(VIETNAM_TIMEZONE),
                max_workers=args.max_workers,
                max_duration_seconds=args.max_duration,
                on_week_complete=write_checkpoint,
            )
    except FreshdeskCookieExpired:
        if args.auth == "cookie":
            mark_cookie_expired(runtime_directory)
        raise
    if args.auth == "cookie":
        mark_cookie_verified(runtime_directory)
    if result.complete:
        try:
            write_reconciliation_cache(
                runtime_directory / "outcome_reconciliation_cache.json",
                result.cache,
            )
        except ReconciliationCacheError as error:
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation cache could not be published"
            ) from error
        try:
            checkpoint_path.unlink(missing_ok=True)
        except OSError as error:
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation checkpoint could not be cleared"
            ) from error
    records = result.cache.records
    checked = sum(item.human_replied_after_ai is not None for item in records)
    human_replied = sum(item.human_replied_after_ai is True for item in records)
    unresolved = sum(item.human_replied_after_ai is None for item in records)
    return {
        "status": "complete" if result.complete else "duration_limit_reached",
        "weeks_fetched": len(result.completed_weeks),
        "checked_ticket_count": checked,
        "human_replied_after_ai": human_replied,
        "unresolved_ticket_count": unresolved,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command in {
            "discover-agents",
            "fetch-csat",
            "reconcile-freshdesk-outcomes",
            "fetch-freshdesk-entry-coverage",
        }:
            from .freshdesk_csat import FreshdeskCSATError
            from .freshdesk_entry_coverage import FreshdeskEntryCoverageError
            from .outcome_reconciliation import OutcomeReconciliationError

            try:
                if args.command == "discover-agents":
                    result = _run_discover_agents_command(args)
                elif args.command == "fetch-csat":
                    result = _run_fetch_csat_command(args)
                elif args.command == "reconcile-freshdesk-outcomes":
                    result = _run_reconcile_freshdesk_outcomes_command(args)
                else:
                    result = _run_fetch_freshdesk_entry_coverage_command(args)
            except (
                FreshdeskCSATError,
                FreshdeskEntryCoverageError,
                OutcomeReconciliationError,
            ) as error:
                print(str(error), file=sys.stderr)
                return 2
            print(json.dumps(result, sort_keys=True))
            return 0
        eval_label_set = (
            load_label_set(args.labels)
            if args.command == "eval-labels"
            else None
        )
        eval_golden = (
            load_golden_evaluation(args.golden, eval_label_set)
            if args.command == "eval-labels" and eval_label_set is not None
            else None
        )
        if args.command == "eval-labels":
            assert eval_golden is not None
            # No approved route exists yet to construct the prediction client.
            raise PIIApprovalRequiredError()
        golden_labels = (
            load_label_set(REOPEN_LABELS_PATH)
            if args.command == "sample-golden"
            else None
        )
        discovery_session_ids = (
            load_discovery_session_ids(REOPEN_DISCOVERY_PATH)
            if args.command == "sample-golden"
            else None
        )
        settings = load_environment()
        with _build_client(settings) as client:
            if args.command == "sample-reopen":
                run_sample_reopen_pii_review(
                    _config_from_args(args),
                    client,
                    args.out,
                )
                # There is deliberately no approval flag/file to continue
                # beyond this manual gate.
                raise PIIApprovalRequiredError()
            elif args.command == "sample-golden":
                assert golden_labels is not None
                assert discovery_session_ids is not None
                run_sample_golden(
                    _config_from_args(args),
                    client,
                    args.out,
                    n=args.n,
                    labels=golden_labels,
                    discovery_session_ids=discovery_session_ids,
                )
            elif args.command == "verify-dimensions":
                report = run_dimension_verification(
                    as_of=args.as_of or datetime.now(timezone.utc),
                    weeks=args.weeks,
                    include_current_wtd=args.include_current_wtd,
                    client=client,
                )
                if args.require_p0 and report.get("p0_pass") is not True:
                    return 1
            else:
                config = _config_from_args(args)
                if args.command == "inspect-session":
                    result = run_dry_run(config, client)
                    print(
                        json.dumps(
                            inspect_session(result, args.session_id),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                else:
                    run_dry_run(config, client)
        return 0
    except (
        ConfigurationError,
        GoldenEvaluationError,
        GoldenSampleError,
        LabelConfigError,
        LangfuseAPIError,
        PIIApprovalRequiredError,
        PIIReviewError,
        ReconciliationError,
        WriteRequiredError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
