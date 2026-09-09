# No channel age alarm — and `fetched_at` is a write receipt, not a poll receipt

**What this is.** A costing of a `coverage_audit` §7 that would alarm on a channel going stale, and
the measurement that refuses it. The unit builds nothing. Its deliverable is the number that says
not to build, kept because a refusal with no measurement behind it is indistinguishable from
inattention six weeks later.

**Where it came from.** Read 2 of the 2026-09-09 session proved `data/generated_at.json` equals
`MAX(fetched_at)` across channels, and noticed on the way that the aggregate is an **any-channel**
high-water mark carried entirely by `news`. Legislation's last item was 2026-06-28; executive's was
09-02. Both are quiet rather than broken, so a per-channel age alarm would be **born red on correct
data** — which is precisely the §5 scoping error unit C caught before it shipped, one level out.
That is the question this file answers, and the answer is no on three separate grounds.

All figures read live from Turso at **`NOW = 2026-09-09T17:48:07Z`**, 10,849 rows.

---

## 0. The premise was checked, not inherited

The whole exercise rests on *legislation and executive are quiet, not broken*. That was asserted
before it was verified, so it was verified first.

The 2026-09-09 16:40Z collect run reached all six watchlist bills and Congress.gov returned nothing
for each:

```
  hr22-119     +0 actions  +0 relations  +0 items
  s128-119     +0 actions  +0 relations  +0 items
  hr7296-119   +0 actions  +0 relations  +0 items
  s3752-119    +0 actions  +0 relations  +0 items
  hr7300-119   +0 actions  +0 relations  +0 items
  s1383-119    +0 actions  +0 relations  +0 items
```

**Legislation is running and genuinely quiet.** Its 73 items are a single bootstrap batch inside a
**28-second window** on 2026-06-28 — 11 distinct timestamps, every gap under 7 seconds — and the
channel has not written an item since its first run, 72.94 days ago.

Keep this section in view while reading §4. It is the evidence for the finding, not preamble to it.

---

## 1. Per channel: `MAX(fetched_at)` and the gap distribution

Gaps are between consecutive **distinct** `fetched_at` values. That is the correct object for this
question: the largest gap in a channel's history is the largest age that channel ever reached, which
is exactly what a threshold has to clear.

| channel | items | distinct | `MAX(fetched_at)` | age at NOW | p50 | p90 | p99 | max closed gap | gaps > 6h |
|---|---|---|---|---|---|---|---|---|---|
| news | 4,461 | 4,397 | 09-09 16:45 | **1.05h** | 1.7s | 32.5s | 7.20h | **23.10h** | 127 / 4,396 |
| state | 3,884 | 3,884 | 09-08 21:21 | **20.45h** | 0.1s | 0.8s | 1.7s | **34.54d** | 6 / 3,883 |
| litigation | 2,302 | 2,190 | 09-08 21:19 | **20.48h** | 0.4s | 1.1m | 23.99h | **2.77d** | 95 / 2,189 |
| executive | 129 | 129 | 09-02 10:07 | **7.32d** | 0.1s | 0.9s | 13.96d | **18.75d** | 10 / 128 |
| legislation | 73 | 11 | 06-28 19:11 | **72.94d** | 0.0s | 6.0s | 6.7s | **6.7s** | 0 / 10 |

**Everything below p99 is within-batch spacing and says nothing about staleness.** A collector writes
its rows milliseconds apart, so the median gap measures insert speed. The tail is the entire signal,
which is why it is dated below rather than summarised.

---

## 2. The tails, dated

**executive** — all 11 intervals over 4h, of 128:

| gap | from | to |
|---|---|---|
| 4.33h | 2026-08-20 02:07 | 08-20 06:27 |
| 17.59h | 2026-06-30 01:51 | 06-30 19:26 |
| 23.30h | 2026-07-17 09:00 | 07-18 08:18 |
| 1.02d | 2026-07-02 09:35 | 07-03 10:02 |
| 1.59d | 2026-06-30 19:26 | 07-02 09:35 |
| 3.99d | 2026-07-28 08:16 | 08-01 08:02 |
| 5.00d | 2026-08-20 06:27 | 08-25 06:28 |
| 8.15d | 2026-08-25 06:28 | 09-02 10:07 |
| 10.00d | 2026-07-18 08:18 | 07-28 08:16 |
| 13.96d | 2026-07-03 10:02 | 07-17 09:00 |
| **18.75d** | 2026-08-01 08:02 | 08-20 02:07 |

This channel routinely goes 8–19 days between documents. That is the Federal Register having nothing
on-topic, not a fault.

**state** — only 6 intervals over 4h, of 3,883:

| gap | from | to |
|---|---|---|
| 11.02h | 2026-07-30 08:11 | 07-30 19:12 |
| 2.28d | 2026-07-28 01:27 | 07-30 08:11 |
| 4.72d | 2026-07-23 08:15 | 07-28 01:27 |
| 5.54d | 2026-07-30 19:13 | 08-05 08:16 |
| 21.51d | 2026-07-01 20:00 | 07-23 08:09 |
| **34.54d** | 2026-08-05 08:16 | 09-08 21:21 |

**news** — 258 over 4h, tightly bunched and with a hard ceiling. Top six: 14.68h, 14.68h, 15.86h,
16.69h, 22.39h, **23.10h** (08-06 13:38 → 08-07 12:44). Nothing above a day, ever.

**litigation** — 116 over 4h. Top six: 1.68d, 1.81d, 2.00d, 2.03d, 2.53d, **2.77d**
(08-07 12:43 → 08-10 07:06). Nothing above three days, ever.

---

## 3. Three refusals, and they are three different failures

The binding quantity is `max(largest closed gap, current open interval)` — the open interval counts,
because the alarm evaluates `now − MAX(fetched_at)` today and has to survive that evaluation.

| channel | min threshold that stays green | set by | headroom over 2nd-largest |
|---|---|---|---|
| news | **23.10h** | closed gap | 23.10h vs 22.39h — **1.03×** |
| litigation | **2.77d** | closed gap | 2.77d vs 2.53d — **1.09×** |
| executive | **18.75d** | closed gap | 18.75d vs 13.96d — **1.34×** |
| state | **34.54d** | closed gap | 34.54d vs 21.51d — **1.61×** |
| legislation | **72.94d and rising** | **the open interval** | no closed gap exists — n/a |

These must stay separate in the record. Collapsed into "the numbers don't work" they become one soft
objection that a later reader can argue past; kept apart, each names a different thing that would
have to change first.

**3.1 — legislation: STRUCTURAL.** Its threshold is set by an interval that has not ended, so it is
not a measurement at all — it is a lower bound that grows by one day per day. Below 72.94d the alarm
is **red today, on data §0 confirms is correct**. Above it, the threshold is defined by today's date
and is green only until tomorrow. There is no distribution to fit because the channel has produced
exactly one batch in its life. No parameter choice fixes this; the shape of the data forbids the
instrument.

**3.2 — executive and state: LATENCY.** Thresholds do exist here, and that is the trap. 18.75d and
34.54d are **2.6× and 40× the current age**. An alarm that speaks after nineteen or thirty-five days
of silence is slower than a person opening the page, so it would deliver its first true positive well
after the outage had been noticed by every other route. A detector whose latency exceeds the outage it
detects is not a detector.

**3.3 — news and litigation: NO MARGIN.** These are the only two whose thresholds land near the
operating range, and they land *on* it: **1.03×** and **1.09×** headroom over the second-largest gap.
The threshold sits directly on top of the observed distribution with nothing to spare, so the first
quiet weekend is a red run on healthy data — the §5 born-red failure again, arrived at from the
opposite direction to §3.1. There is no gap-in-the-gaps for a threshold to sit in.

---

## 4. The finding: `fetched_at` is a WRITE receipt, not a POLL receipt

It records **that a row was created**. It never records that a collector ran, reached its sources, and
got nothing back. So these two states are the same row-absence:

- the collector ran four times a day and upstream had nothing to report;
- the collector stopped running, or ran and failed, and wrote nothing.

**No column in this schema separates them.** That is the real gap the §7 question was circling, and it
is why every threshold above is being asked to do a job the data cannot support: an age alarm built on
`fetched_at` is not measuring collector health, it is measuring upstream event rate, and it fires on
whichever of the two happens to be low.

**The proof that this is the actual gap is §0 of this document.** Establishing that legislation was
healthy required a **poll receipt** — the 16:40Z run reaching all six bills and returning `+0/+0/+0` —
and that receipt had to be produced **by hand, out of a GitHub Actions log**, because no column holds
it. The measurement that refuted the alarm is the same measurement that names what would replace it.

**Same family as the `entries_synced_at` correction**, and the shared failure is worth more than either
instance. That column is the upstream CourtListener `date_modified` high-water mark, deliberately held
on an empty window — and it was read as a *last-checked* date twice: once in an alarm (falsified list,
handoff 37 §2) and again in a **display** two weeks later (falsified list, handoff 52 §3), which
specified a dormancy cell reading *"last checked 08-12"* off it. The correct receipt there was
`status_checked_at`, written by `refresh_status` on every pass **including no-ops** — and *including
no-ops* is the entire difference. The meaning had been written down in the schema comment and in
handoff 25 §3 the whole time.

**The general shape: a mark that upstream moved is not a record of having looked.** `entries_synced_at`
is that mistake for one docket; `fetched_at` is the same mistake for a whole channel. A receipt is only
a receipt if it is written on the empty case.

**And the LegiScan window is this generalised to five channels.** State's 34.54d gap (08-05 → 09-08)
**contains the 2026-08-15 incident**, where all nine states failed at `getMasterList`. This measurement
cannot say whether that interval was quiet, broken, or both — see §5.

---

## 5. Contamination, and its direction

The largest number in each channel's distribution is both the one most likely to contain an outage and
the one that sets the threshold. A threshold fitted to this record is therefore fitted partly to
breakage.

**The direction matters and is the safer of the two.** If a channel's largest gap was an outage rather
than a silence, that gap is **not evidence about the healthy quiet ceiling**, and fitting to it makes
the threshold **too loose**. The failure mode of a contaminated fit is a **LATE alarm, not a false
red**.

Stated because a caveat without its direction reads as fatal when it is merely limiting. Here it is
limiting, and it points the safe way.

**It rescues nothing.** Late is exactly what refusal 3.2 already fails on, so the correction improves
the reasoning without moving the conclusion — which is the only reason to record it.

---

## 6. What is NOT in this unit

**The run receipt is named and deliberately not built.** A per-collector poll record — a row written
every run, per channel, whether or not anything was collected — is the instrument that would answer
§4's question. It is a **schema change** with its own cost and its own failure modes.

**THE PLACEMENT RULE, stated positively, because the objection on its own sends the next reader to the
wrong site.** A receipt proving only that a process *started* is worth less than nothing: a collector
that starts, throws, and is caught by its own per-item handler would still write one, and the column
would then certify health on precisely the runs that failed. The rule that avoids this:

> A poll receipt is written at the point where *asked upstream and got nothing back* is **KNOWN** —
> after a successful response carrying an empty result set. **Not at process start. Not in a
> `finally`. Not on exception.**

**§0 of this document is the worked example, and it already has the property.** `+0 actions +0
relations +0 items`, six times over, is a **response** and not a start: each of those lines exists
because Congress.gov answered and the answer was empty. A collector that died before its first request
prints no such line, and a collector that died after three prints three — which is the discrimination
§4 says no column makes. That is the shape the receipt would have to record, and it is why §0 could
settle a health question `fetched_at` cannot. It exists today only as a line in a log nobody queries.

Whether that is worth a column is not settled here and is not settled by this measurement. Folding it
into a findings commit is how it would escape review, so it stops at being named.

**No "for now" threshold is set on any channel**, including the two where a number exists. A parameter
left in place because refusing felt like doing nothing is the thing this measurement exists to prevent.

---

## 7. Reproducing this

Every figure is one scan of `items`:

```sql
SELECT channel, fetched_at FROM items ORDER BY channel, fetched_at;
```

Take the **distinct** `fetched_at` values per channel, diff consecutive ones, and read the tail — not
the percentiles, which measure insert speed. Compare the largest against `now − MAX(fetched_at)` and
take the greater; that is the minimum threshold that would have stayed green.

**The counts move.** They were read 2026-09-09T17:48:07Z and are as-of, not invariants. The three
refusals are about the *shapes* of the distributions and are more durable than the numbers — but
re-read before quoting either.
