from __future__ import annotations

"""``TicketRow`` and the privacy guards that validate it.

Split out of ``dashboard_schema`` because that module imports the Freshdesk
and AI-review layers, while those layers need ``TicketRow`` -- an import cycle
that used to be worked around with a ``TYPE_CHECKING`` block and a deferred
import inside a function body. Nothing here imports another module of this
package, so the cycle cannot come back.

``dashboard_schema`` re-exports every name below, so existing callers keep
importing them from there.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from unicodedata import category, decimal, normalize


_MAX_TICKET_PAGE_SIZE = 100


_TICKET_ID_PATTERN = re.compile(r"[1-9][0-9]{0,19}\Z")


_PHONE = re.compile(r"(?:^|\D)(?:0|84|\+84)[0-9]{8,10}(?:$|\D)")


_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)


_INTENT_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


_TPE_CODE_PATTERN = re.compile(r"-?[0-9]{1,6}\Z")


_TOOL_ERROR_CODE_PATTERN = re.compile(
    r"[a-z][a-z0-9_]{0,63}:(?:[A-Z_]{1,40}|khac)"
)


_GUARDRAIL_RULES = frozenset(
    {
        "cs_escalation",
        "empty_input",
        "empty_message_marker",
        "max_replies_exceeded",
        "missing_transaction_id",
        "off_topic_llm",
        "prompt_injection",
        "prompt_injection_llm",
        "off_topic",
        "system_prompt_leak",
        "tone_check_error",
    }
)


_TRANSFER_TRIGGER_REASONS = frozenset(
    {
        "skill_suggested_transfer",
        "ai_response_requires_transfer",
        "missing_transaction_id",
        "max_replies_exceeded",
        "out_of_scope",
        "empty_message",
        "prompt_injection",
        "output_check_error",
        "other_guardrail",
        "unknown",
    }
)


_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


_UTC_ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)


_VIETNAMESE_FAMILY_NAMES = frozenset({
    "nguyễn", "nguyen", "trần", "tran", "lê", "le", "phạm", "pham", "hoàng", "hoang", "huỳnh", "huynh", "vũ", "vu", "võ", "vo", "đặng", "dang", "bùi", "bui", "đỗ", "do", "hồ", "ho", "ngô", "ngo", "dương", "duong", "lý", "ly",
})


_VIETNAMESE_NAME_MIDDLES = frozenset({"văn", "van", "thị", "thi"})


_OUTCOMES = ("ai_end_to_end", "ai_then_cs", "direct_cs", "unclassified")


_CSAT_BUCKETS = ("positive", "neutral", "negative")


_CSAT_TICKET_STATES = frozenset({*_CSAT_BUCKETS, "unrated"})


_QUALITY_LABELS = frozenset(
    {
        "valid", "empty_or_technical", "malformed_output", "invalid_timestamp",
        "missing_trace_id", "missing_session_id", "missing_turn", "invalid_turn",
        "session_freshdesk_mismatch", "empty_session", "session_id_mismatch",
        "duplicate_turn", "missing_turn0", "no_turn_zero", "unknown_quality_issue",
    }
)


_AI_REVIEW_RATING_BUCKETS = ("satisfied_count", "satisfied_with_edit_count", "needs_edit_count")


def _parse_cohort_weeks_filter(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("cohort_weeks is invalid")
    weeks = value.split(",")
    if not 2 <= len(weeks) <= 52 or len(set(weeks)) != len(weeks):
        raise ValueError("cohort_weeks is invalid")
    for cohort_week in weeks:
        try:
            parsed = date.fromisoformat(cohort_week)
        except ValueError as error:
            raise ValueError("cohort_weeks is invalid") from error
        if parsed.weekday() != 0:
            raise ValueError("cohort_weeks must contain Mondays")
    return frozenset(weeks)


def _parsed_ticket_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error


@dataclass(frozen=True)
class TicketRow:
    ticket_id: str
    opened_at: str
    cohort_week: str
    cohort_status: str
    is_weekend_start: bool
    outcome: str
    ai_first: bool
    transferred: bool
    reopen_lifetime: int | None
    reopen_within_7d: int | None
    ai_reply_count: int
    turn_count: int
    gt4_turn: bool
    issue_category: str
    app: str
    product_code: str
    skill: str | None
    intent: str | None
    tpe_code: str | None
    tpe_status: str | None
    guardrail_rule: str | None
    transfer_reason: str | None
    escalation_guard_blocked: bool
    csat_satisfaction: str | None
    data_quality: str
    model_core: str | None = None
    # Day-grain diagnostic fields (§4.1). Default empty/None so tickets built
    # before this field set existed still construct; a bumped
    # `_STORAGE_VERSION` means old *stored* snapshots never reach this
    # constructor anyway (`dashboard_cache.py` regenerates on version
    # mismatch instead of migrating field-by-field).
    transfer_rule: str | None = None
    transfer_source: str | None = None
    transfer_stage: str | None = None
    transfer_skill: str | None = None
    guardrail_rules: tuple[str, ...] = ()
    tpe_signals: tuple[tuple[str, str | None, str | None], ...] = ()
    # Public, unlike the diagnostic fields above: allowlisted `<tool>:<code>`
    # pairs, no free text and no PII. See `TicketDimensions.tool_error_codes`
    # for why this is a tuple rather than one label.
    tool_error_codes: tuple[str, ...] = ()
    # Per-ticket AI post-review (hậu kiểm) rating slug, mirroring
    # `csat_satisfaction`'s cache-lookup pattern. Public: a closed-enum slug,
    # not PII.
    ai_review_rating: str | None = None

    def __post_init__(self) -> None:
        _validate_ticket_values(self)


def _validate_ticket_filters(
    *,
    cohort_week: str | None,
    ticket_id: str | None,
    page: int,
    page_size: int,
    cohort_weeks: str | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be at least 1")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if ticket_id is not None and not _is_safe_ticket_id(ticket_id):
        raise ValueError("ticket_id is invalid")
    if cohort_week is not None and cohort_weeks is not None:
        raise ValueError("cohort_weeks cannot be combined with cohort_week")
    if cohort_week is not None:
        if not isinstance(cohort_week, str):
            raise ValueError("cohort_week is invalid")
        try:
            parsed = date.fromisoformat(cohort_week)
        except ValueError as error:
            raise ValueError("cohort_week is invalid") from error
        if parsed.weekday() != 0:
            raise ValueError("cohort_week must be a Monday")
    _parse_cohort_weeks_filter(cohort_weeks)
    if (opened_from is not None or opened_to is not None) and (
        cohort_week is not None or cohort_weeks is not None
    ):
        raise ValueError("opened_from cannot be combined with cohort_week")
    parsed_opened_from = _parsed_ticket_date(opened_from, "opened_from")
    parsed_opened_to = _parsed_ticket_date(opened_to, "opened_to")
    if (
        parsed_opened_from is not None
        and parsed_opened_to is not None
        and parsed_opened_from > parsed_opened_to
    ):
        raise ValueError("opened_from must not be after opened_to")


def _validate_ticket_values(ticket: TicketRow) -> None:
    _validate_ticket_filters(cohort_week=ticket.cohort_week, ticket_id=ticket.ticket_id, page=1, page_size=1)
    _parse_utc_iso(ticket.opened_at, "opened_at")
    if ticket.cohort_status not in {"complete", "wtd"}:
        raise ValueError("cohort_status is invalid")
    if ticket.outcome not in _OUTCOMES:
        raise ValueError("outcome is invalid")
    for value, name in ((ticket.is_weekend_start, "is_weekend_start"), (ticket.ai_first, "ai_first"), (ticket.transferred, "transferred"), (ticket.gt4_turn, "gt4_turn"), (ticket.escalation_guard_blocked, "escalation_guard_blocked")):
        if not isinstance(value, bool):
            raise ValueError(f"{name} is invalid")
    _nullable_nonnegative_int(ticket.reopen_lifetime, "reopen_lifetime")
    _nullable_nonnegative_int(ticket.reopen_within_7d, "reopen_within_7d")
    if ticket.reopen_within_7d not in {None, 0, 1}:
        raise ValueError("reopen_within_7d is invalid")
    _nonnegative_int(ticket.ai_reply_count, "ai_reply_count")
    _positive_int(ticket.turn_count, "turn_count")
    if ticket.gt4_turn != (ticket.turn_count > 3):
        raise ValueError("gt4_turn is inconsistent")
    for value, name in ((ticket.issue_category, "issue_category"), (ticket.app, "app"), (ticket.product_code, "product_code")):
        _safe_string(value, name)
    for value, name in (
        (ticket.skill, "skill"),
        (ticket.guardrail_rule, "guardrail_rule"),
        (ticket.model_core, "model_core"),
    ):
        if value is not None:
            _safe_string(value, name)
    if ticket.transferred:
        if ticket.transfer_reason not in _TRANSFER_TRIGGER_REASONS:
            raise ValueError("transfer_reason is invalid for a transferred ticket")
    elif ticket.transfer_reason is not None:
        raise ValueError("transfer_reason must be null for a ticket not transferred")
    if ticket.tpe_status is not None:
        raise ValueError("tpe_status must be null")
    if ticket.intent is not None and ticket.intent != "khác" and not _is_safe_intent_label(ticket.intent):
        raise ValueError("intent is invalid")
    if ticket.tpe_code is not None and (
        not isinstance(ticket.tpe_code, str)
        or _TPE_CODE_PATTERN.fullmatch(ticket.tpe_code) is None
    ):
        raise ValueError("tpe_code is invalid")
    if (
        ticket.csat_satisfaction is not None
        and ticket.csat_satisfaction not in _CSAT_TICKET_STATES
    ):
        raise ValueError("csat_satisfaction is invalid")
    if (
        ticket.ai_review_rating is not None
        and ticket.ai_review_rating not in _AI_REVIEW_RATING_SLUGS
    ):
        raise ValueError("ai_review_rating is invalid")
    if ticket.data_quality not in _QUALITY_LABELS:
        raise ValueError("data_quality is invalid")
    if ticket.transferred:
        if ticket.transfer_rule is not None and ticket.transfer_rule not in _GUARDRAIL_RULES:
            raise ValueError("transfer_rule is invalid")
    elif ticket.transfer_rule is not None:
        raise ValueError("transfer_rule must be null for a ticket not transferred")
    for value, name in (
        (ticket.transfer_source, "transfer_source"),
        (ticket.transfer_stage, "transfer_stage"),
        (ticket.transfer_skill, "transfer_skill"),
    ):
        if value is not None:
            _safe_string(value, name)
    if not ticket.transferred and (
        ticket.transfer_source is not None
        or ticket.transfer_stage is not None
        or ticket.transfer_skill is not None
    ):
        raise ValueError("transfer diagnostic fields must be null for a ticket not transferred")
    if not isinstance(ticket.guardrail_rules, tuple) or not all(
        isinstance(rule, str) and rule in _GUARDRAIL_RULES
        for rule in ticket.guardrail_rules
    ):
        raise ValueError("guardrail_rules is invalid")
    if len(set(ticket.guardrail_rules)) != len(ticket.guardrail_rules) or list(
        ticket.guardrail_rules
    ) != sorted(ticket.guardrail_rules):
        raise ValueError("guardrail_rules must be sorted, de-duplicated")
    if not isinstance(ticket.tpe_signals, tuple):
        raise ValueError("tpe_signals is invalid")
    for signal in ticket.tpe_signals:
        if not isinstance(signal, tuple) or len(signal) != 3:
            raise ValueError("tpe_signals is invalid")
        transstatus, step_result, status = signal
        if (
            not isinstance(transstatus, str)
            or _TPE_CODE_PATTERN.fullmatch(transstatus) is None
        ):
            raise ValueError("tpe_signals is invalid")
        if step_result is not None and (
            not isinstance(step_result, str)
            or _TPE_CODE_PATTERN.fullmatch(step_result) is None
        ):
            raise ValueError("tpe_signals is invalid")
        if status is not None:
            _safe_string(status, "tpe_signals status")
    if not isinstance(ticket.tool_error_codes, tuple) or not all(
        isinstance(token, str)
        and _TOOL_ERROR_CODE_PATTERN.fullmatch(token) is not None
        for token in ticket.tool_error_codes
    ):
        raise ValueError("tool_error_codes is invalid")
    if len(set(ticket.tool_error_codes)) != len(ticket.tool_error_codes) or list(
        ticket.tool_error_codes
    ) != sorted(ticket.tool_error_codes):
        raise ValueError("tool_error_codes must be sorted, de-duplicated")


def _is_safe_ticket_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and _TICKET_ID_PATTERN.fullmatch(value) is not None
        and _PHONE.search(value) is None
    )


def _safe_string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 256 or (not allow_empty and not value.strip()): raise ValueError(f"{name} is invalid")
    cleaned = normalize("NFC", value.strip())
    if (
        _PHONE.search(cleaned) or _UUID.search(cleaned) or _EMAIL.search(cleaned)
        or _URL.search(cleaned) or any(category(character).startswith("C") for character in cleaned)
        or _contains_long_numeric_identifier(cleaned) or _looks_like_vietnamese_personal_name(cleaned)
    ):
        raise ValueError(f"{name} is unsafe")
    return cleaned


def _is_safe_intent_label(value: object) -> bool:
    """Return true only for a non-identifying, canonical intent label.

    The syntax permitlist alone is insufficient: phone numbers, UUIDs and
    opaque numeric identifiers all satisfy the character class.  Keep this
    predicate independent of the projector so storage validation uses the
    exact same privacy boundary.
    """
    if not isinstance(value, str) or _INTENT_PATTERN.fullmatch(value) is None:
        return False
    return not (
        _PHONE.search(value)
        or _UUID.search(value)
        or _EMAIL.search(value)
        or _URL.search(value)
        or any(category(character).startswith("C") for character in value)
        or _contains_long_numeric_identifier(value)
    )


def _contains_long_numeric_identifier(value: str) -> bool:
    run_length = 0
    for character in value:
        try:
            decimal(character)
        except ValueError:
            run_length = 0
        else:
            run_length += 1
            if run_length >= 6:
                return True
    return False


def _looks_like_vietnamese_personal_name(value: str) -> bool:
    parts = value.casefold().split()
    return (
        len(parts) == 3
        and parts[0] in _VIETNAMESE_FAMILY_NAMES
        and parts[1] in _VIETNAMESE_NAME_MIDDLES
        and parts[2].isalpha()
        and 1 <= len(parts[2]) <= 32
    )


def _parse_utc_iso(value: object, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_ISO.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical UTC ISO timestamp")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error: raise ValueError(f"{name} must be a valid ISO timestamp") from error
    _require_aware(parsed, name); return parsed.astimezone(timezone.utc)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")


def _utc_iso(value: datetime) -> str:
    _require_aware(value, "datetime"); return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nullable_nonnegative_int(value: object, name: str) -> int | None:
    return None if value is None else _nonnegative_int(value, name)


_AI_REVIEW_RATING_SLUGS = frozenset(
    bucket.removesuffix("_count") for bucket in _AI_REVIEW_RATING_BUCKETS
)
