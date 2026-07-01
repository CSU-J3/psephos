# psephos, project instructions

Psephos is the pebble an Athenian citizen dropped into an urn to cast a vote, the root of "psephology," the study of elections.

A monitor for the erosion of voting rights in the United States. It tracks four channels of federal pressure, surfaces the procedural maneuvers a plain bill tracker misses, and presents every change with its source and an Admiralty grade so the record carries the argument.

This document is the build spec, kept current with the as-built system: phases 1–3 have shipped and run unattended on the 6-hour cron. It is written to be read by Claude Code at the start of each session. Follow the review-gated workflow at the bottom: propose a plan, get approval, show diffs before committing.

---

## The core idea

The voting fight rarely shows up as a vote on voting. It shows up as bills riding on unrelated vehicles, bills held hostage to other bills, executive orders, agency demand letters, threats to withhold federal funds, and the lawsuits that follow. A tracker that only lists bills shows none of it.

So psephos ingests four channels into one events table and links them. The value is the correlation: a timeline that assembles the maneuver on its own. When a non-voting bill suddenly stalls because of the SAVE America Act, or DOJ sues a state for its voter rolls, that lands in the same record system as the bills, graded and dated.

Track what changed, attach the roll-call or the document behind it, and let the record speak. The tool stays useful to people who do not share the builder's read of it.

---

## The four channels

| Channel | What lives here | Source | Auth |
| --- | --- | --- | --- |
| Legislation | Federal bills and their vehicles, actions, amendments, related bills, cosponsor counts | Congress.gov API | free key |
| Executive | Executive orders and rulemaking on elections | Federal Register API | none |
| Litigation | Voter-data suits, EO challenges, registration-law challenges; docket movement | CourtListener / RECAP | free token |
| Coercion + news | Demand letters, funding threats, and the reporting that explains why a bill moved or stalled | RSS feeds + Google News RSS | none |

The coercion category (voter-roll demands, funding threats) is not in any structured feed. It surfaces in the news channel first, then becomes a docket in the litigation channel once a state resists. You catch it with a lag, through news plus CourtListener, not in real time. That gap is expected, not a bug to engineer around.

State legislation is the fifth channel, now live via LegiScan. Fifty legislatures and heavy noise make coverage the access question: a change-hash gate keeps it inside the free-tier cap by calling `getBill` only on election bills whose masterlist hash moved. What remains is depth, not existence — a `state_bills` dimension and state-level vehicle detection (5b), and a dedicated state view.

---

## Source grading

Every item carries a NATO Admiralty grade: source reliability A to F, information credibility 1 to 6, following the cyber-osint-research skill. Defaults live in `config/sources.yaml` and may be overridden per item.

- Primary government and court records (congress.gov actions, Federal Register documents, CourtListener docket entries): **A1**.
- Maintained expert trackers and specialist outlets (UW State Democracy Research Initiative, States United, Democracy Docket, Votebeat, Bolts): **B2**.
- Aggregated Google News hits: **C3** until corroborated, then promote.

When two sources conflict, record both and flag the conflict. Do not silently pick one. Use the confidence field (high / moderate / low) only for analyst judgment that goes beyond the observed record.

---

## Data model

See `schema.sql`. The design is items-centric: one `items` table holds every change across all channels, with dimension tables for `bills` and `cases` that the items reference.

- `items` is the spine. Each row is one atomic event with a channel, source, grade, timestamps, an optional bill or case reference, a `content_hash` for dedup, and the raw payload for traceability.
- `bills`, `bill_actions`, `bill_relations` hold the legislation channel. `is_vehicle` flags an unrelated bill carrying voting provisions (S. 1383 is the live example). `bill_relations.relation_type` of `vehicle` or `amendment` is what catches the maneuver.
- `cases`, `case_entries` hold litigation. `category` separates voter-data suits from EO challenges from registration-law challenges.
- `sources` is the registry. `dedup_seen` backs the two-stage news dedup.

State persists in a remote **Turso** (libSQL) database — the upgrade from the committed `data/psephos.db`, which stays the local-dev fallback. `db.py` is dual-backend: an explicit path (tests, offline dev) uses local SQLite; otherwise `TURSO_DATABASE_URL` in the env routes to the remote. JSON snapshots in `data/*.json` are the diff-friendly export the cron commits and the input for the view.

---

## Collectors

Each collector reads `config/sources.yaml`, writes to `items` (plus its dimension tables), and is idempotent on `content_hash`. One module per channel under `collectors/`.

### collectors/legislation.py  (live)
For each watchlist bill, fetch the bill, its actions, amendments, related bills, and cosponsor count. Upsert into `bills`, append new rows to `bill_actions` and `bill_relations`, and write an `items` row for each new action. Grade A1. The amendments and related-bill endpoints are the point: they catch a bill being attached to a vehicle.

### collectors/news.py  (live)
Pull every RSS feed plus each Google News query. Run two-stage dedup (below). For surviving items, write to `items`, grade per source. Cross-reference titles against `legislation.procedural_terms` and watchlist short titles; when a news item names a watched bill and a procedural phrase, tag it so the timeline can attach it to that bill. This is what surfaces a hostage maneuver, since it breaks as reporting before it lands in any action log.

### collectors/litigation.py  (live)
Seed `cases` from the trackers in `config/sources.yaml` (UW, States United, Democracy Docket) plus the confirmed `seed_cases`. Resolve each to a CourtListener docket, then poll for new docket entries, writing them to `case_entries` and a summary to `items`. Grade A1 for court records, B2 for tracker-sourced metadata. The UW DOJ-suit tracker is scraped by `collectors/tracker_uw.py` into a deterministic `data/doj_cases.json` (court names mapped to verified CourtListener ids), which `litigation.py` loads alongside `seed_cases` — taking the channel from 3 hand-seeds to the full ~31-suit list without hardcoding it. On a fresh resolve the CourtListener `case_name` replaces the provisional caption.

### collectors/executive.py  (live)
Query the Federal Register API for documents from the configured agencies matching the configured terms. Write each to `items`, grade A1. Catches executive orders and rule changes that never touch Congress. A title-only relevance score surfaces the handful of on-topic EOs and rules among the agency-rule noise (scoring title+summary floods it with EAC abstracts).

### collectors/state.py  (live)
LegiScan, subject-filtered for elections. One `getMasterList` per state per run, then `getBill` only on election bills whose `change_hash` moved — the budget gate that holds it under the free-tier cap (a `max_getbill_per_run` guard resumes next run if hit). State items are leaf `items` rows (no bill/case dimension yet) with their own `data/state.json`. The `state_bills` dimension and state-level vehicle detection are the deferred 5b depth.

---

## Two-stage news dedup

The same story arrives from a dozen outlets and from Google News with tracking junk on the URL. Match the existing tracker pattern:

1. **Stage 1, canonical URL.** Strip `utm_*`, fragments, and trailing slashes, then exact-match against `dedup_seen.canonical_url`. Same canonical URL means the same item.
2. **Stage 2, content hash plus title similarity.** Compute a sha256 over the normalized title and lede. For near-duplicates with different URLs, compare normalized titles with `rapidfuzz` token_sort_ratio at a 0.90 threshold. A match folds the item into the one already seen.

Record every survivor in `dedup_seen` with its `item_id`.

---

## The correlation output

This is what makes psephos more than a list. From `items` joined to `bills` and `cases`, assemble per-bill and per-case timelines that interleave official actions with the reporting that explains them. The target output is the kind of narrative a bill search cannot produce on its own:

> S. 1383 amended, 218-213, here is the vote and the text. Then: housing bill signing canceled, here is the reporting that ties it to the SAVE America Act.

The cron commits this as JSON. The read-only view is live: a **Next.js app on Vercel** (`web/`) that renders per-bill and per-case timelines from the snapshots, on its own Vercel project (root `web/`) auto-deploying on push to main — not the Astro/Observable Plot originally sketched. The view was never the priority; the linked data is, and it now has a front end.

---

## Build phases — as built

Phases 1–3 have shipped; the system runs unattended on the 6-hour cron and persists to Turso.

**Phase 1 (shipped).** Scaffold, `schema.sql`, and the three MVP collectors — legislation, news, litigation (seeded from the trackers) — on the 6-hour GitHub Actions cron with JSON export and per-bill / per-case timeline data. Captures the SAVE America Act cluster and the DOJ voter-data fight.

**Phase 2 (shipped).** The Federal Register (executive) collector with a title-only relevance lens, and the read-only timeline view — a Next.js app on Vercel, not the originally-sketched Astro/Observable Plot. The backend also migrated from committed SQLite to remote Turso in this phase.

**Phase 3 (shipped).** State legislation via LegiScan, subject-filtered, with the change-hash budget gate. And the UW tracker scraper (`collectors/tracker_uw.py`) that brought litigation to the full ~31-suit DOJ list.

**Remaining depth (not built).** A `state_bills` dimension and state-level vehicle detection (5b): the state channel is items-only today, so it cannot yet catch a state vehicle the way the federal `bill_relations` model does. And a dedicated state view in the read layer. This is the depth that remains, not new channels.

---

## Workflow and conventions

- Spec-driven and review-gated. Propose a plan, get approval, show diffs before committing. No commits without a shown diff.
- Repo and Git identity: CSU-J3. Conventional commit messages.
- Local dev is Windows; the cron runs on Linux. Keep paths POSIX in anything the workflow touches. Watch the documented Windows gotchas in local hooks: forward slashes in paths, and `$HOME` rather than `~` for subprocesses.
- Secrets go in GitHub Actions secrets (and a local `.env`), never in the repo: `CONGRESS_API_KEY`, `COURTLISTENER_TOKEN`, and `LEGISCAN_API_KEY` (all active), plus `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` for the remote database.
- Naming matches the project: `psephos`.

---

## Limitations to state plainly

- The demand letters and funding threats are caught with a lag, through news and the dockets they spawn, not in real time.
- Google News items are C3 until corroborated. Do not let an uncorroborated aggregate drive the timeline.
- The DOJ-suit case list comes from the UW tracker; if that tracker lags, coverage lags with it.
- State coverage is live but items-only: the change-hash gate keeps it under the LegiScan free-tier cap, and it does not yet model state bills as a dimension or detect state-level vehicles (that is the deferred 5b depth).

---

## Current-state snapshot

Context for the build, accurate as of late June 2026. Re-verify before relying on any of it; this is a fast-moving area.

- The SAVE America Act is S. 3752 (Lee) and H.R. 7296 (Roy), refiles of the SAVE Act (H.R. 22, House-passed 220-208 in April 2025; S. 128 stalled). A near-identical MEGA Act is H.R. 7300. The proof-of-citizenship provisions passed the House 218-213 on Feb 11, 2026 as an amendment to S. 1383, an unrelated bill that had cleared the Senate by unanimous consent.
- In June 2026, Trump canceled signing a bipartisan housing bill to pressure the Senate to pass the SAVE America Act first; House action was frozen behind it.
- DOJ has demanded voter data from all 50 states and DC and is compiling it into a single record system. Some demand letters threatened withheld federal funding. Roughly a dozen states fully complied, a handful gave only public fields, and the rest refused. DOJ filed 31 lawsuits against 30 states plus DC; on June 24, 2026 the Sixth Circuit became the first appeals court to rule, affirming a dismissal.
- The effort implements Trump's election executive order, with DHS pushing states to run rolls through the rebuilt SAVE citizenship tool and data slated to reach ICE.
- Config seeds are now the two footnoted related suits (Common Cause v. DOJ, 1:26-cv-01352, D.D.C.; League of Women Voters v. DHS, 1:25-cv-03501, D.D.C.). The 30-states-plus-DC DOJ voter-data suits — including California (formerly hand-seeded as United States v. Weber) — come from the UW tracker artifact (`data/doj_cases.json`), not hand seeds.
