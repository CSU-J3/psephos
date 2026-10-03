# R1: the first-load measure, the reads of 2026-10-02, and the second batch priced

**Status, 2026-10-02.** The rule's 7 pairs were read in full, passed, and are LINKED. The person list is read except for the second batch of 239 first-load pairs, which is PRICED and held for Corey. Nothing a page reads has changed: the views that count objects are read by nothing until the switch.

## What was ruled (Corey, 2026-10-02)

**The first brief: option (b), and the person pairs to readers first.**
- The 2026-10-01 check stands as a fail.
- The 63 bootstrap-only pairs become pairs whose run cannot be told. A fresh 20 from the 203 is read, and the 203 are linked only if it passes.
- The person pairs get the same three-lens read against the same bar.
  - All three readers pass: a candidate link.
  - Any reader shows two entries, or a better match: not linked.
  - Any other pair: to Corey with its reads.
  - Corey reads five candidates drawn at random before any is linked.
  - Pair 23 (93225) stays the duplicate `docs/gates.yaml` records.
- Then (c), (d) and (e) as ruled on 2026-09-30.

**The second brief, on the 259/7 correction below:**
- **1a.** Classify by the first-load test in `plan()`, with a test. The 259 join the person set.
- **1b.** The 7 later-poll pairs are read in full, in place of a draw, and linked only if all 7 pass.
- **1c.** The 20 read on 2026-10-01 count as reads of themselves under the same bar: the 18 unanimous passes are candidates, and n=3 and n=8 go to the split list.
- **1d.** The other 239 first-load pairs are a second batch, priced before it runs. Corey's five come from the unanimous candidates across every batch read.
- **2.** Price the second batch from the 24-pair read, with any cheaper discriminator that can be measured, and stop there.
- **3.** Ship tier 1: (c) for tier 1, (d), (e) through the visual checkpoint at 1440 and 390, then stop for Corey's word. Tier 2's links get their own dated note.

## The finding: 259 first-load pairs, not 63

**How the 63 was counted (2026-10-01).** A pair counted when both rows' `seen_at` equalled each other and the docket's earliest `seen_at`, compared as strings.

**Why that undercounts.** `seen_at` is not one value per run.
- A row held before R1 that has an A1 item carries its item's own `fetched_at`, seconds or minutes apart from its neighbours inside one run.
- A row without one carries its run's start (`scripts/backfill_seen_at.py`).
- So the strings matched only when neither row had an item and both were pinned to the docket's first run.

**Measured again (Turso, read-only), two ways that agree on every pair:**
- **The run clock, the rule's own.** A docket's first load wrote its lowest-id row. A same-run pair whose run lies inside that row's run bracket may have been held by the first load, so its run tells nothing. This is the test now in `plan()` (`cl_twins.pair_relation`, commit `9ef67e2`).
- **Id blocks.** `write_entries` writes one docket's rows for one run in one call, and `case_entries` ids are one AUTOINCREMENT. So a docket's first load is the unbroken block of its rows from its lowest id.
- **Both read 259 first-load pairs and 7 later-poll pairs**, the same pairs on each side. Every one of the 63 is among the 259.

| first-load pairs | pairs |
|---|---|
| counted by the 2026-10-01 string test (no item on either row) | 63 |
| missed: an item time on one row or both | 157 |
| missed: on a docket whose first rows the clock brackets across two runs | 39 |
| **in all** | **259** |

- **The 39 sit on five dockets** (71499795, 71982380, 72055344, 72333329, 73134260). Each first block opens with a few rows the clock brackets across two runs, then runs unbroken into the later run's pinned rows. So the first load was the later run.
- **Every first load was a whole-docket load.** On each of the 30 dockets holding a first-load pair, the first block holds months of entries pinned to one run:

| docket | first-load pairs | rows in the first load | their entry dates | that run began |
|---|---|---|---|---|
| 73133197 League of Women Voters of Massachusetts v. Trump | 30 | 363 | 2026-04-02 to 2026-09-25 | 2026-09-27T17:01Z |
| 72193752 United States v. Raffensperger | 24 | 217 | 2026-01-23 to 2026-07-01 | 2026-07-07T19:45Z |
| 72334676 United States v. Adams | 17 | 98 | 2026-02-26 to 2026-06-30 | 2026-07-07T19:45Z |
| 72110170 United States v. Thomas | 15 | 132 | 2026-01-06 to 2026-07-01 | 2026-07-04T02:08Z |
| 73141063 State of California v. Trump | 15 | 240 | 2026-04-03 to 2026-08-27 | 2026-09-27T17:01Z |
| 71453646 United States v. NH Secretary of State | 14 | 177 | 2025-09-25 to 2026-06-30 | 2026-07-03T09:33Z |
| 71453026 United States v. COMMONWEALTH OF PENNSYLVANIA | 13 | 198 | 2025-09-25 to 2026-07-07 | 2026-07-08T19:46Z |
| 71499795 League of Women Voters v. U.S. Department of Homeland Security | 12 | 189 (174 pinned to that run) | 2025-09-30 to 2026-06-29 | 2026-06-28T19:10Z |
| 74701505 State of California v. United States Postal Service | 12 | 195 | 2026-08-26 to 2026-09-17 | 2026-09-27T21:22Z |
| 71457474 United States v. Board Of Elections of the State of New York | 11 | 121 | 2025-09-25 to 2026-06-29 | 2026-07-04T19:43Z |
| 72055344 United States v. EVANS | 11 | 121 (120 pinned to that run) | 2025-12-18 to 2026-07-01 | 2026-07-06T10:09Z |
| 72110941 United States v. Fontes | 11 | 84 | 2026-01-06 to 2026-06-18 | 2026-08-16T01:44Z |
| 72021508 United States v. Griswold | 10 | 97 | 2025-12-11 to 2026-06-29 | 2026-07-04T02:08Z |
| 71363789 United States v. State of Oregon | 10 | 120 | 2025-09-16 to 2026-03-12 | 2026-08-16T01:44Z |
| 71982380 United States v. Hobbs | 8 | 106 (103 pinned to that run) | 2025-12-02 to 2026-07-02 | 2026-07-04T09:33Z |
| 72333329 United States v. CALDWELL | 7 | 146 (144 pinned to that run) | 2026-02-26 to 2026-07-02 | 2026-07-04T19:43Z |
| 71452580 United States v. Shirley Weber | 7 | 150 | 2025-09-25 to 2026-03-12 | 2026-08-16T01:44Z |
| 71980614 United States v. Hanzas | 4 | 93 | 2025-12-01 to 2026-06-30 | 2026-07-03T19:45Z |
| 71984384 United States v. Albence | 4 | 140 (139 pinned to that run) | 2025-12-02 to 2026-07-01 | 2026-07-06T10:09Z |
| 72053306 United States v. RAFFENSPERGER | 4 | 59 | 2025-12-18 to 2026-02-04 | 2026-07-07T19:45Z |
| 72054244 United States v. Matthews | 4 | 113 | 2025-12-18 to 2026-06-30 | 2026-07-08T08:12Z |
| 73218916 Common Cause v. U.S. Department of Justice | 3 | 67 (65 pinned to that run) | 2026-04-21 to 2026-06-22 | 2026-06-27T22:35Z |
| 72026664 United States v. Aguilar | 3 | 95 | 2025-12-11 to 2026-06-30 | 2026-07-03T19:45Z |
| 71982149 United States v. Oliver | 3 | 145 | 2025-12-02 to 2026-07-01 | 2026-07-04T19:43Z |
| 73131864 DSCC v. TRUMP | 2 | 250 (249 pinned to that run) | 2026-04-01 to 2026-09-23 | 2026-09-27T21:22Z |
| 72335259 United States v. Warner | 1 | 59 | 2026-02-26 to 2026-07-01 | 2026-07-04T09:33Z |
| 71980724 United States v. DeMarinis | 1 | 97 | 2025-12-01 to 2026-06-18 | 2026-07-05T02:40Z |
| 72023578 United States v. Nago | 1 | 88 | 2025-12-11 to 2026-04-27 | 2026-07-07T19:45Z |
| 73143746 NATIONAL ASSOCIATION FOR THE ADVANCEMENT OF COLORED PEOPLE v. DONALD J. TRUMP | 1 | 31 | 2026-04-03 to 2026-09-01 | 2026-09-27T21:22Z |
| 73134260 LEAGUE OF UNITED LATIN AMERICAN CITIZENS v. EXECUTIVE OFFICE OF THE PRESIDENT | 1 | 44 (37 pinned to that run) | 2026-04-02 to 2026-09-01 | 2026-09-28T05:33Z |

**The 7 later-poll pairs.** For every one, both CourtListener objects were created after the docket's previous load, so the poll's window bounds when the two appeared upstream: the premise the rule was built on. Four sit on 71499795, among them the D0's own sampled pairs of Jul 18 and Jul 20, where the rule's fingerprint came from.

| rows | docket | entry date | the poll began | the docket's previous load began | the two objects created | created apart |
|---|---|---|---|---|---|---|
| 5677/5689 | 71499795 | 2026-07-02 | 2026-07-03T19:09Z | 2026-06-29T17:18Z | 2026-07-02T06:04 and 2026-07-02T13:22 (Pacific) | 7h18m |
| 12886/12894 | 71499795 | 2026-07-07 | 2026-07-07T19:45Z | 2026-07-06T19:49Z | 2026-07-07T12:20 and 2026-07-07T12:30 (Pacific) | 0h10m |
| 17161/17167 | 71453646 | 2026-07-07 | 2026-07-08T19:46Z | 2026-07-07T10:01Z | 2026-07-07T11:21 and 2026-07-07T11:28 (Pacific) | 0h07m |
| 57249/57258 | 71499795 | 2026-07-18 | 2026-07-18T18:52Z | 2026-07-18T07:33Z | 2026-07-18T09:16 and 2026-07-18T09:25 (Pacific) | 0h09m |
| 67589/67651 | 71499795 | 2026-07-20 | 2026-07-21T08:12Z | 2026-07-20T19:31Z | 2026-07-20T15:21 and 2026-07-20T17:03 (Pacific) | 1h42m |
| 77471/77602 | 72333329 | 2026-07-23 | 2026-07-24T01:25Z | 2026-07-23T13:20Z | 2026-07-23T12:38 and 2026-07-23T13:46 (Pacific) | 1h08m |
| 87130/87131 | 71984384 | 2026-08-25 | 2026-08-25T18:23Z | 2026-08-20T00:32Z | 2026-08-25T10:08 and 2026-08-25T10:13 (Pacific) | 0h05m |

**The 2026-10-01 sample: all 20 were first-load pairs, and none of the 7 was drawn.** In effect it was a random 20 of the first-load class, and on that class it failed the bar.

**How far apart CourtListener created each pair's two objects, by class:**

| created apart | first-load | of them, counted by the string test | later poll |
|---|---|---|---|
| <=15 min | 56 | 5 | 4 |
| 15 min-6 h | 91 | 13 | 2 |
| 6-48 h | 48 | 18 | 1 |
| >48 h | 64 | 27 | 0 |

## The rule's 7: read in full, PASS, and LINKED

- **Read** by three independent readers per pair, one lens each, the 2026-10-01 lens prompts word for word, against the same bar.
- **All 21 reads were yes, and none named a better match.**
- **Recorded** in `config/entry_links.yaml` as a full read (`full: true`, pool 7), `result: pass`. The 2026-10-01 sample moved to `checks_before`.
- **Linked** by `python -m scripts.link_entry_twins --apply` at 2026-10-02T21:37:08Z: "linked 7 of 7, refolded, committed". A second `--apply` links 0 of 0, so the read still covers the pool.
  - Before: 0 tier-2 links, 6,366 entries in `record_entries`, 216 of 2,976 litigation items folded.
  - After: 7 links, 6,359 entries, 221 items folded. Two of the pairs held an item on one row only.
- **Nothing a page reads moved.** `record_entries` and `record_items` are read by nothing until the switch, and the 7 get their own dated note when it ships.

| n | rows | docket | entry date | kind | identity | alternative | clocks |
|---|---|---|---|---|---|---|---|
| 1 | 5677/5689 | 71499795 | 2026-07-02 | type_only | yes | yes | yes |
| 2 | 12886/12894 | 71499795 | 2026-07-07 | short_long | yes | yes | yes |
| 3 | 17161/17167 | 71453646 | 2026-07-07 | short_long | yes | yes | yes |
| 4 | 57249/57258 | 71499795 | 2026-07-18 | type_only | yes | yes | yes |
| 5 | 67589/67651 | 71499795 | 2026-07-20 | short_long | yes | yes | yes |
| 6 | 77471/77602 | 72333329 | 2026-07-23 | short_long | yes | yes | yes |
| 7 | 87130/87131 | 71984384 | 2026-08-25 | short_long | yes | yes | yes |

## The person pairs: 283, and where each stands

| batch | pairs | candidates (unanimous) | for Corey (split) | not linked |
|---|---|---|---|---|
| 2026-10-01 sample, counted as reads of themselves (ruling 1c) | 20 | 18 | 2 (n=3, n=8) | 0 |
| 2026-10-02 first batch: the 23 laid out plus pair 24 | 24 | 19 | 4 | 0 |
| second batch: the other first-load pairs | 239 | priced, held for Corey | | |

- **Candidates so far: 37.** None is linked and nothing is listed under `asserted`. Corey's five are drawn from the unanimous candidates across every batch read, so they wait for his ruling on the second batch.
- **Corey's split list so far: 6**, laid out below.
- **No reader of any batch has shown a pair to be two entries or named a better match.**
- **Pair 23 is outside the outcome**, as ruled: it stays the duplicate `docs/gates.yaml` records. Its three readers passed it.
  - **Found 2026-10-03: these reads are not independent of that verdict.** The workflow harness handed each reader Corey's brief, which said 93225 stays the duplicate, and two of the three cited it (`r1-batching-control-2026-10-03.md`). No other pair of this batch was named in the brief.
- **Pair 24 arrived after 2026-10-01.** United States v. Albence (D. Del., 71984384), 2026-09-29, cross-run: the RECAP document object "Motion Hearing" against the clerk's minute entry for that day's motion hearing, which CourtListener created on Oct 1. It is not the refused DSCC pair, which the plan files under `refused` before the person list.

**How the first batch was read.** The same three lenses and bar. The brief above the lens prompts says these are pairs the rule does not link. Each reader read one file, its pair plus every object on that docket from the day before to the day after, dumped from Turso the way the 2026-10-01 check dumped its 20.
- **One shape fix since, for the 7 and any later batch: the dump now carries `seen_by`.** All three readers of pair 1 flagged row 505's `seen_at` (Jun 28) as earlier than its own object (Jun 29). It is the lower bound of a range that ends Jun 29 17:18Z, and the reader could not see the upper bound. It bore on no verdict.

| n | rows | docket | date | relation | kind | identity | alternative | clocks | outcome |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 505/577 | 71499795 | 2026-06-29 | undetermined | short_long | yes | yes | yes | candidate |
| 2 | 4059/12693 | 73218916 | 2026-07-01 | cross-run | short_long | yes | yes | yes | candidate |
| 3 | 7714/17501 | 71982149 | 2026-07-01 | cross-run | short_long | yes | yes | yes | candidate |
| 4 | 8868/8873 | 72156765 | 2026-02-05 | undetermined | short_long | yes | yes | uncertain | for Corey |
| 5 | 8869/8871 | 72156765 | 2026-01-16 | undetermined | short_long | yes | yes | uncertain | for Corey |
| 6 | 8870/8872 | 72156765 | 2026-06-16 | undetermined | short_long | yes | yes | yes | candidate |
| 7 | 10510/10511 | 71984384 | 2026-02-11 | undetermined | short_long | yes | yes | yes | candidate |
| 8 | 27277/29042 | 71499795 | 2026-07-11 | cross-run | type_only | yes | yes | yes | candidate |
| 9 | 27574/37917 | 72021508 | 2026-07-10 | cross-run | short_long | yes | yes | yes | candidate |
| 10 | 54722/54724 | 72333329 | 2026-07-15 | undetermined | short_long | yes | yes | yes | candidate |
| 11 | 68098/68128 | 72333329 | 2026-07-16 | undetermined | short_long | yes | yes | yes | candidate |
| 12 | 81820/82168 | 71982380 | 2026-08-04 | cross-run | short_long | yes | yes | yes | candidate |
| 13 | 87390/87543 | 71499795 | 2026-08-26 | cross-run | short_long | yes | yes | yes | candidate |
| 14 | 88676/88680 | 73544809 | 2026-09-04 | cross-run | long_twin_eq | yes | yes | yes | candidate |
| 15 | 89060/89682 | 73582123 | 2026-09-09 | cross-run | long_twin_eq | yes | yes | uncertain | for Corey |
| 16 | 89061/89683 | 73582123 | 2026-09-09 | cross-run | long_twin_eq | yes | yes | yes | candidate |
| 17 | 89874/90160 | 74687843 | 2026-09-15 | undetermined | long_twin_eq | yes | yes | yes | candidate |
| 18 | 89883/90093 | 73582123 | 2026-09-15 | undetermined | long_twin_eq | yes | yes | yes | candidate |
| 19 | 90158/90178 | 73582123 | 2026-09-15 | undetermined | long_twin_eq | yes | yes | yes | candidate |
| 20 | 90159/90179 | 73582123 | 2026-09-16 | undetermined | long_twin_eq | yes | yes | yes | candidate |
| 21 | 90205/91351 | 73582123 | 2026-09-17 | cross-run | long_twin_eq | yes | yes | yes | candidate |
| 22 | 91090/91356 | 73582123 | 2026-09-23 | cross-run | long_twin_eq | yes | uncertain | uncertain | for Corey |
| 23 | 93145/93225 | 71499795 | 2026-09-29 | cross-run | short_long | yes | yes | yes | gates.yaml duplicate (ruled) |
| 24 | 93146/93298 | 71984384 | 2026-09-29 | cross-run | short_long | yes | yes | yes | candidate |

### Corey's split list

**n=3 and n=8 of the 2026-10-01 sample** are laid out with all three reads in `docs/findings/r1-reader-check-2026-10-01.md`: rows 13595/13771 (N.D. Ga.) and 5419/5457 (D.N.H.), each read yes, yes and uncertain on the clocks lens.

#### 4. United States v. Koski (Eastern District of Virginia), 2026-02-05: rows 8868/8873, undetermined

- **Row 8868**, object 452851121, the twin, would fold: Notice of Correction
  - entry number None, created 2026-02-05T10:55:51.912910-08:00, time filed None, text from document
- **Row 8873**, object 452844429, the entry, kept: Notice of Correction re 18, 19, 20 : Documents filed as PDF fillable forms. Filing attorney reminded to only upload standard PDFs. Clerk has corrected. No further action needed. (jenjones, )
  - entry number None, created 2026-02-05T10:12:11.687335-08:00, time filed None, text from entry
- **identity, yes:** Identity lens. The short form is 452851121, row 8868: "Notice of Correction", unnumbered, with its text taken from its document. The long form is 452844429, row 8873: "Notice of Correction re 18, 19, 20 : Documents filed as PDF fillable forms. Filing attorney reminded to only upload standard PDFs. Clerk has corrected. No further action needed. (jenjones, )", also unnumbered. 1. The short form is exactly the event name that opens the long docket text. It names no document, party or act that the long form does not, and it contradicts nothing in it. 2. Both are on the same docket (United States v. Koski, E.D. Va.) and the same day, 2026-02-05. They were created 43 minutes apart, at 10:12:11 and 10:55:51 PT. Both are unnumbered, which is what a clerk's text-only notice would be. 3. The short form has no rival. The window from 02-04 to 02-06 holds no other Notice of Correction, and no other object at all on 02-05 or 02-06. The four objects on 02-04 are pro hac vice motions 18 to 21, a different kind of filing. 4. Other entries back up the long form's subject. Entries 18, 19 and 20, and not 21, carry "(Main Document N replaced on 2/5/2026) (jenjones, )". That is the same clerk, the same day and the same three documents, which points to a single correction event. A docket clerk would read these two texts as one minute entry, and no other object in the window fits the short form better. Remaining risk: the court could have docketed a second notice that same day that CourtListener holds in neither form. Nothing in the file suggests one. Two notes outside this lens, for the other readers: neither object has a time_filed, so the short object does not show the time_filed that the cl_twins.py docstring describes as typical of a short object. Also, the long form lacks the "(Entered: ...)" stamp that the numbered entries carry.
- **alternative, yes:** Lens: alternative match. Pair 4 is United States v. Koski, E.D. Va., docket 72156765, day 2026-02-05. The window (2026-02-04 to 2026-02-06) holds six objects: - Four numbered entries, all motions to appear pro hac vice filed 2/4: #18 (452672252), #19 (452676748), #20 (452681283) and #21 (452681284). - The pair's two unnumbered 2/5 objects. - Nothing on 2/6. The short form 'Notice of Correction' (452851121) cannot describe a pro hac vice motion. Its content stems (notic, corre) appear in none of the four motions, so under strict-B it would pair with no other object even across all three days. Entries #18-#20 are what the notice is about ('re 18, 19, 20'), not rival descriptions of it. Each carries '(Main Document N replaced on 2/5/2026) (jenjones, )', with the notice's own clerk initials. #21, the one motion the notice leaves out, has no replacement note. So the window shows one correction and one notice. There is no second notice of correction, no minute entry with a separate order, and no other 2/5 object. The long form 452844429 is the only entry in the window the short form can describe, and the short form is the long form's exact event-type heading. I found no better match. Outside this lens, for the provenance readers: - Both objects are unnumbered, and neither carries a time_filed. - The long object was created first, at 18:12:11Z (11:12 AM MST). The short one followed 43m40s later, at 18:55:51Z (11:55 AM MST). - That is unlike the fingerprint in the cl_twins.py docstring, where the short object carries a time_filed. - Both psephos rows share one seen_at: 2026-07-05T02:40:23Z (8:40 PM MDT on 07-04). If the short form were a separate second notice that CourtListener holds only in short form, its long form would be missing from the window. No such long form is there, and this lens finds no other entry the short form could belong to.
- **clocks, uncertain:** Lens: clocks and shape. Pair 4 is United States v. Koski, E.D. Va., docket 72156765, entry date 2026-02-05. The two objects: - Twin 452851121 (row 8868, "Notice of Correction"): entry_number null, time_filed null, desc_source document, twin_of null. date_created 2026-02-05T10:55:51.913-08:00, which is 18:55:51Z (11:55 AM MST). - Entry 452844429 (row 8873, "Notice of Correction re 18, 19, 20 ..."): entry_number null, time_filed null, desc_source entry, twin_of null. date_created 2026-02-05T10:12:11.687-08:00, which is 18:12:11Z (11:12 AM MST). - The gap is 43m40s. The long form was created first, and both were created on the entry date. What fits one entry seen twice: - The short text comes from the document and the long text from the entry, which is the twin signature. - Both are unnumbered, as a clerk's text-only notice would be. - Neither object is already another object's twin. - These are the only correction objects in the 2/4 to 2/6 window. The other four objects are numbered pro hac vice motions 18 to 21, created on 2/4. None of them is a rival match, so there is no better match. - The window shows one set of corrections on 2/5. Entries 18, 19 and 20 each say "Main Document replaced on 2/5/2026 (jenjones)" and entry 21 has no such note. That matches a single notice "re 18, 19, 20 (jenjones)". Why the clocks don't settle it: - A gap of 43m40s means two separate arrivals, not one load. For comparison, the window's #20 and #21 objects, which came in one load, are 80 ms apart (18:12:05.782Z and 18:12:05.862Z on 2/4). - The short form is the later object. - time_filed is null on both objects and on all six objects in the window. The fingerprint in the cl_twins.py docstring says the short object carries a time_filed, so that check can't confirm anything here. - Both objects are unnumbered, so no entry_number links this short form to this long form. A second clerk's notice entered about 40 minutes later, and held only in its short form, would have the same clocks and the same shape. The clocks fit one entry but don't rule out a second notice, so the verdict is uncertain.

#### 5. United States v. Koski (Eastern District of Virginia), 2026-01-16: rows 8869/8871, undetermined

- **Row 8869**, object 451291760, the twin, would fold: Initial Case Assignment
  - entry number None, created 2026-01-23T05:49:47.439504-08:00, time filed None, text from document
- **Row 8871**, object 450807435, the entry, kept: Initial Case Assignment to District Judge Roderick C. Young. (adun, )
  - entry number None, created 2026-01-20T07:53:08.063185-08:00, time filed None, text from entry
- **identity, yes:** IDENTITY lens, pair 5 (case 72156765, United States v. Koski, E.D. Va.): yes, these are one minute entry. The short form (twin 451291760) reads "Initial Case Assignment". That is the CM/ECF event name of the long form (entry 450807435), "Initial Case Assignment to District Judge Roderick C. Young. (adun, )", and its first three words exactly. Both objects are unnumbered (entry_number null), have no time_filed, are dated 2026-01-16 and sit on the same docket. The short form names no motion, party, document or judge that the long form leaves out. The long form only adds the judge's name and the clerk's initials. An initial case assignment happens once, when the case opens. The window from 2026-01-15 to 2026-01-17 holds only two other objects: the Complaint (#1, 450666528) and the Proposed Summons re the Complaint (#2, 450666529). The short form cannot describe either one, so nothing in the window is a better match. The provenance fits one entry reaching CourtListener twice. The short form's text came from a document (desc_source 'document') and its object was created 2026-01-23, three days after the long form's object (2026-01-20). Its entry was unnumbered, so CourtListener had no number to merge the two on. One caveat: some districts docket a separate initial assignment to a magistrate judge, and a bare "Initial Case Assignment" could also name that. No such object appears anywhere in the window, so nothing in the file points to a rival event.
- **alternative, yes:** Lens: alternative match. The window (2026-01-15 to 2026-01-17) on United States v. Koski (E.D. Va., case 72156765) holds four CourtListener objects, all dated 2026-01-16: - 450666528, #1: the Complaint. - 450666529, #2: the Proposed Summons re 1. - 450807435, unnumbered: the pair's long form, "Initial Case Assignment to District Judge Roderick C. Young. (adun, )". - 451291760, unnumbered: the short form, "Initial Case Assignment". Every content word of the short form (initial, case, assignment) appears only in the long form. Neither numbered entry is a case assignment. The window has no other unnumbered object and no second assignment-type entry, such as a magistrate referral or a reassignment, so there is nothing the short form could describe instead. That is consistent with cl_twins.strict_b keeping this edge as unique at both ends. The long form is the only entry in the window the short form can describe, so under this lens the answer is yes, with no better match. Outside my lens, for the other readers and Corey (these do not change this verdict): - Both objects are unnumbered, and neither has a time_filed. In the D0 fingerprint, the short object carries a time_filed. - They were created about 2 days 22 hours apart, not minutes apart: the long form at 2026-01-20T15:53:08Z (8:53 AM MST) and the short form at 2026-01-23T13:49:47Z (6:49 AM MST). - Both psephos rows (8869, 8871) share one seen_at, 2026-07-05T02:40:23Z (8:40 PM MDT on Jul 4). That is why the relation is undetermined.
- **clocks, uncertain:** Lens: clocks and shape. Pair 5 is US v. Koski, E.D. Va., docket 72156765, entry_at 2026-01-16 (a Friday). Short form 451291760, 'Initial Case Assignment': entry_number null, time_filed null, desc_source document, date_created 2026-01-23T05:49:47.44-08:00 = 13:49:47Z (6:49 AM MST, Fri Jan 23). Long form 450807435, 'Initial Case Assignment to District Judge Roderick C. Young. (adun, )': entry_number null, time_filed null, desc_source entry, date_created 2026-01-20T07:53:08.06-08:00 = 15:53:08Z (8:53 AM MST, Tue Jan 20). The two were created 69h57m apart (2d 21h 57m), and the short form is the later one. Fits one entry seen twice: - Same entry_at. - The text sources run in the twin direction: the short form's text comes from its document, the long form's from the entry. - Neither object is any object's twin_of. - The window has no rival object. It holds only #1 Complaint and #2 Proposed Summons, both numbered, of other types, and created in one load at 01:32:03.840Z and .909Z on Jan 17 (6:32 PM MST Jan 16), 69 ms apart. - Both creation clocks come 4 and 7 days after the shared filing date, so they record when CourtListener captured each object, not when anything was filed. The long form's clock falls on the first business day after the Friday filing (Jan 19 was MLK Day), which fits the clerk making the one assignment entry then. Does not fit: - The gap is days, not the minutes of the single docket-report load the D0 fingerprint describes (cl_twins.py docstring). - That fingerprint also has the short object carrying a time_filed and the long form numbered. Here time_filed and entry_number are null on both objects. - With both objects unnumbered, no entry number can confirm or contradict the pair. A second, separate assignment entry back-dated to the filing date would also be unnumbered, and if CourtListener held it only in short form it would look exactly like this short form. - The long form lacks the '(Entered: ...)' stamp that #1 and #2 carry, so the two objects arrived by different capture paths about 70 hours apart. That fits one unnumbered entry captured twice and never merged, but the file records no provenance that could separate it from two entries. - Both psephos rows carry one seen_at, 2026-07-05T02:40:23.72Z (8:40 PM MDT Jul 4), the bootstrap. That tells nothing about which run held which row. Verdict: by the lens's own measure, a creation gap of days leans toward two filings, yet nothing in the window shows a second filing. The evidence does not settle it, so the verdict is uncertain. The window holds no better match for the short form.

#### 15. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-09: rows 89060/89682, cross-run

- **Row 89682**, object 477827680, the twin, would fold: HARD COPY RECEIVED from Appellant USA - Joint Appendix. Copies: 4. Volume 2 ONLY (EAF) [Entered: 09/09/2026 03:31 PM]
  - entry number 40, created 2026-09-14T05:20:09.948078-07:00, time filed None, text from entry
- **Row 89060**, object 477374891, the entry, kept: HARD COPY RECEIVED from Appellant USA - Joint Appendix. Copies: 4. Volume 2 ONLY (EAF)
  - entry number None, created 2026-09-09T10:15:41.966988-07:00, time filed None, text from entry
- **identity, yes:** IDENTITY lens. Kind long_twin_eq: the twin is 477827680 (numbered entry 40) and the entry is 477374891 (unnumbered). Strip the '[Entered: 09/09/2026 03:31 PM]' stamp, as cl_twins.ntext does, and the two texts are word for word the same: 'HARD COPY RECEIVED from Appellant USA - Joint Appendix. Copies: 4. Volume 2 ONLY (EAF)'. A docket clerk would read them as one event. Both record the same kind of entry (the clerk's receipt of paper copies), for the same document (Joint Appendix, Volume 2 only), with the same count (4), from the same party (Appellant USA), docketed by the same clerk (EAF), on the same day (both rows' entry_at is 2026-09-09, matching the stamp's date). The twin adds only the entered stamp. It names no act the other text lacks. BETTER MATCH: none. The other objects in the 09/08 to 09/10 window are: entry 39 (paper copies of the Brief, 7 copies, KEL); entry 38 (the electronic JA, Volumes I and II, filed 09/08); and the clerk's TEXT ORDER for Volume I copies (entry 41 and its own unnumbered twin 477406289). None of them records receipt of JA Volume 2. The numbered docket runs 39, 40, 41 on 09/09 with only one JA paper-copy entry, so this text has no second live entry it could describe. FLAG, for the timing lens and Corey (this does not change the identity read): 477374891 was created 2026-09-09 17:15:41Z (11:15 AM MDT). That is about 2h15m BEFORE entry 40's stamp of 03:31 PM ET, which is 19:31Z (1:31 PM MDT). The stamps are Eastern time: entries 36, 37 and 38 arrived 1 to 2 minutes after their ET stamps. Elsewhere in the window, the unnumbered TEXT ORDER arrived at 19:34:39Z (1:34 PM MDT), about 1.5 minutes after entry 41's stamp. So this unnumbered object came before the docket's stamp for the entry it matches. Its arrival instead falls 3 minutes after entry 39's 1:12 PM ET stamp, 17:12Z (11:12 AM MDT). Two explanations fit, and the file can't tell them apart: (1) the receipt was docketed around 1:15 PM ET, then re-entered or re-stamped at 3:31 PM; (2) CourtListener replaced this object's text later. Under either one, the text the object carries now records the same receipt as entry 40. A second, smaller oddity: row 89682 was first held at 2026-09-12 04:40Z (09-11 10:40 PM MDT), but its object 477827680 has date_created 2026-09-14 12:20Z (6:20 AM MDT). The id walk probably attached that id later. The relation is cross-run: the rows were first held at 09-09 21:01Z (3:01 PM MDT) and 09-12 04:40Z.
- **alternative, yes:** Lens: alternative match. The pair is a long_twin_eq, so the twin is 477827680 (entry #40) and it would be linked to 477374891 (unnumbered). Once ntext strips the CM/ECF stamp "[Entered: 09/09/2026 03:31 PM]", the two texts are identical, and they carry specific details: Joint Appendix, Copies: 4, Volume 2 ONLY, clerk EAF. I checked all eight objects in the 09-08 to 09-10 window: - #36 (appearance), #37 (electronic brief) and #38 (electronic JA Vol I and II, filed 09-08) are different events on a different day. - #39 (477382955) is the only other HARD COPY RECEIVED entry. It is the Brief, 7 copies, clerk KEL, and every one of those details contradicts the pair's text. It is also held as its own object (row 89058), which this link does not touch. - #41 (477827681) and the unnumbered 477406289 are the clerk's text order for Volume I hard copies. They are each other's counterpart, not candidates here. The numbered entries run #36 to #41 with no gap, so the docket holds one JA Vol 2 receipt. Under strict_b each end has exactly one partner; #39's text is neither equal to nor a prefix of the pair's. No object in the window matches either side as well or better. One timing anomaly for the timing reader and Corey (it does not point to an alternative match): 477374891 was created 2026-09-09 17:15:41Z (11:15 AM MDT). That is about 2h15m BEFORE #40's stamp, 3:31 PM ET = 19:31Z (1:31 PM MDT), and about 4 min after #39's stamp, 1:12 PM ET = 17:12Z (11:12 AM MDT). I read the stamps as ET because #36, #37, #38 and 477406289 were each created within 1 to 2 min of their stamps on that reading. By time alone the object sits nearer #39. But its text is #40's, psephos has held it with that text since 2026-09-09 21:01Z (3:01 PM MDT), and nothing in the file shows it ever carried #39's text. It may be an earlier docketing of the same receipt that was redone at 3:31 PM; clerk EAF also edited #38 that day to specify volumes. Either way #39 keeps its own object, so the link would fold no distinct entry. Outside this lens: - Row 89682 (#40) was seen 2026-09-12 04:40Z, before its object's date_created of 2026-09-14 12:20Z, which suggests the object was re-created upstream and the id was re-attached. - Per the file's twin/entry fields, the numbered #40 would fold into the unnumbered object.
- **clocks, uncertain:** CLOCKS AND SHAPE, n=15 (Third Circuit docket 73582123, day 2026-09-09). The shape fits one entry seen twice, but the clocks do not, so the verdict is uncertain. SHAPE FITS. The entry 477374891 has no number and the twin 477827680 is #40. Both have desc_source 'entry' and time_filed null, and neither is anyone's twin_of. Once #40's stamp '[Entered: 09/09/2026 03:31 PM]' is stripped, the two texts are identical: same clerk initials (EAF), same 'Copies: 4. Volume 2 ONLY'. The window's other pair has the same shape: 477406289 (no number) and #41 (477827681). The numbered entries #36 to #41 run without a gap and hold only one Joint Appendix hard-copy receipt, so the window shows no second numbered filing the unnumbered object could be. #40 was created five days late (2026-09-14T12:20:09.948Z, 6:20:09 AM MDT), but that is a batch reload, not a later filing: #41 was created 52 ms after it (12:20:10.000Z). CLOCKS DO NOT FIT. The window shows the 'Entered' stamps are court-local Eastern time: - #36 was created within about 1m22s of its stamp, #37 within 57s, #38 within 1m50s. - 477406289 was created at 19:34:39Z (1:34:39 PM MDT), about 1m39s after #41's 3:33 PM ET stamp (19:33Z, 1:33 PM MDT). - The entry 477374891 was created at 2026-09-09T17:15:41.97Z (11:15:41 AM MDT). That is about 2h15m BEFORE #40's 3:31 PM ET stamp (19:31Z, 1:31 PM MDT). An object cannot be a sighting of an entry that had not yet been entered. - Its creation falls about 3 to 4 minutes after #39's 1:12 PM ET stamp (17:12Z, 11:12 AM MDT), the same lag the window's other notice-born objects show. But #39 is a different filing (Brief, Copies: 7, KEL) with its own numbered object, 477382955. - No unnumbered object was created near 3:31 PM ET, where a sighting of #40 would be expected. So either CourtListener wrote #40's text over an object first created for something else, or the receipt was docketed twice (about 1:15 PM ET, then again at 3:31 PM ET). The file cannot tell which. SECOND ANOMALY. The twin's row 89682 was seen at 2026-09-12T04:40:23Z (Sep 11, 10:40:23 PM MDT), about 2.3 days before its object 477827680 was created. That row was first served on an earlier object and tied to this one later. WHAT THIS MEANS FOR A LINK. psephos first held 477374891 (row 89060) at 21:01:13Z (3:01:13 PM MDT), after #40 was entered, and only ever with this text. So a link would not fold any distinct current entry the file shows. BETTER MATCH: none. No other object in the window fits #40's text better than 477374891; #39 differs in document, copy count and clerk initials.

#### 22. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-23: rows 91090/91356, cross-run

- **Row 91356**, object 479305491, the twin, would fold: Appellees Common Cause, Joel Dickson, Trisha Kent, League of Women Voters of Pennsylvania, Nicholas Maston, Gregory Perry, Lior Sternfeld, Todd Thatcher and John Thompson verbally granted an extension of time to file brief until 10/22/2026 pursuant to 3d Cir. L.A.R. 31.4. (EAF) [Entered: 09/23/2026 01:43 PM]
  - entry number 54, created 2026-09-24T12:05:52.426993-07:00, time filed None, text from entry
- **Row 91090**, object 479082481, the entry, kept: Appellees Common Cause, Joel Dickson, Trisha Kent, League of Women Voters of Pennsylvania, Nicholas Maston, Gregory Perry, Lior Sternfeld, Todd Thatcher and John Thompson verbally granted an extension of time to file brief until 10/22/2026 pursuant to 3d Cir. L.A.R. 31.4. (EAF)
  - entry number None, created 2026-09-23T09:23:19.626293-07:00, time filed None, text from entry
- **identity, yes:** Identity lens, reading the texts only: yes. The twin (479305491, entry 54) and the entry (479082481, unnumbered, no document URL) match word for word once the twin's CM/ECF stamp '[Entered: 09/23/2026 01:43 PM]' is removed. ntext strips that stamp, which is why the pair is long_twin_eq. Both texts record the same clerk action: - a verbal grant of an extension of time to file a brief, to 10/22/2026, under 3d Cir. L.A.R. 31.4 - for the same nine appellees: Common Cause, Joel Dickson, Trisha Kent, League of Women Voters of Pennsylvania, Nicholas Maston, Gregory Perry, Lior Sternfeld, Todd Thatcher and John Thompson - with the same clerk initials (EAF), on the same day (2026-09-23). The stamp gives a time, not an action, and it agrees with entry_at. Neither text names anything the other does not do. No better match. The window holds three more verbal extensions to 10/22/2026 on the same day: - 51: Secretary Commonwealth of Pennsylvania, MCW, entered 12:22 PM - 52: NAACP Pennsylvania State Conference, NAACP and Stacey Taylor, EAF, 1:24 PM - 53: Mike Crossey and Pennsylvania Alliance for Retired Americans, EAF, 1:36 PM They have the same wording but name different appellees. In this run of near-identical entries, the party list is the only thing that tells them apart, and it matches 54 alone. Outside this lens, a note for whoever reads the timing. The unnumbered object's date_created is 2026-09-23T16:23:19Z (10:23 AM MDT). The court's stamps are probably Eastern, its local time. If so, the object was created: - about 1 minute after entry 51 was entered (12:22 PM ET = 16:22Z, 10:22 AM MDT) - about 80 minutes before entry 54 was entered (1:43 PM ET = 17:43Z, 11:43 AM MDT). An object cannot carry 54's text before 54 exists, so CourtListener probably rewrote its description after creating it. One explanation fits both facts: a single unnumbered object reused by each of the day's notices in turn (51, then 52, 53 and 54). That would account for the timing, and for there being only one unnumbered object beside four same-form numbered entries. The four numbered entries (51 to 54) were all created together at 2026-09-24T19:05:52Z (1:05 PM MDT), in one docket load. psephos first held the unnumbered object as row 91090 at 2026-09-23T21:28:48Z (3:28 PM MDT). That is after 54 was entered, and the row already carried 54's text. So the two texts this lens reads describe one minute entry. The anomaly raises two separate points: - Durability: CourtListener could rewrite the unnumbered object's text again. - Direction: the computed twin is the numbered, document-bearing 54 and the entry is the unnumbered object. So the link as computed folds 54's item into the unnumbered object's item, not the other way round.
- **alternative, uncertain:** The window holds five objects, all dated 2026-09-23. Numbered entries 51 to 54 run consecutively and are the same kind of entry: appellees verbally granted an extension to file a brief until 10/22/2026 under 3d Cir. L.A.R. 31.4. Each one is for a different group of appellees: - 51 (479305486): the Secretary, clerk MCW, entered 12:22 PM - 52 (479305488): NAACP PA State Conference, NAACP and Stacey Taylor, clerk EAF, entered 1:24 PM - 53 (479305489): Mike Crossey and PA Alliance for Retired Americans, clerk EAF, entered 1:36 PM - 54 (479305491): Common Cause and eight named appellees, clerk EAF, entered 1:43 PM The unnumbered object 479082481 carries 54's text word for word, minus the [Entered:] stamp. It names the same nine appellees and the same clerk initials. No other entry in the window fits that text: 51 to 53 name different parties, and 51 has a different clerk. So there is no alternative match by text, and better_match is null. That is why this is not a 'no'. It is not a 'yes' because of a timestamp the file does not explain. 479082481 was created at 2026-09-23T09:23:19-07:00, which is 16:23:19Z (10:23 AM MDT). Reading the Third Circuit's stamps as Eastern time: - That is about one minute after entry 51 was entered (12:22 PM EDT = 16:22Z, 10:22 AM MDT). - It is about 80 minutes before entry 54 was entered (1:43 PM EDT = 17:43Z, 11:43 AM MDT). When the object was created, entry 51 was the only entry on the docket that day, so the object cannot have been created as a record of 54. The likeliest explanation is that CourtListener created it from 51's notice. It then reused this one unnumbered object as each notice of the same kind arrived, rewriting its text each time. It ended on 54's text, the day's last notice at 1:43 PM, before psephos first held it at 21:28:48Z (3:28 PM MDT). Numbered entries 51 to 54 were all created together on 09-24 at 19:05:52Z (1:05 PM MDT). So the object's origin points to 51 (479305486), while its text fits only 54. As held today, linking would not fold a distinct entry into another. 51 to 53 keep their own rows (91353 to 91355), and the page would only lose a duplicate of 54. But this object behaves like a reused container. The link would fold numbered 54, the twin that carries the document URL, into it. If CourtListener rewrites the object again, 54 could disappear behind the new text. Corey should see this pair.
- **clocks, uncertain:** Lens: clocks and shape. Verdict: uncertain. The shape rules out two separate filings, but the clocks say the unnumbered object was not created as a sighting of #54. Shape, which fits one entry: - 479082481 has no entry number. 479305491 is #54. - Both have desc_source 'entry', so neither is a RECAP document object. time_filed is null on both. twin_of is null on every object in the window. - The docket lists four entries for 2026-09-23, #51 to #54, each for a different appellee group: the Secretary (MCW), NAACP, Crossey/PARA and Common Cause. - That gives exactly one Common Cause entry and exactly one unnumbered object, so there is no fifth filing for 479082481 to be. The time gap does not mean a second filing: - 479082481 was created 2026-09-23T09:23:19.626-07:00, which is 16:23:19Z (10:23 AM MDT). - #54 was created 2026-09-24T12:05:52.427-07:00, which is 19:05:52Z (1:05 PM MDT). That is about 26h42m later. - #54 came in one batch with #51 (.274), #52 (.326) and #53 (.378), all within 0.153 s. That is one pull of the whole day's docket, not a new filing. The clocks do not fit "#54 seen twice": - 479082481 was created about 80 minutes BEFORE #54's own stamp, [Entered: 09/23/2026 01:43 PM]. The Third Circuit stamps in Eastern time, so that is 17:43Z (11:43 AM MDT). - It was created 20 to 80 seconds after #51's stamp, [Entered: 12:22 PM], which is 16:22Z (10:22 AM MDT). - Eastern is the only US zone where the object comes after any of the four entries. Read in any zone further west, all four entries come after its creation. So its creation lines up with #51. - Most likely, CourtListener created this unnumbered object for #51 and later overwrote its text with #54's: Common Cause, clerk EAF. That happened before psephos first read it at 2026-09-23T21:28:48Z (3:28 PM MDT). - The file has no history of the object's text, so this cannot be confirmed. What a link would do: - Both objects now carry #54's text. They match except for the [Entered] stamp. - #51 is held separately as 479305486 (row 91353), so a link would not hide #51. - Still, the object was created for one entry and now carries another's text. This lens cannot settle that, so the pair should go to Corey. Better match: none. - The short form here is the twin's text, which is #54's. No other object in the window fits it: #51 to #53 name other appellees. - 479305486 (#51) fits 479082481 by creation time only, not by text, so I do not name it.

### Pair 24, laid out (new since 2026-10-01)

- **Row 93146**, object 479786124, the twin, would fold: Motion Hearing
  - entry number None, created 2026-09-29T11:14:44.341475-07:00, time filed 13:50:59, text from document
- **Row 93298**, object 480178800, the entry, kept: Minute Entry for proceedings held before Judge Richard G. Andrews - Motion Hearing held on 9/29/2026. Local counsel present for Plaintiff: D. Steinberg. Local counsel present for Defendant Albence: K. Burton, R. Gibson. Local counsel present for Intervenor Defendants Lowery and Jennings: M. Billion. Local counsel present for Intervenor Defendants Latin American Community Center, La Esperanza, Delaware Coalition Against Domestic Violence, and Matthews: A. Bernstein. The court heard arguments from both sides on the motion for production of records (D.I. 3 ) and motions to dismiss (D.I.s 33, 36, and 39 ). The court took the motions under advisement. (Court Reporter Heather Triozzi.) (aas)
  - entry number None, created 2026-10-01T11:40:20.278606-07:00, time filed None, text from entry

## The second batch, priced

**What the first batch cost:** 72 reads, **5,982,479 tokens** and **18m03s** of wall time, 83,090 tokens a read. The rule's 7 cost 1,704,187 tokens and 7m04s for 21 reads (81,152 a read).

**The second batch at that rate: 239 pairs, 717 reads, about 59.6 million tokens and 2h59m of wall time.**

- **At the 2026-10-01 run's rate it is about 50.5 million tokens and 34m06s.** That run made 60 reads for 4,223,279 tokens in 2m51s, 70,388 a read, with the same model, lenses and bar. The likeliest difference is reasoning effort: this session runs at its maximum, and the 2026-10-01 session's setting is not in its workflow's record.
- **Most of a read is fixed overhead.** Every reader's first request already carries about 62,000 to 65,000 tokens of context (the agent's instructions, tools and the project's injected instructions) before it opens its pair. So the price is set by the number of reader agents, not by the text read.

**Cheaper discriminators, measured against every pair read so far (51) and the refused DSCC pair, the one known negative:**

| test | read pairs it holds on | of them unanimous | of them split | DSCC | first-load pairs of the 239 it would settle |
|---|---|---|---|---|---|
| D1: CourtListener created the two objects within 15 minutes | 14 | 14 | 0 | excludes it | 49 |
| D1 and D2 (D2: nothing else in the window fits the short form) | 12 | 12 | 0 | excludes it | 45 |
| D2 alone | 45 | 39 | 6 | passes it | 215 |
| D3: the two texts equal once stamps are stripped, at most one numbered | 9 | 7 | 2 | excludes it | 1 |

- **D1 is the one candidate.** It holds on 14 read pairs, every one a unanimous pass, splits none, and excludes the DSCC pair. It would settle 49 of the 239, leaving 190 pairs, 570 reads, about 47.4 million tokens at this session's rate.
  - D1 is the minutes-apart, one-load signature the rule was built on, read off CourtListener's own clocks rather than psephos's runs, so a first load does not blind it.
  - **The evidence is thin.** 14 for 14 bounds how often D1 would pass a pair the readers would not, at about 19% (one-sided 95%). And no read pair has been shown to be two entries, so D1 has met one known negative, DSCC.
- **D2 alone is not usable:** it passes the DSCC pair, the one known negative. D3 settles 1.
- **Two cheaper ways to read, neither measured:**
  - one reader per docket per lens, 90 readers for the 239 instead of 717, which pays the fixed overhead 90 times. Each reader would judge many pairs in one context, a change of method;
  - readers without the project's injected instructions, which a reader of one dump does not need.

**Held for Corey: whether the second batch runs, and in what form.**

