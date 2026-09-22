from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

import pytest
from tests.fixtures.traces import TRANSFER_HTML, trace
from weekly_cs_report.dashboard_schema import project_dashboard
from weekly_cs_report.report import compute_report
from weekly_cs_report.session_cache import (
    SessionCacheError,
    load_session_cache,
    write_session_cache,
)


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
# A Wednesday, so the reporting window has a week-to-date cohort as well as
# complete weeks behind it.
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"
STORAGE_VERSION = 32


class WindowedClient:
    """Fake Langfuse that honours the requested window, as the real API does.

    A client that returns every trace regardless of bounds would make a
    narrowed refresh look identical to a full one for the wrong reason: the
    whole point is that the narrowed run never sees the older traces.
    """

    def __init__(self, traces: list[dict]) -> None:
        self._traces = traces
        self.bounds: list[tuple[datetime, datetime]] = []
        self.enrichment_bounds: list[tuple[datetime, datetime]] = []
        self.session_lookups: list[str] = []

    def iter_traces(
        self,
        from_timestamp: datetime,
        to_timestamp: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
        max_pages: int = 500,
    ):
        self.bounds.append((from_timestamp, to_timestamp))
        for raw in self._traces:
            stamp = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
            if from_timestamp <= stamp <= to_timestamp:
                yield raw

    def list_traces_by_session(self, session_id: str) -> list[dict]:
        self.session_lookups.append(session_id)
        return [
            raw for raw in self._traces if raw.get("sessionId") == session_id
        ]

    def list_observations(self, trace_id: str) -> list[dict]:
        return []

    def iter_observations_by_name(
        self,
        name: str,
        _from_start_time: datetime,
        _to_start_time: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.enrichment_bounds.append((_from_start_time, _to_start_time))
        return iter(())


def _traces() -> list[dict]:
    """One ticket per week across the reporting window."""
    return [
        trace("old-0", "ticket-old", 0, "2026-06-24T02:00:00Z", "Old safe reply"),
        trace("mid-0", "ticket-mid", 0, "2026-07-01T02:00:00Z", "Mid safe reply"),
        trace(
            "transfer-0",
            "ticket-transfer",
            0,
            "2026-07-08T02:00:00Z",
            TRANSFER_HTML,
            title="Topup synthetic",
        ),
        trace("late-0", "ticket-late", 0, "2026-07-20T02:00:00Z", "Late safe reply"),
        trace("wtd-0", "ticket-wtd", 0, "2026-07-28T02:00:00Z", "WTD safe reply"),
    ]


def _run(client, cached=None):
    return compute_report(
        client,
        as_of=AS_OF,
        weeks=8,
        include_current_wtd=True,
        taxonomy_path=TAXONOMY_PATH,
        refresh_timeout_seconds=30.0,
        cached_sessions=cached,
    )


def _by_week(run) -> dict[date, tuple]:
    grouped: dict[date, list] = {}
    for session in run.result.sessions:
        grouped.setdefault(session.cohort_week, []).append(session)
    return {week: tuple(sessions) for week, sessions in grouped.items()}


def test_cached_refresh_produces_the_same_dashboard_as_a_full_refresh():
    """A narrowed refresh that reuses cached weeks must not change any number.

    This is the whole contract: reusing a closed week is only safe if the
    dashboard it produces is indistinguishable from refetching that week.
    """
    full = _run(WindowedClient(_traces()))
    expected = project_dashboard(full).dashboard_dict()

    cached_client = WindowedClient(_traces())
    cached = _run(cached_client, cached=_by_week(full))
    actual = project_dashboard(cached).dashboard_dict()

    # `source` counts the traces THIS run pulled, so a narrowed refresh
    # legitimately reports fewer -- it is provenance for the fetch, not a
    # reported metric. Every figure the dashboard actually presents must match.
    assert actual.keys() == expected.keys()
    for key in expected:
        if key == "source":
            continue
        assert actual[key] == expected[key], key
    assert actual["source"]["traces_fetched"] < expected["source"]["traces_fetched"]
    assert {s.session_id for s in cached.result.sessions} == {
        s.session_id for s in full.result.sessions
    }


def test_cached_refresh_actually_narrows_the_langfuse_window():
    """Reuse that still fetches everything saves nothing."""
    full_client = WindowedClient(_traces())
    full = _run(full_client)
    full_start = full_client.bounds[0][0]

    cached_client = WindowedClient(_traces())
    _run(cached_client, cached=_by_week(full))

    assert cached_client.bounds[0][0] > full_start


def test_the_most_recent_closed_week_is_refetched_not_reused():
    """A just-closed week can still gain turns and reopen counts.

    `reopen_within_7d` counts a 168-hour window from the first trace, so the
    week that closed yesterday is not settled yet.
    """
    full = _run(WindowedClient(_traces()))
    cached_client = WindowedClient(_traces())
    _run(cached_client, cached=_by_week(full))

    fetch_start = cached_client.bounds[0][0].astimezone(VIETNAM).date()
    last_complete_monday = date(2026, 7, 20)
    assert fetch_start <= last_complete_monday


def test_a_session_analyzed_now_wins_over_its_cached_copy():
    """The fresh copy saw every trace the cached one did, plus later turns.

    Feeds the merge a deliberately wrong cached copy of a session the narrowed
    run analyzes itself, and asserts the freshly analyzed values survive.
    """
    from dataclasses import replace

    full = _run(WindowedClient(_traces()))
    cached = _by_week(full)
    fresh_week = max(cached)
    fresh = cached[fresh_week][0]

    poisoned = dict(cached)
    poisoned[fresh_week] = (
        replace(fresh, turn_count=fresh.turn_count + 99, outcome="unclassified"),
    )

    merged = _run(WindowedClient(_traces()), cached=poisoned)
    identifiers = [s.session_id for s in merged.result.sessions]
    assert len(identifiers) == len(set(identifiers))

    survivor = next(
        s for s in merged.result.sessions if s.session_id == fresh.session_id
    )
    assert survivor.turn_count == fresh.turn_count
    assert survivor.outcome == fresh.outcome


def _carried_traces() -> list[dict]:
    """A ticket opened in a week the cache owns that takes a later turn.

    Its first turn is far enough back that a narrowed fetch cannot see it --
    the whole point is that only the later turn falls inside the window.
    """
    return [
        *_traces(),
        trace("carry-0", "ticket-carry", 0, "2026-06-24T03:00:00Z", "First turn"),
        trace("carry-1", "ticket-carry", 1, "2026-07-28T03:00:00Z", "Later turn"),
    ]


def test_a_session_carried_into_the_window_keeps_its_original_cohort_week():
    """The later turn alone would file the ticket under the wrong week.

    Without refetching the session whole, `select_candidate_sessions` treats
    the later turn as the ticket's first trace and books it into the current
    week with a turn count of one.
    """
    full = _run(WindowedClient(_carried_traces()))
    cached = _by_week(full)
    expected = next(
        s for s in full.result.sessions if s.session_id == "ticket-carry"
    )

    client = WindowedClient(_carried_traces())
    narrowed = _run(client, cached=cached)
    actual = next(
        s for s in narrowed.result.sessions if s.session_id == "ticket-carry"
    )

    assert "ticket-carry" in client.session_lookups
    assert actual.cohort_week == expected.cohort_week
    assert actual.turn_count == expected.turn_count
    assert actual.outcome == expected.outcome


def test_a_carried_session_is_not_counted_twice():
    """Its cached copy must give way to the freshly analyzed one."""
    full = _run(WindowedClient(_carried_traces()))
    narrowed = _run(WindowedClient(_carried_traces()), cached=_by_week(full))

    identifiers = [s.session_id for s in narrowed.result.sessions]
    assert identifiers.count("ticket-carry") == 1
    assert len(identifiers) == len(set(identifiers))


def test_a_carried_session_keeps_its_cached_copy_when_the_refetch_fails():
    """A failed lookup must not downgrade the ticket to a partial view."""
    from weekly_cs_report.langfuse_client import LangfuseAPIError

    full = _run(WindowedClient(_carried_traces()))
    cached = _by_week(full)
    expected = next(
        s for s in full.result.sessions if s.session_id == "ticket-carry"
    )

    class FailingLookup(WindowedClient):
        def list_traces_by_session(self, session_id: str) -> list[dict]:
            raise LangfuseAPIError("GET", "/api/public/traces", 500)

    narrowed = _run(FailingLookup(_carried_traces()), cached=cached)
    actual = next(
        s for s in narrowed.result.sessions if s.session_id == "ticket-carry"
    )

    assert actual.cohort_week == expected.cohort_week
    assert actual.turn_count == expected.turn_count


def test_enrichment_still_covers_the_whole_window_when_traces_are_narrowed():
    """Narrowing enrichment too drops skill and TPE signals from real tickets.

    Enrichment lanes are keyed by observation start time, not by the ticket's
    cohort week, so a ticket opened just before the narrowed trace boundary
    still has observations behind it. Narrowing this bound measurably moved
    coverage_skill and coverage_tpe in production.
    """
    full_client = WindowedClient(_traces())
    full = _run(full_client)
    full_enrichment_start = full_client.enrichment_bounds[0][0]

    cached_client = WindowedClient(_traces())
    _run(cached_client, cached=_by_week(full))

    # Traces narrow; observations must not.
    assert cached_client.bounds[0][0] > full_client.bounds[0][0]
    assert cached_client.enrichment_bounds[0][0] == full_enrichment_start


def test_cache_round_trip_preserves_every_session_field(tmp_path):
    full = _run(WindowedClient(_traces()))
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    path = directory / "session_cache.json"

    write_session_cache(
        path,
        _by_week(full),
        storage_version=STORAGE_VERSION,
        fetched_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    restored = load_session_cache(path, storage_version=STORAGE_VERSION)

    assert restored == _by_week(full)


def test_a_cache_from_another_storage_version_is_discarded(tmp_path):
    """Stored sessions feed aggregates whose shape the projection version sets."""
    full = _run(WindowedClient(_traces()))
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    path = directory / "session_cache.json"

    write_session_cache(
        path,
        _by_week(full),
        storage_version=STORAGE_VERSION,
        fetched_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert load_session_cache(path, storage_version=STORAGE_VERSION + 1) == {}


def test_a_week_holding_a_foreign_cohort_is_rejected(tmp_path):
    """A session filed under the wrong week would be counted in the wrong week."""
    full = _run(WindowedClient(_traces()))
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    path = directory / "session_cache.json"

    weeks = _by_week(full)
    target = min(weeks)
    foreign = next(iter(weeks[max(weeks)]))

    with pytest.raises(SessionCacheError):
        write_session_cache(
            path,
            {target: (*weeks[target], foreign)},
            storage_version=STORAGE_VERSION,
            fetched_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
