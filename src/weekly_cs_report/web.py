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
from typing import Sequence
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import uvicorn

from .cli import ConfigurationError, PROJECT_ROOT, load_environment
from .dashboard_cache import CacheView, ProtectedSnapshotStore, SnapshotManager
from .dashboard_schema import project_dashboard, ticket_page
from .langfuse_client import LangfuseClient
from .report import compute_report


_AUTH_MODES = frozenset({"off", "proxy"})
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
    "outcome",
    "ticket_id",
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
    "tpe_code",
    "gt4_turn",
    "transferred",
    "is_weekend_start",
    "week_definition",
    "page",
    "page_size",
)
_QUERY_NAME_SET = frozenset(_QUERY_NAMES)
_MAX_QUERY_PAIRS = len(_QUERY_NAMES)
_MAX_QUERY_VALUE_LENGTH = 128
_MAX_RAW_QUERY_BYTES = 8192
_INTEGER_QUERY = re.compile(r"[0-9]{1,9}\Z")
_STATIC_INDEX = Path(__file__).with_name("static") / "index.html"
_SNAPSHOT_FILENAME = "dashboard_snapshot.json"
_DIMENSION_BACKFILL_FILENAME = "dimension_backfill.json"
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


@dataclass(frozen=True)
class WebSettings:
    auth_mode: str
    identity_header: str

    def __post_init__(self) -> None:
        if self.auth_mode not in _AUTH_MODES:
            raise ValueError("auth_mode must be off or proxy")
        if not isinstance(self.identity_header, str) or not _HEADER_NAME.fullmatch(
            self.identity_header
        ):
            raise ValueError("identity_header must be a non-empty HTTP header name")
        if self.identity_header.casefold() not in _ALLOWED_IDENTITY_HEADERS:
            raise ValueError("identity_header is not approved for proxy authentication")


def create_app(manager: SnapshotManager, *, settings: WebSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            manager.close()
            client = getattr(app.state, "langfuse_client", None)
            if client is not None:
                client.close()
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
        protected = request.url.path == "/" or is_api
        try:
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
        elif request.url.path == "/":
            for name, value in _document_security_headers().items():
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

    @app.get("/")
    async def root():
        if _STATIC_INDEX.is_file():
            return FileResponse(_STATIC_INDEX)
        return HTMLResponse(_PLACEHOLDER, status_code=503)

    return app


def _document_security_headers() -> dict[str, str]:
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
        if auth_mode != "proxy":
            print(
                "production requires DASHBOARD_AUTH_MODE=proxy",
                file=sys.stderr,
            )
            return 2
    if not 1 <= args.port <= 65535:
        print("port must be between 1 and 65535", file=sys.stderr)
        return 2

    identity_header = (
        os.environ.get("DASHBOARD_IDENTITY_HEADER") or "X-Forwarded-User"
    )
    runtime_directory_value = Path(
        os.environ.get("DASHBOARD_RUNTIME_DIR") or PROJECT_ROOT / "runtime"
    )

    try:
        web_settings = WebSettings(auth_mode, identity_header)
        runtime_directory = _validated_runtime_directory(runtime_directory_value)
        environment = load_environment()
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
            )
            return project_dashboard(report)

        manager = SnapshotManager(
            load_snapshot,
            ProtectedSnapshotStore(runtime_directory),
        )
        app = create_app(manager, settings=web_settings)
        app.state.langfuse_client = client
        uvicorn.run(
            app,
            host=host,
            port=args.port,
            workers=1,
            access_log=False,
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
    value = request.headers.get(header_name)
    return value is not None and bool(value.strip())


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
        if len(value) > _MAX_QUERY_VALUE_LENGTH:
            return {}, name
    for name in _QUERY_NAMES:
        if sum(item_name == name for item_name, _value in items) > 1:
            return {}, name

    values = dict(items)
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
        else:
            parsed[name] = value
    return parsed, None


def _parameter_for_validation_error(error: ValueError) -> str:
    message = str(error)
    for name in _QUERY_NAMES:
        if message.startswith(f"{name} "):
            return name
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
            or entry.name == _DIMENSION_BACKFILL_FILENAME
            or _TEMP_SNAPSHOT_NAME.fullmatch(entry.name) is not None
        )
        if (
            not allowed_name
            or not stat.S_ISREG(entry_status.st_mode)
            or stat.S_IMODE(entry_status.st_mode) != 0o600
        ):
            raise ConfigurationError(_RUNTIME_DIRECTORY_ERROR)
    return directory


if __name__ == "__main__":
    raise SystemExit(main())
