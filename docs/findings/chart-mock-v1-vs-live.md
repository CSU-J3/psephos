# Chart mock v1 against the shipped chart — the delta record

**What this file is.** `docs/design/psephos-chart-mock-v1.html` (2026-09-04) is the mock the
chart redesign was drawn against, and it is **historical as of handoffs 93 and 97**. Handoff 93
shipped the lettering thesis the mock argues for; handoff 97 (`a63eba3`) added a teal cumulative
outcome series the mock never drew. This file records where the two now disagree, so a later
reader who opens the mock knows which side is current.

**It is a delta record, not a work queue.** Nothing below is scoped, prioritised or owed. The
mock is not patched — a design file is a dated statement of intent, and editing it to agree with
the code destroys the only evidence of what was decided when.

Read-only pass at `843fc94`, comparing the mock against `web/lib/board.ts`,
`web/components/RecordsBoard.tsx`, `web/components/SourceLegend.tsx` (`BoardKey`) and the
`.board-*` block in `web/app/globals.css`. Nothing was rendered; see *Container widths* for the
one item that closes only in a browser.

---

## Contradictions — the mock draws or states something the live chart now denies

1. **The teal series does not exist in the mock.** Live `RecordsBoard.tsx:317` draws
   `outcomePath` at `stroke="var(--c-outcome)"`, `strokeWidth 1.5`, inside the same clip as the
   red line. The mock's `geometry()` has five marks and none of them is this. The mock is one
   series short in exactly the vertical band where it puts its chip and its line-anchored
   markers.

2. **One terminal chip in the mock, two live.** Mock: a single `.chip` "31 of 51". Live:
   `.board-chip` (red total) plus `.board-chip.outcome` ("N rejected", teal ink, teal-tinted
   border), both on the same anchor point. The mock has no model for two chips on one edge and
   no collision rule between them.

3. **The chip is scrubber-bound, not right-edge-bound.** Mock pins at the fixed `X(W-PADR-8)`.
   Live pins at `pctX(PAD_L + clipW)` — the frame's leading edge. The mock's position describes
   only the final frame.

4. **The mock has no replay at all.** No clip rect, no `Frame`, no `visibleAt`, no leading-edge
   rule. Live gates every data layer on `clipPath#board-frame` and gates markers and captions on
   the frame in the label layer. Three live behaviours have no mock counterpart: `.leads`
   (`clipW < 90`, flip right), `.below` (`yOfTotal < 44`, drop below), and `.outcome`
   deliberately never taking `.below`.

5. **Milestone 3 is a different fact.** Mock: `Apr 28, 2026 — first record demand rejected`,
   anchored `"line"`. Live: `2026-01-15`, `first court rejection on the record (California)`,
   anchored `"axis"`. Date and anchor both changed — the caption was falsified, and a dismissal
   cannot ride a line that counts filings. Milestones 2 and 4 match on date and anchor;
   milestone 1 matches in position but the mock calls the anchor `"base"` where live calls it
   `"axis"`.

6. **Two violets vs one.** Mock declares `--c-state` / `--c-state-dim` for the bars and a
   separate `--c-fed` for the federal line — distinct hues, hard-coded hex, dark-panel-specific.
   Live uses one token, `--c-legislation`, for both, separated by opacity (bars 0.78, line 0.5)
   and by mark type. That pair is the whole gap.

   **An earlier draft of this list cited `globals.css:52` as a third arrangement of the same
   hues. It is not one.** That comment's "two steps either side of `--c-legislation`" describes
   the `--leg-bright` / `--leg-dim` **`/state-bills` stage ramp** — the block says so in its own
   first sentence and points at `STAGE_STYLE` in `web/lib/statebill.ts` — and the chart takes
   neither token. Checked at `843fc94`, with the whole comment open rather than the one clause.

7. **Every geometry constant but two disagrees.**

   | | mock | live |
   |---|---|---|
   | viewBox | `0 0 900 300` | `0 0 900 260` |
   | left pad | 34 | 34 ✓ |
   | right pad | **64** | **16** |
   | axis y | `BASE` 186 | `AXIS_Y` 130 |
   | ceiling y | `TOP` 26 | `yOfTotal(51)` = 12 |
   | below-axis depth | `BARH` 84 | `H_BOT` 96 |

   The mock's 48 extra units of right pad exist to park the terminal chip and end dot inside the
   box. Live pins the chip to the scrubber instead and needs 16.

8. **Rail alignment is opposite.** Mock `.lbl.rail` is `translate(0,-50%)` at `left:2px` —
   left-aligned. Live `.board-lbl.rail` is `translate(-100%,-50%)` at `pctX(PAD_L - 6)` —
   right-aligned to the rail, mirroring the `textAnchor="end"` it replaced.

9. **Axis labels sit in different boxes.** Mock escapes with `bottom:-22px`. Live stays inside
   the percentage system at `pctY(AXIS_Y + H_BOT + 22)` = 248 of 260 (95.4%) — which is what the
   `+34` in `H` reserves room for.

10. **EO ticks: mock 24 units tall at `strokeWidth 2.5`, live 14 at 1.5.** Live also clips them
    (replay-gated) and gives each a `<title>`; the mock does neither.

11. **The filing-date dot vocabulary is absent from the mock.** Live draws one dot per distinct
    filing date, dim (r2 / .42) with a 31-day lit window (r3.4 / 1.0), and gives it its own key
    row. The mock draws one circle: the terminal dot, r4.5.

---

## Lettering — the mock's design is honoured, with one deliberate notch and one figure now historical

Mock to live, all mono: `.lbl` 12px to `.board-lbl` 12px ✓ · minor 11px to 11px ✓ · `.chip`
13px/600 to `.board-chip` 13px/600 ✓ · `.ms` 18px circle / 11px numeral to `.board-ms` 18/11 ✓ ·
`.caps .n` 10px in a 16px circle ✓. Greys were re-picked (`#7c7c85` to `#737373`, `#55555c` to
`#525252`) but not re-designed.

The one size difference: **`.caps` 12px in the mock, `.board-caps` 13px live** — one notch up,
and **deliberate**, consistent with the v42 homepage type scale, which shipped 09-03, after the
mock was written. It is not a miss to correct.

**The "axis 8.4px post-ratio-fix" figure is pre-redesign and is now historical on both sides.**
8.4px was what a 13-user-unit SVG label rendered at when the chart shared the board row at 584px,
after the C6 ratio notch. Neither file has SVG text any longer. Live axis lettering is a fixed
12px CSS (11px minor), width-independent by construction — which is the whole thesis the two
files share.

---

## The narrow rule — one mechanism, two numbers, both inside the mock

Mock demos a hand-applied `.narrow` class at 520px; live implements a real container query at
`@container boardchart (max-width: 560px)`. Both drop `.axis.minor` and nothing else, so the rule
itself is intact and live is not in doubt: **the live threshold is 560**.

The 520/560 split is **an internal property of the mock, not a mock-vs-live gap**. The mock's
prose says 560 and its own CSS demos 520, so a builder reading only its stylesheet would take the
wrong threshold from it. Recorded here for that reader. The mock is not patched.

---

## Container widths — the disagreement is recorded, not settled

The mock renders at **740 / 883 / 520** and names them (the shared row, the 3xl column, a narrow
case). The live source comments name **584px** and **857px** as the two measured arrangements.
The v42 reflow — chart beside map at a board width of 1080px or more — shipped after the mock.

**The two files disagree, and this pass did not settle which is current.** Doing so needs a
browser at a set of widths, and this was a read-only pass. Stated and stopped, rather than
guessed at.

---

## The mock's four open questions — three answered by shipped code

- *The milestone set.* Changed on the record (contradiction 5 above); curation done.
- *Caption strip always-on vs hover-reveal.* **Always-on**, via a mechanism the mock did not
  propose: `visibility:hidden` on unreached entries holds the strip's height identical across all
  23 frames, which `assert-layout` asserts.
- *Terminal chip replaces or complements the header stat.* **Complements.** Both ship — the
  header carries "N of 51 jurisdictions sued", the chip carries "N of 51".
- *Bar/line geometry fidelity.* **Moot**, and the mock said this was not its question anyway.
  `board.ts` derives the domain, the steps and `monthlyMax()` from rows; the mock's `MONTHS=20.4`,
  `BARMAX=70` and literal traced arrays have no live counterpart to be faithful to.

---

## One item where live exceeds the mock rather than contradicting it

The mock's point 2 — delete the in-chart series labels, the key already names them — is done, and
`BoardKey` now names all six chart encodings with `data-encoding` attributes that
`assert-encodings` joins against the paint in both directions. The mock could not have specified
that; it did not exist yet.
