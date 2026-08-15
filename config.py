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


def b2_outlet_keys(sources: dict | None = None) -> list[str]:
    """Normalized names of the outlets this config grades B2, for outlet promotion.

    DERIVED FROM THE FEED LIST RATHER THAN RESTATED. The registry already says
    which outlets are B2 -- that is what a B2 feed entry means -- so a second
    hand-maintained list would only be a way for the two to disagree. A feed id
    normalizes to the same key its outlet name does (`democracy-docket` and
    `Democracy Docket` and `democracydocket.com` all reduce to `democracydocket`),
    which is what lets one list serve both.

    The key is a PREFIX, matched against a normalized `items.outlet`. Prefix rather
    than equality because outlets spell themselves inconsistently across the
    corpus: 106 items say `Democracy Docket`, 20 say `democracydocket.com`, and
    States United arrives as `States United Democracy Center`. Equality drops every
    variant, which is how this unit's own first measurement undercounted by 20."""
    news = (sources or load_sources()).get("news", {})
    return sorted(
        outlet_key(f["id"]) for f in news.get("feeds", [])
        if str(grade(f.get("grade"))[0]).upper() == "B"
    )


def outlet_key(value: str | None) -> str:
    """Fold an outlet name or feed id to a comparable key: lowercase alphanumerics.

    Mirrors the SQL in `news_outlet_sql` exactly. If you change one, change both --
    the parity test in tests/test_export.py exists because they can silently
    disagree, and a promotion rule that disagrees with itself between the export
    and the view is the failure this whole unit is about."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def news_outlet_sql(keys: list[str], column: str = "i.outlet") -> str:
    """SQL predicate: does `column` name one of these B2 outlets?

    The REPLACE chain is the SQL spelling of `outlet_key` -- lowercase, then drop
    the two characters outlets actually vary on (spaces and dots). Written as a
    string rather than parameterised because it is generated from config, never
    from user input, and both callers need the identical text."""
    norm = f"REPLACE(REPLACE(LOWER({column}), ' ', ''), '.', '')"
    return " OR ".join(f"{norm} LIKE '{k}%'" for k in keys)
