# 5b-b — state vehicle detection: discovery spike (Part A)

Read-only spike against the LegiScan API, ~75 queries, no writes. It asked one
question: can psephos detect a state-level **vehicle** — an unrelated bill carrying
a voting-rights provision — the way it flags the federal maneuver? The answer is no,
and the reason is structural, not a sampling artifact.

## Two framing facts

1. **The federal `is_vehicle` is asserted by hand, not detected.** `config/sources.yaml`
   says so in as many words; `collectors/legislation.py` reads `vehicle_ids` off the
   watchlist. There is no federal detector to port — whatever state detection would be
   is the project's *first* actual detection of the maneuver.
2. **The 179 bills in `state_bills` cannot contain a vehicle, by construction.**
   `election_match` filters the masterlist on title/description. A vehicle's title is
   about something else, so it never matches, never earns a `getBill`, never enters the
   dimension. Detection is therefore a **discovery** problem before it is a flagging one.

## What was measured

**A1 — `getBill` live field inventory** (18 bills). The full payload has 32 top-level
keys. The arrays the repo fixture never exercised, confirmed live (population = share of
18 bills with a non-empty value):

| field | element shape | populated |
| --- | --- | --- |
| `subjects` | `{subject_id, subject_name}` | 9/18 |
| `sasts` | (related-bill relation) | 5/18 |
| `amendments` | `{amendment_id, adopted, title, description, url, …}` | 8/18 |
| `progress` | `{date, event}` | 18/18 |
| `sponsors` / `texts` / `history` | full | 18/18 |
| `votes` | `{roll_call_id, yea, nay, passed, …}` | 15/18 |

`sasts` and `amendments` are real but sparse.

**A2 — subject vocabulary.** Not a controlled vocabulary. `"Elections"` appears in only
3 of 9 states; each state spells its own election subject (`"Elections--Registration &
Suffrage"`, `"Elections : Voting"`, `"Elections And Electors - Title 16"`), and
`subjects` is populated on only ~50% of bills. A subject-based filter would be
state-specific, half-absent, and would need a `getBill` per bill (the budget blowup the
change-hash gate exists to avoid). Not viable.

**A3 — the `getSearchRaw` delta.** `getSearchRaw` returns a flat list of
`{relevance, bill_id, change_hash}` — full-text, token-relevance, no title/subject. Over
3 states × 3 terms the delta (matches **not** already in `state_bills`) was **405
distinct bills**, high-relevance-heavy: **174 at relevance ≥90, 181 at 70–89**, 40 at
50–69, 10 <50. The net is wide; it is not empty.

**A4 — 20 delta bills, stratified across relevance, classified by hand:**

| bucket | count |
| --- | --- |
| **Rider** (off-topic bill genuinely carrying a voting provision — the target) | **0** |
| **Incidental** (voting language in passing) | **14** |
| **Miscategorized** (real election bill, title missed the term list) | **6** |

- *Incidental (14):* municipal-utility-district creations (confirmation-election
  boilerplate), vehicle-registration fee bills matching on the `registration` **token**,
  an immigration bill matching `citizenship`, a vital-records/foreign-birth bill, the WI
  omnibus budget, a transit constitutional amendment, water/bond financing, sheriff
  employment.
- *Miscategorized (6):* genuinely election bills the narrow title-filter missed —
  voter-ID as "proof of identification for voting" (TX HB4030), mail-ballot as "ballot to
  be voted by mail" (HB5351/HB3691), closed primaries (HB4059), election-audit oversight
  (SB1541), veteran voter registration (HB3359). All carry `Elections--*` subjects.
- *Rider:* none in the sample.

## The conclusion, and what actually establishes it

**Full-text discovery cannot catch the vehicle maneuver, at any precision — for a
structural reason, not because of the 0-in-20.** A true vehicle is an unrelated bill to
which a voting payload is attached *by amendment*. Its **base text carries no voting
language until the amendment lands**, so a full-text search over that text cannot match
it at the moment the maneuver matters. By the time the incorporated text would match, the
attachment has already happened and been observable by other means. `getSearchRaw`
searches the wrong artifact for the wrong signal. That is the finding that closes the
door.

The A4 sample corroborates but does not carry the argument, and its limits should be
stated:

- **0 riders in 20 shows riders are *uncommon in the delta*, not that they are *absent*.**
  Zero in a 20-sample is consistent with a true prevalence anywhere from 0 up to a few
  percent: at 2% prevalence there is a ~67% chance of seeing none in 20 (`0.98^20`); at
  5%, ~36%. So the sample bounds riders as rare; it cannot prove there are none.
- It does not change the decision. A discovery queue built on this delta would be ~70%
  incidental token/context noise and ~30% miscategorized election bills, with the rider
  signal — if present at all — indistinguishable by relevance from the vehicle-registration
  junk sitting in the same mid-band. A queue that is ~98% not-the-thing is unusable
  regardless of whether a rare rider hides in it.

## Correction to the spike's own first conclusion: `sasts` ≠ `amendments`

The spike write-up suggested "watch `amendments` and `sasts` on bills we already hold."
That conflates two different things:

- **`amendments` on a bill already in the 179 is amendment-tracking on an *election*
  bill.** Useful, but it is not vehicle detection — the bill is already known and already
  about elections.
- **`sasts` is the only signal that points *out* of the held set:** LegiScan's asserted
  relation from a held voting bill to another bill that may not be in the 179. A `sasts`
  target that *fails* `election_match` is a high-precision vehicle candidate — the tool's
  own assertion that a voting bill is related to an unrelated one.

So the one probe that survives this spike is the **`sasts` probe**, specifically, not
amendment-watching. It is cheap (the masterlist we already pull per state carries the
target's title, so no extra `getBill` to run the filter on the target). It may still
dead-end: `sasts` usually holds *companions*, which are themselves election bills, in
which case state vehicle detection is not reachable on free-tier data and that becomes a
stated spec limitation rather than an open TODO. Its own short session.

The theoretically correct signal is the amendment event on an *un-held* bill:
`amendments` carries `title`/`description`, so the data exists. It's unreachable for the
same reason as subject filtering, since watching it requires a `getBill` on bills the
filter never matched. Detection is discovery-bound at every path tested here, not
signal-bound. (This is why "watch amendments then" is not the escape hatch it looks
like: the amendment *text* would carry the voting language a vehicle's base text lacks,
but you can only read it on bills you already fetched, and the vehicle is by definition
one you didn't.)

## The valuable byproduct

The **6/20 (~30%) miscategorized rate** is a direct measurement of the current election
title-filter's false-negative rate — something nothing had measured. The narrow term
list is leaking real election bills whose titles use different phrasing (voter ID,
mail ballot, primaries, audits). That is a tractable, higher-value unit than vehicle
detection, and it is what handoff 9 addresses.

## Recommendation

- **Do not build `getSearchRaw` vehicle discovery.** Structurally blind to the maneuver,
  and noisy where it can see.
- **Fix the filter's recall first** (handoff 9) — the measured, tractable defect.
- **Keep the `sasts` probe as its own later session**, with the companion-dead-end
  outcome accepted as a possible and legitimate answer.

Queries spent: ~75, all read-only. Nothing touched production Turso, the schema, the
collector, or the web layer. The `is_vehicle` column and Vehicle badge already exist end
to end (5b-a / 5b-c), so whatever a future detection unit writes lights up with no view
change.

---

# Addendum: the sasts probe result (handoff 11) — 5b-b closed

The one probe the spike left open. Read-only, ~464 one-time queries (455 `getBill`
+ 9 `getMasterList`), no writes anywhere. `tools/sasts_dump.py` dumps the
dimension's outward `sasts` relations to a byte-stable corpus; `tools/sasts_join.py`
joins it offline against the held set and a same-day masterlist title snapshot,
running the **live** `election_match`. The answer is the dead-end the spike named:
companions and stragglers all the way down. State vehicle detection is not reachable
on free-tier LegiScan data.

## Inputs

- `data/state_bills.json` @ `e0e8f83` (2026-07-23T08:16Z), **455 bills**. Still 455 at
  origin/main `3da9621` (2026-07-29T19:00Z), so the held set did not grow under the join.
- Same-day `data/masterlist_corpus.json` (37,388 bills across the nine states),
  rebuilt for the join so target titles are current.

## Part A — the sasts dump

**146 carriers / 455 (32%**, against the spike's ~28% prediction), **0 skipped**.
205 relations, **164 distinct targets** (sasts is often reciprocal, so relations
overcount targets). Histogram by relation type:

| relation type | count |
| --- | --- |
| Same As | 98 |
| Crossfiled | 50 |
| Similar To | 45 |
| Enabled by | 7 |
| Enabling for | 4 |
| Related | 1 |
| **Replaces / Replaced by** | **0** |

## Part B — the four-bucket join

| bucket | definition | count |
| --- | --- | --- |
| **held** | target already in `state_bills` | **176** |
| **straggler** | unheld, target title *passes* `election_match` | **0** |
| **candidate** | unheld, target title *fails* `election_match` | **29** |
| **unresolvable** | target absent from the masterlist corpus | **0** |

**Read the 0 stragglers correctly.** Bucket 2 is defined as *unheld AND the title
passes the filter*, so a bill the filter **misses** lands in bucket 3 by
construction — Part C finds ~17 real election bills sitting in the candidate
bucket for exactly that reason. The zero is therefore **not** a clean bill of
health on recall. What it does establish is a **collection-integrity check the
probe passed incidentally**: every filter-passing target in the corpus is already
held, i.e. the collector is not dropping bills it matched. Recall (bills the filter
*should* match but doesn't) is a separate question, answered below.

The 0 unresolvable means every target resolved within the nine-state snapshot.

Cross-tab (bucket × relation type):

| bucket | Same As | Crossfiled | Similar To | Enabled by | Enabling for | Related | total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| held | 90 | 50 | 28 | 4 | 4 | 0 | 176 |
| straggler | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| candidate | 8 | 0 | 17 | 3 | 0 | 1 | 29 |
| unresolvable | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Part C — the 29 candidates, classified (titles are the evidence)

**Zero vehicles.** The bucket splits two ways.

**Class 1 — filter-recall misses (17): real election-domain bills the title filter
dropped.** Every one is a genuine election/redistricting bill; the filter missed it
on a plural form (`voter` vs "voters", `primary election` vs "primary elections") or
on a bare term deliberately excluded from `terms` ("election", "reapportionment"):

| target | title | rel. type | held source |
| --- | --- | --- | --- |
| TX HB2074 | Relating to allowing a person who will be 18 … to vote in the preceding primary elections | Enabled by | TX HJR122 |
| TX SB630 | (same 18-year-old primary-voting title) | Enabled by | TX SJR29 |
| TX SB68 | (same) | Enabled by | TX SJR9 |
| TX HJR161 | Proposing a constitutional amendment adding individuals who are not United States citizens to the classes of persons not allowed to vote | Similar To | TX SJR37 |
| NC H1035 | Various Local Election Changes III | Same As | NC S818 |
| MI HB5971 | Elections: voters; language assistance for elections act; create | Same As | MI HB5972, HB5969, HB5970 |
| MI SB0963 | Elections: voters; language assistance for elections act; create | Same As | MI SB0961, SB0964, SB0962 |
| FL H535 | Candidate Qualifying | Similar To | FL H0991 |
| FL H91 | Candidate Qualification | Similar To | FL H0991 |
| FL S62 | Candidate Qualification | Similar To | FL H0991 |
| FL S620 | Candidate Qualifying | Similar To | FL H0991 |
| FL H619 | State Reapportionment | Similar To | FL H0947 |
| FL S728 | State Reapportionment | Similar To | FL H0947 |

(The MI rows are one target each reached by three tie-barred companions — 6 relations,
2 distinct targets.)

**Class 2 — cross-subject index noise (12): non-election targets.** These fan out of
a handful of broad Florida source bills whose state-provided "Similar To" index reaches
across unrelated subjects:

| target | title | rel. type | held source |
| --- | --- | --- | --- |
| FL S1120 | Water Management Districts | Same As | FL H0701 |
| FL H1161 | Big Cypress Basin | Similar To | FL H0701 |
| FL S1636 | Big Cypress Basin | Similar To | FL H0701 |
| FL H593 | Governmental Agencies and Personnel | Similar To | FL H0701 |
| FL S802 | Public Officers and Employees | Similar To | FL H0701 |
| FL H1527 | Senate Confirmation of Gubernatorial Appointments / Legislative Approval of Extended States of Emergency | Similar To | FL H0947 |
| FL S1584 | (same senate-confirmation title) | Similar To | FL H0947 |
| FL H657 | Community Associations | Similar To | FL S1498 |
| FL S554 | Nonprofit Corporations | Similar To | FL H0797 |
| FL S1014 | Provision of Municipal Utility Service to Owners Outside the Municipal Limits | Similar To | FL H1075 |
| FL S296 | Victims of Domestic Violence and Dating Violence | Related | FL S0298 |
| FL H269 | Victims of Domestic Violence and Dating Violence | Similar To | FL S0298 |

**The Florida observation.** The noise class is looseness on the **source** side of the
relation, not a payload grafted onto the target: a few broad FL source bills (H0701
alone reaches Water Management Districts, Big Cypress Basin, Governmental Agencies, and
Public Officers) fan a wide "Similar To" net. That is why `Similar To` dominates the
candidate bucket at 17 of 29.

## The structural finding

Even the one signal the spike said might survive expresses the **wrong relation**. A
vehicle is defined by *substitution* — a payload grafted onto an unrelated bill by
amendment. The `sasts` vocabulary **as populated in this data** (n=205 relations, nine
states, current sessions) carries only companionship (`Same As`, `Crossfiled`),
similarity (`Similar To`), and the joint-resolution/implementer pair (`Enabled by`,
`Enabling for`). `Replaces` / `Replaced by`, the committee-substitute shape, appears
**zero times**. This is a statement about the vocabulary as it appears here, not a claim
about what LegiScan can ever carry — but at the scope measured it holds: the tool's own
asserted relations, joined against its own filter, point at companions and mislabeled
election bills, never at a vehicle. Combined with the spike's structural close of
full-text discovery, both reachable paths are exhausted, so 5b-b is closed as a stated
free-tier limitation rather than an open TODO.

## Byproduct (its own unit, not touched here)

`election_match` is word-boundary exact, so it misses the **plural of every term** —
`voter` misses "voters", `primary election` misses "primary elections". Measured against
the same corpus, a naive plural-tolerant variant of the current term list would keep
**~74 additional bills** (voter-dominated: +56 voter, +11 election official, +5 primary
election), and because handoff 9 measured recall with this same matcher, the whole class
went straight through it. That is a recall unit under the handoff-9 corpus methodology,
not a change to make here.
