"""Tầng 1: deterministic escalation dossier -- no LLM, usable on its own.

Builds on trace_explainer's existing TraceTurn/TraceStep compaction (fetch +
compact are already solved there); this module only adds the "why" layer:
which of the seven escalation branches applies, what rule text backs it, and
what evidence the agent actually retrieved.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import explain_context
from .categories import Taxonomy
from .explain_context import ExplainConfig, TicketFact
from .langfuse_client import LangfuseClient
from .skill_rules import RuleCandidate
from .trace_explainer import TraceStep, TraceTurn, fetch_trace_turns

_LOG = logging.getLogger("weekly_cs_report.escalation_dossier")

_LOAD_SKILL_PREFIX = "tool:load_skill_reference__"
_LIST_SKILL_PREFIX = "tool:list_skill_references__"
_TOOL_PREFIX = "tool:"

_INPUT_GUARDRAIL_KEY = "input_guardrail"
_OUTPUT_GUARDRAIL_KEY = "output_guardrail"
_SKILL_GUARDRAIL_KEY = "skill_guardrail_checked"
_IDEMPOTENCY_KEY = "idempotency_guard"
_ESCALATION_HISTORY_KEY = "escalation_history_guard"
_GENERAL_RESPONSE_KEY = "general_response"

_CS_ESCALATION_RULE_FAMILY = {"cs_escalation", "cs_escalation_regex"}
_TONE_CHECK_ERROR_RULE = "tone_check_error"
_CANDIDATE_CAP = 40

# The running agent's tool/skill spans use the runtime skill name
# ("interbank-fund-transfer"), but that skill's source doc folder --
# ../docs/cs-agent-skills/ibft -- and skills-snapshot/ibft/ keep the short
# alias. Translate before looking up `rules` (keyed by snapshot folder name)
# so IBFT tickets actually get rule_candidates instead of silently coming
# back empty.
_SKILL_SNAPSHOT_ALIASES = {"interbank-fund-transfer": "ibft"}


def _snapshot_skill_key(skill: str) -> str:
    return _SKILL_SNAPSHOT_ALIASES.get(skill, skill)
_ESCALATE_PHRASE_RE = re.compile(
    r"chuy[ểê]n\b.{0,20}\bcskh|chăm sóc khách hàng|\bcskh\b|\bcs\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolEvidence:
    step_key: str
    label: str
    value: str
    turn: int
    failed: bool


@dataclass(frozen=True)
class TurnDelta:
    turn: int
    agent_asked_for: tuple[str, ...]
    facts_already_known: tuple[str, ...]


@dataclass(frozen=True)
class CoverageCheck:
    app_id: str | None
    expected_skill: str | None
    loaded_skills: tuple[str, ...]
    mismatch: bool


@dataclass(frozen=True)
class TimelineRow:
    label: str
    value: str
    evidence: dict


@dataclass(frozen=True)
class TimelinePhase:
    key: str
    title: str
    summary: str
    rows: tuple[TimelineRow, ...]
    state: str  # "dat" | "thong_tin" | "quyet_dinh" | "chan"
    collapsed: bool


@dataclass(frozen=True)
class EscalationDossier:
    ticket_id: str
    escalation_class: str  # "E1".."E9" | "NONE"
    escalated_turn: int | None
    guardrail_reason: str | None
    blocking_rule: str | None
    skills_loaded: tuple[str, ...]
    sub_skills_read: tuple[str, ...]
    tool_evidence: tuple[ToolEvidence, ...]
    ticket_facts: tuple[TicketFact, ...]
    rule_candidates: tuple[RuleCandidate, ...]
    coverage: CoverageCheck
    turn_deltas: tuple[TurnDelta, ...]
    drift_changed: bool
    phases: tuple[TimelinePhase, ...]
    # The guardrail that actually decided (skill_guardrail_checked stage=output,
    # or the generic output_guardrail) only ever sees the drafted answer -- so
    # that draft, not the mechanical case citation, is the real "why" for E1/
    # E2/E8/E9. Masked with mask_free_text before this ever reaches the dossier.
    blocked_response_draft: str | None
    # E3 (input-stage block) has no drafted answer to show -- the customer's
    # own message is the thing the guardrail actually inspected instead.
    blocked_input_message: str | None


# --------------------------------------------------------------------------
# Branch classification (spec 5.2) -- priority order E5 > E4 > E3 > E7 > E1 > E2 > E6
# --------------------------------------------------------------------------


def _step(turn: TraceTurn, key: str) -> TraceStep | None:
    return next((s for s in turn.steps if s.key == key), None)


def _first_blocked_step(turn: TraceTurn, key: str) -> TraceStep | None:
    # skill_guardrail_checked (and in principle other spans) can appear more
    # than once per turn -- one span per guardrail stage -- so grabbing the
    # first occurrence of `key` is not the same as grabbing the blocked one.
    return next((s for s in turn.steps if s.key == key and s.outcome == "chan"), None)


def _first_blocked_step_at_stage(turn: TraceTurn, key: str, stage: str) -> TraceStep | None:
    return next(
        (s for s in turn.steps if s.key == key and s.outcome == "chan" and _stage_of(s) == stage),
        None,
    )


def _rule_of(step: TraceStep | None) -> str | None:
    if step is None:
        return None
    output = step.evidence.get("output")
    rule = output.get("rule") if isinstance(output, Mapping) else None
    return rule if isinstance(rule, str) else None


def _stage_of(step: TraceStep | None) -> str | None:
    if step is None:
        return None
    input_ = step.evidence.get("input")
    stage = input_.get("stage") if isinstance(input_, Mapping) else None
    return stage if isinstance(stage, str) else None


def _looks_like_escalate_message(message: object) -> bool:
    return isinstance(message, str) and bool(_ESCALATE_PHRASE_RE.search(message))


def _e7_tool_step(turn: TraceTurn) -> TraceStep | None:
    for step in turn.steps:
        if not step.key.startswith(_TOOL_PREFIX):
            continue
        if step.key.startswith(_LOAD_SKILL_PREFIX) or step.key.startswith(_LIST_SKILL_PREFIX):
            continue
        output = step.evidence.get("output")
        result = output.get("result") if isinstance(output, Mapping) else None
        if not isinstance(result, Mapping):
            continue
        message = result.get("message")
        if ("error" in result or "info" in result) and _looks_like_escalate_message(message):
            return step
    return None


def _output_stage_branch(step: TraceStep, *, escalation_branch: str) -> str:
    """Classify a blocked output-stage step (skill_guardrail output or the
    generic output_guardrail) by what its `rule` actually means.

    - cs_escalation / cs_escalation_regex: the bot's draft really did say
      "chuyển giao cho người/bộ phận xử lý" -- E1 (per-skill) or E2 (generic).
    - tone_check_error: the tone_llm guardrail itself crashed (except-branch
      in cs-agent-master's ToneLlmModule) -- an infra fault, not a content
      problem, so it must not be counted as "bot wrote badly" -- E9.
    - anything else (profanity, customer_insult, foreign_language,
      inappropriate_tone_llm, ...): the draft failed a real content check
      that has nothing to do with escalation intent -- E8.
    """

    rule = _rule_of(step)
    if rule in _CS_ESCALATION_RULE_FAMILY:
        return escalation_branch
    if rule == _TONE_CHECK_ERROR_RULE:
        return "E9"
    return "E8"


def _decisive_step_and_branch(turn: TraceTurn) -> tuple[str, TraceStep | None]:
    """Find the branch AND the exact step that decided it, in one pass.

    Real production data shows `skill_guardrail_checked` blocking at
    stage=input (missing_transaction_id, off_topic, ...) is one of the most
    common causes -- not just the global `input_guardrail` span. And that
    same span can block at stage=output for reasons other than
    `cs_escalation` (e.g. tone_check_error). Both are "agent chưa vào
    nghiệp vụ / kỹ thuật chặn" in spirit, not a specific business case, so
    they fold into E3 -- same treatment already given to `output_guardrail`
    blocking on a non-cs_escalation rule.
    """

    step = _first_blocked_step(turn, _IDEMPOTENCY_KEY)
    if step is not None:
        return "E5", step

    step = _first_blocked_step(turn, _ESCALATION_HISTORY_KEY)
    if step is not None:
        return "E4", step

    step = _first_blocked_step(turn, _INPUT_GUARDRAIL_KEY)
    if step is not None:
        return "E3", step

    step = _first_blocked_step_at_stage(turn, _SKILL_GUARDRAIL_KEY, "input")
    if step is not None:
        return "E3", step

    step = _first_blocked_step_at_stage(turn, _SKILL_GUARDRAIL_KEY, "output")
    if step is not None:
        return _output_stage_branch(step, escalation_branch="E1"), step

    step = _first_blocked_step(turn, _OUTPUT_GUARDRAIL_KEY)
    if step is not None:
        return _output_stage_branch(step, escalation_branch="E2"), step

    # E7 comes AFTER the output-stage guardrail checks, not before. A tool
    # call can error out mid-conversation (a typo'd transaction_id, a
    # transient NO_DATA) with a message that happens to mention "cs" without
    # that being the real reason -- ticket 7103046 called
    # get_transaction_processing_engine_data twice: the first call had a
    # malformed id and got "Hãy thông báo cho cs để xử lý trường hợp này",
    # but the agent immediately retried with the correct id, got real data,
    # drafted a full answer, and THAT got blocked by skill_guardrail_checked
    # with a real cs_escalation reason. E7 must only win when there is no
    # later guardrail block to explain instead -- i.e. the agent actually
    # gave up right after the tool's own escalate instruction.
    step = _e7_tool_step(turn)
    if step is not None:
        return "E7", step

    # No guardrail blocked at all -- but every guardrail-block source that
    # compute_verdict()/chuyen_cs can come from is already exhausted above,
    # so `verdict == "chuyen_cs"` can never reach this line. general_response
    # (agent used no skill and gave a generic reply) is the one signal left
    # that a ticket still needs an E6 explanation despite no guard firing.
    if any(s.key == _GENERAL_RESPONSE_KEY for s in turn.steps):
        return "E6", None
    if turn.verdict == "chuyen_cs":
        return "E6", None
    return "NONE", None


def _classify_single_turn(turn: TraceTurn) -> str:
    return _decisive_step_and_branch(turn)[0]


def classify_branch(turns: Sequence[TraceTurn]) -> tuple[str, int | None]:
    """Return (escalation_class, escalated_turn). Session-scoped, not turn-scoped.

    escalation_history_guard only ever says "already escalated last turn" --
    the real reason lives earlier, so E4 walks backward to find it.
    """

    if not turns:
        return "NONE", None

    last = turns[-1]
    branch = _classify_single_turn(last)

    if branch == "E4":
        for turn in reversed(turns[:-1]):
            prior = _classify_single_turn(turn)
            if prior not in ("NONE", "E4", "E5"):
                return prior, turn.turn
        return "E4", last.turn

    if branch == "NONE":
        return "NONE", None
    return branch, last.turn


# --------------------------------------------------------------------------
# Evidence extraction for the escalating turn
# --------------------------------------------------------------------------


def _sub_skills_read(turn: TraceTurn) -> tuple[tuple[str, str], ...]:
    """Return (skill, filename) pairs, in read order, deduplicated."""

    seen: list[tuple[str, str]] = []
    for step in turn.steps:
        if not step.key.startswith(_LOAD_SKILL_PREFIX):
            continue
        skill = step.key[len(_LOAD_SKILL_PREFIX):]
        input_ = step.evidence.get("input")
        inner = input_.get("input") if isinstance(input_, Mapping) else None
        filename = inner.get("filename") if isinstance(inner, Mapping) else None
        if isinstance(filename, str) and filename:
            pair = (skill, filename)
            if pair not in seen:
                seen.append(pair)
    return tuple(seen)


def _tool_evidence(turn: TraceTurn, config: ExplainConfig) -> tuple[ToolEvidence, ...]:
    items: list[ToolEvidence] = []
    for step in turn.steps:
        if not step.key.startswith(_TOOL_PREFIX):
            continue
        if step.key.startswith(_LOAD_SKILL_PREFIX) or step.key.startswith(_LIST_SKILL_PREFIX):
            continue
        output = step.evidence.get("output")
        result = output.get("result") if isinstance(output, Mapping) else output
        nhan, value, failed = explain_context.humanize_tool(config, step.key, result)
        items.append(ToolEvidence(step_key=step.key, label=nhan, value=value, turn=turn.turn, failed=failed))
    return tuple(items)


def _guardrail_reason_and_rule(turn: TraceTurn) -> tuple[str | None, str | None]:
    """(metadata.reason free text, rule name) of the exact step that decided
    the branch. `reason` backs the drawer's evidence when present; `rule`
    lets a template fallback (spec 17.6/17.9) pick the right canned sentence
    even when the guardrail never set a `reason` (true for most rules other
    than `cs_escalation`)."""

    branch, step = _decisive_step_and_branch(turn)
    if branch == "E7":
        if step is not None:
            output = step.evidence.get("output")
            result = output.get("result") if isinstance(output, Mapping) else None
            message = result.get("message") if isinstance(result, Mapping) else None
            if isinstance(message, str) and message:
                return message, None
        return None, None
    if step is None:
        return None, None
    metadata = step.evidence.get("metadata")
    reason = metadata.get("reason") if isinstance(metadata, Mapping) else None
    reason = reason if isinstance(reason, str) and reason else None
    return reason, _rule_of(step)


def _rule_candidates_for_branch(
    branch: str,
    turn: TraceTurn,
    rules: Mapping[str, list[RuleCandidate]],
    sub_skills: Sequence[tuple[str, str]],
) -> list[RuleCandidate]:
    candidates: list[RuleCandidate] = []

    for skill, filename in sub_skills:
        file_label = Path(filename).stem
        for candidate in rules.get(_snapshot_skill_key(skill), ()):
            if candidate.source == "sub_skill" and candidate.file_label == file_label:
                candidates.append(candidate)

    for skill in turn.skills_used:
        for candidate in rules.get(_snapshot_skill_key(skill), ()):
            if candidate.source == "skill_md":
                candidates.append(candidate)

    if branch == "E7":
        step = _e7_tool_step(turn)
        if step is not None:
            output = step.evidence.get("output")
            result = output.get("result") if isinstance(output, Mapping) else None
            message = result.get("message") if isinstance(result, Mapping) else None
            if isinstance(message, str) and message:
                tool_skill = turn.skills_used[0] if turn.skills_used else "khong_xac_dinh"
                candidates.append(
                    RuleCandidate(
                        anchor=step.key,
                        skill=tool_skill,
                        file_label=step.key,
                        case_id=None,
                        case_title="Công cụ báo lỗi và yêu cầu chuyển CSKH",
                        body=message,
                        source="tool_message",
                    )
                )

    if len(candidates) > _CANDIDATE_CAP:
        dropped = len(candidates) - _CANDIDATE_CAP
        _LOG.warning(
            "escalation_dossier: dropping %d rule candidates past the %d cap",
            dropped,
            _CANDIDATE_CAP,
        )
        candidates = candidates[:_CANDIDATE_CAP]
    return candidates


def rank_candidates(
    candidates: Sequence[RuleCandidate],
    *,
    tools_called: Sequence[str] = (),
    known_values: Sequence[str] = (),
    limit: int = 8,
) -> list[RuleCandidate]:
    """Deterministic score, highest first; cap at `limit`, log what got cut."""

    lowered_tools = [t.lower() for t in tools_called if t]
    lowered_values = [v.lower() for v in known_values if v]

    def score(candidate: RuleCandidate) -> int:
        body_lower = candidate.body.lower()
        points = 100 if candidate.source == "sub_skill" else 0
        points += 30 * sum(1 for tool in lowered_tools if tool in body_lower)
        points += 20 * sum(1 for value in lowered_values if value in body_lower)
        if _ESCALATE_PHRASE_RE.search(candidate.body):
            points += 10
        if candidate.source == "skill_md":
            points -= 5
        return points

    ordered = sorted(candidates, key=score, reverse=True)
    if len(ordered) > limit:
        dropped = len(ordered) - limit
        _LOG.warning("rank_candidates: dropping %d candidates past limit=%d", dropped, limit)
    return ordered[:limit]


# --------------------------------------------------------------------------
# Coverage (App -> expected skill vs. loaded skill)
# --------------------------------------------------------------------------


def _build_coverage(turn: TraceTurn, config: ExplainConfig, app_id: str | None) -> CoverageCheck:
    expected_skill = explain_context.skill_for_app(config, app_id)
    loaded = tuple(turn.skills_used)
    mismatch = (not loaded) or (expected_skill is not None and expected_skill not in loaded)
    return CoverageCheck(
        app_id=app_id, expected_skill=expected_skill, loaded_skills=loaded, mismatch=mismatch
    )


# --------------------------------------------------------------------------
# Timeline (spec section 6) -- applies to every ticket with a trace
# --------------------------------------------------------------------------

_TIEP_NHAN_KEYS = (_IDEMPOTENCY_KEY, _ESCALATION_HISTORY_KEY, _INPUT_GUARDRAIL_KEY)
_NHAN_DIEN_KEYS = ("route", "plan", "skills_loaded", _GENERAL_RESPONSE_KEY)
_KET_QUA_KEYS = (_SKILL_GUARDRAIL_KEY, _OUTPUT_GUARDRAIL_KEY)

_PHASE_TITLES = {
    "tiep_nhan": "Tiếp nhận câu hỏi",
    "nhan_dien": "Nhận diện vấn đề",
    "doc_quy_dinh": "Đọc quy định",
    "tra_du_lieu": "Tra dữ liệu",
}
_VERDICT_KET_QUA_TITLE = {
    "chuyen_cs": "QUYẾT ĐỊNH",
    "tra_loi": "TRẢ LỜI KHÁCH",
    "khong_tra_loi": "KHÔNG TRẢ LỜI",
}


def _phase_key_for_step(step: TraceStep) -> str:
    if step.key in _TIEP_NHAN_KEYS:
        return "tiep_nhan"
    if step.key in _NHAN_DIEN_KEYS:
        return "nhan_dien"
    if step.key in _KET_QUA_KEYS:
        return "ket_qua"
    if step.key.startswith(_LOAD_SKILL_PREFIX) or step.key.startswith(_LIST_SKILL_PREFIX):
        return "doc_quy_dinh"
    # Unmapped spans must stay visible -- fall into tra_du_lieu, never dropped.
    return "tra_du_lieu"


def _row_for_step(step: TraceStep, config: ExplainConfig) -> TimelineRow:
    if step.key.startswith(_TOOL_PREFIX):
        output = step.evidence.get("output")
        result = output.get("result") if isinstance(output, Mapping) else output
        nhan, value, _failed = explain_context.humanize_tool(config, step.key, result)
        return TimelineRow(label=nhan, value=value, evidence=step.evidence)

    if step.key == _IDEMPOTENCY_KEY:
        value = "Đã xử lý trước đó" if step.outcome == "chan" else "Chưa xử lý trước đó"
        return TimelineRow(label="Kiểm tra trùng lặp", value=value, evidence=step.evidence)
    if step.key == _ESCALATION_HISTORY_KEY:
        value = "Đã chuyển CS trước đó" if step.outcome == "chan" else "Chưa chuyển CS"
        return TimelineRow(label="Kiểm tra lịch sử chuyển CS", value=value, evidence=step.evidence)
    if step.key == _INPUT_GUARDRAIL_KEY:
        value = "Không hợp lệ" if step.outcome == "chan" else "Hợp lệ"
        return TimelineRow(label="Kiểm tra câu hỏi", value=value, evidence=step.evidence)
    if step.key == _OUTPUT_GUARDRAIL_KEY:
        value = "Không đạt" if step.outcome == "chan" else "Đạt"
        return TimelineRow(label="Kiểm tra câu trả lời", value=value, evidence=step.evidence)
    if step.key == _SKILL_GUARDRAIL_KEY:
        value = "Không đạt" if step.outcome == "chan" else "Đạt"
        return TimelineRow(label="Kiểm tra skill phù hợp", value=value, evidence=step.evidence)
    if step.key == "route":
        return TimelineRow(label="Chọn nhóm nghiệp vụ", value="Đã chọn", evidence=step.evidence)
    if step.key == "plan":
        return TimelineRow(label="Lập kế hoạch", value="Đã lập", evidence=step.evidence)
    if step.key == "skills_loaded":
        return TimelineRow(label="Nạp danh sách skill", value="Đã nạp", evidence=step.evidence)
    if step.key == _GENERAL_RESPONSE_KEY:
        return TimelineRow(label="Trả lời chung", value="Không dùng skill nào", evidence=step.evidence)

    return TimelineRow(label=step.key, value="—", evidence=step.evidence)


def build_phases(turn: TraceTurn, config: ExplainConfig) -> list[TimelinePhase]:
    grouped: dict[str, list[TraceStep]] = {
        "tiep_nhan": [],
        "nhan_dien": [],
        "doc_quy_dinh": [],
        "tra_du_lieu": [],
        "ket_qua": [],
    }
    for step in turn.steps:
        grouped[_phase_key_for_step(step)].append(step)

    tiep_nhan_blocked = any(s.outcome == "chan" for s in grouped["tiep_nhan"])
    decision_key = "tiep_nhan" if tiep_nhan_blocked else "ket_qua"

    phases: list[TimelinePhase] = []
    for key in ("tiep_nhan", "nhan_dien", "doc_quy_dinh", "tra_du_lieu", "ket_qua"):
        steps = grouped[key]
        rows = tuple(_row_for_step(step, config) for step in steps)
        title = (
            _VERDICT_KET_QUA_TITLE.get(turn.verdict, "Kết quả")
            if key == "ket_qua"
            else _PHASE_TITLES[key]
        )

        if key == decision_key:
            state = "quyet_dinh"
            collapsed = False
        elif key == "tra_du_lieu":
            state = "thong_tin" if rows else "dat"
            collapsed = not bool(rows)
        elif any(s.outcome == "chan" for s in steps):
            state = "chan"
            collapsed = False
        else:
            state = "dat"
            collapsed = True

        if not rows:
            summary = "Không có bước nào"
        elif collapsed:
            summary = f"{len(rows)} bước kiểm tra · đạt"
        else:
            summary = ""

        phases.append(
            TimelinePhase(
                key=key, title=title, summary=summary, rows=rows, state=state, collapsed=collapsed
            )
        )
    return phases


# --------------------------------------------------------------------------
# Drift check (spec 5.6) -- optional, defaults to "no drift detected"
# --------------------------------------------------------------------------


def _drift_changed(
    sub_skills: Sequence[tuple[str, str]], turn: TraceTurn, snapshot_root: Path | None
) -> bool:
    if snapshot_root is None or not sub_skills:
        return False
    for step in turn.steps:
        if not step.key.startswith(_LOAD_SKILL_PREFIX):
            continue
        skill = step.key[len(_LOAD_SKILL_PREFIX):]
        input_ = step.evidence.get("input")
        inner = input_.get("input") if isinstance(input_, Mapping) else None
        filename = inner.get("filename") if isinstance(inner, Mapping) else None
        output = step.evidence.get("output")
        result = output.get("result") if isinstance(output, Mapping) else None
        content = result.get("content") if isinstance(result, Mapping) else None
        if not (isinstance(filename, str) and isinstance(content, str)):
            continue
        snapshot_file = snapshot_root / skill / "references" / filename
        if not snapshot_file.is_file():
            continue
        if snapshot_file.read_text(encoding="utf-8") != content:
            return True
    return False


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


_RESPONSE_DRAFT_BRANCHES = frozenset({"E1", "E2", "E8", "E9"})


def _trace_meta(raw_trace: Mapping[str, object] | None) -> Mapping[str, object]:
    if raw_trace is None:
        return {}
    input_data = raw_trace.get("input")
    other_info = input_data.get("other_info") if isinstance(input_data, Mapping) else None
    meta = other_info.get("meta") if isinstance(other_info, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def _trace_title(raw_trace: Mapping[str, object] | None) -> str:
    if raw_trace is None:
        return ""
    input_data = raw_trace.get("input")
    other_info = input_data.get("other_info") if isinstance(input_data, Mapping) else None
    title = other_info.get("title") if isinstance(other_info, Mapping) else None
    return title if isinstance(title, str) else ""


def build_dossier(
    client: LangfuseClient,
    ticket_id: str,
    taxonomy: Taxonomy,
    config: ExplainConfig,
    rules: Mapping[str, list[RuleCandidate]],
    *,
    snapshot_root: Path | None = None,
) -> EscalationDossier | None:
    turns = fetch_trace_turns(client, ticket_id, taxonomy)
    if not turns:
        return None

    branch, escalated_turn = classify_branch(turns)
    target_turn = next((t for t in turns if t.turn == escalated_turn), turns[-1])
    last_turn = turns[-1]

    sub_skills = _sub_skills_read(target_turn)
    raw_trace = next(
        (t for t in client.list_traces_by_session(ticket_id) if t.get("id") == target_turn.trace_id),
        None,
    )
    meta = _trace_meta(raw_trace)
    title = _trace_title(raw_trace)
    raw_app = meta.get("App")
    app_id = str(raw_app) if isinstance(raw_app, (str, int)) and str(raw_app).strip() else None

    reason, rule = _guardrail_reason_and_rule(target_turn) if branch != "NONE" else (None, None)

    blocked_response_draft: str | None = None
    blocked_input_message: str | None = None
    if branch in _RESPONSE_DRAFT_BRANCHES and target_turn.last_llm_call_text:
        blocked_response_draft = explain_context.mask_free_text(target_turn.last_llm_call_text)
    elif branch == "E3" and target_turn.user_input:
        blocked_input_message = explain_context.mask_free_text(target_turn.user_input)

    return EscalationDossier(
        ticket_id=ticket_id,
        escalation_class=branch,
        escalated_turn=escalated_turn,
        guardrail_reason=reason,
        blocking_rule=rule,
        skills_loaded=tuple(target_turn.skills_used),
        sub_skills_read=tuple(filename for _skill, filename in sub_skills),
        tool_evidence=_tool_evidence(target_turn, config),
        ticket_facts=tuple(explain_context.build_ticket_facts(config, meta, title)),
        rule_candidates=tuple(_rule_candidates_for_branch(branch, target_turn, rules, sub_skills)),
        coverage=_build_coverage(target_turn, config, app_id),
        turn_deltas=(),
        drift_changed=_drift_changed(sub_skills, target_turn, snapshot_root),
        phases=tuple(build_phases(last_turn, config)),
        blocked_response_draft=blocked_response_draft,
        blocked_input_message=blocked_input_message,
    )
