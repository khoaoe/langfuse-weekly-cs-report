from __future__ import annotations

"""Server-side structured labeling with no prompt/response logging.

This module consumes only the three masked text segments in ``ReopenSession``.
Its cache and evidence are protected artifacts and deliberately have no
dashboard or snapshot dependency.
"""

import json
import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Iterator

from .llm_client import LLMClient
from .models import ReopenLabel
from .reopen_masker import mask_reopen_text
from .reopen_population import ReopenSession


PROMPT_VERSION = "reopen_reason_label.v1"
_CONFIG_NAME = re.compile(r"reopen_labels\.(v[0-9]+)\.json\Z")
_LABEL_KEY = re.compile(r"[a-z][a-z0-9_]*\Z")
_ROOT_FIELDS = frozenset({"version", "created_at", "labels", "abstain_label", "requires_quote"})
_LABEL_FIELDS = frozenset({"key", "display", "definition", "po_action"})
_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: dict[tuple[str, "_CacheKey"], threading.Lock] = {}


class LabelConfigError(RuntimeError):
    pass


class ContentLabelerError(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelDefinition:
    key: str
    display: str
    definition: str
    po_action: str


@dataclass(frozen=True)
class LabelSet:
    version: str
    labels: tuple[LabelDefinition, ...]
    abstain_label: str
    requires_quote: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.version or not self.labels:
            raise ValueError("label set must have a version and labels")
        keys = tuple(item.key for item in self.labels)
        if (
            len(keys) != len(set(keys))
            or any(not _LABEL_KEY.fullmatch(key) for key in keys)
            or self.abstain_label != "other"
            or self.abstain_label in keys
            or self.requires_quote != (self.abstain_label,)
        ):
            raise ValueError("label set is invalid")

    @property
    def allowed_labels(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.labels) + (self.abstain_label,)


@dataclass(frozen=True)
class LabelBatch:
    labels: tuple[ReopenLabel, ...]
    labeled: int
    abstained: int
    invalid: int
    failed: int
    cached: int


def load_label_set(path: Path) -> LabelSet:
    """Read one exact versioned taxonomy, before a client can be created."""
    source = Path(path)
    match = _CONFIG_NAME.fullmatch(source.name)
    if match is None:
        raise LabelConfigError("reopen label configuration is invalid")
    try:
        decoded = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise LabelConfigError("reopen label configuration is invalid") from None
    if not isinstance(decoded, Mapping) or set(decoded) != _ROOT_FIELDS:
        raise LabelConfigError("reopen label configuration is invalid")
    raw_labels = decoded.get("labels")
    if raw_labels == []:
        raise LabelConfigError("reopen label list is empty")
    if not isinstance(raw_labels, list) or not raw_labels:
        raise LabelConfigError("reopen label configuration is invalid")
    version = decoded.get("version")
    created_at = decoded.get("created_at")
    abstain_label = decoded.get("abstain_label")
    requires_quote = decoded.get("requires_quote")
    if (
        not isinstance(version, str)
        or version != match.group(1)
        or not isinstance(created_at, str)
        or not _valid_date(created_at)
        or abstain_label != "other"
        or requires_quote != ["other"]
    ):
        raise LabelConfigError("reopen label configuration is invalid")
    definitions: list[LabelDefinition] = []
    for raw_label in raw_labels:
        if not isinstance(raw_label, Mapping) or set(raw_label) != _LABEL_FIELDS:
            raise LabelConfigError("reopen label configuration is invalid")
        values = tuple(raw_label.get(name) for name in ("key", "display", "definition", "po_action"))
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise LabelConfigError("reopen label configuration is invalid")
        definitions.append(LabelDefinition(*values))  # type: ignore[arg-type]
    try:
        return LabelSet(
            version=version,
            labels=tuple(definitions),
            abstain_label=abstain_label,
            requires_quote=("other",),
        )
    except ValueError:
        raise LabelConfigError("reopen label configuration is invalid") from None


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class _CacheKey:
    session_id: str
    labels_version: str
    prompt_version: str

    def filename(self) -> str:
        canonical = "\x1f".join((self.session_id, self.labels_version, self.prompt_version))
        return sha256(canonical.encode("utf-8")).hexdigest() + ".json"


class LabelCache:
    """Protected cache keyed by session, label taxonomy, and prompt version."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ContentLabelerError("reopen label cache is unavailable")
        self.root.chmod(0o700)
        self._root_identity = str(self.root.resolve())

    @contextmanager
    def key_lock(self, key: _CacheKey) -> Iterator[None]:
        """Serialize one cache miss/fill sequence across cache instances."""
        lock_identity = (self._root_identity, key)
        with _CACHE_LOCKS_GUARD:
            lock = _CACHE_LOCKS.setdefault(lock_identity, threading.Lock())
        with lock:
            yield

    def get(self, key: _CacheKey) -> ReopenLabel | None:
        path = self.root / key.filename()
        if not path.exists() or path.is_symlink() or not path.is_file():
            return None
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
            label = _cached_label(decoded, key)
        except (OSError, ValueError, TypeError):
            return None
        return label

    def put(self, label: ReopenLabel) -> None:
        key = _CacheKey(label.session_id, label.labels_version, label.prompt_version)
        path = self.root / key.filename()
        payload: dict[str, object] = {
            "session_id": label.session_id,
            "labels_version": label.labels_version,
            "prompt_version": label.prompt_version,
            "label": label.label,
            "status": label.status,
        }
        if label.quote is not None:
            payload["quote"] = label.quote
        _write_json_0600(path, payload)


def _cached_label(value: object, key: _CacheKey) -> ReopenLabel | None:
    if not isinstance(value, Mapping) or set(value) - {"session_id", "labels_version", "prompt_version", "label", "status", "quote"}:
        return None
    if (
        value.get("session_id") != key.session_id
        or value.get("labels_version") != key.labels_version
        or value.get("prompt_version") != key.prompt_version
    ):
        return None
    label = value.get("label")
    status = value.get("status")
    quote = value.get("quote")
    if not isinstance(label, str) or not isinstance(status, str) or (quote is not None and not isinstance(quote, str)):
        return None
    try:
        return ReopenLabel(
            session_id=key.session_id,
            labels_version=key.labels_version,
            prompt_version=key.prompt_version,
            label=label,
            status=status,
            quote=quote,
        )
    except ValueError:
        return None


class ContentLabeler:
    def __init__(self, labels: LabelSet, llm_client: LLMClient, cache: LabelCache) -> None:
        self._labels = labels
        self._llm_client = llm_client
        self._cache = cache

    def label_sessions(self, sessions: Sequence[ReopenSession]) -> LabelBatch:
        labels: list[ReopenLabel] = []
        cached = 0
        for session in sessions:
            key = _CacheKey(session.session_id, self._labels.version, PROMPT_VERSION)
            with self._cache.key_lock(key):
                cached_label = self._cache.get(key)
                if cached_label is not None:
                    labels.append(cached_label)
                    cached += 1
                    continue
                labels.append(self._label_one(session))
        return _batch(tuple(labels), cached)

    def _label_one(self, session: ReopenSession) -> ReopenLabel:
        try:
            generated = self._llm_client.generate_structured(
                messages=(_instruction(self._labels), _segments(session)),
                response_schema=_response_schema(self._labels),
            )
        except Exception:
            return _result(session.session_id, self._labels.version, None, "failed")

        label = _validated_result(generated.value, self._labels)
        if label is None:
            return _result(session.session_id, self._labels.version, None, "invalid")
        normalized_label, quote = label
        status = "abstained" if normalized_label == self._labels.abstain_label else "labeled"
        result = _result(
            session.session_id,
            self._labels.version,
            normalized_label,
            status,
            quote=quote,
        )
        self._cache.put(result)
        return result


def _instruction(labels: LabelSet) -> Mapping[str, object]:
    return {
        "role": "system",
        "content": {
            "allowed_labels": labels.allowed_labels,
            "definitions": {item.key: item.definition for item in labels.labels},
            "abstain_label": labels.abstain_label,
            "quote_required_for": labels.requires_quote,
        },
    }


def _segments(session: ReopenSession) -> Mapping[str, object]:
    return {
        "role": "user",
        "content": {
            "initial_user_text": session.initial_user_text,
            "initial_ai_text": session.initial_ai_text,
            "followup_user_text": session.followup_user_text,
        },
    }


def _response_schema(labels: LabelSet) -> Mapping[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "reopen_reason_label",
            "schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": list(labels.allowed_labels)},
                    "quote": {"type": "string"},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
        },
    }


def _validated_result(
    value: Mapping[str, object], labels: LabelSet
) -> tuple[str, str | None] | None:
    if set(value) - {"label", "quote"}:
        return None
    label = value.get("label")
    if not isinstance(label, str) or label not in labels.allowed_labels:
        return None
    quote = value.get("quote")
    if "quote" in value and not isinstance(quote, str):
        return None
    if label == labels.abstain_label:
        if not isinstance(quote, str) or not quote.strip():
            return None
        return label, mask_reopen_text(quote, {})
    return label, None


def _result(
    session_id: str,
    labels_version: str,
    label: str | None,
    status: str,
    *,
    quote: str | None = None,
) -> ReopenLabel:
    return ReopenLabel(
        session_id=session_id,
        labels_version=labels_version,
        prompt_version=PROMPT_VERSION,
        label=label,
        status=status,
        quote=quote,
    )


def _batch(labels: tuple[ReopenLabel, ...], cached: int) -> LabelBatch:
    return LabelBatch(
        labels=labels,
        labeled=sum(item.status == "labeled" for item in labels),
        abstained=sum(item.status == "abstained" for item in labels),
        invalid=sum(item.status == "invalid" for item in labels),
        failed=sum(item.status == "failed" for item in labels),
        cached=cached,
    )


def write_reopen_evidence(
    output_directory: Path,
    sessions: Sequence[ReopenSession],
    labels: Sequence[ReopenLabel],
) -> Path:
    """Write valid-label evidence only; never expose it to a snapshot."""
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise ContentLabelerError("reopen evidence directory is unavailable")
    directory.chmod(0o700)
    by_session = {session.session_id: session for session in sessions}
    records: list[dict[str, object]] = []
    for item in labels:
        if item.status not in {"labeled", "abstained"} or item.label is None:
            continue
        session = by_session.get(item.session_id)
        if session is None:
            raise ContentLabelerError("reopen evidence session is unavailable")
        record: dict[str, object] = {
            "session_id": item.session_id,
            "label": item.label,
            "anchor_trace_id": session.anchor_trace_id,
            "followup_trace_id": session.followup_trace_id,
        }
        if item.label == "other" and item.quote is not None:
            record["quote"] = mask_reopen_text(item.quote, {})
        records.append(record)
    destination = directory / "evidence.json"
    _write_json_0600(destination, records)
    return destination


def _write_json_0600(path: Path, payload: object) -> None:
    destination = Path(path)
    parent = destination.parent
    if (
        parent.is_symlink()
        or not parent.is_dir()
        or destination.is_symlink()
        or (destination.exists() and not destination.is_file())
    ):
        raise ContentLabelerError("reopen protected output is unavailable")

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if destination.is_symlink() or (
            destination.exists() and not destination.is_file()
        ):
            raise ContentLabelerError("reopen protected output is unavailable")
        os.replace(temporary_path, destination)
        temporary_path = None
    except ContentLabelerError:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        raise
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        raise ContentLabelerError("reopen protected output is unavailable") from None
