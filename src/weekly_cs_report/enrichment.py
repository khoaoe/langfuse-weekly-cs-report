from __future__ import annotations

"""Pure, trace-grain parsing for the bulk observation feeds.

Conflicting scalar signals are intentionally preserved until session reduction.
The reduction fails closed rather than choosing an API-order-dependent value.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
import re
from typing import Mapping, Sequence

from .categories import Taxonomy
from .models import SessionMetrics, TicketDimensions, TraceRecord, TransferTrigger
from .tpe_status import resolve_tpe_status


ENRICHMENT_NAMES = (
    "tool:get_transaction_processing_engine_data",
    "route",
    "execute",
    "input_guardrail",
    "skill_guardrail_checked",
    "output_guardrail",
    "escalation_history_guard",
)
_SAFE_SKILL = re.compile(r"^[a-z0-9_-]{1,64}$")
_PHONE_LIKE_SKILL = re.compile(r"(?:0|84)[0-9]{8,10}$")
_UUID_LIKE_SKILL = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_LONG_NUMERIC_RUN = re.compile(r"[0-9]{6,}")
_SAFE_TPE_TOKEN = re.compile(r"-?[0-9]{1,6}\Z")


@dataclass(frozen=True)
class GuardrailEvent:
    """Allowlisted blocked guardrail metadata at one trace grain."""

    rule: str
    source: str
    stage: str | None = None
    skill: str | None = None


@dataclass(frozen=True)
class TraceEnrichment:
    intents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    guardrail_rules: tuple[str, ...] = ()
    guardrail_events: tuple[GuardrailEvent, ...] = ()
    escalation_guard_blocked: bool = False
    tpe_signals: tuple[tuple[str, str | None], ...] = ()


def build_trace_enrichment(
    observations_by_name: Mapping[str, Sequence[Mapping[str, object]]],
    taxonomy: Taxonomy,
) -> dict[str, TraceEnrichment]:
    """Parse allowlisted scalar signals keyed by Langfuse trace ID only."""
    intents: dict[str, set[str]] = defaultdict(set)
    skills: dict[str, set[str]] = defaultdict(set)
    rules: dict[str, set[str]] = defaultdict(set)
    guardrail_events: dict[
        str,
        list[tuple[tuple[int, tuple[str, str]], GuardrailEvent]],
    ] = defaultdict(list)
    blocked: set[str] = set()
    tpe_signals: dict[str, set[tuple[str, str | None]]] = defaultdict(set)

    for observation in _ordered(observations_by_name.get("route", ())):
        trace_id = _trace_id(observation)
        intent = _nested_string(observation, "metadata", "intent")
        if trace_id is not None and intent is not None:
            intents[trace_id].add(intent)
    for observation in _ordered(observations_by_name.get("execute", ())):
        trace_id = _trace_id(observation)
        if trace_id is not None:
            skills[trace_id].update(_skills(observation, taxonomy))
    for name in ("input_guardrail", "skill_guardrail_checked", "output_guardrail"):
        for observation in _ordered(observations_by_name.get(name, ())):
            trace_id = _trace_id(observation)
            rule = _nested_string(observation, "output", "rule")
            if (
                trace_id is not None
                and rule is not None
                and rule in taxonomy.guardrail_allowed_values
                and rule not in taxonomy.guardrail_compliant_values
            ):
                rules[trace_id].add(rule)
                if is_blocking_guardrail(observation, taxonomy):
                    stage = (
                        _nested_string(observation, "input", "stage")
                        if name == "skill_guardrail_checked"
                        else None
                    )
                    if stage not in {"input", "output"}:
                        stage = None
                    skill = (
                        _guardrail_skill(observation, taxonomy)
                        if name == "skill_guardrail_checked"
                        else None
                    )
                    event = GuardrailEvent(
                        rule=rule,
                        source=name,
                        stage=stage,
                        skill=skill,
                    )
                    guardrail_events[trace_id].append(
                        ((_guardrail_source_order(name, stage), _observation_key(observation)), event)
                    )
    for observation in _ordered(observations_by_name.get("escalation_history_guard", ())):
        trace_id = _trace_id(observation)
        if trace_id is not None and _nested_bool(observation, "output", "blocked") is True:
            blocked.add(trace_id)
    for observation in _ordered(
        observations_by_name.get(
            "tool:get_transaction_processing_engine_data",
            (),
        )
    ):
        trace_id = _trace_id(observation)
        signal = _tpe_signal(observation)
        if trace_id is not None and signal is not None:
            tpe_signals[trace_id].add(signal)

    trace_ids = (
        set(intents)
        | set(skills)
        | set(rules)
        | set(guardrail_events)
        | blocked
        | set(tpe_signals)
    )
    result: dict[str, TraceEnrichment] = {}
    for trace_id in trace_ids:
        item = TraceEnrichment(
            intents=tuple(sorted(intents.get(trace_id, ()))),
            skills=tuple(sorted(skills.get(trace_id, ()))),
            guardrail_rules=tuple(sorted(rules.get(trace_id, ()))),
            guardrail_events=_ordered_guardrail_events(
                guardrail_events.get(trace_id, ())
            ),
            escalation_guard_blocked=trace_id in blocked,
            tpe_signals=tuple(
                sorted(
                    tpe_signals.get(trace_id, ()),
                    key=_tpe_signal_sort_key,
                )
            ),
        )
        if item != TraceEnrichment():
            result[trace_id] = item
    return result


def apply_trace_enrichment(
    dimensions: TicketDimensions,
    traces: Sequence[TraceRecord],
    enrichment_by_trace_id: Mapping[str, TraceEnrichment],
) -> tuple[TicketDimensions, tuple[str, ...]]:
    """Fail closed on conflicting scalars; preserve rules for internal counts."""
    intents: set[str] = set()
    skills: set[str] = set()
    guardrail_rules: set[str] = set()
    tpe_signals: set[tuple[str, str | None]] = set()
    blocked = False
    for trace in traces:
        enrichment = enrichment_by_trace_id.get(trace.id)
        if enrichment is None:
            continue
        intents.update(enrichment.intents)
        skills.update(enrichment.skills)
        guardrail_rules.update(enrichment.guardrail_rules)
        tpe_signals.update(enrichment.tpe_signals)
        blocked = blocked or enrichment.escalation_guard_blocked
    sorted_skills = tuple(sorted(skills))
    return (
        replace(
            dimensions,
            intent=_only_value(intents),
            skill=_only_value(skills),
            guardrail_rule=_only_value(guardrail_rules),
            escalation_guard_blocked=blocked,
            tpe_signals=tuple(sorted(tpe_signals, key=_tpe_signal_sort_key)),
            skill_count=len(sorted_skills),
            skill_set=sorted_skills,
        ),
        tuple(sorted(guardrail_rules)),
    )


def transfer_trigger_for_trace(
    trace_id: str | None,
    enrichment_by_trace_id: Mapping[str, TraceEnrichment],
) -> TransferTrigger | None:
    """Return one exclusive trigger from the first canonical transfer trace."""
    if trace_id is None:
        return None
    enrichment = enrichment_by_trace_id.get(trace_id)
    if enrichment is None or not enrichment.guardrail_events:
        return None
    event = enrichment.guardrail_events[0]
    return TransferTrigger(
        reason=_transfer_reason(event),
        rule=event.rule,
        source=event.source,
        stage=event.stage,
        skill=event.skill,
    )


def _transfer_reason(event: GuardrailEvent) -> str:
    if (
        event.rule == "cs_escalation"
        and event.source == "skill_guardrail_checked"
        and event.stage == "output"
    ):
        return "skill_suggested_transfer"
    if event.rule == "cs_escalation" and event.source == "output_guardrail":
        return "ai_response_requires_transfer"
    return {
        "missing_transaction_id": "missing_transaction_id",
        "max_replies_exceeded": "max_replies_exceeded",
        "off_topic": "out_of_scope",
        "off_topic_llm": "out_of_scope",
        "empty_input": "empty_message",
        "empty_message_marker": "empty_message",
        "prompt_injection": "prompt_injection",
        "prompt_injection_llm": "prompt_injection",
        "system_prompt_leak": "prompt_injection",
        "tone_check_error": "output_check_error",
    }.get(event.rule, "other_guardrail")


def _ordered(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(rows, key=_observation_key)


def _observation_key(observation: Mapping[str, object]) -> tuple[str, str]:
    timestamp = observation.get("startTime")
    if not isinstance(timestamp, str):
        timestamp = observation.get("timestamp")
    identifier = observation.get("id")
    return (
        timestamp if isinstance(timestamp, str) else "",
        identifier if isinstance(identifier, str) else "",
    )


def _trace_id(observation: Mapping[str, object]) -> str | None:
    value = observation.get("traceId")
    return value if isinstance(value, str) and value else None


def _nested_string(observation: Mapping[str, object], container: str, key: str) -> str | None:
    value = observation.get(container)
    candidate = value.get(key) if isinstance(value, Mapping) else None
    return candidate if isinstance(candidate, str) and candidate else None


def _nested_bool(observation: Mapping[str, object], container: str, key: str) -> bool | None:
    value = observation.get(container)
    candidate = value.get(key) if isinstance(value, Mapping) else None
    return candidate if isinstance(candidate, bool) else None


def is_blocking_guardrail(
    observation: Mapping[str, object],
    taxonomy: Taxonomy,
) -> bool:
    if any(
        _nested_bool(observation, "output", field) is True
        for field in taxonomy.guardrail_blocked_fields
    ):
        return True
    return (
        _nested_bool(
            observation,
            "output",
            taxonomy.guardrail_passed_field,
        )
        is False
    )


def _guardrail_skill(
    observation: Mapping[str, object],
    taxonomy: Taxonomy,
) -> str | None:
    raw = _nested_string(observation, "input", "skill")
    if raw is None:
        return None
    value = raw.removeprefix(taxonomy.skills_prefix_strip or "")
    return value if _safe_skill(value) else None


def _guardrail_source_order(source: str, stage: str | None) -> int:
    return {
        ("input_guardrail", None): 0,
        ("skill_guardrail_checked", "input"): 1,
        ("skill_guardrail_checked", "output"): 2,
        ("output_guardrail", None): 3,
    }.get((source, stage), 4)


def _ordered_guardrail_events(
    rows: Sequence[tuple[tuple[int, tuple[str, str]], GuardrailEvent]],
) -> tuple[GuardrailEvent, ...]:
    result: list[GuardrailEvent] = []
    seen: set[GuardrailEvent] = set()
    for _key, event in sorted(
        rows,
        key=lambda item: (
            item[0],
            item[1].rule,
            item[1].skill or "",
        ),
    ):
        if event in seen:
            continue
        seen.add(event)
        result.append(event)
    return tuple(result)


def _tpe_signal(
    observation: Mapping[str, object],
) -> tuple[str, str | None] | None:
    output = observation.get("output")
    result = output.get("result") if isinstance(output, Mapping) else None
    if not isinstance(result, Mapping):
        return None
    transstatus = _safe_tpe_token(result.get("transstatus"))
    if transstatus is None:
        return None
    return transstatus, _safe_tpe_token(result.get("stepresult"))


def _safe_tpe_token(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = str(value)
    elif isinstance(value, str):
        candidate = value
    else:
        return None
    return candidate if _SAFE_TPE_TOKEN.fullmatch(candidate) is not None else None


def _tpe_signal_sort_key(
    value: tuple[str, str | None],
) -> tuple[int, bool, int]:
    transstatus, step_result = value
    return (
        int(transstatus),
        step_result is None,
        int(step_result) if step_result is not None else 0,
    )


def _skills(observation: Mapping[str, object], taxonomy: Taxonomy) -> tuple[str, ...]:
    value = observation.get("metadata")
    raw = value.get("skills_used") if isinstance(value, Mapping) else None
    candidates = (raw,) if isinstance(raw, str) else raw if isinstance(raw, Sequence) else ()
    parsed: set[str] = set()
    for item in candidates:
        if not isinstance(item, str):
            continue
        stripped = item.removeprefix(taxonomy.skills_prefix_strip or "")
        if _safe_skill(stripped):
            parsed.add(stripped)
    return tuple(sorted(parsed))


def _safe_skill(value: str) -> bool:
    return bool(
        _SAFE_SKILL.fullmatch(value)
        and not _PHONE_LIKE_SKILL.fullmatch(value)
        and not _UUID_LIKE_SKILL.fullmatch(value)
        and not _LONG_NUMERIC_RUN.search(value)
    )


def _only_value(values: set[str]) -> str | None:
    return next(iter(values)) if len(values) == 1 else None


def build_tpe_status_index(
    sessions: Sequence[SessionMetrics], taxonomy: Taxonomy
) -> dict[tuple[str, str | None], str]:
    """Map every observed (transstatus, step_result) to its governed status.

    Only observed pairs are included, so the payload never ships the taxonomy
    itself.  Unmapped pairs are omitted entirely — absence means "not mapped",
    which the browser renders as unclassified rather than guessing.
    """
    index: dict[tuple[str, str | None], str] = {}
    for session in sessions:
        for pair in session.dimensions.tpe_signals:
            if pair in index:
                continue
            status = resolve_tpe_status(pair[0], pair[1], taxonomy)
            if status is not None:
                index[pair] = status
    return index
