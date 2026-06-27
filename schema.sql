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
    content_hash     TEXT NOT NULL,          -- sha256 of canonical content, for dedup
    raw_json         TEXT,                   -- original payload, kept for traceability
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_items_channel  ON items(channel);
CREATE INDEX IF NOT EXISTS idx_items_occurred ON items(occurred_at);
CREATE INDEX IF NOT EXISTS idx_items_bill     ON items(bill_id);
CREATE INDEX IF NOT EXISTS idx_items_case     ON items(case_id);

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
    status          TEXT,                    -- pending | dismissed | appeal | settled | decided
    category        TEXT,                    -- voter-data | executive-order | registration-law | redistricting | other
    plaintiff       TEXT,
    defendant       TEXT,
    latest_entry_at TEXT,
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
