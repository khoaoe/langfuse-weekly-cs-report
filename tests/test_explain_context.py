from __future__ import annotations

from pathlib import Path

import pytest

from weekly_cs_report import explain_context as ec

CONFIG_PATH = Path(__file__).parents[1] / "config" / "explain_context.v1.json"


@pytest.fixture()
def config() -> ec.ExplainConfig:
    return ec.load_explain_config(CONFIG_PATH)


def test_skill_for_app_resolves_known_app(config):
    assert ec.skill_for_app(config, "452") == "withdraw"
    assert ec.skill_for_app(config, "241") == "interbank-fund-transfer"


def test_skill_for_app_unknown_returns_none(config):
    assert ec.skill_for_app(config, "999999") is None
    assert ec.skill_for_app(config, None) is None


def test_skill_for_app_matches_real_compound_app_field(config):
    # Real meta.App values look like "241 - Chuyển Tiền ATM", not the bare
    # "241" the config stores -- ticket 7090152 showed coverage.expected_skill
    # always resolving to None in production because of this.
    assert ec.skill_for_app(config, "241 - Chuyển Tiền ATM") == "interbank-fund-transfer"
    assert ec.skill_for_app(config, "452 - Rút tiền") == "withdraw"
    assert ec.skill_for_app(config, "999999 - Unknown App") is None


def test_mask_free_text_only_masks_nine_plus_digit_runs():
    assert ec.mask_free_text("ma so 12345678 con 8 chu so") == "ma so 12345678 con 8 chu so"
    masked = ec.mask_free_text("giao dich 123456789 loi")
    assert "123456789" not in masked
    assert masked.count("*") == 9


def test_build_ticket_facts_splits_value_vs_presence(config):
    meta = {
        "App": "452",
        "Mô tả": "khach bao loi 123456789012",
        "UserID": "u-1",
        "Tên ngân hàng": "Vietcombank",
    }
    facts = ec.build_ticket_facts(config, meta, "Rut tien loi")
    by_label = {f.label: f for f in facts}
    # withdraw's field list: Mô tả + App + TransID + UserID (+ title always).
    assert set(by_label) == {"Mô tả", "App", "TransID", "UserID", "title"}
    assert by_label["Mô tả"].present is True
    assert "123456789012" not in by_label["Mô tả"].value
    assert by_label["App"].value == "452"
    assert by_label["TransID"].present is False


def test_build_ticket_facts_masks_transaction_id_in_title():
    # Ticket 7090152's real title carried the raw 15-digit transaction id
    # verbatim ("... Mã giao dịch: 260813002120041 ..."). "title" is
    # customer/Freshdesk-subject free text just like "Mô tả" and must get
    # the same masking, not just presence-only fields.
    config = ec.load_explain_config(CONFIG_PATH)
    facts = ec.build_ticket_facts(
        config, {"App": "241"}, "Giao dich loi ( Ma giao dich: 260813002120041 )"
    )
    title = next(f for f in facts if f.label == "title")
    assert title.value is not None
    assert "260813002120041" not in title.value
    assert "*" in title.value


def test_build_ticket_facts_userid_shows_real_value_since_2026_08_20(config):
    # PO decision 2026-08-20: UserID/TransID/TransAppID/traceId/sessionId are no
    # longer masked on this internal dashboard's UI (phone/name/email/conversation
    # text remain hidden -- those weren't reversed). UserID moved from
    # field_policy.presence to field_policy.value, so it now carries a real value.
    meta = {"App": "999999", "UserID": "u-secret-1"}
    facts = ec.build_ticket_facts(config, meta, "")
    userid = next(f for f in facts if f.label == "UserID")
    assert userid.present is True
    assert userid.value == "u-secret-1"


def test_build_ticket_facts_missing_field_is_absent(config):
    facts = ec.build_ticket_facts(config, {"App": "999999"}, "")
    userid = next(f for f in facts if f.label == "UserID")
    assert userid.present is False
    assert userid.value is None


def test_humanize_tool_known_tools(config):
    nhan, value, failed = ec.humanize_tool(
        config, "tool:calculate_time_difference__withdraw", {"hours": 79}
    )
    assert (nhan, value, failed) == ("Thời gian giao dịch", "79 giờ", False)

    nhan, value, failed = ec.humanize_tool(
        config, "tool:load_skill_reference__withdraw", {"filename": "sub-skill-C.md"}
    )
    assert (nhan, value, failed) == ("Đọc kịch bản", "sub-skill-C.md", False)

    # Real payload shape (ticket 7090152): the tool's own "status" field is
    # read directly, no taxonomy re-derivation.
    nhan, value, failed = ec.humanize_tool(
        config,
        "tool:get_transaction_processing_engine_data",
        {"transstatus": -374, "stepresult": "-9999", "status": "REFUNDING"},
    )
    assert nhan == "Trạng thái giao dịch"
    assert value == "REFUNDING"
    assert failed is False


def test_humanize_tool_error_envelope_never_leaks_raw(config):
    nhan, value, failed = ec.humanize_tool(
        config, "tool:get_bank_name", {"error": "NO_DATA", "message": "khong tim thay"}
    )
    assert failed is True
    assert value == "Không tra được dữ liệu"
    assert nhan == "Ngân hàng"


def test_humanize_tool_unknown_tool_never_hidden(config):
    nhan, value, failed = ec.humanize_tool(config, "tool:brand_new_tool", {"foo": "bar"})
    assert nhan == "brand_new_tool"
    assert value == "đã tra cứu"
    assert failed is False

    nhan, value, failed = ec.humanize_tool(
        config, "tool:brand_new_tool", {"info": "NO_DATA", "message": "x"}
    )
    assert failed is True
    assert value == "Không tra được dữ liệu"
