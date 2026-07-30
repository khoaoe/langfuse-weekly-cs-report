from __future__ import annotations

import csv
import json
import random
import stat
from datetime import date

import pytest

from weekly_cs_report.cli import build_parser, main
from weekly_cs_report.content_labeler import LabelDefinition, LabelSet
from weekly_cs_report.reopen_golden import (
    GOLDEN_CSV_FIELDS,
    GoldenSampleError,
    sample_golden,
    write_golden_sample,
)
from weekly_cs_report.reopen_population import (
    ReopenControl,
    ReopenPopulation,
    ReopenSession,
)


def _labels() -> LabelSet:
    return LabelSet(
        version="v1",
        labels=(
            LabelDefinition(
                key="ai_wrong_content",
                display="AI trả lời sai",
                definition="Nội dung AI sai",
                po_action="Sửa skill",
            ),
        ),
        abstain_label="other",
        requires_quote=("other",),
    )


def _session(index: int) -> ReopenSession:
    return ReopenSession(
        session_id=f"session-{index:03d}",
        anchor_trace_id=f"anchor-{index:03d}",
        followup_trace_id=f"followup-{index:03d}",
        week=date(2026, 7, 20 + index % 2),
        domain=f"domain-{index % 5}",
        outcome="ai_end_to_end" if index % 2 else "ai_then_cs",
        initial_user_text=f"masked initial {index} [PII]",
        initial_ai_text=f"masked response {index} [PII]",
        followup_user_text=f"masked followup {index} [PII]",
    )


def _population(count: int) -> ReopenPopulation:
    return ReopenPopulation(
        sessions=tuple(_session(index) for index in range(count)),
        excluded_counts={},
        control=ReopenControl(numerator=0, denominator=0, rate=None),
    )


def _id_factory():
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"opaque-{counter:04d}"

    return next_id


def test_n_is_total_rows_with_hidden_duplicates_from_one_unstratified_sample():
    discovery_ids = {f"session-{index:03d}" for index in range(10)}
    sample = sample_golden(
        _population(230),
        _labels(),
        discovery_session_ids=discovery_ids,
        n=200,
        rng=random.Random(20260730),
        id_factory=_id_factory(),
    )

    assert len(sample.rows) == 200
    assert len(sample.manifest) == 200
    assert sample.duplicate_count == 30
    assert sample.model_denominator == 170
    assert len({entry.session_id for entry in sample.manifest.values()}) == 170
    assert not discovery_ids & {
        entry.session_id for entry in sample.manifest.values()
    }

    grouped: dict[str, list[tuple[str, object]]] = {}
    duplicate_positions = []
    for position, row in enumerate(sample.rows):
        entry = sample.manifest[row.row_id]
        if entry.duplicate_group_id is not None:
            grouped.setdefault(entry.duplicate_group_id, []).append(
                (row.row_id, entry)
            )
        if entry.duplicate_source_row_id is not None:
            duplicate_positions.append(position)

    assert len(grouped) == 30
    assert all(len(group) == 2 for group in grouped.values())
    for group in grouped.values():
        primary = next(item for item in group if item[1].duplicate_source_row_id is None)
        duplicate = next(item for item in group if item[1].duplicate_source_row_id is not None)
        assert duplicate[1].duplicate_source_row_id == primary[0]
        assert duplicate[1].session_id == primary[1].session_id
    assert duplicate_positions != list(range(170, 200))
    assert all(
        row.human_label == ""
        and row.row_id.startswith("opaque-")
        and "session-" not in row.row_id
        for row in sample.rows
    )


def test_writes_po_csv_and_private_manifest_with_exact_boundaries(tmp_path):
    sample = sample_golden(
        _population(10),
        _labels(),
        discovery_session_ids=set(),
        n=10,
        rng=random.Random(7),
        id_factory=_id_factory(),
    )

    csv_path, manifest_path = write_golden_sample(tmp_path / "golden", sample)

    assert csv_path.name == "golden.csv"
    assert manifest_path.name == "golden_manifest.json"
    assert stat.S_IMODE(csv_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(csv_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600

    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert tuple(rows[0]) == GOLDEN_CSV_FIELDS
    assert len(rows) == 10
    assert all(row["human_label"] == "" for row in rows)
    forbidden = {
        "session_id",
        "trace_id",
        "anchor_trace_id",
        "followup_trace_id",
        "domain",
        "outcome",
        "model_label",
        "duplicate",
        "duplicate_group_id",
        "duplicate_source_row_id",
    }
    assert not forbidden & set(rows[0])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["labels_version"] == "v1"
    assert set(manifest["rows"]) == {row["row_id"] for row in rows}
    assert set(next(iter(manifest["rows"].values()))) == {
        "session_id",
        "anchor_trace_id",
        "followup_trace_id",
        "week",
        "domain",
        "outcome",
        "duplicate_group_id",
        "duplicate_source_row_id",
    }
    assert "masked initial" not in manifest_path.read_text(encoding="utf-8")
    assert "session-" not in csv_path.read_text(encoding="utf-8")


def test_fails_when_full_population_after_discovery_cannot_fill_unique_denominator():
    with pytest.raises(
        GoldenSampleError,
        match="golden population is too small",
    ):
        sample_golden(
            _population(169),
            _labels(),
            discovery_session_ids=set(),
            n=200,
            rng=random.Random(1),
            id_factory=_id_factory(),
        )


def test_sample_golden_parser_and_empty_labels_fail_before_langfuse_or_model(
    tmp_path, monkeypatch, capsys
):
    labels_path = tmp_path / "reopen_labels.v1.json"
    labels_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "created_at": "2026-07-30",
                "labels": [],
                "abstain_label": "other",
                "requires_quote": ["other"],
            }
        ),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        ["sample-golden", "--n", "200", "--out", str(tmp_path / "golden")]
    )
    assert args.command == "sample-golden"
    assert args.n == 200
    assert args.out == tmp_path / "golden"

    def forbidden(*args, **kwargs):
        raise AssertionError("Langfuse/model must not be touched")

    monkeypatch.setattr("weekly_cs_report.cli.REOPEN_LABELS_PATH", labels_path)
    monkeypatch.setattr("weekly_cs_report.cli.load_environment", forbidden)
    monkeypatch.setattr(
        "weekly_cs_report.llm_client.LLMSettings.from_environment",
        forbidden,
    )

    exit_code = main(
        ["sample-golden", "--n", "200", "--out", str(tmp_path / "golden")]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == "reopen label list is empty\n"
    assert not (tmp_path / "golden").exists()


def test_sample_golden_missing_discovery_fails_before_langfuse_or_model(
    tmp_path, monkeypatch, capsys
):
    labels_path = tmp_path / "reopen_labels.v1.json"
    labels_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "created_at": "2026-07-30",
                "labels": [
                    {
                        "key": "ai_wrong_content",
                        "display": "AI trả lời sai",
                        "definition": "Nội dung AI sai",
                        "po_action": "Sửa skill",
                    }
                ],
                "abstain_label": "other",
                "requires_quote": ["other"],
            }
        ),
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Langfuse/model must not be touched")

    monkeypatch.setattr("weekly_cs_report.cli.REOPEN_LABELS_PATH", labels_path)
    monkeypatch.setattr(
        "weekly_cs_report.cli.REOPEN_DISCOVERY_PATH",
        tmp_path / "missing" / "reasons.csv",
    )
    monkeypatch.setattr("weekly_cs_report.cli.load_environment", forbidden)
    monkeypatch.setattr(
        "weekly_cs_report.llm_client.LLMSettings.from_environment",
        forbidden,
    )

    exit_code = main(
        ["sample-golden", "--n", "200", "--out", str(tmp_path / "golden")]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == "reopen discovery artifact is unavailable\n"
