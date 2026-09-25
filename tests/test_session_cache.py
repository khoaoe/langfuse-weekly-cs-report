from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

import pytest
from tests.fixtures.traces import TRANSFER_HTML, trace
from weekly_cs_report.dashboard_schema import project_dashboard
from weekly_cs_report import report as report_module
from weekly_cs_report.report import compute_report
from weekly_cs_report.session_cache import (
    SessionCacheError,
    load_session_cache,
    write_session_cache,
)
from dataclasses import replace


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
# A Wednesday, so the reporting window has a week-to-date cohort as well as
# complete weeks behind it.
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


class WindowedClient:
    """Fake Langfuse that honours the requested window, as the real API does.

    A client that returns every trace regardless of bounds would make a
    narrowed refresh look identical to a full one for the wrong reason: the
    whole point is that the narrowed run never sees the older traces.
    """

    def __init__(self, traces: list[dict], observations: list[dict] = ()) -> None:
        self._traces = traces
        self._observations = list(observations)
        self.bounds: list[tuple[datetime, datetime]] = []
        self.enrichment_bounds: list[tuple[datetime, datetime]] = []
        self.session_lookups: list[str] = []
        self.observation_lookups: list[str] = []

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
        self.observation_lookups.append(trace_id)
        return [o for o in self._observations if o["traceId"] == trace_id]

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
        return iter([
            o
            for o in self._observations
            if o["name"] == name
            and _from_start_time <= _stamp(o["startTime"]) <= _to_start_time
        ])


def _stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _observations_for(traces: list[dict], *, tpe_only: set[str] = frozenset()) -> list[dict]:
    """A skill and a TPE observation per trace, starting with the trace.

    Traces named in `tpe_only` carry TPE alone, so a ticket's TPE signal can
    be pinned to exactly one of its turns.
    """
    rows = []
    for raw in traces:
        trace_id, start = raw["id"], raw["timestamp"]
        rows.append({
            "id": f"tpe-{trace_id}", "traceId": trace_id, "startTime": start,
            "name": "tool:get_transaction_processing_engine_data",
            "output": {"result": {"transstatus": 1, "stepresult": "-49"}},
        } if trace_id in tpe_only else {
            "id": f"exec-{trace_id}", "traceId": trace_id, "startTime": start,
            "name": "execute", "metadata": {"skills_used": ["ibft"]},
        })
    return rows


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


def _run(client, cached=None, *, as_of=AS_OF):
    return compute_report(
        client,
        as_of=as_of,
        weeks=8,
        include_current_wtd=True,
        taxonomy_path=TAXONOMY_PATH,
        refresh_timeout_seconds=30.0,
        session_cache=cached,
    )


def test_cached_refresh_produces_the_same_dashboard_as_a_full_refresh():
    """A narrowed refresh that reuses cached weeks must not change any number.

    This is the whole contract: reusing a closed week is only safe if the
    dashboard it produces is indistinguishable from refetching that week.
    """
    full = _run(WindowedClient(_traces()))
    expected = project_dashboard(full).dashboard_dict()

    cached_client = WindowedClient(_traces())
    cached = _run(cached_client, cached=full.session_cache)
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
    _run(cached_client, cached=full.session_cache)

    assert cached_client.bounds[0][0] > full_start


def test_a_refresh_rereads_only_the_overlap_before_the_previous_one():
    """Only what arrived since the last refresh, plus room for late writes.

    Langfuse filters by a trace's own timestamp, not by when it was written,
    and writes were measured landing up to 8 min late. Rereading the overlap
    before the previous refresh's reach picks those up on a later refresh.
    """
    full = _run(WindowedClient(_traces()))
    client = WindowedClient(_traces())
    _run(client, cached=full.session_cache)

    assert client.bounds[0][0] == (
        full.session_cache.fetched_at - report_module._REFETCH_OVERLAP
    )


def _open_week_traces() -> list[dict]:
    """An open-week ticket that opened more than the overlap before AS_OF."""
    return [
        *_traces(),
        trace("open-0", "ticket-open", 0, "2026-07-27T01:00:00Z", "Opened Monday"),
    ]


def test_an_open_week_ticket_outside_the_overlap_is_reused_not_refetched():
    """The open week is where most refreshes would otherwise spend requests."""
    full = _run(WindowedClient(_open_week_traces()))
    client = WindowedClient(_open_week_traces())
    cached = _run(client, cached=full.session_cache)

    assert client.bounds[0][0] > _stamp("2026-07-27T01:00:00Z")
    reused = next(s for s in cached.result.sessions if s.session_id == "ticket-open")
    assert reused.cohort_status == "wtd"
    assert _comparable(cached) == _comparable(full)


def test_a_cache_older_than_a_day_is_rebuilt_in_full():
    """The safety net for what the overlap cannot see: writes later than it,
    edits and deletions of old traces."""
    before = datetime(2026, 7, 28, 9, tzinfo=VIETNAM)
    after = before + timedelta(hours=25)
    traces = _open_week_traces()
    stale = _run(LangfuseAt(traces, now=before), as_of=before)
    chained = _run(LangfuseAt(traces, now=before + timedelta(hours=12)),
                   stale.session_cache, as_of=before + timedelta(hours=12))

    full_client = LangfuseAt(traces, now=after)
    _run(full_client, as_of=after)
    client = LangfuseAt(traces, now=after)
    _run(client, chained.session_cache, as_of=after)

    # The chained run was incremental, but it does not reset the clock.
    assert client.bounds[0][0] == full_client.bounds[0][0]


def test_refreshing_every_few_hours_across_a_monday_matches_a_full_refresh():
    """What production does: a refresh every few minutes, chained.

    Crosses the Monday boundary, where open-week tickets reused from the cache
    must turn into complete-week ones without being refetched.
    """
    traces = [
        *_moving_traces(),
        # Opens early in the week that closes mid-chain: far enough back that
        # it is reused from the cache, never refetched, when Monday comes.
        trace("tue-0", "ticket-tuesday", 0, "2026-07-28T05:00:00Z", "Tuesday"),
    ]
    observations = _observations_for(traces)
    steps = [
        datetime(2026, 8, 2, 20, tzinfo=VIETNAM),
        datetime(2026, 8, 3, 1, tzinfo=VIETNAM),
        datetime(2026, 8, 3, 9, tzinfo=VIETNAM),
        datetime(2026, 8, 3, 18, tzinfo=VIETNAM),
    ]
    cache = None
    for index, now in enumerate(steps):
        full = _run(LangfuseAt(traces, observations, now=now), as_of=now)
        client = LangfuseAt(traces, observations, now=now)
        cached = _run(client, cache, as_of=now)
        if index:
            assert client.bounds[0][0] == (
                cache.fetched_at - report_module._REFETCH_OVERLAP
            ), now
        assert cached.enrichment_status == "complete", now
        assert _comparable(cached) == _comparable(full), now
        cache = cached.session_cache
    tuesday = next(s for s in cached.result.sessions if s.session_id == "ticket-tuesday")
    assert tuesday.cohort_status == "complete"


def test_a_session_analyzed_now_wins_over_its_cached_copy():
    """The fresh copy saw every trace the cached one did, plus later turns.

    Feeds the merge a deliberately wrong cached copy of a session the narrowed
    run analyzes itself, and asserts the freshly analyzed values survive.
    """
    full = _run(WindowedClient(_carried_traces()))
    cached = full.session_cache.weeks
    fresh_week, fresh = next(
        (week, s)
        for week, sessions in cached.items()
        for s in sessions
        if s.session_id == "ticket-carry"
    )

    poisoned = dict(cached)
    poisoned[fresh_week] = tuple(
        replace(s, turn_count=s.turn_count + 99, outcome="unclassified")
        if s is fresh else s
        for s in cached[fresh_week]
    )
    poisoned = replace(full.session_cache, weeks=poisoned)

    merged = _run(WindowedClient(_carried_traces()), cached=poisoned)
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
        trace("carry-1", "ticket-carry", 1, "2026-07-29T04:00:00Z", "Later turn"),
    ]


def test_a_session_carried_into_the_window_keeps_its_original_cohort_week():
    """The later turn alone would file the ticket under the wrong week.

    Without refetching the session whole, `select_candidate_sessions` treats
    the later turn as the ticket's first trace and books it into the current
    week with a turn count of one.
    """
    full = _run(WindowedClient(_carried_traces()))
    cached = full.session_cache
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
    narrowed = _run(WindowedClient(_carried_traces()), cached=full.session_cache)

    identifiers = [s.session_id for s in narrowed.result.sessions]
    assert identifiers.count("ticket-carry") == 1
    assert len(identifiers) == len(set(identifiers))


def test_a_carried_session_keeps_its_cached_copy_when_the_refetch_fails():
    """A failed lookup must not downgrade the ticket to a partial view."""
    from weekly_cs_report.langfuse_client import LangfuseAPIError

    full = _run(WindowedClient(_carried_traces()))
    cached = full.session_cache
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


def _signal_traces() -> tuple[list[dict], list[dict]]:
    """Carried ticket whose TPE signal lives only on its first, cached-week turn."""
    traces = _carried_traces()
    return traces, _observations_for(traces, tpe_only={"carry-0"})


def test_cached_refresh_with_observations_matches_a_full_refresh():
    """Narrowed traces AND observations must still reproduce every figure."""
    traces, observations = _signal_traces()
    full = _run(WindowedClient(traces, observations))
    expected = project_dashboard(full).dashboard_dict()

    client = WindowedClient(traces, observations)
    cached = _run(client, cached=full.session_cache)
    actual = project_dashboard(cached).dashboard_dict()

    assert cached.enrichment_status == "complete"
    for key in expected:
        if key == "source":
            continue
        assert actual[key] == expected[key], key
    assert actual["source"]["observations_fetched"] < expected["source"]["observations_fetched"]


def test_enrichment_lanes_narrow_with_the_traces_plus_the_margin():
    """A full-window observation crawl is most of what a refresh costs Langfuse."""
    traces, observations = _signal_traces()
    full_client = WindowedClient(traces, observations)
    full = _run(full_client)

    client = WindowedClient(traces, observations)
    _run(client, cached=full.session_cache)

    trace_start = client.bounds[0][0]
    enrichment_start = client.enrichment_bounds[0][0]
    assert enrichment_start == trace_start - report_module._ENRICHMENT_MARGIN
    assert enrichment_start > full_client.enrichment_bounds[0][0]


def test_a_carried_session_keeps_the_signals_of_its_older_turns():
    """The narrowed lanes never see the first turn; its trace id lookup must."""
    traces, observations = _signal_traces()
    full = _run(WindowedClient(traces, observations))
    expected = next(s for s in full.result.sessions if s.session_id == "ticket-carry")
    assert expected.dimensions.tpe_signals  # the fixture pins TPE to carry-0

    client = WindowedClient(traces, observations)
    narrowed = _run(client, cached=full.session_cache)
    actual = next(s for s in narrowed.result.sessions if s.session_id == "ticket-carry")

    assert actual.dimensions == expected.dimensions
    # Only the turn outside the lanes is looked up, never one they cover.
    assert client.observation_lookups == ["carry-0"]


def test_a_failed_carried_observation_lookup_fails_enrichment_closed():
    """Silently missing a carried ticket's signals would lower coverage."""
    from weekly_cs_report.langfuse_client import LangfuseAPIError

    traces, observations = _signal_traces()
    full = _run(WindowedClient(traces, observations))

    class FailingObservations(WindowedClient):
        def list_observations(self, trace_id: str) -> list[dict]:
            raise LangfuseAPIError("GET", "/api/public/observations", 500)

    narrowed = _run(FailingObservations(traces, observations), cached=full.session_cache)

    assert narrowed.enrichment_status == "partial"
    assert "carried_trace_observations" in narrowed.failed_enrichment_lanes


def _private_path(tmp_path: Path) -> Path:
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    return directory / "session_cache.json"


def _ledger_traces() -> list[dict]:
    """Traces that exercise everything the cache must carry besides sessions."""
    unkeyed = trace("unkeyed-0", None, 0, "2026-07-02T02:00:00Z", "No session")
    return [
        *_carried_traces(),
        trace("bad-0", "ticket-bad", None, "2026-07-01T03:00:00Z", "No turn"),
        unkeyed,
    ]


def test_cache_round_trip_preserves_everything_it_stores(tmp_path):
    full = _run(WindowedClient(_ledger_traces()))
    cache = full.session_cache
    assert cache.invalid_keyed and cache.unkeyed and cache.seen
    path = _private_path(tmp_path)

    write_session_cache(path, cache)

    assert load_session_cache(path) == cache


def test_a_cache_from_other_analysis_code_is_not_reused():
    """Stored outcomes are only as current as the code that classified them."""
    full = _run(WindowedClient(_traces()))
    stale = replace(full.session_cache, fingerprint="0" * 64)

    client = WindowedClient(_traces())
    _run(client, cached=stale)

    full_client = WindowedClient(_traces())
    _run(full_client)
    assert client.bounds[0][0] == full_client.bounds[0][0]


def test_a_cache_in_the_old_format_is_ignored_not_an_error(tmp_path):
    from weekly_cs_report.cache_store import atomic_private_json

    path = _private_path(tmp_path)
    atomic_private_json(
        path,
        {"schema_version": 1, "storage_version": 32, "weeks": {}},
        SessionCacheError,
        "session cache is invalid",
    )

    assert load_session_cache(path) is None


def test_a_week_holding_a_foreign_cohort_is_rejected(tmp_path):
    """A session filed under the wrong week would be counted in the wrong week."""
    full = _run(WindowedClient(_traces()))
    weeks = full.session_cache.weeks
    target = min(weeks)
    foreign = next(iter(weeks[max(weeks)]))

    with pytest.raises(SessionCacheError):
        write_session_cache(
            _private_path(tmp_path),
            replace(
                full.session_cache,
                weeks={**weeks, target: (*weeks[target], foreign)},
            ),
        )


def test_a_carried_sessions_chat_traces_are_not_analyzed():
    """A session id is shared with chat follow-ups the ticket filter drops.

    A full refresh never sees them. Refetching the session by id must not let
    them in either: a chat trace without a turn quarantines the whole ticket.
    """
    chat = trace("carry-chat", "ticket-carry", None, "2026-07-28T04:00:00Z", "Chat")
    chat["input"]["source"] = "chat"
    traces = [*_carried_traces(), chat]
    full = _run(WindowedClient(traces))
    expected = project_dashboard(full).dashboard_dict()

    narrowed = _run(WindowedClient(traces), cached=full.session_cache)
    actual = project_dashboard(narrowed).dashboard_dict()

    assert "ticket-carry" in {s.session_id for s in narrowed.result.sessions}
    for key in expected:
        if key != "source":
            assert actual[key] == expected[key], key


class LangfuseAt(WindowedClient):
    """A Langfuse that only holds what had been written by `now`."""

    def __init__(self, traces, observations=(), *, now: datetime) -> None:
        visible = [
            raw for raw in traces
            if _stamp(raw["timestamp"]) <= now
        ]
        super().__init__(
            visible,
            [o for o in observations if _stamp(o["startTime"]) <= now],
        )


def _moving_traces() -> list[dict]:
    """Tickets whose history keeps changing after their week closes.

    - ticket-late opens on a Sunday and comes back mid-next-week; once that
      later turn leaves the fetch window only the stored copy remembers it.
    - ticket-bad is invalid in a settled week and takes a valid turn later;
      that turn alone would analyze as a brand-new ticket.
    - ticket-pre starts in a week that later slides out of the window; a full
      refresh then reports it as starting before the window.
    """
    return [
        *_ledger_traces(),
        trace("late-a0", "ticket-sunday", 0, "2026-07-26T03:00:00Z", "Sunday"),
        trace("late-a1", "ticket-sunday", 1, "2026-07-29T03:00:00Z", "Back again"),
        trace("bad-1", "ticket-bad", 1, "2026-08-04T03:00:00Z", "Valid later"),
        trace("pre-0", "ticket-pre", 0, "2026-06-10T03:00:00Z", "Early"),
        trace("pre-1", "ticket-pre", 1, "2026-06-17T03:00:00Z", "Early again"),
    ]


def _comparable(run) -> dict:
    payload = project_dashboard(run).dashboard_dict()
    payload.pop("source")
    return payload


def test_refreshing_from_the_cache_matches_a_full_refresh_day_after_day(monkeypatch):
    """The cache is only safe if chaining it never drifts from a full refresh.

    Steps across two Monday boundaries, feeding each run the cache the previous
    one returned -- exactly what the serving process does -- against a Langfuse
    that grows with time.
    """
    monkeypatch.setattr(report_module, "_FULL_REBUILD_EVERY", timedelta(days=365))
    traces = _moving_traces()
    observations = _observations_for(traces)
    steps = [
        datetime(2026, 7, 27, 9, tzinfo=VIETNAM),
        datetime(2026, 7, 29, 12, tzinfo=VIETNAM),
        datetime(2026, 8, 3, 9, tzinfo=VIETNAM),
        datetime(2026, 8, 5, 12, tzinfo=VIETNAM),
        datetime(2026, 8, 10, 9, tzinfo=VIETNAM),
        datetime(2026, 8, 12, 12, tzinfo=VIETNAM),
    ]
    cache = None
    narrowed = 0
    for now in steps:
        full_client = LangfuseAt(traces, observations, now=now)
        full = _run(full_client, as_of=now)
        client = LangfuseAt(traces, observations, now=now)
        cached = _run(client, cache, as_of=now)
        narrowed += client.bounds[0][0] > full_client.bounds[0][0]
        assert cached.enrichment_status == "complete", now
        assert _comparable(cached) == _comparable(full), now
        cache = cached.session_cache
    # Every step after the first must actually have reused the cache.
    assert narrowed == len(steps) - 1


def test_a_cache_left_over_from_an_outage_does_not_hide_the_gap(monkeypatch):
    """A cache only knows traces up to when it was written.

    After two weeks without a refresh, the week it would normally reuse up to
    took turns it never saw; the fetch must reach back far enough to see them.
    """
    monkeypatch.setattr(report_module, "_FULL_REBUILD_EVERY", timedelta(days=365))
    traces = _moving_traces()
    observations = _observations_for(traces)
    before = datetime(2026, 7, 27, 9, tzinfo=VIETNAM)
    after = datetime(2026, 8, 12, 12, tzinfo=VIETNAM)
    stale = _run(LangfuseAt(traces, observations, now=before), as_of=before)

    full = _run(LangfuseAt(traces, observations, now=after), as_of=after)
    cached = _run(
        LangfuseAt(traces, observations, now=after),
        stale.session_cache,
        as_of=after,
    )

    assert _comparable(cached) == _comparable(full)


class LangfuseWithLateWrites(WindowedClient):
    """A Langfuse where some observations are written hours after they start."""

    def __init__(self, traces, observations, *, now: datetime, delays: dict) -> None:
        super().__init__(
            [raw for raw in traces if _stamp(raw["timestamp"]) <= now],
            [
                o for o in observations
                if _stamp(o["startTime"]) + delays.get(o["id"], timedelta()) <= now
            ],
        )


def test_an_observation_written_late_is_picked_up_by_a_later_refresh():
    """Langfuse filters by event time, so a late write predates the last fetch.

    The refresh that ran before the observation landed cached the ticket
    without its TPE signal. Only rereading the overlap lets the next refresh
    see it; a watermark at the previous refresh would freeze the gap.
    """
    traces = [*_traces(), trace("tpe-0", "ticket-tpe", 0, "2026-07-28T04:30:00Z", "Reply")]
    observations = _observations_for(traces, tpe_only={"tpe-0"})
    # Writes landed within 8 minutes when measured; an hour is well past that.
    delays = {"tpe-tpe-0": timedelta(hours=1)}
    before = datetime(2026, 7, 28, 12, tzinfo=VIETNAM)
    after = before + timedelta(hours=3)

    early = _run(
        LangfuseWithLateWrites(traces, observations, now=before, delays=delays),
        as_of=before,
    )
    assert not next(
        s for s in early.result.sessions if s.session_id == "ticket-tpe"
    ).dimensions.tpe_signals

    full = _run(
        LangfuseWithLateWrites(traces, observations, now=after, delays=delays),
        as_of=after,
    )
    cached = _run(
        LangfuseWithLateWrites(traces, observations, now=after, delays=delays),
        early.session_cache,
        as_of=after,
    )

    assert next(
        s for s in cached.result.sessions if s.session_id == "ticket-tpe"
    ).dimensions.tpe_signals
    assert _comparable(cached) == _comparable(full)


def test_an_observation_appended_to_an_old_trace_is_picked_up_without_a_new_turn():
    """Langfuse appends observations to a trace days after it ran.

    The session takes no new turn and the trace is far older than the overlap,
    so only the observation itself says the cached ticket is stale.
    """
    traces = [*_traces(), trace("tpe-0", "ticket-tpe", 0, "2026-07-26T02:00:00Z", "Reply")]
    appended = {
        "id": "tpe-late", "traceId": "tpe-0", "startTime": "2026-07-28T20:00:00Z",
        "name": "tool:get_transaction_processing_engine_data",
        "output": {"result": {"transstatus": 1, "stepresult": "-49"}},
    }
    observations = [*_observations_for(_traces()), appended]
    before = datetime(2026, 7, 28, 12, tzinfo=VIETNAM)
    after = before + timedelta(hours=20)

    early = _run(LangfuseAt(traces, observations, now=before), as_of=before)
    assert not next(
        s for s in early.result.sessions if s.session_id == "ticket-tpe"
    ).dimensions.tpe_signals

    full = _run(LangfuseAt(traces, observations, now=after), as_of=after)
    client = LangfuseAt(traces, observations, now=after)
    cached = _run(client, early.session_cache, as_of=after)

    assert client.bounds[0][0] > full_client_start(after)
    assert client.session_lookups == ["ticket-tpe"]
    assert next(
        s for s in cached.result.sessions if s.session_id == "ticket-tpe"
    ).dimensions.tpe_signals
    assert _comparable(cached) == _comparable(full)


def full_client_start(as_of: datetime) -> datetime:
    client = LangfuseAt([], now=as_of)
    _run(client, as_of=as_of)
    return client.bounds[0][0]


def test_carried_lookups_run_four_at_a_time_in_order_and_stop_on_error():
    """Parallel, but never above the lanes' peak; a failure starts nothing new."""
    import time

    active = peak = 0
    lock = threading.Lock()
    started: list[int] = []

    def lookup(item: int) -> int:
        nonlocal active, peak
        with lock:
            started.append(item)
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        if item == 5:
            raise RuntimeError("lookup failed")
        return item * 10

    assert report_module._bounded_map(lookup, list(range(5))) == [0, 10, 20, 30, 40]
    assert peak == report_module._CARRIED_LOOKUP_WORKERS == 4

    started.clear()
    with pytest.raises(RuntimeError):
        report_module._bounded_map(lookup, list(range(40)))
    assert len(started) < 40
