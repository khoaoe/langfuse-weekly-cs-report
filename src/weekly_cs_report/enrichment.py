from __future__ import annotations

"""Pure, trace-grain parsing for the five bulk observation feeds.

Conflicting scalar signals are intentionally preserved until session reduction.
The reduction fails closed rather than choosing an API-order-dependent value.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
import re
from typing import Mapping, Sequence

from .categories import Taxonomy
from .models import TicketDimensions, TraceRecord


ENRICHMENT_NAMES = (
    "route",
    "execute",
    "input_guardrail",
    "skill_guardrail_checked",
    "escalation_history_guard",
)
_SAFE_SKILL = re.compile(r"^[a-z0-9_-]{1,64}$")
_PHONE_LIKE_SKILL = re.compile(r"(?:0|84)[0-9]{8,10}$")
_UUID_LIKE_SKILL = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_LONG_NUMERIC_RUN = re.compile(r"[0-9]{6,}")


@dataclass(frozen=True)
class TraceEnrichment:
    intents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    guardrail_rules: tuple[str, ...] = ()
    escalation_guard_blocked: bool = False


def build_trace_enrichment(
    observations_by_name: Mapping[str, Sequence[Mapping[str, object]]],
    taxonomy: Taxonomy,
) -> dict[str, TraceEnrichment]:
    """Parse allowlisted scalar signals keyed by Langfuse trace ID only."""
    intents: dict[str, set[str]] = defaultdict(set)
    skills: dict[str, set[str]] = defaultdict(set)
    rules: dict[str, set[str]] = defaultdict(set)
    blocked: set[str] = set()

    for observation in _ordered(observations_by_name.get("route", ())):
        trace_id = _trace_id(observation)
        intent = _nested_string(observation, "metadata", "intent")
        if trace_id is not None and intent is not None:
            intents[trace_id].add(intent)
    for observation in _ordered(observations_by_name.get("execute", ())):
        trace_id = _trace_id(observation)
        if trace_id is not None:
            skills[trace_id].update(_skills(observation, taxonomy))
    for name in ("input_guardrail", "skill_guardrail_checked"):
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
    for observation in _ordered(observations_by_name.get("escalation_history_guard", ())):
        trace_id = _trace_id(observation)
        if trace_id is not None and _nested_bool(observation, "output", "blocked") is True:
            blocked.add(trace_id)

    trace_ids = set(intents) | set(skills) | set(rules) | blocked
    result: dict[str, TraceEnrichment] = {}
    for trace_id in trace_ids:
        item = TraceEnrichment(
            intents=tuple(sorted(intents.get(trace_id, ()))),
            skills=tuple(sorted(skills.get(trace_id, ()))),
            guardrail_rules=tuple(sorted(rules.get(trace_id, ()))),
            escalation_guard_blocked=trace_id in blocked,
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
    blocked = False
    for trace in traces:
        enrichment = enrichment_by_trace_id.get(trace.id)
        if enrichment is None:
            continue
        intents.update(enrichment.intents)
        skills.update(enrichment.skills)
        guardrail_rules.update(enrichment.guardrail_rules)
        blocked = blocked or enrichment.escalation_guard_blocked
    return (
        replace(
            dimensions,
            intent=_only_value(intents),
            skill=_only_value(skills),
            guardrail_rule=_only_value(guardrail_rules),
            escalation_guard_blocked=blocked,
        ),
        tuple(sorted(guardrail_rules)),
    )


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
