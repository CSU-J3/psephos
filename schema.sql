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
    -- The CourtListener docket-entry object an A1 item presents (R1, Corey 2026-09-30):
    -- set when the item is written from a polled entry, or when the id backfill ties
    -- the item's row to its object. NULL on every other channel and on B2 items.
    cl_entry_id      INTEGER,
    -- The fold (R1 step d, collectors/cl_fold.py): how a page reads items as ENTRIES. No
    -- reader before the switch selects these. merged_into names the item that presents
    -- this one's entry (NULL: this item presents one); display_* are the presenting
    -- item's survivor title, text and date; updated_at is the group's latest fetched_at.
    merged_into      INTEGER,
    display_title    TEXT,
    display_summary  TEXT,
    display_at       TEXT,
    updated_at       TEXT,
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_items_channel  ON items(channel);
CREATE INDEX IF NOT EXISTS idx_items_occurred ON items(occurred_at);
CREATE INDEX IF NOT EXISTS idx_items_bill     ON items(bill_id);
CREATE INDEX IF NOT EXISTS idx_items_case     ON items(case_id);
CREATE INDEX IF NOT EXISTS idx_items_state_bill ON items(state_bill_id);
CREATE INDEX IF NOT EXISTS idx_items_cl_entry ON items(cl_entry_id);

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
    date_terminated TEXT,                    -- CourtListener's own date_terminated, kept rather than
                                             -- collapsed. `status` above is derived from exactly this
                                             -- value and carries one bit of it; the DATE was read on
                                             -- every resolve and every status refresh and thrown away
                                             -- from the column's creation until handoff 97.
                                             -- WHAT NEEDED IT, and why one bit was not enough: the
                                             -- read layer derives "a court rejected this demand" from
                                             -- the docket entries at the disposition, and a docket's
                                             -- interlocutory orders use the SAME vocabulary as its
                                             -- terminal one -- "Motion to Compel is DENIED" appears
                                             -- months before the order that ends the case. Scoped to
                                             -- this date the rule agreed with a per-case eyeball on
                                             -- 20 of 20 dockets; unscoped, on 10 of 20. The date is
                                             -- the whole difference between a derivation and a list.
                                             -- NULL is correct and expected on a pending docket: it
                                             -- is what CourtListener sends, and `status` reads
                                             -- 'pending' from the same absence.
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

-- Every text a docket entry has been served with, one row each: the revision log (R1,
-- Corey 2026-09-30). A re-described entry adds a row and keeps the old one, and every
-- row keeps its id -- recheck-flag watermarks and verdicts in docs/gates.yaml point at
-- these ids. Which rows are ONE entry is `cl_entries`' job, below.
CREATE TABLE IF NOT EXISTS case_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    entry_at     TEXT,
    description  TEXT,
    document_url TEXT,
    cl_entry_id  INTEGER,                    -- the CourtListener docket-entry id this text was
                                             -- served on. Written on every row since 2026-09-30,
                                             -- and on older rows by the id backfill walk; NULL
                                             -- on a row nothing has tied to an entry yet.
    seen_at      TEXT,                       -- when psephos first held this text. Exact since
                                             -- 2026-09-30; NULL on older rows (their items'
                                             -- fetched_at and the id order bound it).
    UNIQUE(case_id, entry_at, description)
);
CREATE INDEX IF NOT EXISTS idx_case_entries_cl ON case_entries(cl_entry_id);

-- One row per CourtListener docket-entry object (R1, Corey 2026-09-30): the entry, with
-- its text and date as mutable fields. `current_row` is the case_entries row holding the
-- text upstream serves now. Written by collectors/cl_objects.py: the poll path for every
-- entry a poll serves, and the id backfill walk for the rows held before ids were kept.
-- A NEW TABLE, so no _MIGRATIONS entry.
CREATE TABLE IF NOT EXISTS cl_entries (
    cl_entry_id   INTEGER PRIMARY KEY,       -- CourtListener's docket-entry id
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    entry_number  INTEGER,
    entry_at      TEXT,                      -- the date upstream serves now
    description   TEXT,                      -- the text upstream serves now, derived as
                                             -- write_entries derives it
    current_row   INTEGER REFERENCES case_entries(id),  -- the row holding that text, or the
                                             -- newest row it has when the walk finds its
                                             -- text unheld (reported stale); NULL when the
                                             -- text is another object's row on the same day
                                             -- (held apart) or psephos never held it
    held          INTEGER NOT NULL DEFAULT 1,  -- 0: seen by the id backfill walk only
    first_seen_at TEXT,                      -- when psephos first HELD its text: now for a
                                             -- new text; a legacy row's seen_at or item
                                             -- fetched_at; NULL when neither exists (step c
                                             -- bounds it by the id order). Never the walk's time.
    updated_at    TEXT,                      -- when psephos last saw its text or date move,
                                             -- on the same evidence rule
    date_modified TEXT,                      -- CourtListener's, as last served
    time_filed    TEXT,                      -- CourtListener's; with date_created and
    date_created  TEXT,                      -- desc_source ('entry' | 'document'), the tier-2
    desc_source   TEXT,                      -- fingerprint the D0 found on 3 of 3 pairs
    twin_of       INTEGER REFERENCES cl_entries(cl_entry_id),  -- tier 2: a second object for
                                             -- the same minute entry. psephos's assertion,
                                             -- never upstream's: set by a checked rule or a
                                             -- person, named in twin_rule, reversible
    twin_rule     TEXT,
    twin_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_cl_entries_case ON cl_entries(case_id);

-- THE SWITCH'S TWO READS (R1 step d, Corey 2026-09-30). Defined here so the collector,
-- the export, the audit and the web read ONE definition; nothing reads them before the
-- switch. Dropped and recreated on every init, so an edit here always takes.
--
-- record_items: items as entries. A folded item (merged_into) drops out; the item that
-- presents an entry carries its survivor title, text and date (collectors/cl_fold.py).
-- fetched_at is the presenting item's own, the entry's first-seen time.
DROP VIEW IF EXISTS record_items;
CREATE VIEW record_items AS
SELECT id, channel, source_id, source_url,
       COALESCE(display_title, title) AS title,
       COALESCE(display_summary, summary) AS summary,
       COALESCE(display_at, occurred_at) AS occurred_at,
       fetched_at, admiralty_source, admiralty_info, confidence, bill_id, case_id,
       state_bill_id, outlet, content_hash, raw_json, cl_entry_id, updated_at
  FROM items
 WHERE merged_into IS NULL;

-- record_entries: one row per docket entry psephos holds. An entry is a held CourtListener
-- object that is not a tier-2 twin (its current text and date), or a row no object claims
-- (each such row is its own entry until something ties it). Page counts, latest_entry_at
-- and the outcomes read this, not case_entries.
DROP VIEW IF EXISTS record_entries;
CREATE VIEW record_entries AS
SELECT o.case_id, COALESCE(o.entry_at, e.entry_at) AS entry_at,
       COALESCE(e.description, o.description) AS description,
       o.cl_entry_id, o.current_row AS row_id
  FROM cl_entries o LEFT JOIN case_entries e ON e.id = o.current_row
 WHERE o.held = 1 AND o.twin_of IS NULL
UNION ALL
SELECT e.case_id, e.entry_at, e.description, NULL AS cl_entry_id, e.id AS row_id
  FROM case_entries e
 WHERE e.cl_entry_id IS NULL;

-- The id backfill walk's receipt, one row per docket walked (R1 step b, ruling 6). A
-- docket with a row here is not walked again. The counts are its report: what the walk
-- attached by exact text, by the safe normalization and by document number, and what it
-- left unattached, never held, stale or held apart.
CREATE TABLE IF NOT EXISTS cl_backfill (
    case_id      TEXT PRIMARY KEY REFERENCES cases(case_id),
    walked_at    TEXT NOT NULL,
    requests     INTEGER NOT NULL,
    rows         INTEGER NOT NULL,
    objects      INTEGER NOT NULL,
    exact        INTEGER NOT NULL,
    adopted      INTEGER NOT NULL,
    token        INTEGER NOT NULL,
    token_shared INTEGER NOT NULL,
    unattached   INTEGER NOT NULL,
    never_held   INTEGER NOT NULL,
    stale        INTEGER NOT NULL,
    apart        INTEGER NOT NULL
);

-- The id backfill's failed walks, one row per docket until it walks (then deleted). What
-- moves a docket that fails every time behind the healthy ones (backfill_due), and what
-- makes it loud after litigation.BACKFILL_LOUD_AFTER failures (a CUT naming the docket).
CREATE TABLE IF NOT EXISTS cl_backfill_attempts (
    case_id    TEXT PRIMARY KEY REFERENCES cases(case_id),
    failures   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_at    TEXT
);

-- CourtListener requests per UTC day, so the id backfill is reported against the rest of
-- the day's litigation spend (ruling 6). Attempts, retries included: see litigation.Spend.
CREATE TABLE IF NOT EXISTS cl_usage (
    day        TEXT PRIMARY KEY,
    requests   INTEGER NOT NULL DEFAULT 0,
    backfill   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
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

-- LegiScan query ledger: every HTTP attempt against api.legiscan.com, by month.
-- Attempts, not logical calls: a retried getBill is up to 4 queries upstream.
-- Written by the state collector (in its per-state commit) and by every tool or
-- script that calls LegiScan, additively. It is OUR count: the LegiScan API has no
-- usage op (manual rev. 20250317), so the only upstream reading is the API status
-- page. See collectors/state.py::UsageMeter and ledger_month for the clock.
CREATE TABLE IF NOT EXISTS legiscan_usage (
    month      TEXT PRIMARY KEY,   -- YYYY-MM, UTC calendar month (pending the status-page reading)
    queries    INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    -- The client-side cache-hit proxy (handoff 98b §4d): answered getMasterList
    -- responses, and those that moved no stored change_hash. Born with the session
    -- cadence, so a month's values count only from its deploy -- which is what makes
    -- October's share a post-deploy figure by construction. The API Status page
    -- stays the instrument of record.
    masterlists           INTEGER NOT NULL DEFAULT 0,
    unchanged_masterlists INTEGER NOT NULL DEFAULT 0
);

-- LegiScan sessions of the WATCHED states, from getSessionList (handoff 98b §4
-- revised and rulings). One row per (state, session_id).
--   state_id is MEASURED: the one-time getSessionList&state=XX bootstrap stores what
--     LegiScan returns, because the manual documents sessions by state_id only and
--     publishes no mapping. Never hard-coded. (The live reply also carries state_abbr,
--     used as a cross-check on every national call.)
--   hash_seen_at is OUR observation time of the current dataset_hash (getSessionList
--     carries no dataset_date).
--   masterlist_hash is the DONE-MARKER: "<dataset_hash>|<filter fingerprint>" as of
--     the last master list this project FULLY processed for the session (every
--     changed bill fetched). An adjourned session is polled only when it is stale --
--     the dataset_hash moved, or the election filter did (collectors/state.py
--     filter_fingerprint). Comparing against the freshly stored dataset_hash instead
--     would mark a failed or budget-cut poll as done, and an adjourned session's
--     dataset rarely moves again; leaving the filter out would strand newly-matching
--     bills in every adjourned session after a term broadening.
CREATE TABLE IF NOT EXISTS state_sessions (
    state           TEXT NOT NULL,
    session_id      INTEGER NOT NULL,
    state_id        INTEGER NOT NULL,
    sine_die        INTEGER NOT NULL,
    prefile         INTEGER NOT NULL,
    prior           INTEGER NOT NULL,
    special         INTEGER NOT NULL,
    session_name    TEXT,
    dataset_hash    TEXT NOT NULL,
    hash_seen_at    TEXT NOT NULL,
    masterlist_hash TEXT,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (state, session_id)
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

-- The run heartbeat: one row per collect.yml run, written at run END by a final
-- workflow step, never by a collector. It is the only table in this schema the
-- WORKFLOW writes rather than a collector, and the reason is that no process spans
-- a run: collect.yml invokes six separate `python -m collectors.X` in one step, and
-- no one of them knows the run's total. The step carries `if: always()`, so a failed
-- run still leaves a row and a MISSED run is the only thing that leaves none.
--
-- WHY IT EXISTS. `MAX(fetched_at)` over items cannot answer "has collection stopped".
-- fetched_at is written once on first insert and never updated (insert_ignore on
-- UNIQUE(content_hash)), so a healthy run that collected nothing new leaves it exactly
-- where a missed run would -- measured, 3 of 51 scheduled runs since 58c6aca committed
-- nothing at all. The page compares against finished_at here instead.
--
-- NEVER EXPORTED. No snapshot carries it and tests/test_snapshot_staging does not
-- reach it; the read layer queries it live.
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,      -- GITHUB_RUN_ID; upserted, so a re-run replaces
    slot          TEXT NOT NULL,         -- the cron string, or 'dispatch'
    started_at    TEXT NOT NULL,         -- ISO 8601, job start
    finished_at   TEXT NOT NULL,         -- ISO 8601, when this row was written
    items_written INTEGER NOT NULL,      -- items whose fetched_at falls inside the run
    conclusion    TEXT NOT NULL          -- job.status: success | failure | cancelled
);
CREATE INDEX IF NOT EXISTS idx_runs_finished ON runs(finished_at);

-- channel_runs: one row per class a credentialed channel met in one collect run
-- (unit 99, Corey, 2026-09-28). Written by the collector (run_signals.RunSignals.flush),
-- read by the run's final step (tools/collect_verdict.py), which turns the run red on a
-- loud class and comments on the standing `collect red` issue.
--
-- class is one of: ok | credential failure | missing secret | no OK replies | cut short |
-- deferred | unreached. `ok` means the channel reached its source this run, and the latest
-- state `ok` row is state's receipt (R7, R9). `unreached` means it ran to its end, met no
-- other class and got no OK reply, so every run that ends leaves a row and a missing one
-- means a collector that died. evidence is the printed line's suffix, already scrubbed of
-- the channel's secret values; '' when the line has none.
--
-- A NEW TABLE, so no _MIGRATIONS entry (that list is for ALTERs on existing tables).
-- NEVER EXPORTED: the verdict reads it live, like `runs`.
CREATE TABLE IF NOT EXISTS channel_runs (
    run_id     TEXT NOT NULL,            -- GITHUB_RUN_ID ('.N' from a re-run's 2nd attempt), or 'local'
    channel    TEXT NOT NULL,            -- legislation | litigation | state
    class      TEXT NOT NULL,
    evidence   TEXT NOT NULL,
    written_at TEXT NOT NULL,            -- ISO 8601
    PRIMARY KEY (run_id, channel, class)
);
CREATE INDEX IF NOT EXISTS idx_channel_runs_channel ON channel_runs(channel, class, written_at);
