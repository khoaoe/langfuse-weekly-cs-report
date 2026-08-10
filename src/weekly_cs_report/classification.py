from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Mapping, Sequence
from unicodedata import normalize

from .cohort import VIETNAM_TIMEZONE, cohort_week_for, score_anchor_for
from .models import CohortWindow, QualityIssue, SessionMetrics, TraceRecord


_SYSTEM_ONLY_AGENTS = frozenset(
    {
        "guardrail",
        "idempotency_guard",
        "escalation_history_guard",
    }
)
_TECHNICAL_RESPONSE_MARKERS = frozenset(
    {
        "no_data",
        "exception",
        "escalate_cs_message",
    }
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalize_transfer_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parser = _TextExtractor()
    parser.feed(unescape(normalize("NFKC", value).casefold()))
    parser.close()
    return "".join("".join(parser.parts).split())


def is_transfer_response(
    output: object, canonical_text: str | Sequence[str]
) -> bool:
    if not isinstance(output, Mapping):
        return False
    response = normalize_transfer_text(output.get("response"))
    templates = (
        (canonical_text,)
        if isinstance(canonical_text, str)
        else canonical_text
        if isinstance(canonical_text, Sequence)
        else ()
    )
    normalized_templates = {
        template
        for value in templates
        if (template := normalize_transfer_text(value)) is not None
    }
    return response is not None and response in normalized_templates


def _is_guardrail_or_system_only_output(output: Mapping[str, object]) -> bool:
    if (
        output.get("blocked") is True
        or output.get("passed") is False
        or bool(output.get("violation"))
    ):
        return True

    response = normalize_transfer_text(output.get("response"))
    if response == "escalate_cs_message":
        return True

    agents_used = output.get("agents_used")
    if isinstance(agents_used, str):
        agents = (agents_used,)
    elif isinstance(agents_used, Sequence):
        agents = tuple(agents_used)
    else:
        return False
    if not agents or any(not isinstance(agent, str) for agent in agents):
        return False
    normalized_agents = {
        normalize("NFKC", agent).strip().casefold() for agent in agents
    }
    return bool(normalized_agents) and normalized_agents <= _SYSTEM_ONLY_AGENTS


def is_substantive_ai_response(
    output: object, canonical_text: str | Sequence[str]
) -> bool:
    if not isinstance(output, Mapping):
        return False
    response = output.get("response")
    if not isinstance(response, str) or not response.strip():
        return False
    if _is_guardrail_or_system_only_output(output):
        return False
    if normalize_transfer_text(response) in _TECHNICAL_RESPONSE_MARKERS:
        return False
    return not is_transfer_response(output, canonical_text)


def _issue(reason: str, raw: Mapping[str, object], timestamp: datetime | None = None) -> QualityIssue:
    session_id = raw.get("sessionId")
    trace_id = raw.get("id")
    return QualityIssue(
        reason=reason,
        session_id=session_id if isinstance(session_id, str) and session_id else None,
        trace_id=trace_id if isinstance(trace_id, str) and trace_id else None,
        timestamp=timestamp,
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    timestamp_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(timestamp_value)
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp


def normalize_trace(raw: dict[str, object]) -> TraceRecord | QualityIssue:
    timestamp = _parse_timestamp(raw.get("timestamp"))
    if timestamp is None:
        return _issue("invalid_timestamp", raw)

    trace_id = raw.get("id")
    if not isinstance(trace_id, str) or not trace_id:
        return _issue("missing_trace_id", raw, timestamp)

    session_id = raw.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return _issue("missing_session_id", raw, timestamp)

    metadata = raw.get("metadata")
    turn = metadata.get("turn") if isinstance(metadata, Mapping) else None
    if turn is None:
        return _issue("missing_turn", raw, timestamp)
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 0:
        return _issue("invalid_turn", raw, timestamp)

    input_data = raw.get("input")
    other_info = input_data.get("other_info") if isinstance(input_data, Mapping) else None
    freshdesk_id = (
        other_info.get("freshdesk_id")
        if isinstance(other_info, Mapping)
        else None
    )
    if (
        isinstance(freshdesk_id, str)
        and freshdesk_id
        and freshdesk_id != session_id
    ):
        return _issue("session_freshdesk_mismatch", raw, timestamp)

    environment = raw.get("environment")
    return TraceRecord(
        id=trace_id,
        session_id=session_id,
        timestamp=timestamp,
        turn=turn,
        input_data=input_data,
        output_data=raw.get("output"),
        environment=environment if isinstance(environment, str) else "",
    )


def _cohort_status(first: TraceRecord, window: CohortWindow) -> str:
    local_timestamp = first.timestamp.astimezone(VIETNAM_TIMEZONE)
    if window.complete_start_local <= local_timestamp < window.complete_end_exclusive_local:
        return "complete"
    if (
        window.wtd_start_local is not None
        and window.wtd_start_local <= local_timestamp <= window.as_of.astimezone(VIETNAM_TIMEZONE)
    ):
        return "wtd"
    return "out_of_scope"


def _output_quality(output: object) -> tuple[str, str]:
    if _is_malformed_output(output):
        return "unknown", "malformed_output"
    if isinstance(output, Mapping) and _is_guardrail_or_system_only_output(output):
        return "guardrail_rule", "valid"
    return "empty_or_technical", "empty_or_technical"


def _is_malformed_output(output: object) -> bool:
    return not isinstance(output, Mapping) or not isinstance(output.get("response"), str)


def _first_classifiable_trace(
    traces: Sequence[TraceRecord], canonical_text: str | Sequence[str]
) -> tuple[int, TraceRecord, bool] | None:
    """Find the first trace that establishes the ticket's handling path.

    Guardrail/system-only and empty/technical outputs are not handling outcomes.
    A later substantive AI response or canonical transfer must therefore still
    be allowed to classify the ticket.
    """
    for index, trace in enumerate(traces):
        if is_transfer_response(trace.output_data, canonical_text):
            return index, trace, False
        if is_substantive_ai_response(trace.output_data, canonical_text):
            return index, trace, True
    return None


def classify_session(
    traces: Sequence[TraceRecord],
    window: CohortWindow,
    canonical_text: str | Sequence[str],
) -> SessionMetrics | QualityIssue:
    if not traces:
        return QualityIssue("empty_session", None, None, None)

    ordered = sorted(traces, key=lambda item: (item.turn, item.timestamp, item.id))
    session_ids = {item.session_id for item in ordered}
    if len(session_ids) != 1:
        return QualityIssue("session_id_mismatch", None, None, None)
    first = ordered[0]
    turn_counts = Counter(item.turn for item in ordered)
    transfer_traces = [
        item for item in ordered if is_transfer_response(item.output_data, canonical_text)
    ]
    first_classifiable = _first_classifiable_trace(ordered, canonical_text)
    first_classifiable_index = (
        first_classifiable[0] if first_classifiable is not None else None
    )
    first_classifiable_trace = (
        first_classifiable[1] if first_classifiable is not None else None
    )
    first_is_ai = first_classifiable[2] if first_classifiable is not None else False
    first_transfer = (
        transfer_traces[0]
        if first_classifiable is not None and not first_is_ai
        else next(
            (
                item
                for item in ordered[(first_classifiable_index or 0) + 1 :]
                if is_transfer_response(item.output_data, canonical_text)
            ),
            None,
        )
    )
    ai_reply_count = sum(
        is_substantive_ai_response(item.output_data, canonical_text) for item in ordered
    )
    cohort_status = _cohort_status(first, window)

    if first_classifiable is not None and first_is_ai:
        ai_first = True
        no_ai_first_reason = None
        outcome = (
            "ai_then_cs"
            if any(is_transfer_response(item.output_data, canonical_text) for item in ordered[1:])
            else "ai_end_to_end"
        )
        data_quality = "valid"
    elif first_classifiable is not None:
        ai_first = False
        no_ai_first_reason = "direct_cs"
        outcome = "direct_cs"
        data_quality = "valid"
    else:
        ai_first = False
        no_ai_first_reason, data_quality = _output_quality(first.output_data)
        outcome = "unclassified"

    malformed_trace = next(
        (item for item in ordered if _is_malformed_output(item.output_data)),
        None,
    )
    if malformed_trace is not None:
        data_quality = "malformed_output"

    # ``turn`` is a Freshdesk message index, not a zero-based lifecycle index.
    # A follow-up is measured after the first classifiable handling trace.
    followups = (
        ordered[(first_classifiable_index or 0) + 1 :]
        if first_classifiable_trace is not None
        else ordered[1:]
    )
    if ai_first:
        reopen_lifetime = int(bool(followups))
        reopen_within_7d = int(
            any(
                timedelta() < item.timestamp - first.timestamp <= timedelta(hours=168)
                for item in followups
            )
        )
    else:
        reopen_lifetime = None
        reopen_within_7d = None

    control_reopen_within_7d = (
        int(
            any(
                timedelta() < item.timestamp - first.timestamp <= timedelta(hours=168)
                for item in followups
            )
        )
        if outcome == "direct_cs"
        else None
    )

    return SessionMetrics(
        session_id=first.session_id,
        turn0_trace_id=first.id,
        turn0_timestamp=first.timestamp,
        cohort_week=cohort_week_for(first.timestamp),
        score_timestamp=score_anchor_for(cohort_week_for(first.timestamp)),
        cohort_status=cohort_status,
        ai_first=ai_first,
        no_ai_first_reason=no_ai_first_reason,
        outcome=outcome,
        reopen_lifetime=reopen_lifetime,
        reopen_within_7d=reopen_within_7d,
        ai_reply_count=ai_reply_count,
        first_transfer_trace_id=first_transfer.id if first_transfer is not None else None,
        data_quality=(
            "duplicate_turn"
            if any(count > 1 for count in turn_counts.values())
            else "no_turn_zero"
            if not any(item.turn == 0 for item in ordered)
            else data_quality
        ),
        environment=first.environment,
        is_weekend_start=first.timestamp.astimezone(VIETNAM_TIMEZONE).weekday() >= 5,
        turn_count=len(ordered),
        transferred=first_transfer is not None,
        control_reopen_within_7d=control_reopen_within_7d,
    )
