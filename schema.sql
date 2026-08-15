-- psephos schema (SQLite)
-- One unified events table, dimension tables for bills and cases,
-- a source registry, and dedup bookkeeping for the news layer.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Source registry: every feed/endpoint with its default Admiralty grade.
CREATE TABLE IF NOT EXISTS sources (
    id               TEXT PRIMARY KEY,       -- slug, e.g. 'congress-gov', 'courtlistener'
    name             TEXT NOT NULL,
    channel          TEXT NOT NULL,          -- legislation | executive | litigation | news | state
    kind             TEXT NOT NULL,          -- api | rss | tracker
    url              TEXT,
    admiralty_source TEXT NOT NULL,          -- A-F default reliability
    admiralty_info   TEXT,                   -- 1-6 default credibility (often set per item)
    enabled          INTEGER NOT NULL DEFAULT 1,
    notes            TEXT
);

-- Unified change/event records across all channels.
CREATE TABLE IF NOT EXISTS items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel          TEXT NOT NULL,          -- legislation | executive | litigation | news | state
    source_id        TEXT NOT NULL REFERENCES sources(id),
    source_url       TEXT NOT NULL,
    title            TEXT NOT NULL,
    summary          TEXT,
    occurred_at      TEXT,                   -- ISO 8601, when the event happened
    fetched_at       TEXT NOT NULL,          -- ISO 8601, when we pulled it
    admiralty_source TEXT NOT NULL,          -- A-F (may override the source default)
    admiralty_info   TEXT NOT NULL,          -- 1-6
    confidence       TEXT,                   -- high | moderate | low (analyst judgment, optional)
    bill_id          TEXT REFERENCES bills(bill_id),
    case_id          TEXT REFERENCES cases(case_id),
    state_bill_id    TEXT REFERENCES state_bills(state_bill_id),
    -- The PUBLISHER, which is not the same thing as source_id (the delivery pipe).
    -- One aggregator source carries hundreds of outlets, and the spec grades
    -- outlets, so the two must be stored separately or the grade answers the wrong
    -- question. PROVENANCE DIFFERS BY ROW and matters: items collected from
    -- 2026-08-15 carry the publisher's own structured <source> element out of the
    -- feed, while rows backfilled before that date carry a parse of the
    -- ` - Publisher` suffix Google News appends to the title -- a field the
    -- publisher controls but does not intend as data. Measured 139/139 correct on
    -- the B2-outlet cohort, but they are not the same evidence. NULL on
    -- non-aggregated feeds, where source_id already names the outlet.
    outlet           TEXT,
    content_hash     TEXT NOT NULL,          -- sha256 of canonical content, for dedup
    raw_json         TEXT,                   -- original payload, kept for traceability
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_items_channel  ON items(channel);
CREATE INDEX IF NOT EXISTS idx_items_occurred ON items(occurred_at);
CREATE INDEX IF NOT EXISTS idx_items_bill     ON items(bill_id);
CREATE INDEX IF NOT EXISTS idx_items_case     ON items(case_id);
CREATE INDEX IF NOT EXISTS idx_items_state_bill ON items(state_bill_id);

-- Watched federal bills and their vehicles.
CREATE TABLE IF NOT EXISTS bills (
    bill_id          TEXT PRIMARY KEY,       -- e.g. 'hr22-119', 's3752-119'
    congress         INTEGER NOT NULL,
    bill_type        TEXT NOT NULL,          -- hr | s | hjres | sjres
    number           INTEGER NOT NULL,
    title            TEXT,
    short_title      TEXT,
    sponsor          TEXT,
    introduced_at    TEXT,
    latest_action    TEXT,
    latest_action_at TEXT,
    status           TEXT,
    is_vehicle       INTEGER NOT NULL DEFAULT 0,  -- 1 if an unrelated bill carrying voting provisions
    watch_reason     TEXT,
    cosponsor_count  INTEGER,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS bill_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id     TEXT NOT NULL REFERENCES bills(bill_id),
    action_at   TEXT,
    action_text TEXT,
    action_code TEXT,
    UNIQUE(bill_id, action_at, action_text)
);

CREATE TABLE IF NOT EXISTS bill_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id         TEXT NOT NULL REFERENCES bills(bill_id),
    related_bill_id TEXT NOT NULL,
    relation_type   TEXT,                    -- companion | amendment | vehicle | identical | procedural
    UNIQUE(bill_id, related_bill_id, relation_type)
);

-- Litigation dockets (voter-data suits, EO challenges, registration-law challenges).
CREATE TABLE IF NOT EXISTS cases (
    case_id         TEXT PRIMARY KEY,        -- courtlistener docket id, or slug if seeded by hand
    caption         TEXT NOT NULL,
    court           TEXT,
    docket_number   TEXT,
    filed_at        TEXT,
    status          TEXT,                    -- pending | terminated, and nothing else: the only
                                             -- expression that writes it is `case_status` in
                                             -- collectors/litigation.py, which keys solely on
                                             -- CourtListener's date_terminated. (This comment read
                                             -- `dismissed | appeal | settled | decided` from the
                                             -- column's creation until handoff 27; no such value was
                                             -- ever written.)
    category        TEXT,                    -- voter-data | executive-order | registration-law | redistricting | other
    state           TEXT,                    -- the jurisdiction DOJ sued, e.g. 'Georgia', 'DC'. Written by
                                             -- `upsert_case` in collectors/litigation.py from the tracker
                                             -- artifact's `state` field, through `normalize_state`, which
                                             -- strips the per-docket disambiguation suffix (`Georgia (1)`
                                             -- -> `Georgia`). NOT derivable from `court`: a circuit hears
                                             -- appeals from several states, so `First Circuit` alone covers
                                             -- RI, MA, ME and NH -- 14 of the 40 rows are circuit rows and
                                             -- court-derivation fails on every one. NULL is meaningful and
                                             -- correct on the two config seeds (Common Cause v. DOJ, LWV v.
                                             -- DHS), which are suits against federal agencies and belong in
                                             -- no per-state view. A terminated row that has dropped out of
                                             -- the artifact keeps whatever value it had, since nothing
                                             -- upserts it again; the six that predate this column were
                                             -- filled once by scripts/backfill_case_state.py.
    plaintiff       TEXT,
    defendant       TEXT,
    latest_entry_at TEXT,                    -- DERIVED: MAX(case_entries.entry_at) for this case.
                                             -- Recomputed by `write_entries` in
                                             -- collectors/litigation.py, the only path that
                                             -- inserts into case_entries. It is NOT assigned from
                                             -- the polled batch: an incremental window can hold
                                             -- only a late-backfilled old filing, and assigning
                                             -- moved this column BACKWARDS on 12 of 40 rows
                                             -- between 2026-07-22 and 2026-08-14. Check the
                                             -- invariant with `python -m tools.coverage_audit`
                                             -- (section 4, expect 0); repair with
                                             -- `python -m scripts.repair_latest_entry`.
    entries_synced_at TEXT,                  -- max CourtListener date_modified ingested for this
                                             -- docket; NULL means never bootstrapped (full walk next poll)
    superseded_by   TEXT REFERENCES cases(case_id),  -- this docket's continuation: the appeal or
                                             -- refile that replaced it. Set on the terminated row,
                                             -- pointing forward; NULL for live dockets. The reverse
                                             -- (successor -> predecessor) is a query, not a column,
                                             -- so the collector's upsert path never has to preserve it.
    status_checked_at TEXT,                  -- when `status` was last READ from CourtListener, not
                                             -- when the docket was last polled (that is a different
                                             -- question entirely, and entries_synced_at is not it
                                             -- either -- see its note above). Written by
                                             -- refresh_status() on every pass INCLUDING no-ops,
                                             -- which is what makes it a poll receipt; `updated_at`
                                             -- moves only when the value actually changed.
    source_url      TEXT,
    seeded_from     TEXT,                    -- which tracker the case came from
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS case_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    entry_at     TEXT,
    description  TEXT,
    document_url TEXT,
    UNIQUE(case_id, entry_at, description)
);

-- State bills promoted to first-class, parallel to `bills`. PK is the LegiScan
-- numeric bill_id as text: globally unique and stable, the way `cases` key on the
-- CourtListener docket id. items.state_bill_id references it; the /state-bill/[id]
-- route (5b-c) keys on it. is_vehicle is reserved for 5b-b and stays 0 here.
CREATE TABLE IF NOT EXISTS state_bills (
    state_bill_id  TEXT PRIMARY KEY,       -- str(LegiScan bill_id)
    state          TEXT NOT NULL,
    bill_number    TEXT NOT NULL,
    session        TEXT,
    title          TEXT,
    description    TEXT,
    status         TEXT,                    -- LegiScan numeric status code as text; display-mapped in 5b-c
    url            TEXT,
    is_vehicle     INTEGER NOT NULL DEFAULT 0,
    last_action    TEXT,
    last_action_at TEXT,
    change_hash    TEXT,
    updated_at     TEXT
);

-- LegiScan change-hash bookkeeping: last-seen hash per state bill, so the poll
-- only getBill's bills whose hash moved. Bookkeeping like dedup_seen, not a dimension.
CREATE TABLE IF NOT EXISTS state_seen (
    bill_id     INTEGER PRIMARY KEY,   -- LegiScan bill_id
    change_hash TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Two-stage dedup bookkeeping for the news layer.
-- Stage 1: canonical URL. Stage 2: content-hash plus normalized-title similarity.
CREATE TABLE IF NOT EXISTS dedup_seen (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT,
    content_hash  TEXT NOT NULL,
    title_norm    TEXT,
    first_seen    TEXT NOT NULL,
    item_id       INTEGER REFERENCES items(id),
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_dedup_url   ON dedup_seen(canonical_url);
CREATE INDEX IF NOT EXISTS idx_dedup_title ON dedup_seen(title_norm);
