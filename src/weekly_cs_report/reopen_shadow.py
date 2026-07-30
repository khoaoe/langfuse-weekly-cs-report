from __future__ import annotations

"""In-memory shadow summary for reopen labels; no model calls live here."""

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re


_LABEL_VERSION = re.compile(r"v[0-9]+\Z")
_LABELS_FILENAME = re.compile(r"reopen_labels\.(v[0-9]+)\.json\Z")
_LABEL = re.compile(r"[a-z0-9_-]{1,64}\Z")
_STATUSES = frozenset({"pending", "labeled", "unavailable"})
_OUTCOMES = frozenset({"ai_end_to_end", "ai_then_cs"})


@dataclass(frozen=True)
class ShadowReasonCount:
    cohort_week: date
    outcome: str
    issue_category: str
    label: str
    count: int
    is_weekend_start: bool = False

    def __post_init__(self) -> None:
        _require_week(self.cohort_week)
        if not isinstance(self.outcome, str) or self.outcome not in _OUTCOMES:
            raise ValueError("reopen shadow outcome is invalid")
        if not isinstance(self.issue_category, str) or not self.issue_category.strip():
            raise ValueError("reopen shadow issue category is invalid")
        if not isinstance(self.label, str) or _LABEL.fullmatch(self.label) is None:
            raise ValueError("reopen shadow label is invalid")
        _require_positive_int(self.count, "count")
        _require_bool(self.is_weekend_start, "weekend")


@dataclass(frozen=True)
class ShadowCoverageCount:
    """Aggregate non-label outcomes without retaining a session identifier."""

    cohort_week: date
    failed: int = 0
    invalid: int = 0
    is_weekend_start: bool = False

    def __post_init__(self) -> None:
        _require_week(self.cohort_week)
        _require_nonnegative_int(self.failed, "failed")
        _require_nonnegative_int(self.invalid, "invalid")
        _require_bool(self.is_weekend_start, "weekend")


@dataclass(frozen=True)
class ReopenReasonShadow:
    labels_version: str
    status: str
    counts: tuple[ShadowReasonCount, ...] = ()
    coverage: tuple[ShadowCoverageCount, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.labels_version, str) or _LABEL_VERSION.fullmatch(self.labels_version) is None:
            raise ValueError("reopen shadow labels version is invalid")
        if not isinstance(self.status, str) or self.status not in _STATUSES:
            raise ValueError("reopen shadow status is invalid")
        if not isinstance(self.counts, tuple) or not all(isinstance(item, ShadowReasonCount) for item in self.counts):
            raise ValueError("reopen shadow counts are invalid")
        if not isinstance(self.coverage, tuple) or not all(isinstance(item, ShadowCoverageCount) for item in self.coverage):
            raise ValueError("reopen shadow coverage is invalid")


def _require_week(value: object) -> None:
    if type(value) is not date:
        raise ValueError("reopen shadow cohort week is invalid")


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"reopen shadow {name} is invalid")


def _require_nonnegative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"reopen shadow {name} is invalid")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"reopen shadow {name} is invalid")


def pending_shadow(config_path: Path) -> ReopenReasonShadow:
    """Read only the version header; an empty taxonomy remains pending."""
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    version = payload.get("version") if isinstance(payload, dict) else None
    filename = _LABELS_FILENAME.fullmatch(Path(config_path).name)
    if (
        not isinstance(version, str)
        or _LABEL_VERSION.fullmatch(version) is None
        or filename is None
        or version != filename.group(1)
    ):
        raise ValueError("reopen shadow configuration is invalid")
    return ReopenReasonShadow(labels_version=version, status="pending")


def unavailable_shadow() -> ReopenReasonShadow:
    return ReopenReasonShadow(labels_version="v1", status="unavailable")
