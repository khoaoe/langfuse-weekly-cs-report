from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from weekly_cs_report.categories import (
    extract_dimensions,
    load_taxonomy,
)
from weekly_cs_report.models import TraceRecord


TAXONOMY_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v1.json"
TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


@pytest.fixture()
def taxonomy():
    return load_taxonomy(TAXONOMY_PATH)


@pytest.fixture()
def taxonomy_v2():
    return load_taxonomy(TAXONOMY_V2_PATH)


def turn0(input_data: object) -> TraceRecord:
    return TraceRecord(
        id="turn-0",
        session_id="session-1",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        turn=0,
        input_data=input_data,
        output_data={},
        environment="default",
    )


def test_v2_taxonomy_migrates_all_28_v1_mappings_without_inventing_unknown_codes(
    taxonomy_v2,
):
    expected_projection = (
        ("1", ("1",), 1, "SUCCESSFUL"),
        ("-383", (), 2, "PENDING"),
        ("-375", (), 6, "FAILED_REFUNDED"),
        ("-365", ("-1006",), 7, "FAILED_NFC"),
        ("-374", (), 8, "REFUNDING"),
        ("-376", (), 8, "REFUNDING"),
        ("-356", (), 9, "SECURITY_BLOCK"),
        ("-365", ("-1013",), 10, "FAILED_FACE_AUTH"),
        ("-365", ("-1015",), 11, "FAILED_FACE_AUTH"),
        ("-365", ("-1012",), 12, "FAILED_KYC"),
        ("-365", ("-1021",), 13, "FAILED_OTP"),
        ("-365", ("-1023",), 14, "FAILED_SMART_OTP"),
        ("-365", ("-1020",), 15, "WAITING_NFC_REVIEW"),
        ("-365", ("-1003", "-1000"), 16, "SYSTEM_ERROR"),
        ("-365", ("-1011",), 17, "WAITING_KYC_REVIEW"),
        ("-365", ("-1009",), 18, "FAILED_KYC"),
        ("-365", ("-1005",), 19, "FAILED_NFC"),
        ("-365", ("-1002",), 20, "FAILED_NFC"),
        ("-365", ("-1024",), 21, "SYSTEM_ERROR"),
        ("-348", ("210800",), 22, "INVESTIGATING"),
        ("-348", ("212025", "210001"), 23, "SECURITY_BLOCK"),
        ("-348", ("210002", "210099"), 24, "SUSPICIOUS_DEVICE"),
        ("-244", ("212010",), 25, "POLICY_BLOCK"),
        ("-244", ("700212",), 26, "LIMIT_EXCEEDED"),
        ("-244", ("210808",), 27, "SECURITY_BLOCK"),
        ("-6038", (), 28, "FAILED_OTP"),
        ("-344", (), 29, "BANK_LIMIT_EXCEEDED"),
        ("-357", (), 30, "RISK_BLOCK"),
    )

    assert taxonomy_v2.version == "v2"
    assert len(taxonomy_v2.transfer_texts) == 2
    assert taxonomy_v2.transfer_text == taxonomy_v2.transfer_texts[0]
    assert tuple(
        (
            mapping["code"],
            mapping["steps"],
            mapping["case"],
            mapping["status"],
        )
        for mapping in taxonomy_v2.tpe_mappings
    ) == expected_projection
    assert not {
        "-217",
        "-380",
        "-993",
        "-268",
        "-369",
        "-1442",
        "-333",
        "-367",
    } & {mapping["code"] for mapping in taxonomy_v2.tpe_mappings}
    assert "off_topic" in taxonomy_v2.guardrail_allowed_values
    assert "tone_check_error" in taxonomy_v2.guardrail_allowed_values
    assert taxonomy_v2.guardrail_compliant_values == (
        "input_compliant",
        "output_compliant",
    )
    assert not hasattr(taxonomy_v2, "tpe_applicable_entry_points")


def test_v2_taxonomy_rejects_retired_tpe_applicability_contract(tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["tpe"]["applicable_entry_points"] = ["tranxdetail"]
    path = tmp_path / "invalid-tpe-applicability.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_extract_dimensions_keeps_private_meta_code_but_ignores_meta_step_result(
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Thông tin thêm": {
                            "category": "Thanh toán-IBFT",
                            "sub_source": "tranxdetail",
                        },
                        "App": "241 - Chuyển Tiền ATM",
                        "Product Code": "TF007 - IBFT money transfer",
                        "Kênh thanh toán": "38 - TK Zalo Pay",
                        "Mã lỗi TPE": "-244 Bị từ chối",
                        "Step result": "-1|20|700212|Mô tả nội bộ",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.issue_category == "Thanh toán-IBFT"
    assert dimensions.entry_point == "tranxdetail"
    assert dimensions.app == "241 - Chuyển Tiền ATM"
    assert dimensions.app_code == 241
    assert dimensions.product_code == "TF007 - IBFT money transfer"
    assert dimensions.payment_channel == "38 - TK Zalo Pay"
    assert dimensions.tpe_code == "-244"
    assert dimensions.tpe_status_raw == "Bị từ chối"
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None
    assert dimensions.tpe_signals == ()
    assert dimensions.skill is None
    assert dimensions.intent is None
    assert dimensions.guardrail_rule is None
    assert dimensions.escalation_guard_blocked is False


@pytest.mark.parametrize(
    "app",
    ["٢٤١ - Chuyển Tiền ATM", "２４１ - Chuyển Tiền ATM"],
    ids=("arabic-indic", "full-width"),
)
def test_extract_dimensions_does_not_coerce_unicode_numeric_app_code(
    app,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "App": app,
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.app == app
    assert dimensions.app_code is None


@pytest.mark.parametrize(
    "step_result",
    [
        "700212",
        "Mô tả không phải mã",
        "-1003",
        "-1|20|700212|Mô tả nội bộ",
    ],
)
def test_extract_dimensions_never_interprets_meta_step_result(
    step_result,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-217 Thất bại",
                        "Step result": step_result,
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_step is None
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_case is None


@pytest.mark.parametrize(
    "tpe_value",
    [
        "0901234567 Thất bại",
        "090 1234567",
        "84 901234567",
        "-217 ０９０\u200b١２3٤５6٧",
    ],
    ids=(
        "contiguous-local",
        "formatted-local",
        "formatted-country-code",
        "mixed-unicode-obfuscation",
    ),
)
def test_extract_dimensions_rejects_phone_shaped_raw_tpe_values(
    tpe_value,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": tpe_value,
                        "Step result": "-1|20|700212|Mô tả nội bộ",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code is None
    assert dimensions.tpe_status_raw is None
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


def test_extract_dimensions_rejects_tpe_code_longer_than_six_ascii_digits(
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "1234567 Trạng thái",
                        "Step result": "700212",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code is None
    assert dimensions.tpe_status_raw is None
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


@pytest.mark.parametrize(
    "step_value",
    [
        "0901234567",
        "-1|20|0901234567|Mô tả nội bộ",
        "1234567",
        "-1|20|-1234567|Mô tả nội bộ",
    ],
    ids=(
        "phone-one-segment",
        "phone-pipe-index-two",
        "seven-digits-one-segment",
        "seven-digits-pipe-index-two",
    ),
)
def test_extract_dimensions_rejects_tpe_steps_outside_six_digit_domain(
    step_value,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-217 Thất bại",
                        "Step result": step_value,
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code == "-217"
    assert dimensions.tpe_status_raw == "Thất bại"
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


@pytest.mark.parametrize(
    ("tpe_value", "step_value"),
    [
        ("-٢١٧ Thất bại", "٧٠٠٢١٢"),
        ("-２１７ Thất bại", "７００２１２"),
    ],
    ids=("arabic-indic", "full-width"),
)
def test_extract_dimensions_rejects_unicode_numeric_lookalike_tpe_codes(
    tpe_value,
    step_value,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": tpe_value,
                        "Step result": step_value,
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code is None
    assert dimensions.tpe_status_raw is None
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


@pytest.mark.parametrize(
    "step_value",
    ["٧٠٠٢١٢", "７００２１２"],
    ids=("arabic-indic", "full-width"),
)
def test_extract_dimensions_rejects_unicode_numeric_lookalike_tpe_steps(
    step_value,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-217 Thất bại",
                        "Step result": step_value,
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code == "-217"
    assert dimensions.tpe_status_raw == "Thất bại"
    assert dimensions.tpe_step is None


def test_extract_dimensions_does_not_map_meta_tpe_to_case_or_canonical_status(
    taxonomy_v2,
):
    configured = replace(
        taxonomy_v2,
        tpe_mappings=(
            {"code": "-244", "steps": (), "case": 999, "status": "WILDCARD"},
            {
                "code": "-244",
                "steps": ("700212",),
                "case": 26,
                "status": "LIMIT_EXCEEDED",
            },
        ),
    )

    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-244 Bị từ chối",
                        "Step result": "-1|20|700212|Mô tả nội bộ",
                    }
                }
            }
        ),
        configured,
    )

    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None
    assert dimensions.tpe_status_canonical is None


def test_extract_dimensions_does_not_apply_wildcard_taxonomy_mapping(taxonomy_v2):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-383 Đang xử lý",
                        "Step result": "-1|20|999999|Mô tả nội bộ",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code == "-383"
    assert dimensions.tpe_status_raw == "Đang xử lý"
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


def test_extract_dimensions_passthrough_keeps_unmapped_code_and_raw_status(taxonomy_v2):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": "-217 Thất bại",
                        "Step result": "700212",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code == "-217"
    assert dimensions.tpe_status_raw == "Thất bại"
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_case is None


@pytest.mark.parametrize("tpe_value", [None, "", "   ", 217, "mã-không-hợp-lệ Thất bại"])
def test_extract_dimensions_empty_or_unsafe_tpe_drops_all_tpe_fields(
    tpe_value,
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Mã lỗi TPE": tpe_value,
                        "Step result": "-1|20|700212|Mô tả nội bộ",
                    }
                }
            }
        ),
        taxonomy_v2,
    )

    assert dimensions.tpe_code is None
    assert dimensions.tpe_status_raw is None
    assert dimensions.tpe_status_canonical is None
    assert dimensions.tpe_step is None
    assert dimensions.tpe_case is None


def test_extract_dimensions_uses_fallbacks_and_does_not_serialize_description_or_pii(
    taxonomy_v2,
):
    dimensions = extract_dimensions(
        turn0(
            {
                "other_info": {
                    "meta": {
                        "Thông tin thêm": {
                            "category": "",
                            "sub_source": None,
                            "private": "0901234567",
                        },
                        "App": "không có code đầu",
                        "Product Code": "N/A",
                        "Mã lỗi TPE": "-217 Thất bại",
                        "Step result": "-1|20|700212|Nội dung riêng tư 0901234567",
                        "Mô tả": "Nội dung riêng tư 0901234567",
                        "UserID": "private-user-id",
                    }
                }
            }
        ),
        taxonomy_v2,
    )
    serialized = json.dumps(asdict(dimensions), ensure_ascii=False, sort_keys=True)

    assert dimensions.issue_category == "Không xác định"
    assert dimensions.entry_point == "Không xác định"
    assert dimensions.app == "không có code đầu"
    assert dimensions.app_code is None
    assert dimensions.product_code == "N/A"
    assert dimensions.payment_channel == "Không xác định"
    assert "Nội dung riêng tư" not in serialized
    assert "0901234567" not in serialized
    assert "private-user-id" not in serialized
    assert "Mô tả" not in serialized


def test_v2_taxonomy_loader_rejects_malformed_exact_shapes_and_types(tmp_path):
    valid = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    malformed: list[dict[str, object]] = []

    root_extra = deepcopy(valid)
    root_extra["unsupported"] = True
    malformed.append(root_extra)

    bad_meta_path = deepcopy(valid)
    bad_meta_path["dimensions"]["app"]["meta_path"] = "App"
    malformed.append(bad_meta_path)

    bad_fallback = deepcopy(valid)
    bad_fallback["dimensions"]["app"]["fallback"] = None
    malformed.append(bad_fallback)

    bad_pipe_index = deepcopy(valid)
    bad_pipe_index["tpe"]["step_pipe_index"] = True
    malformed.append(bad_pipe_index)

    bad_steps = deepcopy(valid)
    bad_steps["tpe"]["mappings"][0]["steps"] = "1"
    malformed.append(bad_steps)

    missing_guardrail_field = deepcopy(valid)
    del missing_guardrail_field["guardrail"]["blocked_fields"]
    malformed.append(missing_guardrail_field)

    bad_skill = deepcopy(valid)
    bad_skill["skills"]["prefix_strip"] = 7
    malformed.append(bad_skill)

    bad_intent_count = deepcopy(valid)
    bad_intent_count["intent"]["min_occurrences"] = True
    malformed.append(bad_intent_count)

    bad_intent_pattern = deepcopy(valid)
    bad_intent_pattern["intent"]["pattern"] = "["
    malformed.append(bad_intent_pattern)

    for index, raw in enumerate(malformed):
        path = tmp_path / f"malformed-{index}.json"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError):
            load_taxonomy(path)


@pytest.mark.parametrize(
    ("section", "field", "unsafe_value"),
    [
        ("issue_category", "meta_path", ["UserID"]),
        ("issue_category", "meta_path", ["Thông tin thêm", "Mô tả"]),
        ("app", "meta_path", ["app"]),
        ("product_code", "meta_path", ["Product"]),
        ("entry_point", "meta_path", ["Thông tin thêm", "source"]),
        ("payment_channel", "meta_path", ["Kênh"]),
    ],
)
def test_v2_taxonomy_loader_rejects_wrong_or_deny_listed_dimension_paths(
    section,
    field,
    unsafe_value,
    tmp_path,
):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["dimensions"][section][field] = unsafe_value
    path = tmp_path / "unsafe-dimension-path.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("code_meta_key", "UserID"),
        ("code_meta_key", "Mã TPE"),
        ("step_meta_key", "Mô tả"),
        ("step_meta_key", "Step"),
        ("step_pipe_index", 0),
        ("step_pipe_index", 3),
        ("step_pipe_index", 2.0),
    ],
)
def test_v2_taxonomy_loader_rejects_wrong_or_deny_listed_tpe_selectors(
    field,
    unsafe_value,
    tmp_path,
):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["tpe"][field] = unsafe_value
    path = tmp_path / "unsafe-tpe-selector.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_v2_taxonomy_loader_rejects_duplicate_step_within_one_mapping(tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["tpe"]["mappings"][0]["steps"] = ["1", "1"]
    path = tmp_path / "duplicate-step-in-mapping.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_v2_taxonomy_loader_rejects_overlapping_code_step_across_mappings(tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["tpe"]["mappings"].append(
        {"code": "1", "steps": ["1", "2"], "case": 99, "status": "DUPLICATE"}
    )
    path = tmp_path / "overlapping-code-step.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_v2_taxonomy_loader_rejects_multiple_wildcards_for_one_code(tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    raw["tpe"]["mappings"].append(
        {"code": "-383", "steps": [], "case": 99, "status": "DUPLICATE"}
    )
    path = tmp_path / "duplicate-wildcard.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_v2_taxonomy_loader_rejects_duplicate_transfer_templates(tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    template = raw["transfer"]["semantic_texts"][0]
    raw["transfer"]["semantic_texts"] = [template, template]
    path = tmp_path / "duplicate-transfer-template.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="semantic_texts must not contain duplicates"):
        load_taxonomy(path)


@pytest.mark.parametrize(
    "target",
    [
        "transfer",
        "dimension_path",
        "dimension_fallback",
        "mapping_status",
        "guardrail_list",
        "skill",
        "intent_pattern",
        "intent_label",
    ],
)
def test_v2_taxonomy_loader_rejects_whitespace_only_strings(target, tmp_path):
    raw = json.loads(TAXONOMY_V2_PATH.read_text(encoding="utf-8"))
    if target == "transfer":
        raw["transfer"]["semantic_texts"] = [" \t"]
    elif target == "dimension_path":
        raw["dimensions"]["app"]["meta_path"] = ["  "]
    elif target == "dimension_fallback":
        raw["dimensions"]["app"]["fallback"] = "\n"
    elif target == "mapping_status":
        raw["tpe"]["mappings"][0]["status"] = " "
    elif target == "guardrail_list":
        raw["guardrail"]["violation_rules"] = [" "]
    elif target == "skill":
        raw["skills"]["prefix_strip"] = "\t"
    elif target == "intent_pattern":
        raw["intent"]["pattern"] = " "
    else:
        raw["intent"]["other_label"] = "  "
    path = tmp_path / f"whitespace-{target}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        load_taxonomy(path)


def test_loaded_v2_dimension_paths_are_immutable(taxonomy_v2):
    with pytest.raises(TypeError):
        taxonomy_v2.dimension_paths["app"] = ("UserID",)


def test_loaded_v2_dimension_fallbacks_are_immutable(taxonomy_v2):
    with pytest.raises(TypeError):
        taxonomy_v2.dimension_fallbacks["app"] = "private"
