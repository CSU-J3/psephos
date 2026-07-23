# psephos

A monitor for the erosion of voting rights across four channels of federal pressure: legislation, executive action, litigation, and the administrative coercion in between. The full build spec is imported on the next line.

@docs/psephos.md

## Workflow (non-negotiable)

Spec-driven and review-gated. Use /plan to propose a plan and wait for approval before writing anything. Use /diff to show changes before any commit. No commits without a shown diff.

## Conventions

- Conventional commit messages. Git identity and repo under CSU-J3.
- Secrets live in GitHub Actions secrets and a local .env, never in the repo: CONGRESS_API_KEY, COURTLISTENER_TOKEN, and LEGISCAN_API_KEY (all three active), plus TURSO_DATABASE_URL and TURSO_AUTH_TOKEN for the remote database.
- POSIX paths in anything the workflow touches; the cron runs on Linux.
- As-built: all five collectors — legislation, news, litigation, executive (Federal Register), and state (LegiScan) — run every 6 hours via GitHub Actions, persisting to a remote Turso database and committing JSON snapshots. State bills are first-class: the `state_bills` dimension (179 bills), `items.state_bill_id`, and the 1,248-item backfill, rendered by the read-only Next.js view on Vercel — `/state-bills` and `/state-bill/[id]` alongside the per-bill and per-case timelines. Litigation polls incrementally on a `date_modified` high-water mark (`cases.entries_synced_at`) against a 250/day CourtListener cap; a daily-cap 429 aborts the run rather than retrying. The only unbuilt piece of 5b is state-level vehicle detection (5b-b).

## Process cleanup
Never kill processes by image name (`taskkill /IM node.exe`) or by matching
on "next dev". Other Next apps run on this Windows box and will be killed
too. Scope to this project's port only:

    netstat -ano | findstr :3001
    taskkill /PID <pid> /T /F

The dev script is pinned to `-p 3001` in web/package.json. Keep it
pinned, and pin any new script that spawns a dev server — CBT holds
3000 on this machine.
