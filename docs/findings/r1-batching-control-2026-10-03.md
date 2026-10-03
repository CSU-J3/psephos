# R1: the batching control, the six splits re-read one pair a reader, 2026-10-03

**Status: exactly 1 of the 6 changed outcome, so by the rule stated before the read this stops with the reads laid out (c).** Person pair 4 read unanimous. The other five reproduced their splits, pair 22 among them.

**The read was not blind.** The workflow harness handed every reader Corey's brief, which stated the rule and named pair 22's finding. The branch rests on pair 22's read (below).

**Superseded the same day (Corey's rulings, 2026-10-03, ruling 3a).** The control was read again blind, from the launcher, by the Agent tool, on these same files. 2 of the 6 changed, and the rule gave a. Pair 22 read split again. See `r1-blind-reads-2026-10-03.md`.

## The rule, stated before the read (Corey, 2026-10-03)

- **a.** At least 2 of the 6 change outcome under single-pair re-reads: splits are unstable under any re-read. Adopt batching for the 239. Every split still goes to Corey, and his random check grows from five to ten, drawn from the batched unanimous passes.
- **b.** The re-reads reproduce all 6 splits: batching made a borderline pair look clear. Do not use it for the 239; stop with the price of single-pair reads at the trimmed overhead.
- **c.** Exactly 1 changes: stop with the reads laid out.

## How it was read

- One pair a reader, three readers a pair, one lens each: 18 readers.
- The calibration's trimmed readers: the same agent type, model and reasoning effort, loading no project instructions.
- The calibration's brief and lens prompts word for word, and the same bar: a pair passes when all three read one minute entry and none names a better match.
- Each reader's file held one pair, in the dump the calibration read: the pair, its rows with `seen_by`, and every object on its docket from the day before to the day after.
- Each reader read its file once and returned its verdict. Workflow `wf_c0997506-699`.

## The reads

Each cell gives the three lenses in order, identity / alternative match / clocks (y yes, u uncertain, n no), then the outcome.
- **Recorded:** one pair a reader with the project's instructions loaded, on 2026-10-01 (the sample) or 2026-10-02 (the person list).
- **Batched:** the calibration, 2026-10-03.
- **Alone:** this control.

| pair | rows | docket | recorded | batched | alone | changed |
|---|---|---|---|---|---|---|
| 2026-10-01 sample n=3 | 13595/13771 | 72193752, Northern District of Georgia | y / y / u, **split** | y / y / u, **split** | y / y / u, **split** | no |
| 2026-10-01 sample n=8 | 5419/5457 | 71453646, District of New Hampshire | y / y / u, **split** | y / y / u, **split** | y / y / u, **split** | no |
| person pair 4 | 8868/8873 | 72156765, Eastern District of Virginia | y / y / u, **split** | y / y / y, **unanimous** | y / y / y, **unanimous** | **yes** |
| person pair 5 | 8869/8871 | 72156765, Eastern District of Virginia | y / y / u, **split** | y / y / u, **split** | y / y / u, **split** | no |
| person pair 15 | 89060/89682 | 73582123, Third Circuit | y / y / u, **split** | y / y / u, **split** | u / y / u, **split** | no |
| person pair 22 | 91090/91356 | 73582123, Third Circuit | y / u / u, **split** | y / u / n (better match 479305486), **not linked** | u / u / u, **split** | no |

**Batched against alone.** The two reads use the same trimmed readers, prompts and dumps. They differ in batching and in the brief each reader was handed (below).
- They agree on five of the six, pair 4 included.
- They differ on pair 22: not linked when batched, split alone. Only the readers alone were handed pair 22's finding.
- On none of the six did the batched read make a pair look clearer than the read alone.

## The one change: person pair 4

- **The pair.** Docket 72156765 (United States v. Koski, Eastern District of Virginia), rows 8868/8873.
  - The short form reads "Notice of Correction".
  - The long form reads "Notice of Correction re 18, 19, 20 : Documents filed as PDF fillable forms ... Clerk has corrected."
  - Both are dated 2026-02-05.
- **The clocks lens moved.** It read uncertain on 2026-10-02 and yes in both trimmed reads, batched and alone.
  - Alone, it read the 43 minutes between the two objects as "minutes apart, not far apart".
  - It also found the window holds one correction event: 18, 19 and 20 each note their main document replaced on 2/5, and 21 does not.
- **So the change is not batching's.** It appears in both trimmed reads, against the one read with the project's instructions loaded.
  - The trimmed readers also saw `seen_by`, which the 2026-10-02 dump lacked.
  - Any of the differences could account for it: a fresh read, the trim, the added field, or the brief each reader was handed, though none named pair 4. The control does not separate them.

## Pair 22, recorded either way

- **The pair.** Docket 73582123 (United States v. Secretary Commonwealth of Pennsylvania, Third Circuit), rows 91090/91356, entries of 2026-09-23.
  - The link would fold numbered entry #54 (object 479305491) into an unnumbered object (479082481).
- **The finding: the unnumbered object's text changed at least once.**
  - CourtListener created 479082481 at 16:23:19Z.
  - The docket stamps #51 "[Entered: 09/23/2026 12:22 PM]" and #54, whose text the object now carries, "[Entered: 09/23/2026 01:43 PM]".
  - Read in Eastern time, the Third Circuit's, the object was created about a minute after #51 was entered and 80 minutes before #54. Read in any US zone, it was created before #54.
  - psephos first held it between 21:28:48Z and 21:33:12Z that day, after all four extensions were entered, so it never saw the object's first text.
  - Four extension entries were entered that day, #51 to #54, and this is the only unnumbered object among them.
- **The reads.** All three readers alone found the clocks in the record, and all three read uncertain. None named a better match.
  - The brief they were handed already named the finding: "Pair 22's finding (its text changed at least once)".
  - The identity reader wrote "which is the same signature as pair 22".
- **It stays unlinked.** `config/entry_links.yaml` lists it under `refused` (Corey, 2026-10-03).

## The brief reached the readers

The workflow harness hands every agent the user request that triggered the run, verbatim, ahead of the computed task. So every read from the 2026-10-02 person list on began with Corey's brief for that turn. Where a brief named a pair and its verdict, that pair's readers were told it.

| read | readers | pair-specific content in the brief |
|---|---|---|
| the 2026-10-01 sample (`wf_51856ac1-7b7`, an earlier session) | 60 | no brief relayed |
| the 2026-10-02 person list, first batch (`wf_f9fc30e8-f0c`) | 72 | "Pair 23 (93225) stays the duplicate gates.yaml already records." Each reader's task named its pair's number. Two of pair 23's three readers cited it, one writing "This agrees with the relayed request's note that 93225 is already recorded as a duplicate in gates.yaml." |
| the rule's 7 (`wf_6461b558-288`) | 21 | none for the 7. The brief names n=3 and n=8 of the 2026-10-01 sample. |
| the calibration, and its pilot (`wf_76de00aa-f8a`, `wf_2fa45006-00d`) | 18, 2 | "Pair 23 (93225 with its twin) is linked now as asserted ... three passing reads". Pair 23 was among the 51. |
| this control (`wf_c0997506-699`) | 18 | the rule, so every reader could tell its pair was a recorded split, and pair 22's finding |

**The calibration's negative control was described to every reader too, by design.** Since 2026-10-01 every reader's task has said: "The one pair already refused shows the failure mode: a notice of interlocutory appeal and an '.Order' short form on one day, paired on type alone." That is the DSCC pair. Its three readers' catch shows they apply the description, not that they find an unknown negative.

**What it changes:**
- **The branch.** Exactly 1 changed, so c.
  - Pair 22's reproduction is a primed read. Had an unprimed re-read moved it, 2 would have changed, and the branch would be a.
  - No brief named pair 4 or the other four. But every reader was handed the rule.
- **Pair 23's link stands on Corey's 2026-09-29 verdict.** Its three passing reads of 2026-10-02 are not independent of that verdict: two of the three cited it. Its calibration readers were handed a brief naming it linked.
- **The calibration's FAIL stands.** Its two differences, pairs 4 and 22, were named in no brief it was handed.
- **The 2026-10-01 sample's 60 readers were handed no brief.**
- **Unmeasured:** whether readers launched another way get the same relay. This session launched none another way.

## The price, measured

| | |
|---|---|
| the control | 714,359 tokens and 6m58s for 18 readers: 39,687 a reader, one pair each |
| what each reader loads before its pair | 34,322 tokens (median of 18; 34,260 to 34,330) |
| the 239, one pair a reader, at the control's rate | 717 reads, about 28.5 million tokens, and about 2.5 hours at 16 readers at a time |
| the 239, batched, at the calibration's rate | about 6.16 million tokens and 65 minutes (`r1-batched-calibration-2026-10-03.md`) |

**Nothing is read or linked further until Corey rules.**
