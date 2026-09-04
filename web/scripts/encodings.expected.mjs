/**
 * THE EXPECTED ENCODING SET — the one side of the join the page cannot vote on.
 *
 * `assert-encodings.mjs` used to compare two sets, EMITTED and NAMED, and both are read
 * out of the same rendered document. That is a SELF-JOIN: it proves the page is
 * internally consistent, which is worth proving and is not the same as proving the page
 * is right. A commit that drops a mark from the paint AND its row from the key moves
 * both sides together, and the join goes on passing at a smaller number with nothing to
 * compare that number against. Every check in that file would stay green while an
 * encoding the record depends on quietly left the product.
 *
 * This file is the third side, and its authority comes from being written by hand, from
 * the spec, and from NOT being derived from any render. Nothing generates it; a script
 * that regenerated it from the DOM would reintroduce the self-join with an extra step.
 *
 * WHAT A FAILURE HERE MEANS — and it is a question, not a verdict. A divergence is
 * either a defect (the page stopped painting something) or a deliberate change (the set
 * really did move). The script cannot tell those apart and does not try. It names the
 * direction and stops; a human rules, and if the ruling is "deliberate", this file is
 * edited IN THE SAME COMMIT as the paint, which is the precedent the milestone-marker
 * row set: paint, key row and expected row all landed together and the join moved 9→10
 * atomically with nothing red in between.
 *
 * PROVENANCE IS PART OF THE ROW. `paint` is where the mark is drawn, `key` is where it
 * is named, `since` is the commit that introduced it. All line numbers are pinned to
 * `b468644` and WILL drift — they are a starting point for a reader, never an assertion;
 * nothing in the script reads them. The `since` hashes are the durable half and are all
 * ancestors of origin/main.
 *
 * ONE ROW-SHAPE CAVEAT, worth knowing before trusting the table. The six `stage-*`
 * encodings DO NOT APPEAR AS LITERALS ANYWHERE IN THE SOURCE. `stageEncoding()` builds
 * them as `stage-${STATUS_LABELS[code].toLowerCase()}`, so a rename of a status label
 * silently renames an encoding, and `git log -S"stage-passed"` finds nothing. Their
 * `since` is the commit that introduced the mechanism rather than the string. This
 * fixture is the only place those six strings are written down, which is most of the
 * reason it is worth having for that route.
 */

/** Board — `/`. Ten encodings: three map postures, one map dot, six chart marks. */
export const BOARD = [
  // The map's three fills. One paint site serves all three: `postureAt` picks the fill,
  // so they are distinguished by value and not by call site.
  { encoding: "posture-live", paint: "RecordsMap.tsx:250,293", key: "SourceLegend.tsx:116", since: "c6a551d" },
  { encoding: "posture-ended", paint: "RecordsMap.tsx:250,293", key: "SourceLegend.tsx:119", since: "c6a551d" },
  { encoding: "posture-none", paint: "RecordsMap.tsx:250,293", key: "SourceLegend.tsx:122", since: "c6a551d" },
  { encoding: "state-bill-dot", paint: "RecordsMap.tsx:447", key: "SourceLegend.tsx:126", since: "c6a551d" },

  // The chart. Five SVG marks and one that is not SVG at all.
  { encoding: "filings-cumulative", paint: "RecordsBoard.tsx:279", key: "SourceLegend.tsx:143", since: "c6a551d" },
  { encoding: "filing-date-dot", paint: "RecordsBoard.tsx:290", key: "SourceLegend.tsx:158", since: "c6a551d" },
  { encoding: "state-bills-monthly", paint: "RecordsBoard.tsx:309", key: "SourceLegend.tsx:169", since: "c6a551d" },
  { encoding: "legislation-monthly", paint: "RecordsBoard.tsx:314", key: "SourceLegend.tsx:180", since: "c6a551d" },
  { encoding: "executive-order-tick", paint: "RecordsBoard.tsx:328", key: "SourceLegend.tsx:196", since: "c6a551d" },
  // THE ONLY HTML MARK. It is the reason the emitted side has a third root, and the
  // reason that root reads an encoding by name rather than classifying it by paint.
  { encoding: "milestone-marker", paint: "RecordsBoard.tsx:398", key: "SourceLegend.tsx:214", since: "f0dcc5d" },
];

/**
 * `/state-bills` — six stage encodings, one per rung of the ramp.
 *
 * `paint` here is where a MARK claims a stage (`data-stage`), which is a different
 * attribute from the `data-encoding` the key header carries; both are listed because
 * the join's two sides genuinely come from two places on this route.
 */
export const STATE_BILLS = [
  { encoding: "stage-introduced", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
  { encoding: "stage-engrossed", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
  { encoding: "stage-passed", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
  { encoding: "stage-enrolled", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
  { encoding: "stage-vetoed", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
  { encoding: "stage-failed", paint: "StateMatrix.tsx:72 / StateBillRow.tsx:49", key: "StateMatrix.tsx:90", since: "10696c5" },
];

/**
 * `unstaged` is deliberately ABSENT from the list above, and its absence is a claim.
 *
 * It is what a row claims when its status is outside the ramp, and live data has never
 * held one — 484 rows, all in 1–6. It is therefore not an encoding the key owes an
 * entry, and the script already excludes it from the emitted side by name. Listing it
 * here would make the reconciliation demand paint that by design never appears.
 */
export const NOT_ENCODINGS = ["unstaged"];

export const EXPECTED = { board: BOARD, stateBills: STATE_BILLS };

/** Just the names, which is all the reconciliation needs. */
export const names = (rows) => rows.map((r) => r.encoding).sort();
