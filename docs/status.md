# psephos — status and backlog

Living doc. Belongs at `docs/status.md`, **tracked** (`docs/handoffs/` is ignored via `~/.gitignore_global`, so nothing durable goes there). Update it at the end of a session, not the start.

Last updated: 2026-08-01.

---

## Owed right now

### 1. Handoff 14 invariant — one read-only query, not a unit of work

**Scope first, because this line has already been misread once.** The unit shipped days ago and is half-proven. `--apply` ran, the export ran, and the data commit is `bd4d577` (07-30), all on origin. Six collector-driven data commits have run since — `200931f`, `dda174e`, `4059878`, `98217c5`, `7709e14`, `6eb6554` — and `superseded_by` is still present in `data/cases.json` at HEAD. So the value is no longer just `bd4d577`'s hand-written entry; a collector regenerated the file around it and did not drop it.

What is owed is the **direct Turso proof and the run-log check**, nothing more. Do not write "not started", and do not re-run `--apply`.

That snapshot survival is corroboration, not the proof — a no-diff or partially-completed export can leave a stale file looking healthy, which is why the standing invariant says row state comes from a query. It raises the value from *hand-written* to *DB-derived*; the SELECT is still what closes it.

The doc previously said three crons had run and effectively two were usable. That count is stale: the window is now six-plus completed runs. This should have been read after the first.

Procedure, in order:

1. Cap-abort check across the post-push runs, ids from `gh run list`. `gh run view <id> --log`, looking for the handoff-8 daily-cap abort. You need to know whether litigation actually reached `72053306`.
2. Direct Turso query. **Not the snapshot** — a no-diff run or a pre-export death leaves no new commit, and you'd read `bd4d577`'s hand-written value and credit the manual commit as the collector's work.

       SELECT case_id, status, superseded_by, updated_at FROM cases WHERE case_id = '72053306';

Note that the 07-31 01:26Z run **failed** on the org-wide Turso read block (CBT's doing, not psephos's), so it never reached litigation — this is the same failure §2 names, not a second one. Exclude it from the usable count; the six data commits listed above are runs that reached export, so the usable window is comfortably wide now.

**Record all of it in one pass**, since it's one query plus one log sweep:

- The SELECT's four values: `case_id`, `status`, `superseded_by`, `updated_at`.
- The run ids actually checked, by id, not "the recent ones".
- The cap-abort read for each of those runs — present or absent, per run.

Reading it:

- `superseded_by` still `'72193752'` is load-bearing. Anything else means the unit failed and the omits-`superseded_by` invariant is broken in production.
- `updated_at` moved on either usable run is corroborating.
- `updated_at` unmoved *and* no cap-abort *and* no read-block on the runs that did complete is a real finding: the seed isn't being polled. One run missing it is noise. Three reasons it can legitimately be unmoved now (cap-abort, read-block, run failure), so rule each out by name before calling it a finding.

**Read this alongside §2 and §3 on ~08-08.** All three are log or dashboard reads on the same runs; doing them in one sitting costs one sweep instead of three. What follows them is a build decision, not another read: settle the read-layer snapshot migration against the dashboard redesign — which one is the source the other builds on — and then handoff 17.

### 2. Handoff 15 failure ratio — window open, don't close early

Baseline is 3 failures in 28 runs, all Hrana in `legislation.py`, pre-`474840c`: 07-24 (cursor/EOF), 07-27 and 07-29 (stream not found, in `collect_bill`).

That figure is window-specific and will look wrong if you glance at recent failures instead. The last 40 runs contain 5, and the other two aren't the Hrana family: 07-31 01:26Z is the org-wide Turso read block (post-fix, external, doesn't count against the recovery window), and 07-23 01:26Z predates the recon window and was never inspected. Compare like-for-like or it reads as a regression that isn't one.

Read at ~28 post-fix runs, roughly a week. **Not two days.** The original handoff said two days and that was underpowered: at the ~11% per-run baseline rate, 8 runs come back clean about 40% of the time even if the fix changed nothing. Twenty-eight runs drops that to ~4% and compares like-for-like against the baseline window.

**Next read: ~2026-08-08.** The fix pushed 07-30 (`474840c`); at 4 runs/day that clears 28 post-fix runs with margin. Same sitting as §1 and §3.

If the family recurs, pull the failing line before proposing anything. Same site means `reset()` isn't recovering; a different site means the audit missed one. Those want different fixes.

While in the logs, note litigation's request consumption. Litigation runs third, after legislation in the same `-e` step, so those 3 failed runs aborted before it ever ran and it polled nothing on them; the fix makes ~11% more runs *reach* litigation, adding that draw against the same 250/day cap. Handoff 7's incremental polling should absorb it, handoff 8's abort is the backstop. Report a cap-abort; don't act on a single occurrence.

### 3. Handoff 16 — PUSHED; one chart re-read owed ~08-08

**Closed as a push gate.** Pushed 08-01 (`6eb6554..cc763c9`), four commits, verified from a fresh clone: the cache is live in `web/lib/db.ts` and the finding carries its prediction. The hashes this section previously listed (`a8103ac`, `f0b0683`, `c68a425`) are dead — rebased onto current origin/main before the push. Don't chase them.

The 24h `turso db inspect` gate is **deleted, not satisfied.** The Turso dashboard charts rows read per day per database directly (app.turso.tech → Databases → psephos → Analytics → Rows Read), so the two-reading cumulative protocol was unnecessary; no reading was ever taken under it. Baseline is recorded in `docs/findings/16-channel-count-baseline.md`: ~150–250K/day for Jul 26 – Aug 1, read 08-01 ~21:45Z.

What's owed is one re-read of the same chart, **~2026-08-08**, same sitting as §1 and §2.

**Expect it to show nothing, and don't treat that as failure.** At ~200K rows/day against 8,931 rows/scan the strip accounts for at most ~22 renders/day — a ceiling, since collectors read too — and the cache cap is ≤24/day. Current behaviour already sits at or under the cap, so the delta may be invisible inside the noise of a 150–250K band. The finding predicts this in advance rather than explaining it afterward. The change is still right: it makes a bounded cost a property of the code instead of a property of today's traffic.

The old "falls hard / barely moves" split and its ~190 renders/day ceiling are gone — see the falsified list.

---

## Open units, roughly in order

**Handoff 17 — supersession candidate generator.** Note the renumbering: this was called 16 mid-session before the channel-count cache took that number. It carries two things, which belong together because the fix lives in the `main()` the generator extends:

- The generator itself. Reads a notice-of-appeal or dismissal entry on a terminated row, looks for an unlinked live row in the same state, and *proposes* pairs. Writes nothing, doesn't extend `PAIRS` itself. Three asserted pairs became five in a month; hand-assertion is the bottleneck.
- Handoff 14's dry-run display defect. `main()` prints the `PAIRS` constant, so the table is an echo of the input and the only real dry-run signal is `verify()`'s pass/refuse line. The display should print queried `status` and `docket_number` per row alongside the asserted ones.

**State batch-boundary unit.** Created by handoff 15's recon, not inherited. `state.py` commits once for the whole multi-state run (317/319), so a stream failure at the unguarded `seen_hash`/insert path propagates and discards every state processed that run. The two existing handlers (252, 273) don't catch it — they wrap LegiScan HTTP calls only. Fixing it needs per-state commits to bound the batch. state runs last in the step order, so this costs the run's export and data commit as well as state's own batch; the other five collectors' writes are already committed to Turso, so it delays the snapshot rather than losing data. Don't over-rate it.

**Read-layer snapshot migration.** Serving the web layer from the committed JSON snapshots removes Turso from the request path entirely, killing the count scan, the force-dynamic re-render cost, and any preview-crawl read exposure in one move. Snapshots are exactly as fresh as the DB, since the cron's data commit is what triggers the deploy. The caveat that makes it a unit rather than a swap: anything absent from the snapshots goes invisible in the web layer, which already bit us with orphaned state items, and 2,870 unattached news items (81 of the 2,951 do carry a bill/case/state ref) are invisible by construction today. Needs its own falsification.

**Dashboard redesign — from inventory to intelligence.** The homepage currently answers "what does psephos track"; it should answer "what changed and what does it connect to." Four moves, in value order:

- **Deltas on the channel counts** against the previous export. Raw totals mean nothing on a monitoring tool.
- **A merged reverse-chronological activity feed** across all five channels since the last cron, each entry tagged with channel and Admiralty grade. The grades exist in the data and appear nowhere on the page, and the feed is the cross-channel thesis rendered.
- **The DOJ voter-data campaign as one object**, not 38 near-identical rows: a state grid with status coloring, exceptions surfaced (GA refile, KY appeal, circuit cases), dormant dockets demoted behind it.
- **Watched bills sorted by recent cross-channel activity**, with correlation on the card (news volume, related litigation), so S. 1383 mid-floor-fight doesn't render identically to a bill dormant since referral.

All read-layer: no collector or schema changes. The deltas are the only new data need, and that's one comparison against the prior snapshot. Mockup exists in the 08-01 session.

**Sequencing.** Decide the snapshot migration above before building this. If the read layer is moving to snapshots, build the redesign on that source once, not twice.

**Kentucky supersession candidate — unlinked.** Both rows carry `superseded_by = NULL`; nothing is asserted. `72334676` (E.D. Ky. 3:26-cv-00019) took judgment of dismissal with prejudice 2026-07-23, notice of appeal 07-24; `73674243` (6th Cir. 26-5657) opened 07-24. The district row still reads `status = pending`, so `verify()` correctly refuses it. Gated on CourtListener setting `date_terminated`. **Do not weaken the guard to accommodate it.** On the court's clock, nobody else's.

**Deployment Protection.** Check whether preview deployments are public. If they are, every preview URL is a crawlable, uncached, full-Turso surface nobody is watching. Close it because an open uncached surface is wrong, not because it's costing quota — at psephos's volume it isn't.

**The `~/.gitignore_global` decision.** `docs/handoffs/` is ignored at the workstation level, which makes it not a psephos decision. Two consequences: it applies to every repo on that machine with such a directory, CBT included; and it's machine-local, so whether those files are tracked depends on which box you're on. The real question is whether that global pattern should exist at all, and if so whether each repo needs an explicit committed decision rather than inheriting a workstation default. Cross-repo, so probably not a psephos unit.

**Michigan.** 6th Cir. `26-1225` (`72347022`) reads terminated with no successor and no district row held. Probably a decided appeal rather than a supersession. Worth one look when the generator gets built, not before.

---

## Standing invariants

Things that have bitten before and will again.

- Every collector must exit 0. The workflow runs them as sequential lines in one `-e` bash step; a non-zero exit stops export and the data commit.
- CourtListener is 250 requests/day. Daily-cap 429s abort the run; burst 429s skip and continue. The 429 body's `retry-after` is the only reliable discriminator.
- Database facts come from direct Turso queries, never from JSON snapshots. Snapshots are a lagging derivative and can produce false greens. This applies to the orphan alarm, the supersession invariant, and anything else asserting a row's state.
- Absent cron commits are not failures. An empty-diff run commits nothing by design, so gaps in the 4/day schedule prove nothing without `gh run list`.
- LegiScan needs `getMasterList`, not `getMasterListRaw`. Raw omits `title`/`description`, so election filters silently match zero bills.
- Per-item error handlers recover via `db.recover`, never bare `conn.rollback()`. The remote backend's rollback raises on a dead stream, and a raising handler is a failed run.
- `git check-ignore -v <path>` names the ignoring file and line. Use it when something is untracked and the repo `.gitignore` doesn't explain why.
- Port 3001 for psephos dev, 3000 is CBT. Process cleanup scoped by port via `netstat`/`taskkill /PID`, never by image name.
- psephos and CBT share the `csu-j3` Turso account and its quota. A block in one may be the other's doing.

---

## Falsified — running list

Spans sessions, not just the current one. Kept because the pattern matters more than the individual errors: every one was a confident claim about read cost or repo state, and every one died to a single command or a single chart.

- **Prefetch as the read amplifier.** Wrong. No `loading.tsx` means App Router doesn't fully prefetch dynamic routes, so "every prefetch is a full render" never held.
- **`items` ≈ 6,053 rows.** That was a floor derived from snapshots, correctly labeled and then used as a magnitude anyway. Actual is 8,931; the gap is the unattached items — 2,870 of the 2,951 news items carry no bill/case/state ref, so they never attach and appear in no snapshot.
- **`docs/handoffs/` isn't gitignored.** Read from the repo `.gitignore` in a clone, which can't see `~/.gitignore_global`. The conclusion held by accident; the reasoning didn't.
- **state.py as a seventh bare-rollback site.** Inferred from the handler's shape without checking what the `try` wrapped. Both sites wrap pure-HTTP calls that never touch `conn`, and with the only commits at 317/319 a `reset()` there would have discarded every prior state's pending writes.
- **~4 cache cold starts/day from deploys.** Vercel's Data Cache persists across deployments, so the cron's data commit doesn't invalidate `unstable_cache` entries. The cap is the ≤24/day from the revalidate window alone.
- **~1.7M rows/day as psephos's rate.** Carried from the CBT thread as a user-provided peak of unstated shape, then used as a sustained rate. The per-database chart shows it is a **single-day spike on ~Jul 21**; the Jul 26 – Aug 1 regime is ~150–250K/day. Everything derived from it inherited the error — the ~190 renders/day ceiling was ~8× too high, and the "falls hard → the strip was the bulk" branch it created was never live. Same failure as the 6,053 floor: a number correctly labeled *provisional* and then used as a magnitude.
- **Handoff 14 as an unstarted unit.** Listed as owing `--apply`, export, and a data commit. All three shipped 07-30 (`bd4d577`) and have survived six collector-driven exports. Only the read-only Turso proof was ever outstanding. A stale owed-list entry is as misleading as a wrong measurement, and costs more, because it invites redoing finished work.

The claims that survived were the ones someone queried: the `getChannelCounts` scan (provable from the schema), `items = 8,931` (measured against production), and the handoff-14 data commit (checked with `git log`, not recalled).
