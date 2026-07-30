from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from unicodedata import category, decimal, normalize

import httpx

from .categories import Taxonomy, extract_dimensions
from .dimension_verifier import (
    _contains_private_identifier,
    raw_ticket_session_denominator,
)
from .models import TraceRecord
from .pipeline import normalize_raw_traces


FRESHDESK_BASE_URL = "https://vngzalopay.freshdesk.com"
_SAFE_TPE_CODE = re.compile(r"^-?[0-9]{1,6}$")
_SAFE_TICKET_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_MAX_DIMENSION_LENGTH = 128
_ISSUE_CATEGORY_FALLBACK = "Không xác định"
_TOMBSTONE_FRESHNESS = timedelta(hours=24)
_CATEGORY_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_CATEGORY_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_VIETNAMESE_FAMILY_NAMES = frozenset(
    {
        "nguyễn", "nguyen", "trần", "tran", "lê", "le", "phạm",
        "pham", "hoàng", "hoang", "huỳnh", "huynh", "vũ", "vu",
        "võ", "vo", "đặng", "dang", "bùi", "bui", "đỗ", "do",
        "hồ", "ho", "ngô", "ngo", "dương", "duong", "lý", "ly",
    }
)
_VIETNAMESE_NAME_MIDDLES = frozenset({"văn", "van", "thị", "thi"})
_APPROVED_TPE_STATUSES = frozenset(
    {"Thất bại", "Đang xử lý", "Bị từ chối"}
)
_FRESHDESK_FIELD_CONTRACT = {
    "cf_category": ("Category Chatbot", "custom_dropdown"),
    "cf_m_li_tpe": ("Mã lỗi TPE", "custom_text"),
}


class FreshdeskFieldContractError(RuntimeError):
    pass


class FreshdeskDimensionResponseError(RuntimeError):
    pass


class FreshdeskDimensionAPIError(RuntimeError):
    def __init__(self, status: int | str) -> None:
        self.status = status
        super().__init__(f"Freshdesk GET failed with status {status}")


class DimensionBackfillStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class DimensionBackfill:
    ticket_id: str
    issue_category: str | None
    tpe: str | None


class DimensionBackfillStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.path = self.runtime_dir / "dimension_backfill.json"

    def _ensure_private_runtime_directory(self, *, create: bool) -> None:
        try:
            directory_stat = os.lstat(self.runtime_dir)
        except FileNotFoundError:
            if not create:
                raise DimensionBackfillStoreError(
                    "dimension backfill directory must have mode 0700"
                ) from None
            self.runtime_dir.mkdir(parents=True, mode=0o700)
            directory_stat = os.lstat(self.runtime_dir)
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or stat.S_IMODE(directory_stat.st_mode) != 0o700
        ):
            raise DimensionBackfillStoreError(
                "dimension backfill directory must have mode 0700"
            )

    def _ensure_private_data_file(self, *, allow_missing: bool) -> None:
        try:
            file_stat = os.lstat(self.path)
        except FileNotFoundError:
            if allow_missing:
                return
            raise
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or not stat.S_ISREG(file_stat.st_mode)
            or stat.S_IMODE(file_stat.st_mode) != 0o600
        ):
            raise DimensionBackfillStoreError(
                "dimension backfill file must have mode 0600"
            )

    def write(
        self,
        entries: Mapping[str, DimensionBackfill],
        *,
        generated_at: datetime,
        last_attempt_at: Mapping[str, datetime] | None = None,
    ) -> None:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        generated_at_utc = generated_at.astimezone(timezone.utc)
        if (
            last_attempt_at is not None
            and set(last_attempt_at) != set(entries)
        ):
            raise ValueError(
                "last_attempt_at must match dimension backfill entries"
            )
        self._ensure_private_runtime_directory(create=True)
        self._ensure_private_data_file(allow_missing=True)
        records: list[dict[str, str | None]] = []
        for ticket_id in sorted(entries):
            entry = entries[ticket_id]
            if (
                _SAFE_TICKET_ID.fullmatch(ticket_id) is None
                or entry.ticket_id != ticket_id
            ):
                raise DimensionBackfillStoreError(
                    "dimension backfill contains an invalid ticket ID"
                )
            issue_category = _safe_category_text(entry.issue_category)
            tpe = _safe_tpe(entry.tpe)
            attempted_at = (
                generated_at
                if last_attempt_at is None
                else last_attempt_at[ticket_id]
            )
            if (
                attempted_at.tzinfo is None
                or attempted_at.utcoffset() is None
            ):
                raise ValueError("last_attempt_at must be timezone-aware")
            attempted_at_utc = attempted_at.astimezone(timezone.utc)
            if attempted_at_utc > generated_at_utc:
                raise ValueError(
                    "last_attempt_at must not exceed generated_at"
                )
            records.append(
                {
                    "ticket_id": ticket_id,
                    "cf_category": issue_category,
                    "cf_m_li_tpe": tpe,
                    "last_attempt_at": _utc_timestamp(attempted_at_utc),
                }
            )
        payload = {
            "schema_version": 2,
            "generated_at": _utc_timestamp(generated_at_utc),
            "source": "freshdesk_api_v2",
            "records": records,
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.runtime_dir,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary_path, 0o600)
                json.dump(
                    payload,
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.path)
            self._ensure_private_data_file(allow_missing=False)
            parent_fd = os.open(self.runtime_dir, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def load_with_attempts(
        self,
    ) -> tuple[
        dict[str, DimensionBackfill],
        datetime | None,
        dict[str, datetime],
    ]:
        self._ensure_private_runtime_directory(create=False)
        self._ensure_private_data_file(allow_missing=True)
        if not self.path.exists():
            return {}, None, {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DimensionBackfillStoreError(
                "dimension backfill file is invalid"
            ) from None
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {"schema_version", "generated_at", "source", "records"}
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") not in {1, 2}
            or payload.get("source") != "freshdesk_api_v2"
            or not isinstance(payload.get("generated_at"), str)
            or not isinstance(payload.get("records"), list)
        ):
            raise DimensionBackfillStoreError(
                "dimension backfill file is invalid"
            )
        generated_at = _parse_utc_timestamp(payload["generated_at"])
        schema_version = payload["schema_version"]
        entries: dict[str, DimensionBackfill] = {}
        attempts: dict[str, datetime] = {}
        for raw_entry in payload["records"]:
            expected_keys = (
                {"ticket_id", "cf_category", "cf_m_li_tpe"}
                if schema_version == 1
                else {
                    "ticket_id",
                    "cf_category",
                    "cf_m_li_tpe",
                    "last_attempt_at",
                }
            )
            if (
                not isinstance(raw_entry, dict)
                or set(raw_entry) != expected_keys
            ):
                raise DimensionBackfillStoreError(
                    "dimension backfill file is invalid"
                )
            ticket_id = raw_entry.get("ticket_id")
            if (
                not isinstance(ticket_id, str)
                or _SAFE_TICKET_ID.fullmatch(ticket_id) is None
                or ticket_id in entries
            ):
                raise DimensionBackfillStoreError(
                    "dimension backfill file is invalid"
                )
            issue_category = _safe_category_text(
                raw_entry.get("cf_category")
            )
            tpe = _safe_tpe(raw_entry.get("cf_m_li_tpe"))
            if (
                issue_category != raw_entry.get("cf_category")
                or tpe != raw_entry.get("cf_m_li_tpe")
            ):
                raise DimensionBackfillStoreError(
                    "dimension backfill file is invalid"
                )
            entries[ticket_id] = DimensionBackfill(
                ticket_id=ticket_id,
                issue_category=issue_category,
                tpe=tpe,
            )
            attempted_at = (
                generated_at
                if schema_version == 1
                else _parse_utc_timestamp(raw_entry.get("last_attempt_at"))
            )
            if attempted_at > generated_at:
                raise DimensionBackfillStoreError(
                    "dimension backfill file is invalid"
                )
            attempts[ticket_id] = attempted_at
        return entries, generated_at, attempts

    def load_with_generated_at(
        self,
    ) -> tuple[dict[str, DimensionBackfill], datetime | None]:
        entries, generated_at, _attempts = self.load_with_attempts()
        return entries, generated_at

    def load(self) -> dict[str, DimensionBackfill]:
        entries, _generated_at, _attempts = self.load_with_attempts()
        return entries

    def load_generated_at(self) -> datetime | None:
        _entries, generated_at, _attempts = self.load_with_attempts()
        return generated_at

    def load_last_attempt_at(self) -> dict[str, datetime]:
        _entries, _generated_at, attempts = self.load_with_attempts()
        return attempts


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise DimensionBackfillStoreError(
            "dimension backfill file is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DimensionBackfillStoreError(
            "dimension backfill file is invalid"
        ) from None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
    ):
        raise DimensionBackfillStoreError(
            "dimension backfill file is invalid"
        )
    return parsed.astimezone(timezone.utc)


def _safe_dimension_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = normalize("NFC", value.strip())
    if (
        not cleaned
        or len(cleaned) > _MAX_DIMENSION_LENGTH
        or _contains_private_identifier(cleaned)
    ):
        return None
    return cleaned


def _safe_category_text(value: object) -> str | None:
    cleaned = _safe_dimension_text(value)
    if cleaned is None:
        return None
    normalized = normalize("NFKC", cleaned)
    if (
        any(category(character).startswith("C") for character in normalized)
        or _CATEGORY_EMAIL.search(normalized) is not None
        or _CATEGORY_URL.search(normalized) is not None
        or normalized.startswith(("=", "+", "-", "@"))
        or _contains_long_numeric_identifier(normalized)
        or _looks_like_vietnamese_personal_name(normalized)
    ):
        return None
    return cleaned


def _looks_like_vietnamese_personal_name(value: str) -> bool:
    """Fail closed for the common three-part personal-name form only."""
    parts = value.casefold().split()
    return (
        len(parts) == 3
        and parts[0] in _VIETNAMESE_FAMILY_NAMES
        and parts[1] in _VIETNAMESE_NAME_MIDDLES
        and parts[2].isalpha()
        and 1 <= len(parts[2]) <= 32
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


def _safe_tpe(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = normalize("NFC", value).split("|", maxsplit=1)[0].strip()
    match = re.fullmatch(
        r"(?P<code>-?[0-9]{1,6})(?:[ \t]+(?P<suffix>[^\r\n\x00-\x1f\x7f]*))?",
        candidate,
    )
    if match is None:
        return None
    code = match.group("code")
    suffix = match.group("suffix")
    if suffix in _APPROVED_TPE_STATUSES:
        return f"{code} {suffix}"
    return code


def apply_dimension_backfill(
    trace: TraceRecord,
    backfill: DimensionBackfill | None,
) -> TraceRecord:
    if backfill is None or backfill.ticket_id != trace.session_id:
        return trace
    if not isinstance(trace.input_data, Mapping):
        return trace
    input_data = dict(trace.input_data)
    raw_other_info = input_data.get("other_info")
    other_info = (
        dict(raw_other_info)
        if isinstance(raw_other_info, Mapping)
        else {}
    )
    raw_meta = other_info.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}

    raw_extra = meta.get("Thông tin thêm")
    extra = dict(raw_extra) if isinstance(raw_extra, Mapping) else {}
    existing_category = extra.get("category")
    if (
        backfill.issue_category is not None
        and _is_missing_dimension_value(
            existing_category,
            fallback=_ISSUE_CATEGORY_FALLBACK,
        )
    ):
        extra["category"] = backfill.issue_category
        meta["Thông tin thêm"] = extra

    existing_tpe = meta.get("Mã lỗi TPE")
    if (
        backfill.tpe is not None
        and _is_missing_dimension_value(existing_tpe)
    ):
        meta["Mã lỗi TPE"] = backfill.tpe

    other_info["meta"] = meta
    input_data["other_info"] = other_info
    return replace(trace, input_data=input_data)


def _is_missing_dimension_value(
    value: object,
    *,
    fallback: str | None = None,
) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    normalized = normalize("NFKC", value.strip())
    return not normalized or (fallback is not None and normalized == fallback)


def backfill_ticket_dimensions(
    raw_traces: Sequence[Mapping[str, object]],
    taxonomy: Taxonomy,
    client: "FreshdeskDimensionClient",
    store: DimensionBackfillStore,
    *,
    generated_at: datetime,
) -> dict[str, int]:
    """Fetch only missing ticket dimensions and persist each completed ticket.

    This intentionally accepts raw Langfuse traces so the raw ``input.source``
    remains the sole denominator gate.  The aggregate return value contains
    counts only; ticket IDs and Freshdesk values stay in the private store.
    """
    if taxonomy.version != "v2":
        raise ValueError("dimension backfill requires taxonomy v2")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    ticket_raw = tuple(
        raw
        for raw in raw_traces
        if isinstance(raw.get("input"), Mapping)
        and raw["input"].get("source") == "ticket"
    )
    records, _issues, _deduplicated = normalize_raw_traces(ticket_raw)
    raw_ticket_session_count = raw_ticket_session_denominator(ticket_raw)
    grouped: dict[str, list[TraceRecord]] = {}
    for record in records:
        grouped.setdefault(record.session_id, []).append(record)

    try:
        os.lstat(store.runtime_dir)
    except FileNotFoundError:
        entries = {}
        last_attempt_at: dict[str, datetime] = {}
    else:
        entries, _store_generated_at, last_attempt_at = (
            store.load_with_attempts()
        )
    missing_issue_category_count = 0
    missing_tpe_count = 0
    eligible: list[tuple[str, bool, bool]] = []
    skipped_fresh_tombstone_count = 0
    for session_id in sorted(grouped):
        first_trace = min(
            grouped[session_id],
            key=lambda item: (item.turn, item.timestamp, item.id),
        )
        dimensions = extract_dimensions(first_trace, taxonomy)
        missing_issue_category = _is_missing_dimension_value(
            dimensions.issue_category,
            fallback=taxonomy.dimension_fallbacks["issue_category"],
        )
        missing_tpe = dimensions.tpe_code is None
        missing_issue_category_count += missing_issue_category
        missing_tpe_count += missing_tpe
        if (
            _SAFE_TICKET_ID.fullmatch(session_id) is None
            or not (missing_issue_category or missing_tpe)
        ):
            continue
        cached = entries.get(session_id)
        cache_fills_issue = cached is not None and not _is_missing_dimension_value(
            cached.issue_category,
            fallback=taxonomy.dimension_fallbacks["issue_category"],
        )
        cache_fills_tpe = cached is not None and cached.tpe is not None
        cached_still_missing = (
            missing_issue_category and not cache_fills_issue
        ) or (missing_tpe and not cache_fills_tpe)
        attempted_at = last_attempt_at.get(session_id)
        if cached_still_missing and attempted_at is not None:
            attempt_age = (
                generated_at.astimezone(timezone.utc) - attempted_at
            )
            if timedelta(0) <= attempt_age < _TOMBSTONE_FRESHNESS:
                skipped_fresh_tombstone_count += 1
                continue
        if (
            (not missing_issue_category or cache_fills_issue)
            and (not missing_tpe or cache_fills_tpe)
        ):
            continue
        eligible.append((session_id, missing_issue_category, missing_tpe))

    if eligible:
        client.validate_field_contract()
    fetched_ticket_count = 0
    inaccessible_ticket_count = 0
    for ticket_id, missing_issue_category, missing_tpe in eligible:
        try:
            fetched = client.fetch_ticket_dimensions(ticket_id)
        except FreshdeskDimensionAPIError as error:
            if error.status != 403:
                raise
            fetched = DimensionBackfill(ticket_id, None, None)
            inaccessible_ticket_count += 1
        else:
            fetched_ticket_count += 1
        cached = entries.get(ticket_id)
        entries[ticket_id] = DimensionBackfill(
            ticket_id=ticket_id,
            issue_category=(
                cached.issue_category
                if cached is not None
                and not _is_missing_dimension_value(
                    cached.issue_category,
                    fallback=taxonomy.dimension_fallbacks["issue_category"],
                )
                else fetched.issue_category if missing_issue_category else None
            ),
            tpe=(
                cached.tpe
                if cached is not None and cached.tpe is not None
                else fetched.tpe if missing_tpe else None
            ),
        )
        last_attempt_at[ticket_id] = generated_at.astimezone(timezone.utc)
        # A write per completed ticket attempt is deliberate: a later GET
        # failure cannot discard pre-existing, inaccessible, or completed records.
        store.write(
            entries,
            generated_at=generated_at,
            last_attempt_at=last_attempt_at,
        )

    return {
        "ticket_trace_count": len(ticket_raw),
        "ticket_session_count": raw_ticket_session_count,
        "eligible_ticket_count": len(eligible),
        "missing_issue_category_count": missing_issue_category_count,
        "missing_tpe_count": missing_tpe_count,
        "fetched_ticket_count": fetched_ticket_count,
        "inaccessible_ticket_count": inaccessible_ticket_count,
        "skipped_fresh_tombstone_count": skipped_fresh_tombstone_count,
        "stored_record_count": len(entries),
    }


class FreshdeskDimensionClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        backoff_base_s: float = 0.5,
    ) -> None:
        if base_url.rstrip("/") != FRESHDESK_BASE_URL:
            raise ValueError("Freshdesk base URL does not match the configured target")
        if not api_key:
            raise ValueError("Freshdesk API key is missing")
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if backoff_base_s < 0:
            raise ValueError("backoff_base_s must not be negative")
        self._client = httpx.Client(
            base_url=FRESHDESK_BASE_URL,
            auth=(api_key, "X"),
            timeout=httpx.Timeout(30.0),
            verify=True,
            follow_redirects=False,
            transport=transport,
        )
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._category_choices: frozenset[str] | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FreshdeskDimensionClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get(self, path: str) -> httpx.Response:
        if (
            path != "/api/v2/ticket_fields"
            and re.fullmatch(
                r"/api/v2/tickets/(?:archived/)?[1-9][0-9]{0,19}",
                path,
            )
            is None
        ):
            raise ValueError("Freshdesk GET path is not allowed")
        for attempt in range(self._max_attempts):
            try:
                response = self._client.get(path)
            except httpx.TransportError:
                if attempt + 1 == self._max_attempts:
                    raise FreshdeskDimensionAPIError(
                        "transport_error"
                    ) from None
                self._sleep(self._backoff_base_s * (2**attempt))
                continue
            if response.is_success or response.status_code == 404:
                return response
            if (
                response.status_code == 429
                or 500 <= response.status_code < 600
            ) and attempt + 1 < self._max_attempts:
                retry_after = None
                if response.status_code == 429:
                    try:
                        retry_after = float(
                            response.headers.get("Retry-After", "")
                        )
                    except ValueError:
                        retry_after = None
                delay = (
                    retry_after
                    if retry_after is not None
                    and 0 <= retry_after <= 300
                    else self._backoff_base_s * (2**attempt)
                )
                self._sleep(delay)
                continue
            raise FreshdeskDimensionAPIError(response.status_code)
        raise AssertionError("unreachable")

    def validate_field_contract(self) -> None:
        self._category_choices = None
        response = self._get("/api/v2/ticket_fields")
        try:
            payload = response.json()
        except ValueError:
            raise FreshdeskFieldContractError(
                "Freshdesk dimension field contract is unavailable"
            ) from None
        if not isinstance(payload, list):
            raise FreshdeskFieldContractError(
                "Freshdesk dimension field contract is unavailable"
            )
        category_choices: frozenset[str] | None = None
        for name, (label, field_type) in _FRESHDESK_FIELD_CONTRACT.items():
            fields = [
                item
                for item in payload
                if isinstance(item, dict) and item.get("name") == name
            ]
            field = fields[0] if len(fields) == 1 else None
            if (
                not isinstance(field, dict)
                or field.get("label") != label
                or field.get("type") != field_type
            ):
                raise FreshdeskFieldContractError(
                    "Freshdesk dimension field contract is unavailable"
                )
            if name == "cf_category":
                choices = field.get("choices")
                if (
                    not isinstance(choices, list)
                    or not choices
                    or not all(isinstance(choice, str) for choice in choices)
                    or len(set(choices)) != len(choices)
                ):
                    raise FreshdeskFieldContractError(
                        "Freshdesk dimension field contract is unavailable"
                    )
                if any(_safe_category_text(choice) is None for choice in choices):
                    raise FreshdeskFieldContractError(
                        "Freshdesk dimension field contract is unavailable"
                    )
                category_choices = frozenset(choices)
        if category_choices is None:
            raise FreshdeskFieldContractError(
                "Freshdesk dimension field contract is unavailable"
            )
        self._category_choices = category_choices

    def fetch_ticket_dimensions(self, ticket_id: str) -> DimensionBackfill:
        if self._category_choices is None:
            raise FreshdeskFieldContractError(
                "Freshdesk dimension field contract is unavailable"
            )
        if _SAFE_TICKET_ID.fullmatch(ticket_id) is None:
            raise ValueError("Freshdesk ticket ID must be numeric")
        response = self._get(f"/api/v2/tickets/{ticket_id}")
        if response.status_code == 404:
            response = self._get(
                f"/api/v2/tickets/archived/{ticket_id}"
            )
            if response.status_code == 404:
                return DimensionBackfill(
                    ticket_id=ticket_id,
                    issue_category=None,
                    tpe=None,
                )
        try:
            payload = response.json()
        except ValueError:
            raise FreshdeskDimensionResponseError(
                "Freshdesk ticket response is invalid"
            ) from None
        if (
            not isinstance(payload, dict)
            or type(payload.get("id")) is not int
            or payload.get("id") != int(ticket_id)
            or not isinstance(payload.get("custom_fields"), dict)
        ):
            raise FreshdeskDimensionResponseError(
                "Freshdesk ticket response is invalid"
            )
        custom_fields = payload.get("custom_fields")
        assert isinstance(custom_fields, dict)
        issue_category = _safe_category_text(
            custom_fields.get("cf_category")
        )
        if issue_category not in self._category_choices:
            issue_category = None
        return DimensionBackfill(
            ticket_id=ticket_id,
            issue_category=issue_category,
            tpe=_safe_tpe(custom_fields.get("cf_m_li_tpe")),
        )
