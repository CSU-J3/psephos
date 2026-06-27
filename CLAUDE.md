# psephos

A monitor for the erosion of voting rights across four channels of federal pressure: legislation, executive action, litigation, and the administrative coercion in between. The full build spec is imported on the next line.

@docs/psephos.md

## Workflow (non-negotiable)

Spec-driven and review-gated. Use /plan to propose a plan and wait for approval before writing anything. Use /diff to show changes before any commit. No commits without a shown diff.

## Conventions

- Conventional commit messages. Git identity and repo under CSU-J3.
- Secrets live in GitHub Actions secrets and a local .env, never in the repo: CONGRESS_API_KEY, COURTLISTENER_TOKEN, later LEGISCAN_API_KEY.
- POSIX paths in anything the workflow touches; the cron runs on Linux.
- Build order: legislation, news, and litigation collectors first (the MVP), then the Federal Register collector and a read-only view, then state legislation.
