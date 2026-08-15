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

State legislation is the fifth channel, now live via LegiScan. Fifty legislatures and heavy noise make coverage the access question: a change-hash gate keeps it inside the free-tier cap by calling `getBill` only on election bills whose masterlist hash moved. The `state_bills` dimension and the dedicated state view shipped (5b-a / 5b-c); state-level vehicle detection (5b-b) is closed as a free-tier limitation (see the limitations section).

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

State persists in a remote **Turso** (libSQL) database — the upgrade from `data/psephos.db`, which stays the local-dev fallback (a working artifact in the repo directory, gitignored, never tracked). `db.py` is dual-backend: an explicit path (tests, offline dev) uses local SQLite; otherwise `TURSO_DATABASE_URL` in the env routes to the remote. JSON snapshots in `data/*.json` are the diff-friendly export the cron commits and the input for the view.

---

## Collectors

Each collector reads `config/sources.yaml`, writes to `items` (plus its dimension tables), and is idempotent on `content_hash`. One module per channel under `collectors/`.

### collectors/legislation.py  (live)
For each watchlist bill, fetch the bill, its actions, amendments, related bills, and cosponsor count. Upsert into `bills`, append new rows to `bill_actions` and `bill_relations`, and write an `items` row for each new action. Grade A1. The amendments and related-bill endpoints are the point: they catch a bill being attached to a vehicle.

### collectors/news.py  (live)
Pull every RSS feed plus each Google News query. Run two-stage dedup (below). For surviving items, write to `items`, grade per source. Cross-reference titles against `legislation.procedural_terms` and watchlist short titles; when a news item names a watched bill and a procedural phrase, tag it so the timeline can attach it to that bill. This is what surfaces a hostage maneuver, since it breaks as reporting before it lands in any action log.

**News anchors to bills, not to cases — decided, not unfinished (handoff 48/49).** `classify()` returns a `bill_id` or nothing, and `collectors/news.py` writes `case_id` as `None`. This document used to point both ways: the section above specifies bill matching, while *The core idea* and the coercion channel describe news feeding litigation. The conflict is resolved here in favour of bills, on a measurement rather than a preference.

**The constraint is the corpus, not the task.** Bill matching works because legislation is cited by number in prose — "H.R. 22", "S. 1383" — and a number is unambiguous. Litigation is not cited that way. Across 3,302 unanchored news items, **a docket number appears zero times**; no outlet writes `1:25-cv-03934`. The only remaining signal in an RSS title and summary is the case caption's defendant, and a defendant here is a secretary of state who is in the news constantly for reasons unrelated to being sued — so "Jocelyn Benson" matches a story about her running for governor as readily as one about `72347022`. Measured on the B2 corpus, defendant matching yields ~14 items of which perhaps 2–3 are genuinely about the case. Full article bodies do name cases; fetching them is a separate project with its own cost and its own failure modes.

So the limitation is stated rather than engineered around, the same way 5b-b is. A news item about a lawsuit reaches the record as a graded item on the news channel; it does not reach that case's timeline.

### collectors/litigation.py  (live)
Seed `cases` from the trackers in `config/sources.yaml` (UW, States United, Democracy Docket) plus the confirmed `seed_cases`. Resolve each to a CourtListener docket, then poll for new docket entries, writing them to `case_entries` and a summary to `items`. Grade A1 for court records, B2 for tracker-sourced metadata. The UW DOJ-suit tracker is scraped by `collectors/tracker_uw.py` into a deterministic `data/doj_cases.json` (court names mapped to verified CourtListener ids), which `litigation.py` loads alongside `seed_cases` — taking the channel from 3 hand-seeds to the full ~31-suit list without hardcoding it. On a fresh resolve the CourtListener `case_name` replaces the provisional caption.

**Standing check — bootstrap coverage.** A docket with `entries_synced_at IS NULL` was never bootstrapped, so the alarm for gaps is a direct Turso `SELECT`. The correct form excludes superseded rows, since a terminated district docket that has been continued as a circuit appeal is complete, not unbootstrapped (handoff 13):

```sql
SELECT COUNT(*) FROM cases WHERE entries_synced_at IS NULL AND superseded_by IS NULL;  -- expect 0
```

Without `AND superseded_by IS NULL` this read 3 (the PA/NH/MD district orphans) and every mention of it needed the "34 not 37" caveat. It still reads 3: those three are the only rows in the table with a NULL `entries_synced_at`, and the clause exists for them. `cases.superseded_by` is set on the terminated source row, pointing forward to its successor, a circuit appeal or a venue refile; the reverse lookup is a query. The successors are first-class rows that poll normally.

**Three counts, three different sets (handoff 37/38).** Collapsing any two of them is what produced a stale line in `docs/status.md` that survived several readings, so state them separately:

- **7 superseded** — `superseded_by` is set on PA `71453026`, NH `71453646`, MD `71980724`, GA `72053306`, KY `72334676`, VA `72156765`, NM `71982149`.
- **6 unpolled** — the same set minus GA. Those six are absent from `data/doj_cases.json`, so no run polls them. GA stays seeded because the UW tracker carries two Georgia rows (`Georgia (1)` gamd, `Georgia (2)` gand), and its M.D. Ga. row is therefore superseded *and* polled.
- **3 NULL `entries_synced_at`** — PA, NH, MD, the handoff-13 orphans. KY, VA and NM are unpolled but *not* unbootstrapped: they hold marks frozen 2026-07-27 and 07-28, from before the tracker rewrote their rows.

The arithmetic that pins it: **34 seeded + 6 unpolled = 40.** Unpolled and unbootstrapped are different properties — a row dropped from the seed artifact is never polled again but keeps whatever mark it already had.

State the alarm's mechanism correctly, too. `entries_synced_at IS NULL AND superseded_by IS NULL` reads 0 **because the second clause excludes PA, NH and MD** — not because their marks are populated. They are NULL and always were. Without the clause it reads 3, unchanged by the handoff-37 apply.

Before asserting any future pair, check the **circuit map**: a district's appeals go to exactly one circuit by statute, so this is free, needs no API call, and is the only corroboration independent of both CourtListener and the tracker. A venue refile has no circuit step and must stay intra-state (M.D. Ga. → N.D. Ga.), so establish which kind of successor you have first.

### collectors/executive.py  (live)
Query the Federal Register API for documents from the configured agencies matching the configured terms. Write each to `items`, grade A1. Catches executive orders and rule changes that never touch Congress. A title-only relevance score surfaces the handful of on-topic EOs and rules among the agency-rule noise (scoring title+summary floods it with EAC abstracts).

### collectors/state.py  (live)
LegiScan, subject-filtered for elections. One `getMasterList` per state per run, then `getBill` only on election bills whose `change_hash` moved — the budget gate that holds it under the free-tier cap (a `max_getbill_per_run` guard resumes next run if hit). State items reference a first-class `state_bills` dimension via `items.state_bill_id`, exported as per-bill timelines in `data/state_bills.json` (5b-a). State-level vehicle detection (5b-b) is closed as a free-tier limitation — see the limitations section.

### Per-item recovery: `db.recover`, never bare `rollback` (handoff 15)

Every collector's per-item handler recovers the connection with `db.recover(conn)`, never a bare `conn.rollback()`. On the remote backend a `rollback()` can itself raise when the Hrana stream is already dead, so a handler written to skip one bad item instead crashes the whole run — three of 28 runs failed exactly this way (2026-07-24, -27, -29), all in `legislation.py`, the rollback raising `stream not found` while trying to recover a recoverable, idempotent failure. `db.recover` uses `_Conn.reset()` (rebuild the connection) on the remote and falls through to `rollback()` on local SQLite.

State used to be the deliberate exception; **it is not one any more (handoff 81).** `collectors/state.py` now commits **once per state** inside `collect()`, with a third handler around the per-state write path that calls `db.recover(conn)` — there `conn` *is* the failure, which is exactly what the rule above is for. A stream failure costs one state instead of the whole run: completed states are durable, the failing state is discarded whole, later states are still attempted. That partial is the intended failure mode rather than damage, because the change-hash gate makes it resumable — a bill whose hash never committed has no stored hash, so the next run re-fetches it and items dedup on `content_hash`.

**The two original handlers are still excluded, and it is worth being precise about why, because half the old reason no longer applies.** They wrap `getMasterList` and `getBill` — pure HTTP, where `conn` is never the failure — and *that* is what decides it, independent of batch size. The other half of the old justification, "calling `recover()` there would throw away the run's whole uncommitted batch," is now much weaker: the batch is one state, not nine. The conclusion survives on one leg where it used to stand on two, which is worth recording rather than leaving a rationale that reads luckier than it is.

**What the old shape actually cost, since it was previously written down as "don't over-rate it."** `state` runs last of six lines in one `bash -e` step, and Export and Commit data changes are separate steps with **no `if: always()`**, so a non-zero exit from state ended the job and skipped both. The cycle lost its snapshot and its data commit — not its data, since the other five collectors had already committed to Turso. The 2026-08-15 LegiScan incident is the near miss that makes the shape legible: all nine states failed **at `getMasterList`**, inside a handler, so the run survived and printed nine `ERROR:` lines. Four lines further down, at the write path, the same failure would have taken the run.

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

**Phase 1 (shipped).** Scaffold, `schema.sql`, and the three MVP collectors — legislation, news, litigation (seeded from the trackers) — on the 6-hour GitHub Actions cron with JSON export and per-bill / per-case timeline data. Captures the SAVE America Act cluster and the DOJ voter-data fight. The backend moved from local SQLite to remote Turso within this phase, before either phase-2 marker: `69bb103` made `db.py` dual-backend, and `904e228` cut production over by giving the workflow `TURSO_DATABASE_URL`. The phase-2 markers add at `b4c0524` (the Federal Register collector) and `fcaa61d` (the Next.js scaffold).

**Phase 2 (shipped).** The Federal Register (executive) collector with a title-only relevance lens, and the read-only timeline view — a Next.js app on Vercel, not the originally-sketched Astro/Observable Plot. It was built on Turso from the start, not migrated onto it.

**Phase 3 (shipped).** State legislation via LegiScan, subject-filtered, with the change-hash budget gate. And the UW tracker scraper (`collectors/tracker_uw.py`) that brought litigation to the full ~31-suit DOJ list.

**Phase 5b (complete).** The `state_bills` dimension made state bills first-class (5b-a) and a dedicated state view shipped to the read layer (5b-c). State-level vehicle detection (5b-b) is closed as a stated free-tier limitation: LegiScan's `sasts` relations express companionship and similarity, not the substitution a state vehicle would take, so the tool's own asserted relations cannot point to one (see the limitations section and `docs/findings/5b-b-vehicle-discovery.md`). No build phase remains open.

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
- **News items never attach to a case.** `items.case_id` is always NULL on the news channel, by decision (see the news collector section). RSS titles and summaries carry no docket numbers — zero across 3,302 items — and a defendant's name identifies an official who is in the news for many reasons, not the suit. A story about a DOJ lawsuit sits on the news channel and not on that case's timeline.
- Google News items are C3 until corroborated. Do not let an uncorroborated aggregate drive the timeline. **Corroboration now has one implemented form (2026-08-15): outlet promotion.** An item delivered by the aggregator but *published by* an outlet this config grades B2 is graded B2, because `source_id` is the delivery pipe and the spec grades outlets. `items.outlet` stores the publisher — the feed's own `<source>` element going forward, a parse of the ` - Publisher` title suffix for rows collected before that, which is not equal evidence and is marked as such. The grade is derived at read time, so nothing rewrites what the pipe said. Everything else from the aggregator stays C3: this promotes 159 items of 3,003.
- The DOJ-suit case list comes from the UW tracker; if that tracker lags, coverage lags with it.
- State-level vehicle detection is not reachable on free-tier LegiScan data. The `sasts` relation vocabulary populated across the nine polled states expresses companionship and similarity (Same As, Crossfiled, Similar To) plus the joint-resolution/implementer pair (Enabled by, Enabling for). Substitution, the one shape a committee-substitute vehicle would take, appears zero times in 205 relations across the 455-bill dimension. 86% of those relations resolve to bills already held; the 29 unheld targets are election bills the title filter missed plus cross-subject index noise, with no vehicle among them. So the tool's own asserted relations cannot point to a vehicle, and 5b-b already closed full-text discovery structurally. What remains would require reading amendment text on bills the election filter never matched, and the per-bill query cost puts that out of reach on the free tier. 5b-b is closed. See `docs/findings/5b-b-vehicle-discovery.md`.

---

## Current-state snapshot

Context for the build, accurate as of late June 2026. Re-verify before relying on any of it; this is a fast-moving area.

- The SAVE America Act is S. 3752 (Lee) and H.R. 7296 (Roy), refiles of the SAVE Act (H.R. 22, House-passed 220-208 in April 2025; S. 128 stalled). A near-identical MEGA Act is H.R. 7300. The proof-of-citizenship provisions passed the House 218-213 on Feb 11, 2026 as an amendment to S. 1383, an unrelated bill that had cleared the Senate by unanimous consent.
- In June 2026, Trump canceled signing a bipartisan housing bill to pressure the Senate to pass the SAVE America Act first; House action was frozen behind it.
- DOJ has demanded voter data from all 50 states and DC and is compiling it into a single record system. Some demand letters threatened withheld federal funding. Roughly a dozen states fully complied, a handful gave only public fields, and the rest refused. DOJ filed 31 lawsuits against 30 states plus DC; on June 24, 2026 the Sixth Circuit became the first appeals court to rule, affirming a dismissal.
- The effort implements Trump's election executive order, with DHS pushing states to run rolls through the rebuilt SAVE citizenship tool and data slated to reach ICE.
- Config seeds are now the two footnoted related suits (Common Cause v. DOJ, 1:26-cv-01352, D.D.C.; League of Women Voters v. DHS, 1:25-cv-03501, D.D.C.). The 30-states-plus-DC DOJ voter-data suits — including California (formerly hand-seeded as United States v. Weber) — come from the UW tracker artifact (`data/doj_cases.json`), not hand seeds.
