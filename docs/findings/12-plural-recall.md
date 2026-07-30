# 12 — plural recall and inverted voter constructions

Offline measurement against `data/masterlist_corpus.json` (37,388 bills, nine states),
zero API. It asked two questions in sequence: should the election filter tolerate plural
forms, and — once bare `voters` was rejected — are the genuine bills it would have caught
reachable another way. Both answered cleanly. The shipped changes are the phrase-only
plural rule (handoff 12 Part A) and four inverted-construction phrase terms (Part C). This
records why bare `voters` stayed out and where phrase recall hits its ceiling.

## Framing

The plural probe found that global plural tolerance buys 74 bills, but 56 of them come
from one bare token (`voter` → `voters`) at ~45% precision and 19 from four phrase terms
at ~95%. Part A shipped the split: **phrase terms** (those with a space) tolerate a plural
on the last word, **bare tokens** stay exact. The measured baseline moved 454 → 473 (+19,
distributed exactly as predicted: election official +11, primary election +5, election
audit +2, mail ballot +1). This document covers what happened to the 56 bare-`voters` bills.

## Part B — bare `voters` is unrecoverable

The 56 bills bare-`voters` would add split **25 genuine / 31 noise (45% precision)**. The
question was whether a small set of targeted exclusions could lift the genuine fraction to
viability (~85%) without costing the genuine bills. It cannot. Per-candidate, measured
against the 56 (a bill is "removed" only if redacting the candidate kills its `voters` hit):

| Candidate exclusion | Removes | Noise | Genuine cost | Verdict |
| --- | ---: | ---: | ---: | --- |
| `voters of` | 11 | 11 | 0 | adoptable |
| `league of women voters` | 3 | 3 | 0 | adoptable (⊂ `voters of`) |
| `general obligation bond` | 0 | 0 | 0 | no effect |
| `standard time` | 0 | 0 | 0 | no effect |
| `daylight saving` | 0 | 0 | 0 | no effect |
| `bond election` | 0 | 0 | 0 | no effect |
| `ad valorem` | 0 | 0 | 0 | no effect |

The five topical candidates remove **nothing**: in those bills the `voters` token sits in a
different clause ("allowing **voters** to indicate a preference for observing year-round
standard time"), not next to "standard time" or "bond", so redacting the topic phrase
leaves the match standing. Only a phrase containing `voters` itself (`voters of`) drops
anything. Adopting the one zero-cost candidate leaves a **residual of 45 of 56 — 25
genuine / 20 noise, 56% precision**. Short of viable, and it does not improve, because:

**The collision is the finding.** The residual noise clusters on `voters at a[n] election`
(bond and water-board elections). The genuine bills the recovery is *for* include
`registration of voters at a polling place`. Those two share surface form — anchor token
`voters`, preposition `at a`, then a noun that only context distinguishes (an *election* vs
a *polling place*). No exclusion keyed on `voters at a` can drop the bond bills without
also dropping the registration bills. Bare `voters` cannot be made precise, so it stays out.

## Part C — the genuine bills are reachable at phrase precision

Rejecting bare `voters` does not mean the 25 genuine bills are lost. Most match on
multi-word constructions the term list simply did not contain — reachable at phrase
precision with no bare token. Measured over the 473 baseline, handoff-9 discipline (every
added title, precision). **Every added bill fell inside the genuine 25; zero noise across
the full corpus:**

| Term | +bills | Added (all genuine) | Precision |
| --- | ---: | --- | ---: |
| `registration of voters` | 5 | GA HB661, GA SB562, TX HB568, TX HB425, TX HB1855 | 100% |
| `registered voters` | 2 | GA SB568, TX HB2245 | 100% |
| `eligible voters` | 2 | GA SB568, TX HB2082 | 100% |
| `provided to voters` | 2 | WI SB205, WI AB207 | 100% |
| `voters with disabilities` | 0 | — | — |

**Union: 10 unique genuine bills recovered at 100% precision.** All four are phrases, so
they inherit the Part A plural rule (a no-op here — already plural). Adopted; baseline
483 (473 + 10). `registered voters` and `eligible voters` are the watch terms — the most
generic surface forms, likeliest to admit bond/tax language if the corpus moves; the flood
negatives are pinned in `tests/test_state.py`. Precision tell confirmed: `registration of
voters` does **not** match TX HB509 ("of *registering* voters", a trespass bill), so the
inverted term stays clean.

## The ceiling — the other 15 stay unreachable, structurally

The 15 genuine bills the four terms do not recover are not a TODO; they are the honest
ceiling of phrase matching. **A phrase term cannot span a variable middle.** The
constructions put a modifier between the anchor words:

- `voters with **a** disability`, `ability of voters with **certain** disabilities`
- `registration of **certain** voters convicted` (the `certain` is exactly why
  `registration of voters` reaches TX HB568 but not TX SB631 / HB3215 / HB4594)
- `**time** for voters`, `**leave** for voters`, `**water** to voters near a polling place`

This is the same shape as the `voters with disabilities` +0 result: the literal plural
phrase does not occur because the real titles inflect the middle. Catching these would
require either a bare token (dead, Part B) or a co-occurrence/scoring model that turns the
matcher into a classifier — out of scope, and its own unit if ever pursued.

## MI `Elections:` title convention — measured and closed

The three MI genuine bills matched on `Elections: voters`, Michigan's structured title
prefix rather than natural phrasing, which raised whether that convention is systematically
under-matched. Measured: of 3,883 MI bills, **75** carry an `Elections:` prefix; the filter
keeps **27 (36%)** and misses **48**. But the 48 missed are dominated by out-of-subject
election *administration* — term of office for elected officials, school-board member
eligibility, candidate replacement, special-election scheduling. Only **3** of the missed
are genuine voter-subject, and those three hinge on bare `voters`, which is dead. There is
no unit left: the convention is not under-matching relevant content, it is correctly
leaving candidate/office/school mechanics out. **Closed**, same as 5b-b.

## Latent — the hyphen gap

`_term_pattern` escapes each phrase whole, so `mail ballot` cannot match "mail-ballot"
(same term/exclude asymmetry the plural gap had). **Zero** hyphenated forms of any phrase
term occur in the corpus, so it is latent, not an active miss. Not worth a commit now.
