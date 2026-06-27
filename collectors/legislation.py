"""Legislation collector — Congress.gov API.

For each watchlist bill (config/sources.yaml -> legislation.watchlist) this pulls
the bill, its actions, amendments, and related bills, then:
  - upserts the bill into `bills`,
  - appends new rows to `bill_actions` and `bill_relations`,
  - writes an `items` row (grade A1) for each newly seen action.

The amendments and related-bills endpoints are the point: they catch a SAVE-Act
provision being attached to an unrelated vehicle (S. 1383).

Run from the repo root:  python -m collectors.legislation
"""

from __future__ import annotations

import json
import sys

import common
import config
import db

SOURCE_ID = "congress-gov"
CHANNEL = "legislation"
PAGE_LIMIT = 250  # Congress.gov max page size

# bill_type -> congress.gov web-URL chamber segment
_WEB_CHAMBER = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution",
    "sres": "senate-resolution",
}


def bill_web_url(congress: int, bill_type: str, number: int) -> str:
    chamber = _WEB_CHAMBER.get(bill_type, "bill")
    return f"https://www.congress.gov/bill/{congress}th-congress/{chamber}/{number}"


def related_id(congress, bill_type, number) -> str:
    """Build a psephos bill_id (e.g. 's1383-119') from API type/number/congress."""
    return f"{str(bill_type).lower()}{number}-{congress}"


def map_relation(rel_text: str | None, related_bill_id: str, current_is_vehicle: bool,
                 vehicle_ids: set[str], watch_ids: set[str]) -> str:
    """Classify a related-bill link, flagging the vehicle maneuver.

    'vehicle' fires only when the link crosses between the vehicle bill and a
    *watched* substantive bill (in either direction) -- that cross-link is the
    maneuver. A vehicle bill's other related bills are classified normally.
    """
    crosses = (
        (current_is_vehicle and related_bill_id in watch_ids and related_bill_id not in vehicle_ids)
        or (not current_is_vehicle and related_bill_id in vehicle_ids)
    )
    if crosses:
        return "vehicle"
    t = (rel_text or "").lower()
    if "identical" in t:
        return "identical"
    if "companion" in t:
        return "companion"
    if "procedural" in t:
        return "procedural"
    return "related"


def fetch_page_list(base: str, path: str, key: str, field: str, throttle: float) -> list:
    """Fetch every page of a list endpoint, accumulating `field` items."""
    out: list = []
    offset = 0
    while True:
        data = common.http_get(
            f"{base}{path}",
            params={"api_key": key, "format": "json", "limit": PAGE_LIMIT, "offset": offset},
            throttle=throttle,
        )
        batch = data.get(field) or []
        out.extend(batch)
        count = data.get("pagination", {}).get("count")
        offset += PAGE_LIMIT
        if not batch or len(batch) < PAGE_LIMIT:
            break
        if count is not None and offset >= count:
            break
    return out


def register_source(conn, base: str, gsource: str, ginfo: str) -> None:
    db.upsert(conn, "sources", {
        "id": SOURCE_ID,
        "name": "Congress.gov API",
        "channel": CHANNEL,
        "kind": "api",
        "url": base,
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "enabled": 1,
        "notes": "Primary government record; federal bills, actions, amendments, related bills.",
    }, pk="id")


def collect_bill(conn, base: str, key: str, throttle: float, entry: dict,
                 gsource: str, ginfo: str, vehicle_ids: set[str], watch_ids: set[str]) -> dict:
    """Collect one watchlist bill. Returns a per-bill counts summary."""
    bill_id = entry["bill_id"]
    congress = entry["congress"]
    bill_type = entry["type"]
    number = entry["number"]
    is_vehicle = bool(entry.get("is_vehicle"))
    stem = f"/bill/{congress}/{bill_type}/{number}"

    detail = common.http_get(
        f"{base}{stem}", params={"api_key": key, "format": "json"}, throttle=throttle
    ).get("bill", {})

    sponsors = detail.get("sponsors") or []
    sponsor = sponsors[0].get("fullName") if sponsors else None
    latest = detail.get("latestAction") or {}
    cosponsors = detail.get("cosponsors") or {}
    web_url = bill_web_url(congress, bill_type, number)

    db.upsert(conn, "bills", {
        "bill_id": bill_id,
        "congress": congress,
        "bill_type": bill_type,
        "number": number,
        "title": detail.get("title"),
        "short_title": entry.get("short_title"),
        "sponsor": sponsor,
        "introduced_at": common.to_iso(detail.get("introducedDate")),
        "latest_action": latest.get("text"),
        "latest_action_at": common.to_iso(latest.get("actionDate")),
        "status": latest.get("text"),
        "is_vehicle": 1 if is_vehicle else 0,
        "watch_reason": entry.get("watch_reason"),
        "cosponsor_count": cosponsors.get("count"),
        "updated_at": common.now_iso(),
    }, pk="bill_id")

    counts = {"bill_id": bill_id, "new_actions": 0, "new_relations": 0, "new_items": 0}

    # Actions -> bill_actions + an items row per newly seen action.
    for action in fetch_page_list(base, f"{stem}/actions", key, "actions", throttle):
        action_at = common.to_iso(action.get("actionDate"))
        action_text = action.get("text")
        if not action_text:
            continue
        added = db.insert_ignore(conn, "bill_actions", {
            "bill_id": bill_id,
            "action_at": action_at,
            "action_text": action_text,
            "action_code": action.get("actionCode"),
        })
        if not added:
            continue
        counts["new_actions"] += 1
        item_added = db.insert_ignore(conn, "items", {
            "channel": CHANNEL,
            "source_id": SOURCE_ID,
            "source_url": web_url,
            "title": f"{bill_id}: {action_text}"[:300],
            "summary": action_text,
            "occurred_at": action_at,
            "fetched_at": common.now_iso(),
            "admiralty_source": gsource,
            "admiralty_info": ginfo,
            "confidence": None,
            "bill_id": bill_id,
            "case_id": None,
            "content_hash": common.content_hash(bill_id, action_at, action_text),
            "raw_json": json.dumps(action, separators=(",", ":")),
        })
        if item_added:
            counts["new_items"] += 1

    # Amendments to this bill -> bill_relations (relation_type 'amendment').
    for amd in fetch_page_list(base, f"{stem}/amendments", key, "amendments", throttle):
        rid = related_id(amd.get("congress", congress), amd.get("type"), amd.get("number"))
        if db.insert_ignore(conn, "bill_relations", {
            "bill_id": bill_id,
            "related_bill_id": rid,
            "relation_type": "amendment",
        }):
            counts["new_relations"] += 1

    # Related bills -> bill_relations (vehicle / identical / companion / ...).
    for rel in fetch_page_list(base, f"{stem}/relatedbills", key, "relatedBills", throttle):
        rid = related_id(rel.get("congress"), rel.get("type"), rel.get("number"))
        details = rel.get("relationshipDetails") or [{}]
        rel_text = details[0].get("type") if details else None
        if db.insert_ignore(conn, "bill_relations", {
            "bill_id": bill_id,
            "related_bill_id": rid,
            "relation_type": map_relation(rel_text, rid, is_vehicle, vehicle_ids, watch_ids),
        }):
            counts["new_relations"] += 1

    return counts


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    leg = sources["legislation"]
    base = leg["api"]["base"].rstrip("/")
    key = config.require_env(leg["api"]["key_env"])
    rate = leg["api"].get("rate_limit_per_hour")
    throttle = (3600.0 / rate) if rate else 0.0
    gsource, ginfo = config.grade(leg.get("default_grade"))
    watchlist = leg.get("watchlist", [])
    vehicle_ids = {b["bill_id"] for b in watchlist if b.get("is_vehicle")}
    watch_ids = {b["bill_id"] for b in watchlist}

    conn = db.connect()
    try:
        register_source(conn, base, gsource, ginfo)
        conn.commit()
        for entry in watchlist:
            try:
                counts = collect_bill(conn, base, key, throttle, entry, gsource, ginfo, vehicle_ids, watch_ids)
                conn.commit()
                print(
                    f"  {counts['bill_id']:<12} "
                    f"+{counts['new_actions']} actions  "
                    f"+{counts['new_relations']} relations  "
                    f"+{counts['new_items']} items"
                )
            except Exception as exc:  # one bad bill shouldn't sink the run
                conn.rollback()
                print(f"  {entry['bill_id']:<12} ERROR: {exc}", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
