# R1: the batched readers, calibrated on the 51 pairs already read, 2026-10-03

**Status: the calibration FAILS Corey's bar, 49 of 51, so the 239 are not read.** Corey's ruling of 2026-10-02 (2b): "Use batching on the 239 only if it reproduces every unanimous pass and every split; otherwise stop with the differences." Two splits differ. Every unanimous pass reproduced.

## How it was read

- **Batched (2a).** Each reader took a run of up to 9 pairs under one lens. Every pair still had three readers, one per lens.
  - The runs were grouped by docket and date: 6 runs for the 51 pairs and the control.
  - The lens prompts and the bar were the earlier reads' word for word.
  - The brief tells each reader to judge each pair from its own record, never from another pair in the run.
- **Trimmed (2c).**
  - Each reader ran as an agent type that loads no project instructions, pinned to the same model and reasoning effort as the 2026-10-02 reads.
  - Each read its run's file once.
  - A two-reader pilot measured the trim before the calibration ran.
- **What each reader saw:** the same dump as before for every pair: the pair, its rows (now with `seen_by`), and every object on its docket from the day before to the day after.
- **The control:** the refused DSCC pair (92515/92572) rode along as a known negative, outside the 51.

## The result

| | pairs | reproduced |
|---|---|---|
| recorded unanimous passes | 45 | 45 |
| recorded splits | 6 | 4 |

**The control:** the DSCC pair, read identity no, alternative no (better match 465858909), clocks no (better match 465858909). All three readers caught the known negative.

### The two differences

#### Person pair 4, rows 8868/8873: recorded split, batched unanimous

| lens | 2026-10-02, one pair a reader | 2026-10-03, batched |
|---|---|---|
| identity | yes | yes |
| alternative | yes | yes |
| clocks | uncertain | yes |

- **Batched, identity:** IDENTITY: the short form 'Notice of Correction' is exactly the event the long form records ('Notice of Correction re 18, 19, 20 ... Clerk has corrected ... (jenjones)'). Both objects are unnumbered and dated 2/5/2026, and CL created them 43 minutes apart (10:12 and 10:55 PST). The short form names nothing the long form does not. In the window, entries 18, 19 and 20 each read 'Main Document replaced on 2/5/2026 (jenjones)', which fits a single correction notice covering all three. No other notice of correction is on the docket from 2/4 to 2/6.
- **Batched, alternative:** The window (02/04 to 02/06) holds one Notice of Correction: the long form 452844429 (unnumbered, 02/05, 're 18, 19, 20'). The numbered entries are #18 to #21, the 02/04 pro hac vice motions. Those are the filings the notice corrects, not notices. Nothing else is on 02/05 besides the pair. 'Notice of Correction' can describe only the long form, so there is no alternative.
- **Batched, clocks:** Clocks fit one entry. Both objects are unnumbered with time_filed null (null on every object in this docket's window). Long form 452844429 (desc_source entry) date_created 2026-02-05T10:12:11.687-08:00; short form 452851121 (desc_source document) 2026-02-05T10:55:51.913-08:00: 43m40s apart, on the entry date itself. Neither has twin_of set. The only other objects in the window are #18-#21, created 2026-02-04 09:58-10:12 PT; they are the filings the notice corrects, not competing notices. There is one Notice of Correction long form on 2/5, so the short form has no second correction entry to belong to.

#### Person pair 22, rows 91090/91356: recorded split, batched not linked

| lens | 2026-10-02, one pair a reader | 2026-10-03, batched |
|---|---|---|
| identity | yes | yes |
| alternative | uncertain | uncertain |
| clocks | uncertain | no, better match 479305486 |

- **Batched, identity:** On the texts, the identity holds. Both record the same nine appellees (Common Cause, Dickson, Kent, LWV-PA, Maston, Perry, Sternfeld, Thatcher, Thompson) verbally granted an extension to 10/22/2026 under LAR 31.4, clerk EAF, both dated 9/23. #51-#53 are the same kind of grant for different appellees, and the named parties tell them apart, so the short form fits none of them. A finding outside this lens, from this pair's own record: the entry object 479082481 was created 2026-09-23T09:23:19-07:00, which is 12:23 PM ET. That is about 80 minutes BEFORE #54 was entered (1:43 PM) and about 1 minute after #51 was entered (12:22 PM, Secretary of the Commonwealth, clerk MCW). Under any time zone, the object existed before #54 did. Its text therefore most likely changed after creation, probably from #51 through #52 and #53 to #54. The current texts match, but the link would rest on an unnumbered object whose text has already moved at least once.
- **Batched, alternative:** On text alone, only #54 fits. The unnumbered 479082481 matches #54 (479305491) word for word, and its party list (Common Cause, Dickson, Kent, LWV-PA, Maston, Perry, Sternfeld, Thatcher, Thompson) separates #54 from the day's three other grants of a verbal extension to 10/22/2026: #51 479305486 (Secretary of the Commonwealth, MCW, 12:22 PM), #52 479305488 (NAACP, EAF, 1:24 PM) and #53 479305489 (Crossey/PARA, EAF, 1:36 PM). So I name no better match. The timing does not fit. 479082481 was created 2026-09-23 09:23:19 PDT, which is 12:23 PM ET. That is one minute after #51 was entered and 80 minutes before #54 was entered (1:43 PM). In any US time zone, the object existed before #54 was entered. It is also the only unnumbered object for four entries of the same type that day. Its text must therefore have been replaced after it was created: it looks as if it began as #51's object and was overwritten by the later same-type entries. The record does not settle that this object is a single minute entry with #54. Folding #54 into it would rely on an object that has held more than one entry and could change again.
- **Batched, clocks:** Clocks do not fit. Unnumbered 479082481 has date_created 2026-09-23 09:23:19 -07:00, which is 12:23:19 ET. That is 80 min BEFORE the '[Entered: 09/23/2026 01:43 PM]' stamp on #54 (479305491), whose text the object now carries, so it cannot have been created as a capture of #54. Its clock lands about 1 min after #51's (479305486) '[Entered: 09/23/2026 12:22 PM]'. That is the same echo lag this docket shows for #47 (11:31 AM, echo at 11:32:11) and #48 (11:48 AM, echo at 11:48:37). The window has only one unnumbered object for four same-day clerk verbal-extension entries: #51 at 12:22 PM, #52 at 01:24 PM, #53 at 01:36 PM and #54 at 01:43 PM. By contrast, #46 to #49 each got their own echo. This fits an object created for #51 whose text was later replaced. #54's date_created is 2026-09-24 12:05:52.43 -07:00, in the backfill batch. The better_match 479305486 is a fit on clocks only, for the unnumbered entry-side object. That object's text matches #54, not #51, so this is not a proposal to link it to #51.

**What the two have in common.** Both were splits, uncertain on the clocks lens.
- Pair 4 moved toward a pass. The batched clocks reader read the same 43 minutes between the two objects as fitting one entry.
- Pair 22 moved toward not linked, on a finding the one-pair reads did not name.
  - The unnumbered object 479082481 was created about a minute after entry #51 was entered, and 80 minutes before #54, whose text it now carries.
  - So its text has moved at least once.
  - Its clocks reader's "better match" (#51) is, in its own words, "a fit on clocks only", "not a proposal to link it to #51".
- **Neither difference is a unanimous pass lost or a false pass gained on the control.**
- No one-pair re-read was taken, so how much of the movement is batching and how much is a borderline verdict re-read is not measured.

## The price, measured (2c, 2d)

| | |
|---|---|
| what each reader loads before its pairs, trimmed | 34,547 tokens (median of 18; 34,485 to 34,557) |
| the same, before the trim (2026-10-02's readers) | about 64,700 |
| a reader's context once its run is read | 73,795 (median) |
| the calibration | 1,340,664 tokens and 14m22s for 18 readers: 74,481 a reader, 8,594 a pair-read |
| the 239, batched, at that rate | about 6.16 million tokens (6.03 million by readers, 6.16 million by pairs) and about 65 minutes |
| the 239, one pair a reader, at 2026-10-02's rate | about 59.6 million tokens and three hours |

**The batched run would be under the 10 million ceiling, but the calibration did not clear its bar, so it is not run.**

**D1 stays a recorded measurement (2e).** Nothing here settles a pair without readers.

