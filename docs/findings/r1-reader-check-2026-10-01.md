# R1: the reader's check of the same-run rule, 2026-10-01

**Status: FAIL on the bar set before the read, held for Corey.** `config/entry_links.yaml` records it, so `link_entry_twins --apply` refuses and no tier-2 link has been written.

## What was read

- **The pool:** the rule's 266 linkable pairs, after the id walk completed on 2026-10-01. That is 10 more than the D0's 256, all among rows the D0 held: the rule classifies D0-era rows differently once every row carries its object.
- **The draw:** `python -m scripts.link_entry_twins --sample 20 OUT --seed 20260930`, walks through 2026-10-01T06:13:55Z.
- **The readers:** three per pair, each independent and each with one lens:
  - identity: does the short form describe exactly the event the long form records?
  - alternative match: does any other entry on the docket, from the day before to the day after, fit the short form as well or better? This is the refused DSCC pair's failure mode.
  - clocks: do the two objects' CourtListener clocks and shape fit one minute entry seen twice?
- **What they read:** only a dump of each pair and every object in that window.
- **The bar, set before the read:** a pair passes when all three read one entry and none names a better match. The sample passes when all 20 do.

## The result

- **18 of 20 pass unanimously.**
- **n=3 and n=8 do not.** For each, the identity and alternative lenses read one entry and name no better match. The clocks lens reads uncertain.
- **None of the 20 was shown to be two entries.** No reader named a better match.

| n | rows | docket | kind | created apart | same-run only at bootstrap | identity | alternative | clocks |
|---|---|---|---|---|---|---|---|---|
| 1 | 91808/92003 | 73141063 | short_long | 0.06 h | no | yes | yes | yes |
| 2 | 91481/91750 | 73133197 | type_only | 0.09 h | no | yes | yes | yes |
| 3 | 13595/13771 | 72193752 | long_twin_prefix | 25.68 h | yes | yes | yes | uncertain |
| 4 | 15563/15564 | 72054244 | short_long | 0.05 h | no | yes | yes | yes |
| 5 | 92121/92193 | 74701505 | short_long | 1.28 h | no | yes | yes | yes |
| 6 | 91564/91734 | 73133197 | type_only | 0.79 h | no | yes | yes | yes |
| 7 | 272/294 | 71499795 | short_long | 49.85 h | no | yes | yes | yes |
| 8 | 5419/5457 | 71453646 | short_long | 795.60 h | yes | yes | yes | uncertain |
| 9 | 13982/14001 | 72334676 | short_long | 22.63 h | yes | yes | yes | yes |
| 10 | 91909/91995 | 73141063 | short_long | 7.95 h | no | yes | yes | yes |
| 11 | 91607/91731 | 73133197 | type_only | 0.80 h | no | yes | yes | yes |
| 12 | 280/288 | 71499795 | short_long | 146.10 h | no | yes | yes | yes |
| 13 | 5400/5461 | 71453646 | short_long | 0.19 h | no | yes | yes | yes |
| 14 | 92085/92208 | 74701505 | short_long | 0.03 h | no | yes | yes | yes |
| 15 | 6809/6842 | 72021508 | short_long | 0.03 h | no | yes | yes | yes |
| 16 | 7817/7847 | 71457474 | short_long | 0.47 h | no | yes | yes | yes |
| 17 | 85278/85325 | 71452580 | short_long | 0.10 h | yes | yes | yes | yes |
| 18 | 6767/6834 | 72021508 | short_long | 0.95 h | no | yes | yes | yes |
| 19 | 85413/85415 | 72110941 | short_long | 14.81 h | yes | yes | yes | yes |
| 20 | 17878/17942 | 71453026 | short_long | 0.70 h | no | yes | yes | yes |

### n=3: rows [13595, 13771], United States v. Raffensperger (Northern District of Georgia), 2026-01-28

- **Row 13595**, object 452037636, kept (the entry): NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES ASSIGNED TO THE HONORABLE ELEANOR L. ROSS. (mlb) (mlb). (Entered: 01/28/2026)
  - entry number 12, created 2026-01-29T11:36:36.909876-08:00, time filed None, text from entry
- **Row 13771**, object 451857584, folds into the other (the twin): NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES ASSIGNED TO THE HONORABLE ELEANOR L. ROSS. (mlb)
  - entry number None, created 2026-01-28T09:56:04.454411-08:00, time filed None, text from entry
- **The identity lens, yes:** Read through the identity lens: the short form and the long form record the same event. The short form, unnumbered object 451857584 (row 13771), reads "NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES ASSIGNED TO THE HONORABLE ELEANOR L. ROSS. (mlb)". That text is an exact prefix of entry 12, object 452037636 (row 13595), which adds only "(mlb). (Entered: 01/28/2026)". Both have the same filing type (a court-issued notice), the same subject (Judge Ross's civil-case instructions), the same clerk initials (mlb), and the same entry_at (2026-01-28). The short form names nothing the long form does not do. The second "(mlb)" on the long form looks like the clerk's mark from modifying or re-entering the text, which suggests the numbered text was made from the unnumbered one. It does not point to a different event. No other object on the docket from 01-27 to 01-29 fits the short form. The window holds no other "NOTICE FROM THE COURT" object. The 01-28 "Order" (451865808) and the clerk's notations on entries 4 and 7 are different events. One caveat: the order of objects suggests the notice was unnumbered on the docket at 09:56 PT on 01-28, between entries 5 and 6. Entry 12 was numbered after entry 11. So the court's own docket might show the notice twice, once unnumbered and once as entry 12, if the clerk re-entered it rather than editing it. Even so, both would record one notice, and linking them would not fold a distinct event into another. That is the harm this check exists to catch. Verdict: yes.
- **The alternative lens, yes:** Pair n=3 is in United States v. Raffensperger (N.D. Ga.), docket 72193752, on 2026-01-28. The twin is 451857584, an unnumbered object with desc_source 'entry', created 2026-01-28 at 09:56:04. Its text is 'NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES ASSIGNED TO THE HONORABLE ELEANOR L. ROSS. (mlb)'. The entry is 452037636, docket entry #12, created 2026-01-29 at 11:36. Its text is the same string, then a second '(mlb)' and '. (Entered: 01/28/2026)'. So the short form is an exact word-for-word prefix of the long form, not a match on type alone. Alternative match: the window runs 01-27 to 01-29 and holds 20 objects. I checked every one, and none is another candidate: - Numbered entries #2 to #11 are a summons, two motions to intervene, two corporate disclosure statements, a notice of appearance by Tyson and four pro hac vice applications. None is a notice from the court, and none is about Judge Ross's instructions. - The unnumbered objects are two Clerk's Notations (on #4 and #7), four clerk approvals of the pro hac vice applications, an 'Approval of Application for Admission Pro Hac Vice' document, and an 'Order' document (451865808). None shares the twin's text. - #12 is the only object in the window, numbered or not, that carries 'NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES'. The pattern looks like the usual same-day duplicate: one CourtListener object with no entry number, followed by the numbered docket entry about a day later. Unlike the refused pair, there are not two candidate entries on that day, so this is not that failure mode. No better match.
- **The clocks lens, uncertain:** Pair n=3 is in United States v. Raffensperger, N.D. Ga., case 72193752, on 2026-01-28. It is a long_twin_prefix edge with two identical texts, "NOTICE FROM THE COURT: INSTRUCTIONS FOR CIVIL CASES ASSIGNED TO THE HONORABLE ELEANOR L. ROSS." CLOCKS: - twin 451857584: unnumbered, time_filed null, date_created 2026-01-28T09:56:04.454-08:00, desc_source 'entry'. - entry 452037636: entry_number 12, time_filed null, date_created 2026-01-29T11:36:36.910-08:00, desc_source 'entry'. The two objects were created about 25h40m apart, not minutes apart. This does not fit the D0 tier-2 fingerprint described in cl_twins.py: the short object carries a time_filed and takes its text from its RECAP document, the two objects are created in one docket-report load, and they appear minutes apart. Here neither object has a time_filed, both took their text from the docket entry (neither is a 'document' object), and they arrived in different CourtListener batches. - The unnumbered object sits inside the 09:56:03.979–09:56:04.607 batch of 1/28, between ids 451857582 (#5) and 451857585 (#6), with entries #3–#7 and the unnumbered Clerk's Notation 451857583. - #12 was created alone a day later. - Neither object is another object's twin (twin_of null on both), and they are the only NOTICE FROM THE COURT objects in the window. So there is no rival match, and better_match is null. SHAPE: One story fits one minute entry seen twice across a clerk edit, but nothing in the file proves it. - The notice already existed, unnumbered and with a single "(mlb)", at 1/28 09:56 PT. - The numbered form carries a doubled "(mlb) (mlb)", which is typical of a modified entry, and keeps "(Entered: 01/28/2026)". - Its number 12 is above #8–#11, which CourtListener created at 1/28 11:29:34–11:35:06. That fits a number assigned after a later edit, for example when a document was attached; document_url is null on the unnumbered row and points to /12/ on the numbered one. The same clocks and number also fit a clerk re-docketing the notice as a fresh entry #12 later on 1/28. In that case PACER may hold two rows. The 25h40m gap cannot tell these two stories apart, and the doubled initials are suggestive, not conclusive. The texts are identical, so folding them would lose little. But the clocks do not show the minutes-apart, one-load signature the rule was built on. I default to uncertain, leaning yes. The psephos-side "same-run" condition does hold: both rows have seen_at 2026-07-07T19:45:58.975Z, the bootstrap load. That says nothing about the upstream clocks.

### n=8: rows [5419, 5457], United States v. NH Secretary of State (District of New Hampshire), 2025-09-25

- **Row 5419**, object 442705043, folds into the other (the twin): Case Assigned
  - entry number None, created 2025-10-31T07:13:30.893815-07:00, time filed None, text from document
- **Row 5457**, object 439194969, kept (the entry): Case assigned to US Magistrate Judge Andrea K Johnstone. The case designation is: 1:25-cv-371-AJ. Please show this number with the judge designation on all future pleadings. (ed)
  - entry number None, created 2025-09-28T03:37:17.534743-07:00, time filed None, text from entry
- **The identity lens, yes:** Identity lens, read as a docket clerk. The long form (439194969, unnumbered, desc_source entry, dated 2025-09-25) reads "Case assigned to US Magistrate Judge Andrea K Johnstone. The case designation is: 1:25-cv-371-AJ ... (ed)". This is the clerk's unnumbered case-assignment minute entry. The short form (442705043, unnumbered, desc_source document, dated 2025-09-25) reads "Case Assigned", the standard CM/ECF short description for that same event type. Both carry the same date, and both are unnumbered, which is how a case-assignment minute entry appears on a docket. The short form names no party, motion or document the long form leaves out, so it is fully consistent with it. I checked every other object in the window as a candidate: - Entry #4 (439090829, 9/25, "NOTICE of Assignment to U.S. Magistrate Judge and Consent Form sent to plaintiff") is a separate event, a notice and not the assignment itself. It is also numbered, so an unnumbered "Case Assigned" short form fits it worse. - Entries #1, #2 and #3 are the complaint, the summons request and a null text. Everything from #5 on is dated 9/26. - The ECF-designation notice 439194970 already has its own short form, "Notice - ECF" (439090820). - No second case-assignment long form appears anywhere in the window, so there is nothing for this short form to fit better. Two caveats, neither of which changes the identity reading: 1. A second "Case Assigned" short form exists, 439090834, dated 9/26 with time_filed 13:03:14 and created 9/26. It most likely stands for the same minute entry, which the clerk (ed) entered on 9/26 with a filed date of 9/25. That would make three objects for one entry, not two distinct assignment events. It means the long form may also have another short-form twin, but it is not evidence that 442705043 is a different event. 2. 442705043 was created 2025-10-31, about five weeks after the long form (created 2025-09-28). It does not show the usual "minutes apart" pattern; it was a later upload. Both were first held in the same psephos run (seen_at 2026-07-03T09:33:17Z), so the rule's same-run condition holds. On text identity, it is the same event: same kind, same day, and nothing extra.
- **The alternative lens, yes:** Pair 8 is on docket 71453646 (D.N.H., US v. NH Secretary of State) for 2025-09-25. The short form is 442705043, "Case Assigned". It is unnumbered, its text comes from its document, it has no time_filed, and it was created 2025-10-31. The long form is 439194969, "Case assigned to US Magistrate Judge Andrea K Johnstone. The case designation is: 1:25-cv-371-AJ..." It is also unnumbered and dated 09-25. I checked all 10 objects in the 09-24 to 09-26 window for a rival match. - #1 (complaint), #2 (request for summons) and #5 (summonses issued, 09-26) are different events. - #3 has no text, but it cannot be the assignment. It was filed at 11:59:33, 1.7 minutes after counsel's #2, and CourtListener created it together with #1 and #2 at about 12:48 ET on 09-25. The clerk's assignment was entered later, around 13:03 on 09-26, per the RSS-style object 439090834. - #4 is the only plausible numbered rival: "NOTICE of Assignment to U.S. Magistrate Judge and Consent Form sent to plaintiff", dated 09-25. It is a separate notice-of-assignment event and does not contain the word "case". In CM/ECF, "Case Assigned" is the short label of the case-assigned event, whose docket text is exactly the long form ("Case assigned to ... The case designation is ..."). The window corroborates that this court uses the label for the unnumbered assignment entry. The same RSS batch (created 10:19:16 PT on 09-26) made #4 as its own numbered object and also made a separate unnumbered "Case Assigned" object (439090834, 13:03:14, dated 09-26). If #4's short label had been "Case Assigned", that item would have carried number 4 and merged into #4. So "Case Assigned" belongs to the unnumbered assignment entry, and 442705043 is unnumbered with the same label and the long form's 09-25 date. - The other short forms are not entries the short form could be linked to instead. 439090820 "Notice - ECF" pairs with the long ECF-designation notice 439194970 (09-26). 439090834 "Case Assigned" (09-26) looks like another short copy of the same assignment entry. Conclusion: the long form is the only entry in the window that "Case Assigned" dated 09-25 can describe, so the link joins one minute entry and does not fold a distinct one. One caveat, which does not make the link false: the assignment entry seems to have three CourtListener objects (long 439194969, short 439090834, short 442705043). The rule links only one of the short ones, because 439090834 sits on another day (09-26).
- **The clocks lens, uncertain:** Lens: clocks and shape. The text points one way but the clocks don't confirm it. Pair: twin 442705043 "Case Assigned" and entry 439194969 "Case assigned to US Magistrate Judge Andrea K Johnstone ... 1:25-cv-371-AJ ... (ed)". Docket 71453646 (D.N.H.), both entry_at 2025-09-25. Shape mostly fits one entry seen twice: - The twin has desc_source=document and the entry has desc_source=entry. - Both have entry_number null. An unnumbered clerk 'case assigned' minute entry is normal, but this is not the usual numbered long form plus unnumbered short form. - twin_of is null on both, so neither is already linked elsewhere. - In the 09-24 to 09-26 window, 439194969 is the only long-form text on 2025-09-25 that describes a case assignment. Entry #4 (439090829, 'NOTICE of Assignment to U.S. Magistrate Judge and Consent Form...') is a different event type, a notice, not the assignment. So no other long form fits better. The clocks do not fit the one-entry signature: - date_created is 2025-09-28T03:37:17.534743-07:00 for the entry and 2025-10-31T07:13:30.893815-07:00 for the twin. That is about 33 days apart, not minutes. - time_filed is null on both, so no filing clock corroborates them. - The 'same-run' relation adds almost nothing. Both pair_rows have seen_at 2026-07-03T09:33:17.330216+00:00, which looks like the docket's bootstrap run, when everything on the docket was first held together. - The 33-day gap probably reflects when CourtListener captured each object (a docket-report fetch, then a later RECAP document), not two separate filings. A backdated second assignment entered five weeks later is implausible. But the clock evidence is absent or neutral, not confirming. A competing short form complicates the picture: - 439090834 is another document-source 'Case Assigned' object, unnumbered. Its entry_at is 2025-09-26, time_filed 13:03:14, and date_created 2025-09-26T10:19:16.661249-07:00. It was created in the same second as entry #4 (10:19:16.351884) and 'Notice - ECF' (10:19:16.062425). - So the docket already holds a 'Case Assigned' short form with real clocks, on the next day. It is unlinked. - The 10-31 object is either a second capture of the same assignment, which would make the link true, or a short form for a different assignment event whose long text is not in the window. The file cannot tell these apart. Verdict: the semantic and shape fit is good, but the clocks don't show one entry seen twice (33 days apart, no time_filed, bootstrap same-run). There is also an unexplained duplicate 'Case Assigned' short form on 09-26, so I default to 'uncertain'. better_match is null: no other long-form object in the window fits 'Case Assigned' as well as 439194969. The duplicate short form 439090834 is another short form, not a candidate entry.

## The measurement that followed (Turso, read-only)

**How far apart CourtListener created each pair's two objects**, across all 266:

| created apart | pairs | of them same-run only at bootstrap |
|---|---|---|
| <=15 min | 60 | 5 |
| 15 min-6 h | 93 | 13 |
| 6-48 h | 49 | 18 |
| >48 h | 64 | 27 |

- **The minutes-apart signature describes only 60 pairs (15 minutes or less).** The clocks lens leaned on it.
- 5 of the 18 pairs that passed unanimously were more than 6 hours apart (n=7, 9, 10, 12, 19: 8 to 146 hours), so the gap alone does not separate n=3 and n=8 from them.
- **For 63 of the 266 pairs, "same-run" holds only because the docket's bootstrap load first held both rows.** That load fetched the whole docket at once, so for these pairs the run says nothing about how the two objects relate, and the rule rests on text and type alone.
- n=3 and n=8 are both among them. So are n=9, n=17 and n=19, which passed.
- The other 203 were first held together by a later poll, whose window does bound when the two appeared upstream: the premise the rule was built on.

## The 23 pairs for a person

These are the pairs the rule does not link: 12 held in different runs (cross-run) and 11 whose run cannot be told (undetermined). Each is linked only if a person lists it under `asserted` in `config/entry_links.yaml`. Pair 23 is 71499795's Sep 29 text row, which `docs/gates.yaml` already records as a duplicate by the later-row rule.

### 1. League of Women Voters v. U.S. Department of Homeland Security (D.D.C.), 2026-06-29: undetermined, rows [505, 577]

- **Row 505**, object 469059230, folds into the other (the twin): USCA Case Number
  - entry number None, created 2026-06-29T06:20:41.920460-07:00, time filed 08:18:36, text from document
- **Row 577**, object 469059669, kept (the entry): USCA Case Number 26-5243 for 113 Notice of Appeal to DC Circuit Court, filed by SOCIAL SECURITY ADMINISTRATION, FRANK BISIGNANO, KRISTI L. NOEM, U.S. DEPARTMENT OF HOMELAND SECURITY. (mg)
  - entry number None, created 2026-06-29T06:25:50.906509-07:00, time filed None, text from entry

### 2. Common Cause v. U.S. Department of Justice (D.D.C.), 2026-07-01: cross-run, rows [4059, 12693]

- **Row 4059**, object 469403049, folds into the other (the twin): Order on Motion for Leave to File Amicus Brief
  - entry number None, created 2026-07-01T08:47:10.676381-07:00, time filed 10:50:34, text from document
- **Row 12693**, object 469938096, kept (the entry): MINUTE ORDER granting the 40 Motion for Leave to File Amicus Brief. The Court treats the 40 Motion's attachment, ECF No. 40-1, as the amicus brief. Signed by Judge Sparkle L. Sooknanan on 7/1/2026. (lcak)
  - entry number None, created 2026-07-07T08:08:49.623906-07:00, time filed None, text from entry

### 3. United States v. Oliver (District of New Mexico), 2026-07-01: cross-run, rows [7714, 17501]

- **Row 7714**, object 469459844, folds into the other (the twin): Order on Motion to Withdraw as Attorney
  - entry number None, created 2026-07-01T13:03:47.392386-07:00, time filed 13:28:29, text from document
- **Row 17501**, object 470082775, kept (the entry): ORDER by Magistrate Judge John F. Robbenhaar granting 112 Motion to Withdraw as Attorney. Attorney Omeed Alerasool terminated. THIS IS A TEXT-ONLY ENTRY. THERE ARE NO DOCUMENTS ATTACHED. (kc) (Entered: 07/01/2026)
  - entry number 117, created 2026-07-08T08:33:35.368287-07:00, time filed None, text from entry

### 4. United States v. Koski (Eastern District of Virginia), 2026-02-05: undetermined, rows [8868, 8873]

- **Row 8868**, object 452851121, folds into the other (the twin): Notice of Correction
  - entry number None, created 2026-02-05T10:55:51.912910-08:00, time filed None, text from document
- **Row 8873**, object 452844429, kept (the entry): Notice of Correction re 18, 19, 20 : Documents filed as PDF fillable forms. Filing attorney reminded to only upload standard PDFs. Clerk has corrected. No further action needed. (jenjones, )
  - entry number None, created 2026-02-05T10:12:11.687335-08:00, time filed None, text from entry

### 5. United States v. Koski (Eastern District of Virginia), 2026-01-16: undetermined, rows [8869, 8871]

- **Row 8869**, object 451291760, folds into the other (the twin): Initial Case Assignment
  - entry number None, created 2026-01-23T05:49:47.439504-08:00, time filed None, text from document
- **Row 8871**, object 450807435, kept (the entry): Initial Case Assignment to District Judge Roderick C. Young. (adun, )
  - entry number None, created 2026-01-20T07:53:08.063185-08:00, time filed None, text from entry

### 6. United States v. Koski (Eastern District of Virginia), 2026-06-16: undetermined, rows [8870, 8872]

- **Row 8872**, object 467616347, folds into the other (the twin): Electronic Fee Payment - Pro Hac Vice
  - entry number None, created 2026-06-16T07:07:30.538376-07:00, time filed None, text from document
- **Row 8870**, object 467812805, kept (the entry): Electronic Fee Payment - Pro Hac Vice by Democratic National Committee. Filing fee $ 75, receipt number AVAEDC-11075521.. (Preis, John)
  - entry number None, created 2026-06-16T18:19:59.449128-07:00, time filed None, text from entry

### 7. United States v. Albence (District of Delaware), 2026-02-11: undetermined, rows [10510, 10511]

- **Row 10510**, object 453486788, folds into the other (the twin): SO ORDERED
  - entry number None, created 2026-02-11T08:13:05.764866-08:00, time filed 10:41:29, text from document
- **Row 10511**, object 453541893, kept (the entry): SO ORDERED, re 44 MOTION for Pro Hac Vice Appearance of Attorney Daniel J. Freeman, filed by Democratic National Committee. Signed by Judge Richard G. Andrews on 2/11/2026. (nms)
  - entry number None, created 2026-02-11T12:14:13.539596-08:00, time filed None, text from entry

### 8. League of Women Voters v. U.S. Department of Homeland Security (D.D.C.), 2026-07-11: cross-run, rows [27277, 29042]

- **Row 27277**, object 470523517, folds into the other (the twin): .Order AND ~Util - Set/Reset Deadlines
  - entry number None, created 2026-07-11T05:57:56.924754-07:00, time filed 08:01:02, text from document
- **Row 29042**, object 470527114, kept (the entry): MINUTE ORDER: In light of the 126 Joint Status Report and the Federal Defendants' representations about the exigency of this matter, the Court directs the Social Security Administration to file a notice by 5:00 PM on July 13, 2026, explaining whether the Social Security Administration is bound by the consent decree and the July 7, 2026, order enforcing the consent decree in Florida v. DHS, No. 3:24-cv-00509, ECF Nos. 30, 31, 45 (N.D. Fla.). The Court further directs the Parties to meet and confer by July 13, 2026, to try to resolve their disputes amicably. If they are unable to do so, the Court directs the Parties to comply with the following briefing schedule. The Plaintiffs shall file any motion to enforce or clarify the 112 Order by July 14, 2026. The Defendants shall file any response by July 16, 2026. The Plaintiffs shall file any reply by July 17, 2026. The Parties should be prepared to attend a hearing on this matter at 10:00 AM on July 20, 2026, if needed. The Court encourages the Parties to try to resolve this dispute amicably in light of the Northern District of Florida's recognition that there is "merit" to the Plaintiffs' argument that the Social Security Administration is not bound by its July 7, 2026, Order. Signed by Judge Sparkle L. Sooknanan on 7/11/2026. (lcak)
  - entry number None, created 2026-07-11T09:57:23.268247-07:00, time filed None, text from entry

### 9. United States v. Griswold (District of Colorado), 2026-07-10: cross-run, rows [27574, 37917]

- **Row 27574**, object 470496248, folds into the other (the twin): Order on Motion for Leave
  - entry number None, created 2026-07-10T16:05:39.656081-07:00, time filed 16:36:31, text from document
- **Row 37917**, object 470574182, kept (the entry): ORDER by Judge Philip A. Brimmer on 7/10/2026 re: 88 Colorado Alliance for Retired Americans and Britton DeFord's Motion for Leave to File Supplemental Brief Supporting Their Motion to Dismiss, ECF No. 86 is GRANTED. Colorado Alliance for Retired Americans and Britton DeFord shall file their supplemental brief, not to exceed 5 pages, on or before July 17, 2026. Text Only Entry.(echa, ) (Entered: 07/10/2026)
  - entry number 89, created 2026-07-13T05:07:14.355633-07:00, time filed None, text from entry

### 10. United States v. CALDWELL (District of New Jersey), 2026-07-15: undetermined, rows [54722, 54724]

- **Row 54724**, object 470929141, folds into the other (the twin): Pro Hac Vice Fee Received
  - entry number None, created 2026-07-15T09:42:03.906235-07:00, time filed 12:04:39, text from document
- **Row 54722**, object 471043721, kept (the entry): Pro Hac Vice fee received as to SEJAL JHAVERI $ 250, receipt number TRE150132 (kht)
  - entry number None, created 2026-07-16T04:26:17.857307-07:00, time filed None, text from entry

### 11. United States v. CALDWELL (District of New Jersey), 2026-07-16: undetermined, rows [68098, 68128]

- **Row 68128**, object 471409233, folds into the other (the twin): Pro Hac Vice Fee Received
  - entry number None, created 2026-07-20T05:57:28.267331-07:00, time filed None, text from document
- **Row 68098**, object 471410962, kept (the entry): Pro Hac Vice fee: Received as to JUSTIN LAM $ 250, receipt number NEW54587 (vm)
  - entry number None, created 2026-07-20T06:10:45.333413-07:00, time filed None, text from entry

### 12. United States v. Hobbs (Western District of Washington), 2026-08-04: cross-run, rows [81820, 82168]

- **Row 81820**, object 473219357, folds into the other (the twin): Motion Hearing
  - entry number None, created 2026-08-04T12:21:31.983126-07:00, time filed 11:29:28, text from document
- **Row 82168**, object 473219495, kept (the entry): MINUTE ENTRY for proceedings held before District Judge Kymberly K. Evanson - Dep Clerk: D. Staples; Pla Counsel: Kristen Johnson, Raymond Yang; Def Counsel: Cristina Sepe, Tera Heintz, Renata O'Donnell, Robert Ferguson, Abha Khanna, Tyler Bishop, Walker McKusick; CR: Andrea Ramirez; Time of Hearing: 10:00 AM; Courtroom: 16106; Motion Hearing held on 8/4/2026 re 53 MOTION to Dismiss for Failure to State a Claim and Opposition to Plaintiff's Motion to Compel filed by Steve Hobbs, 62 MOTION to Dismiss AND RESPONSE IN OPPOSITION TO MOTION TO COMPEL filed by Washington Conservation Action Education Fund, Common Cause, 63 MOTION to Dismiss and Response in Opposition to Plaintiff's Motion to Compel filed by Common Power, Washington Alliance for Retired Americans, 29 MOTION to Compel Production of Records filed by United States of America. The Court hears oral argument from the parties and takes the matters under advisement. Order to be issued. (DS) (Entered: 08/04/2026)
  - entry number 89, created 2026-08-04T12:23:32.408867-07:00, time filed None, text from entry

### 13. League of Women Voters v. U.S. Department of Homeland Security (D.D.C.), 2026-08-26: cross-run, rows [87390, 87543]

- **Row 87390**, object 475827532, folds into the other (the twin): USCA Case Number
  - entry number None, created 2026-08-26T07:45:07.276082-07:00, time filed 09:53:56, text from document
- **Row 87543**, object 475980995, kept (the entry): USCA Case Number 26-5301 for 141 Notice of Appeal to DC Circuit Court, filed by STATE OF TEXAS. (mg)
  - entry number None, created 2026-08-27T06:48:48.812679-07:00, time filed None, text from entry

### 14. League of Women Voters v. DHS (D.C. Circuit), 2026-09-04: cross-run, rows [88676, 88680]

- **Row 88676**, object 477057380, kept (the entry): PER ABOVE ORDER lodged Amicus brief [2183627-2], Amicus brief [2182713-2], Amicus brief [2182577-2] is filed [26-5243, 26-5301]
  - entry number None, created 2026-09-04T19:27:59.348272-07:00, time filed None, text from entry
- **Row 88680**, object 477084921, folds into the other (the twin): PER ABOVE ORDER lodged Amicus brief [2183627-2], Amicus brief [2182713-2], Amicus brief [2182577-2] is filed [26-5243, 26-5301] [Entered: 09/04/2026 10:27 PM]
  - entry number None, created 2026-09-05T17:24:28.866003-07:00, time filed None, text from entry

### 15. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-09: cross-run, rows [89060, 89682]

- **Row 89060**, object 477374891, kept (the entry): HARD COPY RECEIVED from Appellant USA - Joint Appendix. Copies: 4. Volume 2 ONLY (EAF)
  - entry number None, created 2026-09-09T10:15:41.966988-07:00, time filed None, text from entry
- **Row 89682**, object 477827680, folds into the other (the twin): HARD COPY RECEIVED from Appellant USA - Joint Appendix. Copies: 4. Volume 2 ONLY (EAF) [Entered: 09/09/2026 03:31 PM]
  - entry number 40, created 2026-09-14T05:20:09.948078-07:00, time filed None, text from entry

### 16. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-09: cross-run, rows [89061, 89683]

- **Row 89061**, object 477406289, kept (the entry): TEXT ORDER (Clerk) directing Attorney Joshua R. Zuckerman, Esq. for Appellant USA to submit 4 hard copies in white covers for the Appellant's Joint Appendix Volume I filed on 9/8/26. Due on or before 09/14/2026.This Order does not change the deadline for filing the next brief. (EAF)
  - entry number None, created 2026-09-09T12:34:39.489228-07:00, time filed None, text from entry
- **Row 89683**, object 477827681, folds into the other (the twin): TEXT ORDER (Clerk) directing Attorney Joshua R. Zuckerman, Esq. for Appellant USA to submit 4 hard copies in white covers for the Appellant's Joint Appendix Volume I filed on 9/8/26. Due on or before 09/14/2026.This Order does not change the deadline for filing the next brief. (EAF) [Entered: 09/09/2026 03:33 PM]
  - entry number 41, created 2026-09-14T05:20:10.000230-07:00, time filed None, text from entry

### 17. United States v. Steve Simon (Eighth District), 2026-09-15: undetermined, rows [89874, 90160]

- **Row 89874**, object 478038390, kept (the entry): APPEARANCE filed by Leah Frazier for Appellees NAACP and Cynthia Wilson w/service 09/15/2026 [5683737] [26-2679] (LF) [Entered: 09/15/2026 11:26 AM]
  - entry number 805610643, created 2026-09-15T09:48:21.986662-07:00, time filed None, text from entry
- **Row 90160**, object 478245810, folds into the other (the twin): ***DOCUMENT LOCKED***APPEARANCE filed by Leah Frazier for Appellees NAACP and Cynthia Wilson w/service 09/15/2026 5683737 [26-2679]--[Edited 09/16/2026 by CRJ. Counsel has refiled the appearance form. See history #5683894.] (LF) [Entered: 09/15/2026 11:26 AM]
  - entry number None, created 2026-09-16T12:43:36.981327-07:00, time filed None, text from entry

### 18. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-15: undetermined, rows [89883, 90093]

- **Row 89883**, object 478090823, kept (the entry): HARD COPY RECEIVED from Appellant USA - Joint Appendix Volume I. Copies: 4. (EMA)
  - entry number None, created 2026-09-15T13:25:37.507571-07:00, time filed None, text from entry
- **Row 90093**, object 478123200, folds into the other (the twin): HARD COPY RECEIVED from Appellant USA - Joint Appendix Volume I. Copies: 4. (EMA) [Entered: 09/15/2026 04:24 PM]
  - entry number 46, created 2026-09-15T15:46:09.851926-07:00, time filed None, text from entry

### 19. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-15: undetermined, rows [90158, 90178]

- **Row 90158**, object 478192847, kept (the entry): COMPLIANCE RECEIVED. (4) copies of Joint Appendix Volume I received from Appellant USA. (EAF)
  - entry number None, created 2026-09-16T08:32:11.193147-07:00, time filed None, text from entry
- **Row 90178**, object 478230496, folds into the other (the twin): COMPLIANCE RECEIVED. (4) copies of Joint Appendix Volume I received from Appellant USA. (EAF) [Entered: 09/16/2026 11:31 AM]
  - entry number 47, created 2026-09-16T11:35:08.133566-07:00, time filed None, text from entry

### 20. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-16: undetermined, rows [90159, 90179]

- **Row 90159**, object 478195380, kept (the entry): HARD COPY RECEIVED from Amicus Appellant Restoring Integrity and Trust in Elections Inc - Amicus Brief. Copies: 7. Received: 11. (KEL)
  - entry number None, created 2026-09-16T08:48:37.789227-07:00, time filed None, text from entry
- **Row 90179**, object 478230500, folds into the other (the twin): HARD COPY RECEIVED from Amicus Appellant Restoring Integrity and Trust in Elections Inc - Amicus Brief. Copies: 7. Received: 11. (KEL) [Entered: 09/16/2026 11:48 AM]
  - entry number 48, created 2026-09-16T11:35:08.223359-07:00, time filed None, text from entry

### 21. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-17: cross-run, rows [90205, 91351]

- **Row 90205**, object 478422666, kept (the entry): HARD COPY RECEIVED from Amicus Appellant America First Policy Institute - Amicus Brief. Copies: 7. (JD)
  - entry number None, created 2026-09-17T13:43:35.044108-07:00, time filed None, text from entry
- **Row 91351**, object 479305484, folds into the other (the twin): HARD COPY RECEIVED from Amicus Appellant America First Policy Institute - Amicus Brief. Copies: 7. (JD) [Entered: 09/17/2026 04:09 PM]
  - entry number 49, created 2026-09-24T12:05:52.163548-07:00, time filed None, text from entry

### 22. United States v. Secretary Commonwealth of Pennsylvania (Third Circuit), 2026-09-23: cross-run, rows [91090, 91356]

- **Row 91090**, object 479082481, kept (the entry): Appellees Common Cause, Joel Dickson, Trisha Kent, League of Women Voters of Pennsylvania, Nicholas Maston, Gregory Perry, Lior Sternfeld, Todd Thatcher and John Thompson verbally granted an extension of time to file brief until 10/22/2026 pursuant to 3d Cir. L.A.R. 31.4. (EAF)
  - entry number None, created 2026-09-23T09:23:19.626293-07:00, time filed None, text from entry
- **Row 91356**, object 479305491, folds into the other (the twin): Appellees Common Cause, Joel Dickson, Trisha Kent, League of Women Voters of Pennsylvania, Nicholas Maston, Gregory Perry, Lior Sternfeld, Todd Thatcher and John Thompson verbally granted an extension of time to file brief until 10/22/2026 pursuant to 3d Cir. L.A.R. 31.4. (EAF) [Entered: 09/23/2026 01:43 PM]
  - entry number 54, created 2026-09-24T12:05:52.426993-07:00, time filed None, text from entry

### 23. League of Women Voters v. U.S. Department of Homeland Security (D.D.C.), 2026-09-29: cross-run, rows [93145, 93225]

- **Row 93145**, object 479853687, folds into the other (the twin): Order on Motion to Enforce Judgment
  - entry number None, created 2026-09-29T14:36:36.368705-07:00, time filed 17:25:32, text from document
- **Row 93225**, object 479868690, kept (the entry): MINUTE ORDER: On September 25, 2026, the Supreme Court stayed this Court's 112 June 22, 2026, Order. See Dep't of Homeland Sec. v. League of Women Voters, No. 26A308, slip op. at 6–7 (U.S. Sept. 25, 2026). The stay is in effect "pending the disposition of appeal" to the D.C. Circuit and disposition of a petition for a writ of certiorari. Id. at 6. A stay operates by "temporarily divesting an order of enforceability." Nken v. Holder, 556 U.S. 418, 428 (2009); see also Dep't of Homeland Sec. v. D.V.D., 145 S. Ct. 2627, 2629 (2025) (explaining that following the Supreme Court's grant of a stay pending appeal, the district court's remedial order "cannot . . . be used to enforce an injunction that our stay rendered unenforceable"). While the stay remains in effect, the Court therefore cannot grant the requested relief compelling compliance with this Court's June 22, 2026, Order. Accordingly, the Court DENIES the Plaintiffs' 128 Motion to Enforce Summary Judgment Order without prejudice to renewal should the judgment become enforceable in light of further appellate proceedings. The Court further VACATES the July 20, 2026, Minute Order ordering weekly joint status reports on the status of the appeal in Florida v. DHS, No. 3:24-cv-509 (N.D. Fla.) in the Eleventh Circuit. Signed by Judge Sparkle L. Sooknanan on 9/29/2026. (lcsls1)
  - entry number None, created 2026-09-29T16:31:22.541314-07:00, time filed None, text from entry

