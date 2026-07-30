from __future__ import annotations

import json
from datetime import date

import pytest

from weekly_cs_report.cli import build_parser, main, run_eval_labels
from weekly_cs_report.content_labeler import LabelDefinition, LabelSet
from weekly_cs_report.llm_client import PIIApprovalRequiredError
from weekly_cs_report.reopen_eval import (
    EvaluationExample,
    GoldenEvaluationError,
    GoldenEvaluationSet,
    evaluate_labels,
    evaluation_payload,
)
from weekly_cs_report.reopen_population import ReopenSession


def _labels() -> LabelSet:
    return LabelSet(
        version="v1",
        labels=(
            LabelDefinition("reason_a", "A", "A", "action-a"),
            LabelDefinition("reason_b", "B", "B", "action-b"),
        ),
        abstain_label="other",
        requires_quote=("other",),
    )


def _session(index: int, *, marker: str | None = None) -> ReopenSession:
    suffix = marker or str(index)
    return ReopenSession(
        session_id=f"session-{index}",
        anchor_trace_id=f"anchor-{index}",
        followup_trace_id=f"followup-{index}",
        week=date(2026, 7, 20),
        domain="IBFT",
        outcome="ai_end_to_end",
        initial_user_text=f"initial-{suffix}",
        initial_ai_text=f"answer-{suffix}",
        followup_user_text=f"followup-{suffix}",
    )


def _example(
    row_id: str,
    index: int,
    human_label: str,
    *,
    group: str | None = None,
    source: str | None = None,
    marker: str | None = None,
) -> EvaluationExample:
    return EvaluationExample(
        row_id=row_id,
        session=_session(index, marker=marker),
        human_label=human_label,
        duplicate_group_id=group,
        duplicate_source_row_id=source,
    )


class FakePredictionClient:
    def __init__(self, predictions):
        self.predictions = predictions
        self.calls = []

    def predict_label(self, session, labels):
        self.calls.append(session.initial_user_text)
        return self.predictions[session.initial_user_text]


def test_public_eval_helper_fails_closed_without_explicit_pii_approval():
    client = FakePredictionClient({})

    with pytest.raises(PIIApprovalRequiredError, match="pii approval required"):
        run_eval_labels(GoldenEvaluationSet("v1", ()), _labels(), client)

    assert client.calls == []


def test_human_consistency_below_threshold_refuses_model_evaluation():
    examples = []
    for index in range(20):
        source_id = f"source-{index}"
        group = f"group-{index}"
        examples.append(_example(source_id, index, "reason_a", group=group))
        examples.append(
            _example(
                f"duplicate-{index}",
                index,
                "reason_a" if index < 16 else "reason_b",
                group=group,
                source=source_id,
            )
        )
    client = FakePredictionClient({})

    report = evaluate_labels(
        GoldenEvaluationSet("v1", tuple(examples)),
        _labels(),
        client,
    )

    assert report.status == "human_consistency_failed"
    assert report.human_consistency == 0.8
    assert report.gate_passed is False
    assert report.overall_accuracy is None
    assert client.calls == []


def test_hidden_duplicate_must_have_identical_masked_content_before_evaluation():
    examples = (
        _example(
            "source",
            0,
            "reason_a",
            group="group-0",
            marker="original",
        ),
        _example(
            "duplicate",
            0,
            "reason_a",
            group="group-0",
            source="source",
            marker="changed-content",
        ),
    )
    client = FakePredictionClient({})

    with pytest.raises(
        GoldenEvaluationError,
        match="golden evaluation data is invalid",
    ):
        evaluate_labels(GoldenEvaluationSet("v1", examples), _labels(), client)

    assert client.calls == []


def test_deduplicates_by_manifest_group_in_row_order_and_computes_metrics():
    examples = [
        _example(
            "duplicate-first",
            0,
            "reason_a",
            group="group-0",
            source="source-later",
            marker="same-content",
        ),
        _example(
            "source-later",
            0,
            "reason_a",
            group="group-0",
            marker="same-content",
        ),
    ]
    predictions = {"initial-same-content": "reason_a"}
    for index in range(1, 20):
        true_label = "reason_a" if index < 10 else "reason_b"
        examples.append(_example(f"row-{index}", index, true_label))
        if index < 8:
            predicted = "reason_a"
        elif index < 10:
            predicted = "reason_b"
        else:
            predicted = "reason_b"
        predictions[f"initial-{index}"] = predicted
    client = FakePredictionClient(predictions)

    report = evaluate_labels(
        GoldenEvaluationSet("v1", tuple(examples)),
        _labels(),
        client,
    )

    assert report.status == "evaluated"
    assert report.model_denominator == 20
    assert len(client.calls) == 20
    assert client.calls[0] == "initial-same-content"
    assert client.calls.count("initial-same-content") == 1
    assert report.overall_accuracy == 0.9
    assert report.label_metrics["reason_a"].support == 10
    assert report.label_metrics["reason_a"].recall == 0.8
    assert report.label_metrics["reason_a"].precision == 1.0
    assert report.label_metrics["reason_a"].verified is True
    assert report.label_metrics["reason_b"].support == 10
    assert report.label_metrics["reason_b"].recall == 1.0
    assert report.label_metrics["reason_b"].precision == 10 / 12
    assert report.confusion_matrix["reason_a"]["reason_b"] == 2
    assert report.abstention_rate == 0.0
    assert report.gate_passed is True


def test_support_below_ten_is_unverified_and_does_not_fail_gate():
    examples = [
        _example("source-0", 0, "reason_a", group="group-0"),
        _example(
            "duplicate-0",
            0,
            "reason_a",
            group="group-0",
            source="source-0",
        ),
    ]
    predictions = {"initial-0": "reason_a"}
    for index in range(1, 11):
        label = "reason_a" if index < 10 else "reason_b"
        examples.append(_example(f"row-{index}", index, label))
        predictions[f"initial-{index}"] = (
            "reason_a" if label == "reason_a" else "reason_a"
        )
    client = FakePredictionClient(predictions)

    report = evaluate_labels(
        GoldenEvaluationSet("v1", tuple(examples)),
        _labels(),
        client,
    )

    assert report.overall_accuracy == 10 / 11
    assert report.label_metrics["reason_a"].verified is True
    assert report.label_metrics["reason_a"].passes_gate is True
    assert report.label_metrics["reason_b"].support == 1
    assert report.label_metrics["reason_b"].recall == 0.0
    assert report.label_metrics["reason_b"].verified is False
    assert report.label_metrics["reason_b"].passes_gate is None
    assert report.gate_passed is True


def test_all_three_model_thresholds_are_inclusive_and_payload_is_aggregate_only():
    examples = [
        _example("source-0", 0, "reason_a", group="group-0"),
        _example(
            "duplicate-0",
            0,
            "reason_a",
            group="group-0",
            source="source-0",
        ),
    ]
    predictions = {"initial-0": "reason_a"}
    for index in range(1, 20):
        label = "reason_a" if index < 10 else "reason_b"
        examples.append(_example(f"row-{index}", index, label))
        if label == "reason_b":
            predicted = "reason_b"
        elif index < 6:
            predicted = "reason_a"
        elif index < 9:
            predicted = "other"
        else:
            predicted = "reason_b"
        predictions[f"initial-{index}"] = predicted

    report = evaluate_labels(
        GoldenEvaluationSet("v1", tuple(examples)),
        _labels(),
        FakePredictionClient(predictions),
    )
    payload = evaluation_payload(report)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert report.overall_accuracy == 0.8
    assert report.label_metrics["reason_a"].recall == 0.6
    assert report.abstention_rate == 0.15
    assert report.gate_passed is True
    assert set(payload) == {
        "status",
        "human_consistency",
        "model_denominator",
        "overall_accuracy",
        "abstention_rate",
        "label_metrics",
        "confusion_matrix",
        "gate_passed",
    }
    assert "initial-" not in encoded
    assert "followup-" not in encoded
    assert "session-" not in encoded
    assert "row_id" not in encoded


def test_eval_labels_parser_and_empty_config_fail_before_any_client(
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
        [
            "eval-labels",
            "--golden",
            str(tmp_path / "golden"),
            "--labels",
            str(labels_path),
        ]
    )
    assert args.command == "eval-labels"

    def forbidden(*args, **kwargs):
        raise AssertionError("client must not be created")

    monkeypatch.setattr("weekly_cs_report.cli.load_environment", forbidden)
    exit_code = main(
        [
            "eval-labels",
            "--golden",
            str(tmp_path / "golden"),
            "--labels",
            str(labels_path),
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == "reopen label list is empty\n"


def test_eval_labels_missing_golden_then_pii_gate_fail_before_any_client(
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
                        "key": "reason_a",
                        "display": "A",
                        "definition": "A",
                        "po_action": "A",
                    }
                ],
                "abstain_label": "other",
                "requires_quote": ["other"],
            }
        ),
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("client must not be created")

    monkeypatch.setattr("weekly_cs_report.cli.load_environment", forbidden)
    missing = tmp_path / "missing-golden"
    exit_code = main(
        [
            "eval-labels",
            "--golden",
            str(missing),
            "--labels",
            str(labels_path),
        ]
    )
    first_output = capsys.readouterr()

    assert exit_code == 2
    assert first_output.err == "golden evaluation artifact is unavailable\n"

    monkeypatch.setattr(
        "weekly_cs_report.cli.load_golden_evaluation",
        lambda directory, labels: GoldenEvaluationSet("v1", ()),
    )
    exit_code = main(
        [
            "eval-labels",
            "--golden",
            str(tmp_path / "golden"),
            "--labels",
            str(labels_path),
        ]
    )
    second_output = capsys.readouterr()

    assert exit_code == 2
    assert second_output.out == ""
    assert second_output.err == "pii approval required\n"
