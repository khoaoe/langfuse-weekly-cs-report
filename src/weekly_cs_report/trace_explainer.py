from __future__ import annotations

"""Deterministic "why did the agent do that" explanation for one ticket.

Three separable responsibilities, each independently testable:
fetch (talk to Langfuse), compact (~20 observations -> 6-10 CS-readable
steps) and verdict (deterministic conclusion from the compacted steps).
No LLM in this module — see docs/superpowers/specs/2026-08-12-trace-
explainer-design.md section 3 for why that split matters.
"""

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from typing import Mapping, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .categories import Taxonomy
from .enrichment import is_blocking_guardrail
from .langfuse_client import LangfuseClient


LANGFUSE_TRACES_URL = "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces"

_VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_EVIDENCE_MAX_STRING_LENGTH = 2000
_EVIDENCE_NOISE_KEYS = {"messages_count", "iteration", "stop_reason"}
_EVIDENCE_NOISE_SUBSTRINGS = ("usage", "token")

_HIDDEN_EXACT_NAMES = {"pipeline", "execute", "tools_loaded", "load_context"}
_HIDDEN_PREFIXES = ("llm_call:", "plugin:")
_LOAD_SKILL_PREFIX = "tool:load_skill_reference__"
_TOOL_PREFIX = "tool:"


@dataclass(frozen=True)
class TraceStep:
    key: str
    label: str
    outcome: str  # "ok" | "chan" | "bo_qua"
    summary: str
    evidence: dict


@dataclass(frozen=True)
class TraceTurn:
    trace_id: str
    turn: int
    timestamp: str
    verdict: str  # "tra_loi" | "chuyen_cs" | "khong_tra_loi"
    verdict_reason: str
    skills_used: list[str]
    tools_called: list[str]
    steps: list[TraceStep]
    user_input: str
    response: str


@dataclass(frozen=True)
class TraceExplanation:
    ticket_id: str
    turns: list[TraceTurn]
    langfuse_url: str


def build_trace_explanation(
    client: LangfuseClient,
    ticket_id: str,
    taxonomy: Taxonomy,
) -> TraceExplanation | None:
    turns = fetch_trace_turns(client, ticket_id, taxonomy)
    if not turns:
        return None
    return TraceExplanation(
        ticket_id=ticket_id,
        turns=turns,
        langfuse_url=_langfuse_url(ticket_id, turns),
    )


def fetch_trace_turns(
    client: LangfuseClient,
    ticket_id: str,
    taxonomy: Taxonomy,
) -> list[TraceTurn]:
    """Fetch every trace of the session and compact each one into a turn."""
    turns: list[TraceTurn] = []
    for trace in client.list_traces_by_session(ticket_id):
        trace_id = trace.get("id")
        if not isinstance(trace_id, str) or not trace_id:
            continue
        observations = client.list_observations(trace_id)
        steps = compact_trace_steps(observations, taxonomy)
        verdict, verdict_reason = compute_verdict(steps)
        turns.append(
            TraceTurn(
                trace_id=trace_id,
                turn=_turn_number(trace),
                timestamp=_string_field(trace, "timestamp"),
                verdict=verdict,
                verdict_reason=verdict_reason,
                skills_used=_skills_used(steps),
                tools_called=_tools_called(steps),
                steps=steps,
                user_input=_nested_string_field(trace, "input", "user_input"),
                response=_nested_string_field(trace, "output", "response"),
            )
        )
    return turns


def compact_trace_steps(
    observations: Sequence[Mapping[str, object]],
    taxonomy: Taxonomy,
) -> list[TraceStep]:
    """Turn ~20 raw observations into the 6-10 steps a CS agent can read.

    Hidden spans (pipeline/execute/plugin:*/tools_loaded/load_context/
    llm_call:iter_N) are dropped entirely; every other span is kept,
    in chronological order, even when it is not in the mapping table
    below — an unmapped span must stay visible, never disappear.
    """
    steps: list[TraceStep] = []
    for observation in sorted(observations, key=_observation_sort_key):
        name = observation.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in _HIDDEN_EXACT_NAMES or name.startswith(_HIDDEN_PREFIXES):
            continue
        steps.append(_step_for(name, observation, taxonomy))
    return steps


def compute_verdict(steps: Sequence[TraceStep]) -> tuple[str, str]:
    """Deterministic conclusion, checked in a fixed priority order.

    This is NOT "first blocked step chronologically" — idempotency always
    outranks a later guard even if (hypothetically) both looked blocked.
    """
    blocked = _first_blocked(steps, "idempotency_guard")
    if blocked is not None:
        return "khong_tra_loi", "Ticket đã được xử lý trước đó"

    blocked = _first_blocked(steps, "escalation_history_guard")
    if blocked is not None:
        return "khong_tra_loi", "Ticket đã chuyển CS ở lượt trước"

    blocked = _first_blocked(steps, "input_guardrail")
    if blocked is not None:
        return "chuyen_cs", _rule_reason("Câu hỏi", blocked)

    blocked = _first_blocked(steps, "output_guardrail")
    if blocked is not None:
        return "chuyen_cs", _rule_reason("Câu trả lời", blocked)

    blocked = _first_blocked(steps, "skill_guardrail_checked")
    if blocked is not None:
        return "chuyen_cs", _rule_reason("Skill", blocked)

    return "tra_loi", "Agent đã trả lời khách"


def _first_blocked(steps: Sequence[TraceStep], key: str) -> TraceStep | None:
    return next((step for step in steps if step.key == key and step.outcome == "chan"), None)


def _rule_reason(subject: str, step: TraceStep) -> str:
    rule = _rule_of(step)
    return f"{subject} vướng rule {rule}" if rule else f"{subject} vướng rule không xác định"


def _rule_of(step: TraceStep) -> str | None:
    output = step.evidence.get("output")
    rule = output.get("rule") if isinstance(output, dict) else None
    return rule if isinstance(rule, str) and rule else None


def _step_for(
    name: str,
    observation: Mapping[str, object],
    taxonomy: Taxonomy,
) -> TraceStep:
    evidence = _evidence(observation)
    output = _mapping_field(observation, "output")
    input_ = _mapping_field(observation, "input")

    if name == "idempotency_guard":
        blocked = output.get("blocked") is True
        return TraceStep(
            key=name,
            label="Kiểm tra trùng lặp",
            outcome="chan" if blocked else "ok",
            summary=(
                "Ticket này đã được xử lý trước đó, agent không trả lời lại"
                if blocked
                else "Chưa xử lý trước đó, agent tiếp tục xử lý"
            ),
            evidence=evidence,
        )

    if name == "escalation_history_guard":
        blocked = output.get("blocked") is True
        return TraceStep(
            key=name,
            label="Kiểm tra lịch sử chuyển CS",
            outcome="chan" if blocked else "ok",
            summary=(
                "Ticket đã từng chuyển cho CS, agent không trả lời các lượt sau"
                if blocked
                else "Ticket chưa từng chuyển CS, agent tiếp tục xử lý"
            ),
            evidence=evidence,
        )

    if name == "input_guardrail":
        blocked = is_blocking_guardrail(observation, taxonomy)
        rule = output.get("rule") if isinstance(output.get("rule"), str) else None
        return TraceStep(
            key=name,
            label="Kiểm tra câu hỏi của khách",
            outcome="chan" if blocked else "ok",
            summary=(
                f"Câu hỏi vướng rule {rule}" if blocked and rule
                else "Câu hỏi vướng rule không xác định" if blocked
                else "Câu hỏi hợp lệ"
            ),
            evidence=evidence,
        )

    if name == "output_guardrail":
        blocked = is_blocking_guardrail(observation, taxonomy)
        rule = output.get("rule") if isinstance(output.get("rule"), str) else None
        return TraceStep(
            key=name,
            label="Kiểm tra câu trả lời",
            outcome="chan" if blocked else "ok",
            summary=(
                f"Câu trả lời vướng rule {rule}" if blocked and rule
                else "Câu trả lời vướng rule không xác định" if blocked
                else "Câu trả lời hợp lệ"
            ),
            evidence=evidence,
        )

    if name == "skill_guardrail_checked":
        blocked = is_blocking_guardrail(observation, taxonomy)
        rule = output.get("rule") if isinstance(output.get("rule"), str) else None
        stage = input_.get("stage") if isinstance(input_.get("stage"), str) else None
        stage_suffix = (
            " (đầu vào)" if stage == "input"
            else " (đầu ra)" if stage == "output"
            else ""
        )
        return TraceStep(
            key=name,
            label=f"Kiểm tra skill có phù hợp không{stage_suffix}",
            outcome="chan" if blocked else "ok",
            summary=(
                f"Skill vướng rule {rule}" if blocked and rule
                else "Skill vướng rule không xác định" if blocked
                else "Skill phù hợp"
            ),
            evidence=evidence,
        )

    if name == "route":
        agents = _string_list(output.get("agents"))
        return TraceStep(
            key=name,
            label="Chọn nhóm nghiệp vụ",
            outcome="ok",
            summary=(
                f"Chọn nhóm nghiệp vụ: {', '.join(agents)}" if agents
                else "Không xác định được nhóm nghiệp vụ"
            ),
            evidence=evidence,
        )

    if name == "plan":
        return TraceStep(
            key=name,
            label="Lập kế hoạch",
            outcome="ok",
            summary="Agent đã lập kế hoạch xử lý trước khi thực thi",
            evidence=evidence,
        )

    if name == "skills_loaded":
        skills = _string_list(output.get("skills"))
        return TraceStep(
            key=name,
            label="Nạp danh sách skill",
            outcome="ok",
            summary=(
                f"Đã nạp {len(skills)} skill: {', '.join(skills)}" if skills
                else "Không nạp được skill nào"
            ),
            evidence=evidence,
        )

    if name.startswith(_LOAD_SKILL_PREFIX):
        skill = name[len(_LOAD_SKILL_PREFIX):]
        return TraceStep(
            key=name,
            label=f"Chọn skill: {skill}",
            outcome="ok",
            summary=f"Agent chọn skill {skill} để trả lời",
            evidence=evidence,
        )

    if name.startswith(_TOOL_PREFIX):
        tool_name = name[len(_TOOL_PREFIX):]
        return TraceStep(
            key=name,
            label=f"Tra dữ liệu: {tool_name}",
            outcome="ok",
            summary=f"Agent tra cứu dữ liệu qua {tool_name}",
            evidence=evidence,
        )

    return TraceStep(
        key=name,
        label=name,
        outcome="ok",
        summary=f"Bước '{name}' chưa có mô tả, xem chi tiết bên dưới",
        evidence=evidence,
    )


def _skills_used(steps: Sequence[TraceStep]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for step in steps:
        if not step.key.startswith(_LOAD_SKILL_PREFIX):
            continue
        skill = step.key[len(_LOAD_SKILL_PREFIX):]
        if skill and skill not in seen:
            seen.add(skill)
            result.append(skill)
    return result


def _tools_called(steps: Sequence[TraceStep]) -> list[str]:
    return [
        step.key[len(_TOOL_PREFIX):]
        for step in steps
        if step.key.startswith(_TOOL_PREFIX)
    ]


def _observation_sort_key(observation: Mapping[str, object]) -> tuple[str, str]:
    timestamp = observation.get("startTime")
    if not isinstance(timestamp, str):
        timestamp = observation.get("timestamp")
    identifier = observation.get("id")
    return (
        timestamp if isinstance(timestamp, str) else "",
        identifier if isinstance(identifier, str) else "",
    )


def _mapping_field(observation: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = observation.get(key)
    return value if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _evidence(observation: Mapping[str, object]) -> dict[str, object]:
    # load_skill_reference carries the full sub-skill markdown in output.result,
    # and metadata (e.g. cs_escalation's `reason`) is never noisy in practice --
    # both are exempt from the 2000-char cap that still applies to everything else.
    name = observation.get("name")
    truncate_body = not (isinstance(name, str) and name.startswith(_LOAD_SKILL_PREFIX))
    result: dict[str, object] = {}
    for key in ("input", "output"):
        if key in observation:
            result[key] = _filtered_value(observation[key], truncate=truncate_body)
    if "metadata" in observation:
        result["metadata"] = _filtered_value(observation["metadata"], truncate=False)
    return result


def _filtered_value(value: object, truncate: bool = True) -> object:
    if isinstance(value, Mapping):
        return {
            key: _filtered_value(item, truncate=truncate)
            for key, item in value.items()
            if not _is_noise_key(key)
        }
    if isinstance(value, list):
        return [_filtered_value(item, truncate=truncate) for item in value]
    if isinstance(value, str):
        return value[:_EVIDENCE_MAX_STRING_LENGTH] if truncate else value
    return value


def _is_noise_key(key: str) -> bool:
    if key in _EVIDENCE_NOISE_KEYS:
        return True
    lowered = key.lower()
    return any(token in lowered for token in _EVIDENCE_NOISE_SUBSTRINGS)


def _turn_number(trace: Mapping[str, object]) -> int:
    metadata = trace.get("metadata")
    turn = metadata.get("turn") if isinstance(metadata, Mapping) else None
    return turn if isinstance(turn, int) and not isinstance(turn, bool) else 0


def _string_field(container: Mapping[str, object], key: str) -> str:
    value = container.get(key)
    return value if isinstance(value, str) else ""


def _nested_string_field(container: Mapping[str, object], outer: str, inner: str) -> str:
    nested = container.get(outer)
    value = nested.get(inner) if isinstance(nested, Mapping) else None
    return value if isinstance(value, str) else ""


def _langfuse_url(ticket_id: str, turns: Sequence[TraceTurn]) -> str:
    """Reuse TicketExplorer.tsx's exact filter format (frontend/src/components/
    TicketExplorer.tsx around line 105), scoped to this ticket's own turns
    instead of a whole cohort week — the backend has the real timestamps."""
    filter_value = f"sessionId;stringOptions;;any of;{ticket_id}"
    query = f"filter={quote(filter_value, safe='')}"

    timestamps = [value for value in (_parse_iso(turn.timestamp) for turn in turns) if value is not None]
    if timestamps:
        start_day = min(timestamps).astimezone(_VIETNAM_TZ).date()
        end_day = max(timestamps).astimezone(_VIETNAM_TZ).date()
        start_ms = _start_of_day_ms(start_day)
        end_ms = _start_of_day_ms(end_day + timedelta(days=1)) - 1
        query += f"&dateRange={start_ms}-{end_ms}"

    return f"{LANGFUSE_TRACES_URL}?{query}"


def _start_of_day_ms(day: date) -> int:
    return int(datetime.combine(day, dt_time.min, tzinfo=_VIETNAM_TZ).timestamp() * 1000)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
