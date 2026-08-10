from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKER = PROJECT_ROOT / "scripts" / "check_python_coverage.py"
CRITICAL = "src/weekly_cs_report/report.py"


def _report(
    *,
    total: object = 85.0,
    files: object | None = None,
) -> object:
    if files is None:
        files = {CRITICAL: {"summary": {"percent_covered": 80.0}}}
    return {
        "totals": {"percent_covered": total},
        "files": files,
    }


def _run(
    tmp_path: Path,
    report: object | None,
    *suffixes: str,
    minimum_total: str = "85",
    minimum_file: str = "80",
) -> subprocess.CompletedProcess[str]:
    coverage_json = tmp_path / "coverage.json"
    if report is not None:
        contents = report if isinstance(report, str) else json.dumps(report)
        coverage_json.write_text(contents, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            str(coverage_json),
            minimum_total,
            minimum_file,
            *(suffixes or (CRITICAL,)),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_checker_accepts_exact_total_and_file_boundaries(tmp_path: Path):
    result = _run(tmp_path, _report())

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "TOTAL COVERAGE: 85.00%\nFILE COVERAGE: report.py 80.00%\n"


@pytest.mark.parametrize(
    ("total", "minimum_total"),
    [
        (84.99, "85"),
        (85.0, "85.01"),
    ],
)
def test_checker_rejects_total_below_minimum(
    tmp_path: Path, total: float, minimum_total: str
):
    result = _run(tmp_path, _report(total=total), minimum_total=minimum_total)

    assert result.returncode != 0
    assert result.stderr == ""
    assert result.stdout == f"TOTAL COVERAGE BELOW MINIMUM: {total:.2f}% < {float(minimum_total):.2f}%\n"


@pytest.mark.parametrize(
    ("file_percent", "minimum_file"),
    [
        (79.99, "80"),
        (80.0, "80.01"),
    ],
)
def test_checker_rejects_critical_file_below_minimum(
    tmp_path: Path, file_percent: float, minimum_file: str
):
    result = _run(
        tmp_path,
        _report(files={CRITICAL: {"summary": {"percent_covered": file_percent}}}),
        minimum_file=minimum_file,
    )

    assert result.returncode != 0
    assert result.stderr == ""
    assert result.stdout == (
        "FILE COVERAGE BELOW MINIMUM: report.py "
        f"{file_percent:.2f}% < {float(minimum_file):.2f}%\n"
    )


@pytest.mark.parametrize(
    ("file_percent", "expected"),
    [
        (
            80.0,
            "TOTAL COVERAGE: 85.00%\nFILE COVERAGE: report.py 80.00%\n",
        ),
        (
            79.99,
            "FILE COVERAGE BELOW MINIMUM: report.py 79.99% < 80.00%\n",
        ),
    ],
)
def test_checker_uses_a_safe_suffix_identifier_instead_of_coverage_json_paths(
    tmp_path: Path, file_percent: float, expected: str
):
    private_prefix = "/private/credential-prefix/\nFILE COVERAGE: injected/"
    report_filename = f"{private_prefix}{CRITICAL}"
    result = _run(
        tmp_path,
        _report(files={report_filename: {"summary": {"percent_covered": file_percent}}}),
    )

    assert result.returncode == (0 if file_percent == 80.0 else 1)
    assert result.stderr == ""
    assert private_prefix not in result.stdout
    assert result.stdout == expected


@pytest.mark.parametrize(
    "report",
    [
        pytest.param(None, id="missing-file"),
        pytest.param("not-json", id="malformed-json"),
        pytest.param([], id="root-not-object"),
        pytest.param({"files": {}}, id="missing-totals"),
        pytest.param({"totals": [], "files": {}}, id="totals-not-object"),
        pytest.param({"totals": {}, "files": {}}, id="missing-total-percent"),
        pytest.param(
            {
                "totals": {"percent_covered": True},
                "files": {CRITICAL: {"summary": {"percent_covered": 80}}},
            },
            id="boolean-total-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": "NaN"},
                "files": {CRITICAL: {"summary": {"percent_covered": 80}}},
            },
            id="non-numeric-total-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": float("inf")},
                "files": {CRITICAL: {"summary": {"percent_covered": 80}}},
            },
            id="non-finite-total-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 100.01},
                "files": {CRITICAL: {"summary": {"percent_covered": 80}}},
            },
            id="out-of-range-total-percent",
        ),
        pytest.param({"totals": {"percent_covered": 85}}, id="missing-files"),
        pytest.param(
            {"totals": {"percent_covered": 85}, "files": []},
            id="files-not-object",
        ),
        pytest.param(
            {"totals": {"percent_covered": 85}, "files": {CRITICAL: []}},
            id="file-entry-not-object",
        ),
        pytest.param(
            {"totals": {"percent_covered": 85}, "files": {CRITICAL: {}}},
            id="missing-summary",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": []}},
            },
            id="summary-not-object",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": {}}},
            },
            id="missing-file-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": {"percent_covered": False}}},
            },
            id="boolean-file-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": {"percent_covered": "80"}}},
            },
            id="non-numeric-file-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": {"percent_covered": float("nan")}}},
            },
            id="non-finite-file-percent",
        ),
        pytest.param(
            {
                "totals": {"percent_covered": 85},
                "files": {CRITICAL: {"summary": {"percent_covered": -0.01}}},
            },
            id="out-of-range-file-percent",
        ),
    ],
)
def test_checker_fails_closed_for_invalid_reports(tmp_path: Path, report: object | None):
    result = _run(tmp_path, report)

    assert result.returncode != 0
    assert result.stderr == ""
    assert result.stdout == "INVALID COVERAGE REPORT\n"


def test_checker_rejects_duplicate_requested_suffixes(tmp_path: Path):
    result = _run(tmp_path, _report(), CRITICAL, CRITICAL)

    assert result.returncode != 0
    assert result.stdout == "INVALID COVERAGE REQUEST\n"


def test_checker_rejects_different_suffixes_selecting_the_same_file(tmp_path: Path):
    result = _run(tmp_path, _report(), CRITICAL, "report.py")

    assert result.returncode != 0
    assert result.stdout == "INVALID COVERAGE REQUEST\n"


def test_checker_fails_closed_for_an_unreadable_coverage_path(tmp_path: Path):
    coverage_directory = tmp_path / "coverage.json"
    coverage_directory.mkdir()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(coverage_directory), "85", "80", CRITICAL],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stderr == ""
    assert result.stdout == "INVALID COVERAGE REPORT\n"


def test_checker_rejects_unmatched_requested_suffix(tmp_path: Path):
    result = _run(tmp_path, _report(), "src/weekly_cs_report/missing.py")

    assert result.returncode != 0
    assert result.stdout == "INVALID COVERAGE REPORT\n"


def test_checker_rejects_suffix_matching_more_than_one_file(tmp_path: Path):
    report = _report(
        files={
            "src/first/report.py": {"summary": {"percent_covered": 80}},
            "src/second/report.py": {"summary": {"percent_covered": 80}},
        }
    )
    result = _run(tmp_path, report, "report.py")

    assert result.returncode != 0
    assert result.stdout == "INVALID COVERAGE REPORT\n"


def test_checker_never_echoes_report_contents_or_input_path(tmp_path: Path):
    secret = "credential-should-not-appear"
    coverage_json = tmp_path / f"{secret}.json"
    coverage_json.write_text("{" + secret, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(coverage_json), "85", "80", CRITICAL],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    assert result.stdout == "INVALID COVERAGE REPORT\n"
