from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class CohortWindow:
    as_of: datetime
    complete_start_local: datetime
    complete_end_exclusive_local: datetime
    wtd_start_local: datetime | None
    query_from_utc: datetime
    query_to_utc: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_aware(self.complete_start_local, "complete_start_local")
        _require_aware(self.complete_end_exclusive_local, "complete_end_exclusive_local")
        if self.wtd_start_local is not None:
            _require_aware(self.wtd_start_local, "wtd_start_local")
        _require_aware(self.query_from_utc, "query_from_utc")
        _require_aware(self.query_to_utc, "query_to_utc")


@dataclass(frozen=True)
class TraceRecord:
    id: str
    session_id: str
    timestamp: datetime
    turn: int
    input_data: object
    output_data: object
    environment: str

    def __post_init__(self) -> None:
        _require_aware(self.timestamp, "timestamp")


@dataclass(frozen=True)
class QualityIssue:
    reason: str
    session_id: str | None
    trace_id: str | None
    timestamp: datetime | None

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")


@dataclass(frozen=True)
class CategoryResult:
    value: str
    raw_values: tuple[str, ...] = ()
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransferCategories:
    business: CategoryResult
    tpe: CategoryResult
    guardrail_rule: CategoryResult


@dataclass(frozen=True)
class TicketDimensions:
    issue_category: str
    app: str
    app_code: int | None
    product_code: str
    entry_point: str
    payment_channel: str
    tpe_code: str | None
    tpe_status_raw: str | None
    tpe_status_canonical: str | None
    tpe_step: str | None
    tpe_case: int | None
    skill: str | None
    intent: str | None
    guardrail_rule: str | None
    escalation_guard_blocked: bool


def _empty_ticket_dimensions() -> TicketDimensions:
    """Safe dimensions for deprecated callers which have not injected v2 yet."""
    return TicketDimensions(
        issue_category="Không xác định",
        app="Không xác định",
        app_code=None,
        product_code="Không xác định",
        entry_point="Không xác định",
        payment_channel="Không xác định",
        tpe_code=None,
        tpe_status_raw=None,
        tpe_status_canonical=None,
        tpe_step=None,
        tpe_case=None,
        skill=None,
        intent=None,
        guardrail_rule=None,
        escalation_guard_blocked=False,
    )


@dataclass(frozen=True)
class SessionMetrics:
    session_id: str
    turn0_trace_id: str
    turn0_timestamp: datetime
    cohort_week: date
    score_timestamp: datetime
    cohort_status: str
    ai_first: bool
    no_ai_first_reason: str | None
    outcome: str | None
    reopen_lifetime: int | None
    reopen_within_7d: int | None
    ai_reply_count: int
    first_transfer_trace_id: str | None
    data_quality: str
    environment: str
    as_of: datetime | None = None
    is_weekend_start: bool = False
    turn_count: int = 0
    transferred: bool = False
    dimensions: TicketDimensions = field(default_factory=_empty_ticket_dimensions)
    # Internal-only allowlisted guardrail values. Never project this to tickets.
    guardrail_rules: tuple[str, ...] = ()
    # Internal-only direct-CS comparison cohort.  It must not enter the
    # published AI-first reopen metrics.
    control_reopen_within_7d: int | None = None

    def __post_init__(self) -> None:
        _require_aware(self.turn0_timestamp, "turn0_timestamp")
        _require_aware(self.score_timestamp, "score_timestamp")
        if self.as_of is not None:
            _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class ReopenLabel:
    """Server-side assisted classification; never project its quote to UI."""

    session_id: str
    labels_version: str
    prompt_version: str
    label: str | None
    status: str
    quote: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.status not in {"labeled", "abstained", "invalid", "failed"}:
            raise ValueError("reopen label status is invalid")
        if self.status in {"labeled", "abstained"} and not self.label:
            raise ValueError("reopen label is missing")
        if self.status in {"invalid", "failed"} and self.label is not None:
            raise ValueError("invalid reopen label must not contain a label")
        if self.status == "labeled" and self.label == "other":
            raise ValueError("other reopen label must be abstained")
        if self.status == "abstained" and (
            self.label != "other" or not self.quote
        ):
            raise ValueError("other reopen label requires a quote")
        if self.quote is not None and not (
            self.status == "abstained" and self.label == "other"
        ):
            raise ValueError("reopen quote is only permitted for other")


@dataclass(frozen=True)
class ScoreSpec:
    id: str
    event_id: str
    name: str
    value: str | int | float
    data_type: str
    session_id: str
    timestamp: datetime
    environment: str
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        _require_aware(self.timestamp, "timestamp")


class InvariantError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateSelection:
    eligible: dict[str, tuple[TraceRecord, ...]]
    weekend_start: tuple[str, ...]
    left_censored: tuple[str, ...]
    invalid_keyed: tuple[QualityIssue, ...]
    unkeyed: tuple[QualityIssue, ...]
    window: CohortWindow
    pre_window_start: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateStatus:
    core_allowed: bool
    business_allowed: bool
    tpe_allowed: bool
    guardrail_allowed: bool
    reasons: tuple[str, ...]
    structural_invalid_rate: float = 0.0


@dataclass(frozen=True)
class WeeklySummary:
    cohort_week: date
    cohort_status: str
    total_tickets: int
    ai_first_count: int
    ai_first_rate: float
    ai_end_to_end_count: int
    ai_then_cs_count: int
    direct_cs_count: int
    unclassified_count: int
    reopen_7d_rate: float | None
    reopen_7d_denominator: int | None
    reopen_lifetime_rate: float | None
    ai_reply_p50: int | None
    ai_reply_p90: int | None
    ai_reply_max: int | None
    as_of: datetime | None = None
    # v3 weekly-report fields.  Defaults retain the deprecated score/artifact
    # callers while the dashboard pipeline always supplies explicit values.
    week_definition: str = "mon_sun"
    has_data: bool = False
    reopen_lifetime_numerator: int = 0
    reopen_lifetime_denominator: int = 0
    ai_reply_mean_ai_first: float | None = None
    gt4_turn_with_cs: int = 0
    gt4_turn_without_cs: int = 0
    max_replies_rule_fired: int = 0

    def __post_init__(self) -> None:
        if self.as_of is not None:
            _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class AnalysisResult:
    sessions: tuple[SessionMetrics, ...]
    transfers: dict[str, TransferCategories]
    selection: CandidateSelection
    weekly: tuple[WeeklySummary, ...]
    gate_status: GateStatus
    weekly_mon_sun: tuple[WeeklySummary, ...] = ()
    weekly_mon_fri: tuple[WeeklySummary, ...] = ()
