"""Resolve the governed TPE status for an observed (transstatus, step_result).

The mapping table lives in ``config/taxonomy.v2.json`` under ``tpe.mappings``.
This module only reads it; it never widens, guesses, or back-fills a status.

Do not reuse ``categories._tpe_mapping`` here: that helper reads the v1 key
``step`` and raises ``KeyError`` against the v2 taxonomy the runtime loads.
"""

from __future__ import annotations

from .categories import Taxonomy


def resolve_tpe_status(
    transstatus: str, step_result: str | None, taxonomy: Taxonomy
) -> str | None:
    """Return the governed status, or ``None`` when the pair is not mapped.

    A mapping whose ``steps`` is empty applies to the code regardless of the
    step.  A mapping with entries applies only when ``step_result`` is one of
    them.  The v2 taxonomy has been verified to contain no code carrying both
    shapes and no ``(code, step)`` pair resolving to two different statuses, so
    the first match is the only match.

    ``None`` means "not mapped" and must stay unlabelled downstream.  The
    taxonomy's ``unmapped_policy = passthrough`` governs storage, never display.
    """
    for mapping in taxonomy.tpe_mappings:
        if mapping["code"] != transstatus:
            continue
        steps = mapping.get("steps") or ()
        if not steps:
            return str(mapping["status"])
        if step_result is not None and step_result in steps:
            return str(mapping["status"])
    return None
