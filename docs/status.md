# psephos — status and backlog

Living doc. Belongs at `docs/status.md`, **tracked** (`docs/handoffs/` is ignored via `~/.gitignore_global`, so nothing durable goes there). Update it at the end of a session, not the start.

Last updated: 2026-08-12.

---

## Owed right now

### The first due run — the 2026-08-12 00:00Z slot

**This is the only open item.** Everything else in this section closed on the 2026-08-11 ~23:00Z sweep and is recorded below under *Closed on the 08-11 sweep*. Read that first if any of this is unfamiliar.

The 08-10 dispatch stamped `status_checked_at` on 33 rows between **19:24:42Z and 19:26:49Z**. The gate was 24h, so those rows came due again at **08-11 19:24–19:26Z** — after the last scheduled run of 08-11 (18:42Z, which read the gate at 18:46:58Z and missed the boundary by 37m44s). The next run to see a non-zero due set is therefore the **08-12 00:00Z slot**. It has not been read as of this update, so nothing below is verified against it.

Expect, and check in one pass:

- **24 due**, not 33. Nine rows flipped to `terminated` on the dispatch and `terminated` is absorbing, so the gate's `status <> 'terminated'` clause drops them permanently. Confirmed by direct query, not inferred: `SELECT COUNT(*) FROM cases WHERE status IS NULL OR status <> 'terminated'` reads **24** right now. A number other than 24 means a row changed state between then and the run, which is a finding, not noise.
- **0 changed, 0 failed.** A flip here would be a docket that terminated inside the 24h window — possible and not alarming, but name it.
- **No `capped at 40/N`.** `max_status_refresh_per_run` is 40 and the due set is 24, so the cap cannot bind. If that line appears, the due set is bigger than the table.

**The gate is now 20h, and the slot walk is why.** `status_refresh_hours: 20`, committed this session and unpushed as of this writing — so any run before it lands still reads 24h and the prediction above is unaffected either way, since the due *set* does not depend on the gate width.

A 24h gate cannot hold a slot. The stamp is written mid-run — 19:24–19:26Z off a 19:19Z dispatch — so at 24h the boundary lands *inside* the same slot's own run the next day, minutes from wherever the previous run put it. Whether that run catches it depends on run-to-run variation in when litigation reaches the pass, and collector wall clock swung **384–751s** across the five measured runs. Miss it and the refresh walks forward a 6h slot. The walk from the 19:19Z dispatch to the 00:00Z slot above is one such step.

At 20h the boundary sits ~4h ahead of the slot that stamped it, clear of variation that size, so the pass pins to whichever slot last ran it: **the first run past the boundary gets the whole due set, the other three get 0.** That turns "0 due on three of four runs" into a standing invariant worth checking rather than a moving target. Cost is firing every 24h instead of every ~30h — one extra pass every few days, 24 requests each. First check: two consecutive days where the same slot carries the pass.

This run is also the **ongoing-cost measurement**, which is the one number the sweep could not produce.

**Record the denominator as a range, because a docket line is not a request.** The seed loop prints one line per docket and paginates silently — there is no `[Nreq]` marker — so line count is a floor, not a count. Both figures below are derived, neither is exact, and the refresh adds 33 once and 24 per day thereafter:

- **Floor, one request per docket line:** 34/run, 136/day → **+24.3% one-time, +17.6% ongoing.**
- **Delta-derived, pagination included:** ~42 and ~51 requests/run, **~168–204/day** → **~+17% one-time, ~+13% ongoing.**

**The pagination-inclusive figure is the truer one**, since those pages are real requests against the same ceiling. The floor only coincides with the truth on a run where every docket returns nothing, which does happen — three of these five runs had all 34 dockets at `0 entries` — but is not the steady state. The 18:42Z run is the counter-example in this very window: New York returned 10 entries and its fetch alone consumed 35.25s against a ~4.1s median.

An earlier draft of this section asserted that no log supported ~192/day. That was wrong and is struck: the delta derivation in handoff 25 is exactly such a log, and multi-page dockets there (Georgia 102 entries, Illinois 66, Vermont 53) are what it measured.

---

## Closed on the 2026-08-11 sweep

Five runs read in one pass, all gated on `0098f3d` or a descendant. Kept in full because each closes a claim that was open for days, and because a cold reader needs the numbers to tell *verified* from *pushed*.

| run | slot | wall | collectors | export | due | changed | data commit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `31423505973` | dispatch 08-10 19:19Z | 14m38s | 751s | 112s | **33** | **9** | `b8009b6` |
| `31447092199` | 08-11 00:44Z | 7m32s | 384s | 48s | 0 | 0 | none (empty diff) |
| `31466091373` | 08-11 06:42Z | 12m05s | 599s | 106s | 0 | 0 | none (empty diff) |
| `31492007355` | 08-11 12:36Z | 7m35s | 388s | 50s | 0 | 0 | `bfd21b7` |
| `31524119289` | 08-11 18:42Z | 8m02s | 411s | 50s | 0 | 0 | `118e41a` |

Two runs committed nothing. Per the standing invariant that is an empty diff, not a failure.

### The status-refresh unit — VERIFIED, migration applied, prediction exact

Header and summary, verbatim from `31423505973`:

```
litigation: status refresh, 33 row(s) due (0 skipped, non-numeric case_id)
  status refresh: 33 checked, 9 changed, 0 skipped, 0 failed
```

**33 due / 9 changed / 0 skipped / 0 failed**, matching the prediction on every field. The header firing at all proves the `status_checked_at` migration applied. No `status refresh pass failed` line in any of the five runs.

The nine flips are all `pending -> terminated`, matched to `case_id` against the `d168cc8` audit and then against Turso: `71457474`, `71982149`, `72021508`, `72054244`, `72055344`, `72110170`, `72156765`, `72333329`, `72334676`.

**Match on `case_id`, never on caption.** Two rows share the caption `United States v. Oliver` — `71982149` (the NM district orphan, terminated) and `73678095` (the live NM docket, pending). The flip line prints caption only, so a caption-keyed match silently collapses them and reports a false mismatch. This nearly produced one in the reading of this very run.

**The refresh reached three rows the seed loop cannot.** `71982149` (NM), `72156765` (VA) and `72334676` (KY) are absent from the seed artifact, so no run polls them; they carry `entries_synced_at` from late July and nothing had touched them since. All three were in the nine. That is the docstring's claim about iterating `cases` rather than the seed list, demonstrated rather than asserted.

**The orphans, per §6 of the handoff:** all three now read `terminated` with non-NULL `status_checked_at` and `superseded_by IS NULL`. The pairs are **not** asserted and nothing here asserts them.

`python -m tools.status_audit`: **0/40 disagree**, 0 in either direction. (Run twice — 80 requests — because the first invocation's summary scrolled past the tail. Own cost, worth noting against the day's draw.)

Turso state after the pass: 40 rows, **24 pending / 16 terminated**. Seven terminated rows carry NULL `status_checked_at` — they were already terminated before the pass and the gate excludes them by design, so **`status_checked_at` is not a coverage record for terminated rows.** Don't read a NULL there as an unchecked row.

### The 24h gate — WORKING, and handoff 30's own §3 premise was an arithmetic slip

All four scheduled runs reported **0 due**. Three of them were predicted; the 06:00Z run was predicted to show 24 and did not, and the gate is not the reason.

Stamps land between **19:24:42Z and 19:26:49Z on 08-10**. Plus 24h that is **08-11 19:24–19:26Z**, which falls *after* every scheduled run of 08-11 — the 18:42Z run read the gate at 18:46:58Z and missed the boundary by 37m44s. The handoff placed the boundary between the 00:00Z and 06:00Z runs; it is between the 18:00Z and the next 00:00Z. So four consecutive 0-due runs are the gate working exactly as designed, and the 33-due-every-run failure mode is ruled out four times over.

The *size* half of the prediction is confirmed independently: the gate's own query reads 24 non-terminated rows today.

This is a reading of the **24h** gate, and it stands as the measurement that motivated changing it. The config now says 20h; see the slot-pin note in *Owed right now*.

### Handoff 21–23 throttle work — VERIFIED, six checks

Was "PUSHED, VERIFIED AGAINST NOTHING." Pushed 2026-08-10 ~01:22Z with the last scheduled run having finished 00:45Z, so nothing had executed against it; the 19:19Z dispatch that day is the first run that did. Now read against five.

1. **Docket count off the run's own header:** `2 config seed(s) + 32 tracker case(s)` = **34 polled**, identical on all five runs. The 40-row table decomposes as 34 polled + 3 superseded district rows never polled (PA `71453026`, NH `71453646`, MD `71980724`, all `entries_synced_at IS NULL`) + the 3 unseeded orphans. The Georgia district row `72053306` is superseded *and* polled, which is why 4 rows carry `superseded_by` but only 3 go unpolled.
2. **No `litigation: daily cap hit`** in any run.
3. **Zero 429s.** Every `429` substring across all five logs was inspected individually and is a timestamp fragment, a wheel version, or the masked-token line — not one rate-limit response. `_log_429` never fired, which is the predicted result and also means it remains untested in production (see Open units).
4. **Spacing measured, and `PYTHONUNBUFFERED` landed** — per-docket timestamps all differ. Medians 3.95 / 4.03 / 4.13 / 4.50 / 4.58s against `PAGE_THROTTLE = 3.2` (the constant is 3.2 as built, not the 3.0 this section used to name), so latency is ~0.75–1.4s on a docket that returns nothing. **One 35.25s outlier**, 18:42Z run, on the New York line — and it is *not* unexplained: New York (`71457474`) returned **10 entries**, the largest fetch in the window, while the 33 lines around it returned 0 or 1. No 429 and no retry line. This is what a docket line costing more than one request looks like from the outside, and it is the reason the draw denominator above is a range.
5. **The mark:** `superseded_by` still `'72193752'` — load-bearing and it holds. `updated_at` now `2026-08-11T18:44:38.003622+00:00`, off the `2026-08-07T12:39:07.102924+00:00` freeze. The starvation is broken.
6. **`entries_synced_at` table-wide:** 40 rows, newest `2026-08-11T11:09:10-07:00`, 3 NULL and all 3 superseded, so the alarm `entries_synced_at IS NULL AND superseded_by IS NULL` reads **0**. The spread of older marks (07-07 through 08-08) is quiet dockets, not starvation — it is a `date_modified` high-water mark, not a last-polled stamp.

**The token question is closed by behaviour, the only instrument available.** 34 of 34 dockets covered with zero 429s at 3.2s spacing, five runs running. At the 5/min tier that spacing 429s by roughly the sixth request, so the runner's `COURTLISTENER_TOKEN` is on the 20/min tier the probe measured.

### Where the dispatch's 14m38s went — not the refresh

The dispatch ran 12+ minutes against an 8–11 expectation, and the refresh pass is **not** the explanation. Measured directly: the pass ran 19:24:39 → 19:26:50, **131 seconds**, on 33 rows at ~4s each. The decisive comparison is the **06:42Z run — 12m05s wall with a 0-second refresh pass.** Collector wall clock swings 384s → 751s across the five runs independently of the refresh, and the export step swings 48s → 112s with it. So the refresh cost 131s exactly, and the rest is ordinary run-to-run variance that predates this unit.

Every docket line in all five runs is `incremental` — **zero fresh resolves and zero full-walks** — so none of the wall clock is a bootstrap. Entry volume was 0 on 34 of 34 lines in three runs, 1 in the 12:36Z run, and 3 in the 18:42Z run (Colorado 1, Maine 2, New York 10).

### Handoff 14 invariant — CLOSED

Closed on the query the unit always wanted:

    SELECT case_id, status, superseded_by, updated_at FROM cases WHERE case_id = '72053306';

`superseded_by` reads `'72193752'` and `updated_at` has moved with the collector. Nothing about this unit is outstanding; `--apply`, the export and the data commit all shipped 07-30 (`bd4d577`) and do not get re-run. Snapshot survival across the six collector-driven data commits counted at the time (`200931f`, `dda174e`, `4059878`, `98217c5`, `7709e14`, `6eb6554`), and the further ones since, was always corroboration rather than proof — it is the query that closes it, which is why those shas are recorded here once and not tracked further.

### Handoff 15 failure ratio — CLOSED, 0 in family across 49 runs

Baseline was 3 failures in 28 runs, all Hrana in `legislation.py`, pre-`474840c`: **07-24 (cursor/EOF), 07-27 and 07-29 (stream not found, in `collect_bill`)**. Since the fix pushed 07-30 there are **49 runs and 4 non-successes, none in that family**:

- 07-31 01:26Z — org-wide Turso read block (`BLOCKED`, reads forbidden). External, CBT's doing, already excluded.
- 08-06 23:46Z, 08-07 01:58Z, 08-07 06:56Z — three consecutive runs killed by `Hrana: api error: status=502 Bad Gateway, upstream forward failed`, all three at **`db.py:235` in `_apply_migrations`, inside `init_db()`** — before any collector runs and before any connection exists to recover. A Turso platform outage, not the stream-death family, and `db.recover` is structurally incapable of addressing it. Recorded as its own unit below.

Zero in-family failures across 49 runs against a ~11% per-run baseline: if the rate were unchanged, a clean 49 has probability ~0.4%. The recovery path is confirmed and this window closes.

### Handoff 16 — CLOSED, null result

**Closed as a push gate.** Pushed 08-01 (`6eb6554..cc763c9`), four commits, verified from a fresh clone: the cache is live in `web/lib/db.ts`. The hashes this section previously listed (`a8103ac`, `f0b0683`, `c68a425`) are dead — rebased onto current origin/main before the push. Don't chase them.

**The result is a null, and it is the one the finding predicted before the push.** Read 2026-08-11 (baseline) and 2026-08-10 (post), tooltip per day, both panels:

- Rows read: 129,573/day (Jul 26 – Aug 1) → 112,331/day (Aug 2 – 8). Down 17,242, 13.3%, about 1.9 scans/day.
- Sample SDs 48,812 and 33,717; SE on the difference 22,423. The delta is **0.77 SE** — not distinguishable from zero. Indicative, not a formal test: seven consecutive calendar days aren't independent samples against a fixed cron schedule. The conclusion rests on the write ratio, not on this.
- **Rows written fell 14.9% across the same window, and no read cache can move writes.** Collector activity declined and reads tracked it. Scaling baseline reads by the write ratio predicts ~110,300/day against 112,331 observed, so the residual has the wrong sign for a saving. Nothing is left to attribute to the change.

Full point values, both series, in `docs/findings/16-channel-count-baseline.md`.

The change is still right and the cap is untouched: ≤24 scans/day independent of render volume is provable from `revalidate: 3600` and needs no dashboard reading. The delta only ever measured today's traffic against it — and at the measured baseline the strip's ceiling was **~14.5 renders/day**, already under the cap, so there was no bindable saving for the instrument to find.

Three claims died to this reading — the 150–250K band, the ~88K/day drop derived from it, and the contamination read on Aug 7. See the falsified list. The old "falls hard / barely moves" split and its ~190 renders/day ceiling are gone with them.

**Standing instrument note:** hover the chart for point values, never read the shape, and read the **Rows Written** panel in the same pass. It sits on the same page, it is the control, and taking it is what turned this delta from a signal into noise at no extra cost.

---

## Open units, roughly in order

**Handoff 17 — supersession candidate generator.** Note the renumbering: this was called 16 mid-session before the channel-count cache took that number. It carries two things, which belong together because the fix lives in the `main()` the generator extends:

- The generator itself. Reads a notice-of-appeal or dismissal entry on a terminated row, looks for an unlinked live row in the same state, and *proposes* pairs. Writes nothing, doesn't extend `PAIRS` itself. Three asserted pairs became five in a month; hand-assertion is the bottleneck.
- Handoff 14's dry-run display defect. `main()` prints the `PAIRS` constant, so the table is an echo of the input and the only real dry-run signal is `verify()`'s pass/refuse line. The display should print queried `status` and `docket_number` per row alongside the asserted ones.

**State batch-boundary unit.** Created by handoff 15's recon, not inherited. `state.py` commits once for the whole multi-state run (the two `conn.commit()` calls, lines 317 and 319), so a stream failure at the unguarded `seen_hash`/insert path propagates and discards every state processed that run. The two existing handlers (lines 252 and 273) don't catch it — they wrap LegiScan HTTP calls only. Fixing it needs per-state commits to bound the batch. state runs last in the step order, so this costs the run's export and data commit as well as state's own batch; the other five collectors' writes are already committed to Turso, so it delays the snapshot rather than losing data. Don't over-rate it.

**Dashboard redesign — from inventory to intelligence.** The homepage currently answers "what does psephos track"; it should answer "what changed and what does it connect to." Four moves, in value order:

- **Deltas on the channel counts** against the previous export. Raw totals mean nothing on a monitoring tool.
- **A merged reverse-chronological activity feed** across all five channels since the last cron, each entry tagged with channel and Admiralty grade. The grades exist in the data and appear nowhere on the page, and the feed is the cross-channel thesis rendered.
- **The DOJ voter-data campaign as one object**, not dozens of near-identical rows: a state grid with status coloring, exceptions surfaced (GA refile, KY appeal, circuit cases), dormant dockets demoted behind it.
- **Watched bills sorted by recent cross-channel activity**, with correlation on the card (news volume, related litigation), so S. 1383 mid-floor-fight doesn't render identically to a bill dormant since referral.

All read-layer: no collector or schema changes. The deltas are the only new data need, and that's one comparison against the prior snapshot. Mockup exists in the 08-01 session. **Sequencing: this goes before the snapshot migration, not after.** The earlier order was backwards. The feed is what determines whether the read path needs the 3,058 unattached news items, and no snapshot carries them, so building the feed settles the migration's data requirement rather than guessing at a requirement that does not exist yet. The strip resolves the same way: the redesign wants deltas rather than raw totals, and if totals go then `getChannelCounts` goes with them, the snapshot strip's 97% news under-report never arises, and handoff 16's cache resolves by deletion. None of that touches the handoff-16 chart reads, which are baseline measurements and stand either way.

**Read-layer snapshot migration: falsified, recommend not doing it.** Measured in handoff 18. The finding is `docs/findings/18-snapshot-parity.md` (`acf5713`); read it before reopening this.

The export itself is clean. The reconciliation closes to zero: 6,089 item references across the four files, 6,089 distinct ids, plus 3,058 invisible news items, against a 9,147-row spine. Nothing lost, nothing double-counted, every channel reconciling on its own. News is the only channel with an invisible set.

Six fields the web layer renders or sorts on are absent from the snapshots: `bills.title`, `bills.introduced_at`, `cases.latest_entry_at`, `cases.source_url`, `state_bills.description`, `items.summary`. All six are addable, and only `cases.latest_entry_at` is non-static, so it is the single one needing a byte-stability check before it goes in. The migration is therefore cheaper than the falsification expected it to be.

Cheaper is not worth doing, and nothing in handoff 18 touched the benefit side. Read cost was the justification, and handoff 16 measured it at a **129,573 rows/day mean** (Jul 26 – Aug 1, point values) rather than the 1.7M spike that motivated it — lower than the 150–250K band this line used to name, which was itself falsified. Preview-crawl exposure is not a live cost, and the earlier claim that it "closes in a settings toggle" was wrong in both halves. Nothing is open: every preview-shaped hostname (per-deployment, project alias, git-branch alias) returns a Vercel SSO redirect with `X-Robots-Tag: noindex` to an unauthenticated request, and no previews are produced at all, since the last 100 GitHub deployments are all Production, origin carries one branch, and no PR has ever been opened. So this leg is removed from both sides rather than recovered. The recommendation is unchanged, and rests on the read-cost falsification above. The production surface above is a different matter: snapshot serving would take it off Turso entirely. That doesn't move the recommendation, and ~130K/day is the measured regime with this surface already live. It does mean the migration has one live benefit rather than none. What remains is cost: `cases.json` and `state_bills.json` are already 964K and 1.5M, 5,971 timeline entries would each gain a summary paragraph, and the swap converts collector reliability into a front-end freshness dependency. Today a run that writes Turso and dies before export leaves the site correct. After a migration it leaves the site stale with no signal, and the run-failure rate is the number that prices that risk — now measured at 4 non-successes in 49 runs, none of them the recoverable family, with one Turso outage taking three of them (see the closed record above).

**What reopens this:** the redesign's activity feed needing the 3,058 unattached news items. No snapshot carries them, so that requirement means a fifth export file and the question returns on data grounds instead of cost grounds. Build the feed and find out. See the sequencing note under the redesign above.

**Kentucky supersession candidate — unlinked.** Both rows carry `superseded_by = NULL`; nothing is asserted. `72334676` (E.D. Ky. 3:26-cv-00019) took judgment of dismissal with prejudice 2026-07-23, notice of appeal 07-24; `73674243` (6th Cir. 26-5657) opened 07-24. The district row still reads `status = pending`, so `verify()` correctly refuses it. Gated on CourtListener setting `date_terminated`. **Do not weaken the guard to accommodate it.** On the court's clock, nobody else's.

**Deployment Protection — closed.** The production alias is `psephos-theta.vercel.app`, not `psephos.vercel.app` — that name was already taken, and the 429 `X-Vercel-Mitigated: challenge` it returns is someone else's surface. `vercel inspect` lists the real aliases; check there before curling a hostname you guessed. Previews are gated and none exist: every preview-shaped hostname (per-deployment, project alias, git-branch alias) 302s to `vercel.com/sso-api` with `X-Robots-Tag: noindex` for an unauthenticated request, the last 100 GitHub deployments are all Production, origin carries one branch, and no PR has ever been opened. Configuration read 2026-08-05 and it matches the behavior. Plan is Pro; Vercel Authentication is on at Standard Protection, which covers previews and non-current production deployment URLs and leaves the up-to-date production domain public. So `psephos-theta.vercel.app` answering 200 is the configured posture, not a gap in it, and the preview 302s are the same setting's other half. The control is interactive rather than greyed, so this is a choice rather than an inherited default. A broader scope covering production would be the wrong outcome for a public monitor; which scopes this plan actually offers is unrecorded — check the dropdown before relying on it. Protected Sourcemaps is on. Password Protection and Deployment Protection Exceptions sit behind the $150/month Advanced add-on and neither is needed. Re-check with `vercel inspect` for aliases and Settings → Deployment Protection for the mode.

**Production read surface.** `psephos-theta.vercel.app` answers 200 to an unauthenticated request, uncached (`no-store`, `X-Vercel-Cache: MISS`), with no `X-Robots-Tag` and no `/robots.txt`, so every anonymous request runs the force-dynamic routes' queries against Turso. Public is correct for a public monitor. Unbounded is the open question. A static `/robots.txt` is the cheap lever and bounds crawler traffic without touching the read path or the migration question; against that, a monitor nobody can find is worth less than one costing a few thousand reads a day. Not built here.

**Vercel connector scope.** `list_projects` returns four projects, all predating psephos's first commit, and `get_project` / `get_project_deployment_protection` 404 on the psephos slug, while GitHub's commit status points at `vercel.com/csu-j3s-projects/psephos`. The connector's scope does not cover the team the project lives in. Routing around it by curling three hostnames worked once and will not generalize. Fix the scope before the next Vercel read depends on it.

**`_reset_seconds` scope parsing.** The daily-vs-burst classifier discriminates on the *magnitude* of the reset rather than on what the 429 actually says, which is why a minute throttle with a long enough reset has now twice been read as a daily cap. The 429 body names its own scope (`Rate limit exceeded: 5/min`) and `common._log_429` already puts that string in the log; the rewrite is to parse it and branch on the scope instead of the number. Not urgent — pacing removed the trigger and the logging removed the blindness — but the heuristic is still structurally unsound and will misfire again the next time a window changes. The captured artifact that makes the case is `docs/findings/22-throttle-scope-vs-magnitude.md`: a 429 whose body says `20/min` and whose `retry-after` says 46, in one response. Read it before reopening this.

**`init_db` transport retry — BUILT this session, unpushed, and unverifiable by a clean log.** Was "`init_db` has no retry, and a transient Turso 502 costs the whole cycle." The three failures are unchanged as facts: 08-06 23:46Z, 08-07 01:58Z, 08-07 06:56Z, all on `Hrana: api error: status=502 Bad Gateway, upstream forward failed` at `db.py:235` in `_apply_migrations`, inside `init_db()` — before any collector ran and before any connection existed, so `db.recover` and the handoff-15 machinery cannot reach it by construction.

`db._retry_transport` now wraps establishment on both remote paths: `init_db`'s whole bootstrap (connect + `_apply_migrations` + `executescript`, retried as one unit — libsql's `connect()` is lazy, the 502s were raised by the migration probe's *first statement*, so retrying the connect alone would have retried nothing), and `connect()`'s establishing PRAGMA, whose retrying variant is also what `reopen` receives, so `_Conn.execute`'s stale-stream recovery and `reset()` inherit it. Four attempts, sleeps 1.5 / 3 / 6, ~10.5s. Six tests in `tests/test_db.py`, including the one that keeps the two Turso failure families apart: the real stale-stream string must not match `_TRANSPORT_ERRORS` and must still take the single-reopen path with no sleep.

**The size claim that motivated this was wrong; see the falsified list.** All three 502s were at a dedicated schema-bootstrap *step* whose unguarded connection ran seconds before the collectors, and `2eec868` removed that step on 08-08. What the retry actually guards is the six per-collector `init_db()` calls and `connect()`'s PRAGMA, and there are **zero observed failures at either**. So this is insurance and an instrument, not the repair of a measured defect. The instrument is the stderr line (`db: connect hit a transport error (...); retry 1 of 3 in 1.5s`) — a healthy run prints nothing, which means a clean log is not evidence that the retry works, the same blindness `_log_429` has.

**Amplification is bounded by the job, not by the ladder.** `_Conn.execute` retries once and its reopen now carries the ladder, so in a sustained outage every failing statement can cost 10.5s and a per-item `recover()` another; `state.py` iterates 484 bills, so a one-second failure becomes hours of sleep. `collect.yml` had no `timeout-minutes`, so the default 360 applied and a hung run would collide with the next cron. It now carries `timeout-minutes: 30` against runs that measure 6–12 minutes.

**The one-call-per-run alternative is rejected, on the record, so it does not get re-proposed.** Having one collector call `init_db()` while the other five rely on it having run recreates the defect `2eec868` removed: a bootstrap in a different location with the same single point of total failure. Six idempotent calls are the resilient design, and the ~1,200 no-op statements per run are what that costs.

**A test that fires `_log_429` deliberately.** Sits next to the unit above and is the smaller half of it. The detector has never fired in the collector — now confirmed across five post-pacing runs at 3.2s spacing, zero 429s in any of them — and if the pacing is right it never will in a healthy run, so a clean run is not a passing test of it, and its first genuine invocation would otherwise be the incident it exists to catch. Wants a synthetic 429 driven through the classification path, asserting the body reaches stderr and that the Authorization header is redacted in both the header map and the body. Reasoning in the finding above.

**The de-tiering itself — cause unknown.** The API Usage table shows 147 requests on 08-05 falling to 84, then 65, then 25 across the following days. The account's rate changed server-side, with no notification, no error, and no log line; the collector's behavior changed underneath code that had not been touched. Whether it was a membership lapse, a policy change, or something applied to the account by hand is unknown, and no artifact in the repo or the dashboard says. Worth one question to Free Law Project, because the answer determines whether the six-month renewal above is the only cliff to watch or just the one with a date on it.

**The `~/.gitignore_global` decision.** `docs/handoffs/` is ignored at the workstation level, which makes it not a psephos decision. Two consequences: it applies to every repo on that machine with such a directory, CBT included; and it's machine-local, so whether those files are tracked depends on which box you're on. The real question is whether that global pattern should exist at all, and if so whether each repo needs an explicit committed decision rather than inheriting a workstation default. Cross-repo, so probably not a psephos unit.

**Michigan.** 6th Cir. `26-1225` (`72347022`) reads terminated with no successor and no district row held. Probably a decided appeal rather than a supersession. Worth one look when the generator gets built, not before.

---

## Standing invariants

Things that have bitten before and will again.

- Every collector must exit 0. The workflow runs them as sequential lines in one `-e` bash step; a non-zero exit stops export and the data commit.
- CourtListener access level, measured 2026-08-09 from the account's own Developer Tools → API Usage panel: **20 requests/minute, 1,000 requests/hour**. The panel renders two stats where the free tier renders three; **no daily figure is shown at this tier.** That is what the panel shows, not proof that no daily throttle exists — do not write "no daily limit" anywhere. The level comes from a free **EDU membership** tied to the university email on the account, and it **expires every six months — it does not auto-renew.** That distinction is the whole point of recording it: this is not a subscription that keeps running until a card declines, it is a term that ends unless somebody acts. The default outcome of forgetting is a lapse back to 5 requests/minute, the tier that produced five consecutive runs at 5-of-34 coverage. The membership landed 2026-08-09, so expiry falls around **2027-02-09** — derived from the landing date, not read off the account. The real date is in the confirmation from `donate.free.law` and in the membership section of the CourtListener account; read either before relying on the derived one. A lapse is silent: no notice, no error, no log line (that is exactly how 08-05 → 08-06 happened). Verifying instrument for every number here is the API Usage panel, **never a log count** — logs only ever see what the throttle let through.
- There is no `X-RateLimit-*` header on a CourtListener response, so a 429's **body** is the only artifact naming which throttle fired; `retry-after` gives a delay with no scope attached. `common._log_429` writes url, headers, and body to stderr on every 429, retried ones included. Quote the scope string verbatim when reporting one.
- Litigation's daily-cap abort fires on `num_requests × spacing < MAX_RETRY_AFTER`, not on any daily budget. That product is the whole classifier: 5/min at ~2.7s spacing aborted at request 6, 10/min at ~2.7s aborted at request 11 on 08-05, and 20/min at `PAGE_THROTTLE = 3.2` does not abort at all. A throttle whose reset outlasts the rest of the run reads as hopeless to the magnitude heuristic regardless of scope. `PAGE_THROTTLE` and the classifier are therefore not independent knobs; changing one changes the other's behavior. Measured wall spacing at 3.2 is **3.95–4.58s median** across five runs (08-10/08-11), i.e. the constant plus ~0.75–1.4s of latency — quote the measured figure, not the constant, when reasoning about how fast a window fills.
- Match a case on `case_id`, never on `caption`. Two rows in `cases` share the caption `United States v. Oliver` (`71982149`, the terminated NM district orphan, and `73678095`, the live NM docket). The refresh pass's flip line prints caption only, so a caption-keyed join silently collapses them; it produced a false mismatch during the 08-11 sweep and was caught only by querying Turso.
- `cases.status_checked_at` is not a coverage record. The refresh gate excludes `status = 'terminated'` because termination is absorbing on the court's clock, so a row that was already terminated before the pass keeps `status_checked_at IS NULL` forever — 7 of 40 rows as of 08-11. A NULL there means *never due*, not *never checked*.
- Free Law Project runs a weekly maintenance window, **Thursdays 21:00–23:59 Pacific.** Pacific is the primary statement because that is how FLP states it and because psephos crons on fixed UTC, so the UTC boundary walks an hour with DST: Fridays **04:00–06:59 UTC** under PDT, Fridays **05:00–07:59 UTC** under PST. The Friday 06:00Z run falls inside the window under both, which is the durable fact and the reason this is recorded. Nothing in psephos accounts for it.
- Database facts come from direct Turso queries, never from JSON snapshots. Snapshots are a lagging derivative and can produce false greens. This applies to the orphan alarm, the supersession invariant, and anything else asserting a row's state.
- Absent cron commits are not failures. An empty-diff run commits nothing by design, so gaps in the 4/day schedule prove nothing without `gh run list`.
- LegiScan needs `getMasterList`, not `getMasterListRaw`. Raw omits `title`/`description`, so election filters silently match zero bills.
- Retry ladders are bounded by the job, not by themselves. `db._retry_transport` is ~10.5s per failing establishment and `_Conn`'s reopen inherits it, so a sustained outage multiplies that by every failing statement and every per-item `recover()`. `collect.yml` carries `timeout-minutes: 30` against runs that measure 6–12 minutes. Keep it, and re-derive it before lengthening any ladder.
- Per-item error handlers recover via `db.recover`, never bare `conn.rollback()`. The remote backend's rollback raises on a dead stream, and a raising handler is a failed run.
- `git check-ignore -v <path>` names the ignoring file and line. Use it when something is untracked and the repo `.gitignore` doesn't explain why.
- Port 3001 for psephos dev, 3000 is CBT. Process cleanup scoped by port via `netstat`/`taskkill /PID`, never by image name.
- psephos and CBT share the `csu-j3` Turso account and its quota. A block in one may be the other's doing.
- A claim in a comment or a doc should name the command that checks it. The `data/psephos.db` parenthetical survived 212 commits as a false statement because it asserted a fact with no way to re-verify in place, so nobody ever did. `git check-ignore -v`, `git ls-files`, `git log --all -- <path>`: a claim that names its own check has a much shorter half-life as a lie.

---

## Falsified — running list

Spans sessions, not just the current one. Kept because the pattern matters more than the individual errors: every one was a confident claim about read cost or repo state, and every one died to a single command or a single chart. Every entry is a claim made in review or in a handoff. None is a defect in the repo.

- **Prefetch as the read amplifier.** Wrong. No `loading.tsx` means App Router doesn't fully prefetch dynamic routes, so "every prefetch is a full render" never held.
- **`items` ≈ 6,053 rows.** That was a floor derived from snapshots, correctly labeled and then used as a magnitude anyway. Actual was 8,931 at 08-01 and 9,147 at 08-05; the gap is the unattached items, 3,058 of the 3,142 news items carrying no bill/case/state ref, so they never attach and appear in no snapshot. The spine grows. Read any count on this page with its date attached.
- **`docs/handoffs/` isn't gitignored.** Read from the repo `.gitignore` in a clone, which can't see `~/.gitignore_global`. The conclusion held by accident; the reasoning didn't.
- **state.py as a seventh bare-rollback site.** Inferred from the handler's shape without checking what the `try` wrapped. Both sites wrap pure-HTTP calls that never touch `conn`, and with the only commits at 317/319 a `reset()` there would have discarded every prior state's pending writes.
- **~4 cache cold starts/day from deploys.** Vercel's Data Cache persists across deployments, so the cron's data commit doesn't invalidate `unstable_cache` entries. The cap is the ≤24/day from the revalidate window alone.
- **~1.7M rows/day as psephos's rate.** Carried from the CBT thread as a user-provided peak of unstated shape, then used as a sustained rate. The per-database chart shows it is a **single-day spike on ~Jul 21**; the Jul 26 – Aug 1 regime is 70K–207K/day, mean 129,573 (the ~150–250K first written here has its own entry below). Everything derived from it inherited the error — the ~190 renders/day ceiling was ~8× too high, and the "falls hard → the strip was the bulk" branch it created was never live. Same failure as the 6,053 floor: a number correctly labeled *provisional* and then used as a magnitude.
- **Handoff 14 as an unstarted unit.** Listed as owing `--apply`, export, and a data commit. All three shipped 07-30 (`bd4d577`) and have survived six collector-driven exports. Only the read-only Turso proof was ever outstanding. A stale owed-list entry is as misleading as a wrong measurement, and costs more, because it invites redoing finished work.
- **The state-bill sort as structurally unfixable.** Handoff 18's Part A asserted, in bold, that `getStateBills`' `COALESCE(last_action_at, updated_at)` could not be reproduced by extending the export, since `build_state_bills` omits `updated_at` for byte-stability. Wrong, and reproducible today: the 81 `(state, last_action_at)` ties break on `state_bill_id`, which the snapshot carries, and the arm that actually needs `updated_at` is `last_action_at IS NULL`, which is 0 of 484. Same failure as the `state.py` rollback claim: read the shape of the clause, saw an omitted column, asserted structural impossibility, never counted the nulls. Died to one COUNT. The guard still belongs beside that sort, because 0 of 484 is a property of today's data and not of the schema.
- **Eight query functions in `web/lib/db.ts`, seven mapping cleanly onto the snapshots.** Thirteen, and six rendered-or-sorted fields absent. The count came from a truncated grep read as though it were the file, in the same message that recommended a build decision off the back of it.
- **psephos as free-tier.** Asserted while flagging in the same sentence that the plan hadn't been checked. It's Pro. Hedging one claim and asserting the adjacent one from the same guess is the same failure wearing a disclaimer.
- **`All Deployments` as a Pro option.** Read off Vercel's docs and written into the unit as fact, in the same commit as the free-tier entry above and about the same plan. Documentation describes the product; the dropdown describes this project. Only the second one is a measurement, and it went unopened.
- **CourtListener as 250 requests/day.** Carried in the standing invariants and used as the denominator for every statement about litigation's coverage. It was never read off this account and has no traceable origin in the repo at all. It was not even the vendor's number: the authenticated free default is 125/day, so the figure was wrong by 2× in the direction that made the budget look comfortable. The measured access level is now recorded in the invariants above, and the daily is recorded as *not shown at this tier* rather than replaced with another unread number. Correcting instrument is the API Usage panel, not a log count.
- **The litigation cap resetting around 08:10Z.** Handoff 10 closed on "the litigation cap resets around 08:10Z; marks should climb on the first run after that," and the number has been repeated since. There is no reset time. DRF throttles are rolling windows with no concept of what day or hour it is — `SimpleRateThrottle` drops each request from its history exactly `duration` seconds after that request was made — so marks climbing after 08:10Z were old requests aging out one at a time, not a period rolling over. Corroborated by the 08-08 probe, whose 429 carried `retry-after: 55` six seconds into a five-request burst: a countdown from the oldest request still in the window, not to any clock boundary. Tier-independent, so this one is corrected outright rather than left pending.
- **"74 of 250, under 30% of the daily budget — independent confirmation the daily cap is not what is firing."** Handoff 20 part B. The conclusion was right and the evidence was worthless, which is the worse failure of the two. The 74 was counted inside the suppressed window: consumption looked low *precisely because* the minute throttle was strangling the run before it could spend. A log count measures what the throttle let through, so it is structurally incapable of showing that a throttle is not binding — the tighter the throttle, the more reassuring the number. Real pre-abort baseline is 102–162 requests/day. Correcting instrument, the same as the two entries above: the API Usage panel, read off the account.
- **Preview-crawl exposure, twice.** First asserted to close in a settings toggle, then corrected to nothing-is-open. Both were reasoning about `psephos.vercel.app`, which is not this project's hostname. The production alias is `psephos-theta.vercel.app` and it was never checked. A hostname picked by pattern-matching the project name is a guess, and `vercel inspect` would have said so at any point.
- **The 150–250K rows/day baseline band.** Eyeballed off a chart segment on 08-01, then recorded in a findings table and cited across three documents as a measurement. **Five of the seven baseline days fall below 150K** (70,208 / 97,480 / 108,033 / 117,789 / 121,429); the range is 70K–207K and the mean is 129,573. The check that catches it is hovering the same chart for point values — available on 08-01, on the same screen, and not done. Same failure as the 1.7M entry above, one instrument later: read the shape of a chart, wrote down a range, used the range as a number.
- **"~88K/day drop the cache cannot explain."** Derived by subtracting post-push point values from the *midpoint of the estimated band*. Comparing an estimate against a measurement and treating the gap as signal. The real delta against a measured baseline is 17,242/day at 0.77 SE, and the write series accounts for all of it. Same class as the run-duration error made the same day.
- **The 24h refresh boundary falling between the 00:00Z and 06:00Z runs.** Handoff 30 §3, which predicted 24 due at 06:00Z and named a 33 there as proof of a broken gate. The stamps read 19:24:42–19:26:49Z on 08-10, so the boundary is **19:24Z on 08-11**, after the 18:00Z run and before the next 00:00Z — the opposite end of the day. Four consecutive 0-due runs were therefore the gate working, and a section written to detect a broken gate would have read the correct behaviour as the failure it was looking for. A boundary time asserted without computing it, when the stamps it needed were already recorded. Instrument: arithmetic on `status_checked_at`. Caught on the stamp read before it cost anything.
- **The `init_db` 502 as "the largest availability defect the project has found."** Written this session while proposing the retry, about a step that no longer exists. All three failures were at the dedicated schema-bootstrap step's unguarded connection; `2eec868` removed that step on 08-08, and `collect.yml` lines 26–30 say so and say why. That file had been read earlier in the same session — the instrument was the workflow itself, open in front of me. The residual is real and small: six idempotent per-collector `init_db()` calls and `connect()`'s PRAGMA, **zero observed failures at either**. A defect's size asserted without checking whether the code that produced it still existed, which is the same failure as the falsified entries above wearing a different hat: the measurement was fine, the thing it measured had been deleted. Correcting instrument: `git log -- .github/workflows/collect.yml`, or reading the comment already sitting in the file.
- **"Aug 7's minimum is consistent with contamination."** The post-push window does contain real contamination — the CourtListener de-tiering and the litigation starvation both fall inside it — and Aug 7's 69,615 was read as its fingerprint. **Jul 27 read 70,208 with no 502s and no starvation.** A ~70K day is ordinary in this series. The contamination is documented and real; it does not surface above the noise in this instrument, and a known confound is not a licence to read any low point as its evidence.

The claims that survived were the ones someone queried: the `getChannelCounts` scan (provable from the schema), `items = 8,931` (measured against production 2026-08-01), the handoff-14 data commit (checked with `git log`, not recalled), and finding 16's advance prediction of a small-to-invisible delta (written before the reading, confirmed at 0.77 SE against a write-series control).
