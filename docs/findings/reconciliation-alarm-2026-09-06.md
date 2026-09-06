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
