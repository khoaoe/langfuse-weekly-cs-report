from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Mapping, Sequence
from unicodedata import category, decimal, normalize

from .categories import Taxonomy, extract_dimensions
from .models import TraceRecord
from .pipeline import normalize_raw_traces

_SAFE_OPERATIONAL_STATUSES = frozenset(
    {
        "Thất bại",
        "Đang xử lý",
        "Bị từ chối",
    }
)
_SAFE_TPE_CODE = re.compile(r"^-?[0-9]{1,6}$")
_VIETNAM_PHONE = re.compile(r"(?:0|84)[0-9]{8,10}")
_UUID = re.compile(
    r"(?<![0-9a-f])"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![0-9a-f])",
    re.IGNORECASE,
)
_PRIVACY_VALIDATION_ERROR = (
    "dimension verification report failed privacy validation"
)
DIMENSION_REPORT_DENY_KEYS = frozenset(
    {
        "UserID",
        "App user",
        "Số điện thoại người dùng",
        "TransID",
        "AppTransId",
        "Mã giao dịch",
        "Zalopay chat keys",
        "System Info",
        "UserAgent",
        "Ghi chú",
        "Ghi chú bên thứ ba",
        "Mô tả",
        "Vấn đề",
        "Thông tin thêm",
        "title",
        "user_input",
        "comments",
        "Số tài khoản ngân hàng",
        "SĐT đăng ký NH",
        "Thời gian giao dịch",
        "Thời điểm giao dịch",
        "session_id",
        "trace_id",
        "sessionId",
        "traceId",
        "input",
        "output",
        "meta",
        "metadata",
        "raw payload",
        "raw_payload",
        "rawPayload",
        "payload",
        "prompt",
        "response",
        "id",
        "internal_id",
        "internal_ids",
        "langfuse_id",
        "observation_id",
        "observationId",
        "score_id",
        "scoreId",
        "project_id",
        "projectId",
        "description",
        "step_description",
        "tpe_status_raw",
        "user_id",
        "trans_id",
        "other_info",
    }
)


class DimensionReportPrivacyError(ValueError):
    pass


def _normalized_identifier_text(value: str) -> str:
    characters: list[str] = []
    for character in normalize("NFKC", value):
        character_category = category(character)
        if character_category == "Cf" or character_category.startswith("M"):
            continue
        try:
            characters.append(str(decimal(character)))
        except ValueError:
            characters.append(character)
    return "".join(characters)


def _contains_private_identifier(value: str) -> bool:
    normalized = _normalized_identifier_text(value)
    digits = "".join(character for character in normalized if character.isdigit())
    return (
        _VIETNAM_PHONE.search(digits) is not None
        or _UUID.search(normalized) is not None
    )


def validate_dimension_report_privacy(report: Mapping[str, object]) -> None:
    pending: list[object] = [report]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise DimensionReportPrivacyError(
                        _PRIVACY_VALIDATION_ERROR
                    )
                normalized_key = normalize("NFC", key)
                if (
                    normalized_key in DIMENSION_REPORT_DENY_KEYS
                    or _contains_private_identifier(normalized_key)
                ):
                    raise DimensionReportPrivacyError(
                        _PRIVACY_VALIDATION_ERROR
                    )
                pending.append(child)
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str):
            if _contains_private_identifier(value):
                raise DimensionReportPrivacyError(
                    _PRIVACY_VALIDATION_ERROR
                )
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise DimensionReportPrivacyError(_PRIVACY_VALIDATION_ERROR)


def is_ticket_trace(raw: Mapping[str, object]) -> bool:
    input_data = raw.get("input")
    return (
        isinstance(input_data, Mapping)
        and input_data.get("source") == "ticket"
    )


def raw_ticket_session_denominator(
    ticket_traces: Sequence[Mapping[str, object]],
) -> int:
    """Count raw ticket units before validation can discard malformed traces."""
    session_ids: set[str] = set()
    unkeyed_trace_count = 0
    for raw in ticket_traces:
        session_id = raw.get("sessionId")
        if isinstance(session_id, str) and session_id:
            session_ids.add(session_id)
        else:
            unkeyed_trace_count += 1
    return len(session_ids) + unkeyed_trace_count


def _raw_dimension_present(
    trace: TraceRecord,
    dimension_name: str,
    taxonomy: Taxonomy,
) -> bool:
    value: object = trace.input_data
    for key in ("other_info", "meta", *taxonomy.dimension_paths[dimension_name]):
        if not isinstance(value, Mapping):
            return False
        value = value.get(key)
    if not isinstance(value, str) or not value.strip():
        return False
    # ``Không xác định`` is the taxonomy's display fallback, not source
    # evidence.  Counting it as present would suppress the read-only
    # Freshdesk backfill and inflate coverage.
    return normalize("NFKC", value.strip()) != normalize(
        "NFKC", taxonomy.dimension_fallbacks[dimension_name]
    )


def _safe_status(value: str | None) -> str | None:
    return value if value in _SAFE_OPERATIONAL_STATUSES else None


def _safe_tpe_code(value: str) -> str | None:
    return value if _SAFE_TPE_CODE.fullmatch(value) is not None else None


def _contains_vietnam_phone(
    code: str,
    status_raw: str | None,
) -> bool:
    reconstructed = (
        f"{code} {status_raw}"
        if status_raw is not None
        else code
    )
    digits: list[str] = []
    for character in normalize("NFKC", reconstructed):
        try:
            digit = decimal(character)
        except ValueError:
            continue
        digits.append(str(digit))
    return _VIETNAM_PHONE.search("".join(digits)) is not None


def _canonical_payload_digest(raw: Mapping[str, object]) -> bytes | None:
    try:
        payload = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload).digest()


def _deduplicate_raw_traces(
    raw_traces: Sequence[Mapping[str, object]],
) -> tuple[tuple[Mapping[str, object], ...], int]:
    without_id: list[Mapping[str, object]] = []
    variants: dict[str, dict[bytes, Mapping[str, object]]] = defaultdict(dict)
    uncanonicalizable_ids: set[str] = set()

    for raw in raw_traces:
        trace_id = raw.get("id")
        if not isinstance(trace_id, str) or not trace_id:
            without_id.append(raw)
            continue
        digest = _canonical_payload_digest(raw)
        if digest is None:
            uncanonicalizable_ids.add(trace_id)
            continue
        variants[trace_id].setdefault(digest, raw)

    retained = list(without_id)
    collision_count = 0
    for trace_id in sorted(set(variants) | uncanonicalizable_ids):
        payloads = variants.get(trace_id, {})
        if trace_id in uncanonicalizable_ids or len(payloads) != 1:
            collision_count += 1
            continue
        retained.append(next(iter(payloads.values())))
    return tuple(retained), collision_count


def aggregate_dimension_coverage(
    records: Sequence[TraceRecord],
    taxonomy: Taxonomy,
    *,
    traces_fetched: int,
    traces_deduplicated: int,
    invalid_trace_count: int,
    dimension_backfill: Mapping[str, object] | None = None,
    ticket_count_override: int | None = None,
) -> dict[str, object]:
    if taxonomy.version != "v2":
        raise ValueError("dimension verification requires taxonomy v2")

    grouped: dict[str, list[TraceRecord]] = defaultdict(list)
    for record in records:
        grouped[record.session_id].append(record)

    trace_issue_category_present_count = 0
    trace_tpe_present_count = 0
    issue_category_present_count = 0
    tpe_present_count = 0
    issue_category_backfilled_count = 0
    tpe_backfilled_count = 0
    unmapped: Counter[tuple[str, str | None]] = Counter()
    for session_id in sorted(grouped):
        first_trace = min(
            grouped[session_id],
            key=lambda item: (item.turn, item.timestamp, item.id),
        )
        raw_dimensions = extract_dimensions(first_trace, taxonomy)
        raw_issue_present = _raw_dimension_present(
            first_trace,
            "issue_category",
            taxonomy,
        )
        raw_safe_code = (
            _safe_tpe_code(raw_dimensions.tpe_code)
            if raw_dimensions.tpe_code is not None
            else None
        )
        raw_tpe_present = (
            raw_safe_code is not None
            and not _contains_vietnam_phone(
                raw_safe_code,
                raw_dimensions.tpe_status_raw,
            )
        )
        trace_issue_category_present_count += raw_issue_present
        trace_tpe_present_count += raw_tpe_present

        effective_trace = first_trace
        if dimension_backfill is not None:
            from .dimension_backfill import (
                DimensionBackfill,
                apply_dimension_backfill,
            )

            candidate = dimension_backfill.get(session_id)
            if isinstance(candidate, DimensionBackfill):
                effective_trace = apply_dimension_backfill(
                    first_trace,
                    candidate,
                )
        dimensions = extract_dimensions(effective_trace, taxonomy)
        effective_issue_present = _raw_dimension_present(
            effective_trace,
            "issue_category",
            taxonomy,
        )
        issue_category_present_count += effective_issue_present
        issue_category_backfilled_count += (
            effective_issue_present and not raw_issue_present
        )
        safe_code = (
            _safe_tpe_code(dimensions.tpe_code)
            if dimensions.tpe_code is not None
            else None
        )
        if safe_code is not None and not _contains_vietnam_phone(
            safe_code,
            dimensions.tpe_status_raw,
        ):
            tpe_present_count += 1
            tpe_backfilled_count += not raw_tpe_present
            if dimensions.tpe_status_canonical is None:
                unmapped[
                    (
                        safe_code,
                        _safe_status(dimensions.tpe_status_raw),
                    )
                ] += 1

    if ticket_count_override is not None and (
        type(ticket_count_override) is not int
        or ticket_count_override < len(grouped)
    ):
        raise ValueError("ticket_count_override must cover all normalized sessions")
    ticket_count = (
        ticket_count_override
        if ticket_count_override is not None
        else len(grouped)
    )
    denominator = ticket_count or 1
    unmapped_rows = [
        {
            "code": code,
            "status": status,
            "count": count,
        }
        for (code, status), count in sorted(
            unmapped.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1] or "",
            ),
        )
    ]
    return {
        "traces_fetched": traces_fetched,
        "traces_deduplicated": traces_deduplicated,
        "invalid_trace_count": invalid_trace_count,
        "ticket_count": ticket_count,
        "trace_issue_category_present_count": (
            trace_issue_category_present_count
        ),
        "trace_tpe_present_count": trace_tpe_present_count,
        "issue_category_backfilled_count": issue_category_backfilled_count,
        "tpe_backfilled_count": tpe_backfilled_count,
        "issue_category_present_count": issue_category_present_count,
        "tpe_present_count": tpe_present_count,
        "coverage_issue_category": (
            issue_category_present_count / denominator if ticket_count else 0.0
        ),
        "coverage_tpe": tpe_present_count / denominator if ticket_count else 0.0,
        "unmapped_tpe_codes": unmapped_rows,
    }


def verify_raw_ticket_dimensions(
    raw_traces: Sequence[Mapping[str, object]],
    taxonomy: Taxonomy,
    *,
    dimension_backfill: Mapping[str, object] | None = None,
) -> dict[str, object]:
    ticket_traces = tuple(raw for raw in raw_traces if is_ticket_trace(raw))
    deduplicated, collision_count = _deduplicate_raw_traces(ticket_traces)
    records, issues, traces_deduplicated = normalize_raw_traces(deduplicated)
    report = aggregate_dimension_coverage(
        records,
        taxonomy,
        traces_fetched=len(ticket_traces),
        traces_deduplicated=traces_deduplicated,
        invalid_trace_count=len(issues) + collision_count,
        dimension_backfill=dimension_backfill,
        ticket_count_override=raw_ticket_session_denominator(ticket_traces),
    )
    validate_dimension_report_privacy(report)
    return report
