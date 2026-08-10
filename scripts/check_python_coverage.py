#!/usr/bin/env python3
"""Fail closed when a Python coverage JSON report misses required thresholds."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable


def _percentage(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    percentage = float(value)
    if not math.isfinite(percentage) or not 0.0 <= percentage <= 100.0:
        raise ValueError
    return percentage


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError
    return value


def _safe_identifier(suffix: str) -> str:
    identifier = suffix.rsplit("/", 1)[-1]
    if not identifier or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in identifier
    ):
        raise RuntimeError
    return identifier


def _load_report(report_path: Path) -> tuple[float, dict[str, float]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        root = _mapping(report)
        totals = _mapping(root["totals"])
        total = _percentage(totals["percent_covered"])
        files = _mapping(root["files"])
        file_percentages: dict[str, float] = {}
        for filename, entry in files.items():
            if not isinstance(filename, str) or not filename:
                raise ValueError
            summary = _mapping(_mapping(entry)["summary"])
            file_percentages[filename] = _percentage(summary["percent_covered"])
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError from None
    return total, file_percentages


def _requested_files(
    file_percentages: dict[str, float], suffixes: Iterable[str]
) -> list[tuple[str, float]]:
    requested_suffixes = list(suffixes)
    if (
        not requested_suffixes
        or any(not suffix for suffix in requested_suffixes)
        or len(set(requested_suffixes)) != len(requested_suffixes)
    ):
        raise RuntimeError

    selected: list[tuple[str, float]] = []
    selected_filenames: set[str] = set()
    for suffix in requested_suffixes:
        identifier = _safe_identifier(suffix)
        matches = [
            (filename, percentage)
            for filename, percentage in file_percentages.items()
            if filename.endswith(suffix)
        ]
        if len(matches) != 1:
            raise ValueError
        filename, percentage = matches[0]
        if filename in selected_filenames:
            raise RuntimeError
        selected_filenames.add(filename)
        selected.append((identifier, percentage))
    return selected


def _minimum(value: str) -> float:
    try:
        return _percentage(float(value))
    except (TypeError, ValueError):
        raise ValueError from None


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print("INVALID COVERAGE REQUEST")
        return 1

    report_path = Path(argv[0])
    try:
        minimum_total = _minimum(argv[1])
        minimum_file = _minimum(argv[2])
        total, file_percentages = _load_report(report_path)
        selected = _requested_files(file_percentages, argv[3:])
    except RuntimeError:
        print("INVALID COVERAGE REQUEST")
        return 1
    except ValueError:
        print("INVALID COVERAGE REPORT")
        return 1

    if total < minimum_total:
        print(f"TOTAL COVERAGE BELOW MINIMUM: {total:.2f}% < {minimum_total:.2f}%")
        return 1
    for filename, percentage in selected:
        if percentage < minimum_file:
            print(
                "FILE COVERAGE BELOW MINIMUM: "
                f"{filename} {percentage:.2f}% < {minimum_file:.2f}%"
            )
            return 1

    print(f"TOTAL COVERAGE: {total:.2f}%")
    for filename, percentage in selected:
        print(f"FILE COVERAGE: {filename} {percentage:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
