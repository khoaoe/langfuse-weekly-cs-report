from __future__ import annotations

import csv
import stat
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from weekly_cs_report.cli import RunConfig, build_parser, main, run_sample_reopen
from weekly_cs_report.llm_client import (
    FakeLLMClient,
    PIIApprovalRequiredError,
    StructuredGeneration,
)
from weekly_cs_report.reopen_population import ReopenSession
from weekly_cs_report.reopen_sampling import (
    DISCOVERY_BATCH_SIZE,
    _select_clusters,
    sample_reopen,
    write_reopen_discovery_csv,
)


class RecordingFakeLLMClient(FakeLLMClient):
    def __init__(self, *, outputs):
        super().__init__(structured_outputs=outputs, embedding_dimensions=6)
        self.embed_inputs: list[tuple[str, ...]] = []
        self.structured_messages: list[tuple[dict[str, object], ...]] = []

    def embed(self, texts):
        self.embed_inputs.append(tuple(texts))
        return super().embed(texts)

    def generate_structured(self, *, messages, response_schema):
        self.structured_messages.append(tuple(dict(message) for message in messages))
        return super().generate_structured(
            messages=messages,
            response_schema=response_schema,
        )


def test_public_discovery_helper_fails_closed_without_explicit_pii_approval(
    tmp_path, monkeypatch
):
    def forbidden_compute(*args, **kwargs):
        raise AssertionError("Langfuse or LLM work must not start before approval")

    monkeypatch.setattr("weekly_cs_report.cli.compute_report", forbidden_compute)
    with pytest.raises(PIIApprovalRequiredError, match="pii approval required"):
        run_sample_reopen(
            RunConfig(
                as_of=datetime(2026, 7, 30, tzinfo=timezone.utc),
                weeks=4,
            ),
            object(),  # type: ignore[arg-type]
            RecordingFakeLLMClient(outputs=()),
            tmp_path / "discovery",
        )

    assert not (tmp_path / "discovery").exists()


def _session(
    session_id: str,
    *,
    week: date = date(2026, 7, 20),
    domain: str = "ibft",
    outcome: str = "ai_end_to_end",
) -> ReopenSession:
    return ReopenSession(
        session_id=session_id,
        anchor_trace_id=f"anchor-{session_id}",
        followup_trace_id=f"followup-{session_id}",
        week=week,
        domain=domain,
        outcome=outcome,
        initial_user_text=f"initial secret {session_id}",
        initial_ai_text=f"ai secret {session_id}",
        followup_user_text=f"followup-only-{session_id} [PII]",
    )


def test_sampling_embeds_only_masked_followup_and_covers_every_nonempty_stratum():
    sessions = (
        _session("b", domain="ibft"),
        _session("a", domain="ibft"),
        _session("c", domain="topup", outcome="ai_then_cs"),
        _session("d", week=date(2026, 7, 27), domain="topup"),
    )
    llm = RecordingFakeLLMClient(outputs=tuple({"reason_text": "reason"} for _ in sessions))

    discovery = sample_reopen(sessions, llm)

    assert llm.embed_inputs == [
        (
            "followup-only-a [PII]",
            "followup-only-b [PII]",
            "followup-only-c [PII]",
            "followup-only-d [PII]",
        )
    ]
    assert all("initial secret" not in text for texts in llm.embed_inputs for text in texts)
    assert {
        (row.week, row.domain, row.outcome, row.cluster_id)
        for row in discovery.rows
    } == {
        (session.week.isoformat(), session.domain, session.outcome, cluster_id)
        for session, cluster_id in zip(discovery.clustered_sessions, discovery.cluster_ids)
    }
    assert len(discovery.rows) == 4
    assert discovery.cluster_count == 1
    assert discovery.silhouette_score is None
    assert all(row.reason_text == "reason" for row in discovery.rows)


def test_sampling_uses_50_session_generation_batches_and_structured_reason_per_sample():
    sessions = tuple(_session(f"s-{index:02d}", domain=f"domain-{index:02d}") for index in range(51))
    llm = RecordingFakeLLMClient(
        outputs=tuple({"reason_text": f"reason-{index}"} for index in range(51))
    )

    discovery = sample_reopen(sessions, llm)

    assert DISCOVERY_BATCH_SIZE == 50
    assert len(discovery.rows) == 51
    assert discovery.generation_batch_count == 2
    assert len(llm.structured_messages) == 51
    assert all(
        message[0]["role"] == "system"
        and "đúng một câu lý do" in str(message[0]["content"])
        and "định danh" in str(message[0]["content"])
        and message[1]["role"] == "user"
        and "followup_user_text" in str(message[1]["content"])
        for message in llm.structured_messages
    )


def test_discovery_csv_has_exact_fields_and_server_side_permissions(tmp_path):
    llm = RecordingFakeLLMClient(outputs=({"reason_text": "call 0900000000"},))
    discovery = sample_reopen((_session("one"),), llm)

    destination = write_reopen_discovery_csv(tmp_path / "discovery", discovery.rows)

    assert destination.name == "reasons.csv"
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with destination.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == [
        "session_id",
        "week",
        "domain",
        "outcome",
        "cluster_id",
        "reason_text",
    ]
    assert rows == [
        {
            "session_id": "one",
            "week": "2026-07-20",
            "domain": "ibft",
            "outcome": "ai_end_to_end",
            "cluster_id": "0",
            "reason_text": "call [PII]",
        }
    ]
    assert "initial secret" not in destination.read_text(encoding="utf-8")
    assert "ai secret" not in destination.read_text(encoding="utf-8")


def test_generated_reason_is_bounded_and_has_no_newline():
    llm = RecordingFakeLLMClient(outputs=({"reason_text": "lý do\n" * 200},))

    discovery = sample_reopen((_session("one"),), llm)

    assert "\n" not in discovery.rows[0].reason_text
    assert len(discovery.rows[0].reason_text) <= 500


def test_sampling_round_robins_all_strata_before_repeating_any_stratum():
    sessions = (
        _session("a-0", domain="ibft"),
        _session("a-1", domain="ibft"),
        _session("b-0", domain="topup"),
        _session("b-1", domain="topup"),
    )
    llm = RecordingFakeLLMClient(outputs=tuple({"reason_text": "same reason"} for _ in sessions))

    discovery = sample_reopen(sessions, llm)

    assert [row.session_id for row in discovery.rows] == ["a-0", "b-0", "a-1", "b-1"]


def test_sampling_stops_after_two_consecutive_batches_without_a_new_reason():
    sessions = tuple(_session(f"s-{index:03d}") for index in range(200))
    llm = RecordingFakeLLMClient(
        outputs=tuple({"reason_text": " Same   reason\n"} for _ in sessions)
    )

    discovery = sample_reopen(sessions, llm)

    assert len(discovery.rows) == 150
    assert discovery.generation_batch_count == 3
    assert {row.reason_text for row in discovery.rows} == {"Same reason"}


def test_sampling_caps_at_300_when_reasons_remain_new():
    sessions = tuple(_session(f"s-{index:03d}") for index in range(350))
    llm = RecordingFakeLLMClient(
        outputs=tuple({"reason_text": f"reason {index}"} for index in range(350))
    )

    discovery = sample_reopen(sessions, llm)

    assert len(discovery.rows) == 300
    assert discovery.generation_batch_count == 6


def test_sampling_fails_when_more_than_300_strata_must_be_covered():
    sessions = tuple(_session(f"s-{index:03d}", domain=f"domain-{index:03d}") for index in range(301))
    llm = RecordingFakeLLMClient(outputs=({"reason_text": "reason"},))

    with pytest.raises(Exception, match="reopen discovery stratum limit exceeded"):
        sample_reopen(sessions, llm)


def test_cluster_candidate_that_collapses_below_its_k_falls_back_to_one_cluster():
    assignments, cluster_count, silhouette, attempted = _select_clusters(
        ((1.0, 0.0),) * 6
    )

    assert assignments == (0, 0, 0, 0, 0, 0)
    assert cluster_count == 1
    assert silhouette is None
    assert attempted == (5,)


def test_sample_reopen_cli_exports_review_after_get_report_then_stops_before_llm(
    tmp_path, monkeypatch, capsys
):
    args = build_parser().parse_args(
        ["sample-reopen", "--weeks", "4", "--out", str(tmp_path / "discovery")]
    )
    assert args.command == "sample-reopen"
    assert args.weeks == 4
    assert args.out == tmp_path / "discovery"

    events = []

    class FakeLangfuseClient:
        def __enter__(self):
            events.append("langfuse-enter")
            return self

        def __exit__(self, *args):
            events.append("langfuse-exit")

    def fake_environment_load():
        events.append("langfuse-settings")
        return object()

    def fake_build_client(settings):
        assert settings is not None
        events.append("langfuse-client")
        return FakeLangfuseClient()

    def fake_compute_report(client, **kwargs):
        assert isinstance(client, FakeLangfuseClient)
        assert kwargs["weeks"] == 4
        events.append("compute-report-get")
        result = type(
            "Result",
            (),
            {
                "sessions": (),
                "selection": type("Selection", (), {"eligible": {}})(),
            },
        )()
        return type("Report", (), {"result": result})()

    def forbidden_llm(*args, **kwargs):
        raise AssertionError("LLM must not be created or called before PII approval")

    monkeypatch.setattr("weekly_cs_report.cli.load_environment", fake_environment_load)
    monkeypatch.setattr("weekly_cs_report.cli._build_client", fake_build_client)
    monkeypatch.setattr("weekly_cs_report.cli.compute_report", fake_compute_report)
    monkeypatch.setattr("weekly_cs_report.cli.sample_reopen", forbidden_llm)
    monkeypatch.setattr(
        "weekly_cs_report.llm_client.LLMSettings.from_environment",
        forbidden_llm,
    )
    exit_code = main(
        ["sample-reopen", "--weeks", "4", "--out", str(tmp_path / "discovery")]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == "pii approval required\n"
    assert events == [
        "langfuse-settings",
        "langfuse-client",
        "langfuse-enter",
        "compute-report-get",
        "langfuse-exit",
    ]
    review = tmp_path / "discovery" / "pii_review.csv"
    assert review.exists()
    assert stat.S_IMODE(review.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(review.stat().st_mode) == 0o600
