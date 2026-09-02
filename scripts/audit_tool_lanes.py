#!/usr/bin/env python3
"""Fail when Langfuse runs a tool the enrichment lanes do not cover.

`TOOL_ENRICHMENT_NAMES` is a static allowlist of exact observation names, so a
tool that is added, renamed, or given a new `__<skill>` variant simply stops
being fetched -- the tool-error column keeps rendering, silently blind to it.
That is how three tools were missed on the first pass, one of them failing 96%
of its calls.

This script closes the loop from the other side: it asks Langfuse which
`tool:*` observation names actually ran, and compares that against the lanes.
Run it after any `cs-agent` release that touches tools.

    .venv/bin/python scripts/audit_tool_lanes.py [--days 7]

Exit codes:
    0  every tool that ran is covered, or knowingly skipped
    1  at least one uncovered tool ran, or a declared lane is dead
    2  could not reach Langfuse

Reads LANGFUSE_BASE_URL / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY from `.env`
and never prints their values.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from weekly_cs_report.enrichment import TOOL_ENRICHMENT_NAMES  # noqa: E402

# Tools that run but are deliberately not fetched, with the reason. Anything
# here is reported as "skipped", not as a gap -- but it still has to be listed
# explicitly, so dropping a lane is always a visible decision.
KNOWINGLY_SKIPPED = {
    "load_skill_reference": "reads skill files from disk; 0 errors in 3,394 calls",
    "list_skill_references": "reads skill files from disk; 0 errors in 382 calls",
    "calculate_time_difference": "pure arithmetic; 0 errors in 30 calls",
}


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def _observation_names(env: dict[str, str], days: int) -> dict[str, int]:
    """Every distinct observation name in the window, with its call count.

    Langfuse's `/api/public/observations` filters by exact name only, so it
    cannot answer "which names exist". The metrics API can, grouped by name,
    in a single request -- which is what makes this audit cheap enough to run
    routinely instead of paging millions of observations.
    """
    to_time = datetime.now(timezone.utc).replace(microsecond=0)
    query = {
        "view": "observations",
        "metrics": [{"measure": "count", "aggregation": "count"}],
        "dimensions": [{"field": "name"}],
        "fromTimestamp": (to_time - timedelta(days=days)).isoformat().replace(
            "+00:00", "Z"
        ),
        "toTimestamp": to_time.isoformat().replace("+00:00", "Z"),
    }
    credentials = f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}"
    header = "Authorization: Basic " + base64.b64encode(
        credentials.encode()
    ).decode()
    url = (
        env["LANGFUSE_BASE_URL"].rstrip("/")
        + "/api/public/metrics?query="
        + urllib.parse.quote(json.dumps(query))
    )
    # The sandbox proxy drops connections under load; retry rather than
    # reporting a coverage gap that is really a network blip.
    for attempt in range(5):
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60", "-H", header, url],
            capture_output=True,
            text=True,
        )
        try:
            rows = json.loads(result.stdout)["data"]
        except (json.JSONDecodeError, KeyError, TypeError):
            time.sleep(1.5 * (attempt + 1))
            continue
        return {row["name"]: int(row["count_count"]) for row in rows}
    print("KHONG DOC DUOC Langfuse metrics API", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    counts = _observation_names(_env(), args.days)
    lanes = set(TOOL_ENRICHMENT_NAMES)
    # A `tool:x__skill` observation is tool `x` invoked from skill `skill`, so
    # the suffix is a parameter, not a different tool -- collapse it the same
    # way `explain_context._base_tool_name` does.
    ran: dict[str, int] = {}
    for name, count in counts.items():
        if not name.startswith("tool:"):
            continue
        ran[name.removeprefix("tool:").split("__")[0]] = (
            ran.get(name.removeprefix("tool:").split("__")[0], 0) + count
        )
    covered = {name.removeprefix("tool:") for name in lanes}

    uncovered = {
        tool: count
        for tool, count in ran.items()
        if tool not in covered and tool not in KNOWINGLY_SKIPPED
    }
    dead = sorted(covered - set(ran))
    skipped = {
        tool: count for tool, count in ran.items() if tool in KNOWINGLY_SKIPPED
    }

    print(f"Cua so: {args.days} ngay | tool da chay: {len(ran)} | lane: {len(lanes)}")
    if skipped:
        print("\nBO QUA CO Y DINH:")
        for tool, count in sorted(skipped.items(), key=lambda item: -item[1]):
            print(f"  {count:7d}  {tool}  -- {KNOWINGLY_SKIPPED[tool]}")
    if dead:
        print("\nLANE CHET (khai bao nhung 0 observation -- tool doi ten?):")
        for tool in dead:
            print(f"        0  {tool}")
    if uncovered:
        print("\nBO LOT (tool da chay nhung khong co lane):")
        for tool, count in sorted(uncovered.items(), key=lambda item: -item[1]):
            print(f"  {count:7d}  {tool}")
        print(
            "\nThem vao TOOL_ENRICHMENT_NAMES trong src/weekly_cs_report/"
            "enrichment.py,\nhoac vao KNOWINGLY_SKIPPED trong script nay kem ly do."
        )
    if not uncovered and not dead:
        print("\nOK: moi tool da chay deu co lane hoac duoc bo qua co y dinh.")
    return 1 if (uncovered or dead) else 0


if __name__ == "__main__":
    raise SystemExit(main())
