from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence
from unicodedata import combining, decimal, normalize

from .models import CategoryResult, TicketDimensions, TraceRecord, TransferCategories


@dataclass(frozen=True)
class Taxonomy:
    version: str
    transfer_text: str
    transfer_texts: tuple[str, ...]
    business_precedence: tuple[str, ...]
    business_meta_keys: frozenset[str]
    business_patterns: dict[str, tuple[str, ...]]
    business_fallback: str
    max_meta_depth: int
    tpe_tool_names: frozenset[str]
    tpe_mappings: tuple[Mapping[str, object], ...]
    guardrail_blocked_fields: frozenset[str]
    guardrail_passed_field: str
    guardrail_value_fields: tuple[str, ...]
    guardrail_allowed_values: tuple[str, ...]
    dimension_paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    dimension_fallbacks: Mapping[str, str] = field(default_factory=dict)
    tpe_code_meta_key: str | None = None
    tpe_step_meta_key: str | None = None
    tpe_step_pipe_index: int | None = None
    tpe_unmapped_policy: str | None = None
    guardrail_compliant_values: tuple[str, ...] = ()
    skills_prefix_strip: str | None = None
    intent_min_occurrences: int | None = None
    intent_pattern: str | None = None
    intent_other_label: str | None = None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _required_mapping(value: object, field: str) -> Mapping[str, object]:
    result = _mapping(value)
    if result is None:
        raise ValueError(f"taxonomy {field} must be an object")
    return result


def _required_string(value: object, field: str) -> str:
    result = _string(value)
    if result is None or not result.strip():
        raise ValueError(f"taxonomy {field} must be a non-empty string")
    return result


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"taxonomy {field} must be a list of non-empty strings")
    return tuple(value)


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"taxonomy {field} has unsupported or missing fields")


def _load_v1_taxonomy(root: Mapping[str, object]) -> Taxonomy:
    transfer = _required_mapping(root.get("transfer"), "transfer")
    business = _required_mapping(root.get("business"), "business")
    tpe = _required_mapping(root.get("tpe"), "tpe")
    guardrail = _required_mapping(root.get("guardrail"), "guardrail")

    precedence = _string_list(business.get("precedence"), "business.precedence")
    meta_keys = _string_list(business.get("meta_keys"), "business.meta_keys")
    raw_patterns = _required_mapping(business.get("patterns"), "business.patterns")
    patterns = {key: _string_list(value, f"business.patterns.{key}") for key, value in raw_patterns.items() if isinstance(key, str)}
    if set(patterns) != set(precedence):
        raise ValueError("taxonomy business patterns must match precedence")
    max_meta_depth = business.get("max_meta_depth")
    if isinstance(max_meta_depth, bool) or not isinstance(max_meta_depth, int) or max_meta_depth < 1:
        raise ValueError("taxonomy business.max_meta_depth must be a positive integer")

    raw_mappings = tpe.get("mappings")
    if not isinstance(raw_mappings, list):
        raise ValueError("taxonomy tpe.mappings must be a list")
    mappings: list[dict[str, object]] = []
    for index, raw_mapping in enumerate(raw_mappings):
        item = _required_mapping(raw_mapping, f"tpe.mappings[{index}]")
        if set(item) != {"code", "step", "case", "status"}:
            raise ValueError("taxonomy TPE mapping has unsupported fields")
        code = _required_string(item.get("code"), f"tpe.mappings[{index}].code")
        step = item.get("step")
        if step is not None and not isinstance(step, str):
            raise ValueError("taxonomy TPE mapping step must be a string or null")
        case = item.get("case")
        if isinstance(case, bool) or not isinstance(case, int):
            raise ValueError("taxonomy TPE mapping case must be an integer")
        status = _required_string(item.get("status"), f"tpe.mappings[{index}].status")
        mappings.append({"code": code, "step": step, "case": case, "status": status})

    if set(guardrail) != {"blocked_fields", "passed_field", "value_fields", "allowed_values"}:
        raise ValueError("taxonomy guardrail has unsupported fields")
    _string_list(guardrail.get("blocked_fields"), "guardrail.blocked_fields")
    _required_string(guardrail.get("passed_field"), "guardrail.passed_field")
    _string_list(guardrail.get("value_fields"), "guardrail.value_fields")
    _string_list(guardrail.get("allowed_values"), "guardrail.allowed_values")

    transfer_text = _required_string(
        transfer.get("semantic_text"), "transfer.semantic_text"
    )
    return Taxonomy(
        version="v1",
        transfer_text=transfer_text,
        transfer_texts=(transfer_text,),
        business_precedence=precedence,
        business_meta_keys=frozenset(meta_keys),
        business_patterns=patterns,
        business_fallback=_required_string(business.get("fallback"), "business.fallback"),
        max_meta_depth=max_meta_depth,
        tpe_tool_names=frozenset(_string_list(tpe.get("tool_names"), "tpe.tool_names")),
        tpe_mappings=tuple(mappings),
        guardrail_blocked_fields=frozenset(
            _string_list(guardrail.get("blocked_fields"), "guardrail.blocked_fields")
        ),
        guardrail_passed_field=_required_string(
            guardrail.get("passed_field"), "guardrail.passed_field"
        ),
        guardrail_value_fields=_string_list(guardrail.get("value_fields"), "guardrail.value_fields"),
        guardrail_allowed_values=_string_list(
            guardrail.get("allowed_values"), "guardrail.allowed_values"
        ),
    )


_DIMENSION_PATHS = {
    "issue_category": ("Thông tin thêm", "category"),
    "app": ("App",),
    "product_code": ("Product Code",),
    "entry_point": ("Thông tin thêm", "sub_source"),
    "payment_channel": ("Kênh thanh toán",),
}
_NUMERIC_CODE = re.compile(r"^-?[0-9]{1,6}$")
_UNSIGNED_NUMERIC_CODE = re.compile(r"^[0-9]+$")
_VIETNAM_PHONE = re.compile(r"(?:0|84)[0-9]{8,10}")
_TPE_CODE_META_KEY = "Mã lỗi TPE"
_TPE_STEP_META_KEY = "Step result"
_TPE_STEP_PIPE_INDEX = 2


def _load_v2_taxonomy(root: Mapping[str, object]) -> Taxonomy:
    _exact_keys(
        root,
        {"version", "transfer", "dimensions", "tpe", "guardrail", "skills", "intent"},
        "root",
    )
    transfer = _required_mapping(root.get("transfer"), "transfer")
    _exact_keys(transfer, {"semantic_texts"}, "transfer")
    transfer_texts = _string_list(
        transfer.get("semantic_texts"), "transfer.semantic_texts"
    )
    if len(set(transfer_texts)) != len(transfer_texts):
        raise ValueError("taxonomy transfer.semantic_texts must not contain duplicates")

    dimensions = _required_mapping(root.get("dimensions"), "dimensions")
    _exact_keys(dimensions, set(_DIMENSION_PATHS), "dimensions")
    dimension_paths: dict[str, tuple[str, ...]] = {}
    dimension_fallbacks: dict[str, str] = {}
    for name in sorted(_DIMENSION_PATHS):
        definition = _required_mapping(dimensions.get(name), f"dimensions.{name}")
        _exact_keys(definition, {"meta_path", "fallback"}, f"dimensions.{name}")
        path = _string_list(definition.get("meta_path"), f"dimensions.{name}.meta_path")
        if path != _DIMENSION_PATHS[name]:
            raise ValueError(f"taxonomy dimensions.{name}.meta_path is not allowed")
        dimension_paths[name] = path
        dimension_fallbacks[name] = _required_string(
            definition.get("fallback"), f"dimensions.{name}.fallback"
        )

    tpe = _required_mapping(root.get("tpe"), "tpe")
    _exact_keys(
        tpe,
        {
            "code_meta_key",
            "step_meta_key",
            "step_pipe_index",
            "unmapped_policy",
            "mappings",
        },
        "tpe",
    )
    step_pipe_index = tpe.get("step_pipe_index")
    if type(step_pipe_index) is not int or step_pipe_index != _TPE_STEP_PIPE_INDEX:
        raise ValueError(f"taxonomy tpe.step_pipe_index must be {_TPE_STEP_PIPE_INDEX}")
    code_meta_key = _required_string(tpe.get("code_meta_key"), "tpe.code_meta_key")
    if code_meta_key != _TPE_CODE_META_KEY:
        raise ValueError(f"taxonomy tpe.code_meta_key must be {_TPE_CODE_META_KEY}")
    step_meta_key = _required_string(tpe.get("step_meta_key"), "tpe.step_meta_key")
    if step_meta_key != _TPE_STEP_META_KEY:
        raise ValueError(f"taxonomy tpe.step_meta_key must be {_TPE_STEP_META_KEY}")
    unmapped_policy = _required_string(tpe.get("unmapped_policy"), "tpe.unmapped_policy")
    if unmapped_policy != "passthrough":
        raise ValueError("taxonomy tpe.unmapped_policy must be passthrough")
    raw_mappings = tpe.get("mappings")
    if not isinstance(raw_mappings, list):
        raise ValueError("taxonomy tpe.mappings must be a list")
    mappings: list[Mapping[str, object]] = []
    seen_code_steps: set[tuple[str, str]] = set()
    wildcard_codes: set[str] = set()
    for index, raw_mapping in enumerate(raw_mappings):
        item = _required_mapping(raw_mapping, f"tpe.mappings[{index}]")
        _exact_keys(item, {"code", "steps", "case", "status"}, f"tpe.mappings[{index}]")
        code = _required_string(item.get("code"), f"tpe.mappings[{index}].code")
        if _NUMERIC_CODE.fullmatch(code) is None:
            raise ValueError(f"taxonomy tpe.mappings[{index}].code must be numeric")
        steps = _string_list(item.get("steps"), f"tpe.mappings[{index}].steps")
        if any(_NUMERIC_CODE.fullmatch(step) is None for step in steps):
            raise ValueError(f"taxonomy tpe.mappings[{index}].steps must be numeric")
        if not steps:
            if code in wildcard_codes:
                raise ValueError(f"taxonomy TPE mapping has duplicate wildcard for {code}")
            wildcard_codes.add(code)
        for step in steps:
            code_step = (code, step)
            if code_step in seen_code_steps:
                raise ValueError(f"taxonomy TPE mapping duplicates {code}/{step}")
            seen_code_steps.add(code_step)
        case = item.get("case")
        if isinstance(case, bool) or not isinstance(case, int):
            raise ValueError("taxonomy TPE mapping case must be an integer")
        mappings.append(
            MappingProxyType(
                {
                    "code": code,
                    "steps": steps,
                    "case": case,
                    "status": _required_string(
                        item.get("status"), f"tpe.mappings[{index}].status"
                    ),
                }
            )
        )

    guardrail = _required_mapping(root.get("guardrail"), "guardrail")
    _exact_keys(
        guardrail,
        {
            "blocked_fields",
            "passed_field",
            "value_fields",
            "violation_rules",
            "compliant_rules",
        },
        "guardrail",
    )
    blocked_fields = _string_list(guardrail.get("blocked_fields"), "guardrail.blocked_fields")
    passed_field = _required_string(guardrail.get("passed_field"), "guardrail.passed_field")
    value_fields = _string_list(guardrail.get("value_fields"), "guardrail.value_fields")
    violation_rules = _string_list(
        guardrail.get("violation_rules"), "guardrail.violation_rules"
    )
    compliant_rules = _string_list(
        guardrail.get("compliant_rules"), "guardrail.compliant_rules"
    )
    if set(violation_rules) & set(compliant_rules):
        raise ValueError("taxonomy guardrail violation and compliant rules must not overlap")

    skills = _required_mapping(root.get("skills"), "skills")
    _exact_keys(skills, {"prefix_strip"}, "skills")
    prefix_strip = _required_string(skills.get("prefix_strip"), "skills.prefix_strip")

    intent = _required_mapping(root.get("intent"), "intent")
    _exact_keys(intent, {"min_occurrences", "pattern", "other_label"}, "intent")
    min_occurrences = intent.get("min_occurrences")
    if (
        isinstance(min_occurrences, bool)
        or not isinstance(min_occurrences, int)
        or min_occurrences < 1
    ):
        raise ValueError("taxonomy intent.min_occurrences must be a positive integer")
    intent_pattern = _required_string(intent.get("pattern"), "intent.pattern")
    try:
        re.compile(intent_pattern)
    except re.error as error:
        raise ValueError("taxonomy intent.pattern must be a valid regular expression") from error

    return Taxonomy(
        version="v2",
        transfer_text=transfer_texts[0],
        transfer_texts=transfer_texts,
        business_precedence=(),
        business_meta_keys=frozenset(),
        business_patterns={},
        business_fallback="other",
        max_meta_depth=1,
        tpe_tool_names=frozenset(),
        tpe_mappings=tuple(mappings),
        guardrail_blocked_fields=frozenset(blocked_fields),
        guardrail_passed_field=passed_field,
        guardrail_value_fields=value_fields,
        guardrail_allowed_values=violation_rules,
        dimension_paths=MappingProxyType(dimension_paths),
        dimension_fallbacks=MappingProxyType(dimension_fallbacks),
        tpe_code_meta_key=code_meta_key,
        tpe_step_meta_key=step_meta_key,
        tpe_step_pipe_index=step_pipe_index,
        tpe_unmapped_policy=unmapped_policy,
        guardrail_compliant_values=compliant_rules,
        skills_prefix_strip=prefix_strip,
        intent_min_occurrences=min_occurrences,
        intent_pattern=intent_pattern,
        intent_other_label=_required_string(intent.get("other_label"), "intent.other_label"),
    )


def load_taxonomy(path: Path) -> Taxonomy:
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    root = _required_mapping(raw, "root")
    version = _required_string(root.get("version"), "version")
    if version == "v1":
        return _load_v1_taxonomy(root)
    if version == "v2":
        return _load_v2_taxonomy(root)
    raise ValueError(f"unsupported taxonomy version: {version}")


def _normalized(value: str) -> str:
    decomposed = normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if not combining(character))


def _trace_meta(first_trace: TraceRecord) -> Mapping[str, object]:
    input_data = _mapping(first_trace.input_data)
    other_info = _mapping(input_data.get("other_info")) if input_data is not None else None
    meta = _mapping(other_info.get("meta")) if other_info is not None else None
    return meta if meta is not None else {}


def _dimension_value(meta: Mapping[str, object], name: str, taxonomy: Taxonomy) -> str:
    value: object = meta
    for key in taxonomy.dimension_paths[name]:
        container = _mapping(value)
        if container is None:
            return taxonomy.dimension_fallbacks[name]
        value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        return taxonomy.dimension_fallbacks[name]
    return value


def _app_code(value: str) -> int | None:
    token = value.split(maxsplit=1)[0] if value.split() else ""
    return int(token) if _UNSIGNED_NUMERIC_CODE.fullmatch(token) is not None else None


def _contains_vietnam_phone(value: str) -> bool:
    digits: list[str] = []
    for character in normalize("NFKC", value):
        try:
            digit = decimal(character)
        except ValueError:
            continue
        digits.append(str(digit))
    return _VIETNAM_PHONE.search("".join(digits)) is not None


def _parse_tpe(
    meta: Mapping[str, object], taxonomy: Taxonomy
) -> tuple[str | None, str | None, str | None]:
    """Keep only the legacy meta code/status used by private backfill tools.

    ``meta["Step result"]`` is a pipe-encoded support field, not the
    transaction-processing-engine ``stepresult`` contract. It must never be
    interpreted as a dashboard Step result.
    """
    raw_value = meta.get(taxonomy.tpe_code_meta_key)
    if not isinstance(raw_value, str):
        return None, None, None
    value = raw_value.strip()
    if not value:
        return None, None, None
    if _contains_vietnam_phone(value):
        return None, None, None
    code_and_status = value.split(maxsplit=1)
    code = code_and_status[0]
    if _NUMERIC_CODE.fullmatch(code) is None:
        return None, None, None
    status_raw = code_and_status[1].strip() if len(code_and_status) == 2 else None
    if not status_raw:
        status_raw = None
    return code, status_raw, None


def _model_core(first_trace: TraceRecord) -> str | None:
    """The A/B arm this ticket ran on, straight from the root trace input.

    Unlike the taxonomy-mapped dimensions above, this is a direct pass-through
    -- older tickets predate the field and legitimately have none, projected
    downstream as null (rendered "--" like any other absent dimension).
    """
    input_data = _mapping(first_trace.input_data)
    model_info = _mapping(input_data.get("model_info")) if input_data is not None else None
    model_core = model_info.get("model_core") if model_info is not None else None
    return _string(model_core)


def extract_dimensions(first_trace: TraceRecord, taxonomy: Taxonomy) -> TicketDimensions:
    if taxonomy.version != "v2":
        raise ValueError("extract_dimensions requires taxonomy v2")
    meta = _trace_meta(first_trace)
    issue_category = _dimension_value(meta, "issue_category", taxonomy)
    app = _dimension_value(meta, "app", taxonomy)
    product_code = _dimension_value(meta, "product_code", taxonomy)
    entry_point = _dimension_value(meta, "entry_point", taxonomy)
    payment_channel = _dimension_value(meta, "payment_channel", taxonomy)

    tpe_code, tpe_status_raw, _legacy_step = _parse_tpe(meta, taxonomy)
    return TicketDimensions(
        issue_category=issue_category,
        app=app,
        app_code=_app_code(app),
        product_code=product_code,
        entry_point=entry_point,
        payment_channel=payment_channel,
        tpe_code=tpe_code,
        tpe_status_raw=tpe_status_raw,
        tpe_status_canonical=None,
        tpe_step=None,
        tpe_case=None,
        skill=None,
        intent=None,
        guardrail_rule=None,
        escalation_guard_blocked=False,
        tpe_signals=(),
        model_core=_model_core(first_trace),
    )


def _business_matches(value: str, taxonomy: Taxonomy) -> set[str]:
    normalized = _normalized(value)
    return {
        category
        for category in taxonomy.business_precedence
        if any(_normalized(pattern) in normalized for pattern in taxonomy.business_patterns[category])
    }


def _allowed_meta_values(
    meta: Mapping[str, object], taxonomy: Taxonomy, depth: int = 1
) -> list[tuple[str, str]]:
    if depth > taxonomy.max_meta_depth:
        return []
    values: list[tuple[str, str]] = []
    for key, value in meta.items():
        if not isinstance(key, str):
            continue
        if key in taxonomy.business_meta_keys and isinstance(value, str):
            values.append((f"meta.{key}", value))
        nested = _mapping(value)
        if nested is not None:
            values.extend(_allowed_meta_values(nested, taxonomy, depth + 1))
    return values


def _category_result(matches: set[str], ordered: Sequence[str], source_fields: list[str], fallback: str) -> CategoryResult:
    values = tuple(category for category in ordered if category in matches)
    if not values:
        return CategoryResult(fallback)
    if len(values) == 1:
        return CategoryResult(values[0], values, tuple(source_fields))
    return CategoryResult("multiple", values, tuple(source_fields))


def classify_business(turn0_input: object, taxonomy: Taxonomy) -> CategoryResult:
    input_data = _mapping(turn0_input)
    other_info = _mapping(input_data.get("other_info")) if input_data is not None else None
    if other_info is None:
        return CategoryResult("unknown")
    candidates: list[tuple[str, str]] = []
    title = _string(other_info.get("title"))
    if title is not None:
        candidates.append(("title", title))
    meta = _mapping(other_info.get("meta"))
    if title is None and meta is None:
        return CategoryResult("unknown")
    if meta is not None:
        candidates.extend(_allowed_meta_values(meta, taxonomy))

    matches: set[str] = set()
    sources: list[str] = []
    for field, value in candidates:
        found = _business_matches(value, taxonomy)
        if found:
            matches.update(found)
            sources.append(field)
    return _category_result(matches, taxonomy.business_precedence, sources, taxonomy.business_fallback)


def _tpe_mapping(code: str, step: str | None, taxonomy: Taxonomy) -> dict[str, object] | None:
    for mapping in taxonomy.tpe_mappings:
        if mapping["code"] == code and mapping["step"] == step:
            return mapping
    return next(
        (mapping for mapping in taxonomy.tpe_mappings if mapping["code"] == code and mapping["step"] is None),
        None,
    )


def _tpe_scalar(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        return str(value)
    return None


def _is_tpe_observation(observation: Mapping[str, object], taxonomy: Taxonomy) -> bool:
    metadata = _mapping(observation.get("metadata"))
    tool_name = _string(metadata.get("tool_name")) if metadata is not None else None
    return (
        tool_name in taxonomy.tpe_tool_names
        or observation.get("name") == "tool:get_transaction_processing_engine_data"
    )


def classify_tpe(observations: Sequence[dict], taxonomy: Taxonomy) -> CategoryResult:
    matched: list[tuple[dict[str, object], tuple[str, str | None]]] = []
    sources: list[str] = []
    for observation in observations:
        if not _is_tpe_observation(observation, taxonomy):
            continue
        output = _mapping(observation.get("output"))
        result = _mapping(output.get("result")) if output is not None else None
        if result is None:
            continue
        code_field = "transstatus" if _tpe_scalar(result.get("transstatus")) is not None else "tpe_error_code"
        code = _tpe_scalar(result.get(code_field))
        step = _tpe_scalar(result.get("stepresult"))
        if code is None:
            continue
        mapping = _tpe_mapping(code, step, taxonomy)
        if mapping is None:
            continue
        mapped_result = (str(mapping["code"]), mapping["step"] if isinstance(mapping["step"], str) else None)
        if mapped_result not in [item[1] for item in matched]:
            matched.append((mapping, mapped_result))
        source = f"output.result.{code_field}"
        if source not in sources:
            sources.append(source)
        if step is not None and "output.result.stepresult" not in sources:
            sources.append("output.result.stepresult")
    if not matched:
        return CategoryResult("unknown")
    if len(matched) == 1:
        mapping, (_, mapped_step) = matched[0]
        raw_values = (str(mapping["code"]),)
        if mapped_step is not None:
            raw_values += (mapped_step,)
        return CategoryResult(str(mapping["case"]), raw_values, tuple(sources))
    return CategoryResult("multiple", tuple(item[1][0] for item in matched), tuple(sources))


def _guardrail_signal(observation: Mapping[str, object], taxonomy: Taxonomy) -> bool:
    metadata = _mapping(observation.get("metadata"))
    output = _mapping(observation.get("output"))
    for container in (metadata, output):
        if container is None:
            continue
        if container.get(taxonomy.guardrail_passed_field) is False:
            return True
        for field in taxonomy.guardrail_blocked_fields:
            if field == "violation":
                if bool(container.get(field)):
                    return True
            elif container.get(field) is True:
                return True
    return False


def classify_guardrail(observations: Sequence[dict], taxonomy: Taxonomy) -> CategoryResult:
    rules: list[str] = []
    fields: list[str] = []
    for observation in observations:
        if not _guardrail_signal(observation, taxonomy):
            continue
        for container_name in ("metadata", "output"):
            container = _mapping(observation.get(container_name))
            if container is None:
                continue
            for key in taxonomy.guardrail_value_fields:
                value = _string(container.get(key))
                if (
                    value is not None
                    and value in taxonomy.guardrail_allowed_values
                    and value not in taxonomy.guardrail_compliant_values
                    and value not in rules
                ):
                    rules.append(value)
                    fields.append(f"{container_name}.{key}")
    if not rules:
        return CategoryResult("unknown")
    if len(rules) == 1:
        return CategoryResult(rules[0], tuple(rules), tuple(fields))
    return CategoryResult("multiple", tuple(rules), tuple(fields))


def classify_transfer(
    turn0: TraceRecord, observations: Sequence[dict], taxonomy: Taxonomy
) -> TransferCategories:
    return TransferCategories(
        business=classify_business(turn0.input_data, taxonomy),
        tpe=classify_tpe(observations, taxonomy),
        guardrail_rule=classify_guardrail(observations, taxonomy),
    )
