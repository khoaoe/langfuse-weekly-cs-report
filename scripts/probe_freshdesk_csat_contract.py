#!/usr/bin/env python3
"""Read-only, schema-only Freshdesk CSAT contract discovery.

Raw ticket, conversation, and rating payloads are summarized in memory and are
never written or printed. This is a Stage 0A probe, not a production CSAT job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT_NAME = "identity_checkpoint.json"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_CONVERSATION_PAGES = 100
MAX_RETRIES = 3
APPROVED_FRESHDESK_HOST = "vngzalopay.freshdesk.com"
RATING_SOURCE_ID_PATH = "satisfaction_ratings[].id"
ENDPOINT_NAMES = (
    "ticket",
    "ticket_with_stats",
    "conversations",
    "satisfaction_ratings",
)
_TYPE_TOKENS = frozenset(
    {"null", "boolean", "integer", "number", "string", "unobserved"}
)
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_.\[\]-]+$")
_SAFE_LABEL = re.compile(r"^[^@\r\n]{1,80}$")


class ContractProbeError(RuntimeError):
    """Sanitized discovery failure; source payloads never enter the message."""


@dataclass(frozen=True)
class FreshdeskProbeSettings:
    base_url: str
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validate_origin(self.base_url))
        if not self.api_key:
            raise ContractProbeError("FRESHDESK_API_KEY is missing")


@dataclass(frozen=True)
class _EndpointObservation:
    status: int
    shape: object | None
    cardinality: int | None = None


@dataclass(frozen=True)
class _RatingEvidence:
    response_key_hash: str | None
    missing_source_id: bool
    api_id_hashes: tuple[tuple[str, str], ...]
    survey_observation: tuple[object, object | None, str | None] | None


@dataclass(frozen=True)
class _SchemaTicketResult:
    endpoints: Mapping[str, tuple[_EndpointObservation, ...]]
    ratings: tuple[_RatingEvidence, ...]
    agent_fields: tuple[tuple[str, str], ...]


@dataclass
class _IdentityState:
    processed_weeks: set[str] = field(default_factory=set)
    processed_ticket_ids: set[str] = field(default_factory=set)
    response_key_hashes: set[str] = field(default_factory=set)
    missing_source_id_count: int = 0
    collision_count: int = 0
    response_count: int = 0
    api_id_seen_counts: Counter[str] = field(default_factory=Counter)
    api_id_hashes: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    survey_counts: Counter[str] = field(default_factory=Counter)


def _validate_origin(value: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        raise ContractProbeError("FRESHDESK_BASE_URL is invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != APPROVED_FRESHDESK_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ContractProbeError("FRESHDESK_BASE_URL is invalid")
    return f"https://{parsed.netloc}".rstrip("/")


def load_probe_settings(env_path: Path) -> FreshdeskProbeSettings:
    """Load only the two Freshdesk values without mutating process environment."""
    file_values = dotenv_values(Path(env_path))
    selected: dict[str, str | None] = {}
    for name in ("FRESHDESK_BASE_URL", "FRESHDESK_API_KEY"):
        process_value = os.environ.get(name)
        selected[name] = process_value if process_value is not None else file_values.get(name)
    if not isinstance(selected["FRESHDESK_BASE_URL"], str) or not selected[
        "FRESHDESK_BASE_URL"
    ].strip():
        raise ContractProbeError("FRESHDESK_BASE_URL is missing")
    if not isinstance(selected["FRESHDESK_API_KEY"], str) or not selected[
        "FRESHDESK_API_KEY"
    ].strip():
        raise ContractProbeError("FRESHDESK_API_KEY is missing")
    return FreshdeskProbeSettings(
        base_url=_validate_origin(selected["FRESHDESK_BASE_URL"].strip()),
        api_key=selected["FRESHDESK_API_KEY"].strip(),
    )


def summarize_shape(value: object) -> object:
    """Return recursive field/type evidence without retaining source values."""
    if isinstance(value, Mapping):
        return {
            str(key): summarize_shape(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        shapes = _deduplicated_shapes(value)
        return {"type": "list", "item_shapes": shapes}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise ContractProbeError("Freshdesk response contains an unsupported type")


def _deduplicated_shapes(values: Sequence[object]) -> list[object]:
    by_key = {
        json.dumps(shape, ensure_ascii=True, sort_keys=True, separators=(",", ":")): shape
        for shape in (summarize_shape(value) for value in values)
    }
    return [by_key[key] for key in sorted(by_key)]


def _value_type(value: object) -> str:
    summary = summarize_shape(value)
    if isinstance(summary, str):
        return summary
    if isinstance(value, list):
        return "list"
    return "object"


def _agent_field_candidates(value: object, prefix: str) -> tuple[tuple[str, str], ...]:
    candidates: set[tuple[str, str]] = set()

    def visit(child: object, path: str) -> None:
        if isinstance(child, Mapping):
            for key, nested in child.items():
                name = str(key)
                nested_path = f"{path}.{name}" if path else name
                folded = name.casefold()
                if (
                    "agent" in folded
                    or "responder" in folded
                    or folded == "user_id"
                ):
                    candidates.add((nested_path, _value_type(nested)))
                visit(nested, nested_path)
        elif isinstance(child, list):
            for nested in child:
                visit(nested, f"{path}[]")

    visit(value, prefix)
    return tuple(sorted(candidates))


def _iter_scalar_paths(value: object, prefix: str = ""):
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            yield from _iter_scalar_paths(child, path)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_scalar_paths(child, f"{prefix}[]")
    else:
        yield prefix, value


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _safe_survey_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not _SAFE_LABEL.fullmatch(normalized)
        or "http://" in normalized.casefold()
        or "https://" in normalized.casefold()
        or re.search(r"\d{6,}", normalized)
    ):
        return None
    return normalized


def _rating_token(item: Mapping[str, object]) -> tuple[object | None, str | None]:
    ratings = item.get("ratings")
    if not isinstance(ratings, Mapping):
        return None, None
    value = ratings.get("default_question")
    if isinstance(value, bool) or value is None:
        return None, None
    if isinstance(value, (int, float)):
        return value, None
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped), None
        except ValueError:
            return None, _safe_survey_label(stripped)
    return None, None


def _rating_evidence(payload: object) -> tuple[_RatingEvidence, ...]:
    if not isinstance(payload, list):
        return ()
    evidence: list[_RatingEvidence] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        source_id = item.get("id")
        missing_source_id = source_id is None or isinstance(
            source_id, (Mapping, list, bool)
        )
        response_key = None if missing_source_id else _canonical_hash(source_id)
        api_ids: list[tuple[str, str]] = []
        for path, value in _iter_scalar_paths(item):
            terminal = path.rsplit(".", 1)[-1]
            if (
                terminal == "id"
                and value is not None
                and not isinstance(value, (Mapping, list, bool))
            ):
                api_ids.append((f"satisfaction_ratings[].{path}", _canonical_hash(value)))
        survey_id = item.get("survey_id")
        rating_raw, rating_label = _rating_token(item)
        survey = None
        if isinstance(survey_id, (int, str)) and not isinstance(survey_id, bool):
            survey = (survey_id, rating_raw, rating_label)
        evidence.append(
            _RatingEvidence(
                response_key_hash=response_key,
                missing_source_id=missing_source_id,
                api_id_hashes=tuple(sorted(api_ids)),
                survey_observation=survey,
            )
        )
    return tuple(evidence)


class _FreshdeskProbeClient:
    def __init__(
        self,
        settings: FreshdeskProbeSettings,
        *,
        transport: httpx.BaseTransport,
        sleep: Callable[[float], None],
    ) -> None:
        origin = _validate_origin(settings.base_url)
        self._client = httpx.Client(
            base_url=origin,
            auth=(settings.api_key, "X"),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(30.0),
            transport=transport,
            follow_redirects=False,
        )
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _request(self, path: str, *, params: Mapping[str, object] | None = None):
        for attempt in range(MAX_RETRIES + 1):
            try:
                with self._client.stream("GET", path, params=params) as response:
                    if 300 <= response.status_code < 400:
                        raise ContractProbeError("Freshdesk redirect refused")
                    if response.status_code == 429 and attempt < MAX_RETRIES:
                        self._sleep(_retry_after(response.headers.get("Retry-After")))
                        continue
                    if response.status_code in {401, 403}:
                        raise ContractProbeError(
                            "Freshdesk authentication or permission failed"
                        )
                    if response.status_code == 429:
                        raise ContractProbeError(
                            "Freshdesk rate limit persisted after retries"
                        )
                    if not 200 <= response.status_code < 300:
                        return response.status_code, None
                    return response.status_code, _read_bounded_json(response)
            except httpx.TransportError:
                if attempt >= MAX_RETRIES:
                    raise ContractProbeError("Freshdesk transport failed") from None
                continue
        raise AssertionError("unreachable")

    def ticket(self, ticket_id: str, *, stats: bool = False):
        params = {"include": "stats"} if stats else None
        return self._request(f"/api/v2/tickets/{ticket_id}", params=params)

    def conversations(self, ticket_id: str):
        combined: list[object] = []
        statuses: list[int] = []
        for page in range(1, MAX_CONVERSATION_PAGES + 1):
            status, payload = self._request(
                f"/api/v2/tickets/{ticket_id}/conversations",
                params={"page": page, "per_page": 100},
            )
            statuses.append(status)
            if status != 200:
                return tuple(statuses), None
            if not isinstance(payload, list):
                raise ContractProbeError("Freshdesk conversations shape is not a list")
            combined.extend(payload)
            if len(payload) < 100:
                return tuple(statuses), combined
        raise ContractProbeError("Freshdesk conversation page limit exceeded")

    def satisfaction_ratings(self, ticket_id: str):
        return self._request(f"/api/v2/tickets/{ticket_id}/satisfaction_ratings")


def _retry_after(value: str | None) -> float:
    try:
        parsed = float(value) if value is not None else 1.0
    except ValueError:
        parsed = 1.0
    return min(300.0, max(0.0, parsed))


def _read_bounded_json(response: httpx.Response) -> object:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > MAX_RESPONSE_BYTES:
                raise ContractProbeError("Freshdesk response exceeded byte limit")
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ContractProbeError("Freshdesk response exceeded byte limit")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContractProbeError("Freshdesk returned invalid JSON") from None


def _validated_ticket_ids(ticket_ids: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(ticket_id).strip() for ticket_id in ticket_ids)
    if not 1 <= len(normalized) <= 100:
        raise ContractProbeError("schema sample size must be between 1 and 100")
    if any(not ticket_id.isdigit() for ticket_id in normalized):
        raise ContractProbeError("ticket IDs must contain digits only")
    if len(set(normalized)) != len(normalized):
        raise ContractProbeError("schema sample contains duplicate ticket IDs")
    return normalized


def _observation(status: int, payload: object | None) -> _EndpointObservation:
    return _EndpointObservation(
        status=status,
        shape=summarize_shape(payload) if payload is not None else None,
        cardinality=len(payload) if isinstance(payload, list) else None,
    )


def _probe_schema_ticket(client: _FreshdeskProbeClient, ticket_id: str):
    ticket_status, ticket = client.ticket(ticket_id)
    stats_status, stats = client.ticket(ticket_id, stats=True)
    conversation_statuses, conversations = client.conversations(ticket_id)
    rating_status, ratings = client.satisfaction_ratings(ticket_id)
    endpoint_rows = {
        "ticket": (_observation(ticket_status, ticket),),
        "ticket_with_stats": (_observation(stats_status, stats),),
        "conversations": tuple(
            _observation(status, conversations if index == len(conversation_statuses) - 1 else None)
            for index, status in enumerate(conversation_statuses)
        ),
        "satisfaction_ratings": (_observation(rating_status, ratings),),
    }
    agent_fields = set()
    for name, payload in (
        ("ticket", ticket),
        ("ticket_with_stats", stats),
        ("conversations", conversations),
        ("satisfaction_ratings", ratings),
    ):
        if payload is not None:
            agent_fields.update(_agent_field_candidates(payload, name))
    return _SchemaTicketResult(
        endpoints=endpoint_rows,
        ratings=_rating_evidence(ratings),
        agent_fields=tuple(sorted(agent_fields)),
    )


def _finalize_shape(observations: Sequence[_EndpointObservation]) -> object:
    shapes = _deduplicate_existing_shapes(
        observation.shape for observation in observations if observation.shape is not None
    )
    if not shapes:
        return "unobserved"
    shape: object = shapes[0] if len(shapes) == 1 else {"type": "union", "options": shapes}
    cardinalities = [
        observation.cardinality
        for observation in observations
        if observation.cardinality is not None
    ]
    if cardinalities and isinstance(shape, dict) and shape.get("type") == "list":
        return {
            **shape,
            "cardinality": {"min": min(cardinalities), "max": max(cardinalities)},
        }
    return shape


def _deduplicate_existing_shapes(shapes) -> list[object]:
    by_key = {
        json.dumps(shape, ensure_ascii=True, sort_keys=True, separators=(",", ":")): shape
        for shape in shapes
    }
    return [by_key[key] for key in sorted(by_key)]


def _finalize_endpoints(
    observations: Mapping[str, Sequence[_EndpointObservation]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in ENDPOINT_NAMES:
        rows = tuple(observations.get(name, ()))
        status_counts = Counter(str(row.status) for row in rows)
        result[name] = {
            "status_counts": dict(sorted(status_counts.items())),
            "shape": _finalize_shape(rows),
        }
    return result


def _apply_rating_evidence(state: _IdentityState, evidence: _RatingEvidence) -> None:
    state.response_count += 1
    if evidence.missing_source_id:
        state.missing_source_id_count += 1
    if evidence.response_key_hash is not None:
        if evidence.response_key_hash in state.response_key_hashes:
            state.collision_count += 1
        state.response_key_hashes.add(evidence.response_key_hash)
    for path, value_hash in evidence.api_id_hashes:
        state.api_id_seen_counts[path] += 1
        state.api_id_hashes[path].add(value_hash)
    if evidence.survey_observation is not None:
        state.survey_counts[_survey_key(evidence.survey_observation)] += 1


def _survey_key(observation: tuple[object, object | None, str | None]) -> str:
    survey_id, rating_raw, rating_label = observation
    return json.dumps(
        {
            "survey_id": survey_id,
            "rating_raw": rating_raw,
            "rating_label_raw": rating_label,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _survey_observations(state: _IdentityState) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for key, count in sorted(state.survey_counts.items()):
        parsed = json.loads(key)
        observations.append({**parsed, "count": count})
    return observations


def _stable_api_id_paths(state: _IdentityState) -> list[str]:
    return sorted(
        path
        for path, seen_count in state.api_id_seen_counts.items()
        if state.response_count > 0
        and seen_count == state.response_count
        and len(state.api_id_hashes[path]) == state.response_count
    )


def _host_fingerprint(base_url: str) -> str:
    return _canonical_hash(urlparse(base_url).hostname or "")


def _population_fingerprint(
    ticket_ids_by_week: Mapping[str, Sequence[str]], identity_weeks: int
) -> str:
    normalized = {
        str(week): sorted(str(ticket_id) for ticket_id in ticket_ids)
        for week, ticket_ids in sorted(ticket_ids_by_week.items())
    }
    return _canonical_hash({"identity_weeks": identity_weeks, "weeks": normalized})


def _new_identity_state() -> _IdentityState:
    return _IdentityState()


def _load_checkpoint(
    path: Path,
    *,
    host_fingerprint: str,
    population_fingerprint: str,
) -> _IdentityState:
    if not path.exists():
        return _new_identity_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ContractProbeError("identity checkpoint is invalid") from None
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != 2
        or payload.get("host_fingerprint") != host_fingerprint
        or payload.get("population_fingerprint") != population_fingerprint
    ):
        raise ContractProbeError("identity checkpoint does not match this run")
    try:
        state = _IdentityState(
            processed_weeks=set(payload["processed_weeks"]),
            processed_ticket_ids=set(payload["processed_ticket_ids"]),
            response_key_hashes=set(payload["response_key_hashes"]),
            missing_source_id_count=int(payload["missing_source_id_count"]),
            collision_count=int(payload["collision_count"]),
            response_count=int(payload["response_count"]),
            api_id_seen_counts=Counter(payload["api_id_seen_counts"]),
            api_id_hashes=defaultdict(
                set,
                {
                    str(key): set(values)
                    for key, values in payload["api_id_hashes"].items()
                },
            ),
            survey_counts=Counter(
                {
                    json.dumps(
                        {
                            "survey_id": row["survey_id"],
                            "rating_raw": row["rating_raw"],
                            "rating_label_raw": row["rating_label_raw"],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ): int(row["count"])
                    for row in payload["survey_observations"]
                }
            ),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ContractProbeError("identity checkpoint is invalid") from None
    return state


def _checkpoint_payload(
    state: _IdentityState,
    *,
    host_fingerprint: str,
    population_fingerprint: str,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "host_fingerprint": host_fingerprint,
        "population_fingerprint": population_fingerprint,
        "processed_weeks": sorted(state.processed_weeks),
        "processed_ticket_ids": sorted(state.processed_ticket_ids),
        "response_key_hashes": sorted(state.response_key_hashes),
        "missing_source_id_count": state.missing_source_id_count,
        "collision_count": state.collision_count,
        "response_count": state.response_count,
        "api_id_seen_counts": dict(sorted(state.api_id_seen_counts.items())),
        "api_id_hashes": {
            path: sorted(values) for path, values in sorted(state.api_id_hashes.items())
        },
        "survey_observations": _survey_observations(state),
    }


def _atomic_private_json(path: Path, payload: Mapping[str, object]) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    temporary = directory / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _scan_identity(
    client: _FreshdeskProbeClient,
    *,
    ticket_ids_by_week: Mapping[str, Sequence[str]],
    identity_weeks: int,
    checkpoint: Path,
    max_duration_seconds: float,
    monotonic: Callable[[], float],
    endpoint_observations: dict[str, list[_EndpointObservation]],
    initial_state: _IdentityState | None = None,
) -> _IdentityState:
    host = _host_fingerprint(str(client._client.base_url))
    population = _population_fingerprint(ticket_ids_by_week, identity_weeks)
    state = initial_state or _load_checkpoint(
        checkpoint, host_fingerprint=host, population_fingerprint=population
    )
    started = monotonic()
    for week, ticket_ids in sorted(ticket_ids_by_week.items()):
        if week in state.processed_weeks:
            continue
        pending = [
            str(ticket_id)
            for ticket_id in ticket_ids
            if str(ticket_id) not in state.processed_ticket_ids
        ]
        duration_reached = False
        with ThreadPoolExecutor(max_workers=2) as executor:
            for start in range(0, len(pending), 2):
                if monotonic() - started >= max_duration_seconds:
                    duration_reached = True
                    break
                batch = pending[start : start + 2]
                rows = executor.map(client.satisfaction_ratings, batch)
                for ticket_id, (status, payload) in zip(batch, rows, strict=True):
                    endpoint_observations["satisfaction_ratings"].append(
                        _observation(status, payload)
                    )
                    for evidence in _rating_evidence(payload):
                        _apply_rating_evidence(state, evidence)
                    state.processed_ticket_ids.add(ticket_id)
                _atomic_private_json(
                    checkpoint,
                    _checkpoint_payload(
                        state,
                        host_fingerprint=host,
                        population_fingerprint=population,
                    ),
                )
                if monotonic() - started >= max_duration_seconds:
                    duration_reached = True
                    break
        if duration_reached:
            return state
        state.processed_weeks.add(week)
        _atomic_private_json(
            checkpoint,
            _checkpoint_payload(
                state,
                host_fingerprint=host,
                population_fingerprint=population,
            ),
        )
        if monotonic() - started >= max_duration_seconds:
            break
    return state


def _default_identity_state(schema_results: Sequence[_SchemaTicketResult]):
    state = _new_identity_state()
    for result in schema_results:
        for evidence in result.ratings:
            _apply_rating_evidence(state, evidence)
    state.processed_ticket_ids.update(
        str(index) for index in range(len(schema_results))
    )
    state.processed_weeks.add("sample")
    return state


def run_contract_probe(
    ticket_ids: Sequence[str],
    settings: FreshdeskProbeSettings,
    *,
    transport: httpx.BaseTransport,
    out: Path,
    identity_ticket_ids_by_week: Mapping[str, Sequence[str]] | None = None,
    identity_weeks: int = 1,
    checkpoint: Path | None = None,
    max_duration_seconds: float = 1800.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    sample = _validated_ticket_ids(ticket_ids)
    if identity_weeks < 1:
        raise ContractProbeError("identity weeks must be positive")
    if max_duration_seconds < 0:
        raise ContractProbeError("max duration must not be negative")
    normalized_population = None
    checkpoint_path = None
    initial_identity_state = None
    if identity_ticket_ids_by_week is not None:
        normalized_population = _validate_identity_population(
            identity_ticket_ids_by_week
        )
        checkpoint_path = checkpoint or Path(out).parent / DEFAULT_CHECKPOINT_NAME
        initial_identity_state = _load_checkpoint(
            checkpoint_path,
            host_fingerprint=_host_fingerprint(settings.base_url),
            population_fingerprint=_population_fingerprint(
                normalized_population, identity_weeks
            ),
        )
    client = _FreshdeskProbeClient(settings, transport=transport, sleep=sleep)
    endpoint_observations = {name: [] for name in ENDPOINT_NAMES}
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            schema_results = tuple(executor.map(lambda item: _probe_schema_ticket(client, item), sample))
        agent_fields: set[tuple[str, str]] = set()
        for result in schema_results:
            agent_fields.update(result.agent_fields)
            for name, rows in result.endpoints.items():
                endpoint_observations[name].extend(rows)
        if identity_ticket_ids_by_week is None:
            identity_state = _default_identity_state(schema_results)
            identity_population_count = len(sample)
            completed = True
        else:
            assert normalized_population is not None
            assert checkpoint_path is not None
            identity_state = _scan_identity(
                client,
                ticket_ids_by_week=normalized_population,
                identity_weeks=identity_weeks,
                checkpoint=checkpoint_path,
                max_duration_seconds=max_duration_seconds,
                monotonic=monotonic,
                endpoint_observations=endpoint_observations,
                initial_state=initial_identity_state,
            )
            identity_population_count = sum(map(len, normalized_population.values()))
            completed = len(identity_state.processed_ticket_ids) == identity_population_count
    finally:
        client.close()
    result = {
        "schema_version": 1,
        "sample_size": len(sample),
        "identity_scan": {
            "weeks": identity_weeks,
            "completed": completed,
            "ticket_count": identity_population_count,
            "checked_ticket_count": len(identity_state.processed_ticket_ids),
        },
        "endpoints": _finalize_endpoints(endpoint_observations),
        "identity_candidates": {
            "source_id_path": RATING_SOURCE_ID_PATH,
            "missing_source_id_count": identity_state.missing_source_id_count,
            "collision_count": identity_state.collision_count,
        },
        "survey_observations": _survey_observations(identity_state),
        "agent_field_candidates": [
            {"path": path, "type": value_type}
            for path, value_type in sorted(agent_fields)
        ],
    }
    _validate_contract_mapping(result)
    _atomic_private_json(Path(out), result)
    return result


def _validate_identity_population(
    value: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for week, ticket_ids in sorted(value.items()):
        if not isinstance(week, str) or not week:
            raise ContractProbeError("identity population week is invalid")
        ids = tuple(str(ticket_id).strip() for ticket_id in ticket_ids)
        if any(not ticket_id.isdigit() for ticket_id in ids):
            raise ContractProbeError("identity ticket IDs must contain digits only")
        if seen.intersection(ids):
            raise ContractProbeError("identity population contains duplicate ticket IDs")
        seen.update(ids)
        normalized[week] = ids
    if not normalized or not seen:
        raise ContractProbeError("identity population is empty")
    return normalized


def validate_contract_artifact(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ContractProbeError("contract artifact is invalid") from None
    _validate_contract_mapping(payload)
    return payload


def _require_exact_keys(value: Mapping[str, object], keys: set[str]) -> None:
    if set(value) != keys:
        raise ContractProbeError("contract artifact has unexpected fields")


def _validate_contract_mapping(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise ContractProbeError("contract artifact root is invalid")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "sample_size",
            "identity_scan",
            "endpoints",
            "identity_candidates",
            "survey_observations",
            "agent_field_candidates",
        },
    )
    if payload["schema_version"] != 1 or not isinstance(payload["sample_size"], int):
        raise ContractProbeError("contract artifact version is invalid")
    _validate_identity_scan(payload["identity_scan"])
    _validate_endpoints(payload["endpoints"])
    _validate_identity_candidates(payload["identity_candidates"])
    _validate_survey_observations(payload["survey_observations"])
    _validate_agent_fields(payload["agent_field_candidates"])


def _validate_identity_scan(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ContractProbeError("contract artifact identity scan is invalid")
    _require_exact_keys(
        value, {"weeks", "completed", "ticket_count", "checked_ticket_count"}
    )
    if (
        not isinstance(value["weeks"], int)
        or not isinstance(value["completed"], bool)
        or not isinstance(value["ticket_count"], int)
        or not isinstance(value["checked_ticket_count"], int)
        or value["ticket_count"] < value["checked_ticket_count"]
    ):
        raise ContractProbeError("contract artifact identity counts are invalid")


def _validate_endpoints(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != set(ENDPOINT_NAMES):
        raise ContractProbeError("contract artifact endpoints are invalid")
    for endpoint in value.values():
        if not isinstance(endpoint, Mapping):
            raise ContractProbeError("contract artifact endpoint is invalid")
        _require_exact_keys(endpoint, {"status_counts", "shape"})
        counts = endpoint["status_counts"]
        if not isinstance(counts, Mapping) or any(
            not isinstance(key, str)
            or not key.isdigit()
            or not isinstance(count, int)
            or count < 0
            for key, count in counts.items()
        ):
            raise ContractProbeError("contract artifact status counts are invalid")
        _validate_shape(endpoint["shape"])


def _validate_shape(value: object) -> None:
    if isinstance(value, str):
        if value not in _TYPE_TOKENS:
            raise ContractProbeError("contract artifact shape token is invalid")
        return
    if not isinstance(value, Mapping):
        raise ContractProbeError("contract artifact shape is invalid")
    shape_type = value.get("type")
    if shape_type == "list":
        if not set(value).issubset({"type", "item_shapes", "cardinality"}):
            raise ContractProbeError("contract artifact list shape is invalid")
        if not isinstance(value.get("item_shapes"), list):
            raise ContractProbeError("contract artifact list items are invalid")
        for item in value["item_shapes"]:
            _validate_shape(item)
        cardinality = value.get("cardinality")
        if cardinality is not None and (
            not isinstance(cardinality, Mapping)
            or set(cardinality) != {"min", "max"}
            or any(not isinstance(item, int) or item < 0 for item in cardinality.values())
        ):
            raise ContractProbeError("contract artifact cardinality is invalid")
        return
    if shape_type == "union":
        if set(value) != {"type", "options"} or not isinstance(value["options"], list):
            raise ContractProbeError("contract artifact union shape is invalid")
        for option in value["options"]:
            _validate_shape(option)
        return
    for key, child in value.items():
        if not isinstance(key, str) or not key:
            raise ContractProbeError("contract artifact field name is invalid")
        _validate_shape(child)


def _validate_identity_candidates(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ContractProbeError("contract artifact identity candidates are invalid")
    _require_exact_keys(
        value,
        {
            "source_id_path",
            "missing_source_id_count",
            "collision_count",
        },
    )
    if value["source_id_path"] != RATING_SOURCE_ID_PATH:
        raise ContractProbeError("contract artifact identity paths are invalid")
    if (
        not isinstance(value["missing_source_id_count"], int)
        or value["missing_source_id_count"] < 0
    ):
        raise ContractProbeError("contract artifact missing count is invalid")
    if not isinstance(value["collision_count"], int) or value["collision_count"] < 0:
        raise ContractProbeError("contract artifact collision count is invalid")


def _validate_survey_observations(value: object) -> None:
    if not isinstance(value, list):
        raise ContractProbeError("contract artifact survey observations are invalid")
    for row in value:
        if not isinstance(row, Mapping):
            raise ContractProbeError("contract artifact survey row is invalid")
        _require_exact_keys(
            row, {"survey_id", "rating_raw", "rating_label_raw", "count"}
        )
        if isinstance(row["survey_id"], bool) or not isinstance(
            row["survey_id"], (int, str)
        ):
            raise ContractProbeError("contract artifact survey ID is invalid")
        rating = row["rating_raw"]
        if rating is not None and (
            isinstance(rating, bool) or not isinstance(rating, (int, float))
        ):
            raise ContractProbeError("contract artifact rating token is invalid")
        label = row["rating_label_raw"]
        if label is not None and _safe_survey_label(label) != label:
            raise ContractProbeError("contract artifact rating label is unsafe")
        if not isinstance(row["count"], int) or row["count"] < 1:
            raise ContractProbeError("contract artifact survey count is invalid")


def _validate_agent_fields(value: object) -> None:
    if not isinstance(value, list):
        raise ContractProbeError("contract artifact agent fields are invalid")
    for row in value:
        if not isinstance(row, Mapping):
            raise ContractProbeError("contract artifact agent field is invalid")
        _require_exact_keys(row, {"path", "type"})
        if (
            not isinstance(row["path"], str)
            or not _SAFE_PATH.fullmatch(row["path"])
            or row["type"] not in _TYPE_TOKENS | {"list", "object"}
        ):
            raise ContractProbeError("contract artifact agent field is invalid")


def _load_langfuse_population(
    *, as_of: datetime, weeks: int
) -> dict[str, tuple[str, ...]]:
    from weekly_cs_report.cli import _build_client, load_environment
    from weekly_cs_report.cohort import build_cohort_window, cohort_week_for
    from weekly_cs_report.dimension_verifier import is_ticket_trace
    from weekly_cs_report.pipeline import normalize_raw_traces, select_candidate_sessions

    file_values = dotenv_values(PROJECT_ROOT / ".env")
    names = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
    environment = {
        name: os.environ.get(name, file_values.get(name) or "") for name in names
    }
    settings = load_environment(environment)
    window = build_cohort_window(as_of, weeks, True)
    with _build_client(settings) as client:
        raw = tuple(
            trace
            for trace in client.iter_traces(window.query_from_utc, window.query_to_utc)
            if is_ticket_trace(trace)
        )
    records, issues, _ = normalize_raw_traces(raw)
    selection = select_candidate_sessions(records, issues, window)
    grouped: dict[str, list[str]] = defaultdict(list)
    for ticket_id, traces in selection.eligible.items():
        grouped[cohort_week_for(traces[0].timestamp).isoformat()].append(ticket_id)
    return {week: tuple(sorted(ids)) for week, ids in sorted(grouped.items())}


def _deterministic_sample(
    population: Mapping[str, Sequence[str]], *, weeks: int, size: int
) -> tuple[str, ...]:
    selected_weeks = sorted(population)[-weeks:]
    candidates = {
        str(ticket_id)
        for week in selected_weeks
        for ticket_id in population[week]
    }
    ordered = sorted(
        candidates,
        key=lambda value: (hashlib.sha256(value.encode()).hexdigest(), value),
    )
    if len(ordered) < size:
        raise ContractProbeError("Langfuse population is smaller than schema sample")
    return tuple(ordered[:size])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-weeks", type=int, default=4)
    parser.add_argument("--schema-sample-size", type=int, default=50)
    parser.add_argument("--identity-weeks", type=int, default=13)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not 1 <= args.schema_sample_size <= 100:
            raise ContractProbeError("schema sample size must be between 1 and 100")
        if args.schema_weeks < 1 or args.identity_weeks < args.schema_weeks:
            raise ContractProbeError("week options are invalid")
        settings = load_probe_settings(PROJECT_ROOT / ".env")
        from weekly_cs_report.cohort import VIETNAM_TIMEZONE

        as_of = datetime.now(VIETNAM_TIMEZONE)
        population = _load_langfuse_population(as_of=as_of, weeks=args.identity_weeks)
        sample = _deterministic_sample(
            population,
            weeks=args.schema_weeks,
            size=args.schema_sample_size,
        )
        result = run_contract_probe(
            sample,
            settings,
            transport=httpx.HTTPTransport(retries=0),
            out=args.out,
            identity_ticket_ids_by_week=population,
            identity_weeks=args.identity_weeks,
            checkpoint=args.out.parent / DEFAULT_CHECKPOINT_NAME,
        )
        scan = result["identity_scan"]
        status = (
            "identity_scan_complete" if scan["completed"] else "identity_scan_incomplete"
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "sample_size": result["sample_size"],
                    "ticket_count": scan["ticket_count"],
                    "checked_ticket_count": scan["checked_ticket_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    except ContractProbeError as error:
        print(f"freshdesk_contract_probe_error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
