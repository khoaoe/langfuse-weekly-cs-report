from __future__ import annotations

"""Fail-closed parsing of Freshdesk's AI post-review (hậu kiểm) custom fields."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

from .freshdesk_entry_coverage import FreshdeskTicketMetadata, _cohort_week


_CONFIG_KEYS = frozenset(
    {"schema_version", "approved_by", "approved_at", "notes", "rating_labels"}
)
_REOPEN_NOT_REPLIED = "Chưa phản hồi Private Note"
# Freshdesk emits the bare "Đã phản hồi" alongside the "Private Note" wording
# (observed live 2026-09-09). Both say replied without naming a count, so both
# map to (True, None) -- the count stays unknown rather than invented.
_REOPEN_REPLIED_UNSPECIFIED = frozenset({"Đã phản hồi Private Note", "Đã phản hồi"})
_REOPEN_REPLIED_N = re.compile(r"Đã phản hồi (\d{1,2})\Z")
_USER_REPLIED = "Đã trả lời cho User"
_USER_NOT_REPLIED = "Chưa trả lời cho User"
_RATING_SLUGS = frozenset({"satisfied", "satisfied_with_edit", "needs_edit"})


class AIReviewError(RuntimeError):
    """A sanitized AI post-review contract error."""


@dataclass(frozen=True)
class AIReviewLabelConfig:
    rating_labels: Mapping[str, str]

    def slug_for(self, raw_label: str) -> str:
        slug = self.rating_labels.get(raw_label)
        if slug is None:
            raise AIReviewError(
                "Freshdesk AI review rating label is not approved: "
                f"{_quoted(raw_label)}"
            )
        return slug


@dataclass(frozen=True)
class AIReviewRecord:
    ticket_id: str
    opened_at: str
    cohort_week: str
    rating: str | None
    review_count: int | None
    review_date: str | None
    reopen_replied: bool | None
    reopen_reply_count: int | None
    user_replied: bool | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ticket_id, str)
            or not self.ticket_id.isdigit()
            or (self.rating is not None and self.rating not in _RATING_SLUGS)
            or (
                self.review_count is not None
                and (
                    not isinstance(self.review_count, int)
                    or isinstance(self.review_count, bool)
                    or not 0 <= self.review_count <= 15
                )
            )
            or (
                self.reopen_replied is not None
                and not isinstance(self.reopen_replied, bool)
            )
            or (self.reopen_replied is not True and self.reopen_reply_count is not None)
            or (
                self.reopen_reply_count is not None
                and (
                    not isinstance(self.reopen_reply_count, int)
                    or isinstance(self.reopen_reply_count, bool)
                    or not 1 <= self.reopen_reply_count <= 20
                )
            )
            or (
                self.user_replied is not None
                and not isinstance(self.user_replied, bool)
            )
        ):
            raise AIReviewError("Freshdesk AI review record is invalid")
        _validate_utc_timestamp(self.opened_at)
        try:
            date.fromisoformat(self.cohort_week)
        except ValueError:
            raise AIReviewError("Freshdesk AI review record is invalid") from None
        if self.review_date is not None:
            try:
                date.fromisoformat(self.review_date)
            except ValueError:
                raise AIReviewError("Freshdesk AI review record is invalid") from None


def _validate_utc_timestamp(value: str) -> None:
    if not isinstance(value, str):
        raise AIReviewError("Freshdesk AI review record is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise AIReviewError("Freshdesk AI review record is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AIReviewError("Freshdesk AI review record is invalid")


def load_ai_review_label_config(path: Path) -> AIReviewLabelConfig:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AIReviewError("Freshdesk AI review label config is invalid") from None
    if not isinstance(value, Mapping) or set(value) != _CONFIG_KEYS:
        raise AIReviewError("Freshdesk AI review label config is invalid")
    if (
        value["schema_version"] != 1
        or value["approved_by"] != "PO"
        or not isinstance(value["approved_at"], str)
        or not isinstance(value["notes"], str)
    ):
        raise AIReviewError("Freshdesk AI review label config is invalid")
    try:
        date.fromisoformat(value["approved_at"])
    except ValueError:
        raise AIReviewError("Freshdesk AI review label config is invalid") from None
    raw_labels = value["rating_labels"]
    if (
        not isinstance(raw_labels, Mapping)
        or not raw_labels
        or any(
            not isinstance(key, str) or not isinstance(item, str) or not key or not item
            for key, item in raw_labels.items()
        )
        or set(raw_labels.values()) - _RATING_SLUGS
    ):
        raise AIReviewError("Freshdesk AI review label config is invalid")
    return AIReviewLabelConfig(rating_labels=dict(raw_labels))


def _quoted(raw: object) -> str:
    # These are Freshdesk dropdown labels, not free text, so naming the
    # offending value is safe and is the only way a fail-closed abort is
    # diagnosable. Truncated in case the field ever carries something longer.
    text = raw if isinstance(raw, str) else repr(raw)
    return f"{text[:60]!r}"


def parse_reopen_status(raw: str) -> tuple[bool, int | None]:
    if raw == _REOPEN_NOT_REPLIED:
        return False, None
    if raw in _REOPEN_REPLIED_UNSPECIFIED:
        return True, None
    match = _REOPEN_REPLIED_N.fullmatch(raw)
    if match is None:
        raise AIReviewError(f"Freshdesk AI reopen status is invalid: {_quoted(raw)}")
    count = int(match.group(1))
    if not 1 <= count <= 20:
        raise AIReviewError(f"Freshdesk AI reopen status is invalid: {_quoted(raw)}")
    return True, count


def parse_user_replied(raw: str) -> bool:
    if raw == _USER_REPLIED:
        return True
    if raw == _USER_NOT_REPLIED:
        return False
    raise AIReviewError(
        f"Freshdesk AI user-replied status is invalid: {_quoted(raw)}"
    )


def build_ai_review_record(
    ticket: FreshdeskTicketMetadata,
    labels: AIReviewLabelConfig,
) -> AIReviewRecord:
    rating = (
        labels.slug_for(ticket.ai_review_rating_raw)
        if ticket.ai_review_rating_raw is not None
        else None
    )
    review_count = None
    if ticket.ai_review_count_raw is not None:
        if not ticket.ai_review_count_raw.isdigit():
            raise AIReviewError(
                "Freshdesk AI review count is invalid: "
                f"{_quoted(ticket.ai_review_count_raw)}"
            )
        review_count = int(ticket.ai_review_count_raw)
    reopen_replied: bool | None = None
    reopen_reply_count: int | None = None
    if ticket.ai_reopen_status_raw is not None:
        reopen_replied, reopen_reply_count = parse_reopen_status(
            ticket.ai_reopen_status_raw
        )
    user_replied = (
        parse_user_replied(ticket.ai_user_replied_raw)
        if ticket.ai_user_replied_raw is not None
        else None
    )
    return AIReviewRecord(
        ticket_id=ticket.ticket_id,
        opened_at=ticket.created_at,
        cohort_week=_cohort_week(ticket.created_at),
        rating=rating,
        review_count=review_count,
        review_date=ticket.ai_review_date_raw,
        reopen_replied=reopen_replied,
        reopen_reply_count=reopen_reply_count,
        user_replied=user_replied,
    )


def _demo() -> None:
    labels = AIReviewLabelConfig(
        rating_labels={"Hài Lòng": "satisfied", "Cần chỉnh sửa": "needs_edit"}
    )
    ticket = FreshdeskTicketMetadata(
        ticket_id="1",
        created_at="2026-08-24T01:00:00Z",
        ai_review_rating_raw="Hài Lòng",
        ai_review_count_raw="0",
        ai_reopen_status_raw="Đã phản hồi 3",
        ai_user_replied_raw="Đã trả lời cho User",
    )
    record = build_ai_review_record(ticket, labels)
    assert record.opened_at == "2026-08-24T01:00:00Z"
    assert record.rating == "satisfied"
    assert record.review_count == 0
    assert record.reopen_replied is True
    assert record.reopen_reply_count == 3
    assert record.user_replied is True
    try:
        build_ai_review_record(
            FreshdeskTicketMetadata(
                ticket_id="2",
                created_at="2026-08-24T01:00:00Z",
                ai_review_rating_raw="Không rõ",
            ),
            labels,
        )
    except AIReviewError:
        pass
    else:
        raise AssertionError("expected fail-closed on unapproved rating label")


if __name__ == "__main__":
    _demo()
