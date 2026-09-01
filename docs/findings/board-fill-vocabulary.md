# The map's fill vocabulary against the line beneath it

**Status: DECIDED 2026-09-01: option 4, `c322259`.**

Measured 2026-08-20 against a production build at `e677481`, from the emitted DOM and
from `/campaign`, not from either component's comments.

---

## The disagreement

The map paints **three** postures. The line directly beneath it names **five** figures,
six when the conditional one fires:

> 31 of 51 jurisdictions sued · 26 active · 5 ended · 12 continued elsewhere · 2 quiet · 3 ended, no link asserted

A reader who takes the line as a key for the map above it goes looking for three fills
that are not there.

## What the map paints, and what it does not

| | n | carried by |
| --- | --- | --- |
| `--c-litigation` | **26** | AZ CA CO GA HI ID IL KY ME NM NY OR PA UT VA WA WI WV · CT DC DE MA MD NH RI VT |
| the dimmed `color-mix` | **5** | MI MN NV OK · NJ |
| `#1f1f1f` | **20** | AK AL AR FL IA IN KS LA MO MS MT NC ND NE OH SC SD TN TX WY |

51 exactly. The other three figures in the line are read off `/campaign`, where they are
already rendered as per-cell glyphs (`↑` appeal, `↻` refile, `●` dormant, `†` unlinked):

| overlay | n | cells |
| --- | --- | --- |
| continued elsewhere | **12** | 11 appeals AZ CA CT KY MD NH NM NY OR PA VA · 1 refile GA |
| quiet | **2** | HI ID |
| ended, no link asserted | **3** | CO DC IL |

**17 cells carry an overlay, and not one carries two.**

## The finding that decides the shape of the answer

**Continued elsewhere and quiet are not postures. They are overlays on cells the map
already paints.**

- `quiet` ⊂ active — 2 of the 26, by construction: `dormant` requires `status === "active"`.
- `chained` ⊂ active ∪ ended — 12 of the 31. **Measured today all 12 are active**, but that
  is data and not structure: `chain` needs `predecessors.length && live`, and `live` may be
  terminated, so a chained-and-ended cell is reachable.
- `unlinked` — 3, and orthogonal to both.

So the map is not missing three postures. It is missing two overlays and one alarm on
cells whose posture it already shows correctly.

## The constraint

The section's own rule: one property, one meaning. `fill` carries posture. `stroke` is
**reserved for outcome** and the teal layer takes it when it exists, so quiet and
continued-elsewhere cannot have it. The violet dot is spoken for — state bills tracked,
radius scaled. That leaves adding a mark, changing fill, or changing words.

---

## Option 1 — widen fill to five values

**Reject.** It is the option that looks most like "make the map match the line" and is the
only one that makes the map lie.

Because the overlays are not disjoint from the postures, a five-value fill needs a
precedence rule, and any precedence rule silently erases the losing claim. Paint the 12
chained cells "chained" and 12 of 51 jurisdictions stop reporting whether their suit is
live. Michigan is the case that shows the cost from the other side: it is the campaign's
first appellate loss, `ended` with no chain, and a vocabulary that spends its distinctions
on overlays flattens it back toward the cells it was separated from in the first place.

Cost: fill stops meaning posture and starts meaning posture-or-overlay-whichever-wins.
That is precisely the second job the section's rule forbids.

## Option 2 — add a mark

**Reject on measurement, not on taste.** The map has less room than the grid does.

- **3 of the 17** already carry a violet dot with a two-digit numeral centred on the same
  anchor: AZ (41 bills, appeal), GA (39, refile), PA (52, appeal). A second glyph competes
  with a mark whose own geometry is measured at render because a constant offset was not
  good enough.
- **4 of the 17** are 12-px callout squares: CT, MD, NH (appeals) and DC (unlinked). The
  square already holds a two-letter label at `fontSize={12}`. There is no room.
- That is 7 of 17 obstructed. The remaining 10 would work, which is the trap — the marks
  that landed would look fine and the seven that mattered would be the crowded ones.

Cost: a third mark type on a surface with two, for a claim `/campaign` already carries with
room to grade it, and `StateCell`'s own "deliberately small" rule has already been bent once
for `†` with an argument attached.

## Option 3 — narrow the line to what the map can show

Drop `continued elsewhere`, `quiet` and `ended, no link asserted` from the homepage line, so
it reads *31 of 51 jurisdictions sued · 26 live · 5 ended · 20 not sued*, and let the three
overlays live on `/campaign`, where every one of them already renders per-cell.

**Cost: it removes three true figures from the board.** The dormancy count in particular is
a claim the board is well placed to make — a campaign with 2 stalled dockets is a different
campaign from one with 15 — and the link to `/campaign` sits one line below, so the
information is one click away rather than gone. But one click away is not on the board, and
this option makes the summary less informative in order to make it consistent.

## Option 4 — leave the line, and let the key say what the map does not paint

Add one clause to the key: the map's fill carries litigation posture, and the line beneath
also reports chains and dormancy the map does not paint.

**This is the option this unit already built the machinery for.** The key exists, it is in
the register, it carries `data-encoding` on every entry, and `assert-encodings.mjs` joins
named encodings against emitted ones in both directions. A clause naming an encoding that is
deliberately absent is the same statement as the reserved-stroke omission, made out loud.

**And it removes nothing.** Options 1 and 3 both pay in information — one in the map's
posture reading, one in the summary's figures. This one pays in a sentence.

Cost, stated honestly:

- It is a **negative claim in a list of positive ones**. Every other key entry says "this
  mark means this"; this one says "these numbers have no mark". That is a different kind of
  sentence and it will read slightly oddly.
- It does not survive carelessly. If the join assertion is ever extended to check that every
  *figure in the line* is either painted or disclaimed, the clause has to be maintained
  alongside. Today nothing enforces it.
- It leaves 26 + 5 = 31 sitting beside a five-term line, so the reader still has to read the
  clause to resolve it. It fixes the ambiguity by explaining it rather than by removing it.

---

## Recommendation: option 4, with option 3 second

The defect is **not** that the board reports more than the map paints. It is that nothing
tells the reader which of those figures the map is painting. Option 4 addresses exactly
that; options 1 and 3 address it by deleting one side of the mismatch.

Option 3 becomes the better answer if the clause turns out not to be readable in place — if
a negative entry in the key genuinely confuses more than the mismatch did. That is a
question about rendered copy and should be settled by looking at it, not by arguing about
it here.

**What would flip me to option 2:** the overlay counts growing enough that they stop being
exceptions. At 12 chains and 2 quiet out of 51, a glyph marks a minority. If chains passed
roughly half the sued cells, a map that cannot show them would be hiding the campaign's
dominant shape, and the crowding cost would be worth paying on the 10 unobstructed cells
with a stated limitation on the 7.

**Corey decides.** Nothing is implemented.
