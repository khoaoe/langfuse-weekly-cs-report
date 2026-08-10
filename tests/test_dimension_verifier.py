from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from unicodedata import normalize
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.traces import trace
from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.cli import (
    PROJECT_ROOT,
    TARGET_BASE_URL,
    EnvironmentSettings,
    RunConfig,
    build_parser,
    main,
)
from weekly_cs_report.classification import normalize_trace
from weekly_cs_report.models import TraceRecord


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
TAXONOMY_V2 = PROJECT_ROOT / "config" / "taxonomy.v2.json"
FINAL_REPORT_DENY_KEYS = (
    "UserID",
    "App user",
    "Số điện thoại người dùng",
    "TransID",
    "AppTransId",
    "Mã giao dịch",
    "Zalopay chat keys",
    "System Info",
    "UserAgent",
    "Ghi chú",
    "Ghi chú bên thứ ba",
    "Mô tả",
    "Vấn đề",
    "Thông tin thêm",
    "title",
    "user_input",
    "comments",
    "Số tài khoản ngân hàng",
    "SĐT đăng ký NH",
    "Thời gian giao dịch",
    "Thời điểm giao dịch",
    "session_id",
    "trace_id",
    "sessionId",
    "traceId",
    "input",
    "output",
    "meta",
    "metadata",
    "raw payload",
    "raw_payload",
    "rawPayload",
    "payload",
    "prompt",
    "response",
    "id",
    "internal_id",
    "internal_ids",
    "langfuse_id",
    "observation_id",
    "observationId",
    "score_id",
    "scoreId",
    "project_id",
    "projectId",
    "description",
    "step_description",
    "tpe_status_raw",
    "user_id",
    "trans_id",
    "other_info",
)
PRIVACY_VALIDATION_ERROR = (
    "dimension verification report failed privacy validation"
)
RETIRED_DIMENSION_REPORT_KEYS = frozenset(
    {
        "issue_category_backfilled_count",
        "tpe_backfilled_count",
        "freshdesk_tpe_applicable_ticket_count",
        "freshdesk_tpe_applicable_present_count",
        "freshdesk_tpe_applicable_missing_count",
        "freshdesk_tpe_non_applicable_ticket_count",
        "freshdesk_tpe_applicability_unknown_ticket_count",
        "coverage_freshdesk_tpe_applicable",
        "p0_freshdesk_tpe_applicable_pass",
    }
)


def _ticket_trace(
    trace_id: str,
    session_id: str,
    turn: int,
    timestamp: str,
    *,
    issue_category: str | None = None,
    tpe: str | None = None,
    entry_point: str | None = "ticketdetail",
    description: str = "PII customer phone 0900000000",
) -> dict:
    raw = trace(
        trace_id,
        session_id,
        turn,
        timestamp,
        "Sensitive response payload",
        title="Sensitive ticket title",
    )
    meta = {
        "Thông tin thêm": {
            "Mô tả": description,
        },
        "App": "241 - Chuyển Tiền ATM",
        "Product Code": "TF007 - IBFT money transfer",
        "Kênh thanh toán": "38 - TK Zalo Pay",
    }
    if entry_point is not None:
        meta["Thông tin thêm"]["sub_source"] = entry_point
    if issue_category is not None:
        meta["Thông tin thêm"]["category"] = issue_category
    if tpe is not None:
        meta["Mã lỗi TPE"] = tpe
    raw["input"]["other_info"]["meta"] = meta
    return raw


def _verifier_module():
    return importlib.import_module("weekly_cs_report.dimension_verifier")


@pytest.mark.parametrize("value", ["", " null ", "None", "undefined"])
def test_diagnostic_entry_point_treats_null_like_values_as_broken(value):
    record = normalize_trace(
        _ticket_trace(
            "diagnostic-null-like",
            "diagnostic-null-like-session",
            0,
            "2026-07-21T01:00:00Z",
            entry_point=value,
        )
    )

    assert isinstance(record, TraceRecord)
    assert _verifier_module()._diagnostic_entry_point(
        record,
        load_taxonomy(TAXONOMY_V2),
    ) == ("null_string", None)


@pytest.mark.parametrize("value", [None, 17, ["tranxdetail"]])
def test_diagnostic_entry_point_separates_present_invalid_types(value):
    raw = _ticket_trace(
        "diagnostic-invalid-type",
        "diagnostic-invalid-type-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point="placeholder",
    )
    raw["input"]["other_info"]["meta"]["Thông tin thêm"]["sub_source"] = value
    record = normalize_trace(raw)

    assert isinstance(record, TraceRecord)
    assert _verifier_module()._diagnostic_entry_point(
        record,
        load_taxonomy(TAXONOMY_V2),
    ) == ("invalid_type", None)


def test_diagnostic_entry_point_separates_absent_and_normalized_values():
    taxonomy = load_taxonomy(TAXONOMY_V2)
    absent = normalize_trace(
        _ticket_trace(
            "diagnostic-absent",
            "diagnostic-absent-session",
            0,
            "2026-07-21T01:00:00Z",
            entry_point=None,
        )
    )
    present = normalize_trace(
        _ticket_trace(
            "diagnostic-present",
            "diagnostic-present-session",
            0,
            "2026-07-21T01:00:00Z",
            entry_point=" tranxdetail ",
        )
    )

    assert isinstance(absent, TraceRecord)
    assert isinstance(present, TraceRecord)
    assert _verifier_module()._diagnostic_entry_point(absent, taxonomy) == (
        "absent",
        None,
    )
    assert _verifier_module()._diagnostic_entry_point(present, taxonomy) == (
        "value",
        "tranxdetail",
    )


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _nested_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def _nested_strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return {
            item
            for child in value.values()
            for item in _nested_strings(child)
        }
    if isinstance(value, list):
        return {item for child in value for item in _nested_strings(child)}
    return set()


@pytest.mark.parametrize("denied_key", FINAL_REPORT_DENY_KEYS)
def test_final_report_privacy_validator_rejects_every_nested_deny_key_without_echo(
    denied_key: str,
):
    verifier = _verifier_module()
    marker = f"unique-private-marker::{denied_key}"
    unsafe_report = {
        "safe_root": [
            {
                "safe_middle": {
                    "safe_leaf": {
                        denied_key: marker,
                    }
                }
            }
        ]
    }

    with pytest.raises(ValueError) as captured:
        verifier.validate_dimension_report_privacy(unsafe_report)

    assert str(captured.value) == PRIVACY_VALIDATION_ERROR
    assert marker not in str(captured.value)


def test_final_report_deny_list_is_immutable_and_normalizes_vietnamese_keys():
    verifier = _verifier_module()
    decomposed_key = normalize("NFD", "Số điện thoại người dùng")

    assert verifier.DIMENSION_REPORT_DENY_KEYS == frozenset(
        FINAL_REPORT_DENY_KEYS
    )
    with pytest.raises(AttributeError):
        verifier.DIMENSION_REPORT_DENY_KEYS.add("new-key")
    with pytest.raises(ValueError) as captured:
        verifier.validate_dimension_report_privacy(
            {"safe": [{decomposed_key: "decomposed-private-marker"}]}
        )

    assert str(captured.value) == PRIVACY_VALIDATION_ERROR
    assert "decomposed-private-marker" not in str(captured.value)


@pytest.mark.parametrize(
    "private_value",
    [
        "Khách hàng ０９０\u200b١２3٤５6٧ cần hỗ trợ",
        "Liên hệ +８４ ９０１-２３４-５６７",
        "ref ５５０ｅ８４００－ｅ２９ｂ－４１ｄ４－ａ７１６－４４６６５５４４００００",
        "ref 550e8400-\u200be29b-41d4-a716-446655440000",
        "ref dead\uFE0Fbeef-cafe-babe-acde-feedfacebeef",
        "ref dead\u034Fbeef-cafe-babe-acde-feedfacebeef",
    ],
    ids=(
        "mixed-unicode-local-phone",
        "full-width-country-phone",
        "full-width-uuid",
        "zero-width-uuid",
        "variation-selector-uuid",
        "combining-grapheme-joiner-uuid",
    ),
)
def test_final_report_privacy_validator_recursively_rejects_normalized_pii_values(
    private_value: str,
):
    verifier = _verifier_module()
    unsafe_report = {
        "safe_counts": {"ticket_count": 1},
        "safe_rows": [{"code": "-217", "status": private_value, "count": 1}],
    }

    with pytest.raises(ValueError) as captured:
        verifier.validate_dimension_report_privacy(unsafe_report)

    assert str(captured.value) == PRIVACY_VALIDATION_ERROR
    assert private_value not in str(captured.value)


def test_verify_raw_ticket_dimensions_runs_final_privacy_scan_before_return(
    monkeypatch,
):
    verifier = _verifier_module()
    private_marker = "private-final-return-marker"
    monkeypatch.setattr(
        verifier,
        "aggregate_dimension_coverage",
        lambda *_args, **_kwargs: {
            "safe": [{"session_id": private_marker}],
        },
    )

    with pytest.raises(ValueError) as captured:
        verifier.verify_raw_ticket_dimensions(
            [
                _ticket_trace(
                    "return-scan-trace",
                    "return-scan-session",
                    1,
                    "2026-07-21T01:00:00Z",
                )
            ],
            load_taxonomy(TAXONOMY_V2),
        )

    assert str(captured.value) == PRIVACY_VALIDATION_ERROR
    assert private_marker not in str(captured.value)


def test_verify_dimensions_cli_revalidates_before_print_with_sanitized_error(
    monkeypatch,
    capsys,
):
    private_marker = "private-final-print-marker"
    client = ReadOnlyVerifierClient([])
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli._build_client",
        lambda _settings: client,
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli.verify_raw_ticket_dimensions",
        lambda *_args, **_kwargs: {
            "safe": [{"trace_id": private_marker}],
        },
    )

    exit_code = main(
        [
            "verify-dimensions",
            "--weeks",
            "2",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.strip() == PRIVACY_VALIDATION_ERROR
    assert private_marker not in captured.err


def test_verify_raw_traces_counts_all_valid_sessions_without_turn0_weekday_or_unique_turn_rules():
    raw = [
        _ticket_trace(
            "weekend-turn-9",
            "secret-weekend-session",
            9,
            "2026-07-25T03:00:00Z",
            issue_category="Thanh toán-IBFT",
            tpe="-383 Đang xử lý",
        ),
        _ticket_trace(
            "tuple-turn-2",
            "secret-tuple-session",
            2,
            "2026-07-20T01:00:00Z",
            issue_category="wrong-turn",
            tpe="-383 Wrong turn",
        ),
        _ticket_trace(
            "tuple-turn-1-z",
            "secret-tuple-session",
            1,
            "2026-07-21T01:00:00Z",
            issue_category="wrong-id",
            tpe="-383 Wrong id",
        ),
        _ticket_trace(
            "tuple-turn-1-a",
            "secret-tuple-session",
            1,
            "2026-07-21T01:00:00Z",
            issue_category="Thanh toán-Tuple",
            tpe="-217 Thất bại",
        ),
        _ticket_trace(
            "unmapped-2",
            "secret-second-unmapped-session",
            7,
            "2026-07-22T01:00:00Z",
            issue_category="Thanh toán-TPE",
            tpe="-217 Thất bại",
        ),
        _ticket_trace(
            "unmapped-2",
            "secret-second-unmapped-session",
            7,
            "2026-07-22T01:00:00Z",
            issue_category="Thanh toán-TPE",
            tpe="-217 Thất bại",
        ),
        _ticket_trace(
            "unmapped-low-a",
            "secret-unmapped-low-a",
            4,
            "2026-07-23T01:00:00Z",
            tpe="-111 Alpha",
        ),
        _ticket_trace(
            "unmapped-low-z",
            "secret-unmapped-low-z",
            4,
            "2026-07-24T01:00:00Z",
            tpe="-999 Zulu",
        ),
        _ticket_trace(
            "missing-dimensions",
            "secret-missing-session",
            3,
            "2026-07-24T02:00:00Z",
        ),
        {
            **_ticket_trace(
                "not-a-ticket",
                "secret-chat-session",
                0,
                "2026-07-24T03:00:00Z",
                issue_category="must be excluded",
                tpe="-217 must be excluded",
            ),
            "input": {"source": "chat", "raw_pii": "private"},
        },
        {
            **_ticket_trace(
                "invalid-timestamp",
                "secret-invalid-session",
                0,
                "2026-07-24T04:00:00Z",
            ),
            "timestamp": "not-a-timestamp",
        },
    ]

    report = _verifier_module().verify_raw_ticket_dimensions(
        raw,
        load_taxonomy(TAXONOMY_V2),
    )

    assert report == {
        "traces_fetched": 10,
        "traces_deduplicated": 9,
        "invalid_trace_count": 1,
        "ticket_count": 7,
        "trace_issue_category_present_count": 3,
        "trace_tpe_present_count": 5,
        "issue_category_present_count": 3,
        "tpe_present_count": 5,
        "coverage_issue_category": 3 / 7,
        "coverage_tpe": 5 / 7,
        "p0_issue_category_pass": False,
        "p0_tpe_pass": False,
        "p0_pass": False,
        "applicable_population_definition": "entry_point == tranxdetail",
        "applicable_ticket_count": 0,
        "applicable_tpe_present": 0,
        "coverage_tpe_applicable": 0.0,
        "non_applicable_ticket_count": 6,
        "entry_point_absent_count": 0,
        "entry_point_null_string_count": 0,
        "entry_point_invalid_type_count": 0,
        "diagnostic_uninspectable_ticket_count": 1,
        "category_gap_by_entry_point": {
            "<other-valid>": 3,
            "<uninspectable>": 1,
        },
        "unmapped_tpe_codes": [
            {"code": "-217", "status": "Thất bại", "count": 2},
            {"code": "-111", "status": None, "count": 1},
            {"code": "-383", "status": "Đang xử lý", "count": 1},
            {"code": "-999", "status": None, "count": 1},
        ],
    }


def test_raw_ticket_denominator_keeps_invalid_conflicting_and_unkeyed_units():
    valid = _ticket_trace(
        "valid-denominator",
        "valid-session",
        0,
        "2026-07-21T01:00:00Z",
        issue_category="Thanh toán-IBFT",
        tpe="-217 Thất bại",
    )
    invalid = {
        **_ticket_trace(
            "invalid-denominator",
            "invalid-session",
            0,
            "2026-07-21T01:00:00Z",
        ),
        "timestamp": "not-a-timestamp",
    }
    conflict_one = _ticket_trace(
        "conflicting-trace",
        "conflict-session",
        0,
        "2026-07-21T02:00:00Z",
    )
    conflict_two = _ticket_trace(
        "conflicting-trace",
        "conflict-session",
        1,
        "2026-07-21T02:01:00Z",
    )
    unkeyed_one = _ticket_trace(
        "unkeyed-one", None, 0, "2026-07-21T03:00:00Z"
    )
    unkeyed_two = _ticket_trace(
        "unkeyed-two", "", 0, "2026-07-21T03:01:00Z"
    )

    report = _verifier_module().verify_raw_ticket_dimensions(
        [valid, invalid, conflict_one, conflict_two, unkeyed_one, unkeyed_two],
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["ticket_count"] == 5
    assert report["issue_category_present_count"] == 1
    assert report["tpe_present_count"] == 1
    assert report["coverage_issue_category"] == 0.2
    assert report["coverage_tpe"] == 0.2


def test_langfuse_only_p0_uses_exact_all_ticket_raw_thresholds():
    raw = [
        _ticket_trace(
            f"raw-boundary-{index}",
            f"raw-boundary-session-{index}",
            0,
            f"2026-07-21T01:{index:02d}:00Z",
            issue_category="Thanh toán-IBFT" if index < 18 else None,
            tpe="-217 Thất bại" if index < 17 else None,
            entry_point="ticketdetail",
        )
        for index in range(20)
    ]

    report = _verifier_module().verify_raw_ticket_dimensions(
        raw,
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["ticket_count"] == 20
    assert report["coverage_issue_category"] == 0.90
    assert report["coverage_tpe"] == 0.85
    assert report["p0_issue_category_pass"] is True
    assert report["p0_tpe_pass"] is True
    assert report["p0_pass"] is True


def test_langfuse_only_report_omits_retired_backfill_and_applicability_keys():
    report = _verifier_module().verify_raw_ticket_dimensions(
        [
            _ticket_trace(
                "raw-only",
                "raw-only-session",
                0,
                "2026-07-21T01:00:00Z",
                issue_category="Thanh toán-IBFT",
                tpe="-217 Thất bại",
                entry_point="tranxdetail",
            )
        ],
        load_taxonomy(TAXONOMY_V2),
    )

    assert RETIRED_DIMENSION_REPORT_KEYS.isdisjoint(report)
    assert report["p0_tpe_pass"] is True


def test_langfuse_only_verifier_exposes_no_backfill_arguments():
    verifier = _verifier_module()

    assert "dimension_backfill" not in signature(
        verifier.aggregate_dimension_coverage
    ).parameters
    assert "dimension_backfill" not in signature(
        verifier.verify_raw_ticket_dimensions
    ).parameters


def test_langfuse_only_empty_population_fails_closed():
    report = _verifier_module().verify_raw_ticket_dimensions(
        [],
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["ticket_count"] == 0
    assert report["coverage_issue_category"] == 0.0
    assert report["coverage_tpe"] == 0.0
    assert report["p0_issue_category_pass"] is False
    assert report["p0_tpe_pass"] is False
    assert report["p0_pass"] is False


def test_aggregate_dimension_coverage_accepts_explicit_raw_denominator_override():
    raw = _ticket_trace(
        "override-trace",
        "override-session",
        0,
        "2026-07-21T01:00:00Z",
        issue_category="Thanh toán-IBFT",
        tpe="-217 Thất bại",
    )
    record = normalize_trace(raw)
    assert isinstance(record, TraceRecord)

    report = _verifier_module().aggregate_dimension_coverage(
        [record],
        load_taxonomy(TAXONOMY_V2),
        traces_fetched=2,
        traces_deduplicated=1,
        invalid_trace_count=1,
        diagnostic_uninspectable_ticket_count=1,
        ticket_count_override=2,
    )

    assert report["ticket_count"] == 2
    assert report["coverage_issue_category"] == 0.5
    assert report["coverage_tpe"] == 0.5


def test_applicable_diagnostics_partition_population_without_changing_legacy_gate():
    tranxdetail = _ticket_trace(
        "diagnostic-tranxdetail",
        "diagnostic-tranxdetail-session",
        0,
        "2026-07-21T01:00:00Z",
        issue_category="Thanh toán-IBFT",
        tpe="-217 Thất bại",
        entry_point="tranxdetail",
    )
    resultpage = _ticket_trace(
        "diagnostic-resultpage",
        "diagnostic-resultpage-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point="resultpage",
    )
    absent = _ticket_trace(
        "diagnostic-absent-aggregate",
        "diagnostic-absent-aggregate-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point=None,
    )
    null_string = _ticket_trace(
        "diagnostic-null-string-aggregate",
        "diagnostic-null-string-aggregate-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point=" null ",
    )
    invalid_type = _ticket_trace(
        "diagnostic-invalid-type-aggregate",
        "diagnostic-invalid-type-aggregate-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point="placeholder",
    )
    invalid_type["input"]["other_info"]["meta"]["Thông tin thêm"][
        "sub_source"
    ] = None
    private_other = _ticket_trace(
        "diagnostic-private-other",
        "diagnostic-private-other-session",
        0,
        "2026-07-21T01:00:00Z",
        entry_point="private-0900000000",
    )
    uninspectable = {
        **_ticket_trace(
            "diagnostic-uninspectable",
            "diagnostic-uninspectable-session",
            0,
            "2026-07-21T01:00:00Z",
            entry_point="tranxdetail",
        ),
        "metadata": {"turn": -1},
    }

    report = _verifier_module().verify_raw_ticket_dimensions(
        [
            tranxdetail,
            resultpage,
            absent,
            null_string,
            invalid_type,
            private_other,
            uninspectable,
        ],
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["applicable_population_definition"] == (
        "entry_point == tranxdetail"
    )
    assert report["applicable_ticket_count"] == 1
    assert report["applicable_tpe_present"] == 1
    assert report["coverage_tpe_applicable"] == 1.0
    assert report["non_applicable_ticket_count"] == 2
    assert report["entry_point_absent_count"] == 1
    assert report["entry_point_null_string_count"] == 1
    assert report["entry_point_invalid_type_count"] == 1
    assert report["diagnostic_uninspectable_ticket_count"] == 1
    population_keys = (
        "applicable_ticket_count",
        "non_applicable_ticket_count",
        "entry_point_absent_count",
        "entry_point_null_string_count",
        "entry_point_invalid_type_count",
        "diagnostic_uninspectable_ticket_count",
    )
    assert sum(report[key] for key in population_keys) == report["ticket_count"]
    assert report["category_gap_by_entry_point"] == {
        "<absent>": 1,
        "<invalid-type>": 1,
        "<null-string>": 1,
        "<other-valid>": 1,
        "<uninspectable>": 1,
        "resultpage": 1,
    }
    assert report["ticket_count"] == 7
    assert report["issue_category_present_count"] == 1
    assert report["tpe_present_count"] == 1
    assert report["coverage_issue_category"] == 1 / 7
    assert report["coverage_tpe"] == 1 / 7
    assert report["p0_issue_category_pass"] is False
    assert report["p0_tpe_pass"] is False
    assert report["p0_pass"] is False
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "private-0900000000" not in serialized


def test_aggregate_records_treats_taxonomy_fallback_literal_as_missing():
    raw = _ticket_trace(
        "record-only",
        "record-session",
        5,
        "2026-07-21T01:00:00Z",
        issue_category="Không xác định",
    )
    record = normalize_trace(raw)
    assert isinstance(record, TraceRecord)

    report = _verifier_module().aggregate_dimension_coverage(
        [record],
        load_taxonomy(TAXONOMY_V2),
        traces_fetched=1,
        traces_deduplicated=1,
        invalid_trace_count=0,
        diagnostic_uninspectable_ticket_count=0,
    )

    assert report["trace_issue_category_present_count"] == 0
    assert report["issue_category_present_count"] == 0
    assert report["coverage_issue_category"] == 0.0


def test_verifier_is_deterministic_and_invalid_raw_ticket_stays_in_denominator():
    verifier = _verifier_module()
    taxonomy = load_taxonomy(TAXONOMY_V2)
    invalid = {
        **_ticket_trace(
            "invalid",
            "invalid-session",
            0,
            "2026-07-21T01:00:00Z",
        ),
        "metadata": {"turn": -1},
    }

    first = verifier.verify_raw_ticket_dimensions([invalid], taxonomy)
    second = verifier.verify_raw_ticket_dimensions([invalid], taxonomy)

    assert first == second
    assert first == {
        "traces_fetched": 1,
        "traces_deduplicated": 1,
        "invalid_trace_count": 1,
        "ticket_count": 1,
        "trace_issue_category_present_count": 0,
        "trace_tpe_present_count": 0,
        "issue_category_present_count": 0,
        "tpe_present_count": 0,
        "coverage_issue_category": 0.0,
        "coverage_tpe": 0.0,
        "p0_issue_category_pass": False,
        "p0_tpe_pass": False,
        "p0_pass": False,
        "applicable_population_definition": "entry_point == tranxdetail",
        "applicable_ticket_count": 0,
        "applicable_tpe_present": 0,
        "coverage_tpe_applicable": 0.0,
        "non_applicable_ticket_count": 0,
        "entry_point_absent_count": 0,
        "entry_point_null_string_count": 0,
        "entry_point_invalid_type_count": 0,
        "diagnostic_uninspectable_ticket_count": 1,
        "category_gap_by_entry_point": {"<uninspectable>": 1},
        "unmapped_tpe_codes": [],
    }


def test_identical_trace_id_payloads_dedupe_even_when_mapping_key_order_differs():
    original = _ticket_trace(
        "canonical-duplicate",
        "canonical-session",
        2,
        "2026-07-21T01:00:00Z",
        issue_category="Thanh toán-IBFT",
        tpe="-217 Thất bại",
    )
    reordered = dict(reversed(tuple(original.items())))

    report = _verifier_module().verify_raw_ticket_dimensions(
        [original, reordered],
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["traces_fetched"] == 2
    assert report["traces_deduplicated"] == 1
    assert report["invalid_trace_count"] == 0
    assert report["ticket_count"] == 1


def test_conflicting_trace_id_payloads_drop_every_variant_order_independently():
    valid = _ticket_trace(
        "valid-trace",
        "valid-session",
        1,
        "2026-07-21T01:00:00Z",
        issue_category="Thanh toán-IBFT",
        tpe="-217 Thất bại",
    )
    collision_a1 = _ticket_trace(
        "collision-a",
        "secret-collision-a",
        1,
        "2026-07-21T02:00:00Z",
        issue_category="private-a1",
        tpe="-999 private-a1",
    )
    collision_a2 = _ticket_trace(
        "collision-a",
        "secret-collision-a",
        1,
        "2026-07-21T02:00:00Z",
        issue_category="private-a2",
        tpe="-999 private-a2",
    )
    collision_b1 = _ticket_trace(
        "collision-b",
        "secret-collision-b",
        1,
        "2026-07-21T03:00:00Z",
        issue_category="private-b1",
    )
    collision_b2 = _ticket_trace(
        "collision-b",
        "secret-collision-b",
        2,
        "2026-07-21T03:00:00Z",
        issue_category="private-b2",
    )
    ordered = [valid, collision_a1, collision_a2, collision_b1, collision_b2]

    forward = _verifier_module().verify_raw_ticket_dimensions(
        ordered,
        load_taxonomy(TAXONOMY_V2),
    )
    reverse = _verifier_module().verify_raw_ticket_dimensions(
        list(reversed(ordered)),
        load_taxonomy(TAXONOMY_V2),
    )

    assert forward == reverse
    assert forward == {
        "traces_fetched": 5,
        "traces_deduplicated": 1,
        "invalid_trace_count": 2,
        "ticket_count": 3,
        "trace_issue_category_present_count": 1,
        "trace_tpe_present_count": 1,
        "issue_category_present_count": 1,
        "tpe_present_count": 1,
        "coverage_issue_category": 1 / 3,
        "coverage_tpe": 1 / 3,
        "p0_issue_category_pass": False,
        "p0_tpe_pass": False,
        "p0_pass": False,
        "applicable_population_definition": "entry_point == tranxdetail",
        "applicable_ticket_count": 0,
        "applicable_tpe_present": 0,
        "coverage_tpe_applicable": 0.0,
        "non_applicable_ticket_count": 1,
        "entry_point_absent_count": 0,
        "entry_point_null_string_count": 0,
        "entry_point_invalid_type_count": 0,
        "diagnostic_uninspectable_ticket_count": 2,
        "category_gap_by_entry_point": {"<uninspectable>": 2},
        "unmapped_tpe_codes": [
            {"code": "-217", "status": "Thất bại", "count": 1}
        ],
    }
    serialized = json.dumps(forward, ensure_ascii=False, sort_keys=True)
    assert "private-a" not in serialized
    assert "private-b" not in serialized
    assert "secret-collision" not in serialized


def test_report_json_never_contains_ticket_ids_payloads_pii_or_descriptions():
    report = _verifier_module().verify_raw_ticket_dimensions(
        [
            _ticket_trace(
                "secret-trace-id",
                "secret-session-id",
                8,
                "2026-07-21T01:00:00Z",
                issue_category="Thanh toán-IBFT",
                tpe="-217 Khach 0901234567",
                description="Secret customer phone 0900000000",
            )
        ],
        load_taxonomy(TAXONOMY_V2),
    )

    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    forbidden_values = (
        "secret-trace-id",
        "secret-session-id",
        "Sensitive response payload",
        "Sensitive ticket title",
        "0900000000",
        "0901234567",
        "Khach 0901234567",
    )
    forbidden_keys = {
        "session_id",
        "trace_id",
        "input",
        "output",
        "meta",
        "metadata",
        "description",
        "Mô tả",
        "step_description",
        "payload",
        "tpe_status_raw",
    }

    assert all(value not in serialized for value in forbidden_values)
    assert not (forbidden_keys & _nested_keys(report))
    assert not (set(forbidden_values) & _nested_strings(report))
    assert report["tpe_present_count"] == 0
    assert report["coverage_tpe"] == 0.0
    assert report["unmapped_tpe_codes"] == []


@pytest.mark.parametrize(
    "unsafe_status",
    [
        "user 550e8400-e29b-41d4-a716-446655440000",
        "john.doe@example.com",
        "Nguyen Van An",
        "Nguyễn Văn An",
        "Thất bại|private",
        "Thất bại\nprivate",
        "A" * 65,
    ],
)
def test_unmapped_tpe_status_fails_closed_for_unsafe_or_unbounded_text(
    unsafe_status: str,
):
    report = _verifier_module().verify_raw_ticket_dimensions(
        [
            _ticket_trace(
                "privacy-trace",
                "privacy-session",
                1,
                "2026-07-21T01:00:00Z",
                tpe=f"-217 {unsafe_status}",
            )
        ],
        load_taxonomy(TAXONOMY_V2),
    )

    if unsafe_status == "user 550e8400-e29b-41d4-a716-446655440000":
        assert report["tpe_present_count"] == 0
        assert report["coverage_tpe"] == 0.0
        assert report["unmapped_tpe_codes"] == []
    else:
        assert report["unmapped_tpe_codes"] == [
            {"code": "-217", "status": None, "count": 1}
        ]
    assert unsafe_status not in _nested_strings(report)


@pytest.mark.parametrize(
    "allowed_status",
    ["Thất bại", "Đang xử lý", "Bị từ chối"],
)
def test_unmapped_tpe_status_preserves_only_source_backed_operational_values(
    allowed_status: str,
):
    report = _verifier_module().verify_raw_ticket_dimensions(
        [
            _ticket_trace(
                "allowed-status-trace",
                "allowed-status-session",
                1,
                "2026-07-21T01:00:00Z",
                tpe=f"-217 {allowed_status}",
            )
        ],
        load_taxonomy(TAXONOMY_V2),
    )

    assert report["unmapped_tpe_codes"] == [
        {"code": "-217", "status": allowed_status, "count": 1}
    ]


def test_unsafe_tpe_codes_do_not_satisfy_coverage_or_serialize_phone_and_uuid():
    phone = "0901234567"
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    raw = [
        _ticket_trace(
            "phone-code-trace",
            "phone-code-session",
            1,
            "2026-07-21T01:00:00Z",
            tpe=f"{phone} Thất bại",
        ),
        _ticket_trace(
            "uuid-code-trace",
            "uuid-code-session",
            1,
            "2026-07-21T02:00:00Z",
            tpe=f"{uuid} Thất bại",
        ),
    ]
    taxonomy = load_taxonomy(TAXONOMY_V2)
    report = _verifier_module().verify_raw_ticket_dimensions(raw, taxonomy)
    reversed_report = _verifier_module().verify_raw_ticket_dimensions(
        list(reversed(raw)),
        taxonomy,
    )

    assert report == reversed_report
    assert report["ticket_count"] == 2
    assert report["tpe_present_count"] == 0
    assert report["coverage_tpe"] == 0.0
    assert report["unmapped_tpe_codes"] == []
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert phone not in serialized
    assert uuid not in serialized
    assert phone not in _nested_strings(report)
    assert uuid not in _nested_strings(report)


@pytest.mark.parametrize(
    "tpe_value",
    [
        "090 1234567 Thất bại",
        "84 901234567 Thất bại",
        "090\u00a0123-4567 Thất bại",
        "090 (123).4567 Thất bại",
        "-217 ０９０１２３４５６７",
        "-217 ٠٩٠١٢٣٤٥٦٧",
        "-217 ０٩０\u200b١２3٤５6٧",
        "-217 090\ufe0f1234567",
        "-217 090\ufe0e1234567",
        "-217 090\u034f1234567",
        "-217 0a9b0c1d2e3f4g5h6i7",
    ],
    ids=(
        "local-spaces",
        "country-spaces",
        "nbsp-hyphen",
        "parentheses-dot",
        "full-width-status",
        "arabic-indic-status",
        "mixed-script-zero-width-status",
        "emoji-variation-selector",
        "text-variation-selector",
        "combining-grapheme-joiner",
        "arbitrary-letter-obfuscation",
    ),
)
def test_formatted_vietnamese_phone_in_reconstructed_tpe_value_fails_closed(
    tpe_value: str,
):
    raw = [
        _ticket_trace(
            "formatted-phone-trace",
            "formatted-phone-session",
            1,
            "2026-07-21T01:00:00Z",
            tpe=tpe_value,
        )
    ]
    taxonomy = load_taxonomy(TAXONOMY_V2)

    report = _verifier_module().verify_raw_ticket_dimensions(raw, taxonomy)
    repeated = _verifier_module().verify_raw_ticket_dimensions(raw, taxonomy)

    assert report == repeated
    assert report["ticket_count"] == 1
    assert report["tpe_present_count"] == 0
    assert report["coverage_tpe"] == 0.0
    assert report["unmapped_tpe_codes"] == []


class ReadOnlyVerifierClient:
    def __init__(self, traces: list[dict]) -> None:
        self.traces = traces
        self.bounds: list[tuple[datetime, datetime]] = []
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

    def list_observations(self, _trace_id: str):
        raise AssertionError("dimension verifier must not read observations")

    def ingest_events(self, _events):
        raise AssertionError("dimension verifier must not write scores")

    def delete_score(self, _score_id):
        raise AssertionError("dimension verifier must not delete scores")


def test_verify_dimensions_ignores_retired_runtime_backfill_for_p0(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    backfill = runtime / "dimension_backfill.json"
    backfill.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-07-31T03:00:00Z",
                "source": "freshdesk_api_v2",
                "records": [
                    {
                        "ticket_id": "145665",
                        "cf_category": "Thanh toán-IBFT",
                        "cf_m_li_tpe": "-217 Thất bại",
                        "last_attempt_at": "2026-07-31T03:00:00Z",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    backfill.chmod(0o600)
    client = ReadOnlyVerifierClient(
        [
            _ticket_trace(
                "raw-missing",
                "145665",
                0,
                "2026-07-25T01:00:00Z",
                entry_point="tranxdetail",
            )
        ]
    )
    monkeypatch.setattr("weekly_cs_report.cli.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: client)

    exit_code = main(
        [
            "verify-dimensions",
            "--require-p0",
            "--weeks",
            "2",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 1
    assert report["coverage_issue_category"] == 0.0
    assert report["coverage_tpe"] == 0.0
    assert report["p0_pass"] is False
    assert RETIRED_DIMENSION_REPORT_KEYS.isdisjoint(report)


@pytest.mark.parametrize(
    "argv",
    [
        [
            "--weeks",
            "2",
            "--include-current-wtd",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
            "verify-dimensions",
        ],
        [
            "verify-dimensions",
            "--weeks",
            "2",
            "--include-current-wtd",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ],
    ],
    ids=("options-before-command", "options-after-command"),
)
def test_verify_dimensions_cli_is_read_only_prints_one_safe_json_and_writes_no_artifacts(
    argv: list[str],
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    client = ReadOnlyVerifierClient(
        [
            _ticket_trace(
                "cli-trace",
                "cli-session",
                6,
                "2026-07-25T01:00:00Z",
                issue_category="Thanh toán-IBFT",
                tpe="-217 Thất bại",
            )
        ]
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: client)
    monkeypatch.chdir(tmp_path)

    exit_code = main(argv)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "traces_fetched": 1,
        "traces_deduplicated": 1,
        "invalid_trace_count": 0,
        "ticket_count": 1,
        "trace_issue_category_present_count": 1,
        "trace_tpe_present_count": 1,
        "issue_category_present_count": 1,
        "tpe_present_count": 1,
        "coverage_issue_category": 1.0,
        "coverage_tpe": 1.0,
        "p0_issue_category_pass": True,
        "p0_tpe_pass": True,
        "p0_pass": True,
        "applicable_population_definition": "entry_point == tranxdetail",
        "applicable_ticket_count": 0,
        "applicable_tpe_present": 0,
        "coverage_tpe_applicable": 0.0,
        "non_applicable_ticket_count": 1,
        "entry_point_absent_count": 0,
        "entry_point_null_string_count": 0,
        "entry_point_invalid_type_count": 0,
        "diagnostic_uninspectable_ticket_count": 0,
        "category_gap_by_entry_point": {},
        "unmapped_tpe_codes": [
            {"code": "-217", "status": "Thất bại", "count": 1}
        ],
    }
    assert client.bounds == [
        (
                datetime(2026, 6, 28, 17, tzinfo=timezone.utc),
            datetime(2026, 7, 29, 5, tzinfo=timezone.utc),
        )
    ]
    assert client.closed is True
    assert not (tmp_path / "artifacts").exists()


def test_verify_dimensions_require_p0_returns_zero_after_one_safe_passing_report(
    monkeypatch,
    capsys,
):
    client = ReadOnlyVerifierClient(
        [
            _ticket_trace(
                "cli-p0-pass-trace",
                "cli-p0-pass-session",
                0,
                "2026-07-25T01:00:00Z",
                issue_category="Thanh toán-IBFT",
                tpe="-217 Thất bại",
                entry_point="tranxdetail",
            )
        ]
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: client)

    exit_code = main(
        [
            "verify-dimensions",
            "--require-p0",
            "--weeks",
            "2",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out)["p0_pass"] is True


@pytest.mark.parametrize(
    ("require_p0", "expected_exit_code"),
    [(True, 1), (False, 0)],
    ids=("required-gate-fails", "default-diagnostic-remains-zero"),
)
def test_verify_dimensions_p0_failure_prints_one_safe_report_and_only_require_p0_fails(
    require_p0,
    expected_exit_code,
    monkeypatch,
    capsys,
):
    client = ReadOnlyVerifierClient(
        [
            _ticket_trace(
                "cli-p0-miss-trace",
                "cli-p0-miss-session",
                0,
                "2026-07-25T01:00:00Z",
                issue_category="Thanh toán-IBFT",
                entry_point="tranxdetail",
            )
        ]
    )
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: client)
    argv = [
        "verify-dimensions",
        "--weeks",
        "2",
        "--as-of",
        "2026-07-29T12:00:00+07:00",
    ]
    if require_p0:
        argv.insert(1, "--require-p0")

    exit_code = main(argv)
    captured = capsys.readouterr()

    assert exit_code == expected_exit_code
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out)["p0_pass"] is False


def test_parser_supports_verify_dimensions_without_changing_existing_commands():
    after = build_parser().parse_args(
        [
            "verify-dimensions",
            "--weeks",
            "3",
            "--include-current-wtd",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
        ]
    )
    before = build_parser().parse_args(
        [
            "--weeks",
            "3",
            "--include-current-wtd",
            "--as-of",
            "2026-07-29T12:00:00+07:00",
            "verify-dimensions",
        ]
    )

    assert vars(before) == vars(after) == {
        "weeks": 3,
        "include_current_wtd": True,
        "as_of": AS_OF,
        "artifact_root": Path("artifacts"),
        "week_definition": "mon_sun",
        "command": "verify-dimensions",
        "require_p0": False,
    }
    assert build_parser().parse_args(["verify-dimensions", "--require-p0"]).require_p0 is True
    assert build_parser().parse_args([]).command == "dry-run"
    for command in ("sync", "canary"):
        with pytest.raises(SystemExit):
            build_parser().parse_args([command])


def test_run_config_uses_v2_taxonomy_default():
    config = RunConfig(as_of=AS_OF)

    assert config.taxonomy_path == PROJECT_ROOT / "config" / "taxonomy.v2.json"
