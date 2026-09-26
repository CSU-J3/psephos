/**
 * The reconciliation's set arithmetic, pure, so it can be tested without a browser.
 *
 * assert-encodings.mjs compares the hand-written expected set (encodings.expected.mjs)
 * against what the page emits and what its key names, in four named directions. The
 * sets come from Chromium; the comparison does not need to. It lives here so that
 * components/StateMatrix.test.ts can feed it markup rendered from a fixture and watch a
 * mutation turn it red, which the script alone can only show against a running server.
 *
 * CONDITIONAL ROWS. An expected row may carry `when`: a sentence naming the data that
 * makes the encoding appear. The first is `unstaged`, whose key entry and marks render
 * only while some bill has no stage the ramp knows. Such a row is expected in a render
 * that emits it or names it, AND whenever an independent WITNESS says the data holds one
 * -- and once expected it is held to all four directions like any other row.
 *
 * WHY THE WITNESS, and it is the whole of this row's value. Without it the page would
 * vote on its own expected set: a render that dropped the branch whole -- a null status
 * coerced into a stage, or the bill excluded before the matrix is built -- shows neither
 * the key entry nor a mark, and a row expected only when present would pass it. That is
 * the silent shrink the third side exists to catch. The witness is counted from data the
 * page's code never touches (see offRampCount), so it can demand what the page dropped.
 *
 * Why not the two simpler shapes: an UNCONDITIONAL row reds the day the last status-less
 * bill is given a status and the page correctly stops showing the branch; a DROPPED row
 * reds `emitted but not expected` on every day the page correctly shows it.
 *
 * @param {{encoding: string, when?: string}[]} expectedRows
 * @param {Iterable<string>} emitted    encodings the page's marks claim
 * @param {Iterable<string>} named      encodings the page's key names
 * @param {Iterable<string>} [witnessed] conditional encodings the data says must appear
 */
export function reconcileSets(expectedRows, emitted, named, witnessed = []) {
  const em = [...new Set(emitted)].sort();
  const nm = [...new Set(named)].sort();
  const emSet = new Set(em);
  const nmSet = new Set(nm);
  const wSet = new Set(witnessed);
  const present = (r) => emSet.has(r.encoding) || nmSet.has(r.encoding) || wSet.has(r.encoding);
  const conditionalAbsent = expectedRows
    .filter((r) => r.when && !present(r))
    .map((r) => r.encoding)
    .sort();
  const exp = expectedRows
    .filter((r) => !r.when || present(r))
    .map((r) => r.encoding)
    .sort();
  const expSet = new Set(exp);
  return {
    expected: exp,
    emitted: em,
    named: nm,
    conditionalAbsent,
    emittedNotExpected: em.filter((e) => !expSet.has(e)),
    expectedNotEmitted: exp.filter((e) => !emSet.has(e)),
    namedNotExpected: nm.filter((e) => !expSet.has(e)),
    expectedNotNamed: exp.filter((e) => !nmSet.has(e)),
  };
}

/**
 * THE RAMP, WRITTEN OUT A SECOND TIME ON PURPOSE. It mirrors STAGE_ORDER in
 * web/lib/statebill.ts, and components/StateMatrix.test.ts asserts the two agree. It is
 * not imported from there because the witness must not share the page's code: a defect
 * in stageOf -- a null coerced into Introduced, say -- would move a derived witness in
 * step with the page, and a witness that moves with its subject witnesses nothing.
 */
export const RAMP_CODES = ["1", "2", "3", "4", "5", "6"];

/**
 * The witness for `unstaged`: how many bills carry a status outside the ramp -- null or
 * an unmapped code -- in `data/state_bills.json`, which export/snapshots.py writes from
 * Turso on every collect run and which no web code reads.
 *
 * A STATED EXCEPTION TO A STANDING INVARIANT (ruled 2026-09-26). docs/status.md's standing
 * invariants say: "Database facts come from direct Turso queries, never from JSON
 * snapshots. Snapshots are a lagging derivative and can produce false greens. This
 * applies to the orphan alarm, the supersession invariant, and anything else asserting a
 * row's state." This witness asserts a row's state from the snapshot anyway, and the
 * exception rests on two facts.
 *   - The snapshot is a FULL-TABLE export for this question. build_state_bills is
 *     `SELECT * FROM state_bills`, one object per row with its raw `status`, so a bill
 *     with a null status and no items still exports -- pinned in tests/test_export.py.
 *     That meets the orphan alarm's ground, which is structural: items with no
 *     state_bill_id have no row to hang on, so no per-bill snapshot can show them. A
 *     state bill IS the row. The invariant's other ground, LAG, does reach this witness;
 *     it is the cost below.
 *   - The Python export path is INDEPENDENT of the web classifier, which is why it was
 *     chosen: a defect in stageOf or getStateBills cannot move it. A direct Turso read
 *     would be independent too, but this lane's check steps carry no credentials, and
 *     dom-checks.yml keeps them to two steps on purpose.
 *   - CONSIDERED AND DECLINED (ruled 2026-09-26): giving the check steps TURSO_READ_TOKEN
 *     and counting directly would retire both this exception and the lag. Declined
 *     because a render check holding database credentials widens the lane's credential
 *     surface to save a lag the next data commit clears.
 * ITS COST IS THE LAG WINDOW. It is the snapshot at the checked-out head, while the page
 * reads Turso live, so the two can disagree for the minutes between a state run's write
 * and its data commit. In that window it can red falsely: a snapshot still holding a
 * status-less bill that live data has just given a status demands a row the page
 * correctly no longer shows, and the next data commit clears it. And it can green
 * falsely, the invariant's own failure: a status-less bill written after the export, on a
 * page that has dropped the branch, is demanded by neither side. When the page and the
 * witness disagree, the failure line prints the page's count, the snapshot's count and
 * the snapshot's generated_at.
 *
 * @param {{status?: string | null}[]} bills
 */
export function offRampCount(bills) {
  return bills.filter((b) => !RAMP_CODES.includes(b.status ?? "")).length;
}
