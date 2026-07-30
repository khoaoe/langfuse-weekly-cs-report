from __future__ import annotations

import json
import stat
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.cli import (
    PROJECT_ROOT,
    TARGET_BASE_URL,
    EnvironmentSettings,
    main,
    run_dimension_verification,
)
from weekly_cs_report.dimension_backfill import (
    DimensionBackfill,
    DimensionBackfillStore,
    DimensionBackfillStoreError,
    FRESHDESK_BASE_URL,
    FreshdeskDimensionAPIError,
    FreshdeskDimensionClient,
    FreshdeskDimensionResponseError,
    FreshdeskFieldContractError,
    apply_dimension_backfill,
    backfill_ticket_dimensions,
)
from weekly_cs_report.dimension_verifier import verify_raw_ticket_dimensions
from weekly_cs_report.models import TraceRecord
from tests.fixtures.traces import trace


VALID_CHOICES = ["Thanh toán-IBFT", "Chăm sóc khách hàng"]
VALID_FIELDS = [
    {
        "name": "cf_category",
        "label": "Category Chatbot",
        "type": "custom_dropdown",
        "choices": VALID_CHOICES,
    },
    {
        "name": "cf_m_li_tpe",
        "label": "Mã lỗi TPE",
        "type": "custom_text",
    },
]
FIELD_CONTRACT_ERROR = "Freshdesk dimension field contract is unavailable"


def _client(handler):
    return FreshdeskDimensionClient(
        FRESHDESK_BASE_URL,
        "test-secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )


def _validated_client(ticket_payload: object, requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        return httpx.Response(200, json=ticket_payload, request=request)

    client = _client(handler)
    client.validate_field_contract()
    return client


def test_fetch_requires_successful_field_contract_before_ticket_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={}, request=request)

    client = _client(handler)

    with pytest.raises(FreshdeskFieldContractError) as captured:
        client.fetch_ticket_dimensions("6971338")

    assert str(captured.value) == FIELD_CONTRACT_ERROR
    assert requests == []


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        [],
        [
            {
                "name": "cf_category",
                "label": "Category Chatbot",
                "type": "custom_dropdown",
                "choices": ["duplicate", "duplicate"],
            },
            VALID_FIELDS[1],
        ],
        [
            {
                "name": "cf_category",
                "label": "Category Chatbot",
                "type": "custom_dropdown",
                "choices": ["valid", 7],
            },
            VALID_FIELDS[1],
        ],
        [
            {
                "name": "cf_category",
                "label": "Wrong label",
                "type": "custom_dropdown",
                "choices": ["valid"],
            },
            VALID_FIELDS[1],
        ],
    ],
)
def test_field_contract_rejects_malformed_or_incompatible_fields(payload: object):
    private_marker = "private-contract-response-0901234567"

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload, request=request)
        return httpx.Response(200, json={"fields": payload, "private": private_marker}, request=request) if isinstance(payload, dict) else httpx.Response(200, json=payload, request=request)

    client = _client(handler)

    with pytest.raises(FreshdeskFieldContractError) as captured:
        client.validate_field_contract()
    with pytest.raises(FreshdeskFieldContractError):
        client.fetch_ticket_dimensions("6971338")

    assert str(captured.value) == FIELD_CONTRACT_ERROR
    assert private_marker not in str(captured.value)


def test_field_contract_validation_is_atomic_when_tpe_field_is_invalid():
    requests: list[httpx.Request] = []
    fields = [
        VALID_FIELDS[0],
        {
            "name": "cf_m_li_tpe",
            "label": "Wrong TPE label",
            "type": "custom_text",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fields, request=request)

    client = _client(handler)

    with pytest.raises(FreshdeskFieldContractError):
        client.validate_field_contract()
    with pytest.raises(FreshdeskFieldContractError):
        client.fetch_ticket_dimensions("6971338")

    assert [request.url.path for request in requests] == [
        "/api/v2/ticket_fields"
    ]


@pytest.mark.parametrize(
    "unsafe_category",
    [
        "customer@example.test",
        "=HYPERLINK(\"https://private.example\")",
        "https://private.example/category",
        "unsafe\ncategory",
        "550e8400-e29b-41d4-a716-446655440000",
        "Khách ０９０\u200b١２3٤５6٧",
        "Nguyễn Văn An",
        "Tran Thi B",
        "account 123456789012",
        "account ١٢٣٤٥٦٧٨٩",
        "transaction 987654321",
    ],
)
def test_unsafe_category_choice_or_value_cannot_reach_store(
    tmp_path: Path, unsafe_category: str
):
    requests: list[httpx.Request] = []
    fields = [
        {**VALID_FIELDS[0], "choices": ["Thanh toán-IBFT", unsafe_category]},
        VALID_FIELDS[1],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fields, request=request)

    client = _client(handler)
    with pytest.raises(FreshdeskFieldContractError):
        client.validate_field_contract()
    with pytest.raises(FreshdeskFieldContractError):
        client.fetch_ticket_dimensions("6971338")

    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {
            "6971338": DimensionBackfill(
                ticket_id="6971338",
                issue_category=unsafe_category,
                tpe="1",
            )
        },
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    stored = json.loads(store.path.read_text(encoding="utf-8"))
    assert stored["records"][0]["cf_category"] is None
    assert unsafe_category not in store.path.read_text(encoding="utf-8")
    assert [request.url.path for request in requests] == [
        "/api/v2/ticket_fields"
    ]


def test_validated_client_uses_only_allowed_get_routes_and_retains_exact_choice():
    requests: list[httpx.Request] = []
    client = _validated_client(
        {
            "id": 6971338,
            "custom_fields": {
                "cf_category": "Thanh toán-IBFT",
                "cf_m_li_tpe": "-217 Thất bại",
                "cf_user_id": "private-user-id",
            },
        },
        requests,
    )

    result = client.fetch_ticket_dimensions("6971338")

    assert asdict(result) == {
        "ticket_id": "6971338",
        "issue_category": "Thanh toán-IBFT",
        "tpe": "-217 Thất bại",
    }
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/ticket_fields"),
        ("GET", "/api/v2/tickets/6971338"),
    ]
    assert client._client.follow_redirects is False


def test_validated_client_discards_category_outside_validated_choice_set():
    requests: list[httpx.Request] = []
    client = _validated_client(
        {
            "id": 6971338,
            "custom_fields": {
                "cf_category": "Safe but unapproved category",
                "cf_m_li_tpe": "1 Đang xử lý",
            },
        },
        requests,
    )

    assert client.fetch_ticket_dimensions("6971338").issue_category is None


@pytest.mark.parametrize("category", VALID_CHOICES)
def test_documented_category_examples_remain_safe_and_cacheable(category: str):
    requests: list[httpx.Request] = []
    client = _validated_client(
        {
            "id": 6971338,
            "custom_fields": {
                "cf_category": category,
                "cf_m_li_tpe": "1 Đang xử lý",
            },
        },
        requests,
    )

    assert client.fetch_ticket_dimensions("6971338").issue_category == category


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-217 Thất bại", "-217 Thất bại"),
        ("1 Đang xử lý", "1 Đang xử lý"),
        ("42 Bị từ chối", "42 Bị từ chối"),
        ("1 Thành công", "1"),
        ("-217 Thất bại | customer@example.test", "-217 Thất bại"),
        ("1 unknown customer suffix", "1"),
        ("=HYPERLINK(\"https://private.example\")", None),
        ("550e8400-e29b-41d4-a716-446655440000", None),
        ("1234567 Thất bại", None),
        ("1\nThất bại", None),
    ],
)
def test_tpe_sanitizer_retains_only_safe_code_and_approved_status(
    raw: str, expected: str | None
):
    requests: list[httpx.Request] = []
    client = _validated_client(
        {
            "id": 6971338,
            "custom_fields": {
                "cf_category": "Thanh toán-IBFT",
                "cf_m_li_tpe": raw,
            },
        },
        requests,
    )

    result = client.fetch_ticket_dimensions("6971338")

    assert result.tpe == expected
    assert raw not in repr(result) or raw == expected


def test_archived_fallback_and_terminal_tombstone_remain_after_contract_validation():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        return httpx.Response(404, json={}, request=request)

    client = _client(handler)
    client.validate_field_contract()

    assert client.fetch_ticket_dimensions("6971338") == DimensionBackfill(
        ticket_id="6971338", issue_category=None, tpe=None
    )
    assert [request.url.path for request in requests] == [
        "/api/v2/ticket_fields",
        "/api/v2/tickets/6971338",
        "/api/v2/tickets/archived/6971338",
    ]


def test_ticket_response_error_is_redacted_after_contract_validation():
    requests: list[httpx.Request] = []
    client = _validated_client(
        {"id": 6971338, "custom_fields": [], "private": "0901234567"},
        requests,
    )

    with pytest.raises(FreshdeskDimensionResponseError) as captured:
        client.fetch_ticket_dimensions("6971338")

    assert str(captured.value) == "Freshdesk ticket response is invalid"
    assert "0901234567" not in str(captured.value)


def test_ticket_get_retries_with_redacted_error_after_contract_validation():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        return httpx.Response(503, text="private-upstream-0901234567", request=request)

    client = _client(handler)
    client.validate_field_contract()

    with pytest.raises(FreshdeskDimensionAPIError) as captured:
        client.fetch_ticket_dimensions("6971338")

    assert str(captured.value) == "Freshdesk GET failed with status 503"
    assert len(requests) == 4


def test_store_is_fixed_to_private_runtime_directory_and_round_trips(tmp_path: Path):
    runtime = tmp_path / "runtime"
    store = DimensionBackfillStore(runtime)

    store.write(
        {
            "6971338": DimensionBackfill(
                ticket_id="6971338",
                issue_category="Thanh toán-IBFT",
                tpe="-217 Thất bại",
            )
        },
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert store.path == runtime / "dimension_backfill.json"
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.load() == {
        "6971338": DimensionBackfill(
            ticket_id="6971338",
            issue_category="Thanh toán-IBFT",
            tpe="-217 Thất bại",
        )
    }
    assert store.load_generated_at() == datetime(
        2026, 7, 29, 12, tzinfo=timezone.utc
    )
    assert not tuple(runtime.glob("*.tmp"))


def test_store_migrates_schema_v1_generated_at_to_per_record_attempts(
    tmp_path: Path,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = DimensionBackfillStore(runtime)
    legacy_generated_at = datetime(
        2026, 7, 28, 12, tzinfo=timezone.utc
    )
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-07-28T12:00:00Z",
                "source": "freshdesk_api_v2",
                "records": [
                    {
                        "ticket_id": "6971338",
                        "cf_category": None,
                        "cf_m_li_tpe": None,
                    },
                    {
                        "ticket_id": "6971339",
                        "cf_category": "Thanh toán-IBFT",
                        "cf_m_li_tpe": None,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    entries = store.load()
    attempts = store.load_last_attempt_at()

    assert attempts == {
        "6971338": legacy_generated_at,
        "6971339": legacy_generated_at,
    }

    new_generated_at = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
    store.write(
        entries,
        generated_at=new_generated_at,
        last_attempt_at=attempts,
    )
    payload = json.loads(store.path.read_text(encoding="utf-8"))

    assert set(payload) == {
        "schema_version",
        "generated_at",
        "source",
        "records",
    }
    assert payload["schema_version"] == 2
    assert payload["generated_at"] == "2026-07-29T12:00:00Z"
    assert all(
        set(record)
        == {
            "ticket_id",
            "cf_category",
            "cf_m_li_tpe",
            "last_attempt_at",
        }
        for record in payload["records"]
    )
    assert {
        record["last_attempt_at"] for record in payload["records"]
    } == {"2026-07-28T12:00:00Z"}
    assert store.load() == entries
    assert store.load_last_attempt_at() == attempts
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "record_mutation",
    [
        lambda record: record.pop("last_attempt_at"),
        lambda record: record.__setitem__(
            "last_attempt_at", "2026-07-29T12:00:00+07:00"
        ),
        lambda record: record.__setitem__("unexpected", "value"),
    ],
)
def test_store_rejects_schema_v2_record_key_or_timestamp_drift(
    tmp_path: Path, record_mutation
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = DimensionBackfillStore(runtime)
    record = {
        "ticket_id": "6971338",
        "cf_category": None,
        "cf_m_li_tpe": None,
        "last_attempt_at": "2026-07-29T12:00:00Z",
    }
    record_mutation(record)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-07-29T12:00:00Z",
                "source": "freshdesk_api_v2",
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    with pytest.raises(DimensionBackfillStoreError):
        store.load()


def test_store_rejects_symlink_or_wrong_mode_runtime_and_data_file(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked_runtime = tmp_path / "runtime-link"
    linked_runtime.symlink_to(outside, target_is_directory=True)
    generated_at = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)

    with pytest.raises(DimensionBackfillStoreError):
        DimensionBackfillStore(linked_runtime).write({}, generated_at=generated_at)

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = DimensionBackfillStore(runtime)
    store.path.write_text("{}", encoding="utf-8")
    store.path.chmod(0o644)
    with pytest.raises(DimensionBackfillStoreError):
        store.write({}, generated_at=generated_at)

    store.path.unlink()
    store.path.symlink_to(outside / "dimension_backfill.json")
    with pytest.raises(DimensionBackfillStoreError):
        store.load()


@pytest.mark.parametrize(
    "generated_at",
    [
        "not-a-timestamp",
        "2026-07-29T12:00:00",
        "2026-07-29T12:00:00+07:00",
    ],
)
def test_store_load_requires_timezone_aware_utc_generated_at(
    tmp_path: Path, generated_at: str
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = DimensionBackfillStore(runtime)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "source": "freshdesk_api_v2",
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    with pytest.raises(DimensionBackfillStoreError):
        store.load()


def test_dimension_verifier_preserves_overlay_semantics_and_chat_denominator():
    ticket = trace("trace-ticket", "6971338", 4, "2026-07-01T06:11:09Z", "safe response")
    chat = trace("trace-chat", "6971339", 0, "2026-07-01T06:12:09Z", "safe response")
    chat["input"]["source"] = "chat"
    backfill = {
        "6971338": DimensionBackfill("6971338", "Thanh toán-IBFT", "-217 Thất bại"),
        "6971339": DimensionBackfill("6971339", "Chăm sóc khách hàng", "1 Đang xử lý"),
    }

    report = verify_raw_ticket_dimensions(
        [ticket, chat],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        dimension_backfill=backfill,
    )

    assert report["ticket_count"] == 1
    assert report["issue_category_backfilled_count"] == 1
    assert report["tpe_backfilled_count"] == 1
    assert report["coverage_issue_category"] == 1.0
    assert report["coverage_tpe"] == 1.0


@pytest.mark.parametrize("existing_value", ["already set", ["value"], {"k": "v"}, 7])
def test_dimension_backfill_never_overwrites_non_empty_values_of_any_type(
    existing_value: object,
):
    trace_record = TraceRecord(
        id="trace-1",
        session_id="6971338",
        timestamp=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        turn=0,
        input_data={
            "other_info": {
                "meta": {
                    "Thông tin thêm": {"category": existing_value},
                    "Mã lỗi TPE": existing_value,
                }
            }
        },
        output_data={},
        environment="production",
    )

    result = apply_dimension_backfill(
        trace_record,
        DimensionBackfill("6971338", "Thanh toán-IBFT", "1 Đang xử lý"),
    )
    result_meta = result.input_data["other_info"]["meta"]

    assert result_meta["Thông tin thêm"]["category"] == existing_value
    assert result_meta["Mã lỗi TPE"] == existing_value


def test_dimension_backfill_treats_taxonomy_fallback_as_missing_but_preserves_real_values():
    fallback_record = TraceRecord(
        id="trace-fallback",
        session_id="6971338",
        timestamp=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        turn=0,
        input_data={
            "other_info": {
                "meta": {
                    "Thông tin thêm": {"category": " Không xác định "},
                    "Mã lỗi TPE": "",
                }
            }
        },
        output_data={},
        environment="production",
    )
    real_record = TraceRecord(
        id="trace-real",
        session_id="6971339",
        timestamp=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        turn=0,
        input_data={
            "other_info": {
                "meta": {
                    "Thông tin thêm": {"category": "Thanh toán-IBFT"},
                    "Mã lỗi TPE": "-217 Thất bại",
                }
            }
        },
        output_data={},
        environment="production",
    )

    fallback_result = apply_dimension_backfill(
        fallback_record,
        DimensionBackfill("6971338", "Chăm sóc khách hàng", "1 Đang xử lý"),
    )
    real_result = apply_dimension_backfill(
        real_record,
        DimensionBackfill("6971339", "Chăm sóc khách hàng", "1 Đang xử lý"),
    )

    assert fallback_result.input_data["other_info"]["meta"]["Thông tin thêm"]["category"] == "Chăm sóc khách hàng"
    assert fallback_result.input_data["other_info"]["meta"]["Mã lỗi TPE"] == "1 Đang xử lý"
    assert real_result == real_record


def test_batch_backfill_is_get_only_excludes_chat_preserves_denominator_and_checkpoints(tmp_path: Path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        if request.url.path == "/api/v2/tickets/6971338":
            return httpx.Response(
                200,
                json={
                    "id": 6971338,
                    "custom_fields": {
                        "cf_category": "Thanh toán-IBFT",
                        "cf_m_li_tpe": "-217 Thất bại",
                    },
                },
                request=request,
            )
        return httpx.Response(503, text="private upstream 0901234567", request=request)

    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971337": DimensionBackfill("6971337", "Chăm sóc khách hàng", None)},
        generated_at=datetime(2026, 7, 29, 11, tzinfo=timezone.utc),
    )
    first = trace("batch-first", "6971338", 2, "2026-07-29T01:00:00Z", "private response")
    first["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": "Không xác định"},
        "Mã lỗi TPE": "",
    }
    later = trace("batch-later", "6971338", 3, "2026-07-29T02:00:00Z", "private response")
    later["input"]["other_info"]["meta"] = {
        "Thông tin thêm": {"category": "must not use"},
        "Mã lỗi TPE": "1 should not use",
    }
    failing = trace("batch-failing", "6971339", 0, "2026-07-29T01:00:00Z", "private response")
    chat = trace("batch-chat", "6971340", 0, "2026-07-29T01:00:00Z", "private chat")
    chat["input"]["source"] = "chat"

    with pytest.raises(FreshdeskDimensionAPIError) as captured:
        backfill_ticket_dimensions(
            [first, later, failing, chat],
            load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
            _client(handler),
            store,
            generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        )

    assert str(captured.value) == "Freshdesk GET failed with status 503"
    assert store.load() == {
        "6971337": DimensionBackfill("6971337", "Chăm sóc khách hàng", None),
        "6971338": DimensionBackfill("6971338", "Thanh toán-IBFT", "-217 Thất bại"),
    }
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/ticket_fields"),
        ("GET", "/api/v2/tickets/6971338"),
        ("GET", "/api/v2/tickets/6971339"),
        ("GET", "/api/v2/tickets/6971339"),
        ("GET", "/api/v2/tickets/6971339"),
    ]
    persisted = store.path.read_text(encoding="utf-8")
    assert "6971340" not in persisted
    assert "private" not in persisted


def test_batch_backfill_does_not_treat_cached_taxonomy_fallback_as_complete(tmp_path: Path):
    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971338": DimensionBackfill("6971338", "Không xác định", None)},
        generated_at=datetime(2026, 7, 28, 11, tzinfo=timezone.utc),
    )
    raw = trace("cached-fallback", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    raw["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}

    class FakeFreshdesk:
        def __init__(self):
            self.validated = 0
            self.fetched: list[str] = []

        def validate_field_contract(self):
            self.validated += 1

        def fetch_ticket_dimensions(self, ticket_id):
            self.fetched.append(ticket_id)
            return DimensionBackfill(ticket_id, "Thanh toán-IBFT", "1 Đang xử lý")

    client = FakeFreshdesk()
    result = backfill_ticket_dimensions(
        [raw],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        client,
        store,
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result["fetched_ticket_count"] == 1
    assert client.validated == 1
    assert client.fetched == ["6971338"]
    assert store.load()["6971338"] == DimensionBackfill(
        "6971338", "Thanh toán-IBFT", "1 Đang xử lý"
    )


def test_batch_backfill_revalidates_cached_tombstone_at_exact_24h_boundary(tmp_path: Path):
    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971338": DimensionBackfill("6971338", None, None)},
        generated_at=datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
    )
    raw = trace("cached-tombstone", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    raw["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}

    class FakeFreshdesk:
        def validate_field_contract(self):
            return None

        def fetch_ticket_dimensions(self, ticket_id):
            return DimensionBackfill(ticket_id, "Thanh toán-IBFT", "1 Đang xử lý")

    result = backfill_ticket_dimensions(
        [raw],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        FakeFreshdesk(),
        store,
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result["fetched_ticket_count"] == 1
    assert result["skipped_fresh_tombstone_count"] == 0
    assert store.load()["6971338"] == DimensionBackfill(
        "6971338", "Thanh toán-IBFT", "1 Đang xử lý"
    )


def test_batch_backfill_skips_tombstone_younger_than_24h(tmp_path: Path):
    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971338": DimensionBackfill("6971338", None, None)},
        generated_at=datetime(2026, 7, 28, 12, 0, 1, tzinfo=timezone.utc),
    )
    raw = trace("fresh-tombstone", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    raw["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}

    class NoFetchFreshdesk:
        def validate_field_contract(self):
            raise AssertionError("fresh tombstones must skip contract validation")

        def fetch_ticket_dimensions(self, _ticket_id):
            raise AssertionError("fresh tombstones must not be fetched")

    result = backfill_ticket_dimensions(
        [raw],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        NoFetchFreshdesk(),
        store,
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result["fetched_ticket_count"] == 0
    assert result["skipped_fresh_tombstone_count"] == 1
    assert store.load_generated_at() == datetime(
        2026, 7, 28, 12, 0, 1, tzinfo=timezone.utc
    )


def test_new_checkpoint_does_not_refresh_another_records_attempt_timestamp(
    tmp_path: Path,
):
    run_at = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
    first_attempt = datetime(2026, 7, 28, 12, 0, 1, tzinfo=timezone.utc)
    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971338": DimensionBackfill("6971338", None, None)},
        generated_at=first_attempt,
        last_attempt_at={"6971338": first_attempt},
    )
    raw = [
        trace("fresh-a", "6971338", 0, "2026-07-29T01:00:00Z", "private"),
        trace("new-b", "6971339", 0, "2026-07-29T01:01:00Z", "private"),
    ]

    class FirstRunFreshdesk:
        def validate_field_contract(self):
            return None

        def fetch_ticket_dimensions(self, ticket_id):
            assert ticket_id == "6971339"
            return DimensionBackfill(
                ticket_id, "Thanh toán-IBFT", "1 Đang xử lý"
            )

    first_result = backfill_ticket_dimensions(
        raw,
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        FirstRunFreshdesk(),
        store,
        generated_at=run_at,
    )

    assert first_result["skipped_fresh_tombstone_count"] == 1
    assert store.load_last_attempt_at() == {
        "6971338": first_attempt,
        "6971339": run_at,
    }

    retried: list[str] = []

    class BoundaryFreshdesk:
        def validate_field_contract(self):
            return None

        def fetch_ticket_dimensions(self, ticket_id):
            retried.append(ticket_id)
            return DimensionBackfill(
                ticket_id, "Chăm sóc khách hàng", "1 Đang xử lý"
            )

    second_result = backfill_ticket_dimensions(
        raw,
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        BoundaryFreshdesk(),
        store,
        generated_at=datetime(
            2026, 7, 29, 12, 0, 1, tzinfo=timezone.utc
        ),
    )

    assert second_result["skipped_fresh_tombstone_count"] == 0
    assert retried == ["6971338"]


def test_batch_continues_after_ticket_403_preserves_partial_cache_and_checkpoints(
    tmp_path: Path,
):
    private_body = "private-user-0901234567"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        if request.url.path == "/api/v2/tickets/6971338":
            return httpx.Response(403, text=private_body, request=request)
        return httpx.Response(
            200,
            json={
                "id": 6971339,
                "custom_fields": {
                    "cf_category": "Thanh toán-IBFT",
                    "cf_m_li_tpe": "1 Đang xử lý",
                },
            },
            request=request,
        )

    store = DimensionBackfillStore(tmp_path / "runtime")
    store.write(
        {"6971338": DimensionBackfill("6971338", "Chăm sóc khách hàng", None)},
        generated_at=datetime(2026, 7, 28, 1, tzinfo=timezone.utc),
    )
    raw = [
        trace("inaccessible", "6971338", 0, "2026-07-29T01:00:00Z", "private"),
        trace("accessible", "6971339", 0, "2026-07-29T01:01:00Z", "private"),
    ]

    result = backfill_ticket_dimensions(
        raw,
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        _client(handler),
        store,
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result == {
        "ticket_trace_count": 2,
        "ticket_session_count": 2,
        "eligible_ticket_count": 2,
        "missing_issue_category_count": 2,
        "missing_tpe_count": 2,
        "fetched_ticket_count": 1,
        "inaccessible_ticket_count": 1,
        "skipped_fresh_tombstone_count": 0,
        "stored_record_count": 2,
    }
    assert store.load() == {
        "6971338": DimensionBackfill("6971338", "Chăm sóc khách hàng", None),
        "6971339": DimensionBackfill("6971339", "Thanh toán-IBFT", "1 Đang xử lý"),
    }
    assert store.load_generated_at() == datetime(
        2026, 7, 29, 12, tzinfo=timezone.utc
    )
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/ticket_fields"),
        ("GET", "/api/v2/tickets/6971338"),
        ("GET", "/api/v2/tickets/6971339"),
    ]
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "6971338" not in serialized
    assert "6971339" not in serialized
    assert private_body not in serialized

    requests.clear()
    rerun = backfill_ticket_dimensions(
        raw,
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        _client(handler),
        store,
        generated_at=datetime(2026, 7, 29, 13, tzinfo=timezone.utc),
    )

    assert rerun["skipped_fresh_tombstone_count"] == 1
    assert rerun["fetched_ticket_count"] == 0
    assert rerun["inaccessible_ticket_count"] == 0
    assert requests == []
    assert store.load()["6971338"] == DimensionBackfill(
        "6971338", "Chăm sóc khách hàng", None
    )


def test_batch_archived_403_checkpoints_tombstone_without_exposing_response(
    tmp_path: Path,
):
    requests: list[httpx.Request] = []
    private_body = "private archived response 0901234567"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/ticket_fields":
            return httpx.Response(200, json=VALID_FIELDS, request=request)
        if request.url.path == "/api/v2/tickets/6971338":
            return httpx.Response(404, json={}, request=request)
        return httpx.Response(403, text=private_body, request=request)

    raw = trace("archived-inaccessible", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    store = DimensionBackfillStore(tmp_path / "runtime")
    result = backfill_ticket_dimensions(
        [raw],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        _client(handler),
        store,
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result["inaccessible_ticket_count"] == 1
    assert result["fetched_ticket_count"] == 0
    assert store.load() == {
        "6971338": DimensionBackfill("6971338", None, None)
    }
    assert [request.url.path for request in requests] == [
        "/api/v2/ticket_fields",
        "/api/v2/tickets/6971338",
        "/api/v2/tickets/archived/6971338",
    ]
    assert private_body not in json.dumps(result)


def test_batch_field_contract_403_still_aborts_with_redacted_error(tmp_path: Path):
    private_body = "private auth body 0901234567"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, text=private_body, request=request)

    raw = trace("contract-auth", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    store = DimensionBackfillStore(tmp_path / "runtime")

    with pytest.raises(FreshdeskDimensionAPIError) as captured:
        backfill_ticket_dimensions(
            [raw],
            load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
            _client(handler),
            store,
            generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        )

    assert str(captured.value) == "Freshdesk GET failed with status 403"
    assert private_body not in str(captured.value)
    assert [request.url.path for request in requests] == [
        "/api/v2/ticket_fields"
    ]
    assert not store.path.exists()


def test_batch_backfill_counts_raw_invalid_and_unkeyed_ticket_denominator_without_fetching_them(
    tmp_path: Path,
):
    valid = trace("valid-backfill", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    valid["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}
    invalid = trace("invalid-backfill", "6971339", "bad-turn", "2026-07-29T01:00:00Z", "private")
    unkeyed = trace("unkeyed-backfill", None, 0, "2026-07-29T01:00:00Z", "private")
    chat = trace("chat-backfill", "6971340", 0, "2026-07-29T01:00:00Z", "private")
    chat["input"]["source"] = "chat"

    class FakeFreshdesk:
        def __init__(self):
            self.fetched: list[str] = []

        def validate_field_contract(self):
            return None

        def fetch_ticket_dimensions(self, ticket_id):
            self.fetched.append(ticket_id)
            return DimensionBackfill(ticket_id, "Thanh toán-IBFT", "1 Đang xử lý")

    client = FakeFreshdesk()
    result = backfill_ticket_dimensions(
        [valid, invalid, unkeyed, chat],
        load_taxonomy(PROJECT_ROOT / "config" / "taxonomy.v2.json"),
        client,
        DimensionBackfillStore(tmp_path / "runtime"),
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert result["ticket_trace_count"] == 3
    assert result["ticket_session_count"] == 3
    assert client.fetched == ["6971338"]


def test_backfill_dimensions_cli_uses_env_key_only_and_prints_one_safe_aggregate(
    monkeypatch, capsys, tmp_path: Path
):
    class FakeLangfuse:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def iter_traces(self, _from, _to):
            ticket = trace("cli-backfill", "6971338", 0, "2026-07-29T01:00:00Z", "private response")
            ticket["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}
            chat = trace("cli-chat", "6971339", 0, "2026-07-29T01:00:00Z", "private chat")
            chat["input"]["source"] = "chat"
            yield ticket
            yield chat

    class FakeFreshdesk:
        instances: list[object] = []

        def __init__(self, base_url, api_key):
            assert base_url == FRESHDESK_BASE_URL
            assert api_key == "env-only-secret"
            self.validated = 0
            self.fetched: list[str] = []
            FakeFreshdesk.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def validate_field_contract(self):
            self.validated += 1

        def fetch_ticket_dimensions(self, ticket_id):
            self.fetched.append(ticket_id)
            return DimensionBackfill(ticket_id, "Thanh toán-IBFT", "-217 Thất bại")

    langfuse = FakeLangfuse()
    monkeypatch.setattr(
        "weekly_cs_report.cli.load_environment",
        lambda: EnvironmentSettings("pk-test", "sk-test", TARGET_BASE_URL),
    )
    monkeypatch.setattr("weekly_cs_report.cli._build_client", lambda _settings: langfuse)
    monkeypatch.setattr("weekly_cs_report.cli.FreshdeskDimensionClient", FakeFreshdesk)
    monkeypatch.setattr("weekly_cs_report.cli.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("FRESHDESK_API_KEY", "env-only-secret")

    exit_code = main([
        "backfill-dimensions", "--weeks", "2", "--as-of", "2026-07-29T12:00:00+07:00"
    ])
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "eligible_ticket_count": 1,
        "fetched_ticket_count": 1,
        "missing_issue_category_count": 1,
        "missing_tpe_count": 1,
        "inaccessible_ticket_count": 0,
        "skipped_fresh_tombstone_count": 0,
        "stored_record_count": 1,
        "ticket_session_count": 1,
        "ticket_trace_count": 1,
    }
    assert "6971338" not in captured.out
    assert "private" not in captured.out
    assert "env-only-secret" not in captured.out + captured.err
    assert FakeFreshdesk.instances[0].validated == 1
    assert FakeFreshdesk.instances[0].fetched == ["6971338"]
    assert langfuse.closed is True


def test_backfill_dimensions_cli_requires_env_key_without_echo(monkeypatch, capsys):
    monkeypatch.delenv("FRESHDESK_API_KEY", raising=False)
    monkeypatch.setattr("weekly_cs_report.cli.load_environment", lambda: pytest.fail("missing Freshdesk env must fail first"))

    assert main(["backfill-dimensions"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "FRESHDESK_API_KEY is missing\n"


def test_verify_dimensions_loads_private_backfill_and_reports_raw_and_effective_counts(
    monkeypatch, capsys, tmp_path: Path
):
    runtime = tmp_path / "runtime"
    store = DimensionBackfillStore(runtime)
    store.write(
        {"6971338": DimensionBackfill("6971338", "Thanh toán-IBFT", "-217 Thất bại")},
        generated_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )
    raw = trace("verify-overlay", "6971338", 0, "2026-07-29T01:00:00Z", "private")
    raw["input"]["other_info"]["meta"] = {"Thông tin thêm": {"category": "Không xác định"}}

    class FakeLangfuse:
        def iter_traces(self, _from, _to):
            yield raw

    monkeypatch.setattr("weekly_cs_report.cli.PROJECT_ROOT", tmp_path)
    report = run_dimension_verification(
        as_of=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        weeks=1,
        include_current_wtd=False,
        client=FakeLangfuse(),
    )
    captured = capsys.readouterr()

    assert report["trace_issue_category_present_count"] == 0
    assert report["trace_tpe_present_count"] == 0
    assert report["issue_category_present_count"] == 1
    assert report["tpe_present_count"] == 1
    assert json.loads(captured.out) == report
    assert "6971338" not in captured.out
    assert "private" not in captured.out
