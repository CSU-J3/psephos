# Finding 16 — channel-count strip: measured baseline

Measured production figures for the `perf(web): cache the channel-count scan`
change (commit `a8103ac`). Tracked here because measurements belong in the repo;
the narrative lives in the untracked `docs/handoffs/16-channel-count-cache.md`.

## The scan, measured

The homepage channel-count strip runs, per uncached render of `/`:

```sql
SELECT channel, COUNT(*) AS n FROM items GROUP BY channel ORDER BY channel
```

`items` is indexed on `channel`, so this is an index scan — one row read per item
to emit 5 integers.

Against production Turso, **2026-07-31**:

| metric | value |
| --- | --- |
| `items` total | **8,931** |
| state | 3,881 |
| news | 2,951 |
| litigation | 1,909 |
| executive | 117 |
| legislation | 73 |
| **rows read per render of the strip** | **8,931** (returns 5 integers) |

Note: 8,931 actual vs the 6,053 committed-snapshot floor. The ~2,900 gap is mostly
the 2,951 **news** items — most never attach to a bill, so they appear in no
snapshot. The snapshot count is a floor, never a magnitude.

## Instrument note — inspect is cumulative, not a rate

`turso db inspect psephos` reports **rows read cumulative for the billing cycle**,
not per day. A single reading is not a daily rate and cannot baseline a daily-rate
delta. A pre-change daily rate = the difference between two readings ≥24h apart,
divided by elapsed time — taken on the same instrument as every post-change reading.

## Inspect readings log (cumulative cycle rows-read)

Fill each row from `turso db inspect psephos`. Two pre-change readings ≥24h apart
give the pre-change daily rate; readings after the push give the post-change rate.

| timestamp (UTC) | cumulative rows read (cycle) | phase | notes |
| --- | --- | --- | --- |
| _(fill)_ | _(fill)_ | pre-change #1 | reading taken now |
| _(fill)_ | _(fill)_ | pre-change #2 | +24h; pre-change daily rate = (#2 − #1) / elapsed |
| _(fill)_ | _(fill)_ | post-push #1 | first reading after deploy |
| _(fill)_ | _(fill)_ | post-push … | daily for a few days |

**Context, not a measurement:** psephos's ~1.7M rows/day peak comes from the
CBT-thread account overview — **user-provided, not measured here**. The Turso block
was org-wide (CBT the burner, ~85–90M/day); psephos's 2026-07-30T20:20:48Z `500` on
`/` was collateral that cleared on its own. This change gets no credit for that.

## What the delta answers

The fix is the measurement. Web and collector reads are confounded inside the daily
rows-read today; rather than a per-source split, watch the daily rate across the push:

- Falls hard → the strip was the bulk of psephos's own reads.
- Barely moves → collectors were, and the ~190 renders/day ceiling (1.7M ÷ 8,931,
  itself resting on the user-provided 1.7M) was mostly them.

## Post-change cap

`getChannelCounts` is wrapped in `unstable_cache` (`revalidate: 3600`), so the scan
runs on cache miss only — **capped at the revalidate window, ≤24/day, independent of
render volume**. Vercel's Data Cache persists across deployments, so the entry
survives the cron's data commit; there is no per-deploy cold-start term (an earlier
"~4/day" figure was inferred and dropped — do not reintroduce without measuring it).
