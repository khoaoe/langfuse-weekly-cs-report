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

    def iter_traces(
        self,
        from_timestamp: datetime,
        to_timestamp: datetime,
        **_controls,
    ):
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
    for command in ("sync", "canary", "backfill-dimensions"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_parser_exposes_bounded_freshdesk_csat_commands():
    fetch = build_parser().parse_args(
        [
            "fetch-csat",
            "--weeks",
            "13",
            "--since-week",
            "2026-07-27",
            "--max-workers",
            "2",
            "--max-duration",
            "1800",
        ]
    )
    discover = build_parser().parse_args(["discover-agents", "--weeks", "13"])
    reconcile = build_parser().parse_args(
        [
            "reconcile-freshdesk-outcomes",
            "--weeks",
            "13",
            "--max-workers",
            "2",
            "--max-duration",
            "1800",
        ]
    )
    entry_coverage = build_parser().parse_args(
        [
            "fetch-freshdesk-entry-coverage",
            "--weeks",
            "13",
            "--max-workers",
            "1",
            "--max-duration",
            "1800",
        ]
    )

    assert fetch.command == "fetch-csat"
    assert fetch.weeks == 13
    assert fetch.since_week.isoformat() == "2026-07-27"
    assert fetch.max_workers == 2
    assert fetch.max_duration == 1800
    assert discover.command == "discover-agents"
    assert discover.weeks == 13
    assert reconcile.command == "reconcile-freshdesk-outcomes"
    assert reconcile.weeks == 13
    assert reconcile.max_workers == 2
    assert reconcile.max_duration == 1800
    assert entry_coverage.command == "fetch-freshdesk-entry-coverage"
    assert entry_coverage.weeks == 13
    assert entry_coverage.max_workers == 1
    assert entry_coverage.max_duration == 1800


def test_freshdesk_command_dispatch_does_not_load_langfuse_credentials(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: (_ for _ in ()).throw(AssertionError("Langfuse env was read")),
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli._run_fetch_csat_command",
        lambda _args: {
            "status": "complete",
            "weeks_fetched": 1,
            "included_bot_response_count": 3,
        },
    )

    assert main(["fetch-csat", "--weeks", "1"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "included_bot_response_count": 3,
        "status": "complete",
        "weeks_fetched": 1,
    }
    assert output.err == ""


def test_entry_coverage_population_is_fixed_to_start_week(monkeypatch, tmp_path: Path):
    from weekly_cs_report import cli as cli_module

    class Snapshot:
        def dashboard_dict(self):
            return {
                "views": {
                    "mon_sun": {
                        "weekly": [
                            {"cohort_week": "2026-06-29"},
                            {"cohort_week": "2026-07-06"},
                            {"cohort_week": "2026-07-13"},
                        ]
                    }
                }
            }

        tickets = ()

    class Store:
        def __init__(self, _directory):
            pass

        def load(self):
            return Snapshot()

    monkeypatch.setattr("weekly_cs_report.dashboard_cache.ProtectedSnapshotStore", Store)

    weeks, tickets = cli_module._entry_coverage_population(tmp_path / "runtime", 13)

    assert weeks == ("2026-07-06", "2026-07-13")
    assert tickets == {}


def test_csat_population_loads_the_protected_snapshot_store(monkeypatch, tmp_path: Path):
    from weekly_cs_report import cli as cli_module

    class Ticket:
        def __init__(self, ticket_id: str, cohort_week: str):
            self.ticket_id = ticket_id
            self.cohort_week = cohort_week

    class Snapshot:
        tickets = (
            Ticket("101", "2026-07-06"),
            Ticket("102", "2026-07-13"),
            Ticket("103", "2026-06-29"),
        )

        def dashboard_dict(self):
            return {
                "views": {
                    "mon_sun": {
                        "weekly": [
                            {"cohort_week": "2026-06-29"},
                            {"cohort_week": "2026-07-06"},
                            {"cohort_week": "2026-07-13"},
                        ]
                    }
                }
            }

    class Store:
        def __init__(self, _directory):
            pass

        def load(self):
            return Snapshot()

    monkeypatch.setattr("weekly_cs_report.dashboard_cache.ProtectedSnapshotStore", Store)

    assert cli_module._csat_population(tmp_path / "runtime", 2) == {
        "2026-07-06": ("101",),
        "2026-07-13": ("102",),
    }


def test_entry_coverage_command_publishes_only_after_inventory_and_coverage_complete(
    monkeypatch, tmp_path: Path
):
    from weekly_cs_report import cli as cli_module
    from weekly_cs_report.entry_coverage_cache import load_entry_coverage_cache
    from weekly_cs_report.freshdesk_entry_coverage import FreshdeskTicketMetadata
    from weekly_cs_report.outcome_reconciliation import ReconciliationAgentConfig

    runtime = tmp_path / "runtime"
    selected_ticket = FreshdeskTicketMetadata("123", "2026-07-06T01:00:00Z")
    monkeypatch.setattr(
        cli_module,
        "_entry_coverage_population",
        lambda *_args: (("2026-07-06",), {}),
    )
    monkeypatch.setattr(cli_module, "_freshdesk_settings", lambda: object())
    monkeypatch.setattr(
        "weekly_cs_report.outcome_reconciliation.load_reconciliation_agent_config",
        lambda *_args, **_kwargs: ReconciliationAgentConfig(
            approved_by="PO",
            approved_at="2026-08-03",
            bot_agent_ids=frozenset({1}),
            human_agent_ids=frozenset({2}),
            excluded_agent_ids=frozenset({3}),
            source_hash="sha256:" + "1" * 64,
        ),
    )

    class FakeFreshdeskClient:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_ticket_metadata(self, **kwargs):
            kwargs["on_page"]((selected_ticket,), 2, True)
            return (selected_ticket,)

        def get_conversation_metadata(self, _ticket_id, *, should_stop=None):
            return ()

    monkeypatch.setattr("weekly_cs_report.freshdesk_csat.FreshdeskClient", FakeFreshdeskClient)

    result = cli_module._run_fetch_freshdesk_entry_coverage_command(
        build_parser().parse_args(
            [
                "fetch-freshdesk-entry-coverage",
                "--runtime-dir",
                str(runtime),
                "--weeks",
                "13",
                "--max-duration",
                "60",
                "--auth",
                "rest",
            ]
        )
    )

    assert result["status"] == "complete"
    cache = load_entry_coverage_cache(runtime / "entry_coverage_cache.json")
    assert cache is not None
    assert [record.ticket_id for record in cache.records] == ["123"]
    checkpoint_dir = tmp_path / "artifacts" / "freshdesk_entry_coverage"
    assert not (checkpoint_dir / "inventory_checkpoint.json").exists()
    assert not (checkpoint_dir / "coverage_checkpoint.json").exists()


def test_entry_coverage_command_resumes_inventory_after_rate_limit_checkpoint(
    monkeypatch, tmp_path: Path
):
    from weekly_cs_report import cli as cli_module
    from weekly_cs_report.entry_coverage_cache import load_entry_coverage_cache
    from weekly_cs_report.freshdesk_csat import FreshdeskFetchDeadline
    from weekly_cs_report.freshdesk_entry_coverage import FreshdeskTicketMetadata
    from weekly_cs_report.outcome_reconciliation import ReconciliationAgentConfig

    runtime = tmp_path / "runtime"
    first_ticket = FreshdeskTicketMetadata("123", "2026-07-06T01:00:00Z")
    second_ticket = FreshdeskTicketMetadata("456", "2026-07-06T02:00:00Z")
    monkeypatch.setattr(
        cli_module,
        "_entry_coverage_population",
        lambda *_args: (("2026-07-06",), {}),
    )
    monkeypatch.setattr(cli_module, "_freshdesk_settings", lambda: object())
    monkeypatch.setattr(
        "weekly_cs_report.outcome_reconciliation.load_reconciliation_agent_config",
        lambda *_args, **_kwargs: ReconciliationAgentConfig(
            approved_by="PO",
            approved_at="2026-08-03",
            bot_agent_ids=frozenset({1}),
            human_agent_ids=frozenset({2}),
            excluded_agent_ids=frozenset({3}),
            source_hash="sha256:" + "1" * 64,
        ),
    )

    class ResumingFreshdeskClient:
        attempts = 0
        starts: list[int] = []

        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_ticket_metadata(self, **kwargs):
            type(self).attempts += 1
            type(self).starts.append(kwargs["start_page"])
            if type(self).attempts == 1:
                kwargs["on_page"]((first_ticket,), 2, False)
                raise FreshdeskFetchDeadline("resume")
            assert kwargs["existing"] == (first_ticket,)
            kwargs["on_page"]((first_ticket, second_ticket), 3, True)
            return (first_ticket, second_ticket)

        def get_conversation_metadata(self, _ticket_id, *, should_stop=None):
            return ()

    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskClient",
        ResumingFreshdeskClient,
    )
    args = build_parser().parse_args(
        [
            "fetch-freshdesk-entry-coverage",
            "--runtime-dir",
            str(runtime),
            "--weeks",
            "13",
            "--max-duration",
            "60",
            "--auth",
            "rest",
        ]
    )

    first_result = cli_module._run_fetch_freshdesk_entry_coverage_command(args)
    second_result = cli_module._run_fetch_freshdesk_entry_coverage_command(args)

    assert first_result["status"] == "duration_limit_reached"
    assert second_result["status"] == "complete"
    assert ResumingFreshdeskClient.starts == [1, 2]
    cache = load_entry_coverage_cache(runtime / "entry_coverage_cache.json")
    assert cache is not None
    assert {record.ticket_id for record in cache.records} == {"123", "456"}


def test_fetch_csat_command_checkpoints_completed_weeks_without_publishing_partial(
    monkeypatch, tmp_path: Path
):
    from weekly_cs_report import cli as cli_module
    from weekly_cs_report.csat_cache import (
        CSATCache,
        CSATCacheStats,
        CachedCSATResponse,
        load_csat_cache,
    )
    from weekly_cs_report.freshdesk_csat import (
        FreshdeskAgentConfig,
        IncrementalCSATResult,
    )

    runtime = tmp_path / "runtime"
    cache = CSATCache(
        fetched_weeks={"2026-07-27": "2026-08-02T01:00:00Z"},
        fetch_stats=CSATCacheStats(1, 1, 0, 0),
        responses=(
            CachedCSATResponse(
                response_key=f"sha256:{'a' * 64}",
                ticket_id="123",
                survey_id=43000076179,
                responded_at="2026-08-02T01:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=False,
                comment_redacted=None,
            ),
        ),
    )

    class FakeFreshdeskClient:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_fetch(*_args, on_week_complete, **_kwargs):
        on_week_complete(cache)
        return IncrementalCSATResult(
            cache=cache,
            completed_weeks=("2026-07-27",),
            complete=False,
        )

    monkeypatch.setattr(cli_module, "_csat_population", lambda *_args: {})
    monkeypatch.setattr(cli_module, "_freshdesk_settings", lambda: object())
    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.load_agent_config",
        lambda _path: FreshdeskAgentConfig(
            bot_agent_ids=frozenset({73_001}),
            survey_scales={
                "43000076179": {
                    "positive": (103,),
                    "neutral": (100,),
                    "negative": (-103,),
                }
            },
        ),
    )
    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskClient",
        FakeFreshdeskClient,
    )
    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.fetch_csat_population",
        fake_fetch,
    )

    result = cli_module._run_fetch_csat_command(
        build_parser().parse_args(
            [
                "fetch-csat",
                "--runtime-dir",
                str(runtime),
                "--weeks",
                "1",
                "--auth",
                "rest",
            ]
        )
    )

    checkpoint = tmp_path / "artifacts" / "freshdesk_csat" / "checkpoint.json"
    assert result["status"] == "duration_limit_reached"
    assert load_csat_cache(checkpoint) == cache
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert not (runtime / "csat_cache.json").exists()


def test_reconciliation_command_checkpoints_without_exposing_identity(
    monkeypatch, tmp_path: Path
):
    from weekly_cs_report import cli as cli_module
    from weekly_cs_report.outcome_reconciliation import (
        IncrementalReconciliationResult,
        ReconciliationAgentConfig,
    )
    from weekly_cs_report.reconciliation_cache import (
        ReconciliationCache,
        ReconciliationRecord,
        load_reconciliation_cache,
    )

    runtime = tmp_path / "runtime"
    cache = ReconciliationCache(
        fetched_weeks={"2026-07-27": "2026-08-03T01:00:00Z"},
        records=(ReconciliationRecord("123", "2026-07-27", None),),
    )

    class FakeFreshdeskClient:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_fetch(*_args, on_week_complete, **_kwargs):
        on_week_complete(cache)
        return IncrementalReconciliationResult(
            cache=cache,
            completed_weeks=("2026-07-27",),
            complete=False,
        )

    monkeypatch.setattr(cli_module, "_reconciliation_population", lambda *_args: {})
    monkeypatch.setattr(cli_module, "_freshdesk_settings", lambda: object())
    monkeypatch.setattr(
        "weekly_cs_report.outcome_reconciliation.load_reconciliation_agent_config",
        lambda *_args, **_kwargs: ReconciliationAgentConfig(
            approved_by="PO",
            approved_at="2026-08-03",
            bot_agent_ids=frozenset({1}),
            human_agent_ids=frozenset({2}),
            excluded_agent_ids=frozenset({3}),
            source_hash="sha256:" + "1" * 64,
        ),
    )
    monkeypatch.setattr(
        "weekly_cs_report.freshdesk_csat.FreshdeskClient",
        FakeFreshdeskClient,
    )
    monkeypatch.setattr(
        "weekly_cs_report.outcome_reconciliation.fetch_reconciliation_population",
        fake_fetch,
    )

    result = cli_module._run_reconcile_freshdesk_outcomes_command(
        build_parser().parse_args(
            [
                "reconcile-freshdesk-outcomes",
                "--runtime-dir",
                str(runtime),
                "--weeks",
                "1",
                "--auth",
                "rest",
            ]
        )
    )

    checkpoint = (
        tmp_path
        / "artifacts"
        / "freshdesk_reconciliation"
        / "checkpoint.json"
    )
    assert result == {
        "status": "duration_limit_reached",
        "weeks_fetched": 1,
        "checked_ticket_count": 0,
        "human_replied_after_ai": 0,
        "unresolved_ticket_count": 1,
    }
    assert load_reconciliation_cache(checkpoint) == cache
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert not (runtime / "outcome_reconciliation_cache.json").exists()
    assert not {"author_id", "conversation_id", "agent_id"} & nested_keys(result)


def test_reconciliation_dispatch_does_not_load_langfuse_credentials(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: (_ for _ in ()).throw(AssertionError("Langfuse env was read")),
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli._run_reconcile_freshdesk_outcomes_command",
        lambda _args: {
            "status": "complete",
            "weeks_fetched": 1,
            "checked_ticket_count": 3,
            "human_replied_after_ai": 1,
            "unresolved_ticket_count": 0,
        },
    )

    assert main(["reconcile-freshdesk-outcomes", "--weeks", "1"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["human_replied_after_ai"] == 1
    assert output.err == ""


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
        def iter_traces(self, from_timestamp, to_timestamp, **_controls):
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
