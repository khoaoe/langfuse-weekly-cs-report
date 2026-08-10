from __future__ import annotations

import stat
from pathlib import Path

from weekly_cs_report.entry_coverage_cache import EntryCoverageRecord
from weekly_cs_report.entry_coverage_checkpoint import (
    CoverageCheckpoint,
    InventoryCheckpoint,
    load_coverage_checkpoint,
    load_inventory_checkpoint,
    write_coverage_checkpoint,
    write_inventory_checkpoint,
)
from weekly_cs_report.freshdesk_entry_coverage import FreshdeskTicketMetadata


def _ticket(ticket_id: str) -> FreshdeskTicketMetadata:
    return FreshdeskTicketMetadata(ticket_id, "2026-07-06T01:00:00Z")


def _record(ticket_id: str) -> EntryCoverageRecord:
    return EntryCoverageRecord(
        ticket_id=ticket_id,
        opened_at="2026-07-06T01:00:00Z",
        cohort_week="2026-07-06",
        status="invoked_no_result",
        human_replied=None,
    )


def test_inventory_checkpoint_round_trips_projected_page_state(tmp_path: Path):
    path = tmp_path / "artifacts" / "inventory_checkpoint.json"
    checkpoint = InventoryCheckpoint(
        source_start_week="2026-07-06",
        updated_since="2026-07-05T17:00:00Z",
        page_size=50,
        next_page=3,
        complete=False,
        tickets=(_ticket("123"), _ticket("456")),
        fingerprint="sha256:" + "a" * 64,
    )

    write_inventory_checkpoint(path, checkpoint)

    assert load_inventory_checkpoint(path) == checkpoint
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text(encoding="utf-8")
    for forbidden in ("subject", "description", "requester", "body", "author_id"):
        assert forbidden not in text


def test_coverage_checkpoint_round_trips_resume_cursor_and_records(tmp_path: Path):
    path = tmp_path / "artifacts" / "coverage_checkpoint.json"
    checkpoint = CoverageCheckpoint(
        source_start_week="2026-07-06",
        inventory_fingerprint="sha256:" + "b" * 64,
        target_weeks=("2026-07-06", "2026-07-13"),
        active_week="2026-07-06",
        next_ticket_index=25,
        completed_weeks=(),
        records=(_record("123"),),
    )

    write_coverage_checkpoint(path, checkpoint)

    assert load_coverage_checkpoint(path) == checkpoint

