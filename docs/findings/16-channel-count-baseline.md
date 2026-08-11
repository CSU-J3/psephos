# Finding 16 — channel-count strip: measured baseline, and a null result

Measured production figures for the `perf(web): cache the channel-count scan out of
the per-render path` change. Referenced by subject rather than hash: the hash churns
on every rebase, and the `a8103ac` first recorded here is already unreachable.
Tracked here because measurements belong in the repo; the narrative lives in the
untracked `docs/handoffs/16-channel-count-cache.md`.

**Outcome, stated first: the delta is a null result, and it is the one this document
predicted in advance.** Rows read fell 13.3% across the push. Rows written fell 14.9%
across the same window, and no cache can affect writes. Collector activity declined
and reads tracked it proportionally, leaving no residual for the change. The cap the
change establishes — ≤24 scans/day independent of render volume — stands on its own
terms and is untouched by this.

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

**Hover it. Do not read the shape.** Every point value in this document came from the
tooltip, one day at a time. The first baseline entry below was taken by eye off a
chart segment and was wrong by enough to invert a conclusion; the tooltip was
available on the same screen at the same time.

The **Rows Written** panel sits on the same page and appears in the same screenshots.
It is the control: writes are collector-side by construction and no read cache can
move them. Read both panels in one pass, always. Reading it is what turned this
finding's read delta from a signal into noise, and it cost nothing extra to take.

This supersedes an earlier two-reading `turso db inspect psephos` protocol. That
protocol existed only because `inspect` reports rows read **cumulative for the billing
cycle**: deriving a daily rate from it needed two readings ≥24h apart and a division,
and a cycle rollover between them would have silently corrupted the subtraction. The
dashboard reports the rate directly and per-database. No reading was ever taken under
the old protocol, so nothing is lost in dropping it.

## Readings log (daily rows read, this database)

| read at (UTC) | window shown | daily rows read | phase | notes |
| --- | --- | --- | --- | --- |
| 2026-08-01 ~21:45Z | Jul 26 – Aug 1 | ~150–250K/day | pre-change baseline | **falsified — eyeballed off the chart segment, never hovered. Do not cite.** |
| 2026-08-11 | Jul 26 – Aug 1 | **mean 129,573/day** | pre-change baseline | point values, tooltip per day; sum 907,014 |
| 2026-08-10 | Aug 2 – Aug 8 | **mean 112,331/day** | post-push | point values, tooltip per day; sum 786,319 |

Both windows are seven days, same chart, same instrument. The push landed 08-01, so
Aug 2 – 8 is the first clean post-change week.

### Point values, both windows

| day | rows read | rows written |
| --- | --- | --- |
| Jul 26 | 108,033 | 3,382 |
| Jul 27 | 70,208 | 3,078 |
| Jul 28 | 121,429 | 5,662 |
| Jul 29 | 97,480 | 3,288 |
| Jul 30 | 206,925 | 6,567 |
| Jul 31 | 185,150 | 3,364 |
| Aug 1 | 117,789 | 3,525 |
| **baseline mean** | **129,573** | **4,124** |
| Aug 2 | 116,885 | 3,043 |
| Aug 3 | 100,763 | 4,071 |
| Aug 4 | 99,839 | 3,809 |
| Aug 5 | 180,233 | 5,217 |
| Aug 6 | 114,917 | 3,093 |
| Aug 7 | 69,615 | 2,630 |
| Aug 8 | 104,067 | 2,707 |
| **post mean** | **112,331** | **3,510** |

Baseline sum 907,014 reads / 28,866 writes. Post sum 786,319 reads / 24,570 writes.

### Shape of the 30-day window

- ~200–400K/day in early July.
- Climbing through mid-month.
- A **single-day spike to ~1.7M on ~Jul 21**.
- From Jul 26 onward, a regime spanning **70K–207K/day**, mean 129,573.

**The 1.7M figure, corrected.** This document previously carried ~1.7M rows/day as a
user-provided peak from the CBT thread, of unstated shape. It is measured on this
chart and it is **a single-day spike on ~Jul 21, not a sustained rate**. Any inference
that treated 1.7M as psephos's daily volume was reasoning from an outlier.

### Org and cycle context

- Cycle **reset Aug 1**, so the post-push window sits at the start of a fresh cycle
  and the baseline window sits at the end of the previous one. The instrument is a
  per-day rate, so the boundary does not enter the comparison.
- Read ceiling **2.50B rows/cycle** — not the 500M assumed earlier.
- The org was already at **15.6M on day one**. That pace is CBT-shaped and belongs to
  the CBT thread, not to this finding.
- Write ceiling 25M/cycle against psephos's 2.6–6.6K/day. Non-issue as a quota
  question; the write series earns its place here as the control, not as a cost.

The 2026-07-30T20:20:48Z `500` on `/` was collateral from an org-wide block (CBT the
burner, ~85–90M/day). This change gets no credit for clearing it.

## Result — the predicted null

**Reads.** 129,573 → 112,331, a fall of **17,242/day, 13.3%**. At 8,931 rows that is
about **1.9 scans/day** of apparent saving.

**Dispersion.** Sample SDs 48,812 (baseline) and 33,717 (post). SE on the difference
of means is sqrt(48,812²/7 + 33,717²/7) = **22,423**. The observed delta is **0.77 SE**.
Not distinguishable from zero — but read that as indicative, not as a formal test:
seven consecutive calendar days are not independent samples, since the cron runs on a
fixed schedule and weekday patterns repeat, so the independence the SE assumes does
not hold. **The conclusion rests on the write ratio below, not on the SE.**

**The control kills what is left of it.** Writes fell 4,124 → 3,510, **14.9%**, across
the same seven-day pair. A read cache cannot affect writes, so that fall is collector
activity declining, not the change. Scale the baseline reads by the write ratio —
assuming reads move linearly with collector activity, which is an assumption and not a
measurement — and the expected post-push read mean is 129,573 × (3,510 / 4,124) ≈
**110,300**. Observed is 112,331: about **2,000 rows/day above** the activity-only
prediction, the wrong sign for a saving. There is no residual to attribute to the
cache, and the read fall is slightly *smaller* than the activity fall rather than
larger.

**This is the outcome the document predicted before the push, and it is recorded as a
success of the prediction rather than a failure of the change.** The prediction below
was written when the baseline was believed to be a 150–250K band; correcting the band
to a 129,573 mean makes the prediction stronger, not weaker.

## What the delta could ever have answered

Web and collector reads are confounded inside the daily rows-read figure. Rather than
attempt a per-source split, the plan was to watch the daily rate across the push.

At the measured baseline mean of 129,573 rows/day and 8,931 rows per scan, the strip
can account for **at most ~14.5 renders/day** (7.9 on Jul 27, 23.2 on Jul 30). That is
a ceiling, not an estimate: it assumes every read in the database is the strip, when
the five collectors read on every 6-hour cron. Actual homepage renders are far below
it.

That ceiling sits **under the ≤24/day cap the cache imposes**, on six of the seven
baseline days and on the mean. So the cache had nothing to bind on: current traffic
was already inside the bound before the change shipped. There was no measurable
saving available for the instrument to find, and the confounded instrument could not
have isolated one that size regardless.

**So the honest prediction was a small delta, recorded before the reading rather than
explained away after it.** It came back at 0.77 SE with a write series that accounts
for all of it. That is the predicted result, not a failed change.

This does not make the change wrong. It converts a cost that was unbounded in render
volume into a bounded one: that the strip ran ~15 times a day on this window is a fact
about current traffic, not about the code. After the change it is a fact about the
code. The delta measured present traffic; the cap governs future traffic, and the cap
is what the change bought.

The earlier framing here — "falls hard → the strip was the bulk of psephos's own
reads" — rested on a ~190 renders/day ceiling derived from the 1.7M spike. With 1.7M
corrected to an outlier the ceiling was roughly 8× too high, the "falls hard" branch
was never live, and the measured delta has now confirmed it from the other end.

## Post-change cap

`getChannelCounts` is wrapped in `unstable_cache` (`revalidate: 3600`), so the scan
runs on cache miss only — **capped at the revalidate window, ≤24/day, independent of
render volume**. Vercel's Data Cache persists across deployments, so the entry
survives the cron's data commit; there is no per-deploy cold-start term (an earlier
"~4/day" figure was inferred and dropped — do not reintroduce without measuring it).

**The null result does not touch this.** The cap is a property of the code, provable
from `revalidate: 3600` without any dashboard reading. The delta was only ever a
measurement of today's traffic against it.

State the cap's limit plainly: ≤24 scans/day at 8,931 rows is **≤~214K rows/day**,
which is above the whole of current daily volume. The cap bounds *render volume*, not
scan cost, and scan cost tracks the size of `items`, which the cron grows every 6
hours. The cap is protection against traffic growth. It is not protection against
corpus growth, and if `items` becomes the problem the answer is a maintained count,
not a longer revalidate window.

## What the reading cost, in errors

Three claims died to this pair of readings, all of them made in review, none of them a
defect in the repo. They are entered in the falsified list in `docs/status.md`:
the 150–250K band, the "~88K/day drop the cache cannot explain" derived from it, and
the reading of Aug 7's minimum as contamination. The common shape is comparing an
estimate to a measurement and treating the gap as signal.

The contamination is real and documented — the 08-05→08-08 CourtListener de-tiering
and the litigation starvation both fall inside the post-push window — but it does not
surface above the noise in this instrument. Jul 27 read 70,208 with no 502s and no
starvation, against Aug 7's 69,615. A ~70K day is ordinary here.
