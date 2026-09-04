from __future__ import annotations

"""Keep pytest's temporary tree off `/tmp`.

`_validated_runtime_directory` (``web.py``) refuses a runtime directory whose
ancestors carry group/other write bits. `/private/tmp` is mode 1777 -- the
sticky world-writable mode every Unix `/tmp` has -- so every `tmp_path` under
the default basetemp trips that check and the runtime-directory tests fail
with `dashboard runtime directory is unsafe`. The validator is right to be
strict (sticky is a subtle exception, not worth loosening a security check
for), so the temporary tree moves instead of the rule.

`--basetemp` on the command line still wins; this only supplies the default.
"""

from pathlib import Path

_BASETEMP = Path(__file__).resolve().parents[1] / ".pytest-tmp"


def pytest_configure(config) -> None:
    if config.option.basetemp is None:
        _BASETEMP.mkdir(mode=0o700, exist_ok=True)
        config.option.basetemp = str(_BASETEMP)
