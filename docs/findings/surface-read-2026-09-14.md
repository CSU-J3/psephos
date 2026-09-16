# Surface read, 2026-09-14

Five findings from a read of the production site (`psephos-theta.vercel.app`), recorded
and not fixed. No pixels move in the commit that lands this file.

**The file is new.** The brief that opened it asked to extend "the file from the previous
entry" and "yesterday's two-29s entry". Neither is in this repository at `0acff03`: no
`docs/findings/surface-read-*` file has ever been committed, and no entry about two 29s
exists in `docs/`. They are referenced here and not reproduced, so a reader does not go
looking for text this repo never held. **The brief called this file an extension of a
"two 29s" entry that was never committed, so the entry it referenced does not exist.** Its
finding is restated below as its own item, under the denominators (section 4).

Code reads are pinned to `0acff03`. Production reads were taken 2026-09-14 23:30Z, on the
export of 12:55:50Z.

## 1. The stamp's zone, and the mechanism

**Observed (review layer):** one export, 12:55Z, read as 07:55 CDT, 08:55 EDT and 06:55
MDT on three reads, beside a section label in Z and a list headed "UTC days".

**Mechanism, read from the code: those are one instant on three frames of a rotation,
not three clocks.** `web/app/page.tsx:265` renders `collected <RotatingTime
iso={collectedAt} />`. `collectedAt` is `readCollectedAt(activity)` (`page.tsx:138`),
which is `MAX(last_fetch)` read off the rows (`web/lib/read.ts:92`). `RotatingTime`
(`web/components/RotatingTime.tsx:53`) builds the date as `new Date(iso)`, with an
argument, and formats it through seven IANA zones with explicit `timeZone`: UTC, New
York, Chicago, Denver, Los Angeles, Anchorage, Honolulu. It swaps the visible reading
every 4 s (`CYCLE_MS = 4000`). The production server HTML carries all seven at once:

```
<time dateTime="2026-09-14T12:55:50.259600+00:00"
      title="12:55Z · 08:55 EDT · 07:55 CDT · 06:55 MDT · 05:55 PDT · 04:55 AKDT · 02:55 HST">
```

So the stamp reads the record, not the runtime clock, and **no invariant is violated by
the stamp.** The Where-this-stands label beside it is a different renderer:
`stamp()` in `WhereThisStands.tsx:53` slices the same ISO string into `Sep 14, 12:55Z`.
One instant, two renderers, one of them rotating through seven zones and one fixed at Z.

**What the lane can see: nothing about this string.** No DOM check asserts the stamp:
`assert-gates.mjs`, `assert-encodings.mjs` and `assert-layout.mjs` contain no reference
to `RotatingTime`, `rt-stack`, the `time` element or its `dateTime`. The zone the lane runs
in would not matter anyway, because every reading carries an explicit `timeZone`. What
varies between reads is time since mount, which picks the visible frame.

**Beside it, and not the stamp: four no-argument `new Date()` calls are live in the web
layer**, each a deliberate window computation against the present, not a label:

- `web/app/page.tsx:112`, `const now = new Date();`. It drives the homepage's 24h
  collected-news cut (`collectedSince`), `buildTimeline`, `readNews`, `readCampaign` and
  `readBills`.
- `web/app/campaign/page.tsx:96`, `const now = new Date();`. It feeds `buildCells(rows,
  now)`, which dates dormancy (the 60-day Quiet cut).
- `web/lib/db.ts:303`, `windowStarts(new Date())` in `getChannelActivity`. It computes
  the 24h and 7d starts behind the wire's channel deltas.
- `web/lib/db.ts:820`, `const now = new Date();` in `getTimelineEntries`. It computes the
  band start and the 24h window of the timeline query.

`page.tsx` documents its use as deliberate: *"`now` still drives every window below --
those ARE questions about the present -- but the label is not a window."*

**There is no standing invariant to violate.** `docs/status.md` holds no `new Date()` rule
among its standing invariants. It holds a falsified entry (`status.md:1609`, *"`new Date()`
is prohibited in the web layer"*) recording that the prohibition "was written as though it
already held". That entry names the two page sites, `page.tsx` (then line 107) and
`campaign/page.tsx:96`, and calls the rule "enforceable on new code". The per-file bans
(`stands.ts`, `statebill.ts`, `movement.ts`, `assert-gates.mjs`) do not reach any of the
four. **Two of the four have never been recorded anywhere**: the `db.ts` pair, both from
2026-08-14 (`96f04d3`, `a9fb298`), appears in no entry in `docs/` or `CLAUDE.md`.

**RULING OWED, Corey: whether to write the invariant, and over what scope**, given four live
window computations, each deliberate. Written layer-wide, it makes these four violations
that each need a disposition, or it has to carve them out by name. Written per file, it
should say so where it is stated. Left unwritten, the falsified entry stays the only record,
and it covers two of the four.

## 2. An ungated assertion on Tab 2

Tab 1 (`WhereThisStands.tsx:145-167`) states both EO claims inside
`<span data-gate="eo-14248-enjoined">` and `<span data-gate="eo-14399-s3-enjoined">`, with
two recheck chips: `recheck by Dec 10` and `recheck by Sep 25`. Tab 2's Path "The election
executive orders operate unblocked" (`WhereThisStands.tsx:298-313`) states the same two
claims in its "In force today" step, verbatim on production:

> §3 of 14399 and 14248's registration rules enjoined per tracker · the rest not in the record

It has no gate id and no recheck chip, and it cannot carry a gate: `Path` renders each
step as two plain spans (`WhereThisStands.tsx:464-465`).

**The brief put the cost as "on 2026-09-25 Tab 1 greys and Tab 2 does not." Neither greys
on its own.** Tab 1's chip is a typed literal, `<span className="rk">recheck by Sep
25</span>`, and nothing restyles it on a date. What fires on the date is `assert-gates.mjs
--expiry-only` in `ci.yml`, keyed on the gate id, once the record's clock passes
`recheck_after`. It fires on the next human push, not on the cron. **The concrete cost,
restated on that mechanism:** when that red arrives and a person rechecks
`eo-14399-s3-enjoined`, the gate id leads to Tab 1's span and to nothing else. Tab 2 goes on
asserting the claim with no id to find it by, and no chip to restyle when the claim is
marked stale. This is the chip-register unit's failure in operation, and its failure
statement in `docs/status.md` now names it as the cost.

**Where the "greys on its date" description came from: the repo, before the review layer.**
It was written into the register and the script, and repeated from there. **`367d714`
(2026-09-07) was the earliest carrier**: *"THIS GOES GREY ON 2026-09-16 unless someone
rechecks it"* on `eo-blocked-per-reporting` in `docs/gates.yaml`. That line was already
retired, and for an unrelated reason: `cb09416` (2026-09-13) removed the whole entry
because its date matched no docket event, not because the grey claim was wrong. The two
live carriers, the `gates.yaml` header (*"it does NOT stop the chip rendering grey with its
date"*) and `assert-gates.mjs`'s *"(status: stale, renders grey)"*, are corrected in the
commit that lands this file. Nothing asserted on either string, checked by `git grep`
over tests, the DOM checks and every workflow before editing.

## 3. The dagger gloss versus the section names

Section titles, `web/lib/movement.ts:18-21`, verbatim:

```
continued: "Continued elsewhere",
unlinked: "Ended, with no link asserted",
ended: "Ended in this record",
quiet: "Quiet",
```

**The buckets live in `lib/movement.ts` (`isMember`) and `lib/campaign.ts` (`buildCells`),
not in `web/lib/board.ts`**, which the brief named. `board.ts` holds the homepage map's
posture vocabulary.

Legend, `web/app/campaign/page.tsx:154`, verbatim: `† ended here, with no link asserted to
the live docket`. The cell marker, `components/StateCell.tsx:50`, renders `†` when
`cell.unlinked.length > 0`, titled `N ended docket(s) here with no link asserted to the
live one`.

Production, 23:30Z: **Continued elsewhere 18, Ended, with no link asserted 0, Ended in this
record 2 (MI, OK), Quiet 3.** The gloss names the **`unlinked` bucket, the one that reads
0.** No cell carries a dagger, **MI and OK included**: each renders with no marker at all.
The gloss opens on "ended here", which echoes the title of the bucket that reads 2, while
its criterion is the one that reads 0. A reader who sees MI and OK under "Ended in this
record" and a legend saying "† ended here" has reason to expect daggers on them, and finds
none.

**Both halves are the finding.** (1) **The legend explains a mark with zero instances**: no
cell on the page carries `†`. (2) **It explains that mark as the bucket reading 0**, "Ended,
with no link asserted", while the bucket reading 2 (MI, OK) is named "Ended in this
record". So the one ended state a reader can actually see on the grid has no mark, and
the one the legend describes has no members.

## 4. Unlabelled denominators

Appeals render as three numbers on production, each correct for its own denominator and
none naming it:

- **22**: "27 district suits and **22 appeals**" (`data-gate="district-circuit-split"`), meaning
  appeal dockets among the 49 DOJ-scoped dockets.
- **21**: "29 remain open — 8 district, **21 on appeal**" (`data-gate="open-split"`), meaning
  appeal dockets still open.
- **17**: `/campaign` grid cells carrying `↑ continued as a circuit appeal`, meaning
  jurisdictions whose live docket is an appeal. One more cell carries `↻` (a refile), so
  17 + 1 = 18 matches "Continued elsewhere".

**The two 29s, restated here as their own item because the entry that first named them
was never committed.** Two different quantities render the same figure on the homepage:

- **29 open dockets**: the DOJ fact row, "29 remain open — 8 district, 21 on appeal"
  (`data-gate="open-split"`). The unit is dockets.
- **29 jurisdictions with a live suit**: the map summary, "31 of 51 jurisdictions sued · 29
  suit live · 2 suit ended". The unit is jurisdictions.

They agree today by coincidence of the data, not by construction. A jurisdiction with two
open dockets, or one whose only open docket is a superseded original, would separate them,
and nothing on the page says which unit either figure counts. The brief treated them as
one instance of the unlabelled-denominator shape, not the whole of it, and the three
appeals figures above are the rest.

## 5. 26 passed titles

Florida H0797 "Nonprofit Corporations" sits in the passed column (26) that Tab 1's
narrative draws on, and its title carries no election content.

**The brief's query does not run as written.** `SELECT state, bill_number, title FROM
state_bills WHERE stage = 'passed'` fails on Turso with `no such column: stage`. The table
stores LegiScan's numeric `status` (`schema.sql`, `state_bills.status`), and the web layer
derives the stage from it (`web/lib/statebill.ts:15`, `"4": "Passed"`; `stageOf` at
`:124`). The query run instead, on the remote backend (`db.backend(conn) == 'turso'`,
2026-09-14 23:28Z):

```sql
SELECT state, bill_number, title FROM state_bills WHERE status = '4' ORDER BY state, bill_number
```

It returned **26 rows**, matching the column. All 26, unfiltered and unreclassified. The
list is the finding, and the collector is unchanged.

| state | bill | title |
| --- | --- | --- |
| AZ | HCR2001 | Citizenship; identification; contributions; early voting |
| FL | H0797 | Nonprofit Corporations |
| FL | H0991 | Elections |
| FL | S0298 | Public Records/Victims of Domestic and Dating Violence |
| GA | HB788 | Macon County; rename position of chief election official as chief election supervisor |
| GA | HR139 | Georgia Association of Voter Registration and Election Officials Day at the state capitol; 02/04/25; recognize |
| GA | HR838 | O'Connor; Daniel; service in redistricting and celebrating his birthday; commend |
| GA | SR563 | Georgia Secretary of State; request of the United States Department of Justice to securely produce Georgia's voter registration list; urge |
| MI | HR0196 | A resolution to demand that the Michigan Secretary of State comply with the United States Department of Justice’s request for an unredacted copy of Michigan’s computerized statewide voter registration list, as required by section 303 of the Civil Rights Act of 1960 and section 8(i)(1) of the National Voter Registration Act of 1993, to the full extent permitted by law. |
| OH | SB293 | Revise deadline to return absent voter ballots |
| OH | SB63 | Prohibit use of ranked choice voting; withhold funding for use |
| TX | HB2259 | Relating to the instructions for an application form for an early voting ballot. |
| TX | HB3697 | Relating to the text on an application for a ballot to be voted by mail. |
| TX | HB493 | Relating to ineligibility to serve as a poll watcher. |
| TX | HR591 | Honoring Cliff Albright for his efforts to encourage voter participation and civic engagement. |
| TX | SB1470 | Relating to requiring the Department of Public Safety to share data for the purpose of maintaining the statewide voter registration list. |
| TX | SB1540 | Relating to maintaining the confidentiality of the personal information of election officials and their employees. |
| TX | SB1862 | Relating to interstate notification by the voter registrar of certain applicants for voter registration. |
| TX | SB2166 | Relating to testing of voting tabulation equipment. |
| TX | SB2629 | Relating to organization of, meetings of, and voting by condominium unit owners' associations and property owners' associations. |
| TX | SB2753 | Relating to the integration of early voting by personal appearance and election day voting, including the manner in which election returns are processed and other related changes. |
| TX | SB2964 | Relating to an opportunity to correct certain defects in an early voting ballot voted by mail. |
| TX | SB510 | Relating to the failure of a voter registrar to comply with voter registration laws. |
| TX | SB827 | Relating to the audit of an election using an electronic voting system. |
| TX | SB901 | Relating to the declaration of a candidate's ineligibility on the basis of filing an application for a place on the general primary election ballot or for nomination by convention with more than one political party. |
| TX | SJR37 | Proposing a constitutional amendment clarifying that a voter must be a United States citizen. |

## Closing note, 2026-09-16

Two additions. Nothing above is reopened and nothing is fixed here. Code reads in this
section are pinned to `c779f4d`, not to `0acff03` like the five findings above.

### The 380px read

**Read by Corey on 2026-09-15, against the deploy carrying `99cea6d`** (*fix(stands): path
step details stack under their labels below 640px*, 2026-09-13). What it reports: on Tab 2,
the Path's step details stack under their labels at the label's indent; step 3 of "The
election executive orders operate unblocked" (`WhereThisStands.tsx:299,304`) wraps to three
lines; nothing overflows horizontally. **380px is the width the read is given at** — the
brief names it, and it agrees with `99cea6d`'s own measurement, which put step 3 at three
lines at 380 where it had run to nine beside a 170px label.

**This is the only read of that width the project has, and no lane supplies another.** Two
reasons, and the second is stronger than the brief allowed.

1. **380 is below the matrix floor.** `assert-layout.mjs`'s `EXPECTED_ZONES` (`:68-79`) runs
   2542 down to 500 in twelve rows, both sides of each breakpoint pinned. 380 is 120px under
   the lowest row, so no assertion in the lane is evaluated anywhere near it.
2. **At the three widths where the stacked form does exist, the 03:17Z lane does not see it
   at all — not for overflow, not for anything.** The brief put this as "overflow only";
   it is less than that. All five `Path` instances sit in the `wts-next` panel
   (`WhereThisStands.tsx:215-323`), which renders `hidden={tab !== "next"}` while the default
   tab is `now` (`:75`, `:215`); `globals.css` carries no `.panel` rule and no `[hidden]`
   override, so a hidden panel is `display:none` and generates no boxes; and
   `assert-layout.mjs` contains no `click` — its only interaction with the page is the month
   scrubber. So at 640, 639 and 500 (`:77-79`) the `no horizontal overflow` check (`:149`) is
   measuring a page those steps are absent from.

**What follows from both: the rules at `globals.css:638-642` — the second of the file's two
`max-width: 640px` blocks, deliberately after the first — are asserted by nothing.** A person
selecting Tab 2 at phone width is the only instrument that has ever looked at them, and this
read is the one time that happened.

### An instance of section 1, not a sixth finding

Beside the stamp's zone: a concrete case a reader meets on the homepage.

**A "Sep 16, 2026" bucket heads the last-7-days list, correctly.** The bands are UTC days
generated from `now` rather than from the data — `BAND_DAYS = 7` (`timeline.ts:35`) and the
loop at `timeline.ts:183-188` walks back from `dayKey(now)`, so the top band is always the
current UTC day whether or not anything landed in it — and the header says so, "The last 7
days · UTC days" (`page.tsx:337`). The collected stamp beside it (`page.tsx:265`) renders
through `RotatingTime`, one frame of whose seven-zone rotation is `America/Denver`.

**So a Denver reader between 18:00 and 23:59 MDT sees tomorrow's bucket above a stamp reading
their own evening**, and the stamp cannot say otherwise: it is time-of-day only, with no date
in any of the seven readings. That is the cost `DayTimeline.tsx:17-23` already states in its
own words — "the top band opens at 00:00Z, which is 6 PM the previous evening in Denver" —
arriving at the one place on the page where a UTC-dayed label and a zone-rotating stamp sit
next to each other.

**This is an instance of the item filed as section 1, not a new finding.** No invariant is
violated, both renderers are explicit about their zone handling, and the ruling section 1
owes — whether to write a `new Date()` invariant, and over what scope — is unchanged by it.
