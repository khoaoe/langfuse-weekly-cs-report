from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class CohortWindow:
    """The time bounds one analysis run is allowed to look at.

    Carries both the local Vietnam-time reporting boundaries (which weeks are
    complete, where week-to-date begins) and the UTC bounds actually sent to
    Langfuse. Every field is timezone-aware; naive input is rejected outright,
    because a silently-naive boundary shifts a whole cohort by seven hours.
    """
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
    """One normalized Langfuse trace: a single turn of one conversation.

    A ticket has many traces, ordered by ``turn``. This is the raw grain --
    ``SessionMetrics`` is what one ticket becomes after all of its traces are
    folded together.
    """
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
    """One trace or ticket rejected from analysis, with the reason why.

    Kept rather than dropped so a run can report what it excluded: an
    unexplained fall in ticket count is indistinguishable from a real fall.
    """
    reason: str
    session_id: str | None
    trace_id: str | None
    timestamp: datetime | None

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")


@dataclass(frozen=True)
class CategoryResult:
    """A single resolved taxonomy value, with the raw input it came from.

    ``raw_values`` and ``source_fields`` retain the pre-mapping evidence so a
    reader can tell "no value present" from "value present but unmapped".
    """
    value: str
    raw_values: tuple[str, ...] = ()
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransferCategories:
    """The three taxonomy axes resolved for one transfer to CS."""
    business: CategoryResult
    tpe: CategoryResult
    guardrail_rule: CategoryResult


@dataclass(frozen=True)
class TicketDimensions:
    """Every taxonomy axis resolved for one ticket.

    Populated from ``input.other_info.meta`` plus TPE observations, via
    ``taxonomy.v2.json``. No LLM is involved -- these are field lookups.

    Absent values are the string ``"Không xác định"`` for the required axes and
    ``None`` for the optional ones; the difference is deliberate and load-bearing
    for the P0 coverage gate, which counts field presence.
    """
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
    # Exact-source TPE observations. The legacy meta fields above are retained
    # only when they were already present in the raw Langfuse trace.
    tpe_signals: tuple[tuple[str, str | None], ...] = ()
    # `skill` collapses to None whenever more than one distinct skill ran, so a
    # triple-skill ticket and a ticket with zero `execute` observations were
    # indistinguishable downstream. These two carry the count and the sorted
    # combination through instead of discarding them.
    skill_count: int = 0
    skill_set: tuple[str, ...] = ()
    # Allowlisted `<tool>:<code>` pairs for every tool call in the session that
    # returned an `error` envelope. Sorted, de-duplicated; empty means no tool
    # reported a failure.
    #
    # Deliberately not collapsed into a cause label: the code does not
    # determine the cause. A separate investigation of the 230 `NOT_FOUND`
    # results from `get_zalopay_id_by_phone` (2026-09-02, written up in
    # `docs/cs-agent-skills/bank-unlink/references/context-noi-bo.md`) split
    # them across a handler bug that strips a leading `0` via `int(digits)`
    # with the arguments correct, phone numbers the LLM fabricated, and a
    # real-miss remainder -- three different owners behind one code. The
    # figures are that investigation's, not measured here; the design
    # conclusion is what this comment carries. A cause label also erases the
    # tool identity, which is the half that surfaces a failure rate like
    # `get_zalopay_id_by_phone`'s 217/233 = 93.1% (Langfuse, seven days to
    # 2026-09-02).
    #
    # Not reduced with `_only_value` either. Over the 13-week snapshot as of
    # 2026-09-02 (16,413 tickets, 3,076 with an error) the distinct-pair count
    # per ticket ran 1: 80.9%, 2: 17.2%, 3: 1.7%, 4: 0.2% -- so **19.1% of
    # error tickets carry more than one pair** and collapsing on conflict
    # would discard every one of them. Same reasoning as
    # `skill_set`/`skill_count` above.
    tool_error_codes: tuple[str, ...] = ()
    # The A/B arm this ticket ran on (`input.model_info.model_core`). Older
    # tickets predate the field and are null, not a data-quality problem.
    model_core: str | None = None


@dataclass(frozen=True)
class TransferTrigger:
    """Privacy-safe trigger observed on the first canonical transfer trace."""

    reason: str
    rule: str
    source: str
    stage: str | None = None
    skill: str | None = None


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
        tpe_signals=(),
        skill_count=0,
        skill_set=(),
        model_core=None,
    )


@dataclass(frozen=True)
class SessionMetrics:
    """One ticket, after all of its traces are folded into a single row.

    Naming, to be read carefully: this type is keyed by ``session_id``, but a
    session *is* a ticket here -- the two words name the same thing throughout
    this codebase, and ``dimensions`` on this very class is a
    ``TicketDimensions``. ``dashboard_schema._ticket_row`` completes the
    rename by assigning ``ticket_id=session.session_id``. The ``session_``
    prefix is Langfuse's wire vocabulary, not a second concept.

    Several fields are marked internal-only and must never reach the browser;
    each carries its own comment saying so.
    """
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
    # Internal trace-grain trigger. Its allowlisted reason is projected per
    # ticket; rule/source/stage/skill remain aggregate-only.
    transfer_trigger: TransferTrigger | None = None
    # Internal-only direct-CS comparison cohort.  It must not enter the
    # published AI-first reopen metrics.
    control_reopen_within_7d: int | None = None
    # Hours from the first classifiable handling trace to each counted reopen,
    # in the same order and with the same burst grouping as `reopen_lifetime`
    # (so `len(...) == reopen_lifetime` whenever that is not None). Kept so a
    # consumer can re-cut the reopen window to a shorter maturity horizon --
    # `summarize_same_period` needs that to compare a week-to-date cohort
    # against older weeks without crediting the older weeks' extra weeks of
    # elapsed time. Empty when the ticket is not AI-first.
    reopen_offsets_hours: tuple[float, ...] = ()

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
    """One score to write back to Langfuse, as its ingestion API expects it."""
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
    """A published invariant did not hold, so the run must not publish.

    Raised rather than logged: a broken invariant means the numbers are
    wrong, and wrong numbers are worse than absent ones.
    """


@dataclass(frozen=True)
class CandidateSelection:
    """The outcome of choosing which tickets an analysis run may score.

    ``eligible`` is what gets analysed; every other field records what was set
    aside and why. The P0 denominator is built from the whole picture, not from
    ``eligible`` alone -- excluded units stay in the denominator.
    """
    eligible: dict[str, tuple[TraceRecord, ...]]
    weekend_start: tuple[str, ...]
    left_censored: tuple[str, ...]
    invalid_keyed: tuple[QualityIssue, ...]
    unkeyed: tuple[QualityIssue, ...]
    window: CohortWindow
    pre_window_start: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateStatus:
    """Which metric families this run is allowed to publish.

    A gate closes when its input data is too incomplete to report honestly;
    ``reasons`` carries the human-readable explanation for each closure.
    """
    core_allowed: bool
    business_allowed: bool
    tpe_allowed: bool
    guardrail_allowed: bool
    reasons: tuple[str, ...]
    structural_invalid_rate: float = 0.0


@dataclass(frozen=True)
class WeeklySummary:
    """One cohort week's published figures.

    ``cohort_status`` distinguishes a complete week from a week-to-date one,
    which is what stops a partial week from being compared against full weeks
    as though they were alike.
    """
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
    ai_reply_sum_ai_first: int = 0
    ai_reply_mean_ai_first: float | None = None
    gt4_turn_with_cs: int = 0
    gt4_turn_without_cs: int = 0
    max_replies_rule_fired: int = 0
    resolved_first_reply: int = 0

    def __post_init__(self) -> None:
        if self.as_of is not None:
            _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class AnalysisResult:
    """Everything one pipeline run produced, before projection to a payload.

    ``sessions`` is the per-ticket grain (see ``SessionMetrics`` on the
    session/ticket naming); ``weekly_mon_sun`` and ``weekly_mon_fri`` are the
    same tickets summarized under the two supported week definitions.
    """
    sessions: tuple[SessionMetrics, ...]
    transfers: dict[str, TransferCategories]
    selection: CandidateSelection
    weekly: tuple[WeeklySummary, ...]
    gate_status: GateStatus
    weekly_mon_sun: tuple[WeeklySummary, ...] = ()
    weekly_mon_fri: tuple[WeeklySummary, ...] = ()
