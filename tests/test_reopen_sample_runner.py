from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from weekly_cs_report import reopen_sample_runner as runner
from weekly_cs_report.reopen_population import ReopenSession


def _write_review(directory, rows=200, *, header=runner.PII_REVIEW_FIELDS):
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    review = directory / "pii_review.csv"
    with review.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for index in range(rows):
            writer.writerow(
                [
                    f"session-{index}",
                    f"trace-{index}",
                    runner.APPROVED_SEGMENTS[index % len(runner.APPROVED_SEGMENTS)],
                    "reviewed masked text",
                ]
            )
    review.chmod(0o600)
    return review


def _approved_environment(monkeypatch, review):
    monkeypatch.setenv(
        runner.APPROVAL_ENVIRONMENT_NAME,
        hashlib.sha256(review.read_bytes()).hexdigest(),
    )


def _arguments(review, directory, *, as_of="2026-07-30T00:00:00+00:00", weeks="4"):
    return [
        "--approved-review",
        str(review),
        "--as-of",
        as_of,
        "--weeks",
        weeks,
        "--out",
        str(directory),
    ]


def _runner_lock(directory):
    return directory / ".reasons.csv.lock"


def test_main_validates_review_before_clients_then_runs_with_explicit_approval(
    tmp_path, monkeypatch, capsys
):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    _approved_environment(monkeypatch, review)
    events = []

    class Client:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            events.append(f"{self.name}-enter")
            return self

        def __exit__(self, *args):
            events.append(f"{self.name}-exit")

    def fake_load_environment():
        events.append("load-environment")
        return object()

    def fake_build_client(settings):
        assert settings is not None
        events.append("build-langfuse")
        return Client("langfuse")

    def fake_llm(*, pii_approved):
        assert pii_approved is True
        events.append("build-llm")
        return Client("llm")

    def fake_run(config, langfuse, llm, output, *, pii_approved):
        assert config.as_of == datetime(2026, 7, 30, tzinfo=timezone.utc)
        assert config.weeks == 4
        assert config.include_current_wtd is False
        assert pii_approved is True
        assert output == directory
        assert langfuse.name == "langfuse"
        assert llm.name == "llm"
        assert _runner_lock(directory).exists()
        events.append("run")
        with (directory / "reasons.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["session_id", "week"])
            writer.writerows([["a", "2026-07-20"], ["b", "2026-07-20"]])

    monkeypatch.setattr(runner, "load_environment", fake_load_environment)
    monkeypatch.setattr(runner, "_build_client", fake_build_client)
    monkeypatch.setattr(runner.GemmaHFLLMClient, "from_environment", fake_llm)
    monkeypatch.setattr(runner, "run_sample_reopen", fake_run)

    assert runner.main(_arguments(review, directory)) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"status":"complete","rows":2}\n'
    assert captured.err == ""
    assert events == [
        "load-environment",
        "build-langfuse",
        "langfuse-enter",
        "build-llm",
        "llm-enter",
        "run",
        "llm-exit",
        "langfuse-exit",
    ]
    assert not _runner_lock(directory).exists()


@pytest.mark.parametrize("digest", (None, "a" * 64, "A" * 64, "invalid"))
def test_missing_or_invalid_approval_refuses_before_environment_load(
    tmp_path, monkeypatch, capsys, digest
):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    monkeypatch.delenv(runner.APPROVAL_ENVIRONMENT_NAME, raising=False)
    if digest is not None:
        monkeypatch.setenv(runner.APPROVAL_ENVIRONMENT_NAME, digest)
    monkeypatch.setattr(runner, "load_environment", lambda: pytest.fail("must not load"))

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"


@pytest.mark.parametrize(
    ("mutation", "rows"),
    [
        ("unsafe-file-mode", 200),
        ("unsafe-parent-mode", 200),
        ("wrong-header", 200),
        ("unmasked-text", 200),
        ("duplicate", 200),
        ("too-few", 199),
    ],
)
def test_invalid_review_refuses_before_any_client(
    tmp_path, monkeypatch, capsys, mutation, rows
):
    directory = tmp_path / "discovery"
    review = _write_review(directory, rows)
    if mutation == "unsafe-file-mode":
        review.chmod(0o644)
    elif mutation == "unsafe-parent-mode":
        directory.chmod(0o755)
    elif mutation == "wrong-header":
        review.unlink()
        review = _write_review(directory, header=("bad", "header", "only", "here"))
    elif mutation == "unmasked-text":
        with review.open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow(["extra", "trace", "initial_user_text", "0901234567"])
    elif mutation == "duplicate":
        with review.open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow(["session-0", "trace-0", "initial_user_text", "other"])
    _approved_environment(monkeypatch, review)
    monkeypatch.setattr(runner, "load_environment", lambda: pytest.fail("must not load"))

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"


def test_symlinked_review_is_refused_before_any_client(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "discovery"
    source = _write_review(tmp_path / "source")
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    review = directory / "pii_review.csv"
    review.symlink_to(source)
    _approved_environment(monkeypatch, source)
    monkeypatch.setattr(runner, "load_environment", lambda: pytest.fail("must not load"))

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"


def test_existing_reasons_file_is_never_overwritten(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    reasons = directory / "reasons.csv"
    reasons.write_text("keep", encoding="utf-8")
    _approved_environment(monkeypatch, review)
    monkeypatch.setattr(runner, "load_environment", lambda: pytest.fail("must not load"))

    assert runner.main(_arguments(review, directory)) == 2
    assert reasons.read_text(encoding="utf-8") == "keep"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"


def test_existing_atomic_runner_lock_refuses_before_environment_load(
    tmp_path, monkeypatch, capsys
):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    _runner_lock(directory).write_bytes(b"")
    _runner_lock(directory).chmod(0o600)
    _approved_environment(monkeypatch, review)
    monkeypatch.setattr(runner, "load_environment", lambda: pytest.fail("must not load"))

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"
    assert _runner_lock(directory).exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--as-of", "2026-07-30T00:00:00", "--weeks", "4"],
        ["--as-of", "2026-07-30T00:00:00+00:00", "--weeks", "0"],
    ],
)
def test_parser_rejects_naive_as_of_and_nonpositive_weeks(arguments):
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(
            ["--approved-review", "pii_review.csv", *arguments, "--out", "out"]
        )


def test_runtime_error_is_payload_free_and_closes_both_clients(
    tmp_path, monkeypatch, capsys
):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    _approved_environment(monkeypatch, review)
    closed = []

    class Client:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(self.name)

    monkeypatch.setattr(runner, "load_environment", lambda: object())
    monkeypatch.setattr(runner, "_build_client", lambda settings: Client("langfuse"))
    monkeypatch.setattr(
        runner.GemmaHFLLMClient,
        "from_environment",
        lambda *, pii_approved: Client("llm"),
    )
    monkeypatch.setattr(
        runner,
        "run_sample_reopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret payload")),
    )

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"
    assert "secret payload" not in captured.err
    assert closed == ["llm", "langfuse"]
    assert not _runner_lock(directory).exists()


def test_keyboard_interrupt_is_not_swallowed(tmp_path, monkeypatch):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    _approved_environment(monkeypatch, review)
    monkeypatch.setattr(runner, "load_environment", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        runner.main(_arguments(review, directory))
    assert not _runner_lock(directory).exists()


def test_approved_review_for_a_different_population_refuses_before_model_calls(
    tmp_path, monkeypatch, capsys
):
    directory = tmp_path / "discovery"
    review = _write_review(directory)
    _approved_environment(monkeypatch, review)
    events = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class ForbiddenLLM(Client):
        def embed(self, texts):
            events.append("embed")
            raise AssertionError("must refuse before embedding")

        def generate_structured(self, *, messages, response_schema):
            events.append("generate")
            raise AssertionError("must refuse before generation")

    current_population = SimpleNamespace(
        sessions=(
            ReopenSession(
                session_id="current-session",
                anchor_trace_id="current-anchor",
                followup_trace_id="current-followup",
                week=date(2026, 7, 20),
                domain="ibft",
                outcome="ai_end_to_end",
                initial_user_text="current initial [PII]",
                initial_ai_text="current response [PII]",
                followup_user_text="current followup [PII]",
            ),
        )
    )
    report = SimpleNamespace(
        result=SimpleNamespace(
            sessions=(),
            selection=SimpleNamespace(eligible={}),
        )
    )

    monkeypatch.setattr(runner, "load_environment", lambda: object())
    monkeypatch.setattr(runner, "_build_client", lambda settings: Client())
    monkeypatch.setattr(
        runner.GemmaHFLLMClient,
        "from_environment",
        lambda *, pii_approved: ForbiddenLLM(),
    )
    monkeypatch.setattr("weekly_cs_report.cli.compute_report", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        "weekly_cs_report.cli.build_reopen_population",
        lambda *args, **kwargs: current_population,
    )

    assert runner.main(_arguments(review, directory)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runner.FIXED_ERROR + "\n"
    assert events == []
    assert not (directory / "reasons.csv").exists()
