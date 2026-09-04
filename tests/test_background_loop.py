from __future__ import annotations

"""Cover the thread lifecycle the two background refreshers now share.

`_BackgroundLoop` was extracted from two hand-copied lifecycles that no test
touched directly. These assert the parts a refactor there could silently
break: the loop actually calls the loader, `close` stops it, a raising loader
does not kill the thread, and each subclass still reports through its own
`get` shape.
"""

import threading

from weekly_cs_report.web import _AbTestBackgroundCache, _ModelListBackgroundCache


def _drain(cache, calls: threading.Event) -> None:
    cache.start()
    assert calls.wait(timeout=5.0), "background loop never called its loader"
    cache.close()
    assert not cache._thread.is_alive()


def test_ab_test_background_loop_publishes_payload_then_stops() -> None:
    called = threading.Event()

    def loader() -> dict[str, object]:
        called.set()
        return {"arms": []}

    cache = _AbTestBackgroundCache(loader, interval_seconds=0.01)
    _drain(cache, called)
    assert cache.get() == ({"arms": []}, None)


def test_ab_test_background_loop_reports_error_code_and_keeps_running() -> None:
    called = threading.Event()

    def loader() -> dict[str, object]:
        called.set()
        raise RuntimeError("langfuse down")

    cache = _AbTestBackgroundCache(loader, interval_seconds=0.01)
    _drain(cache, called)
    assert cache.get() == (None, "refresh_failed")


def test_model_list_background_loop_hands_back_a_defensive_copy() -> None:
    called = threading.Event()

    def loader() -> list[str]:
        called.set()
        return ["gemma-3-27b"]

    cache = _ModelListBackgroundCache(loader, interval_seconds=0.01)
    _drain(cache, called)
    first = cache.get()
    assert first == ["gemma-3-27b"]
    first.append("mutated-by-caller")
    assert cache.get() == ["gemma-3-27b"]


def test_model_list_background_loop_survives_a_failing_loader() -> None:
    called = threading.Event()

    def loader() -> list[str]:
        called.set()
        raise RuntimeError("langfuse down")

    cache = _ModelListBackgroundCache(loader, interval_seconds=0.01)
    _drain(cache, called)
    assert cache.get() is None
