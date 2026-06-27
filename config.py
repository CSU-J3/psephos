"""Config and credential loading for psephos.

Reads the source registry from `config/sources.yaml` and loads `.env` for local
dev. On the cron, secrets come from the environment (GitHub Actions secrets), so
`.env` values never clobber an already-set variable.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ENV_PATH = ".env"
SOURCES_PATH = "config/sources.yaml"


def load_env(path: str = ENV_PATH) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Skips blanks and comments, splits on the first '=', strips surrounding
    quotes. Existing environment variables win, so CI secrets are never
    overwritten by a stray local .env.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_sources(path: str = SOURCES_PATH) -> dict:
    """Parse the source registry / watchlist YAML."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def require_env(name: str) -> str:
    """Return an environment variable or raise a clear, actionable error."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable {name}. "
            f"Set it in .env (see .env.example) or as a GitHub Actions secret."
        )
    return value


def grade(d: dict | None) -> tuple[str, str]:
    """Normalize a {source, info} Admiralty grade dict to ('A', '1') strings."""
    d = d or {}
    return str(d.get("source", "")), str(d.get("info", ""))
