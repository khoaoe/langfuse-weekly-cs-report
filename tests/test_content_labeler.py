from __future__ import annotations

import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from weekly_cs_report.content_labeler import (
    PROMPT_VERSION,
    ContentLabeler,
    ContentLabelerError,
    LabelCache,
    LabelConfigError,
    LabelDefinition,
    LabelSet,
    load_label_set,
    write_reopen_evidence,
    _CacheKey,
)
from weekly_cs_report.llm_client import FakeLLMClient
from weekly_cs_report.models import ReopenLabel
from weekly_cs_report.reopen_population import ReopenSession


PROJECT_ROOT = Path(__file__).parents[1]


class RecordingFakeLLMClient(FakeLLMClient):
    def __init__(self, *, outputs):
        super().__init__(structured_outputs=outputs)
        self.calls: list[tuple[dict[str, object], ...]] = []

    def generate_structured(self, *, messages, response_schema):
        self.calls.append(tuple(dict(message) for message in messages))
        return super().generate_structured(
            messages=messages,
            response_schema=response_schema,
        )


class FailingLLMClient:
    def __init__(self):
        self.calls = 0

    def generate_structured(self, *, messages, response_schema):
        self.calls += 1
        raise RuntimeError("raw model failure must not escape")

    def embed(self, texts):
        raise AssertionError("labeler must not embed")


@pytest.fixture()
def labels() -> LabelSet:
    return LabelSet(
        version="v9",
        labels=(
            LabelDefinition(
                key="ai_wrong_content",
                display="Sai nội dung",
                definition="AI trả lời sai.",
                po_action="sửa skill",
            ),
        ),
        abstain_label="other",
        requires_quote=("other",),
    )


def _session(session_id: str = "session-1") -> ReopenSession:
    return ReopenSession(
        session_id=session_id,
        anchor_trace_id=f"anchor-{session_id}",
        followup_trace_id=f"followup-{session_id}",
        week=date(2026, 7, 20),
        domain="ibft",
        outcome="ai_end_to_end",
        initial_user_text="khách hỏi [PII]",
        initial_ai_text="AI trả lời đã mask",
        followup_user_text="khách quay lại [PII]",
    )


def test_empty_label_file_fails_before_any_client_or_network(tmp_path):
    label_path = tmp_path / "reopen_labels.v1.json"
    label_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "created_at": "2026-07-31",
                "labels": [],
                "abstain_label": "other",
                "requires_quote": ["other"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LabelConfigError, match="reopen label list is empty"):
        load_label_set(label_path)


def test_production_label_file_loads_the_po_approved_v1_taxonomy():
    labels = load_label_set(PROJECT_ROOT / "config" / "reopen_labels.v1.json")

    assert labels.version == "v1"
    assert tuple(label.key for label in labels.labels) == (
        "fraud_or_unauthorized",
        "wrong_transfer_recovery",
        "account_or_verification_blocked",
        "refund_or_reversal_pending",
        "recipient_not_credited",
        "transaction_failed_or_debited",
        "status_or_next_step_unclear",
    )
    assert labels.abstain_label == "other"
    assert labels.requires_quote == ("other",)


def test_labeler_uses_exact_label_enum_only_three_masked_segments_and_drops_quote_for_non_other(
    labels, tmp_path
):
    llm = RecordingFakeLLMClient(
        outputs=({"label": "ai_wrong_content", "quote": "must not be retained"},)
    )
    labeler = ContentLabeler(labels, llm, LabelCache(tmp_path / "cache"))

    result = labeler.label_sessions((_session(),))

    assert result.labeled == 1
    assert result.abstained == 0
    assert result.invalid == 0
    assert result.failed == 0
    assert result.labels[0].label == "ai_wrong_content"
    assert result.labels[0].quote is None
    assert len(llm.calls) == 1
    user_message = llm.calls[0][-1]
    assert user_message["role"] == "user"
    assert set(user_message["content"]) == {
        "initial_user_text",
        "initial_ai_text",
        "followup_user_text",
    }
    assert "session-1" not in json.dumps(llm.calls[0], ensure_ascii=False)


def test_labeler_marks_outside_enum_missing_quote_and_extra_fields_invalid(labels, tmp_path):
    llm = RecordingFakeLLMClient(
        outputs=(
            {"label": "invented_label"},
            {"label": "other"},
            {"label": "ai_wrong_content", "unexpected": "must be rejected"},
        )
    )
    labeler = ContentLabeler(labels, llm, LabelCache(tmp_path / "cache"))

    result = labeler.label_sessions(
        (_session("one"), _session("two"), _session("three"))
    )

    assert [item.status for item in result.labels] == [
        "invalid",
        "invalid",
        "invalid",
    ]
    assert [item.label for item in result.labels] == [None, None, None]
    assert result.invalid == 3


def test_cache_key_prevents_second_model_call_and_never_serializes_three_texts(labels, tmp_path):
    cache = LabelCache(tmp_path / "cache")
    first_llm = RecordingFakeLLMClient(
        outputs=({"label": "other", "quote": "quay lại 0900000000"},)
    )
    first = ContentLabeler(labels, first_llm, cache).label_sessions((_session(),))
    second_llm = FailingLLMClient()

    second = ContentLabeler(labels, second_llm, cache).label_sessions((_session(),))

    assert first.labels[0].status == "abstained"
    assert first.labels[0].quote == "quay lại [PII]"
    assert second.labels == first.labels
    assert second.cached == 1
    assert second_llm.calls == 0
    cached_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cached_files) == 1
    assert stat.S_IMODE(cached_files[0].stat().st_mode) == 0o600
    serialized = cached_files[0].read_text(encoding="utf-8")
    assert "khách hỏi" not in serialized
    assert "AI trả lời" not in serialized
    assert "khách quay lại [PII]" not in serialized
    assert PROMPT_VERSION in serialized


def test_concurrent_labelers_for_same_cache_key_call_client_at_most_once(
    labels, tmp_path
):
    entered = threading.Event()
    release = threading.Event()
    calls_lock = threading.Lock()

    class BlockingClient:
        def __init__(self):
            self.calls = 0

        def generate_structured(self, *, messages, response_schema):
            with calls_lock:
                self.calls += 1
            entered.set()
            assert release.wait(2)
            return type(
                "Generated",
                (),
                {"value": {"label": "ai_wrong_content"}},
            )()

        def embed(self, texts):
            raise AssertionError("labeler must not embed")

    client = BlockingClient()
    cache_root = tmp_path / "cache"
    first = ContentLabeler(labels, client, LabelCache(cache_root))
    second = ContentLabeler(labels, client, LabelCache(cache_root))
    second_started = threading.Event()

    def label_with_second():
        second_started.set()
        return second.label_sessions((_session(),))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first.label_sessions, (_session(),))
        assert entered.wait(2)
        second_future = executor.submit(label_with_second)
        assert second_started.wait(2)
        release.set()
        batches = (first_future.result(2), second_future.result(2))

    assert client.calls == 1
    assert [batch.labels[0].label for batch in batches] == [
        "ai_wrong_content",
        "ai_wrong_content",
    ]
    assert sorted(batch.cached for batch in batches) == [0, 1]
    assert len(list(cache_root.glob("*.json"))) == 1
    assert list(cache_root.glob(".*.tmp")) == []


def test_cache_and_evidence_writes_are_fsynced_atomic_and_mode_600(
    labels, tmp_path, monkeypatch
):
    from weekly_cs_report import content_labeler

    real_replace = content_labeler.os.replace
    real_fsync = content_labeler.os.fsync
    replacements = []
    fsynced = []

    def recording_fsync(descriptor):
        fsynced.append(descriptor)
        return real_fsync(descriptor)

    def recording_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent
        assert source_path != destination_path
        assert stat.S_IMODE(source_path.stat().st_mode) == 0o600
        json.loads(source_path.read_text(encoding="utf-8"))
        replacements.append((source_path.name, destination_path.name))
        return real_replace(source, destination)

    monkeypatch.setattr(content_labeler.os, "fsync", recording_fsync)
    monkeypatch.setattr(content_labeler.os, "replace", recording_replace)

    cache = LabelCache(tmp_path / "cache")
    ContentLabeler(
        labels,
        RecordingFakeLLMClient(outputs=({"label": "ai_wrong_content"},)),
        cache,
    ).label_sessions((_session(),))
    evidence = write_reopen_evidence(
        tmp_path / "evidence",
        (_session(),),
        (
            ReopenLabel(
                session_id="session-1",
                labels_version="v9",
                prompt_version=PROMPT_VERSION,
                label="ai_wrong_content",
                status="labeled",
            ),
        ),
    )

    assert len(replacements) == 2
    assert len(fsynced) == 2
    assert stat.S_IMODE(next((tmp_path / "cache").glob("*.json")).stat().st_mode) == 0o600
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600
    assert stat.S_IMODE(evidence.parent.stat().st_mode) == 0o700
    assert list((tmp_path / "cache").glob(".*.tmp")) == []
    assert list((tmp_path / "evidence").glob(".*.tmp")) == []


def test_partial_evidence_write_preserves_last_good_and_removes_temp(
    tmp_path, monkeypatch
):
    from weekly_cs_report import content_labeler

    destination = write_reopen_evidence(
        tmp_path / "evidence",
        (_session(),),
        (
            ReopenLabel(
                session_id="session-1",
                labels_version="v9",
                prompt_version=PROMPT_VERSION,
                label="ai_wrong_content",
                status="labeled",
            ),
        ),
    )
    last_good = destination.read_bytes()
    secret = "partial raw secret 0901234567"

    def partial_dump(payload, stream, **kwargs):
        stream.write(secret)
        stream.flush()
        raise OSError(secret)

    monkeypatch.setattr(content_labeler.json, "dump", partial_dump)

    with pytest.raises(
        content_labeler.ContentLabelerError,
        match="reopen protected output is unavailable",
    ):
        write_reopen_evidence(
            tmp_path / "evidence",
            (_session(),),
            (
                ReopenLabel(
                    session_id="session-1",
                    labels_version="v9",
                    prompt_version=PROMPT_VERSION,
                    label="ai_wrong_content",
                    status="labeled",
                ),
            ),
        )

    assert destination.read_bytes() == last_good
    assert secret not in destination.read_text(encoding="utf-8")
    assert list(destination.parent.glob(".*.tmp")) == []


def test_cache_write_refuses_final_symlink_without_touching_target(labels, tmp_path):
    cache = LabelCache(tmp_path / "cache")
    target = tmp_path / "outside.json"
    target.write_text("outside sentinel", encoding="utf-8")
    key_name = _CacheKey("session-1", labels.version, PROMPT_VERSION).filename()
    (cache.root / key_name).symlink_to(target)

    with pytest.raises(
        ContentLabelerError,
        match="reopen protected output is unavailable",
    ):
        ContentLabeler(
            labels,
            RecordingFakeLLMClient(outputs=({"label": "ai_wrong_content"},)),
            cache,
        ).label_sessions((_session(),))

    assert target.read_text(encoding="utf-8") == "outside sentinel"


def test_model_exception_is_failed_and_batch_continues_without_raw_error(labels, tmp_path, caplog):
    failed = FailingLLMClient()
    succeeding = RecordingFakeLLMClient(outputs=({"label": "ai_wrong_content"},))

    class FirstFailsThenSucceeds:
        def __init__(self):
            self.calls = 0

        def generate_structured(self, *, messages, response_schema):
            self.calls += 1
            if self.calls == 1:
                return failed.generate_structured(messages=messages, response_schema=response_schema)
            return succeeding.generate_structured(messages=messages, response_schema=response_schema)

        def embed(self, texts):
            raise AssertionError("labeler must not embed")

    result = ContentLabeler(
        labels, FirstFailsThenSucceeds(), LabelCache(tmp_path / "cache")
    ).label_sessions((_session("one"), _session("two")))

    assert [item.status for item in result.labels] == ["failed", "labeled"]
    assert result.failed == 1
    assert result.labeled == 1
    assert "raw model failure" not in caplog.text


def test_evidence_is_mode_600_and_keeps_a_masked_quote_only_for_other(tmp_path):
    sessions = (_session("one"), _session("two"))
    labels = (
        ReopenLabel(
            session_id="one",
            labels_version="v9",
            prompt_version=PROMPT_VERSION,
            label="ai_wrong_content",
            status="labeled",
        ),
        ReopenLabel(
            session_id="two",
            labels_version="v9",
            prompt_version=PROMPT_VERSION,
            label="other",
            status="abstained",
            quote="khách gọi 0900000000",
        ),
    )

    destination = write_reopen_evidence(tmp_path / "evidence", sessions, labels)

    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    rows = json.loads(destination.read_text(encoding="utf-8"))
    assert rows[0] == {
        "session_id": "one",
        "label": "ai_wrong_content",
        "anchor_trace_id": "anchor-one",
        "followup_trace_id": "followup-one",
    }
    assert rows[1] == {
        "session_id": "two",
        "label": "other",
        "anchor_trace_id": "anchor-two",
        "followup_trace_id": "followup-two",
        "quote": "khách gọi [PII]",
    }
