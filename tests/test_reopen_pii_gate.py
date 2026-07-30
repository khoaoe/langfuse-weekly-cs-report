from __future__ import annotations

import csv
import stat
from collections import Counter
from datetime import date

import pytest

from weekly_cs_report.reopen_population import (
    ReopenControl,
    ReopenPopulation,
    ReopenSession,
)
from weekly_cs_report.reopen_pii_review import (
    PII_REVIEW_FIELDS,
    PII_REVIEW_LIMIT,
    build_pii_review_rows,
    write_pii_review_csv,
)


def _session(index: int) -> ReopenSession:
    return ReopenSession(
        session_id=f"session-{index:03d}",
        anchor_trace_id=f"anchor-{index:03d}",
        followup_trace_id=f"followup-{index:03d}",
        week=date(2026, 7, 20),
        domain="Thanh toán-IBFT",
        outcome="ai_end_to_end",
        initial_user_text=f"initial-{index:03d} [PII]",
        initial_ai_text=f"response-{index:03d} [PII]",
        followup_user_text=f"followup-{index:03d} [PII]",
    )


def _population(*sessions: ReopenSession) -> ReopenPopulation:
    return ReopenPopulation(
        sessions=tuple(sessions),
        excluded_counts={},
        control=ReopenControl(numerator=0, denominator=0, rate=None),
    )


def test_review_rows_are_stable_balanced_bounded_and_hold_no_raw_objects():
    population = _population(*(_session(index) for index in reversed(range(100))))

    first = build_pii_review_rows(population)
    second = build_pii_review_rows(population)

    assert first == second
    assert len(first) == PII_REVIEW_LIMIT == 200
    assert Counter(row.segment for row in first) == {
        "initial_user_text": 67,
        "initial_ai_text": 67,
        "followup_user_text": 66,
    }
    assert [
        (row.session_id, row.segment)
        for row in first[:6]
    ] == [
        ("session-000", "initial_user_text"),
        ("session-000", "initial_ai_text"),
        ("session-000", "followup_user_text"),
        ("session-001", "initial_user_text"),
        ("session-001", "initial_ai_text"),
        ("session-001", "followup_user_text"),
    ]
    assert set(vars(first[0])) == {
        "session_id",
        "trace_id",
        "segment",
        "masked_text",
    }
    assert "initial-000" not in repr(first[0])


def test_zero_review_limit_returns_no_rows():
    assert build_pii_review_rows(_population(_session(1)), limit=0) == ()


def test_writes_only_allowlisted_fields_with_server_side_permissions(tmp_path):
    destination = write_pii_review_csv(tmp_path / "review", _population(_session(1)))

    assert destination == tmp_path / "review" / "pii_review.csv"
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert tuple(rows[0]) == PII_REVIEW_FIELDS
    assert len(rows) == 3
    assert {
        row["segment"]: row["trace_id"]
        for row in rows
    } == {
        "initial_user_text": "anchor-001",
        "initial_ai_text": "anchor-001",
        "followup_user_text": "followup-001",
    }
    assert not {
        "UserID",
        "App user",
        "TransID",
        "Số điện thoại người dùng",
        "domain",
        "outcome",
    } & set(rows[0])


@pytest.mark.parametrize(
    "raw",
    (
        "user@example.com",
        "https://example.com/private",
        "0901234567",
        "4111 1111 1111 1111",
    ),
)
def test_rejects_a_deterministic_pii_pattern_before_review_or_llm_use(raw):
    with pytest.raises(ValueError, match="reopen session text is not masked"):
        ReopenSession(
            session_id="unsafe",
            anchor_trace_id="anchor",
            followup_trace_id="followup",
            week=date(2026, 7, 20),
            domain="domain",
            outcome="ai_end_to_end",
            initial_user_text=raw,
            initial_ai_text="masked [PII]",
            followup_user_text="masked [PII]",
        )
