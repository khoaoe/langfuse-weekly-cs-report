from __future__ import annotations

import argparse
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat
import sys
import threading
from typing import Sequence
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import uvicorn

from .cli import ConfigurationError, PROJECT_ROOT, load_environment
from .csat_cache import CSATCacheError, load_csat_cache
from .dashboard_cache import CacheView, ProtectedSnapshotStore, SnapshotManager
from .dashboard_schema import (
    entry_coverage_ticket_page,
    project_dashboard,
    ticket_page,
)
from .entry_coverage_cache import (
    EntryCoverageCacheError,
    load_entry_coverage_cache,
)
from .langfuse_client import LangfuseClient
from .reconciliation_cache import (
    ReconciliationCacheError,
    load_reconciliation_cache,
)
from .report import compute_report
from .runtime_logging import configure_json_logging, emit_event


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
    "outcome",
    "ticket_id",
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
    "tpe_code",
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
_ENTRY_QUERY_NAMES = (
    "week_definition",
    "cohort_weeks",
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
_TEMP_SNAPSHOT_NAME = re.compile(r"\.dashboard_snapshot\..+\.tmp\Z")
_RUNTIME_DIRECTORY_ERROR = "dashboard runtime directory is unsafe"
_REFRESH_ACTION_HEADER = "X-Dashboard-Action"
_REFRESH_ACTION_VALUE = "refresh"
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


def create_app(manager: SnapshotManager, *, settings: WebSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        emit_event("service_start")
        try:
            yield
        finally:
            try:
                manager.close()
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
        try:
            payload = ticket_page(view.snapshot, **parsed)
        except ValueError as error:
            return _invalid_query(_parameter_for_validation_error(error))
        return JSONResponse(payload)

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
        app = create_app(manager, settings=web_settings)
        app.state.langfuse_client = client
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


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
        max_length = 1024 if name == "cohort_weeks" else _MAX_QUERY_VALUE_LENGTH
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
