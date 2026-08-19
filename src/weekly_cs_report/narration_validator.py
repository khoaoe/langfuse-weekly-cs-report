"""Tầng 3: V1-V7. Trượt bất kỳ luật nào -> llm_status = "rejected", bỏ narration.

Không mệnh đề nào chưa qua đây được tới tay CS (spec section 9).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .escalation_dossier import EscalationDossier
from .escalation_narrator import Narration

_LONG_DIGIT_RUN = re.compile(r"[0-9]{6,}")
_NUMBER_RUN = re.compile(r"\d[\d.,]*\d|\d")
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "explain_context.v1.json"


@lru_cache(maxsize=1)
def _forbidden_words() -> tuple[str, ...]:
    from .explain_context import load_explain_config

    return load_explain_config(_CONFIG_PATH).forbidden_words


def _contains_forbidden_word(text: str) -> bool:
    lowered = text.lower()
    return any(
        re.search(rf"\b{re.escape(word.lower())}\b", lowered) for word in _forbidden_words()
    )


def _normalize_digits(text: str) -> str:
    return re.sub(r"[.,]", "", text)


def _numbers_backed_by_evidence(narration: Narration, dossier: EscalationDossier) -> bool:
    numbers = {_normalize_digits(m) for m in _NUMBER_RUN.findall(narration.ket_luan)}
    if not numbers:
        return True
    haystacks = [ev.value for ev in dossier.tool_evidence]
    if narration.can_cu is not None and narration.can_cu.trich_dan:
        haystacks.append(narration.can_cu.trich_dan)
    combined = _normalize_digits(" ".join(haystacks))
    return all(number in combined for number in numbers)


def validate(
    narration: Narration,
    dossier: EscalationDossier,
    quoted_line: str | None,
) -> bool:
    # V6: kết luận không rỗng sau khi strip.
    if not narration.ket_luan.strip():
        return False

    if narration.do_tin_cay not in ("cao", "trung_binh", "thap"):
        return False

    if narration.can_cu is not None:
        # V1: chỉ số stage A phải trỏ tới một candidate thật trong dossier,
        # không phải chỉ số rác -- anchor là khoá duy nhất tuyệt đối (spec 5.3).
        anchors = {c.anchor for c in dossier.rule_candidates}
        if narration.can_cu.nguon not in anchors:
            return False
        # V2: dòng trích phải đúng nguyên văn dòng backend đã cắt ra --
        # không phải câu do model tự sinh.
        if narration.can_cu.trich_dan is not None and narration.can_cu.trich_dan != quoted_line:
            return False

    # V3: mọi bằng chứng phải là step_key thật trong dossier -- bang_chung
    # không do LLM sinh (backend lấy trực tiếp tool_evidence), đây là chốt
    # phòng thủ cho trường hợp cấu trúc lại vô tình làm sai.
    real_steps = {ev.step_key for ev in dossier.tool_evidence}
    if any(item.buoc not in real_steps for item in narration.bang_chung):
        return False

    # V4: không rò định danh -- chuỗi số dài trong kết luận.
    if _LONG_DIGIT_RUN.search(narration.ket_luan):
        return False

    # V5: không lọt ngôn ngữ kỹ thuật.
    if _contains_forbidden_word(narration.ket_luan):
        return False

    # V7: mọi cụm số trong kết luận phải có mặt trong bằng chứng hoặc dòng
    # luật đã trích -- số viết bằng chữ không chặn được, chấp nhận theo spec.
    if not _numbers_backed_by_evidence(narration, dossier):
        return False

    return True
