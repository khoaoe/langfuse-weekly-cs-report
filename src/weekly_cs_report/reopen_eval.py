from __future__ import annotations

"""Offline evaluation for the fixed reopen-reason label taxonomy."""

import csv
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import stat
from typing import Mapping, Protocol, Sequence

from .content_labeler import LabelSet
from .reopen_golden import GOLDEN_CSV_FIELDS
from .reopen_masker import mask_reopen_text
from .reopen_population import ReopenSession


HUMAN_CONSISTENCY_THRESHOLD = 0.85
OVERALL_ACCURACY_THRESHOLD = 0.80
LABEL_RECALL_THRESHOLD = 0.60
ABSTENTION_THRESHOLD = 0.15
VERIFIED_SUPPORT = 10
_MANIFEST_FIELDS = frozenset(
    {
        "session_id",
        "anchor_trace_id",
        "followup_trace_id",
        "week",
        "domain",
        "outcome",
        "duplicate_group_id",
        "duplicate_source_row_id",
    }
)


class GoldenEvaluationError(RuntimeError):
    """Fixed, payload-free evaluation input or prediction failure."""


class LabelPredictionClient(Protocol):
    def predict_label(self, session: ReopenSession, labels: LabelSet) -> str:
        ...


@dataclass(frozen=True)
class EvaluationExample:
    row_id: str
    session: ReopenSession = field(repr=False)
    human_label: str
    duplicate_group_id: str | None
    duplicate_source_row_id: str | None


@dataclass(frozen=True)
class GoldenEvaluationSet:
    labels_version: str
    examples: tuple[EvaluationExample, ...]


@dataclass(frozen=True)
class LabelMetric:
    support: int
    true_positive: int
    predicted: int
    recall: float | None
    precision: float | None
    verified: bool
    passes_gate: bool | None


@dataclass(frozen=True)
class EvaluationReport:
    status: str
    human_consistency: float
    model_denominator: int
    overall_accuracy: float | None
    abstention_rate: float | None
    label_metrics: Mapping[str, LabelMetric]
    confusion_matrix: Mapping[str, Mapping[str, int]]
    gate_passed: bool


def evaluate_labels(
    golden: GoldenEvaluationSet,
    labels: LabelSet,
    client: LabelPredictionClient,
) -> EvaluationReport:
    """Measure human consistency first, then evaluate deduplicated examples."""
    if golden.labels_version != labels.version:
        raise GoldenEvaluationError("golden labels version is invalid")
    _validate_examples(golden.examples, labels)
    groups = _duplicate_groups(golden.examples)
    human_consistency = sum(
        len({example.human_label for example in group}) == 1
        for group in groups.values()
    ) / len(groups)
    deduplicated = _deduplicate_first(golden.examples)

    if human_consistency < HUMAN_CONSISTENCY_THRESHOLD:
        return EvaluationReport(
            status="human_consistency_failed",
            human_consistency=human_consistency,
            model_denominator=len(deduplicated),
            overall_accuracy=None,
            abstention_rate=None,
            label_metrics={},
            confusion_matrix={},
            gate_passed=False,
        )

    predictions: list[str] = []
    try:
        for example in deduplicated:
            prediction = client.predict_label(example.session, labels)
            if prediction not in labels.allowed_labels:
                raise GoldenEvaluationError("label evaluation response is invalid")
            predictions.append(prediction)
    except GoldenEvaluationError:
        raise
    except Exception:
        raise GoldenEvaluationError("label evaluation unavailable") from None

    true_labels = tuple(example.human_label for example in deduplicated)
    denominator = len(true_labels)
    confusion = {
        true_label: {
            predicted_label: sum(
                observed_true == true_label and observed_prediction == predicted_label
                for observed_true, observed_prediction in zip(true_labels, predictions)
            )
            for predicted_label in labels.allowed_labels
        }
        for true_label in labels.allowed_labels
    }
    metrics = {
        label: _label_metric(label, true_labels, predictions)
        for label in labels.allowed_labels
    }
    overall_accuracy = sum(
        true_label == prediction
        for true_label, prediction in zip(true_labels, predictions)
    ) / denominator
    abstention_rate = predictions.count(labels.abstain_label) / denominator
    verified_recalls_pass = all(
        metric.passes_gate is not False
        for metric in metrics.values()
    )
    gate_passed = (
        human_consistency >= HUMAN_CONSISTENCY_THRESHOLD
        and overall_accuracy >= OVERALL_ACCURACY_THRESHOLD
        and verified_recalls_pass
        and abstention_rate <= ABSTENTION_THRESHOLD
    )
    return EvaluationReport(
        status="evaluated",
        human_consistency=human_consistency,
        model_denominator=denominator,
        overall_accuracy=overall_accuracy,
        abstention_rate=abstention_rate,
        label_metrics=metrics,
        confusion_matrix=confusion,
        gate_passed=gate_passed,
    )


def evaluation_payload(report: EvaluationReport) -> dict[str, object]:
    """Return only aggregate values safe for CLI output."""
    return {
        "status": report.status,
        "human_consistency": report.human_consistency,
        "model_denominator": report.model_denominator,
        "overall_accuracy": report.overall_accuracy,
        "abstention_rate": report.abstention_rate,
        "label_metrics": {
            label: {
                "support": metric.support,
                "true_positive": metric.true_positive,
                "predicted": metric.predicted,
                "recall": metric.recall,
                "precision": metric.precision,
                "verified": metric.verified,
                "passes_gate": metric.passes_gate,
            }
            for label, metric in report.label_metrics.items()
        },
        "confusion_matrix": {
            true_label: dict(predictions)
            for true_label, predictions in report.confusion_matrix.items()
        },
        "gate_passed": report.gate_passed,
    }


def load_golden_evaluation(
    directory: Path,
    labels: LabelSet,
) -> GoldenEvaluationSet:
    """Load protected golden artifacts while preserving CSV occurrence order."""
    root = Path(directory)
    csv_path = root / "golden.csv"
    manifest_path = root / "golden_manifest.json"
    if (
        root.is_symlink()
        or not root.is_dir()
        or stat.S_IMODE(root.stat().st_mode) != 0o700
        or not _protected_file(csv_path)
        or not _protected_file(manifest_path)
    ):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != GOLDEN_CSV_FIELDS:
                raise GoldenEvaluationError(
                    "golden evaluation artifact is unavailable"
                )
            csv_rows = list(reader)
    except (OSError, ValueError, csv.Error):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable") from None

    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != {"labels_version", "rows"}
        or manifest.get("labels_version") != labels.version
        or not isinstance(manifest.get("rows"), Mapping)
    ):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable")
    manifest_rows = manifest["rows"]
    assert isinstance(manifest_rows, Mapping)

    examples: list[EvaluationExample] = []
    seen_row_ids: set[str] = set()
    for row in csv_rows:
        row_id = row.get("row_id")
        if (
            not isinstance(row_id, str)
            or not row_id
            or row_id in seen_row_ids
            or row.get("human_label") not in labels.allowed_labels
        ):
            raise GoldenEvaluationError("golden evaluation artifact is unavailable")
        seen_row_ids.add(row_id)
        raw_entry = manifest_rows.get(row_id)
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != _MANIFEST_FIELDS:
            raise GoldenEvaluationError("golden evaluation artifact is unavailable")
        examples.append(_loaded_example(row, raw_entry))
    if not examples or seen_row_ids != set(manifest_rows):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable")
    evaluation = GoldenEvaluationSet(labels.version, tuple(examples))
    _validate_examples(evaluation.examples, labels)
    return evaluation


def _loaded_example(
    row: Mapping[str, str],
    manifest: Mapping[str, object],
) -> EvaluationExample:
    required_strings = (
        row.get("initial_user_text"),
        row.get("initial_ai_text"),
        row.get("followup_user_text"),
        manifest.get("session_id"),
        manifest.get("anchor_trace_id"),
        manifest.get("followup_trace_id"),
        manifest.get("week"),
        manifest.get("domain"),
        manifest.get("outcome"),
    )
    if any(not isinstance(value, str) or not value for value in required_strings):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable")
    group = manifest.get("duplicate_group_id")
    source = manifest.get("duplicate_source_row_id")
    if (
        (group is not None and (not isinstance(group, str) or not group))
        or (source is not None and (not isinstance(source, str) or not source))
    ):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable")
    try:
        week = date.fromisoformat(manifest["week"])  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise GoldenEvaluationError("golden evaluation artifact is unavailable") from None
    return EvaluationExample(
        row_id=row["row_id"],
        session=ReopenSession(
            session_id=manifest["session_id"],  # type: ignore[arg-type]
            anchor_trace_id=manifest["anchor_trace_id"],  # type: ignore[arg-type]
            followup_trace_id=manifest["followup_trace_id"],  # type: ignore[arg-type]
            week=week,
            domain=manifest["domain"],  # type: ignore[arg-type]
            outcome=manifest["outcome"],  # type: ignore[arg-type]
            initial_user_text=row["initial_user_text"],
            initial_ai_text=row["initial_ai_text"],
            followup_user_text=row["followup_user_text"],
        ),
        human_label=row["human_label"],
        duplicate_group_id=group,
        duplicate_source_row_id=source,
    )


def _protected_file(path: Path) -> bool:
    return (
        not path.is_symlink()
        and path.is_file()
        and stat.S_IMODE(path.stat().st_mode) == 0o600
    )


def _validate_examples(
    examples: Sequence[EvaluationExample],
    labels: LabelSet,
) -> None:
    if not examples:
        raise GoldenEvaluationError("golden evaluation data is invalid")
    row_ids = {example.row_id for example in examples}
    if len(row_ids) != len(examples):
        raise GoldenEvaluationError("golden evaluation data is invalid")
    for example in examples:
        if (
            not example.row_id
            or example.human_label not in labels.allowed_labels
            or (
                example.duplicate_source_row_id is not None
                and example.duplicate_source_row_id not in row_ids
            )
        ):
            raise GoldenEvaluationError("golden evaluation data is invalid")
        for text in (
            example.session.initial_user_text,
            example.session.initial_ai_text,
            example.session.followup_user_text,
        ):
            if not text or mask_reopen_text(text, {}) != text:
                raise GoldenEvaluationError("golden evaluation data is invalid")
    _duplicate_groups(examples)


def _duplicate_groups(
    examples: Sequence[EvaluationExample],
) -> dict[str, tuple[EvaluationExample, ...]]:
    groups: dict[str, list[EvaluationExample]] = {}
    for example in examples:
        if example.duplicate_group_id is not None:
            groups.setdefault(example.duplicate_group_id, []).append(example)
    if not groups:
        raise GoldenEvaluationError("golden evaluation data is invalid")
    for group in groups.values():
        primaries = [
            example for example in group if example.duplicate_source_row_id is None
        ]
        duplicates = [
            example for example in group if example.duplicate_source_row_id is not None
        ]
        if (
            len(group) != 2
            or len(primaries) != 1
            or len(duplicates) != 1
            or duplicates[0].duplicate_source_row_id != primaries[0].row_id
            or duplicates[0].session != primaries[0].session
        ):
            raise GoldenEvaluationError("golden evaluation data is invalid")
    return {key: tuple(value) for key, value in groups.items()}


def _deduplicate_first(
    examples: Sequence[EvaluationExample],
) -> tuple[EvaluationExample, ...]:
    deduplicated: list[EvaluationExample] = []
    seen: set[tuple[str, str]] = set()
    for example in examples:
        key = (
            ("group", example.duplicate_group_id)
            if example.duplicate_group_id is not None
            else ("row", example.row_id)
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(example)
    return tuple(deduplicated)


def _label_metric(
    label: str,
    true_labels: Sequence[str],
    predictions: Sequence[str],
) -> LabelMetric:
    support = true_labels.count(label)
    predicted = predictions.count(label)
    true_positive = sum(
        true_label == label and prediction == label
        for true_label, prediction in zip(true_labels, predictions)
    )
    recall = true_positive / support if support else None
    precision = true_positive / predicted if predicted else None
    verified = support >= VERIFIED_SUPPORT
    return LabelMetric(
        support=support,
        true_positive=true_positive,
        predicted=predicted,
        recall=recall,
        precision=precision,
        verified=verified,
        passes_gate=(
            recall >= LABEL_RECALL_THRESHOLD
            if verified and recall is not None
            else None
        ),
    )
