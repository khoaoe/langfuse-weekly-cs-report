from __future__ import annotations

"""Environment configuration, shared by the CLI and the web server.

Split out of ``cli`` so that ``web`` no longer imports the CLI module just to
read three names from it: a web server depending on a command-line entry point
is backwards, and it dragged the whole CLI import graph into the serving
process. Both now depend on this leaf instead.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


TARGET_BASE_URL = "https://langfuse.zalopay.vn"


_ENVIRONMENT_NAMES = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnvironmentSettings:
    public_key: str
    secret_key: str
    base_url: str


def load_environment(
    environ: Mapping[str, str] | None = None,
) -> EnvironmentSettings:
    if environ is None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        environ = os.environ
    missing = tuple(name for name in _ENVIRONMENT_NAMES if not environ.get(name))
    if missing:
        raise ConfigurationError(
            "Missing environment variables: " + ", ".join(missing)
        )
    if environ["LANGFUSE_BASE_URL"].rstrip("/") != TARGET_BASE_URL:
        raise ConfigurationError(
            "LANGFUSE_BASE_URL does not match the configured target"
        )
    return EnvironmentSettings(
        public_key=environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=environ["LANGFUSE_SECRET_KEY"],
        base_url=TARGET_BASE_URL,
    )
