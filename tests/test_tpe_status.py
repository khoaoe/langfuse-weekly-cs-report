from pathlib import Path

import pytest

from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.tpe_status import resolve_tpe_status

TAXONOMY_V2 = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy(TAXONOMY_V2)


def test_resolves_step_specific_pair(taxonomy):
    assert resolve_tpe_status("1", "1", taxonomy) == "SUCCESSFUL"


def test_resolves_code_with_empty_steps_regardless_of_step(taxonomy):
    # -374 mang mapping steps rong, nen moi step deu ra REFUNDING.
    assert resolve_tpe_status("-374", "-9999", taxonomy) == "REFUNDING"
    assert resolve_tpe_status("-374", None, taxonomy) == "REFUNDING"


def test_returns_none_for_unmapped_code(taxonomy):
    # -217 khong co trong taxonomy; khong duoc doan nghia.
    assert resolve_tpe_status("-217", "-5025", taxonomy) is None


def test_returns_none_when_step_specific_code_lacks_step(taxonomy):
    # -244 chi co mapping step-specific, thieu step thi khong ket luan.
    assert resolve_tpe_status("-244", None, taxonomy) is None


def test_never_raises_on_v2_shape(taxonomy):
    # Hoi quy cho bay _tpe_mapping: KeyError 'step' tren taxonomy v2.
    for code in ("1", "-217", "-365", "-993"):
        resolve_tpe_status(code, None, taxonomy)
