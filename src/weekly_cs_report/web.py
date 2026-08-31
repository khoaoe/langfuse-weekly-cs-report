from __future__ import annotations

import argparse
import base64
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
from typing import Sequence
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import uvicorn

from .ab_test import AbTestSnapshot, compute_ab_test, default_window
from .ab_test_cache import (
    AbTestCacheError,
    CachedAbTestSnapshot,
    load_ab_test_cache,
    write_ab_test_cache,
)
from .categories import load_taxonomy
from .cli import ConfigurationError, PROJECT_ROOT, load_environment
from .csat_cache import CSATCacheError, load_csat_cache
from .dashboard_cache import CacheView, ProtectedSnapshotStore, SnapshotManager
from .dashboard_schema import (
    entry_coverage_ticket_page,
    project_dashboard,
    ticket_day_aggregate,
    ticket_page,
)
from .entry_coverage_cache import (
    EntryCoverageCacheError,
    load_entry_coverage_cache,
)
from .escalation_dossier import EscalationDossier, build_dossier, rank_candidates
from .escalation_narrator import (
    ExplainLLMClient,
    Narration,
    load_explain_settings,
    narrate,
)
from .explain_context import load_explain_config
from .narration_validator import validate as validate_narration
from .langfuse_client import LangfuseAPIError, LangfuseClient
from .model_discovery import discover_first_seen, list_recent_models
from .model_list_cache import (
    CachedModelList,
    ModelListCacheError,
    load_model_list_cache,
    write_model_list_cache,
)
from .model_seen_cache import (
    CachedModelSeen,
    ModelSeenCache,
    ModelSeenCacheError,
    load_model_seen_cache,
    write_model_seen_cache,
)
from .reconciliation_cache import (
    ReconciliationCacheError,
    load_reconciliation_cache,
)
from .report import compute_report
from .runtime_logging import configure_json_logging, emit_event
from .skill_rules import parse_snapshot
from .trace_explainer import build_trace_explanation


_AUTH_MODES = frozenset({"off", "proxy", "basic"})
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_ALLOWED_IDENTITY_HEADERS = frozenset(
    {
        "remote-user",
        "x-auth-request-user",
        "x-authenticated-user",
        "x-forwarded-user",
    }
)
_QUERY_NAMES = (
    "cohort_week",
    "cohort_weeks",
    "opened_from",
    "opened_to",
    "aggregate",
    "outcome",
    "ticket_id",
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
    "tpe_code",
    "model_core",
    "transfer_reason",
    "csat_satisfaction",
    "gt4_turn",
    "transferred",
    "is_weekend_start",
    "week_definition",
    "sort_by",
    "sort_direction",
    "page",
    "page_size",
)
_QUERY_NAME_SET = frozenset(_QUERY_NAMES)
_MULTI_SELECT_QUERY_NAMES = frozenset(
    {
        "cohort_weeks",
        "outcome",
        "issue_category",
        "app",
        "product_code",
        "skill",
        "tpe_code",
        "model_core",
        "transfer_reason",
        "csat_satisfaction",
    }
)
_ENTRY_QUERY_NAMES = (
    "week_definition",
    "cohort_weeks",
    "opened_from",
    "opened_to",
    "status",
    "page",
    "page_size",
    "sort_by",
    "sort_dir",
)
_ENTRY_QUERY_NAME_SET = frozenset(_ENTRY_QUERY_NAMES)
_MAX_QUERY_PAIRS = len(_QUERY_NAMES)
_MAX_QUERY_VALUE_LENGTH = 128
_MAX_RAW_QUERY_BYTES = 8192
_INTEGER_QUERY = re.compile(r"[0-9]{1,9}\Z")
_TRACE_EXPLAIN_TICKET_ID = re.compile(r"[0-9]{1,20}\Z")
_TRACE_EXPLAIN_CACHE_TTL_SECONDS = 300.0
_TRACE_EXPLAIN_CACHE_MISS = object()
_AB_TEST_MAX_WINDOW_DAYS = 60
_AB_TEST_CACHE_TTL_SECONDS = 300.0
_AB_TEST_DEADLINE_SECONDS = 240.0
_AB_TEST_MAX_ARMS = 8
_AB_TEST_ARMS_VALUE_LENGTH = 1024
_AB_TEST_MODEL_LIST_LIMIT = 8
_MODEL_LIST_CACHE_TTL_SECONDS = 60.0
_STATIC_ROOT = Path(__file__).with_name("static")
_STATIC_INDEX = _STATIC_ROOT / "index.html"
_SPA_ROOT = _STATIC_ROOT / "spa"
_SPA_ASSET_DIRECTORY = "assets"
_ASSET_NAME = re.compile(r"[A-Za-z0-9._-]+\Z")
_FRONTEND_MODES = frozenset({"spa", "legacy"})
_REFRESH_DEADLINE_ENV = "DASHBOARD_REFRESH_DEADLINE_SECONDS"
_TRACE_PAGE_LIMIT_ENV = "DASHBOARD_MAX_TRACE_PAGES"
_REFRESH_DEADLINE_ERROR = "DASHBOARD_REFRESH_DEADLINE_SECONDS must be between 30 and 300"
_TRACE_PAGE_LIMIT_ERROR = "DASHBOARD_MAX_TRACE_PAGES must be an integer between 1 and 500"

# Hashed build output is immutable for its lifetime, but it is only ever served
# to an authenticated operator, so it must never enter a shared cache.
SPA_ASSET_CACHE_CONTROL = "private, max-age=31536000, immutable"
_SNAPSHOT_FILENAME = "dashboard_snapshot.json"
_CSAT_CACHE_FILENAME = "csat_cache.json"
_RECONCILIATION_CACHE_FILENAME = "outcome_reconciliation_cache.json"
_ENTRY_COVERAGE_CACHE_FILENAME = "entry_coverage_cache.json"
_MODEL_SEEN_CACHE_FILENAME = "model_seen_cache.json"
_AB_TEST_CACHE_FILENAME = "ab_test_snapshot_cache.json"
_MODEL_LIST_CACHE_FILENAME = "model_list_cache.json"
_MODEL_LIST_BACKGROUND_INTERVAL_SECONDS = 300.0
_FRESHDESK_COOKIE_FILENAME = "freshdesk_cookie"
_FRESHDESK_COOKIE_STATE_FILENAME = "freshdesk_cookie_state.json"
_TEMP_SNAPSHOT_NAME = re.compile(r"\.dashboard_snapshot\..+\.tmp\Z")
_RUNTIME_DIRECTORY_ERROR = "dashboard runtime directory is unsafe"
_REFRESH_ACTION_HEADER = "X-Dashboard-Action"
_REFRESH_ACTION_VALUE = "refresh"
_COOKIE_ACTION_VALUE = "update_freshdesk_cookie"
_COOKIE_BODY_LIMIT_BYTES = 8 * 1024
_COOKIE_POST_LIMIT = 5
_COOKIE_POST_WINDOW_SECONDS = 60.0
_INLINE_STYLE = re.compile(r"<style>(.*?)</style>", re.DOTALL)
_INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.DOTALL)
_PLACEHOLDER = (
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<title>Dashboard unavailable</title></head>"
    "<body><h1>Dashboard unavailable</h1></body></html>"
)


def spa_index_path() -> Path:
    """Absolute path of the built SPA document inside the installed package."""

    return _SPA_ROOT / "index.html"


def spa_build_present() -> bool:
    return spa_index_path().is_file()


@dataclass(frozen=True)
class WebSettings:
    auth_mode: str
    identity_header: str
    frontend_mode: str = "spa"

    def __post_init__(self) -> None:
        if self.auth_mode not in _AUTH_MODES:
            raise ValueError("auth_mode must be off, proxy, or basic")
        if self.frontend_mode not in _FRONTEND_MODES:
            raise ValueError("frontend_mode must be spa or legacy")
        if not isinstance(self.identity_header, str) or not _HEADER_NAME.fullmatch(
            self.identity_header
        ):
            raise ValueError("identity_header must be a non-empty HTTP header name")
        if self.identity_header.casefold() not in _ALLOWED_IDENTITY_HEADERS:
            raise ValueError("identity_header is not approved for proxy authentication")


class _TraceExplainCache:
    """In-process TTL cache keyed by ticket_id.

    A cached value of None is a confirmed "no trace found" result, distinct
    from a cache miss — both are legitimate outcomes worth remembering for
    the TTL window. Langfuse errors are never cached: a transient outage
    must not lock the next request out of a retry.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = _TRACE_EXPLAIN_CACHE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, object]] = {}

    def get(self, ticket_id: str) -> object:
        with self._lock:
            entry = self._entries.get(ticket_id)
            if entry is None:
                return _TRACE_EXPLAIN_CACHE_MISS
            expires_at, value = entry
            if self._monotonic() >= expires_at:
                del self._entries[ticket_id]
                return _TRACE_EXPLAIN_CACHE_MISS
            return value

    def set(self, ticket_id: str, value: object) -> None:
        with self._lock:
            self._entries[ticket_id] = (self._monotonic() + self._ttl_seconds, value)


@lru_cache(maxsize=1)
def _trace_explain_taxonomy():
    return load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json")


@lru_cache(maxsize=1)
def _why_explain_config():
    return load_explain_config(PROJECT_ROOT / "config" / "explain_context.v1.json")


@lru_cache(maxsize=1)
def _why_skill_rules():
    return parse_snapshot(PROJECT_ROOT / "skills-snapshot")


# E3/E5/E6 never carry a case to narrate (spec 8.2); NONE means nothing was
# escalated at all. E8 (output content check failed) and E9 (the tone_llm
# guardrail itself crashed) are about the drafted response's content/an
# infra fault, not a skill rule -- no case citation applies either. Calling
# the LLM with an empty enum is never valid.
_NO_CANDIDATE_BRANCHES = frozenset({"E3", "E5", "E6", "E8", "E9", "NONE"})


def _narration_possible(dossier: EscalationDossier) -> bool:
    """Same early-exit check _explain() makes -- exposed so /why can decide,
    without ever calling the LLM, whether /why-narration is worth fetching
    at all (it never is for E3/E5/E6/E8/E9/NONE or a branch with no case)."""

    return dossier.escalation_class not in _NO_CANDIDATE_BRANCHES and bool(
        dossier.rule_candidates
    )


def _explain(dossier: EscalationDossier) -> tuple[Narration | None, str]:
    """Tầng 2 + Tầng 3 orchestration for one dossier. Never raises."""

    if not _narration_possible(dossier):
        return None, "skipped"

    settings = load_explain_settings()
    if settings is None:
        return None, "disabled"

    tools_called = tuple(
        ev.step_key.removeprefix("tool:").split("__", 1)[0] for ev in dossier.tool_evidence
    )
    known_values = tuple(ev.value for ev in dossier.tool_evidence)
    shortlist = rank_candidates(
        list(dossier.rule_candidates), tools_called=tools_called, known_values=known_values
    )

    try:
        client = ExplainLLMClient(settings)
    except Exception:
        return None, "unavailable"
    try:
        raw = narrate(client, dossier, shortlist)
    finally:
        client.close()

    if raw is None:
        return None, "unavailable"

    quoted_line = raw.can_cu.trich_dan if raw.can_cu is not None else None
    if not validate_narration(raw, dossier, quoted_line):
        return None, "rejected"
    return raw, "ok"


class _AbTestBackgroundCache:
    """Refreshes the AB Test default window on its own schedule.

    A custom time-range read still goes through the per-request path in
    ``ab_test`` route (its own short-TTL cache); this class exists only so the
    common case -- the default window every reader sees on first load -- is
    already computed and instant, the same trade the main dashboard snapshot
    makes. Unlike ``SnapshotManager`` this does not block on disk state at
    startup -- it seeds from ``cache_path`` (if given) synchronously in
    ``__init__`` so a cold start still serves the last-known payload instead
    of a blank/loading state, then keeps writing after every successful
    background refresh. This stays a bolt-on store, not a merge into
    ``SnapshotManager``: ``ab_test.py``'s own module docstring requires this
    layer to remain independent of the weekly snapshot pipeline's enrichment
    gate.
    """

    def __init__(
        self,
        loader: Callable[[], dict[str, object]],
        *,
        interval_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        cache_path: Path | None = None,
    ) -> None:
        self._loader = loader
        self._interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._cache_path = cache_path
        self._lock = threading.Lock()
        self._payload: dict[str, object] | None = None
        self._last_success_at: float | None = None
        self._last_error_code: str | None = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if cache_path is not None:
            try:
                cached = load_ab_test_cache(cache_path)
            except AbTestCacheError:
                emit_event("ab_test_cache_load_ignored", code="invalid_cache")
                cached = None
            if cached is not None:
                self._payload = cached.payload

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._refresh_once()
            self._stop_event.wait(self._interval_seconds)

    def _refresh_once(self) -> None:
        try:
            payload = self._loader()
        except Exception:
            with self._lock:
                self._last_error_code = "refresh_failed"
            emit_event("ab_test_background_refresh_failure")
            return
        with self._lock:
            self._payload = payload
            self._last_success_at = self._monotonic()
            self._last_error_code = None
        emit_event("ab_test_background_refresh_success")
        if self._cache_path is not None:
            try:
                write_ab_test_cache(
                    self._cache_path,
                    CachedAbTestSnapshot(
                        generated_at=_utc_iso(datetime.now(timezone.utc)),
                        arms_key="default",
                        payload=payload,
                    ),
                )
            except AbTestCacheError:
                emit_event("ab_test_cache_write_ignored", code="write_failed")

    def get(self) -> tuple[dict[str, object] | None, str | None]:
        with self._lock:
            return self._payload, self._last_error_code


class _ModelListBackgroundCache:
    """Refreshes the AB-test model picker's candidate list on its own schedule.

    `list_recent_models` pages every ticket trace in its lookback window (see
    `model_discovery.py`'s module docstring for why it must read the
    ticket-scoped `model_core` field rather than a cheap aggregation query) --
    too expensive to run inline on the request that opens the picker. This
    mirrors `_AbTestBackgroundCache`: seed from disk at startup so a cold
    start still serves the last-known list, then keep writing after every
    successful background refresh.
    """

    def __init__(
        self,
        loader: Callable[[], list[str]],
        *,
        interval_seconds: float = _MODEL_LIST_BACKGROUND_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        cache_path: Path | None = None,
    ) -> None:
        self._loader = loader
        self._interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._cache_path = cache_path
        self._lock = threading.Lock()
        self._models: list[str] | None = None
        self._last_success_at: float | None = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if cache_path is not None:
            try:
                cached = load_model_list_cache(cache_path)
            except ModelListCacheError:
                emit_event("model_list_cache_load_ignored", code="invalid_cache")
                cached = None
            if cached is not None:
                self._models = list(cached.models)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._refresh_once()
            self._stop_event.wait(self._interval_seconds)

    def _refresh_once(self) -> None:
        try:
            models = self._loader()
        except Exception:
            emit_event("model_list_background_refresh_failure")
            return
        with self._lock:
            self._models = models
            self._last_success_at = self._monotonic()
        emit_event("model_list_background_refresh_success")
        if self._cache_path is not None:
            try:
                write_model_list_cache(
                    self._cache_path,
                    CachedModelList(
                        generated_at=_utc_iso(datetime.now(timezone.utc)),
                        models=tuple(models),
                    ),
                )
            except ModelListCacheError:
                emit_event("model_list_cache_write_ignored", code="write_failed")

    def get(self) -> list[str] | None:
        with self._lock:
            return None if self._models is None else list(self._models)


def create_app(
    manager: SnapshotManager,
    *,
    settings: WebSettings,
    runtime_directory: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        emit_event("service_start")
        try:
            yield
        finally:
            try:
                manager.close()
                background = getattr(app.state, "ab_test_background", None)
                if background is not None:
                    background.close()
                model_list_background = getattr(
                    app.state, "model_list_background", None
                )
                if model_list_background is not None:
                    model_list_background.close()
                client = getattr(app.state, "langfuse_client", None)
                if client is not None:
                    client.close()
            finally:
                emit_event("service_stop")
                app.state.resources_closed = True

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.snapshot_manager = manager
    app.state.resources_closed = False
    app.state.freshdesk_cookie_post_times = []
    app.state.trace_explain_cache = _TraceExplainCache()
    app.state.dossier_cache = _TraceExplainCache()
    app.state.narration_cache = _TraceExplainCache()
    app.state.ab_test_cache = _TraceExplainCache(
        ttl_seconds=_AB_TEST_CACHE_TTL_SECONDS
    )
    app.state.model_list_cache = _TraceExplainCache(
        ttl_seconds=_MODEL_LIST_CACHE_TTL_SECONDS
    )

    @app.middleware("http")
    async def security_boundary(request: Request, call_next):
        is_api = request.url.path.startswith("/api/")
        # Build output is as sensitive as the document that loads it: an
        # unauthenticated reader must not be able to enumerate the bundle.
        is_asset = request.url.path.startswith(f"/{_SPA_ASSET_DIRECTORY}/")
        protected = request.url.path == "/" or is_api or is_asset
        try:
            # "basic" mode trusts the platform's own HTTP Basic Auth at the
            # edge (e.g. Coolify/Traefik) as the real gate; that edge never
            # forwards an SSO identity header, so this app must not demand one.
            if (
                protected
                and settings.auth_mode == "proxy"
                and not _has_identity(request, settings.identity_header)
            ):
                response = JSONResponse(
                    {"detail": {"code": "authentication_required"}},
                    status_code=401,
                )
            else:
                response = await call_next(request)
        except Exception:
            if not is_api:
                raise
            response = JSONResponse(
                {"detail": {"code": "internal_error"}},
                status_code=500,
            )
        if is_api:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        elif is_asset:
            # Successful hashed assets set their immutable private policy in
            # the route. Authentication failures and not-found responses must
            # not be cached or content-sniffed.
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["X-Content-Type-Options"] = "nosniff"
        elif request.url.path == "/":
            for name, value in _document_security_headers(
                _effective_frontend_mode(settings)
            ).items():
                response.headers[name] = value
        return response

    @app.get("/api/dashboard")
    async def dashboard():
        view = manager.get()
        return JSONResponse(
            _state_envelope(view),
            status_code=202 if view.snapshot is None else 200,
        )

    @app.get("/api/tickets")
    async def tickets(request: Request):
        parsed, invalid_parameter = _parse_ticket_query(request)
        if invalid_parameter is not None:
            return _invalid_query(invalid_parameter)

        view = manager.get()
        if view.snapshot is None:
            return JSONResponse(
                {"detail": {"code": "dashboard_not_ready"}},
                status_code=503,
            )
        if parsed.pop("aggregate", False):
            opened_from = parsed.get("opened_from")
            opened_to = parsed.get("opened_to")
            if opened_from is None:
                return _invalid_query("opened_from")
            if opened_to is None:
                return _invalid_query("opened_to")
            try:
                days = ticket_day_aggregate(
                    view.snapshot,
                    opened_from=opened_from,
                    opened_to=opened_to,
                    week_definition=parsed.get("week_definition"),
                )
            except ValueError as error:
                return _invalid_query(_parameter_for_validation_error(error))
            return JSONResponse({"days": days})
        try:
            payload = ticket_page(view.snapshot, **parsed)
        except ValueError as error:
            return _invalid_query(_parameter_for_validation_error(error))
        return JSONResponse(payload)

    @app.get("/api/trace-explain/{ticket_id}")
    def trace_explain(ticket_id: str, request: Request):
        # Deliberately sync: this route makes a live, potentially slow
        # Langfuse HTTP call, so FastAPI must run it in its threadpool
        # rather than block the single-worker event loop used elsewhere.
        if not _TRACE_EXPLAIN_TICKET_ID.fullmatch(ticket_id):
            return JSONResponse(
                {"detail": {"code": "invalid_ticket_id"}}, status_code=400
            )

        cached = app.state.trace_explain_cache.get(ticket_id)
        if cached is _TRACE_EXPLAIN_CACHE_MISS:
            langfuse_client = getattr(request.app.state, "langfuse_client", None)
            if langfuse_client is None:
                return JSONResponse(
                    {"detail": {"code": "langfuse_unavailable"}}, status_code=503
                )
            try:
                explanation = build_trace_explanation(
                    langfuse_client, ticket_id, _trace_explain_taxonomy()
                )
            except LangfuseAPIError:
                return JSONResponse(
                    {"detail": {"code": "langfuse_unavailable"}}, status_code=503
                )
            app.state.trace_explain_cache.set(ticket_id, explanation)
        else:
            explanation = cached

        if explanation is None:
            return JSONResponse(
                {"detail": {"code": "trace_not_found"}}, status_code=404
            )
        return JSONResponse(asdict(explanation))

    @app.get("/api/trace-explain/{ticket_id}/why")
    def trace_explain_why(ticket_id: str, request: Request):
        # Deterministic dossier only -- build_dossier() is a Langfuse fetch
        # plus local computation, no LLM call, so this stays fast even when
        # the LLM endpoint is unreachable. llm_status "pending" tells the
        # frontend /why-narration is worth fetching; any other value here is
        # already final (no case candidates at all -- "skipped").
        if not _TRACE_EXPLAIN_TICKET_ID.fullmatch(ticket_id):
            return JSONResponse(
                {"detail": {"code": "invalid_ticket_id"}}, status_code=400
            )

        cached = app.state.dossier_cache.get(ticket_id)
        if cached is _TRACE_EXPLAIN_CACHE_MISS:
            langfuse_client = getattr(request.app.state, "langfuse_client", None)
            if langfuse_client is None:
                return JSONResponse(
                    {"detail": {"code": "langfuse_unavailable"}}, status_code=503
                )
            try:
                dossier = build_dossier(
                    langfuse_client,
                    ticket_id,
                    _trace_explain_taxonomy(),
                    _why_explain_config(),
                    _why_skill_rules(),
                    snapshot_root=PROJECT_ROOT / "skills-snapshot",
                )
            except LangfuseAPIError:
                return JSONResponse(
                    {"detail": {"code": "langfuse_unavailable"}}, status_code=503
                )
            app.state.dossier_cache.set(ticket_id, dossier)
        else:
            dossier = cached

        if dossier is None:
            return JSONResponse(
                {"detail": {"code": "trace_not_found"}}, status_code=404
            )

        llm_status = "pending" if _narration_possible(dossier) else "skipped"
        return JSONResponse(
            {
                "ticket_id": dossier.ticket_id,
                "escalation_class": dossier.escalation_class,
                "dossier": asdict(dossier),
                "narration": None,
                "llm_status": llm_status,
                "drift": {"changed": dossier.drift_changed},
            }
        )

    @app.get("/api/trace-explain/{ticket_id}/why-narration")
    def trace_explain_why_narration(ticket_id: str):
        # Separate, potentially slow (LLM) request. The frontend only calls
        # this once /why has returned llm_status == "pending", so its own
        # loading state never blocks the deterministic dossier from
        # rendering immediately.
        if not _TRACE_EXPLAIN_TICKET_ID.fullmatch(ticket_id):
            return JSONResponse(
                {"detail": {"code": "invalid_ticket_id"}}, status_code=400
            )

        cached = app.state.narration_cache.get(ticket_id)
        if cached is not _TRACE_EXPLAIN_CACHE_MISS:
            narration, llm_status = cached
            return JSONResponse(
                {
                    "narration": asdict(narration) if narration is not None else None,
                    "llm_status": llm_status,
                }
            )

        dossier = app.state.dossier_cache.get(ticket_id)
        if dossier is _TRACE_EXPLAIN_CACHE_MISS or dossier is None:
            return JSONResponse(
                {"detail": {"code": "trace_not_found"}}, status_code=404
            )

        narration, llm_status = _explain(dossier)
        app.state.narration_cache.set(ticket_id, (narration, llm_status))
        return JSONResponse(
            {
                "narration": asdict(narration) if narration is not None else None,
                "llm_status": llm_status,
            }
        )

    @app.get("/api/ab-test")
    def ab_test(request: Request):
        # Deliberately sync, same reasoning as trace-explain: a live Langfuse
        # call must run in FastAPI's threadpool, not the shared event loop.
        parsed = _parse_ab_test_query(request)
        if parsed is None:
            return JSONResponse(
                {"detail": {"code": "invalid_query"}}, status_code=400
            )
        window_start, window_end, arms = parsed
        # A wide window costs hundreds of trace pages, and the reader pans
        # across the same window repeatedly. Cache on the exact bounds and
        # the selected arms, since the same window can be re-queried with a
        # different model pair.
        cache_key = (
            f"{_utc_iso(window_start)}|{_utc_iso(window_end)}"
            f"|{','.join(arms) if arms is not None else ''}"
        )
        cached = app.state.ab_test_cache.get(cache_key)
        if cached is not _TRACE_EXPLAIN_CACHE_MISS:
            return JSONResponse(cached)

        langfuse_client = getattr(request.app.state, "langfuse_client", None)
        if langfuse_client is None:
            return JSONResponse(
                {"detail": {"code": "langfuse_unavailable"}}, status_code=503
            )
        try:
            snapshot = compute_ab_test(
                langfuse_client,
                window_start,
                window_end,
                _trace_explain_taxonomy(),
                csat_by_ticket=_csat_buckets_by_ticket(runtime_directory),
                deadline=time.monotonic() + _AB_TEST_DEADLINE_SECONDS,
                arms=arms,
            )
        except LangfuseAPIError:
            return JSONResponse(
                {"detail": {"code": "langfuse_unavailable"}}, status_code=503
            )
        payload = _ab_test_payload(snapshot)
        app.state.ab_test_cache.set(cache_key, payload)
        return JSONResponse(payload)

    @app.get("/api/ab-test/models")
    def ab_test_models(request: Request):
        # Deliberately sync, same reasoning as trace-explain: live Langfuse
        # calls must run in FastAPI's threadpool, not the shared event loop.
        langfuse_client = getattr(request.app.state, "langfuse_client", None)
        if langfuse_client is None:
            return JSONResponse(
                {"detail": {"code": "langfuse_unavailable"}}, status_code=503
            )
        now = datetime.now(timezone.utc)
        model_list_background = getattr(
            request.app.state, "model_list_background", None
        )
        background_models = (
            None if model_list_background is None else model_list_background.get()
        )
        if background_models is not None:
            # Already computed by the background refresh loop -- instant,
            # never blocks on the 14-day ticket trace scan `list_recent_models`
            # needs to stay correctly scoped to `model_core`.
            recent_models = background_models
        else:
            cached = app.state.model_list_cache.get("recent_models")
            if cached is not _TRACE_EXPLAIN_CACHE_MISS:
                recent_models = cached
            else:
                try:
                    recent_models = list_recent_models(
                        langfuse_client,
                        now=now,
                        deadline=time.monotonic() + _AB_TEST_DEADLINE_SECONDS,
                    )
                except LangfuseAPIError:
                    return JSONResponse(
                        {"detail": {"code": "langfuse_unavailable"}}, status_code=503
                    )
                app.state.model_list_cache.set("recent_models", recent_models)

        results = []
        for model in recent_models[:_AB_TEST_MODEL_LIST_LIMIT]:
            entry = _get_or_discover_first_seen(
                langfuse_client,
                runtime_directory,
                model,
                now=now,
                deadline=time.monotonic() + _AB_TEST_DEADLINE_SECONDS,
            )
            results.append(
                {
                    "model": model,
                    "first_seen": entry.first_seen,
                    "confirmed": entry.confirmed,
                }
            )
        return JSONResponse({"models": results})

    @app.get("/api/ab-test/default")
    async def ab_test_default():
        background = getattr(app.state, "ab_test_background", None)
        if background is None:
            return JSONResponse(
                {"status": "loading", "data": None}, status_code=202
            )
        payload, error_code = background.get()
        if payload is None:
            return JSONResponse(
                {
                    "status": "stale_error" if error_code else "loading",
                    "data": None,
                    "last_error_code": error_code,
                },
                status_code=202,
            )
        return JSONResponse(
            {"status": "ready", "data": payload, "last_error_code": error_code}
        )

    @app.get("/api/freshdesk-entry-coverage/tickets")
    async def freshdesk_entry_coverage_tickets(request: Request):
        parsed, invalid_parameter = _parse_entry_coverage_query(request)
        if invalid_parameter is not None:
            return _invalid_query(invalid_parameter)
        view = manager.get()
        if view.snapshot is None:
            return JSONResponse(
                {"detail": {"code": "dashboard_not_ready"}},
                status_code=503,
            )
        try:
            payload = entry_coverage_ticket_page(view.snapshot, **parsed)
        except ValueError as error:
            return _invalid_query(_entry_parameter_for_validation_error(error))
        return JSONResponse(payload)

    @app.post("/api/refresh")
    async def refresh(request: Request):
        if request.headers.get(_REFRESH_ACTION_HEADER) != _REFRESH_ACTION_VALUE:
            return JSONResponse(
                {"detail": {"code": "refresh_action_required"}},
                status_code=403,
            )
        view = manager.request_refresh(force=True)
        return JSONResponse(_state_envelope(view), status_code=202)

    @app.get("/api/freshdesk-cookie")
    async def freshdesk_cookie_state():
        return JSONResponse(_freshdesk_cookie_state_payload(runtime_directory))

    @app.post("/api/freshdesk-cookie")
    async def freshdesk_cookie_update(request: Request):
        if runtime_directory is None:
            return JSONResponse(
                {"detail": {"code": "freshdesk_cookie_unavailable"}},
                status_code=503,
            )
        if request.headers.get(_REFRESH_ACTION_HEADER) != _COOKIE_ACTION_VALUE:
            return JSONResponse(
                {"detail": {"code": "cookie_action_required"}},
                status_code=403,
            )
        now = time.monotonic()
        recent = [
            sent_at
            for sent_at in app.state.freshdesk_cookie_post_times
            if now - sent_at < _COOKIE_POST_WINDOW_SECONDS
        ]
        if len(recent) >= _COOKIE_POST_LIMIT:
            return JSONResponse(
                {"detail": {"code": "cookie_rate_limited"}},
                status_code=429,
            )
        app.state.freshdesk_cookie_post_times = recent + [now]

        body = await request.body()
        if len(body) > _COOKIE_BODY_LIMIT_BYTES:
            return JSONResponse(
                {"detail": {"code": "cookie_too_large"}},
                status_code=413,
            )
        try:
            payload = json.loads(body)
        except ValueError:
            return JSONResponse(
                {"detail": {"code": "cookie_invalid"}},
                status_code=400,
            )
        cookie = payload.get("cookie") if isinstance(payload, dict) else None
        if not isinstance(cookie, str) or not cookie.strip():
            return JSONResponse(
                {"detail": {"code": "cookie_invalid"}},
                status_code=400,
            )

        from .freshdesk_csat import (
            FreshdeskCSATError,
            FreshdeskUIClient,
            mark_cookie_verified,
            write_freshdesk_cookie,
        )

        try:
            with FreshdeskUIClient(cookie) as client:
                client.verify()
        except FreshdeskCSATError:
            return JSONResponse(
                {"detail": {"code": "cookie_invalid"}},
                status_code=400,
            )
        try:
            write_freshdesk_cookie(runtime_directory, cookie)
            mark_cookie_verified(runtime_directory)
        except FreshdeskCSATError:
            return JSONResponse(
                {"detail": {"code": "internal_error"}},
                status_code=500,
            )
        return JSONResponse(
            _freshdesk_cookie_state_payload(runtime_directory),
            status_code=202,
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readiness():
        view = manager.peek()
        if view.snapshot is None:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @app.get(f"/{_SPA_ASSET_DIRECTORY}/{{asset_path:path}}", include_in_schema=False)
    async def spa_asset(asset_path: str):
        resolved = _resolved_asset(asset_path)
        if resolved is None:
            return JSONResponse({"detail": {"code": "not_found"}}, status_code=404)
        return FileResponse(
            resolved,
            headers={
                "Cache-Control": SPA_ASSET_CACHE_CONTROL,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/")
    async def root():
        if _effective_frontend_mode(settings) == "spa":
            return FileResponse(spa_index_path())
        if _STATIC_INDEX.is_file():
            return FileResponse(_STATIC_INDEX)
        return HTMLResponse(_PLACEHOLDER, status_code=503)

    return app


def _effective_frontend_mode(settings: WebSettings) -> str:
    """Serve the SPA only when a build is actually installed.

    A missing build degrades to the inline legacy page rather than to an error
    page, so an incomplete deployment still shows a working report. `main()`
    refuses to start in that state, which keeps the fallback from being silent
    in production.
    """

    if settings.frontend_mode == "spa" and spa_build_present():
        return "spa"
    return "legacy"


def _resolved_asset(asset_path: str) -> Path | None:
    """Resolve a request path inside the built asset directory, or refuse.

    Every segment must be a plain file name, the resolved target must stay
    under the asset directory, and symlinks are rejected so a link planted in
    the build output cannot read arbitrary files.
    """

    if asset_path == "" or asset_path.endswith("/"):
        return None
    segments = asset_path.split("/")
    if any(_ASSET_NAME.fullmatch(segment) is None for segment in segments):
        return None
    if any(segment in {".", ".."} for segment in segments):
        return None

    directory = _SPA_ROOT / _SPA_ASSET_DIRECTORY
    try:
        base = directory.resolve(strict=True)
        candidate = directory.joinpath(*segments)
        if candidate.is_symlink():
            return None
        target = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None

    if base != target and base not in target.parents:
        return None
    if not target.is_file():
        return None
    return target


_SPA_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "style-src 'self'",
        "style-src-elem 'self'",
        "style-src-attr 'none'",
        "script-src 'self'",
        "script-src-attr 'none'",
        "worker-src 'none'",
        "manifest-src 'none'",
        "media-src 'none'",
    )
)


def _document_security_headers(frontend_mode: str = "legacy") -> dict[str, str]:
    """Policy for the document response.

    The SPA ships no inline script or style at all, so it gets a plain
    `'self'` policy with inline attributes explicitly forbidden. The legacy
    page is one inline block each, so it keeps the hash allowance computed
    from its own bytes; neither mode ever permits `unsafe-inline`.
    """

    if frontend_mode == "spa":
        return {
            "Cache-Control": "no-store",
            "Content-Security-Policy": _SPA_POLICY,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }

    script_sources = "'none'"
    style_sources = "'none'"
    try:
        page = _STATIC_INDEX.read_text(encoding="utf-8")
    except OSError:
        page = ""
    script = _INLINE_SCRIPT.search(page)
    style = _INLINE_STYLE.search(page)
    if script is not None:
        script_sources = _sha256_source(script.group(1))
    if style is not None:
        style_sources = _sha256_source(style.group(1))
    policy = "; ".join(
        (
            "default-src 'self'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "connect-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            f"style-src {style_sources}",
            f"script-src {script_sources}",
            "worker-src 'none'",
            "manifest-src 'none'",
            "media-src 'none'",
        )
    )
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": policy,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _sha256_source(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    encoded = base64.b64encode(digest).decode("ascii")
    return f"'sha256-{encoded}'"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weekly-cs-dashboard")
    parser.add_argument(
        "--local",
        action="store_true",
        help="run without proxy authentication on a loopback address",
    )
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host or ("127.0.0.1" if args.local else "0.0.0.0")
    if args.local:
        if not _is_loopback(host):
            print("local mode requires a loopback host", file=sys.stderr)
            return 2
        auth_mode = "off"
    else:
        auth_mode = os.environ.get("DASHBOARD_AUTH_MODE", "")
        if auth_mode not in ("proxy", "basic"):
            print(
                "production requires DASHBOARD_AUTH_MODE=proxy or basic",
                file=sys.stderr,
            )
            return 2
    if not 1 <= args.port <= 65535:
        print("port must be between 1 and 65535", file=sys.stderr)
        return 2

    identity_header = (
        os.environ.get("DASHBOARD_IDENTITY_HEADER") or "X-Forwarded-User"
    )
    frontend_mode = os.environ.get("DASHBOARD_FRONTEND_MODE") or "spa"
    if frontend_mode not in _FRONTEND_MODES:
        print("DASHBOARD_FRONTEND_MODE must be spa or legacy", file=sys.stderr)
        return 2
    if frontend_mode == "spa" and not spa_build_present():
        # Falling back silently would ship the previous interface under the
        # new release, so refuse to start instead.
        print(
            "SPA build is missing; run the frontend build or set "
            "DASHBOARD_FRONTEND_MODE=legacy",
            file=sys.stderr,
        )
        return 2
    runtime_directory_value = Path(
        os.environ.get("DASHBOARD_RUNTIME_DIR") or PROJECT_ROOT / "runtime"
    )

    try:
        refresh_timeout_seconds = _refresh_timeout_seconds()
        max_trace_pages = _max_trace_pages()
        web_settings = WebSettings(auth_mode, identity_header, frontend_mode)
        runtime_directory = _validated_runtime_directory(runtime_directory_value)
        environment = load_environment()
        configure_json_logging()
        client = LangfuseClient(
            environment.base_url,
            environment.public_key,
            environment.secret_key,
        )
    except (ConfigurationError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    manager: SnapshotManager | None = None
    app: FastAPI | None = None
    refresh_cancel_event = threading.Event()
    try:
        vietnam = ZoneInfo("Asia/Ho_Chi_Minh")

        def load_snapshot():
            as_of = datetime.now(vietnam)
            report = compute_report(
                client,
                as_of=as_of,
                weeks=12,
                include_current_wtd=True,
                taxonomy_path=PROJECT_ROOT / "config" / "taxonomy.v2.json",
                refresh_timeout_seconds=refresh_timeout_seconds,
                max_trace_pages=max_trace_pages,
                cancel_event=refresh_cancel_event,
            )
            if report.enrichment_status != "complete":
                emit_event(
                    "enrichment_incomplete",
                    failed_lanes=(
                        ",".join(report.failed_enrichment_lanes) or "unknown"
                    ),
                    observation_count=report.observations_fetched,
                )
                raise InvariantError("enrichment is incomplete")
            try:
                csat_cache = load_csat_cache(
                    runtime_directory / _CSAT_CACHE_FILENAME
                )
            except CSATCacheError:
                emit_event("csat_cache_load_ignored", code="invalid_cache")
                csat_cache = None
            try:
                reconciliation_cache = load_reconciliation_cache(
                    runtime_directory / _RECONCILIATION_CACHE_FILENAME
                )
            except ReconciliationCacheError:
                emit_event(
                    "outcome_reconciliation_cache_load_ignored",
                    code="invalid_cache",
                )
                reconciliation_cache = None
            try:
                entry_coverage_cache = load_entry_coverage_cache(
                    runtime_directory / _ENTRY_COVERAGE_CACHE_FILENAME
                )
            except EntryCoverageCacheError:
                emit_event(
                    "entry_coverage_cache_load_ignored",
                    code="invalid_cache",
                )
                entry_coverage_cache = None
            return project_dashboard(
                report,
                csat_cache=csat_cache,
                reconciliation_cache=reconciliation_cache,
                entry_coverage_cache=entry_coverage_cache,
            )

        manager = SnapshotManager(
            load_snapshot,
            ProtectedSnapshotStore(
                runtime_directory,
                require_complete_enrichment=True,
            ),
            cancel_event=refresh_cancel_event,
        )
        app = create_app(
            manager, settings=web_settings, runtime_directory=runtime_directory
        )
        app.state.langfuse_client = client

        def load_ab_test_default() -> dict[str, object]:
            now = datetime.now(timezone.utc)
            deadline = time.monotonic() + _AB_TEST_DEADLINE_SECONDS
            arms: tuple[str, ...] | None = None
            window_start, window_end = default_window(now)
            try:
                recent_models = list_recent_models(client, now=now, deadline=deadline)
            except LangfuseAPIError:
                recent_models = []
            if len(recent_models) >= 2:
                # Most-active-first: the two arms actually being compared
                # right now, not an alphabetical or hardcoded pair.
                arms = tuple(recent_models[:2])
                first_seen_candidates = []
                for model in arms:
                    entry = _get_or_discover_first_seen(
                        client, runtime_directory, model, now=now, deadline=deadline
                    )
                    if entry.first_seen is not None:
                        first_seen_candidates.append(
                            datetime.fromisoformat(
                                entry.first_seen.replace("Z", "+00:00")
                            )
                        )
                if first_seen_candidates:
                    # The window a true A/B comparison starts once BOTH arms
                    # have traffic -- the later of the two first-seen times.
                    window_start = max(first_seen_candidates)
                    window_end = now
            snapshot = compute_ab_test(
                client,
                window_start,
                window_end,
                _trace_explain_taxonomy(),
                csat_by_ticket=_csat_buckets_by_ticket(runtime_directory),
                deadline=deadline,
                arms=arms,
            )
            return _ab_test_payload(snapshot)

        ab_test_background = _AbTestBackgroundCache(
            load_ab_test_default,
            cache_path=runtime_directory / _AB_TEST_CACHE_FILENAME,
        )
        ab_test_background.start()
        app.state.ab_test_background = ab_test_background

        def load_recent_models() -> list[str]:
            return list_recent_models(
                client,
                now=datetime.now(timezone.utc),
                deadline=time.monotonic() + _AB_TEST_DEADLINE_SECONDS,
            )

        model_list_background = _ModelListBackgroundCache(
            load_recent_models,
            cache_path=runtime_directory / _MODEL_LIST_CACHE_FILENAME,
        )
        model_list_background.start()
        app.state.model_list_background = model_list_background
        uvicorn.run(
            app,
            host=host,
            port=args.port,
            workers=1,
            access_log=False,
            timeout_graceful_shutdown=45,
        )
    finally:
        resources_closed = (
            app is not None and getattr(app.state, "resources_closed", False)
        )
        if not resources_closed:
            try:
                if manager is not None:
                    manager.close()
                if app is not None:
                    background = getattr(app.state, "ab_test_background", None)
                    if background is not None:
                        background.close()
                    model_list_background = getattr(
                        app.state, "model_list_background", None
                    )
                    if model_list_background is not None:
                        model_list_background.close()
            finally:
                client.close()
    return 0


def _has_identity(request: Request, header_name: str) -> bool:
    values = request.headers.getlist(header_name)
    if len(values) != 1:
        return False
    value = values[0]
    return (
        1 <= len(value) <= 256
        and value.strip() == value
        and "," not in value
        and not any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    )


def _refresh_timeout_seconds() -> float:
    value = os.environ.get(_REFRESH_DEADLINE_ENV, "120")
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise ValueError(_REFRESH_DEADLINE_ERROR) from None
    if not 30.0 <= timeout <= 300.0:
        raise ValueError(_REFRESH_DEADLINE_ERROR)
    return timeout


def _max_trace_pages() -> int:
    value = os.environ.get(_TRACE_PAGE_LIMIT_ENV, "500")
    try:
        max_pages = int(value)
    except (TypeError, ValueError):
        raise ValueError(_TRACE_PAGE_LIMIT_ERROR) from None
    if not 1 <= max_pages <= 500:
        raise ValueError(_TRACE_PAGE_LIMIT_ERROR)
    return max_pages


def _state_envelope(view: CacheView) -> dict[str, object]:
    return {
        "status": view.status,
        "refreshing": view.refreshing,
        "last_error_code": view.last_error_code,
        "last_error_at": (
            _utc_iso(view.last_error_at) if view.last_error_at is not None else None
        ),
        "snapshot": (
            view.snapshot.dashboard_dict() if view.snapshot is not None else None
        ),
    }


def _freshdesk_cookie_state_payload(
    runtime_directory: Path | None,
) -> dict[str, object]:
    if runtime_directory is None:
        return {"state": "missing", "updated_at": None, "last_verified_at": None}
    from .freshdesk_csat import FreshdeskCSATError, read_cookie_state

    try:
        state = read_cookie_state(runtime_directory)
    except FreshdeskCSATError:
        state = {"state": "missing", "updated_at": None, "last_verified_at": None}
    return {
        "state": state["state"],
        "updated_at": state["updated_at"],
        "last_verified_at": state["last_verified_at"],
    }


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ab_test_query(
    request: Request,
) -> tuple[datetime, datetime, tuple[str, ...] | None] | None:
    items = list(request.query_params.multi_items())
    if len(items) > 3 or any(
        name not in {"start", "end", "arms"} for name, _value in items
    ):
        return None
    if sum(1 for name, _value in items if name == "arms") > 1:
        return None
    for name, value in items:
        max_length = _AB_TEST_ARMS_VALUE_LENGTH if name == "arms" else _MAX_QUERY_VALUE_LENGTH
        if len(value) > max_length:
            return None
    values = dict(items)
    if "start" not in values or not values["start"]:
        return None
    start_raw = values["start"]
    end_raw = values.get("end") or ""

    normalized_start = (
        start_raw[:-1] + "+00:00" if start_raw.endswith("Z") else start_raw
    )
    try:
        window_start = datetime.fromisoformat(normalized_start)
    except ValueError:
        return None
    if window_start.tzinfo is None:
        return None
    window_start = window_start.astimezone(timezone.utc)

    if end_raw:
        normalized_end = end_raw[:-1] + "+00:00" if end_raw.endswith("Z") else end_raw
        try:
            window_end = datetime.fromisoformat(normalized_end)
        except ValueError:
            return None
        if window_end.tzinfo is None:
            return None
        window_end = window_end.astimezone(timezone.utc)
    else:
        window_end = datetime.now(timezone.utc)

    if window_end <= window_start:
        return None
    if window_end - window_start > timedelta(days=_AB_TEST_MAX_WINDOW_DAYS):
        return None

    arms: tuple[str, ...] | None = None
    raw_arms = values.get("arms") or ""
    if raw_arms:
        candidates = [item.strip() for item in raw_arms.split(",")]
        if not candidates or any(not item or len(item) > 200 for item in candidates):
            return None
        if len(candidates) > _AB_TEST_MAX_ARMS:
            return None
        if len(set(candidates)) != len(candidates):
            return None
        arms = tuple(candidates)

    return window_start, window_end, arms


def _get_or_discover_first_seen(
    client: LangfuseClient,
    runtime_directory: Path | None,
    model: str,
    *,
    now: datetime,
    deadline: float | None,
) -> CachedModelSeen:
    """Cached first-seen lookup for one model, discovering on a cold/failed miss.

    A previously confirmed (or found) entry is trusted forever -- a model's
    first appearance never changes. Only a total prior failure (no candidate
    and not confirmed) is retried.
    """

    cache_path = (
        runtime_directory / _MODEL_SEEN_CACHE_FILENAME
        if runtime_directory is not None
        else None
    )
    seen_cache: ModelSeenCache | None = None
    if cache_path is not None:
        try:
            seen_cache = load_model_seen_cache(cache_path)
        except ModelSeenCacheError:
            emit_event("model_seen_cache_load_ignored", code="invalid_cache")
            seen_cache = None
    if seen_cache is None:
        seen_cache = ModelSeenCache(entries={})

    entry = seen_cache.get(model)
    if entry is not None and (entry.first_seen is not None or entry.confirmed):
        return entry

    try:
        first_seen, confirmed = discover_first_seen(
            client, model, now=now, deadline=deadline
        )
    except Exception:
        first_seen, confirmed = None, False
    entry = CachedModelSeen(
        model=model,
        first_seen=_utc_iso(first_seen) if first_seen is not None else None,
        confirmed=confirmed,
        checked_at=_utc_iso(now),
    )
    if cache_path is not None:
        try:
            write_model_seen_cache(cache_path, seen_cache.with_entry(entry))
        except ModelSeenCacheError:
            emit_event("model_seen_cache_write_ignored", code="write_failed")
    return entry


def _csat_buckets_by_ticket(
    runtime_directory: Path | None,
) -> dict[str, str] | None:
    """Latest satisfaction bucket per ticket, or None when no cache exists.

    Only the bucket travels: no comment text, survey id, or response key.
    """
    if runtime_directory is None:
        return None
    try:
        cache = load_csat_cache(runtime_directory / _CSAT_CACHE_FILENAME)
    except CSATCacheError:
        return None
    if cache is None:
        return None
    latest: dict[str, tuple[str, str]] = {}
    for response in cache.responses:
        responded_at = response.responded_at or ""
        previous = latest.get(response.ticket_id)
        if previous is None or responded_at >= previous[0]:
            latest[response.ticket_id] = (responded_at, response.satisfaction_bucket)
    return {
        ticket_id: bucket for ticket_id, (_at, bucket) in latest.items()
    }


def _ab_test_payload(snapshot: AbTestSnapshot) -> dict[str, object]:
    return {
        "window_start": _utc_iso(snapshot.window_start),
        "window_end": _utc_iso(snapshot.window_end),
        "total_tickets": snapshot.total_tickets,
        "unmatched_tickets": snapshot.unmatched_tickets,
        "csat_available": snapshot.csat_available,
        "arms": [
            {
                "arm": arm.arm,
                "ticket_count": arm.ticket_count,
                "share": arm.share,
                "low_sample": arm.low_sample,
                "ai_end_to_end": arm.ai_end_to_end,
                "ai_then_cs": arm.ai_then_cs,
                "direct_cs": arm.direct_cs,
                "unclassified": arm.unclassified,
                "ai_first_count": arm.ai_first_count,
                "transferred_count": arm.transferred_count,
                "reopen_count": arm.reopen_count,
                "reopen_denominator": arm.reopen_denominator,
                "turn_total": arm.turn_total,
                "latency_p50": arm.latency_p50,
                "latency_p95": arm.latency_p95,
                "llm_call_count": arm.llm_call_count,
                "input_tokens": arm.input_tokens,
                "output_tokens": arm.output_tokens,
                "total_tokens": arm.total_tokens,
                "llm_latency_p50": arm.llm_latency_p50,
                "llm_latency_p95": arm.llm_latency_p95,
                "csat_response_count": arm.csat_response_count,
                "csat_positive_count": arm.csat_positive_count,
                "csat_negative_count": arm.csat_negative_count,
            }
            for arm in snapshot.arms
        ],
        "daily": [
            {
                "date": item.date,
                "arm": item.arm,
                "ticket_count": item.ticket_count,
                "ai_end_to_end": item.ai_end_to_end,
                "ai_first_count": item.ai_first_count,
                "transferred_count": item.transferred_count,
                "direct_cs": item.direct_cs,
                "reopen_count": item.reopen_count,
                "reopen_denominator": item.reopen_denominator,
                "turn_total": item.turn_total,
                "latency_p50": item.latency_p50,
                "latency_p95": item.latency_p95,
                "total_tokens": item.total_tokens,
                "output_tokens": item.output_tokens,
            }
            for item in snapshot.daily
        ],
        "dimensions": {
            dimension: [
                {
                    "value": item.value,
                    "arm": item.arm,
                    "ticket_count": item.ticket_count,
                    "ai_end_to_end": item.ai_end_to_end,
                }
                for item in rows
            ]
            for dimension, rows in snapshot.dimensions.items()
        },
    }


def _parse_ticket_query(
    request: Request,
) -> tuple[dict[str, object], str | None]:
    raw_query = request.scope.get("query_string", b"")
    if (
        not isinstance(raw_query, bytes)
        or len(raw_query) > _MAX_RAW_QUERY_BYTES
        or (raw_query.count(b"&") + 1 if raw_query else 0) > _MAX_QUERY_PAIRS
    ):
        return {}, "unknown"
    items = list(request.query_params.multi_items())
    if len(items) > _MAX_QUERY_PAIRS:
        return {}, "unknown"
    if any(name not in _QUERY_NAME_SET for name, _value in items):
        return {}, "unknown"
    for name, value in items:
        # Multi-select dimension filters carry comma-separated values, same
        # convention as cohort_weeks, so they need the same longer allowance.
        max_length = 1024 if name in _MULTI_SELECT_QUERY_NAMES else _MAX_QUERY_VALUE_LENGTH
        if len(value) > max_length:
            return {}, name
    for name in _QUERY_NAMES:
        if sum(item_name == name for item_name, _value in items) > 1:
            return {}, name

    values = dict(items)
    if "sort_direction" in values and "sort_by" not in values:
        return {}, "sort_direction"
    parsed: dict[str, object] = {}
    for name in _QUERY_NAMES:
        if name not in values:
            continue
        value = values[name]
        if name in {"page", "page_size"}:
            if not _INTEGER_QUERY.fullmatch(value):
                return {}, name
            parsed[name] = int(value)
        elif name in {"gt4_turn", "transferred", "is_weekend_start"}:
            if value not in {"true", "false"}:
                return {}, name
            parsed[name] = value == "true"
        elif name == "aggregate":
            if value != "1":
                return {}, name
            parsed[name] = True
        elif name == "sort_direction":
            if value not in {"asc", "desc"}:
                return {}, name
            parsed[name] = value
        else:
            parsed[name] = value
    return parsed, None


def _parse_entry_coverage_query(
    request: Request,
) -> tuple[dict[str, object], str | None]:
    raw_query = request.scope.get("query_string", b"")
    if (
        not isinstance(raw_query, bytes)
        or len(raw_query) > _MAX_RAW_QUERY_BYTES
        or (raw_query.count(b"&") + 1 if raw_query else 0) > len(_ENTRY_QUERY_NAMES)
    ):
        return {}, "unknown"
    items = list(request.query_params.multi_items())
    if len(items) > len(_ENTRY_QUERY_NAMES):
        return {}, "unknown"
    if any(name not in _ENTRY_QUERY_NAME_SET for name, _value in items):
        return {}, "unknown"
    if any(
        sum(item_name == name for item_name, _value in items) > 1
        for name in _ENTRY_QUERY_NAMES
    ):
        return {}, "unknown"
    values = dict(items)
    parsed: dict[str, object] = {}
    for name, value in values.items():
        if len(value) > (1024 if name == "cohort_weeks" else _MAX_QUERY_VALUE_LENGTH):
            return {}, name
        if name in {"page", "page_size"}:
            if not _INTEGER_QUERY.fullmatch(value):
                return {}, name
            parsed[name] = int(value)
        elif name == "sort_dir":
            if value not in {"asc", "desc"}:
                return {}, name
            parsed[name] = value
        else:
            parsed[name] = value
    return parsed, None


def _parameter_for_validation_error(error: ValueError) -> str:
    message = str(error)
    for name in _QUERY_NAMES:
        if message.startswith(f"{name} "):
            return name
    return "unknown"


def _entry_parameter_for_validation_error(error: ValueError) -> str:
    message = str(error)
    for name in _ENTRY_QUERY_NAMES:
        if message.startswith(f"{name} "):
            return name
    if message.startswith("status "):
        return "status"
    return "unknown"


def _invalid_query(parameter: str) -> JSONResponse:
    return JSONResponse(
        {"detail": {"code": "invalid_query", "parameter": parameter}},
        status_code=422,
    )


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_runtime_directory(value: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
    directory = Path(os.path.abspath(os.fspath(candidate)))
    static_directory = Path(os.path.abspath(os.fspath(_STATIC_INDEX.parent)))
    prohibited = {
        Path(directory.anchor),
        Path(os.path.abspath(os.fspath(Path.home()))),
        Path(os.path.abspath(os.fspath(PROJECT_ROOT))),
        Path(os.path.abspath(os.fspath(PROJECT_ROOT.parent))),
    }
    if (
        directory in prohibited
        or directory == static_directory
        or static_directory in directory.parents
    ):
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)

    effective_uid = os.geteuid()
    components = tuple(reversed(directory.parents)) + (directory,)
    directory_exists = True
    try:
        for component in components:
            try:
                component_status = component.lstat()
            except FileNotFoundError:
                if component != directory:
                    raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
                directory_exists = False
                break
            if stat.S_ISLNK(component_status.st_mode):
                raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
            if component == directory:
                continue
            if (
                not stat.S_ISDIR(component_status.st_mode)
                or component_status.st_uid not in {0, effective_uid}
                or stat.S_IMODE(component_status.st_mode) & 0o022
            ):
                raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)

        if not directory_exists:
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
        directory_status = directory.lstat()
    except OSError:
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR) from None

    if (
        stat.S_ISLNK(directory_status.st_mode)
        or not stat.S_ISDIR(directory_status.st_mode)
        or directory_status.st_uid != effective_uid
    ):
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
    if stat.S_IMODE(directory_status.st_mode) != 0o700:
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
    try:
        entries = tuple(directory.iterdir())
    except OSError:
        raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR) from None
    for entry in entries:
        try:
            entry_status = entry.lstat()
        except OSError:
            raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR) from None
        allowed_name = (
            entry.name == _SNAPSHOT_FILENAME
            or entry.name == _CSAT_CACHE_FILENAME
            or entry.name == _RECONCILIATION_CACHE_FILENAME
            or entry.name == _ENTRY_COVERAGE_CACHE_FILENAME
            or entry.name == _MODEL_SEEN_CACHE_FILENAME
            or entry.name == _AB_TEST_CACHE_FILENAME
            or entry.name == _MODEL_LIST_CACHE_FILENAME
            or entry.name == _FRESHDESK_COOKIE_FILENAME
            or entry.name == _FRESHDESK_COOKIE_STATE_FILENAME
            or _TEMP_SNAPSHOT_NAME.fullmatch(entry.name) is not None
        )
        if (
            not allowed_name
            or not stat.S_ISREG(entry_status.st_mode)
            or entry_status.st_uid != effective_uid
            or stat.S_IMODE(entry_status.st_mode) != 0o600
        ):
            raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
    return directory


if __name__ == "__main__":
    raise SystemExit(main())
