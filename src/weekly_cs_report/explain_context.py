"""Load explain_context.v1.json: App->skill->field policy and tool humanization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .categories import Taxonomy, load_taxonomy
from .tpe_status import resolve_tpe_status

_LONG_NUMERIC_RUN = re.compile(r"[0-9]{9,}")
_TOOL_PREFIX = "tool:"
# Real meta.App values are compound strings like "241 - Chuyển Tiền ATM", not
# the bare numeric id the config's `app` list stores -- pull the leading
# digits out before comparing.
_APP_ID_PREFIX_RE = re.compile(r"^\s*(\d+)")


@dataclass(frozen=True)
class TicketFact:
    label: str  # "Tên ngân hàng"
    value: str | None  # giá trị thật, hoặc None nếu là field định danh
    present: bool


@dataclass(frozen=True)
class SkillFieldConfig:
    app: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ToolLabelConfig:
    nhan: str
    duong_dan: tuple[str, ...]
    mau: str


@dataclass(frozen=True)
class ExplainConfig:
    version: int
    skills: Mapping[str, SkillFieldConfig]
    default_fields: tuple[str, ...]
    always_include: tuple[str, ...]
    field_policy_value: frozenset[str]
    field_policy_presence: frozenset[str]
    forbidden_words: tuple[str, ...]
    tool_labels: Mapping[str, ToolLabelConfig]
    taxonomy: Taxonomy


def load_explain_config(path: Path) -> ExplainConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    skills = {
        name: SkillFieldConfig(
            app=tuple(str(app_id) for app_id in definition["app"]),
            fields=tuple(definition["fields"]),
        )
        for name, definition in data["skills"].items()
    }
    tool_labels = {
        name: ToolLabelConfig(
            nhan=definition["nhan"],
            duong_dan=tuple(definition["duong_dan"]),
            mau=definition["mau"],
        )
        for name, definition in data["tool_labels"].items()
    }
    return ExplainConfig(
        version=data["version"],
        skills=skills,
        default_fields=tuple(data["default_fields"]),
        always_include=tuple(data["always_include"]),
        field_policy_value=frozenset(data["field_policy"]["value"]),
        field_policy_presence=frozenset(data["field_policy"]["presence"]),
        forbidden_words=tuple(data["forbidden_words"]),
        tool_labels=tool_labels,
        taxonomy=load_taxonomy(path.parent / "taxonomy.v2.json"),
    )


def skill_for_app(config: ExplainConfig, app_id: str | None) -> str | None:
    if not app_id:
        return None
    match = _APP_ID_PREFIX_RE.match(app_id)
    numeric_id = match.group(1) if match else None
    for skill, field_config in config.skills.items():
        if app_id in field_config.app or (numeric_id is not None and numeric_id in field_config.app):
            return skill
    return None


def mask_free_text(text: str) -> str:
    """Redact runs of >=9 digits, in the spirit of enrichment._LONG_NUMERIC_RUN."""

    return _LONG_NUMERIC_RUN.sub(lambda match: "*" * len(match.group(0)), text)


def build_ticket_facts(
    config: ExplainConfig, meta: Mapping[str, object], title: str
) -> list[TicketFact]:
    raw_app = meta.get("App")
    app_id = str(raw_app) if isinstance(raw_app, (str, int)) and str(raw_app).strip() else None
    skill = skill_for_app(config, app_id)
    field_names = list(config.skills[skill].fields) if skill else list(config.default_fields)
    for name in config.always_include:
        if name not in field_names:
            field_names.append(name)

    facts: list[TicketFact] = []
    for name in field_names:
        if name == "title":
            raw_value: object = title
        else:
            raw_value = meta.get(name)
        text_value = raw_value.strip() if isinstance(raw_value, str) else (
            str(raw_value) if raw_value is not None else None
        )
        present = bool(text_value)

        if name in config.field_policy_presence:
            facts.append(TicketFact(label=name, value=None, present=present))
            continue

        value = text_value if present else None
        # "title" is free text set by the customer/Freshdesk subject line,
        # same as "Mô tả" -- ticket 7090152 showed it can carry the raw
        # transaction id verbatim ("... Mã giao dịch: 260813002120041 ...").
        if name in ("Mô tả", "title") and value is not None:
            value = mask_free_text(value)
        facts.append(TicketFact(label=name, value=value, present=present))
    return facts


def _base_tool_name(step_key: str) -> str:
    name = step_key[len(_TOOL_PREFIX):] if step_key.startswith(_TOOL_PREFIX) else step_key
    return name.split("__", 1)[0] if "__" in name else name


def _is_error_envelope(result: object) -> bool:
    return isinstance(result, Mapping) and ("error" in result or "info" in result)


def humanize_tool(
    config: ExplainConfig, step_key: str, result: object
) -> tuple[str, str, bool]:
    """Return (nhan, value, failed) for one tool-call result envelope."""

    base_name = _base_tool_name(step_key)
    label_config = config.tool_labels.get(base_name)
    failed = _is_error_envelope(result)

    if label_config is None:
        return base_name, ("Không tra được dữ liệu" if failed else "đã tra cứu"), failed

    if failed:
        return label_config.nhan, "Không tra được dữ liệu", True

    if label_config.mau == "tpe":
        transstatus = result.get("transstatus") if isinstance(result, Mapping) else None
        step_result = result.get("step_result") if isinstance(result, Mapping) else None
        status = (
            resolve_tpe_status(transstatus, step_result, config.taxonomy)
            if isinstance(transstatus, str)
            else None
        )
        return label_config.nhan, status or "Không xác định", False

    if label_config.mau == "{len} kịch bản":
        items = result.get(label_config.duong_dan[0]) if isinstance(result, Mapping) else None
        length = len(items) if isinstance(items, (list, tuple)) else 0
        return label_config.nhan, label_config.mau.replace("{len}", str(length)), False

    raw_value = (
        result.get(label_config.duong_dan[0])
        if isinstance(result, Mapping) and label_config.duong_dan
        else None
    )
    if raw_value is None:
        return label_config.nhan, "Không tra được dữ liệu", True
    return label_config.nhan, label_config.mau.format(raw_value), False
