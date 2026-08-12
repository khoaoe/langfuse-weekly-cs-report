"""Run the dashboard against a fixed in-memory snapshot for browser tests.

This is the real FastAPI application, so end-to-end runs exercise the actual
security headers, asset route and SPA document. Only the Langfuse read is
replaced: no credential is needed and no network call is made.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from weekly_cs_report.dashboard_cache import ProtectedSnapshotStore, SnapshotManager
from weekly_cs_report.dashboard_schema import project_dashboard
from weekly_cs_report.report import compute_report
from weekly_cs_report.web import WebSettings, create_app

from tests.fixtures.traces import TRANSFER_HTML, trace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
FIRST_MONDAY = datetime(2026, 6, 15, tzinfo=VIETNAM)
WEEKS = 7


def _stamp(monday: datetime, day: int, hour: int) -> str:
    moment = monday + timedelta(days=day, hours=hour)
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyntheticClient:
    """Replays a deterministic, privacy-free trace set through the real pipeline.

    Building the snapshot from `compute_report` rather than from a hand-written
    dictionary means the browser sees a payload that satisfies every
    reconciliation rule the production projection enforces.
    """

    def __init__(self) -> None:
        self.traces: list[dict] = []
        ticket = 500_000
        for week in range(WEEKS):
            monday = FIRST_MONDAY + timedelta(weeks=week)
            volume = 6 + week

            for index in range(volume):
                ticket += 1
                self.traces.append(
                    trace(
                        f"ai-{ticket}",
                        str(ticket),
                        0,
                        _stamp(monday, index % 5, 9),
                        "Phản hồi tổng hợp, không chứa dữ liệu khách hàng.",
                    )
                )

            for index in range(2):
                ticket += 1
                self.traces.append(
                    trace(
                        f"then-cs-{ticket}",
                        str(ticket),
                        0,
                        _stamp(monday, index, 10),
                        "Phản hồi tổng hợp trước khi chuyển CS.",
                    )
                )
                self.traces.append(
                    trace(
                        f"then-cs-{ticket}-b",
                        str(ticket),
                        1,
                        _stamp(monday, index, 11),
                        TRANSFER_HTML,
                    )
                )

            ticket += 1
            self.traces.append(
                trace(
                    f"direct-{ticket}",
                    str(ticket),
                    0,
                    _stamp(monday, 2, 9),
                    TRANSFER_HTML,
                    title="Topup tổng hợp",
                )
            )

            ticket += 1
            for turn in range(6):
                self.traces.append(
                    trace(
                        f"long-{ticket}-{turn}",
                        str(ticket),
                        turn,
                        _stamp(monday, 3, 9 + turn),
                        "Phản hồi tổng hợp lần tiếp theo.",
                    )
                )

            ticket += 1
            self.traces.append(
                trace(
                    f"weekend-{ticket}",
                    str(ticket),
                    0,
                    _stamp(monday, 5, 9),
                    "Phản hồi tổng hợp mở vào cuối tuần.",
                )
            )

    def iter_traces(
        self,
        from_timestamp: datetime,
        to_timestamp: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
        max_pages: int | None = None,
    ):
        del from_timestamp, to_timestamp, deadline, cancel_event, max_pages
        yield from self.traces

    def list_observations(self, trace_id: str) -> list[dict]:
        del trace_id
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
        del name, deadline, cancel_event
        return iter(())


def build_snapshot():
    run = compute_report(
        SyntheticClient(),
        as_of=AS_OF,
        weeks=12,
        include_current_wtd=True,
        taxonomy_path=PROJECT_ROOT / "config" / "taxonomy.v2.json",
    )
    return project_dashboard(run)


def main() -> int:
    host = os.environ.get("E2E_HOST", "127.0.0.1")
    port = int(os.environ.get("E2E_PORT", "18765"))
    mode = os.environ.get("DASHBOARD_FRONTEND_MODE", "spa")

    runtime = Path(tempfile.mkdtemp(prefix="zalopay-e2e-"))
    runtime.chmod(0o700)

    snapshot = build_snapshot()
    store = ProtectedSnapshotStore(runtime)
    store.save(snapshot)
    manager = SnapshotManager(lambda: snapshot, store)

    app = create_app(manager, settings=WebSettings("off", "X-Forwarded-User", mode))
    uvicorn.run(
        app, host=host, port=port, workers=1, access_log=False, log_level="warning"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
