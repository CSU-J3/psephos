# psephos — status and backlog

Living doc. Belongs at `docs/status.md`, **tracked** (`docs/handoffs/` is ignored via `~/.gitignore_global`, so nothing durable goes there). Update it at the end of a session, not the start.

Last updated: 2026-08-10.

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
- `updated_at` moved on any of the usable runs is corroborating.
- `updated_at` unmoved *and* no cap-abort *and* no read-block on the runs that did complete is a real finding: the seed isn't being polled. One run missing it is noise. Three reasons it can legitimately be unmoved now (cap-abort, read-block, run failure), so rule each out by name before calling it a finding.

**Read this alongside §2 and §3 on ~08-08.** All three are log or dashboard reads on the same runs; doing them in one sitting costs one sweep instead of three. What follows them is a build decision, not another read — but not the one this line used to name. Handoff 18 already settled the migration against the redesign: the migration is falsified and the redesign goes first (see Open units). What follows is the redesign itself, and then handoff 17.

### 2. Handoff 15 failure ratio — window open, don't close early

Baseline is 3 failures in 28 runs, all Hrana in `legislation.py`, pre-`474840c`: 07-24 (cursor/EOF), 07-27 and 07-29 (stream not found, in `collect_bill`).

That figure is window-specific and will look wrong if you glance at recent failures instead. The last 40 runs contain 5, and the other two aren't the Hrana family: 07-31 01:26Z is the org-wide Turso read block (post-fix, external, doesn't count against the recovery window), and 07-23 01:26Z predates the recon window and was never inspected. Compare like-for-like or it reads as a regression that isn't one.

Read at ~28 post-fix runs, roughly a week. **Not two days.** The original handoff said two days and that was underpowered: at the ~11% per-run baseline rate, 8 runs come back clean about 40% of the time even if the fix changed nothing. Twenty-eight runs drops that to ~4% and compares like-for-like against the baseline window.

**Next read: ~2026-08-08.** The fix pushed 07-30 (`474840c`); at 4 runs/day that clears 28 post-fix runs with margin. Same sitting as §1 and §3.

If the family recurs, pull the failing line before proposing anything. Same site means `reset()` isn't recovering; a different site means the audit missed one. Those want different fixes.

While in the logs, note litigation's request consumption. Litigation runs third, after legislation in the same `-e` step, so those 3 failed runs aborted before it ever ran and it polled nothing on them; the fix makes ~11% more runs *reach* litigation, adding that draw against the same CourtListener allowance — which is 20/min and 1,000/hour, not the 250/day this line used to name; see the invariants and the falsified list. Handoff 7's incremental polling should absorb it, handoff 8's abort is the backstop. Report a cap-abort; don't act on a single occurrence.

### 3. Handoff 16 — PUSHED; one chart re-read owed ~08-08

**Closed as a push gate.** Pushed 08-01 (`6eb6554..cc763c9`), four commits, verified from a fresh clone: the cache is live in `web/lib/db.ts` and the finding carries its prediction. The hashes this section previously listed (`a8103ac`, `f0b0683`, `c68a425`) are dead — rebased onto current origin/main before the push. Don't chase them.

The 24h `turso db inspect` gate is **deleted, not satisfied.** The Turso dashboard charts rows read per day per database directly (app.turso.tech → Databases → psephos → Analytics → Rows Read), so the two-reading cumulative protocol was unnecessary; no reading was ever taken under it. Baseline is recorded in `docs/findings/16-channel-count-baseline.md`: ~150–250K/day for Jul 26 – Aug 1, read 08-01 ~21:45Z.

What's owed is one re-read of the same chart, same sitting as §1, §2, and §4. Due ~2026-08-08 and **now overdue** — as of 2026-08-10 it has not been taken. The window to read is Aug 2–8 against the Jul 26 – Aug 1 baseline.

**Expect it to show nothing, and don't treat that as failure.** At ~200K rows/day against 8,931 rows/scan the strip accounts for at most ~22 renders/day — a ceiling, since collectors read too — and the cache cap is ≤24/day. Current behaviour already sits at or under the cap, so the delta may be invisible inside the noise of a 150–250K band. The finding predicts this in advance rather than explaining it afterward. The change is still right: it makes a bounded cost a property of the code instead of a property of today's traffic.

The old "falls hard / barely moves" split and its ~190 renders/day ceiling are gone — see the falsified list.

### 4. Handoff 21–23 throttle work — PUSHED, VERIFIED AGAINST NOTHING

The session closed with everything on origin and **no run having executed against it.** Pushed 2026-08-10 ~01:22Z; the last scheduled run finished 00:45Z. So the throttle pacing, the unbuffering, and `_log_429` are all unproven in production, and this section exists so a cold reader does not read *pushed* as *verified*.

What shipped: `common._log_429` (dump the 429 before classifying), `PYTHONUNBUFFERED` on the collectors step, `PAGE_THROTTLE` 2.0 → 3.0, and the access-level corrections in the invariants and the falsified list. What is measured and solid is the **tier**, from a direct probe: first-429 at index 21, body `Rate limit exceeded: 20/min`, `retry-after: 46`, on the same token the collector loads (`docs/findings/22-throttle-scope-vs-magnitude.md`).

Read the first scheduled run after 06:00Z 2026-08-10. Six checks:

1. **Docket count, read off the run's own header line** — `N config seed(s) + M tracker case(s)`. Do **not** check against a remembered 34. The table holds 40 cases; 34 came from one run's header and was promptly treated as a constant, which is the same error class as the 250/day figure two entries down the falsified list. If the run prints 37 or 40, that is the header being read correctly, not a failure.
2. **No `litigation: daily cap hit`.**
3. **Zero 429s**, which is the prediction — at ~3.7s spacing the 60s window never fills. If any fire, `_log_429` prints the full body; quote the scope string verbatim.
4. **Per-docket timestamps that differ from each other**, confirming `PYTHONUNBUFFERED` landed. Every line in the pre-push logs carried the process-exit timestamp. Report observed spacing against the predicted ~3.7s; this is the first real measurement of litigation's spacing the project has had.
5. **The mark**, direct Turso query, subsuming §1's: `superseded_by` still `'72193752'` and `updated_at` off `2026-08-07T12:39:07.102924+00:00` on case `72053306`.
6. **`entries_synced_at` across the whole table**, not one case. The starvation was table-wide since 08-06 — one row advancing does not prove the tail did.

**The run is also the only available proof that the runner's `COURTLISTENER_TOKEN` is the token the probe measured.** GitHub secrets are write-only; nothing local can read the runner's value. Workflow behaviour is the sole evidence, so a full-coverage run is what closes that question and nothing else can.

Note that §1's mark query, §2's failure-ratio sweep, and §3's chart re-read are all still owed and all read the same runs. Doing them in one sitting with the six checks above costs one log sweep instead of four.

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

All read-layer: no collector or schema changes. The deltas are the only new data need, and that's one comparison against the prior snapshot. Mockup exists in the 08-01 session. **Sequencing: this goes before the snapshot migration, not after.** The earlier order was backwards. The feed is what determines whether the read path needs the 3,058 unattached news items, and no snapshot carries them, so building the feed settles the migration's data requirement rather than guessing at a requirement that does not exist yet. The strip resolves the same way: the redesign wants deltas rather than raw totals, and if totals go then `getChannelCounts` goes with them, the snapshot strip's 97% news under-report never arises, and handoff 16's cache resolves by deletion. None of that touches §3. The 08-08 chart read is a baseline measurement and stands either way.

**Read-layer snapshot migration: falsified, recommend not doing it.** Measured in handoff 18. The finding is `docs/findings/18-snapshot-parity.md` (`acf5713`); read it before reopening this.

The export itself is clean. The reconciliation closes to zero: 6,089 item references across the four files, 6,089 distinct ids, plus 3,058 invisible news items, against a 9,147-row spine. Nothing lost, nothing double-counted, every channel reconciling on its own. News is the only channel with an invisible set.

Six fields the web layer renders or sorts on are absent from the snapshots: `bills.title`, `bills.introduced_at`, `cases.latest_entry_at`, `cases.source_url`, `state_bills.description`, `items.summary`. All six are addable, and only `cases.latest_entry_at` is non-static, so it is the single one needing a byte-stability check before it goes in. The migration is therefore cheaper than the falsification expected it to be.

Cheaper is not worth doing, and nothing in handoff 18 touched the benefit side. Read cost was the justification, and handoff 16 measured it at 150–250K rows/day rather than the 1.7M spike that motivated it. Preview-crawl exposure is not a live cost, and the earlier claim that it "closes in a settings toggle" was wrong in both halves. Nothing is open: every preview-shaped hostname (per-deployment, project alias, git-branch alias) returns a Vercel SSO redirect with `X-Robots-Tag: noindex` to an unauthenticated request, and no previews are produced at all, since the last 100 GitHub deployments are all Production, origin carries one branch, and no PR has ever been opened. So this leg is removed from both sides rather than recovered. The recommendation is unchanged, and rests on the read-cost falsification above. The production surface above is a different matter: snapshot serving would take it off Turso entirely. That doesn't move the recommendation, and 150–250K/day is the measured regime with this surface already live. It does mean the migration has one live benefit rather than none. What remains is cost: `cases.json` and `state_bills.json` are already 964K and 1.5M, 5,971 timeline entries would each gain a summary paragraph, and the swap converts collector reliability into a front-end freshness dependency. Today a run that writes Turso and dies before export leaves the site correct. After a migration it leaves the site stale with no signal, and §2 is the number that prices that risk.

**What reopens this:** the redesign's activity feed needing the 3,058 unattached news items. No snapshot carries them, so that requirement means a fifth export file and the question returns on data grounds instead of cost grounds. Build the feed and find out. See the sequencing note under the redesign above.

**Kentucky supersession candidate — unlinked.** Both rows carry `superseded_by = NULL`; nothing is asserted. `72334676` (E.D. Ky. 3:26-cv-00019) took judgment of dismissal with prejudice 2026-07-23, notice of appeal 07-24; `73674243` (6th Cir. 26-5657) opened 07-24. The district row still reads `status = pending`, so `verify()` correctly refuses it. Gated on CourtListener setting `date_terminated`. **Do not weaken the guard to accommodate it.** On the court's clock, nobody else's.

**Deployment Protection — closed.** The production alias is `psephos-theta.vercel.app`, not `psephos.vercel.app` — that name was already taken, and the 429 `X-Vercel-Mitigated: challenge` it returns is someone else's surface. `vercel inspect` lists the real aliases; check there before curling a hostname you guessed. Previews are gated and none exist: every preview-shaped hostname (per-deployment, project alias, git-branch alias) 302s to `vercel.com/sso-api` with `X-Robots-Tag: noindex` for an unauthenticated request, the last 100 GitHub deployments are all Production, origin carries one branch, and no PR has ever been opened. Configuration read 2026-08-05 and it matches the behavior. Plan is Pro; Vercel Authentication is on at Standard Protection, which covers previews and non-current production deployment URLs and leaves the up-to-date production domain public. So `psephos-theta.vercel.app` answering 200 is the configured posture, not a gap in it, and the preview 302s are the same setting's other half. The control is interactive rather than greyed, so this is a choice rather than an inherited default. A broader scope covering production would be the wrong outcome for a public monitor; which scopes this plan actually offers is unrecorded — check the dropdown before relying on it. Protected Sourcemaps is on. Password Protection and Deployment Protection Exceptions sit behind the $150/month Advanced add-on and neither is needed. Re-check with `vercel inspect` for aliases and Settings → Deployment Protection for the mode.

**Production read surface.** `psephos-theta.vercel.app` answers 200 to an unauthenticated request, uncached (`no-store`, `X-Vercel-Cache: MISS`), with no `X-Robots-Tag` and no `/robots.txt`, so every anonymous request runs the force-dynamic routes' queries against Turso. Public is correct for a public monitor. Unbounded is the open question. A static `/robots.txt` is the cheap lever and bounds crawler traffic without touching the read path or the migration question; against that, a monitor nobody can find is worth less than one costing a few thousand reads a day. Not built here.

**Vercel connector scope.** `list_projects` returns four projects, all predating psephos's first commit, and `get_project` / `get_project_deployment_protection` 404 on the psephos slug, while GitHub's commit status points at `vercel.com/csu-j3s-projects/psephos`. The connector's scope does not cover the team the project lives in. Routing around it by curling three hostnames worked once and will not generalize. Fix the scope before the next Vercel read depends on it.

**`_reset_seconds` scope parsing.** The daily-vs-burst classifier discriminates on the *magnitude* of the reset rather than on what the 429 actually says, which is why a minute throttle with a long enough reset has now twice been read as a daily cap. The 429 body names its own scope (`Rate limit exceeded: 5/min`) and `common._log_429` already puts that string in the log; the rewrite is to parse it and branch on the scope instead of the number. Not urgent — pacing removed the trigger and the logging removed the blindness — but the heuristic is still structurally unsound and will misfire again the next time a window changes. The captured artifact that makes the case is `docs/findings/22-throttle-scope-vs-magnitude.md`: a 429 whose body says `20/min` and whose `retry-after` says 46, in one response. Read it before reopening this.

**A test that fires `_log_429` deliberately.** Sits next to the unit above and is the smaller half of it. The detector has never fired in the collector and, if the pacing is right, never will in a healthy run — so a clean run is not a passing test of it, and its first genuine invocation would otherwise be the incident it exists to catch. Wants a synthetic 429 driven through the classification path, asserting the body reaches stderr and that the Authorization header is redacted in both the header map and the body. Reasoning in the finding above.

**The de-tiering itself — cause unknown.** The API Usage table shows 147 requests on 08-05 falling to 84, then 65, then 25 across the following days. The account's rate changed server-side, with no notification, no error, and no log line; the collector's behavior changed underneath code that had not been touched. Whether it was a membership lapse, a policy change, or something applied to the account by hand is unknown, and no artifact in the repo or the dashboard says. Worth one question to Free Law Project, because the answer determines whether the six-month renewal above is the only cliff to watch or just the one with a date on it.

**The `~/.gitignore_global` decision.** `docs/handoffs/` is ignored at the workstation level, which makes it not a psephos decision. Two consequences: it applies to every repo on that machine with such a directory, CBT included; and it's machine-local, so whether those files are tracked depends on which box you're on. The real question is whether that global pattern should exist at all, and if so whether each repo needs an explicit committed decision rather than inheriting a workstation default. Cross-repo, so probably not a psephos unit.

**Michigan.** 6th Cir. `26-1225` (`72347022`) reads terminated with no successor and no district row held. Probably a decided appeal rather than a supersession. Worth one look when the generator gets built, not before.

---

## Standing invariants

Things that have bitten before and will again.

- Every collector must exit 0. The workflow runs them as sequential lines in one `-e` bash step; a non-zero exit stops export and the data commit.
- CourtListener access level, measured 2026-08-09 from the account's own Developer Tools → API Usage panel: **20 requests/minute, 1,000 requests/hour**. The panel renders two stats where the free tier renders three; **no daily figure is shown at this tier.** That is what the panel shows, not proof that no daily throttle exists — do not write "no daily limit" anywhere. The level comes from a free **EDU membership** tied to the university email on the account, and it **expires every six months — it does not auto-renew.** That distinction is the whole point of recording it: this is not a subscription that keeps running until a card declines, it is a term that ends unless somebody acts. The default outcome of forgetting is a lapse back to 5 requests/minute, the tier that produced five consecutive runs at 5-of-34 coverage. The membership landed 2026-08-09, so expiry falls around **2027-02-09** — derived from the landing date, not read off the account. The real date is in the confirmation from `donate.free.law` and in the membership section of the CourtListener account; read either before relying on the derived one. A lapse is silent: no notice, no error, no log line (that is exactly how 08-05 → 08-06 happened). Verifying instrument for every number here is the API Usage panel, **never a log count** — logs only ever see what the throttle let through.
- There is no `X-RateLimit-*` header on a CourtListener response, so a 429's **body** is the only artifact naming which throttle fired; `retry-after` gives a delay with no scope attached. `common._log_429` writes url, headers, and body to stderr on every 429, retried ones included. Quote the scope string verbatim when reporting one.
- Litigation's daily-cap abort fires on `num_requests × spacing < MAX_RETRY_AFTER`, not on any daily budget. That product is the whole classifier: 5/min at ~2.7s spacing aborted at request 6, 10/min at ~2.7s aborted at request 11 on 08-05, and 20/min at ~3.7s does not abort at all. A throttle whose reset outlasts the rest of the run reads as hopeless to the magnitude heuristic regardless of scope. `PAGE_THROTTLE` and the classifier are therefore not independent knobs; changing one changes the other's behavior.
- Free Law Project runs a weekly maintenance window, **Thursdays 21:00–23:59 Pacific.** Pacific is the primary statement because that is how FLP states it and because psephos crons on fixed UTC, so the UTC boundary walks an hour with DST: Fridays **04:00–06:59 UTC** under PDT, Fridays **05:00–07:59 UTC** under PST. The Friday 06:00Z run falls inside the window under both, which is the durable fact and the reason this is recorded. Nothing in psephos accounts for it.
- Database facts come from direct Turso queries, never from JSON snapshots. Snapshots are a lagging derivative and can produce false greens. This applies to the orphan alarm, the supersession invariant, and anything else asserting a row's state.
- Absent cron commits are not failures. An empty-diff run commits nothing by design, so gaps in the 4/day schedule prove nothing without `gh run list`.
- LegiScan needs `getMasterList`, not `getMasterListRaw`. Raw omits `title`/`description`, so election filters silently match zero bills.
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
- **~1.7M rows/day as psephos's rate.** Carried from the CBT thread as a user-provided peak of unstated shape, then used as a sustained rate. The per-database chart shows it is a **single-day spike on ~Jul 21**; the Jul 26 – Aug 1 regime is ~150–250K/day. Everything derived from it inherited the error — the ~190 renders/day ceiling was ~8× too high, and the "falls hard → the strip was the bulk" branch it created was never live. Same failure as the 6,053 floor: a number correctly labeled *provisional* and then used as a magnitude.
- **Handoff 14 as an unstarted unit.** Listed as owing `--apply`, export, and a data commit. All three shipped 07-30 (`bd4d577`) and have survived six collector-driven exports. Only the read-only Turso proof was ever outstanding. A stale owed-list entry is as misleading as a wrong measurement, and costs more, because it invites redoing finished work.
- **The state-bill sort as structurally unfixable.** Handoff 18's Part A asserted, in bold, that `getStateBills`' `COALESCE(last_action_at, updated_at)` could not be reproduced by extending the export, since `build_state_bills` omits `updated_at` for byte-stability. Wrong, and reproducible today: the 81 `(state, last_action_at)` ties break on `state_bill_id`, which the snapshot carries, and the arm that actually needs `updated_at` is `last_action_at IS NULL`, which is 0 of 484. Same failure as the `state.py` rollback claim: read the shape of the clause, saw an omitted column, asserted structural impossibility, never counted the nulls. Died to one COUNT. The guard still belongs beside that sort, because 0 of 484 is a property of today's data and not of the schema.
- **Eight query functions in `web/lib/db.ts`, seven mapping cleanly onto the snapshots.** Thirteen, and six rendered-or-sorted fields absent. The count came from a truncated grep read as though it were the file, in the same message that recommended a build decision off the back of it.
- **psephos as free-tier.** Asserted while flagging in the same sentence that the plan hadn't been checked. It's Pro. Hedging one claim and asserting the adjacent one from the same guess is the same failure wearing a disclaimer.
- **`All Deployments` as a Pro option.** Read off Vercel's docs and written into the unit as fact, in the same commit as the free-tier entry above and about the same plan. Documentation describes the product; the dropdown describes this project. Only the second one is a measurement, and it went unopened.
- **CourtListener as 250 requests/day.** Carried in the standing invariants and used as the denominator for every statement about litigation's coverage. It was never read off this account and has no traceable origin in the repo at all. It was not even the vendor's number: the authenticated free default is 125/day, so the figure was wrong by 2× in the direction that made the budget look comfortable. The measured access level is now recorded in the invariants above, and the daily is recorded as *not shown at this tier* rather than replaced with another unread number. Correcting instrument is the API Usage panel, not a log count.
- **The litigation cap resetting around 08:10Z.** Handoff 10 closed on "the litigation cap resets around 08:10Z; marks should climb on the first run after that," and the number has been repeated since. There is no reset time. DRF throttles are rolling windows with no concept of what day or hour it is — `SimpleRateThrottle` drops each request from its history exactly `duration` seconds after that request was made — so marks climbing after 08:10Z were old requests aging out one at a time, not a period rolling over. Corroborated by the 08-08 probe, whose 429 carried `retry-after: 55` six seconds into a five-request burst: a countdown from the oldest request still in the window, not to any clock boundary. Tier-independent, so this one is corrected outright rather than left pending.
- **"74 of 250, under 30% of the daily budget — independent confirmation the daily cap is not what is firing."** Handoff 20 part B. The conclusion was right and the evidence was worthless, which is the worse failure of the two. The 74 was counted inside the suppressed window: consumption looked low *precisely because* the minute throttle was strangling the run before it could spend. A log count measures what the throttle let through, so it is structurally incapable of showing that a throttle is not binding — the tighter the throttle, the more reassuring the number. Real pre-abort baseline is 102–162 requests/day. Correcting instrument, the same as the two entries above: the API Usage panel, read off the account.
- **Preview-crawl exposure, twice.** First asserted to close in a settings toggle, then corrected to nothing-is-open. Both were reasoning about `psephos.vercel.app`, which is not this project's hostname. The production alias is `psephos-theta.vercel.app` and it was never checked. A hostname picked by pattern-matching the project name is a guess, and `vercel inspect` would have said so at any point.

The claims that survived were the ones someone queried: the `getChannelCounts` scan (provable from the schema), `items = 8,931` (measured against production 2026-08-01), and the handoff-14 data commit (checked with `git log`, not recalled).
