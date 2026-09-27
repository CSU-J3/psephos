import type { CampaignRow, Bill, StateBill } from "@/lib/db";
import { isCircuit } from "@/lib/campaign";
import { utcDay } from "@/lib/format";
import { datedAhead, type RecordClock } from "@/lib/dated";

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
 *  import so both `DocketRow` (the section) and `Case` (the rail's class mark) satisfy it
 *  without either becoming a dependency of this file. `CampaignRow` does not: it
 *  carries neither `plaintiff` nor `category`. */
export type DocketLike = {
  court: string | null;
  status: string | null;
  superseded_by: string | null;
  plaintiff: string | null;
  category: string | null;
};

// --- THE THREE SETS ------------------------------------------------------------------
//
// Every docket the section reads lands in exactly one of three sets, and a test
// holds them disjoint and covering:
//
//   eoChallenges  -- dockets the SEED marks `category: executive-order`, after
//                    reading the operative complaint against the test: does it seek
//                    relief against an election executive order, or against agency
//                    action the complaint pleads was taken under one? (Corey,
//                    2026-09-26)
//   dojFilings    -- suits the United States filed, minus the class above.
//   relatedSuits  -- everything else, a suit that passes the test but is not yet
//                    marked included: LWV v. DHS and its appeal pass under EO 14248
//                    and sit here until that order's dockets are seeded.
//
// THE MARK MEANS "A CHALLENGE", and only because the seed commit is the only writer of
// it: `category` is a topic vocabulary in schema.sql, and a DOJ-filed suit tagged
// `executive-order` would leave DOJ's count and be called a challenge. None exists.
//
// THE CLASS IS DECIDED FIRST, AND ON THE SEED'S MARK, NOT ON A CAPTION. Its
// membership test is read off each operative complaint, once, when the docket is seeded
// (docs/status.md carries the paragraph that decided each), and it cannot be
// re-derived from any column: the defendants are the President in most of these suits
// and the Postal Service in one, and neither name marks a challenge. And it must run
// before the plaintiff test, because that test is a prefix: the Supreme Court's own
// docket captions this litigation United States Postal Service v. California, and
// "United States Postal Service" starts with "United States". (CourtListener's case
// name for that docket reads "Postal Service v. California", and it is not seeded; the
// order is for the day a caption like it arrives.)

/** The `cases.category` value that marks the class. In the schema's vocabulary
 *  (schema.sql) since the table was written; the seed commit is its first user. */
export const EO_CHALLENGE = "executive-order";

/** A suit whose operative complaint seeks relief against an election executive order,
 *  or against agency action the complaint pleads was taken under one. */
export function isEoChallenge(row: DocketLike): boolean {
  return row.category === EO_CHALLENGE;
}

/** The class's dockets, appeals included. */
export function eoChallenges<T extends DocketLike>(rows: readonly T[]): T[] {
  return rows.filter(isEoChallenge);
}

/** The class's LAWSUITS: its trial-court dockets. An appeal continues a suit rather
 *  than being one, so the sentence that counts challenges counts these. One held lead
 *  appeal stands for four consolidated ones (26-2029 for 26-2029 to 26-2032, the
 *  26-5301 precedent), so an appeals figure beside it would state a number the record
 *  does not hold. A Supreme Court docket is not a lawsuit either, and is excluded by
 *  name for the day one is seeded. */
export function eoLawsuits<T extends DocketLike>(rows: readonly T[]): T[] {
  return eoChallenges(rows).filter((r) => !isAppellate(r.court));
}

function isAppellate(court: string | null): boolean {
  return isCircuit(court) || /\bSupreme Court\b/i.test(court ?? "");
}

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

/** The dockets DOJ filed. The class is excluded first; see THE THREE SETS. */
export function dojFilings<T extends DocketLike>(rows: readonly T[]): T[] {
  return rows.filter((r) => !isEoChallenge(r) && isDojFiling(r));
}

/** Suits brought by civil-society plaintiffs against federal agencies: dockets neither
 *  filed by the United States nor marked on the seed as an EO challenge. A suit can
 *  pass the class test and still sit here until its seed is marked -- LWV v. DHS does,
 *  under EO 14248 (docs/status.md, the 14248 unit). They stay in the record and
 *  leave the DOJ count -- the section names them in their own clause rather than
 *  dropping them, because a reader who counts the map and the sentence should be able
 *  to reconcile the difference.
 *
 *  NAMED BY BOTH EXCLUSIONS, not as the complement of one. It was `!isDojFiling` until
 *  the class existed, and under that definition every EO challenge seeded would have
 *  joined this count, under a clause that names its three captions. */
export function relatedSuits<T extends DocketLike>(rows: readonly T[]): T[] {
  return rows.filter((r) => !isEoChallenge(r) && !isDojFiling(r));
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
export function vehicleQuietSince(bills: readonly Bill[], clock: RecordClock): string | null {
  const vehicles = bills.filter((b) => b.is_vehicle === 1);
  if (vehicles.length === 0) return null;
  // Newest action among the vehicles, so more than one flagged bill cannot silently
  // hide the others behind whichever the query happened to order first. An action dated
  // ahead of the record's clock is skipped: one meaning of "latest" (lib/dated.ts).
  let newest: string | null = null;
  for (const v of vehicles) {
    const at = v.latest_action_at;
    if (at === null || datedAhead(at, clock)) continue;
    if (newest === null || at > newest) newest = at;
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
