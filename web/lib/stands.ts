import type { CampaignRow, Bill, StateBill } from "@/lib/db";
import { isCircuit } from "@/lib/campaign";
import { utcDay } from "@/lib/format";

// Derivations for the "Where this stands" section. Every figure the section states
// is computed here from rows the page already fetched; nothing in this file holds a
// literal, and `docs/gates.yaml` names each function beside the sentence it feeds.
//
// NO `new Date()` IN THIS FILE, and the rule is not decoration. Two of these figures
// are ages -- how long the SAVE Act has been stalled, how long the vehicle has been
// quiet -- and an age computed against the render clock is a different number on
// every page load, drifting away from the record it claims to describe. The clock is
// passed in, and it is the record's own: `MAX(fetched_at)` over items, which reaches
// the page as `collectedAt` and reaches `assert-gates.mjs` as data/generated_at.json.
// Same aggregate, two readers.
//
// THE FUNCTIONS TAKE ROWS, NEVER QUERIES. What population a figure describes is the
// caller's decision and a visible one; see the scope note on docketTotals.

/** The minimum a docket must carry to be counted. Structural rather than a named
 *  import so both `DocketRow` and `CampaignRow` satisfy it without either becoming a
 *  dependency of this file. */
export type DocketLike = {
  court: string | null;
  status: string | null;
  superseded_by: string | null;
  plaintiff: string | null;
};

/** Suits the United States FILED, which is the only population a sentence beginning
 *  "DOJ has sued" may count.
 *
 * SCOPED ON `plaintiff`, EXPLICITLY, AND NOT INHERITED FROM A STATE FILTER. The
 * campaign query's `WHERE state IS NOT NULL` selects the same 49 rows today, and it
 * does so by coincidence: the three rows it drops are stateless BECAUSE their
 * defendant is a federal agency, not because anyone scoped on who sued. Two unrelated
 * properties agreeing today is not a rule, and the failure is silent in both
 * directions -- a DOJ suit naming no state would be dropped from DOJ's own count, and
 * a related suit that acquired a state would be added to it. Both are tested.
 *
 * The vocabulary is two spellings of one party, measured across the table: 43 rows
 * read 'United States' and 6 read 'United States of America'. A prefix test covers
 * both and any third spelling of the same plaintiff. */
export function isDojFiling(row: DocketLike): boolean {
  return (row.plaintiff ?? "").startsWith("United States");
}

/** The dockets DOJ filed. */
export function dojFilings<T extends DocketLike>(rows: readonly T[]): T[] {
  return rows.filter(isDojFiling);
}

/** The dockets DOJ did NOT file: suits brought by civil-society plaintiffs against
 *  federal agencies. They stay in the record and leave the DOJ count -- the section
 *  names them in their own clause rather than dropping them, because a reader who
 *  counts the map and the sentence should be able to reconcile the difference. */
export function relatedSuits<T extends DocketLike>(rows: readonly T[]): T[] {
  return rows.filter((r) => !isDojFiling(r));
}

export type DocketTotals = {
  total: number;
  district: number;
  circuit: number;
};

/** Dockets in `rows`, split district vs circuit.
 *
 * THROUGH `isCircuit`, WHICH CANONICALIZES FIRST, and this is the trap the D0 pass
 * measured rather than guessed. The UW tracker types 'Eighth District' for the
 * Eighth Circuit. A bare /\bcircuit\b/ over `cases.court` does not match it, so the
 * split reads 30/22 where the record says 29/23 -- and both readings look entirely
 * plausible on a page. One row decides it. `isCircuit` runs `canonicalCourt` before
 * the regex; call it rather than re-implementing the test.
 *
 * SCOPE IS THE CALLER'S, and the caller must scope. This counts what it is handed.
 * The section hands it `dojFilings(rows)` -- 49 dockets -- because the sentence it
 * feeds begins "DOJ has sued", and three rows in `cases` are suits against federal
 * agencies in which the United States is the DEFENDANT. One of them is Common Cause
 * v. U.S. Department of Justice. Counting those inside DOJ's own figure reported a
 * suit against DOJ as one of DOJ's filings, which is what the ledger of 52/29/23
 * did. See `isDojFiling`. */
export function docketTotals(rows: readonly DocketLike[]): DocketTotals {
  const circuit = rows.filter((r) => isCircuit(r.court)).length;
  return { total: rows.length, district: rows.length - circuit, circuit };
}

/** Dockets still running: neither terminated nor superseded by a successor.
 *
 * `superseded_by` is set on the DEAD row pointing forward, so a row carrying it is
 * complete however its own status column reads -- a terminated district docket
 * continued as a circuit appeal is finished, not open. Same canonicalization trap as
 * above: read raw, this split reads 10/21 where the record says 9/22. */
export function openSplit(rows: readonly DocketLike[]): DocketTotals {
  const open = rows.filter((r) => !r.superseded_by && !isTerminated(r));
  return docketTotals(open);
}

/** A row the record shows as ended. `status` is the tracker's word and `cases` also
 *  carries a termination date; the campaign rows the page fetches expose the status
 *  string, so that is what this reads. Kept separate from `openSplit` so the
 *  predicate has one home. */
function isTerminated(row: DocketLike): boolean {
  return (row.status ?? "").toLowerCase() === "terminated";
}

export type StateOutcomes = {
  tracked: number;
  failed: number;
  vetoed: number;
};

/** Terminal outcomes among one state's tracked election bills.
 *
 * LegiScan progress codes, via the labels `statebill.ts` already owns rather than a
 * second copy of the mapping: 5 is Vetoed, 6 is Failed. Both are terminal and they
 * are NOT the same event -- a veto is a bill that passed a legislature and was
 * stopped by a governor, a failure is a session ending under it -- so they are
 * counted separately and rendered separately. `tracked` is the denominator and is
 * the count of bills the election filter matched in that state, never a claim about
 * every bill the legislature saw. */
export function stateOutcomes(bills: readonly StateBill[], state: string): StateOutcomes {
  const inState = bills.filter((b) => b.state === state);
  return {
    tracked: inState.length,
    failed: inState.filter((b) => b.status === "6").length,
    vetoed: inState.filter((b) => b.status === "5").length,
  };
}

/** Wisconsin's outcomes -- the state the section names, bound here so the gate has
 *  the single function `docs/gates.yaml` promises rather than a call with an
 *  argument the register cannot see. */
export function wisconsinOutcomes(bills: readonly StateBill[]): StateOutcomes {
  return stateOutcomes(bills, "WI");
}

/** Whole months a bill has sat without an action, as of `asOf`.
 *
 * WHOLE months, floor: the day-of-month has to come round before the count moves, so
 * a bill last touched on the 16th does not read a month older on the 1st. Computed
 * from the calendar fields of two ISO dates -- no epoch arithmetic, because month
 * lengths differ and dividing days by 30 drifts a whole month inside two years.
 *
 * `asOf` is the RECORD's clock, passed in. See this file's header. */
export function monthsSince(value: string | null, asOf: string | null): number | null {
  const then = utcDay(value);
  const now = utcDay(asOf);
  if (then === null || now === null) return null;
  const a = new Date(then);
  const b = new Date(now);
  let months =
    (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth());
  if (b.getUTCDate() < a.getUTCDate()) months -= 1;
  return months < 0 ? 0 : months;
}

/** How long the Senate companion has been stalled.
 *
 * S. 128 is the stall, not H.R. 22. The House bill passed and moved; the Senate
 * companion was read twice, referred, and has not moved since -- so the age that
 * means anything is the referral's. Reads `latest_action_at`, the last LEGISLATIVE
 * action, for the same reason `vehicleQuietSince` does. */
export function saveStallMonths(bills: readonly Bill[], asOf: string | null): number | null {
  const companion = bills.find((b) => b.bill_id === SAVE_SENATE_COMPANION);
  if (!companion) return null;
  return monthsSince(companion.latest_action_at, asOf);
}

/** The Senate companion whose referral date is the stall clock. A bill_id rather
 *  than a title match: short_title is editorial and has already been null on rows
 *  this page reads. */
export const SAVE_SENATE_COMPANION = "s128-119";

/** The date the vehicle bill last took a legislative action, or null if no bill on
 *  the watchlist is flagged as a vehicle.
 *
 * TWO TRAPS, BOTH MEASURED, BOTH PINNED BY TEST.
 *
 * It reads `latest_action_at` and NOT a timeline. S. 1383's timeline carries news
 * items months newer than its last floor action -- 2026-09-02 against 2026-03-26 as
 * this was written -- so a timeline maximum silently reports the date a story ran as
 * the date a legislature acted, under a label that says "quiet since".
 *
 * And it filters the whole list on `is_vehicle`, never `bills.latest`. Reading the
 * newest bill's flag draws correctly only while the vehicle happens to hold the most
 * recent action of the watchlist; the day any other watched bill moves, the figure
 * silently changes subject. That is a defect this repo has already shipped once --
 * see the Vehicle badge entry in the falsified list. */
export function vehicleQuietSince(bills: readonly Bill[]): string | null {
  const vehicles = bills.filter((b) => b.is_vehicle === 1);
  if (vehicles.length === 0) return null;
  // Newest action among the vehicles, so more than one flagged bill cannot silently
  // hide the others behind whichever the query happened to order first.
  let newest: string | null = null;
  for (const v of vehicles) {
    const at = v.latest_action_at;
    if (at !== null && (newest === null || at > newest)) newest = at;
  }
  return newest;
}

/** The presidential document types the executive collector asks the Federal Register
 *  for. Tab 3's spine sentence names them, and a sentence that names a collector's
 *  configuration is a claim about a file -- exactly the shape that went stale in this
 *  repo before: the mock's earlier spine said "executive orders only", which was true
 *  when drawn and false two days later.
 *
 *  WRITTEN TWICE ON PURPOSE, and held equal by a test. `collectors/executive.py`
 *  needs the list as query values; the page needs it as prose. Neither derives from
 *  the other across a language boundary, so `tests/test_presidential_types_agreement.py`
 *  parses this literal and fails in BOTH directions -- adding a type to the collector
 *  without following it here breaks the build, which is the requirement. That test
 *  lives on the Python side for the same reason the court-alias one does: the Python
 *  list is the one a person edits. */
export const PRESIDENTIAL_TYPES: readonly string[] = [
  "determination",
  "executive order",
  "memorandum",
  "notice",
  "other",
  "presidential order",
  "proclamation",
];
