# R1: the blind re-reads, 2026-10-03

**Status: READ BLIND (Corey's rulings, 2026-10-03, ruling 3).** The control: 2 of the 6 splits changed outcome, so the rule written on 2026-10-03 gives **a**: batching is adopted for the 239, every split still goes to Corey, and his random check grows from five to ten, drawn from the batched unanimous passes.
Pair 23 read **unanimous** blind. The rule's 7 read 7 of 7 unanimous blind.

## How they were read

- **Every reader started from the launcher** (`tools/reader_launcher.txt`, sha256 `b6f45a4c2975`), rendered for its lens and its file, as its whole start message.
  - Each was launched by the Agent tool, one pair a reader, three readers a pair, one lens each.
  - Each file held one pair, named by its content hash.
  - A linked pair's own link was hidden: the state the 2026-10-02 reads saw.
- **A canary on an empty file went first and passed** (`docs/reads/2026-10-03-blind-rereads-canary.json`).
- **Every reader passed the check** (`python -m tools.reader_launch check`):
  - its start message was the launcher, byte for byte, with nothing before it;
  - nothing else reached it but the harness's hand-back note;
  - it saw no pair id outside its own file;
  - it used only Read, on its own file, and the hand-back.
  - Records: `docs/reads/2026-10-03-blind-control.json` and `docs/reads/2026-10-03-blind-links.json`.
- **The control's files are the primed control's records, unchanged**, so the two differ in how they were launched, not in what was read.
- **Launched in waves.** The Agent tool runs 20 subagents at once, so 12 of the 42 started once others had finished. That is recorded, and no reader was launched twice.

## 3a. The control

Each cell gives the three lenses, identity / alternative match / clocks (y yes, u uncertain, n no).

| pair | recorded | primed control | blind | blind outcome | changed | tokens |
|---|---|---|---|---|---|---|
| 2026-10-01 sample n=3 | split | split | y / y / u | **split** | no | 185,298 |
| 2026-10-01 sample n=8 | split | split | y / y / y | **unanimous** | **yes** | 176,168 |
| person pair 4 | split | unanimous | y / y / y | **unanimous** | **yes** | 159,963 |
| person pair 5 | split | split | y / y / u | **split** | no | 131,175 |
| person pair 15 | split | split | y / y / u | **split** | no | 186,490 |
| person pair 22 | split | split | y / y / u | **split** | no | 172,448 |

**2 of 6 changed: 2026-10-01 sample n=8, person pair 4.** The rule, as written on 2026-10-03, before any read:
- **a.** At least 2 change: splits are unstable under any re-read. Adopt batching for the 239. Every split still goes to Corey, and his random check grows from five to ten, drawn from the batched unanimous passes.
- b. All 6 reproduce: do not batch.
- c. Exactly 1 changes: stop with the reads laid out.

**So a.**

- Blind and primed agree on 5 of the 6.
- The blind read moved one pair the primed read had kept: the 2026-10-01 sample's n=8, to unanimous.
- Pair 22, the read the primed control's branch turned on, read split again, blind.

## 3b. Pair 23

| pair | rows | 2026-10-02 (named in its brief) | blind | blind outcome | tokens |
|---|---|---|---|---|---|
| pair 23 | 93145/93225 | y / y / y | y / y / y | **unanimous** | 144,417 |

Its link stands on the direct read of the order's text either way (ruling 3b). The blind reads are unanimous.

## 3c. The rule's 7

Their links rest on their 2026-10-02 full read, every read of which section 2 lists.

| pair | rows | 2026-10-02 | blind | blind outcome | tokens |
|---|---|---|---|---|---|
| rule pair 1 of 7 | 5677/5689 | y / y / y | y / y / y | **unanimous** | 144,860 |
| rule pair 2 of 7 | 12886/12894 | y / y / y | y / y / y | **unanimous** | 124,043 |
| rule pair 3 of 7 | 17161/17167 | y / y / y | y / y / y | **unanimous** | 127,355 |
| rule pair 4 of 7 | 57249/57258 | y / y / y | y / y / y | **unanimous** | 134,313 |
| rule pair 5 of 7 | 67589/67651 | y / y / y | y / y / y | **unanimous** | 129,703 |
| rule pair 6 of 7 | 77471/77602 | y / y / y | y / y / y | **unanimous** | 137,466 |
| rule pair 7 of 7 | 87130/87131 | y / y / y | y / y / y | **unanimous** | 115,364 |

**All 7 read unanimous blind**, so their links rest on a blind full read.

## 4. The method for the 239, and the price

**The method follows the blind control: batching.** It must launch blind like these reads: from the launcher, by the Agent tool, in waves of at most 20 readers.

| | tokens |
|---|---|
| the blind control, 18 reads | 1,011,542 (56,197 a read) |
| pair 23 and the rule's 7, 24 reads | 1,057,521 (44,063 a read) |
| all 42 blind reads | 2,069,063 (49,263 a read) |
| the primed control, 18 reads, for comparison | 714,359 (39,687 a read) |
| the 239 batched, at the calibration's rate | about 6.16 million |

**The two channels' figures are not like for like.**
- A blind reader starts from less: 30,269 tokens (median of 42), against 34,322 for a Workflow reader, with no brief relayed.
- It takes one more request. A Workflow reader stops at its structured answer, the second request. A blind reader hands back its report, then takes a closing turn whose context carries everything before it, its reasoning included.
- The measure, a reader's final context, counts that turn. So the same work shows larger for a blind reader: 56,197 a read against 39,687, on the control's identical files.
- **So the 239 batched under the blind launch is not priced here.** The calibration's 6.16 million was read through the Workflow channel. The batch's first wave will measure the blind rate.

## The tallies after the blind reads

- **Candidates:** the 2026-10-01 sample's n=8 and person pair 4, unanimous blind.
- **Corey's split list:** n=3 and person pairs 5, 15 and 22. Pair 22 is refused and stays unlinked either way.
- **Linked, on blind reads:** pair 23 and the rule's 7.
- **Out of the tallies until read blind (ruling 2):** the 2026-10-01 sample's other 18 candidates and the person batch's other 19, 37 pairs. With the 239, that is 276 pairs.
