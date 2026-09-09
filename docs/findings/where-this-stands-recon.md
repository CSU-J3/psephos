# "Where this stands" — the recon and the editorial record

**What this file is.** The read-only recon of the cut *"Where this stands"* section, taken
2026-09-06, plus the decisions taken against it the same day. It is the record a plan gets
written against; it is not itself a plan.

**Which file is the spec.** The section's content spec is **`docs/design/psephos-home-mock-v37.html`,
lines ~305–432** — the only file that contains it. The **frame** is v42: `psephos-home-mock-v42.html`
carries the `.tabs` stylesheet at lines 62–67 and 111 and **not one tab in its body**, which is the
orphaned half of the same cut. v37 is **historical**, like the chart mock beside it
(`chart-mock-v1-vs-live.md`); it is not patched to agree with anything.

The cut is recorded in `docs/status.md` in two places — the *"still cut and still gated on
`docs/gates.yaml`"* entry, and the *"Three things the record cannot show"* entry that cut it
alongside the teal series and the hatched demands band.

Live figures below were read from Turso at **DB clock 2026-09-06 20:58–20:59Z**. Every count on
this page moves; re-read before quoting.

---

## 1. The inventory — 24 statements, three tabs

**THE 24 DOES NOT DECOMPOSE FROM THE TABLES BELOW, noted 2026-09-09 and deliberately not
re-counted.** Tab 1 prints **13** table rows, Tab 2 prints **14**, and Tab 3 prints six statutory
rows in prose plus three DEAD spine statements — more than 24 however they are grouped. The figure
reconciles only as `13 rows + 5 paths + 6 statutory rows`, which counts Tab 1 in **rows** and Tab 2
in **paths**: one heading over two units, and the third instance of that failure on this project's
record. **No better total is offered here**, because the total was never the load-bearing number.
What is countable exactly is what the decisions touch, and that is what later work should cite:

- **Decision 2 (SUED, not "demanded") touches ONE statement** — Tab 1 **7a**, DEAD as worded. It
  survives only as the gated authored claim, which exists as `doj-demands-all-51` and is
  `status: stale`. Tab 2 path 3's *"Suits filed 31 jurisdictions"* is already SUED wording and
  DERIVABLE; it survives unchanged.
- **Decision 3 (tab 3 ships, rewritten) touches THREE** — the two `blind spot` badges and the
  closing tabnote. All three are rewritten, none dropped; the six statutory rows ship unchanged.
- **FIVE more are DERIVABLE-but-drifting and are touched by neither decision** — 7b, 7c, 7d,
  *"stalled 19 months"* and *"Appeals taken 12 dockets"*. These are the ones the derived gates
  exist to stop, and they rot without any editorial decision being wrong.

Classes: **DERIVABLE** (computable from the record today), **AUTHORED** (an editorial claim no
table produces), **DEAD** (falsified by the record).

### Tab 1 · "On the books now" (chip: 8)

| # | Statement | Class | Live check |
|---|---|---|---|
| 1 | TX **SJR37** passed May 15 2025, goes to voters | DERIVABLE | ✅ status `4`, `2025-05-15` |
| 2 | TX **SB510** passed Jun 20 2025; **HB493** same day | DERIVABLE | ✅ both `4`, both `2025-06-20` |
| 3 | OH **SB293** passed Mar 20 2026 | DERIVABLE | ✅ `4`, `2026-03-20` |
| 4 | AZ **HCR2001** passed Jun 15 2026 | DERIVABLE | ✅ `4`, `2026-06-15` |
| 5 | OH **SB63** passed Jun 16 2026 | DERIVABLE | ✅ `4`, `2026-06-16` |
| 6a | EO **14248** / **14399** published Mar 25 2025 / Mar 31 2026 | DERIVABLE | ✅ both exact |
| 6b | "a judge blocked an election EO on Aug 16 per reporting" | AUTHORED (C3) | no field exists |
| 6c | "Whether either is operating today is not in the record" | AUTHORED-true | correct; there is no outcome field |
| 7a | "DOJ has demanded voter data from **31 of 51** jurisdictions" | **DEAD as worded** | 31 is the **sued** count. The spec records demands going to all 50 states + DC |
| 7b | "**25** suits are live" | DERIVABLE, stale | **31** |
| 7c | "**12** have moved to a court of appeals" | DERIVABLE, stale | **23** — see §2 |
| 7d | "CourtListener · **46** dockets" | DERIVABLE, stale | **52** |
| 8 | WI: **56 of 59** failed, **3** vetoed, nothing became law | DERIVABLE | ✅ **exact** — 56 status-6, 3 status-5, 59 total, zero status-4 |

Producers: `state_bills` on `(state, bill_number)` with the vocabulary in
`web/lib/statebill.ts` (`STATUS_LABELS`, `stageOf`); `cases` counts through
`web/lib/campaign.ts` (`buildCells`, `isCircuit`, `summarize`, `JURISDICTIONS`).

**Fact 8 is the model for the whole section.** Every figure in it is derived, and it is still
exact a year after it was drawn, because nothing in it was typed by hand.

### Tab 2 · "What it would take" (chip: 5 paths)

| Path | Statement | Class | Live check |
|---|---|---|---|
| 1 | SAVE Act **2 of 5**; introduced Jan 3 2025, House Apr 10 2025, S.128 referred Jan 16 2025 and unmoved | DERIVABLE | ✅ all four exact; `s128-119` has `introduced_at == latest_action_at` |
| 1 | "stalled **19 months**" | DERIVABLE, drifting | 19.7 months today off the S.128 referral. **Must be computed at render** |
| 2 | Vehicle `s1383-119`, live in the Senate Mar 26 2026 | DERIVABLE | ✅ `is_vehicle=1`, `2026-03-26` |
| 2 | "Election text attached — **not on the record**" | AUTHORED-true | correct, and structural: the legislation channel never names the payload |
| 2 | "the path the trackers do not watch" | AUTHORED | no source cited |
| 3 | Suits filed **31 jurisdictions** | DERIVABLE | ✅ 31 |
| 3 | Appeals taken **12 dockets** | DERIVABLE, stale | **23** — see §2 |
| 3 | "DOJ wins one — **0 reported**" | AUTHORED | no win/loss field exists anywhere |
| 3 | "Cert petition — **none filed**" | DERIVABLE-negative | 3 entries match `certiorari\|supreme court`; all three are boilerplate or unrelated (a pro-hac-vice denial, two "do any cases raise similar issues? YES" brief headers). Absence of evidence only |
| 3 | tracker at "0 for 22" Aug 14 · AG called a SCOTUS filing "a possibility" Aug 16 | AUTHORED (B2) | dated, sourced to Democracy Docket, unverifiable here |
| 4 | TX **1 of 3**, passed May 15 2025; AZ same path Jun 15 2026 | DERIVABLE | ✅ exact |
| 4 | "Ratified by voters — not tracked here" | AUTHORED-true | correct |
| 5 | EOs published Mar 2025 · Mar 2026 | DERIVABLE | ✅ |
| 5 | "Challenged in court — per reporting" · "In force today — not in the record" | AUTHORED | the second is the honest half |

### Tab 3 · "If an emergency is declared" (chip: 0 on the record)

Six rows of statutory exposition — `2 U.S.C. §7`, `§1`, `3 U.S.C. §1`, the 20th Amendment, the
Electoral Count Reform Act of 2022, `50 U.S.C. §1601`, `10 U.S.C. §§251-255`, `47 U.S.C. §606`.
**All AUTHORED**: verifiable against the U.S. Code, derivable from nothing psephos holds. They
are also the most durable statements in the section, and the tab says as much itself.

**Three statements in this tab are DEAD, and they are its spine** — the two `blind spot` badges
and the closing tabnote, all resting on:

> "The executive collector asks the Federal Register for `presidential_document_type=executive_order`
> … so a proclamation declaring an emergency would be collected by neither shape."

`collectors/executive.py` requests **all seven** presidential document types; `proclamation` is in
`PRESIDENTIAL_TYPES`, and the docstring names "a national emergency declaration or an Insurrection
Act invocation" as exactly what the old shape missed. See §3 for when that changed relative to the
mock, which is the part a reader will otherwise get backwards.

---

## 2. The circuit count is 23, and this recon's first reading was 22

Two independent signals, agreeing on every row but one:

- `court LIKE '%Circuit%'` → **22**
- docket number not `cv`-shaped (appellate shape) → **23**
- The single disagreement: `united-states-v-minnesota`, `court = 'Eighth District'`, docket
  **`26-2679`**. Appellate docket, non-circuit court string.
- **Zero rows in the reverse direction** — nothing whose court says Circuit carries a `cv` docket.

So the court string has no false positives and exactly one false negative. **True circuit count:
23**, contingent on the classification fix in §5. Restated: fact **7c** and **path 3** read
**12 → 23**, not 12 → 22.

**The recon's own first reading inherited the defect it was reporting.** It named `'Eighth District'`
as a data-quality problem and then used the 22 that the problem produces, in the same pass. A
count is not independent of the defect you just described; that is why the cross-check exists.

---

## 3. The terminal-vs-running asymmetry

Every figure the mock derived from `state_bills` and `bills` is **exact today** — 12 of 12 date
and status checks, a year on. Every figure it derived from `cases` has **drifted upward**:
25 → 31 live, 12 → 23 appeals, 46 → 52 dockets.

That is the finding, not the individual numbers. **Bill facts are terminal** — a bill that passed
stays passed, on a date that never moves. **Litigation facts are running totals**, and every one
of them is a photograph of a Tuesday. A tab that mixes the two must know which is which, or it
will keep aging in exactly one half while looking uniformly current.

---

## 4. Tab 3 provenance — true at writing, falsified by the repo two days later

The earlier reading of this ("already false when the mock was written, by twelve days") had the
direction backwards, because it read a **tracking** date as a **writing** date.

| When | What | Evidence |
|---|---|---|
| ~2026-08-17 | v37 drawn | the mock's own chart labels the present: line 527, `today · Aug 17`. Latest reported content in it is Aug 14 / Aug 16 |
| 2026-08-19 | the board ships | `docs/status.md` |
| 2026-08-19 20:04:36 −0600 | the widening lands | `da49c3f  fix(collectors): the presidential shape requested one document type of seven` |
| 2026-09-01 | v37 is tracked | `d17e669  docs(design): track the v37 board spec…` — **tracking, not writing** |

**The claim was true when written and was falsified about two days later by the repo moving.**
The mock described the collector accurately; `da49c3f` widened it; the mock was tracked twelve
days after that and has read false ever since. Classification stays **DEAD** — it is false now,
on a page that would render it now — but nothing was careless at writing.

**There is no off-by-one in the two dates for the widening, and it is worth writing down because
it looks like one.** `da49c3f` is `2026-08-19 20:04:36 −0600`, which is `2026-08-20T02:04:36Z`.
The docstring and `docs/status.md` carry the UTC/session date (the 20th); `git log --date=short`
carries the local one (the 19th). One instant, two zones, no discrepancy.

This joins the family this project already tracks — **a design note ages exactly like a description
of a file**. No ordinal is given: there is no counted table of that family to order an entry
against, and inventing a rank would be the same species of error the family is about.

---

## 5. Prerequisite unit — canonicalize `cases.court` at READ, not in the data

### The mechanism, corrected

An earlier draft called the affected rows hand-seeded and therefore collector-safe. **They are
not.** The instrument that corrected it was `git log -- data/doj_cases.json`.

- `'Eighth District'` is **UW's string**, at `data/doj_cases.json:149`.
- `'DC Circuit'` is **UW's string**, at `data/doj_cases.json:41`, against `config/sources.yaml:292`
  which spells the same court `'D.C. Circuit'`.
- `collectors/tracker_uw.py` **resyncs that artifact**: bot commits touched it on 2026-08-29,
  09-01 and 09-04.
- Seed reuse **joins on the literal court string** — `config/sources.yaml:317` says so in its own
  comment, keeping UW's spelling verbatim *because* it is the join key.

**So rewriting the stored values is declined.** It self-reverts at both ends — the tracker rewrites
the artifact and the collector rewrites the row — and while it is briefly in place it breaks the
join that reuse depends on.

**Decision (approved 2026-09-06): store verbatim, classify at read.** A `canonicalCourt()` feeding
`isCircuit`, the chain logic and display, plus an **every-distinct-value-classifies alarm** so an
unknown court string fails loudly instead of silently classifying as a district.

**Open sub-question for the plan:** does the page display the verbatim string or the canonical one?

### What it actually costs today — latent, not rendered

The framing of this as a defect rendering a false "refile" on `/campaign` today **does not survive
the read, and the correction matters because it changes the unit's urgency**:

- `web/lib/campaign.ts:162` builds `predecessors` as *rows in the state group carrying
  `superseded_by`* — and **neither Minnesota row carries one** (`71453336`, D. Minn., terminated
  2026-08-17; `united-states-v-minnesota`, `26-2679`, live). So `chain` at line 187 evaluates to
  **`null`**, `StateCell.tsx:33–34` draws neither ↑ nor ↻, and `summarize().chains` does not count
  it. The cell contributes to `unlinkedEndings` instead.
- **The defect is latent.** The moment Minnesota's supersession is asserted — the same
  reconciliation already applied to 13 rows — `isCircuit('Eighth District')` returns false and the
  cell renders **↻ "refiled in another district"** for an Eighth Circuit appeal: wrong glyph,
  wrong tooltip, and indistinguishable from a real refile.
- `'DC Circuit'` is harmless to `isCircuit` (the substring matches) and is a display-consistency
  issue only.
- What *is* wrong today is every circuit tally, which is one short. Nothing on the site renders a
  circuit count — `summarize` has no circuit field — so the understatement lives in analysis, and
  §2 is where it first bit.

So the unit is a **latent-defect fix and a correctness prerequisite for any circuit figure the tab
would render**, not a repair of something visibly wrong on the page today.

### Sequencing

**routing → canonicalize `cases.court` → assert the Minnesota pair → section mock v1 on live data
→ build.**

Two orderings are load-bearing and neither is arbitrary. The canonicalization precedes the mock
because a mock drawn against a circuit count of 22 would bake the defect into the spec. And **the
canonicalization precedes the Minnesota supersession assert**, which is the ordering that actually
costs something if reversed: asserting the pair first **arms** the latent chain defect, and the
cell is born rendering a false ↻ *"refiled in another district"* for a circuit appeal. Canonicalize
first and the same assert produces ↑ *"appeal"* on its first render — the link is born correct
instead of being shipped wrong and then fixed. The assert is its own unit either way; it is not
folded into the canonicalization.

---

## 6. `docs/gates.yaml` — proposed schema

Absent at origin and locally, confirmed. Two shapes.

**Authored** — an editorial claim, carrying its source and its expiry:

```yaml
- id: doj-scotus-possibility
  claim: "the Attorney General called a Supreme Court filing a possibility"
  kind: authored
  grade: {source: B, info: 2}
  source: "Democracy Docket"
  source_url: "https://…"
  asserted_on: 2026-08-16        # the date the SOURCE said it
  recheck_after: 2026-11-16
  falsified_by: "a docket entry showing a cert petition filed"
  status: active                 # active | stale | falsified
```

**Derived** — and it **carries no literal value**, which is the whole point:

```yaml
- id: suits-live
  kind: derived
  produced_by: "web/lib/campaign.ts#summarize"
  renders_as: "{n} suits are live"
```

A derived entry holding a number is how 25, 12 and 46 rotted while looking maintained.

**Enforcement: `assert-gates.mjs`, joined both directions, plus `recheck_after` expiry.** It
catches ungated claims and orphan gates in one run.

**CORRECTED 2026-09-09 — this paragraph said it "matches the house pattern (`assert-encodings`,
`assert-layout`) … and shares an exit code", and what shipped deliberately does not.** The other
three scripts are binary: `exit(failures === 0 ? 0 : 1)`. `assert-gates` has **four** codes —
`0 OK`, `1 EXPIRY`, `2 DOM`, `3 CANNOT_RUN` — and the departure is the point, not a drift from the
pattern. The failures need different actions: an expired claim is a claim to go and recheck, a DOM
join failure is a claim to gate or a gate to delete, and they are not the same errand. And
`CANNOT_RUN` carries the distinction this repo shipped twice in one day elsewhere — **a run that
COULD NOT CHECK is not a run that checked clean**, which is `sha_sweep`'s NOT CHECKED ending and
its coverage-gap list, in a different tool. Binary would collapse all three into `1` and a reader
would have to open the log to learn which errand they were on.
 Expiry is the part that earns the file: an authored
claim with a date goes stale invisibly, and `recheck_after` is the only property of it a machine
can fail on.

**Declined, with the cost that decided it.** A **build step** refusing to build on an ungated claim
is stronger, but a stale gate then blocks an unrelated deploy, and the pressure that creates is to
widen the gate rather than recheck the claim. **Review-only** costs nothing and enforces nothing;
this project's own falsified list is four-for-four on claims that survived review because they
looked right, and the drifting "19 months" would have gone straight through it.

---

## 7. The seven editorial decisions — approved 2026-09-06

These answer the seven questions the recon put to the editorial pass. All seven are **approved
2026-09-06**.

1. **Spec.** Content from v37's section, frame from v42; the build starts from a **new section
   mock on live data**, per the chart precedent; v37 is historical.
2. **The "31 of 51" verb: SUED** — that is what the record supports. *"Demanded"* survives only as
   a gated authored claim (the spec's all-51 statement, B2), or it drops.
3. **Tab 3 SHIPS, rewritten.** The statutes are the durable core. The spine flips to present
   tense — *"requests all seven types since 2026-08-20; a proclamation declaring an emergency
   would be collected"* — which is checkable against the docstring.
4. **Grade granularity: PER CLAUSE.** The gate is the unit of grading, so fact 6's A1 date never
   shares a badge with its C3 reporting.
5. **Expiry: stale renders GREY PLUS DATE**, never silent removal. `recheck_after` defaults by
   grade, as starting numbers to be adjusted: **C3 30d, B2 90d, statutes 365d**.
6. **Absence of evidence: SCOPED NEGATIVES** — *"none in the record psephos holds"*, on the map
   key's option-4 precedent. Never a bare *"none filed"*.
7. **Enforcement: the ASSERT SCRIPT**, joined both directions, plus the `recheck_after` expiry
   check. Build-step declined (over-couples); review-only declined (the falsified list indicts it).

Decisions recorded elsewhere in this file and approved the same day: `cases.court` stored verbatim
and classified at read (§5), the sequencing (§5), the circuit figure of 23 contingent on that
classification (§2), and the deliberate omission of an ordinal in the design-note-ages family (§4).

**The last sub-question is DECIDED, 2026-09-09: the page displays the VERBATIM court string, and
canonicalization stays a CLASSIFICATION concern.** This ratifies what production already does
rather than changing anything — which is the reason to write it down, since an undecided state that
happens to be coherent is one nobody has to defend until something else depends on it.

Three things decide it together. **Canonicalization is already scoped to classification**:
`campaign.ts` runs `isCircuit` through `canonicalCourt`, so district-vs-circuit bucketing is
canonical while the value shown is not. **§5 already ruled the stored value stays verbatim**,
because `cases.court` is a join key in three places and rewriting it breaks all three — and display
following storage is the consistent reading rather than a second rule. **And the reader sees what
the tracker actually typed**, which is what a record is for: `'Eighth District'` on the page is UW's
own words, and the fact that psephos knows it means the Eighth Circuit shows up in the bucketing
rather than by silently correcting the source.

As built: `CaseRow.tsx` and `case/[case_id]/page.tsx` render `{c.court}` raw, including both
supersession directions. **No gate displays a court string at all** — all eight `renders_as`
templates are counts or dates — so the register did not force this and would not have.
