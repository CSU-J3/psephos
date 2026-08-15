# psephos

A monitor for the erosion of voting rights across four channels of federal pressure: legislation, executive action, litigation, and the administrative coercion in between. The full build spec is imported on the next line.

@docs/psephos.md

## Workflow (non-negotiable)

Spec-driven and review-gated. Use /plan to propose a plan and wait for approval before writing anything. Use /diff to show changes before any commit. No commits without a shown diff.

## Conventions

- Conventional commit messages. Git identity and repo under CSU-J3.
- Secrets live in GitHub Actions secrets and a local .env, never in the repo: CONGRESS_API_KEY, COURTLISTENER_TOKEN, and LEGISCAN_API_KEY (all three active), plus TURSO_DATABASE_URL and TURSO_AUTH_TOKEN for the remote database.
- POSIX paths in anything the workflow touches; the cron runs on Linux.
- State collector gate order (`collectors/state.py`): `election_match` runs BEFORE the change-hash gate, so `state_seen` only ever holds filter-passers. A term broadening therefore SELF-STAMPS on the next cron — the newly-matched bills have no stored hash, so they pass the gate and get a getBill — and needs no getBill backfill. (The 5b-a 1,248-item backfill was a different job: linking pre-existing items to the new dimension, not stamping new bills.)
- `tools/` vs `scripts/`: read-only offline analysis lives in `tools/` (`masterlist_corpus`, `sasts_dump`, `sasts_join`, `lit_resolve_audit`, `status_audit`, `coverage_audit`); anything that mutates a database lives in `scripts/` (`backfill_state_bills`, `backfill_supersession`, `backfill_case_state`, `repair_latest_entry`) and is dry-run-by-default with an `--apply` gate. The last two are one-time and already applied — do not schedule them; `backfill_case_state` is superseded by `upsert_case` writing `state` every run, and `repair_latest_entry` by `write_entries` recomputing its column. `python -m tools.coverage_audit` is the standing coverage check: its **exit code is sections 1 and 4** — the reconciliation alarm (a row matching no seed and carrying no `superseded_by`) and the derived-column alarm (`cases.latest_entry_at` disagreeing with `MAX(case_entries.entry_at)`), both expect 0 — while sections 2 and 3 are reports that are expected non-empty: 7 unresolvable docket references and 1 terminated circuit row awaiting a cert petition. Do not read those two counts as failures.
- As-built: all five collectors — legislation, news, litigation, executive (Federal Register), and state (LegiScan) — run every 6 hours via GitHub Actions, persisting to a remote Turso database and committing JSON snapshots. State bills are first-class: the `state_bills` dimension (**484 bills**), `items.state_bill_id`, and **3,882 linked items** across it, rendered by the read-only Next.js view on Vercel — `/state-bills` and `/state-bill/[id]` alongside the per-bill and per-case timelines. Litigation polls incrementally on a `date_modified` high-water mark (`cases.entries_synced_at`) against a measured CourtListener EDU tier of **20/min and 1,000/hour**, with no daily figure shown at that tier. A 429 is classified on the **scope named in its body**, not on the size of its reset: sub-daily scopes retry, `day` and longer raises `RateBudgetExhausted` and aborts the collector, and an unparseable scope falls back to a reset-magnitude rule. State-level vehicle detection (5b-b) is closed as a stated free-tier limitation — LegiScan's `sasts` relations express companionship, not the substitution a vehicle would take; see `docs/findings/5b-b-vehicle-discovery.md`. 5b is complete.
- **Every count above moves, and the two state-bill figures were read from Turso on 2026-08-15 in the session that wrote them.** Re-read before quoting them; they were stale by 29 bills and 273 items when last corrected. **Corrections belong in `docs/status.md`, not here** — its falsified list is where a number's history lives, including the `250/day` CourtListener cap this line used to cite and which was never read off the account. A file a cold reader opens first should say what is true now, not what a figure used to be.

## Process cleanup
Never kill processes by image name (`taskkill /IM node.exe`) or by matching
on "next dev". Other Next apps run on this Windows box and will be killed
too. Scope to this project's port only:

    netstat -ano | findstr :3001
    taskkill /PID <pid> /T /F

The dev script is pinned to `-p 3001` in web/package.json. Keep it
pinned, and pin any new script that spawns a dev server — CBT holds
3000 on this machine.
