from __future__ import annotations

import csv
import json
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.traces import TRANSFER_HTML, trace
from weekly_cs_report.cli import (
    PROJECT_ROOT,
    TARGET_BASE_URL,
    TARGET_PROJECT_ID,
    ConfigurationError,
    EnvironmentSettings,
    RunConfig,
    build_parser,
    inspect_session,
    load_environment,
    main,
    run_dry_run,
)
from weekly_cs_report.langfuse_client import LangfuseAPIError

VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
FORBIDDEN = {
    "input",
    "output",
    "comments",
    "user_input",
    "user_id",
    "trans_id",
    "response",
}


def raw_traces() -> list[dict]:
    return [
        trace(
            "ai-0",
            "ticket-ai",
            0,
            "2026-07-20T02:00:00Z",
            "A safe synthetic AI reply",
        ),
        trace(
            "transfer-0",
            "ticket-transfer",
            0,
            "2026-07-21T02:00:00Z",
            TRANSFER_HTML,
            title="Topup synthetic",
        ),
        trace(
            "weekend-0",
            "ticket-weekend",
            0,
            "2026-07-25T02:00:00Z",
            "Excluded weekend reply",
        ),
    ]


class FakeClient:
    def __init__(self, traces: list[dict] | None = None) -> None:
        self.traces = list(traces or raw_traces())
        self.bounds: list[tuple[datetime, datetime]] = []
        self.observation_trace_ids: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_traces(self, from_timestamp: datetime, to_timestamp: datetime):
        self.bounds.append((from_timestamp, to_timestamp))
        yield from self.traces

    def list_observations(self, trace_id: str) -> list[dict]:
        self.observation_trace_ids.append(trace_id)
        return []


def config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        as_of=AS_OF,
        weeks=2,
        include_current_wtd=True,
        artifact_root=tmp_path / "artifacts",
    )


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in nested_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in nested_keys(child)}
    return set()


def test_parser_defaults_to_dry_run_twelve_weeks_and_supports_reproducible_time():
    defaults = build_parser().parse_args([])
    explicit = build_parser().parse_args(
        [
            "dry-run",
            "--week-definition",
            "mon_fri",
            "--include-current-wtd",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ]
    )

    assert defaults.command == "dry-run"
    assert defaults.weeks == 12
    assert defaults.include_current_wtd is False
    assert defaults.week_definition == "mon_sun"
    assert explicit.include_current_wtd is True
    assert explicit.week_definition == "mon_fri"
    assert explicit.as_of == AS_OF


def test_parser_rejects_naive_as_of_and_does_not_expose_write_subcommands():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["dry-run", "--as-of", "2026-07-29T12:00:00"])

    parser = build_parser()
    for command in ("sync", "canary"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_environment_errors_name_only_missing_variables_and_load_project_dotenv(
    monkeypatch,
):
    loaded: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_dotenv",
        lambda path, override=False: loaded.append((Path(path), override)),
    )
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    with pytest.raises(ConfigurationError) as error:
        load_environment(
            {
                "LANGFUSE_PUBLIC_KEY": "pk-sensitive",
                "LANGFUSE_BASE_URL": TARGET_BASE_URL,
            }
        )
    with pytest.raises(ConfigurationError):
        load_environment()

    assert str(error.value) == "Missing environment variables: LANGFUSE_SECRET_KEY"
    assert "pk-sensitive" not in str(error.value)
    assert loaded == [(PROJECT_ROOT / ".env", False)]


def test_environment_is_pinned_to_the_approved_host_without_echoing_bad_value():
    bad_host = "https://attacker.example/sensitive"

    with pytest.raises(ConfigurationError) as error:
        load_environment(
            {
                "LANGFUSE_PUBLIC_KEY": "pk-sensitive",
                "LANGFUSE_SECRET_KEY": "sk-sensitive",
                "LANGFUSE_BASE_URL": bad_host,
            }
        )

    assert str(error.value) == "LANGFUSE_BASE_URL does not match the configured target"
    assert bad_host not in str(error.value)


def test_run_dry_run_uses_full_pipeline_and_writes_only_protected_redacted_artifacts(
    tmp_path,
):
    client = FakeClient()

    result = run_dry_run(config(tmp_path), client)

    assert tuple(session.session_id for session in result.sessions) == (
        "ticket-ai",
        "ticket-transfer",
        "ticket-weekend",
    )
    assert client.observation_trace_ids == []
    assert len(client.bounds) == 1
    latest = tmp_path / "artifacts" / "latest"
    assert {path.name for path in latest.iterdir()} == {
        "summary.json",
        "weekly_summary.csv",
        "investigation.csv",
        "score_manifest.json",
    }
    assert stat.S_IMODE(latest.stat().st_mode) == 0o700
    for report in latest.iterdir():
        assert stat.S_IMODE(report.stat().st_mode) == 0o600
        if report.suffix == ".json":
            assert not (nested_keys(json.loads(report.read_text())) & FORBIDDEN)
        else:
            with report.open(newline="", encoding="utf-8") as file:
                assert not (set(next(csv.reader(file))) & FORBIDDEN)

    summary = json.loads((latest / "summary.json").read_text())
    assert summary["source"] == {
        "traces_fetched": 3,
        "traces_deduplicated": 3,
    }
    assert summary["counts"]["eligible_ticket_count"] == 3
    assert summary["counts"]["weekend_start_count"] == 1
    assert summary["reopen"]["lifetime"] == {"numerator": 0, "denominator": 2}
    assert summary["reopen"]["within_7d"] == {
        "numerator": 0,
        "denominator": 2,
    }
    assert summary["reopen"]["control_within_7d"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
    }
    assert summary["reply_count_distribution"] == {"0": 1, "1": 2}
    assert summary["transfer_coverage"] == {
        "business": {"not_applicable": 1},
        "guardrail_rule": {"not_applicable": 1},
        "tpe": {"not_applicable": 1},
    }
    manifest = json.loads((latest / "score_manifest.json").read_text())
    assert manifest["project_id"] == TARGET_PROJECT_ID
    assert manifest["score_count"] == len(manifest["scores"]) > 0


def test_dry_run_deduplicates_a_repeated_page_boundary_trace(tmp_path):
    duplicated = raw_traces()
    duplicated.insert(1, dict(duplicated[0]))
    client = FakeClient(duplicated)

    result = run_dry_run(config(tmp_path), client)

    assert tuple(session.session_id for session in result.sessions) == (
        "ticket-ai",
        "ticket-transfer",
        "ticket-weekend",
    )
    summary = json.loads(
        (tmp_path / "artifacts" / "latest" / "summary.json").read_text()
    )
    assert summary["source"] == {
        "traces_fetched": 4,
        "traces_deduplicated": 3,
    }


def test_week_definition_changes_exported_weekly_rows(tmp_path):
    client = FakeClient()
    mon_sun_root = tmp_path / "mon-sun"
    mon_fri_root = tmp_path / "mon-fri"

    run_dry_run(
        RunConfig(
            as_of=AS_OF,
            weeks=2,
            include_current_wtd=True,
            artifact_root=mon_sun_root,
            week_definition="mon_sun",
        ),
        client,
    )
    run_dry_run(
        RunConfig(
            as_of=AS_OF,
            weeks=2,
            include_current_wtd=True,
            artifact_root=mon_fri_root,
            week_definition="mon_fri",
        ),
        FakeClient(),
    )

    def weekly_total(root: Path) -> str:
        with (root / "latest" / "weekly_summary.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        return next(row["total_tickets"] for row in rows if row["cohort_week"] == "2026-07-20")

    assert weekly_total(mon_sun_root) == "3"
    assert weekly_total(mon_fri_root) == "2"


def test_inspect_session_contains_labels_and_ids_but_no_raw_payload(tmp_path):
    client = FakeClient()
    result = run_dry_run(
        RunConfig(
            as_of=AS_OF,
            weeks=2,
            include_current_wtd=True,
            artifact_root=tmp_path / "artifacts",
        ),
        client,
    )

    inspected = inspect_session(result, "ticket-transfer")

    assert inspected["session_id"] == "ticket-transfer"
    assert inspected["outcome"] == "direct_cs"
    assert not (nested_keys(inspected) & FORBIDDEN)
    assert "Topup synthetic" not in json.dumps(inspected)


def test_main_default_command_runs_with_fake_client_and_without_real_env(
    tmp_path, monkeypatch
):
    fake = FakeClient()
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: fake)

    exit_code = main(["--artifact-root", str(tmp_path / "artifacts")])

    assert exit_code == 0
    assert fake.closed is True
    assert fake.bounds


def test_main_reports_client_failures_without_a_traceback_or_credentials(
    tmp_path, monkeypatch, capsys
):
    class BrokenClient(FakeClient):
        def iter_traces(self, from_timestamp, to_timestamp):
            raise LangfuseAPIError("GET", "/api/public/traces", 500)

    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-sensitive", "sk-sensitive", TARGET_BASE_URL),
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli._build_client",
        lambda _settings: BrokenClient(),
    )

    exit_code = main(["--artifact-root", str(tmp_path / "artifacts")])
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == "GET /api/public/traces status=500\n"
    assert "sensitive" not in output.err
    assert "Traceback" not in output.err
