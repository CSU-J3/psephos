# Finding 16 — channel-count strip: measured baseline

Measured production figures for the `perf(web): cache the channel-count scan out of
the per-render path` change. Referenced by subject rather than hash: the hash churns
on every rebase, and the `a8103ac` first recorded here is already unreachable.
Tracked here because measurements belong in the repo; the narrative lives in the
untracked `docs/handoffs/16-channel-count-cache.md`.

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

This figure grows with the cron. It is the per-scan cost on 2026-07-31, not a
constant.

## Instrument — the dashboard's daily rows-read chart

app.turso.tech → Databases → psephos → Analytics → Rows Read, Last 30 days. It charts
**rows read per day, for this database**, which is exactly the quantity the change is
meant to move. Re-read the same chart after the push.

This supersedes an earlier two-reading `turso db inspect psephos` protocol. That
protocol existed only because `inspect` reports rows read **cumulative for the billing
cycle**: deriving a daily rate from it needed two readings ≥24h apart and a division,
and a cycle rollover between them would have silently corrupted the subtraction. The
dashboard reports the rate directly and per-database. No reading was ever taken under
the old protocol, so nothing is lost in dropping it.

## Readings log (daily rows read, this database)

| read at (UTC) | window shown | daily rows read | phase | notes |
| --- | --- | --- | --- | --- |
| 2026-08-01 ~21:45Z | Jul 26 – Aug 1 | **~150–250K/day** | pre-change baseline | current regime, post the mid-July anomaly |
| _(fill)_ | | _(fill)_ | post-push | ~a week after the push; same chart, same window length |

### Shape of the 30-day window

- ~200–400K/day in early July.
- Climbing through mid-month.
- A **single-day spike to ~1.7M on ~Jul 21**.
- Back to the ~150–250K/day baseline from Jul 26 onward.

**The 1.7M figure, corrected.** This document previously carried ~1.7M rows/day as a
user-provided peak from the CBT thread, of unstated shape. It is now measured on this
chart and it is **a single-day spike on ~Jul 21, not a sustained rate**. Any inference
that treated 1.7M as psephos's daily volume was reasoning from an outlier — see the
render-ceiling correction below.

### Org and cycle context

- Cycle **reset Aug 1**, so this baseline sits at the start of a fresh cycle.
- Read ceiling **2.50B rows/cycle** — not the 500M assumed earlier.
- The org is already at **15.6M on day one**. That pace is CBT-shaped and belongs to
  the CBT thread, not to this finding.
- Write ceiling 25M/cycle against psephos's 5–25K/day. Non-issue; not tracked further.

The 2026-07-30T20:20:48Z `500` on `/` was collateral from an org-wide block (CBT the
burner, ~85–90M/day). This change gets no credit for clearing it.

## What the delta answers — and how small it will be

Web and collector reads are confounded inside the daily rows-read figure. Rather than
attempt a per-source split, watch the daily rate across the push.

At ~200K rows/day and 8,931 rows per scan, the strip can account for **at most ~22
renders/day** (~17–28 across the 150–250K band). That is a ceiling, not an estimate:
it assumes every read in the database is the strip, when the five collectors read on
every 6-hour cron. Actual homepage renders are at or below it.

**So the honest prediction is a small delta, recorded now rather than explained away
later.** The post-change cap is ≤24 scans/day. Current behaviour already sits at or
under that ceiling, so the cache may remove close to nothing measurable, and whatever
it does remove can hide inside the day-to-day noise of a 150–250K band. If the
post-push reading looks unchanged, that is the predicted result, not a failed change.

This does not make the change wrong. It converts a cost that was unbounded in render
volume into a bounded one: that the strip runs ~22 times a day today is a fact about
current traffic, not about the code. After the change it is a fact about the code.
The delta measures present traffic; the cap governs future traffic.

The earlier framing here — "falls hard → the strip was the bulk of psephos's own
reads" — rested on a ~190 renders/day ceiling derived from the 1.7M spike. With 1.7M
corrected to an outlier, that ceiling was roughly 8× too high and the "falls hard"
branch was never live.

## Post-change cap

`getChannelCounts` is wrapped in `unstable_cache` (`revalidate: 3600`), so the scan
runs on cache miss only — **capped at the revalidate window, ≤24/day, independent of
render volume**. Vercel's Data Cache persists across deployments, so the entry
survives the cron's data commit; there is no per-deploy cold-start term (an earlier
"~4/day" figure was inferred and dropped — do not reintroduce without measuring it).

State the cap's limit plainly: ≤24 scans/day at 8,931 rows is **≤~214K rows/day**,
which is the whole of current daily volume. The cap bounds *render volume*, not scan
cost, and scan cost tracks the size of `items`, which the cron grows every 6 hours.
The cap is protection against traffic growth. It is not protection against corpus
growth, and if `items` becomes the problem the answer is a maintained count, not a
longer revalidate window.
