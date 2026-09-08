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
 * SCOPE IS THE CALLER'S, and it is not a detail. `getCampaignRows()` filters
 * `WHERE state IS NOT NULL`, which drops three dockets whose defendant is a federal
 * agency rather than a state -- League of Women Voters v. DHS (and its D.C. Circuit
 * appeal) and Common Cause v. DOJ. Those three are in `cases` as related suits, and
 * in two of them the United States is the DEFENDANT. Counting them inside a figure
 * introduced by "DOJ has sued" would report a suit against DOJ as one of DOJ's own.
 * So this function counts what it is handed and says so; the page chooses. */
export function docketTotals(rows: readonly CampaignRow[]): DocketTotals {
  const circuit = rows.filter((r) => isCircuit(r.court)).length;
  return { total: rows.length, district: rows.length - circuit, circuit };
}

/** Dockets still running: neither terminated nor superseded by a successor.
 *
 * `superseded_by` is set on the DEAD row pointing forward, so a row carrying it is
 * complete however its own status column reads -- a terminated district docket
 * continued as a circuit appeal is finished, not open. Same canonicalization trap as
 * above: read raw, this split reads 10/21 where the record says 9/22. */
export function openSplit(rows: readonly CampaignRow[]): DocketTotals {
  const open = rows.filter((r) => !r.superseded_by && !isTerminated(r));
  return docketTotals(open);
}

/** A row the record shows as ended. `status` is the tracker's word and `cases` also
 *  carries a termination date; the campaign rows the page fetches expose the status
 *  string, so that is what this reads. Kept separate from `openSplit` so the
 *  predicate has one home. */
function isTerminated(row: CampaignRow): boolean {
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
