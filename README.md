# psephos

Named for the *psephos*, the pebble an Athenian dropped into an urn to cast a vote.

A monitor for the erosion of voting rights in the United States. It tracks federal legislation, executive action, litigation, and the administrative coercion in between, then links them into per-bill and per-case timelines that surface the procedural maneuvers a plain bill tracker misses. Every change carries its source and an Admiralty grade.

Full build spec: [`docs/psephos.md`](docs/psephos.md).

## Channels

| Channel | Source | Auth |
| --- | --- | --- |
| Legislation | Congress.gov API | free key |
| Executive | Federal Register API | none |
| Litigation | CourtListener / RECAP | free token |
| Coercion + news | RSS feeds + Google News RSS | none |
| State (phase 3) | LegiScan / OpenStates | free tier |

## Layout

```
psephos/
  schema.sql                  SQLite schema
  config/sources.yaml         watchlist, feeds, seed cases, Admiralty grades
  collectors/                 one module per channel (built by phase)
  export/snapshots.py         JSON export for the view and for diffs
  data/                       psephos.db + JSON snapshots (committed by the cron)
  .github/workflows/collect.yml   6-hour cron
  docs/psephos.md    the spec
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # fill in CONGRESS_API_KEY, COURTLISTENER_TOKEN
mkdir -p data && sqlite3 data/psephos.db < schema.sql
python -m collectors.legislation
```

Add the same two keys as GitHub Actions secrets so the cron can run.

## Build order

1. Legislation, news, and litigation collectors (the MVP).
2. Federal Register collector and a read-only timeline view.
3. State legislation, once the API budget is settled.

## Conventions

Spec-driven and review-gated: propose a plan, get approval, show diffs before committing. Repo and Git identity under CSU-J3.
