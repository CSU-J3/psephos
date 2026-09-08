# The reconciliation alarm read 6 for seventeen days

**What happened.** `tools.coverage_audit` section 1 — *unseeded and unlinked* — is documented in
`docs/status.md` as *"Reads 0 today."* On 2026-09-06 it read **6**, and the oldest of the six had
been firing for **seventeen days**. Nothing was broken. The alarm was correct, it ran on demand,
and no one ran it.

This file records what the six rows were, why two of them are a different problem from the other
four, and the delivery decision that came out of it.

---

## 1. The six rows — one pattern, two shapes

Every firing row was a **terminated district docket whose circuit successor psephos already held**.
There was no coverage gap: nothing needed fetching, only linking.

| Row | State | District docket | Terminated | Successor held | Successor entries | Shape |
|---|---|---|---|---|---|---|
| `71453336` | Minnesota | `0:25-cv-03761` | 08-17 | `united-states-v-minnesota` `26-2679` *Eighth District* | **0, never synced** | **A** |
| `72055344` | DC | `1:25-cv-04403` | 08-06 | `united-states-v-dc` `26-5296` *DC Circuit* | **0, never synced** | **A** |
| `72021508` | Colorado | `1:25-cv-03967` | 08-04 | `74667007` `26-1326` Tenth Circuit | 1, synced | B |
| `72026664` | Nevada | `3:25-cv-00728` | 08-14 | `74694778` `26-5375` Ninth Circuit | 10, synced | B |
| `72054244` | Illinois | `3:25-cv-03398` | 07-31 | `74671260` `26-2695` Seventh Circuit | 13, synced | B |
| `72333329` | New Jersey | `3:26-cv-02025` | 07-29 | `74676722` `26-3085` Third Circuit | 11, synced | B |

**Days unfired**, from UW's rewrite of each artifact row to 2026-09-06:

| Docket | UW rewrote | Days |
|---|---|---|
| `26-1326` CO · `26-2695` IL · `26-5296` DC | 2026-08-20 | **17** |
| `26-3085` NJ | 2026-08-21 | 16 |
| `26-2679` MN | 2026-08-24 | 13 |
| `26-5375` NV | 2026-08-26 | 11 |

---

## 2. Evidence per pair — and a correction to how it was first reported

The first pass over these rows searched **only the district side** and reported the evidence as
*"A1 and one-directional in all six."* That was a property of the search, not of the record.
Searching the successor side as well found the reverse entry on two of the four Shape B pairs:

| Pair | Forward (district names the appeal) | Reverse (appeal names the district) | Strength |
|---|---|---|---|
| CO `72021508` → `74667007` | 08-18 *"USCA Case Number 26-1326 for 105 Notice of Appeal filed by USA"* | — (one bare `Civil case docketed` entry) | A1 forward only |
| NV `72026664` → `74694778` | 08-18 *"NOTICE OF APPEAL as to 94 Judgment"* | 08-20 *"CASE OPENED. A copy of your notice of appeal / petition filed in `3:25-cv-00728-ART-CLB` has been received"* | **A1 both ways** |
| IL `72054244` → `74671260` | 08-19 *"NOTICE of Docketing Record on Appeal from USCA"* | — (entries carry `[26-2695]`, never the district number) | A1 forward only |
| NJ `72333329` → `74676722` | 08-20 *"USCA Case Number 26-3085 for 110 Notice of Appeal (USCA)"* | 08-20 *"CIVIL CASE DOCKETED. Notice filed by Appellant USA in District Court No. `3:26-cv-02025`."* | **A1 both ways** |

**Two bidirectional, two forward-only.** An absence of reverse evidence here says nothing about
the pair — it says the circuit clerk's docketing text differs by circuit, which the backfill
script's step 3 already anticipates by treating the cross-reference as *the strongest signal when
it exists* rather than as a requirement.

**One number was checked rather than waved through.** Nevada's successor docket `26-5375` sits in
the range this record's *D.C. Circuit* rows occupy — `26-5243`, `26-5296`, `26-5301` — which is not
what a Ninth Circuit docket usually looks like. The reverse entry settles it: the appeal itself
names the D. Nev. docket. The circuit map agrees independently (D. Nev. appeals lie to the Ninth
and nowhere else), and that check costs no API call.

---

## 3. Shape A is a different defect, and the collector has been saying so

The two Shape A successors carry **`court_id: null`** in `data/doj_cases.json`; all four Shape B
rows carry a real one (`ca10`, `ca9`, `ca7`, `ca3`).

The cause is a vocabulary mismatch. `collectors/tracker_uw.py` maps court names to verified
CourtListener ids through `COURT_IDS`, whose keys include `"Eighth Circuit": "ca8"` and
`"D.C. Circuit": "cadc"`. UW writes **`'Eighth District'`** and **`'DC Circuit'`**. Neither is a
key, so `COURT_IDS.get(court)` returns `None`, the docket never resolves to a CourtListener id,
the row falls back to a slug key, and it is never polled.

**So `COURT_IDS` is closed over the wrong vocabulary.** It is written against the names courts
actually have; the artifact is written against the names UW types. Those agree most of the time,
which is exactly why the two disagreements went unnoticed.

**And the instrument for this already exists and already fires.** `tracker_uw.py` prints
`WARN unmapped court 'Eighth District' (state 'Minnesota') -> court_id null; add + verify its
CourtListener id in COURT_IDS`, plus a summary `WARN N row(s) with no court_id (will not resolve)`
— on **every cron run**, four times a day, into stderr that nothing reads.

That is the same failure as the headline: **two working alarms, no reader.** The gap this unit
found is not detection. It is delivery.

---

## 4. Section 2 went 7 → 6, and that is the check working

The recorded set of unresolvable docket references was seven: `26-5243`, the three district
originals (`2:25-cv-09149`, `6:25-cv-01666`, `2:26-cv-00066`), and three non-DOJ references.

Today it reads six. **The four that left are all now held** — `26-5243` → `73544809`,
`2:25-cv-09149` → `71452580`, `6:25-cv-01666` → `71363789`, `2:26-cv-00066` → `72110941` — and the
three that arrived (`26-00066` as a self-ref, `26-5301`, `8:25-cv-01370`) are further references
that those newly-held dockets' own entries surfaced.

This is precisely the non-monotonicity the audit's own header warns about: holding a docket
removes its token **and** adds that docket's entries to the corpus. The three non-DOJ references
persist unchanged. 7 → 6 is the report describing a changed world correctly, not drift.

---

## 5. The complement — the alarm's denominator

Twelve rows match no seed. The alarm is the subset carrying no `superseded_by`. The other six were
already linked forward to a **polled** circuit successor and are benign: PA → `73582123` (58
entries), NH → `73607684` (35), MD → `73608654` (41), NM → `73678095` (23), VA → `73690636` (20),
KY → `73674243` (18). Unseeded is not the alarm; unseeded **and** unlinked is.

---

## 6. What Unit B did, and what it read afterwards

Four pairs asserted through `scripts/backfill_supersession.py` (dry-run, `--apply`, idempotence
re-run), 2026-09-06. Readings taken with one script before and after, so nothing below is an
expectation that was confirmed:

| | before | after |
|---|---|---|
| `coverage_audit` §1 | **6** | **2** — exactly the Shape A pair |
| six rows with `superseded_by IS NULL` | 6 of 6 | 2 of 6 |
| `/campaign` `chains` | 12 | **16** (+4) |
| `/campaign` `unlinkedEndings` | 8 | **4** (−4) |
| CO / NV / IL / NJ cells | `chain=None, unlinked=1` | `chain=appeal, unlinked=0` |
| `sued` / `live` / `ended` / `none` | 31 / 29 / 2 / 20 | unchanged |
| `updated_at`, `status_checked_at`, all eight rows | — | **unmoved**, byte-identical |

**The four cells were born correct.** Their successors' court strings are canonical, so
`isCircuit` is true and each renders ↑ *appeal* on its first draw. Had the two Shape A pairs been
asserted first, they would have been born drawing ↻ *"refiled in another district"* for circuit
appeals — which is why canonicalization precedes assertion in the sequence below, and why this
unit stopped at four.

`coverage_audit` still exits **1**: §1 reads 2, not 0. Unit A closes it.

---

## 7. Delivery — a separate daily workflow

**Decided: a separate scheduled workflow with a read-only Turso token**, running the audit daily
and failing loudly.

The whole finding is that detection already works and nobody sees it, so the choice was made on
what happens when the alarm fires, not on what it costs to add.

**Declined — §1 as a step in `collect.yml`.** It has credentials already and runs at the natural
cadence, but it couples a record-keeping alarm to the collection job. A non-zero exit there is the
documented failure mode: `collect.yml` runs its collectors in one `bash -e` step and its Export
and Commit steps carry no `if: always()`, so a failing alarm would cost the cycle its snapshot and
its data commit. Making it `continue-on-error` avoids that and reduces the alarm to a log line —
which is the exact failure this unit is about.

**Declined — a documented manual ritual.** Free, and already half-existed as a session-open read.
This unit is the evidence against it: seventeen days on the audit, longer on the `tracker_uw`
WARN.

---

## 8. Sequence

**B → A → C → section mock.**

- **B (done, 2026-09-06):** the four Shape B pairs asserted. §1 6 → 2.
- **A:** canonicalize the court vocabulary — a `canonicalCourt()` classifying at read plus the
  `COURT_IDS` aliases, with an every-distinct-value-classifies alarm — then resolve the two
  unpolled slug rows, then assert the MN and DC pairs. Order matters inside the unit: canonicalize
  before asserting, or the two cells are born wrong.
- **C:** the delivery workflow from §7.
- **Then** the "Where this stands" section mock v1 on live data, which needs a circuit count it
  can trust.

---

## 9. Corrections made while running this unit

**A correction that reversed a correct estimate. 2026-09-07.** Mine. Gate 4's readings all
wait on the first `collect` run carrying `6470a79`, so "when does the next run land" gates the
unit. The first estimate, extrapolated from observed run start times, was **~02:2x Z**. It was
then "corrected" by reading the cron expression — `17 */6 * * *`, slots at 00:17 / 06:17 /
12:17 / 18:17Z — and reporting the 00:17Z run as **6 minutes past due, inside a normal 8–42
minute queue band**. Both figures in that band are arithmetic errors of the same kind: the
hours were dropped from every subtraction. `20:25:44 − 18:17` was read as 8 minutes and is
**2h08m**; `10:59:25 − 06:17` was read as 42 minutes and is **4h42m**.

The measured lag against the stated anchors, all four 09-06 runs:

| slot | start | lag |
| --- | --- | --- |
| 00:17Z | 04:41:40Z | 4h24m |
| 06:17Z | 10:59:25Z | 4h42m |
| 12:17Z | 15:29:32Z | 3h12m |
| 18:17Z | 20:25:44Z | 2h08m |

~~So the band is **2h08–4h42**, expected landing for the 00:17Z slot is **~02:25–05:00Z**, and
the original ~02:2x estimate was right. The correction was worse than the thing it corrected.~~

**STRUCK 2026-09-08. This is the THIRD correction layer on one claim, and the layering is the
finding.** Layer 1 was the original ~02:2x estimate. Layer 2 was a "minute band" whose arithmetic
had dropped the hours — corrected above, and correctly. Layer 3 is the struck sentence: it fixed
that arithmetic and then generalised **four runs of a single day** into an operating envelope,
which is a different error wearing the first one's clothes.

The fuller table — **n=16 scheduled runs, 2026-09-04 to 09-08**, every run since the cron took its
current form at `58c6aca` — reads **2h05m to 5h04m**. That breaks the band in **both** directions:
2h05m below the floor (09-05 18:17Z), and 5h04m above the ceiling **twice** (09-04 06:17Z at
5h03m, 09-08 06:17Z at 5h04m). A seventeenth run is unassignable and is filed as such rather than
averaged in: **09-07 12:36:16Z** is either the 12:17 slot 19 minutes late or the 06:17 slot 6h19m
late, and nothing in the run record decides which.

So the derived **~02:25–05:00Z** window is withdrawn, and with it the claim that the original
estimate was vindicated — nothing measured here was ever precise enough to vindicate anything.
**The correction was not "worse than the thing it corrected"; both were the same mistake at
different scales**, and the table above (185, 187–194) stays because it is a record of four real
runs, which is exactly what it should always have been called.

**Instruments, two.** A range computed from one day's runs is a sample, not an envelope — pull the
whole `run_started_at` table across days before writing any range. And check the cron expression's
own history first: runs before `58c6aca` were on `0 */6` and belong to different slots entirely,
so a table reaching back past it silently measures two schedules at once.

**Why it is recorded here rather than fixed silently.** The failure is not the subtraction, it
is that finding the cron expression *felt* like finding the ground truth, and the feeling
carried the arithmetic through unchecked. A correction arrives with more confidence than the
estimate it replaces — it is by construction the later, better-informed claim — and that
confidence is what stopped anyone re-reading four two-digit subtractions. This doc already
carries the neighbouring shape in §2, a correction to how a pair was first reported; the
difference is that this one **inverted a true statement into a false one**, which a correction
is uniquely able to do and an original estimate is not.

It also had a live cost, caught before it mattered: the run watcher armed against the wrong
band had a 60-minute window and would have reported `TIMEOUT` at ~01:23Z, an hour before the
earliest possible landing — a false negative that reads exactly like a missed slot, on the same
unit whose entire subject is an alarm nobody ran. Re-armed to 5h30m off the measured band.

**Instrument: subtract against the stated slot anchors, and write the units.** A lag quoted
without its unit is not a measurement. When a correction reverses an earlier estimate, re-derive
the estimate rather than only the correction — a correction is a claim, with the same standing
as what it replaces, and this one had less.

**Second instrument, carried by the `.github/workflows/collect.yml:5-10` annotation this
correction requires (pinned at `6470a79`).** That comment asserts a *mechanism* — "GitHub
queues scheduled workflows … a run can sit minutes to tens of minutes behind its slot" — with
no basis attached, and the queuing half is contradicted by `createdAt == startedAt`, which says
rows are created at dispatch rather than created at the slot and held; so the annotation states
its basis in the sentence — n=3 completed runs, created==started on all three, no live queued
row ever observed for this workflow — which is `docs/status.md`'s dated-absence rule applied to
a mechanism claim rather than an absence claim, and leaves the new text falsifiable by the first
queued row anyone observes instead of rebuilding the same trap one measurement further along.

**An elapsed figure stated without a subtraction. 2026-09-07.** Mine, and the same class as the
one above. Reporting gate 4.5, the pre-apply read was described as showing the trio still empty
"four days and several crons past the re-key." Both halves are wrong, and worse than wrong: **no
subtraction was performed at all.** No anchor was named, so there was nothing to check the figure
against — it was an impression of staleness written in the grammar of a measurement.

The anchor exists and is not hard to reach. The re-key had to be applied immediately before the
alias commit `6470a79` — that is the ordering trap `scripts/rekey_slug_cases.py` documents at
length, the aliases cannot land first — and `6470a79` is committed **2026-09-07T00:00:48Z**. The
trio was read still empty at **2026-09-07T12:39:53Z**, the `updated_at` the collector left on both
rows. So:

| | |
| --- | --- |
| re-key applied (anchor: immediately pre-`6470a79`) | 2026-09-07T00:00:48Z |
| trio read still empty | 2026-09-07T12:39:53Z |
| elapsed | **~12h40m** |
| crons in between | **2** — `e381da9` 05:00Z, `0bee19c` 13:08Z |

**~13h and two crons, not four days and several.** The observation still holds — two crons passed
and neither filled the trio, which is the falsified paragraph's prediction failing in the open —
but it was a third the size claimed, and an overstated interval makes a weaker piece of evidence
look like a stronger one.

**Instrument: an elapsed figure is a subtraction, so name both endpoints and write it down.**
§9's first correction was arithmetic performed wrongly; this one is arithmetic *not performed*,
and it is the more dangerous of the two because there is no wrong operand to catch later — only a
number with no derivation, which reads exactly like one that has been checked. The pattern across
both: this doc's numbers are load-bearing, and the ones that went wrong are the ones that were
never written as `a − b`.

**A third instrument, earned the same session and cheaply.** The 12:39:53Z endpoint above came
from a commit the local clone did not have: `git fetch` first moved origin `e381da9..0bee19c`, and
`0bee19c` is the run that wrote it. The cron pushes data commits this clone has not seen, so a
`git log` taken before a fetch is a reading of a stale world — the same hazard as quoting a count
from `docs/status.md` instead of re-reading it.

---

## 10. Unit A, and a record that only exists because it was written down

Unit A ran on 2026-09-07 in gates: re-key the two slug rows onto their CourtListener ids,
alias the two spellings in `COURT_IDS` (`6470a79`), read the first cron carrying that
alias, fill the docket-derived trio the reuse path can never write, canonicalize the court
vocabulary at the read boundary (`7ac866e`), then assert the two pairs.

**A methodological note that belongs in this file specifically, because this file's
subject is delivery rather than detection.** The readings taken at the alias gate — the
ones confirming the first post-`6470a79` run had resolved and polled both rows — were
taken in a session whose context was later cleared, and they were never written to disk.
They are gone. Not wrong, not disputed: *gone*, because a reading that lives only in a
conversation is not a record. That is the same sentence this document opens with about an
alarm firing into a stderr nobody reads.

So the table below is a **re-read, taken 2026-09-07 after the pair asserts**, and it is
labelled as one rather than presented as the original. Every row is reproducible from the
repo and the database.

| what | reading | source |
| --- | --- | --- |
| rows with a null `court_id` in `data/doj_cases.json` | **0** of 32 | the tracked artifact |
| MN's artifact row | `court 'Eighth District'`, `court_id 'ca8'` | same |
| DC's artifact row | `court 'DC Circuit'`, `court_id 'cadc'` | same |
| the two WARN sites in `tracker_uw.py` | both gated on a null `court_id`; **neither can fire** | source + the artifact above |
| MN `74687843` | 31 `case_entries`, 9 items | `cases` / `case_entries` |
| DC `74671625` | 3 `case_entries`, 4 items | same |
| the trio, both rows | `caption` / `filed_at` / `source_url` all populated | gate 4.5 |
| `status_checked_at`, both rows | stamped `2026-09-07T04:51Z` by `refresh_status` | `cases` |
| never-bootstrapped alarm | **0** | `entries_synced_at IS NULL AND superseded_by IS NULL` |
| rows carrying `superseded_by` | **19** | `cases` |

**The WARN closure is the one to state carefully**, because it is an absence claim and
this project has a rule about those. It is not "the WARN stopped appearing in a log
someone read" — nobody reads that stderr, which is the whole finding. It is that both emit
sites are guarded on a null `court_id`, and the tracked artifact now carries **zero** nulls
across 32 rows. The WARN cannot fire on this artifact. That is checkable offline, today, by
anyone, which is what makes it a record rather than the memory of a green run.

---

## 11. The reuse gate: a prediction that its own success falsified

`scripts/rekey_slug_cases.py` shipped with a paragraph predicting that the next cron's
fresh resolve would replace the carried-over caption from CourtListener's `case_name` —
turning `United States v. Minnesota` into `United States v. Steve Simon` — and fill
`source_url`. That paragraph is **falsified, and corrected in place rather than deleted**,
because the shape of the error is more useful than the fact of it.

**The migration's own success is what removes the thing it predicted.** After the re-key
`str(case_id).isdigit()` is true, so `collect_case` binds on the reuse path, `docket` stays
`None`, and `upsert_case` — which gates `caption`, `filed_at` and `source_url` behind
`if docket is not None:` — never writes them again. The very condition the migration exists
to create is the condition under which the prediction cannot come true. It was not merely
wrong; it was the negation of what the change guarantees.

**Two things hid it, and they hide differently.** The claim described a FUTURE state, so
nothing at apply time could contradict it — the dated-absence shape `docs/status.md`
already names. And it was **half-confirmed by the first cron that ran**: `status`,
`date_terminated` and `status_checked_at` genuinely do get filled, by `refresh_status`,
which probes `/dockets/{id}/` on its own schedule and to which both rows sort as
never-checked. A paragraph that is half right reads as right.

**Both corrections are attributable, and they came from different readers.** The docstring
correction is Code's, written into the file at the point the reuse path was traced. The
endorsement that this was the right call rather than an over-reading came from the review
layer at gate 1 — which is why the paragraph was corrected in place with its wrong
reasoning preserved instead of quietly cut. A deleted wrong prediction teaches nothing,
and this one names a trap that will recur: a claim about the future, half-confirmed by an
unrelated mechanism.

**The probe completed the picture rather than opening it.** `refresh_status` fetches the
exact endpoint carrying all three missing values and reads two of them, dropping the rest
on the floor. So the cheapest theoretical fix was to widen that probe. Considered and
DECLINED, recorded as declined: it would put a backfill's concern inside a pass whose
single job is re-reading one bit, on every row, forever, to serve two rows once.
`scripts/backfill_appeal_metadata.py` pays two requests once instead. If a third such row
ever appears, that is the signal to revisit — not this one.

---

## 12. The duplicate B2 note: mechanism proven, display already settled

The re-key left a visible-looking artifact: DC carries **2** B2 subject notes and MN
carries **4**, where each case should carry one.

**The mechanism was proven rather than inferred**, which matters because the plausible
story and the true one differ. `write_b2_item` keys on
`content_hash(case_id, "b2-subject", notes)`, so a new row is minted when *either*
component moves. Recomputing the hash settles which:

- On both rows the newest note's `notes` text is **byte-identical** to the one before it.
- Recomputing `content_hash` with the **slug** key over that same text reproduces the
  **previous** row's hash exactly.
- Recomputing it with the **numeric** key reproduces the **newest** row's hash exactly.

So the `case_id` move alone minted exactly **one** extra note per row. MN's other three
come from a separate, pre-existing mechanism — the tracker rewriting its Status prose,
notes length 222 to 251 to 249 — and they predate the re-key entirely.

**Nothing is cleaned, and the display question is already answered.** `lib/ledger.ts`'s
`promoteStatus` collapses every B2 litigation item to the single highest `id` and renders
it in the header rather than dated into the docket; its own comment records that on **29 of
52 cases** the note already repeated "up to five times". Screenshots of both case pages
confirm it: one note each, from 2 rows and 4 rows respectively. So this is not a new class.
It is one more instance of a class the read layer was built to absorb, and the duplicates
stay in `items` as the honest record of what was written when.

---

## 13. Closure

**2026-09-07.** Both Shape A pairs asserted through `scripts/backfill_supersession.py`
(dry-run, `--apply`, idempotence re-run), after the canonicalization they were waiting on.

| | 09-06, before Unit B | after Unit B | after Unit A |
| --- | --- | --- | --- |
| `coverage_audit` §1 | **6** | 2 | **0** |
| `coverage_audit` exit | 1 | 1 | **0** |
| `/campaign` chains | 12 | 16 | **18** |
| `/campaign` unlinked endings | 8 | 4 | **0** |
| `cases` rows with `superseded_by` | 12 | 16 | **19** |

§1 reads 0 for the first time since **2026-08-20**, the day the oldest of the six began
firing. §2 reads 6 and §3 reads 1, both expected non-empty and both unmoved by this apply —
correctly, since asserting a supersession links dockets already held and adds no entries to
the corpus.

Five-column byte-diff across all four rows: only `superseded_by` moved, and only on the two
sources. Both `17:00:55` stamps from gate 4.5's trio write and both `04:51` stamps from
`refresh_status` are byte-identical before and after.

**Both cells were born correct.** MN and DC each render the appeal glyph with the title
`continued as a circuit appeal` on their first draw, because canonicalization landed first.
Had the order been reversed, MN would have drawn *refiled in another district* for a
circuit appeal — the section 6 hazard, avoided by sequencing rather than by luck.

### The DC evidence was re-graded downward, by a reader other than its author

The pair was first written up as carrying three signals: the district's USCA entry, the
successor's `appeal_from_str`, and the appeal's own entry naming `1:25-cv-04403`. **The
review layer caught that the first of those is empty** — not by doubting the sentence but
by pattern-matching across the dockets already in this file. On MN, CO, IL and NJ the
district's `USCA Case Number` entry *carries the circuit docket number in its text*, and
that is what makes it a forward signal at all. On DC it does not: read directly,
`72055344`'s 2026-08-19 entry description is **16 characters long and reads exactly
`USCA Case Number`**, with no number after it.

So DC's forward direction establishes that an appeal was taken, not which docket it became,
and the pair rests on its reverse entry — which names both dockets in one line — plus
`appeal_from_str` plus the circuit map. That is still stronger than CO or IL, which carry no
reverse entry at all. But three signals were claimed and two are load-bearing, and the
`PAIRS` comment now says so.

**Instrument: a signal named by its type is not yet a signal read by its content.** "The
district's USCA entry" is a category; `USCA Case Number 26-2679 for 212 Notice of Appeal` is
evidence and `USCA Case Number` is not. The check that caught it was comparing the same
field across pairs already in the record — no API call, no cost, the same shape as the
circuit-map check this file already recommends.

---

## 14. What is next

**Unit C, the delivery workflow** (section 7), is the open one, and it is the point of the
whole finding: detection worked throughout and nobody was reading it. A daily scheduled
workflow with a read-only Turso token, failing loudly, plus two new `coverage_audit`
sections — a vocabulary alarm (every distinct court string in the artifact must classify, so
a THIRD spelling fails loudly rather than falling through to a null `court_id` and silence)
and a bootstrap-coverage section carrying the `entries_synced_at IS NULL AND superseded_by
IS NULL` query this document already treats as a standing check.

The aliases shipped in `6470a79` are a **bridge, not a fix for the class**: an alias only
exists once someone has noticed the miss, and noticing is exactly what failed here.
