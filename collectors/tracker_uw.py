"""UW SDRI DOJ-suit tracker scraper -> data/doj_cases.json  (handoff 4a).

Pure discovery: fetch the University of Wisconsin State Democracy Research
Initiative tracker of DOJ lawsuits seeking states' voter data, parse its one
server-rendered <table>, and emit a committed, deterministic seed artifact the
litigation collector consumes (4b). No DB writes, no CourtListener calls here.

The table reflects CURRENT posture: an appealed case shows the *circuit* docket
in "Current Federal Court" / "Current Case Number", not the district one, so v1
seeds the current docket (what the table gives cleanly). Acceptable for v1 --
appealed cases track the appeal, not the full district history.

Determinism is the point: sorted by (state, docket_number) with sorted object
keys and NO wall-clock, so the artifact is byte-identical on an unchanged
tracker (extends the empty-diff proof; a real diff means the tracker moved).

Run from the repo root:  python -m collectors.tracker_uw
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

import common
import config

ARTIFACT_PATH = "data/doj_cases.json"
USER_AGENT = "psephos/0.1 (+https://github.com/CSU-J3/psephos)"
CATEGORY = "voter-data"

# Court name (the tracker's "Current Federal Court" cell text) -> CourtListener
# court id, for the litigation collector's exact docket_number+court resolution.
# EVERY id below was verified against CourtListener /api/rest/v4/courts/{id}/ --
# a wrong id makes resolve_docket return 0 and SILENTLY skip the case. The 32
# districts are exactly the states in the tracker (verify-on-demand: add + verify
# a new district only when a row needs it). The 13 courts of appeals are a closed,
# fully-verified set, pre-populated so any future appeal maps without a code change.
COURT_IDS = {
    # District courts (verified 1:1 against CourtListener /courts/)
    "District of Arizona": "azd",
    "Central District of California": "cacd",
    "District of Colorado": "cod",
    "District of Connecticut": "ctd",
    "District of D.C.": "dcd",
    "District of Delaware": "ded",
    "Middle District of Georgia": "gamd",
    "Northern District of Georgia": "gand",
    "District of Hawaii": "hid",
    "District of Idaho": "idd",
    "Central District of Illinois": "ilcd",
    "Eastern District of Kentucky": "kyed",
    "District of Maine": "med",
    "District of Maryland": "mdd",
    "District of Massachusetts": "mad",
    "Western District of Michigan": "miwd",
    "District of Minnesota": "mnd",
    "District of Nevada": "nvd",
    "District of New Hampshire": "nhd",
    "District of New Jersey": "njd",
    "District of New Mexico": "nmd",
    "Northern District of New York": "nynd",
    "Western District of Oklahoma": "okwd",
    "District of Oregon": "ord",
    "Western District of Pennsylvania": "pawd",
    "District of Rhode Island": "rid",
    "District of Utah": "utd",
    "District of Vermont": "vtd",
    "Eastern District of Virginia": "vaed",
    "Western District of Washington": "wawd",
    "Southern District of West Virginia": "wvsd",
    "Western District of Wisconsin": "wiwd",
    # Courts of appeals (closed set, all 13 verified against CourtListener /courts/)
    "First Circuit": "ca1",
    "Second Circuit": "ca2",
    "Third Circuit": "ca3",
    "Fourth Circuit": "ca4",
    "Fifth Circuit": "ca5",
    "Sixth Circuit": "ca6",
    "Seventh Circuit": "ca7",
    "Eighth Circuit": "ca8",
    "Ninth Circuit": "ca9",
    "Tenth Circuit": "ca10",
    "Eleventh Circuit": "ca11",
    "D.C. Circuit": "cadc",
    "Federal Circuit": "cafc",
}

REQUIRED_COLUMNS = ("State", "Current Federal Court", "Current Case Number")
ROW_COUNT_MIN, ROW_COUNT_MAX = 25, 40   # ~32 physical rows (31 jurisdictions, GA doubled)


def _clean(text: str | None) -> str:
    """Collapse whitespace and drop NBSP; an empty/NBSP-only cell becomes ''."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _state_name(state: str) -> str:
    """Provisional-caption state: drop a trailing footnote marker like ' (1)'."""
    return re.sub(r"\s*\(\d+\)\s*$", "", state).strip()


def _notes(claims: str, status: str, key_decisions: str) -> str:
    """The B2 framing: what the case is about, from tracker prose (never the docket)."""
    parts = []
    if claims:
        parts.append(f"Claims: {claims}")
    if status:
        parts.append(f"Status: {status}")
    if key_decisions:
        parts.append(f"Key decisions: {key_decisions}")
    return " | ".join(parts)


def _find_suit_table(soup: BeautifulSoup):
    """The one table whose header carries 'Current Case Number'."""
    for table in soup.find_all("table"):
        head = table.find("thead") or table
        if "Current Case Number" in head.get_text(" ", strip=True):
            return table
    raise RuntimeError("suit table not found (no table header contains 'Current Case Number')")


def parse_table(html: str) -> list[dict]:
    """Parse the tracker HTML into sorted seed dicts. Pure -- no network, no I/O.

    Warns (never raises) on a court name missing from COURT_IDS and on a row
    count far from the ~32 expected; a wrong-shaped layout is surfaced loudly,
    not silently mis-scraped.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = _find_suit_table(soup)

    head = table.find("thead") or table
    headers = [_clean(th.get_text()) for th in head.find_all(["th", "td"])]
    idx = {h: i for i, h in enumerate(headers)}
    missing = [c for c in REQUIRED_COLUMNS if c not in idx]
    if missing:
        raise RuntimeError(f"tracker layout changed: missing columns {missing}; headers={headers}")

    body = table.find("tbody") or table
    rows: list[dict] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(headers):
            continue  # a colspan footnote row, not a data row

        def col(name: str) -> str:
            return _clean(cells[idx[name]].get_text(" ", strip=True)) if name in idx else ""

        state = col("State")
        if not state:
            continue
        court = col("Current Federal Court")
        court_id = COURT_IDS.get(court)
        if court_id is None:
            print(f"WARN unmapped court {court!r} (state {state!r}) -> court_id null; "
                  f"add + verify its CourtListener id in COURT_IDS", file=sys.stderr)
        rows.append({
            "caption": f"United States v. {_state_name(state)}",
            "category": CATEGORY,
            "court": court,
            "court_id": court_id,
            "docket_number": col("Current Case Number"),
            "notes": _notes(col("Claims"), col("Status"), col("Key Decisions")),
            "state": state,
        })

    _warn_on_shape(rows)
    rows.sort(key=lambda r: (r["state"], r["docket_number"]))
    return rows


def _warn_on_shape(rows: list[dict]) -> None:
    if not (ROW_COUNT_MIN <= len(rows) <= ROW_COUNT_MAX):
        print(f"WARN parsed {len(rows)} rows, expected ~32 -- tracker layout may have changed",
              file=sys.stderr)
    unmapped = [r["state"] for r in rows if r["court_id"] is None]
    if unmapped:
        print(f"WARN {len(unmapped)} row(s) with no court_id (will not resolve): {unmapped}",
              file=sys.stderr)


def serialize(rows: list[dict]) -> str:
    """Deterministic artifact text: sorted keys, indented, LF, no wall-clock."""
    return json.dumps(rows, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_artifact(rows: list[dict], path: str = ARTIFACT_PATH) -> str:
    text = serialize(rows)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return text


def tracker_url(sources: dict | None = None) -> str:
    """The UW SDRI tracker url from config (already in litigation.seed_trackers)."""
    src = sources or config.load_sources()
    for t in src["litigation"].get("seed_trackers", []):
        if "statedemocracy.law.wisc.edu" in (t.get("url") or ""):
            return t["url"]
    raise RuntimeError("UW SDRI tracker url not found in litigation.seed_trackers")


def main() -> int:
    config.load_env()
    html = common.http_get_text(tracker_url(), headers={"User-Agent": USER_AGENT})
    rows = parse_table(html)
    write_artifact(rows)
    mapped = sum(1 for r in rows if r["court_id"])
    print(f"wrote {len(rows)} cases to {ARTIFACT_PATH} ({mapped} resolvable, "
          f"{len(rows) - mapped} unmapped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
