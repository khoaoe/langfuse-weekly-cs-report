from __future__ import annotations

import importlib

import pytest


def _masker_module():
    try:
        return importlib.import_module("weekly_cs_report.reopen_masker")
    except ModuleNotFoundError:
        pytest.fail("reopen_masker is not implemented")


def test_masks_only_exact_values_from_the_four_known_meta_keys():
    masker = _masker_module()
    meta = {
        "UserID": "user-145665",
        "App user": "app-user-private",
        "TransID": "transaction-private",
        "Số điện thoại người dùng": "0901234567",
        "Ghi chú": "must-not-drive-masking",
    }
    text = (
        "user-145665 app-user-private transaction-private 0901234567 "
        "must-not-drive-masking"
    )

    assert masker.mask_reopen_text(text, meta) == (
        "[PII] [PII] [PII] [PII] must-not-drive-masking"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mã 123456789", "Mã [PII]"),
        ("Mã 12345678901234567890", "Mã [PII]"),
        ("Email person.name+tag@example.com", "Email [PII]"),
        ("Mở https://example.com/private?a=1", "Mở [PII]"),
        ("Mở WWW.example.com/path", "Mở [PII]"),
        ("Thẻ 4111 1111 1111 1111", "Thẻ [PII]"),
        ("Thẻ 5500-0000-0000-0004", "Thẻ [PII]"),
    ],
)
def test_masks_deterministic_pattern_classes(raw: str, expected: str):
    masker = _masker_module()

    assert masker.mask_reopen_text(raw, {}) == expected


def test_digit_bounds_do_not_mask_out_of_scope_sequences():
    masker = _masker_module()

    assert masker.mask_reopen_text("12345678 123456789012345678901", {}) == (
        "12345678 123456789012345678901"
    )


def test_applies_a_hard_output_length_ceiling():
    masker = _masker_module()
    secret = "person@example.com"
    text = ("x" * masker.MAX_REOPEN_TEXT_LENGTH) + secret

    masked = masker.mask_reopen_text(text, {})

    assert len(masked) <= masker.MAX_REOPEN_TEXT_LENGTH
    assert secret not in masked


def test_does_not_guess_person_names_or_emit_raw_text_to_logs(caplog):
    masker = _masker_module()
    raw = "Nguyễn Văn An cần kiểm tra giao dịch"

    first = masker.mask_reopen_text(raw, {})
    second = masker.mask_reopen_text(raw, {})

    assert first == second == raw
    assert raw not in caplog.text
