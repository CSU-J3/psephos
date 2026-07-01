# psephos

A monitor for the erosion of voting rights across four channels of federal pressure: legislation, executive action, litigation, and the administrative coercion in between. The full build spec is imported on the next line.

@docs/psephos.md

## Workflow (non-negotiable)

Spec-driven and review-gated. Use /plan to propose a plan and wait for approval before writing anything. Use /diff to show changes before any commit. No commits without a shown diff.

## Conventions

- Conventional commit messages. Git identity and repo under CSU-J3.
- Secrets live in GitHub Actions secrets and a local .env, never in the repo: CONGRESS_API_KEY, COURTLISTENER_TOKEN, and LEGISCAN_API_KEY (all three active), plus TURSO_DATABASE_URL and TURSO_AUTH_TOKEN for the remote database.
- POSIX paths in anything the workflow touches; the cron runs on Linux.
- As-built: all five collectors — legislation, news, litigation, executive (Federal Register), and state (LegiScan) — run every 6 hours via GitHub Actions, persisting to a remote Turso database and committing JSON snapshots. A read-only Next.js view on Vercel renders per-bill and per-case timelines. Remaining depth, not built: a state_bills dimension with state-level vehicle detection (5b) and a dedicated state view.
