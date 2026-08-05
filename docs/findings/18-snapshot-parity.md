# Finding 18 — the snapshot parity gap, measured

Measured against production Turso and the committed snapshots at `f492e1f`
(`data: scheduled collection 2026-08-05T19:21Z`), on **2026-08-05**. Read-only:
no schema, collector, export or web change was made, and no `--apply` was run.

This exists so the sequencing call in `docs/status.md` — read-layer snapshot
migration versus dashboard redesign — is made against measurements rather than
against the paragraph that proposed it. It does not settle that call.

## 1. The claim under test

From `docs/status.md` (last updated **2026-08-01**), under *Open units*:

> **Read-layer snapshot migration.** Serving the web layer from the committed JSON
> snapshots removes Turso from the request path entirely, killing the count scan,
> the force-dynamic re-render cost, and any preview-crawl read exposure in one
> move. Snapshots are exactly as fresh as the DB, since the cron's data commit is
> what triggers the deploy. The caveat that makes it a unit rather than a swap:
> anything absent from the snapshots goes invisible in the web layer, which
> already bit us with orphaned state items, and 2,870 unattached news items (81 of
> the 2,951 do carry a bill/case/state ref) are invisible by construction today.
> Needs its own falsification.

The caveat is stated as if it applies to rows. It applies to **columns** too, and
that half had not been measured.

The row half of the caveat holds and has grown: the unattached news set is now
**3,058** of **3,142** news items, up from the 2,870 of 2,951 recorded on 08-01.
Attached news went 81 → **84**. The shape is unchanged, the magnitude moved with
five days of collection; the 08-01 figure is not wrong, it is stale.

## 2. The gap table, confirmed

Confirmed field-by-field against the live repo at `f492e1f`, not spot-checked:
every field of `Bill`, `Case`, `StateBill`, `TimelineItem` and `ExecItem` in
`web/lib/db.ts` was checked against the object each snapshot builder emits in
`export/snapshots.py`. The handoff's counts hold — `web/lib/db.ts` is 248 lines
with 13 exported query functions, `export/snapshots.py` is 299 lines with four
builders — and no seventh missing field was found.

### Fields the web layer needs and the snapshots do not carry

| Field | Web consumer | Rendered? | Builder that omits it |
|---|---|---|---|
| `bills.title` | `BillRow.tsx:20`, `bill/[bill_id]/page.tsx:32` (fallback after `short_title`) | yes | `build_bills` |
| `bills.introduced_at` | `getBills` ORDER BY fallback only | no | `build_bills` |
| `cases.latest_entry_at` | `CaseRow.tsx:36`, `case/[case_id]/page.tsx:56`, and `getCases` primary sort | yes, twice | `build_cases` |
| `cases.source_url` | `case/[case_id]/page.tsx:58` docket link | yes | `build_cases` |
| `state_bills.description` | `state-bill/[id]/page.tsx:46` | yes | `build_state_bills` |
| `items.summary` | `Timeline.tsx:45` | yes | `_item_entry` |

All six confirmed at the cited lines. Three corrections, none of which changes a
row of the table:

- **`items.summary` renders on three surfaces, not four.** `Timeline.tsx` has
  exactly three consumers — the bill, case and state-bill detail pages. The fourth
  timeline-ish surface, the executive channel, renders through
  `ExecutiveList.tsx`, which never touches `summary`. So the executive builder's
  missing `summary` costs nothing, which matters because executive is also the
  only channel with incomplete `summary` coverage (100 of 118).
- **`bills.introduced_at` is also selected by `getBill`** (`db.ts:128`), not only
  `getBills`. It is still rendered nowhere, so "no" in the Rendered column stands.
- **`getExecutiveAll` does not map cleanly as written.** It maps cleanly *after*
  the same grade split every other surface needs; `ExecItem` wants
  `admiralty_source` / `admiralty_info` and `_item_entry` emits one `grade`
  string. Every field is otherwise present.

### Sort keys that cannot be reproduced

- `getBills`: `COALESCE(latest_action_at, introduced_at) DESC, bill_id`. The
  fallback arm has no snapshot source — but **0 of 6** bills have a null
  `latest_action_at`, so the arm is unreachable today. Cosmetic.
- `getCases`: `COALESCE(latest_entry_at, filed_at) DESC, case_id`. The **primary**
  arm has no snapshot source, and **0 of 40** cases fall through to `filed_at`. So
  the missing column decides the order of every case row, and the case list cannot
  be ordered from snapshots at all without a substitute key. Deriving
  `latest_entry_at` as the max timeline date is not equivalent — the timeline
  carries B2 tracker framing as well as A1 docket entries — and was not assumed.
- `getStateBills`: `state, COALESCE(last_action_at, updated_at) DESC,
  state_bill_id`. **The handoff's query 3 does not measure this arm.** It counts
  `(state, last_action_at)` groups with more than one row — 81 of them — but those
  ties are broken by `state_bill_id`, which the snapshot carries, so they
  reproduce fine. The arm that actually needs `updated_at` is
  `last_action_at IS NULL`, measured separately: **0 of 484**. So this sort, the
  one the handoff called unfixable, is in practice fully reproducible from the
  snapshot today. `build_state_bills` still cannot start emitting `updated_at`
  without breaking byte-stability — the docstring's reason stands — but nothing
  currently depends on it.

Note the reversal: the sort the handoff flagged as the hard one is a non-issue,
and the one it did not flag as hard (`getCases`) is the only sort with real
exposure.

### Shape mismatches, both directions

- `_item_entry` emits `grade` as one string (`"A1"`); `TimelineItem` wants
  `admiralty_source` and `admiralty_info` separately. Split as `[0]` and `[1:]`,
  not `[0]` and `[1]` — `_grade_key` already assumes a multi-character info field
  is possible.
- `_item_entry` emits `source_id`, which no web type carries. Harmless.
- Timelines contain `kind: "cluster"` nodes with `members`, `anchor`, `label`,
  `source_count` and no top-level `channel`; `TimelineItem` is flat.
  `Timeline.tsx` changes either way — to render clusters, or to flatten them and
  discard the grouping the export exists to produce. Cluster **members** also
  carry no `channel`, though it is recoverable as the constant `"news"`:
  `_matches` only ever clusters `channel == "news"` rows.
- `is_vehicle` is `bool` in the snapshots, `number` (0/1) in the web types.
- `getExecutiveAll`'s order reverses exactly: the snapshot's ascending
  `(occurred_at, id)` inverts to `occurred_at DESC, id DESC`, and the NULL-ordering
  edge cannot bite because **0 of 118** executive items have a null or empty
  `occurred_at` (36 items across all channels do, none of them executive).
- `getCaseRef` and `getPredecessorRef` are derivable in-process from `cases.json`
  now that `superseded_by` is in it. Lookup-by-id for bills, cases and state bills
  works modulo the missing columns above.
- `getChannelCounts` is unreproducible by construction. §3 measures how badly.

## 3. The measurements

Read-only against production Turso, 2026-08-05. Verbatim, each next to the
question it answers.

**How many rows fall to a missing sort-fallback arm?** None, in either direction.

| query | result |
|---|---|
| `SELECT COUNT(*) FROM bills` | **6** |
| `SELECT COUNT(*) FROM bills WHERE latest_action_at IS NULL` | **0** |
| `SELECT COUNT(*) FROM cases` | **40** |
| `SELECT COUNT(*) FROM cases WHERE latest_entry_at IS NULL` | **0** |

The second and fourth rows read in opposite directions. Zero null
`latest_action_at` means the bill sort's missing arm never fires. Zero null
`latest_entry_at` means the case sort's missing arm is the one *always* used.

**How many rows lose visible text?**

| query | result |
|---|---|
| `bills WHERE short_title IS NULL AND title IS NOT NULL` | **1** of 6 |
| `cases WHERE source_url IS NOT NULL` | **40** of 40 |
| `state_bills WHERE description NOT NULL AND <> '' AND <> title` | **191** of 484 |

One bill row falls back to `title` for its heading and would render its `bill_id`
instead — a raw id where a name goes, on the homepage. (No bill has both null:
`short_title IS NULL AND title IS NULL` is 0.) Every one of the 40 case detail
pages loses its "View docket ↗" link. 191 state-bill detail pages lose the
description paragraph, which is the only place the `description <> title` test is
applied, so that count is exactly the number of pages that visibly change.

**How often does `updated_at` decide state-bill order?**

| query | result |
|---|---|
| `(state, last_action_at)` groups with `COUNT(*) > 1` (handoff query 3) | **81** |
| `state_bills WHERE last_action_at IS NULL` (the arm that needs `updated_at`) | **0** of 484 |

Query 3 was run verbatim and is reported verbatim; the second row is an addition,
not a substitute, because query 3 measures ties broken by `state_bill_id` rather
than the `updated_at` arm. See §2.

**`summary` coverage per channel** — the largest display gap:

| channel | n_total | n_summary |
|---|---|---|
| executive | 118 | 100 |
| legislation | 73 | 73 |
| litigation | 1,932 | 1,932 |
| news | 3,142 | 3,142 |
| state | 3,882 | 3,882 |

9,129 of 9,147 items carry a summary and **none** of them survives into a
snapshot. Weighted by what actually renders: 1,932 litigation + 3,882 state + 73
legislation + 84 attached news = 5,971 timeline entries lose their summary
paragraph. The 18 executive items without one are the only rows where the gap
costs nothing, and executive does not render `summary` anyway.

**The invisible set** — in `items`, in no file:

| channel | n |
|---|---|
| news | **3,058** |

News is the **only** channel with an invisible set. Nothing else in the spine
falls outside the union of (carries a bill/case/state ref) ∪ (channel =
`executive`). That is the difference the handoff called out: the count strip needs
a footnote on one channel, not a demonstration that it cannot exist. It is also
the largest single channel, so a snapshot-derived strip would under-report news by
97% while reading every other channel exactly right — arguably worse than a
footnote, since four of five numbers would be correct.

**Double-attachment:**

| query | result |
|---|---|
| `items` attached to more than one dimension | **0** |

Corroborated independently in §4: the 6,089 item references across all four files
resolve to 6,089 distinct ids. No item appears in two snapshots. Executive items
carrying a dimension ref — the one cross-file path query 6 does not cover — is
also **0**.

**The spine:**

| query | result |
|---|---|
| `SELECT COUNT(*) FROM items` | **9,147** |
| executive | 118 |
| legislation | 73 |
| litigation | 1,932 |
| news | 3,142 |
| state | 3,882 |

For context against finding 16's 08-01 baseline of 8,931: the spine grew 216 rows
in five days, 191 of them news.

## 4. The reconciliation

Snapshot contents at `f492e1f`, counted from the files:

| file | rows | entries | clusters | cluster members | item references |
|---|---|---|---|---|---|
| `bills.json` | 6 bills | 149 | 1 | 9 | 157 |
| `cases.json` | 40 cases | 1,932 | 0 | 0 | 1,932 |
| `executive.json` | — | 118 | 0 | 0 | 118 |
| `state_bills.json` | 484 bills | 3,882 | 0 | 0 | 3,882 |
| **total** | | **6,081** | **1** | **9** | **6,089** |

Every figure the handoff pinned is confirmed, including the single cluster.

Applying the three adjustments:

```
  6,089   snapshot item references (entries 6,081 + cluster expansion 9 − 1 = 8)
+ 3,058   the invisible set, in items and in no file
−     0   double-attached, counted once per file they appear in
= 9,147
  9,147   items total
```

**Residual: 0.** The export loses no item and duplicates none. The 6,089 references
are 6,089 distinct ids, which closes the same arithmetic a second way.

By channel, the snapshot side decomposes as 3,882 state + 1,932 litigation + 118
executive + 73 legislation + 84 news (75 standalone + 9 cluster members), and the
84 matches the attached-news count queried directly. Every channel reconciles
individually, not just in total.

## 5. The three options

Stated without picking one.

**A. Extend the export and migrate fully.** Add the five addable fields —
`bills.title`, `cases.latest_entry_at`, `cases.source_url`,
`state_bills.description`, `items.summary` — split `grade` in the reader, and
teach `Timeline.tsx` clusters. The state-bill sort turns out not to need changing
(0 rows use the `updated_at` arm), and `bills.introduced_at` is unreachable, so
the sort work is smaller than the handoff assumed: the only sort with real
exposure is `getCases`, which `cases.latest_entry_at` fixes directly. Cost is a
schema-adjacent change to a byte-stable export — `latest_entry_at` and `summary`
are stable per row, so byte-stability survives, unlike `updated_at` — plus a
`Timeline.tsx` rewrite for clusters. The count strip still needs a decision,
because no export change can produce the 3,058 unattached news items without a
fifth file.

**B. Hybrid.** Serve bills, cases, state bills and executive from snapshots; keep
the count strip on Turso. One query stays in the request path, so the handoff-16
cache stays live and load-bearing rather than becoming dead code, and the strip
stays exactly correct on all five channels. Does not remove Turso from the request
path, so it does not close the preview-crawl exposure by itself.

**C. Don't migrate.** Close the preview-deployment exposure directly — one of the
three things the migration was going to fix, and the only one it fixes uniquely —
and leave the read path alone. The other two, the count scan and the
force-dynamic re-render cost, are already bounded: finding 16 caps the strip at
≤24 scans/day and predicts the delta is invisible inside a 150–250K rows/day band.

## 6. Freshness coupling

Today the web layer reads Turso, so a run that writes to Turso and then dies
before export leaves the site **correct**. After a migration, that same failure
leaves the site **stale with no signal** — the page renders cleanly from the last
committed snapshot and nothing on it says how old that snapshot is.
`docs/status.md` §2 is currently measuring exactly that failure rate. The
data-commit cadence since the fix is uneven, against four scheduled slots a day:
07-31 three, 08-01 three, 08-02 none, 08-03 four, 08-04 one, 08-05 three
(confirmed from `git log` on `origin/main`). **The 08-02 and 08-04 gaps are not
evidence of failure**: empty-diff runs commit nothing by design and there is no
`news.json`, so a slot in which no bill, case, executive or state row moved is
expected to be silent — and news, the busiest channel, is precisely the one whose
movement never produces a commit. What the migration does is convert collector
reliability into a front-end freshness dependency, moving a class of failure from
invisible-and-harmless to invisible-and-user-facing. The number that prices that
risk is the handoff-15 failure ratio, and it arrives at the 08-08 sitting.

## Provenance

- Part A: `web/lib/db.ts` and `export/snapshots.py` at `f492e1f`, read against the
  five web row types and all four snapshot builders, plus the eight `web/`
  components and five pages that consume them.
- Part B: read-only `SELECT`s against production Turso via `db.connect()`,
  2026-08-05. No writes, no commit.
- Part C: `data/{bills,cases,executive,state_bills}.json` at `f492e1f`.
- The working tree was at `a1daf80` (8 commits behind) when this began;
  `f492e1f` arrived on fetch and the tree was fast-forwarded to it. The eight
  intervening commits are all data commits, so no Part A source file differs
  between them.
