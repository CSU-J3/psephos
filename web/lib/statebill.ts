import type { StateBill } from "@/lib/db";

// "TX HB 1234" style label. Shared by StateBillRow and the detail page so the
// label reads identically in both, exactly like billLabel.
export function stateBillLabel(sb: Pick<StateBill, "state" | "bill_number">): string {
  return `${sb.state} ${sb.bill_number}`;
}

// LegiScan progress codes -> display. The collector stores the raw numeric code
// (schema: status is "display-mapped in 5b-c"); this is that mapping.
export const STATUS_LABELS: Record<string, string> = {
  "1": "Introduced",
  "2": "Engrossed",
  "3": "Enrolled",
  "4": "Passed",
  "5": "Vetoed",
  "6": "Failed",
};

export function stateBillStatus(code: string | null): string | null {
  if (!code) return null;
  return STATUS_LABELS[code] ?? code; // unmapped -> show the raw code, don't hide it
}

// --- the stage ramp ---------------------------------------------------------
// Column order is LegiScan's own progression, not a ranking invented here, so the
// matrix reads left-to-right as a bill moves.
export type StageCode = "1" | "2" | "3" | "4" | "5" | "6";
export const STAGE_ORDER: readonly StageCode[] = ["1", "2", "3", "4", "5", "6"];

// VIOLET MARKS MOVEMENT, AND ONLY MOVEMENT. --c-legislation is the board-wide
// legislation hue (globals.css), so spending it on all six stages would say every
// row is equally a legislative event. Engrossed/Enrolled take the dim ramp step and
// Passed takes the bright one; Introduced, Vetoed and Failed stay neutral, because a
// bill sitting in committee and a bill that died are not movement.
//
// Vetoed is LIGHTER than Failed on purpose. Both are terminal, but a veto is an
// executive act on a bill that cleared a chamber -- a record of something happening
// -- while Failed is a session ending under it. Dimming them equally would erase
// that, and Wisconsin is the case that shows it: 3 vetoed against 56 failed.
//
// Four roles, because the page paints four surfaces: `dot` is the column-header key,
// `tick` a row's 2px left rule, `cell` a matrix count, `chip` the stage name on a row.
// Only stage 1 makes cell and chip disagree (a count is worth reading; a chip saying
// "Introduced" is the least informative thing on the row).
//
// THE SWATCH IS A SAMPLE OF THE INK, NOT A FAMILY RESEMBLANCE TO IT: `dot === cell` on
// every stage, and assert-encodings.mjs fails if that ever stops being true. A key whose
// swatch is merely near the colour it explains is a key the reader has to squint past,
// and it is the kind of thing that drifts one stage at a time because each step looks
// close enough on its own.
//
// The mock did not have this rule and could not have had it. Its dot painted a general
// per-stage colour that was sometimes the cell and sometimes not, plus a hard-coded
// ternary overriding it for stage 1 alone -- which left Introduced named by THREE
// different greys at once: n700 on the dot, n500 on the chip, n400 on the cell. The
// first port of it here half-normalised that (Failed's dot moved to its cell) and left
// Introduced and Passed diverging, which is a job stopped in the middle rather than a
// decision. This finishes it.
//
// `dot` AND `cell` STAY SEPARATE FIELDS, deliberately, even though the rule now makes
// them equal. Deriving one from the other would make the assertion true by construction
// -- exactly the vacuity that this project's own encodings script shipped in its first
// draft and had to fix. Two fields that must agree can disagree, which is the only
// reason checking them is worth anything.
//
// TICK IS EXEMPT AND IS NEVER ASSERTED AGAINST THE DOT. A 2px rule against a near-black
// ground is a different contrast problem from 0.4rem of text: at that width the ramp's
// dim step is nearly invisible, so the tick is free to run brighter or darker than the
// count it accompanies. It is its own channel. The script prints it beside the other two
// every run so the divergence stays visible, and asserts nothing about it.
export type StageStyle = {
  dot: string;
  tick: string | null; // null = no tick; Introduced gets no rule
  cell: string;
  chip: string;
  bold: boolean;
};

export const STAGE_STYLE: Record<StageCode, StageStyle> = {
  "1": { dot: "#a3a3a3", tick: null, cell: "#a3a3a3", chip: "#737373", bold: false },
  "2": {
    dot: "var(--leg-dim)",
    tick: "var(--leg-dim)",
    cell: "var(--leg-dim)",
    chip: "var(--leg-dim)",
    bold: false,
  },
  "3": {
    dot: "var(--leg-dim)",
    tick: "var(--leg-dim)",
    cell: "var(--leg-dim)",
    chip: "var(--leg-dim)",
    bold: false,
  },
  "4": {
    dot: "var(--leg-bright)",
    tick: "var(--c-legislation)",
    cell: "var(--leg-bright)",
    chip: "var(--leg-bright)",
    bold: true,
  },
  "5": { dot: "#d4d4d4", tick: "#a3a3a3", cell: "#d4d4d4", chip: "#d4d4d4", bold: false },
  "6": { dot: "#525252", tick: "#404040", cell: "#525252", chip: "#525252", bold: false },
};

// The join vocabulary, DERIVED FROM THE DISPLAY VOCABULARY so it cannot become a third
// one. scripts/assert-encodings.mjs reads these off `data-encoding` in the matrix key
// and off `data-stage` on every painted surface, then joins the two sets. Nothing
// transcribes the list: change STATUS_LABELS and both sides of that join move together.
//
// It exists because colour cannot carry the identity here. Stages 2 and 3 are painted
// IDENTICALLY on all four surfaces -- both are `var(--leg-dim)` -- so a classifier that
// read only computed colour would have to report Engrossed and Enrolled as one thing,
// or guess. The attribute says which stage a mark claims to be; the paint is then
// checked against what that stage declares. Identity from the attribute, verification
// from the pixel.
export function stageEncoding(code: StageCode): string {
  return `stage-${STATUS_LABELS[code].toLowerCase()}`;
}

// A bill's stage, or null when its status is missing or outside the ramp. The matrix
// uses this to pick a column; the row itself renders either way.
export function stageOf(bill: Pick<StateBill, "status">): StageCode | null {
  const s = bill.status;
  if (!s) return null;
  return (STAGE_ORDER as readonly string[]).includes(s) ? (s as StageCode) : null;
}

// --- the matrix -------------------------------------------------------------
export type MatrixRow = {
  state: string;
  cells: number[]; // one per STAGE_ORDER entry, same index
  unstaged: number;
  total: number;
};

export type Matrix = {
  rows: MatrixRow[];
  stageTotals: number[];
  unstagedTotal: number;
  total: number;
  hasUnstaged: boolean;
};

// State x stage counts, plus every margin the table shows.
//
// `unstaged` EXISTS SO NOTHING CAN VANISH. Live data carries no null or unmapped
// status today (484 rows, all 1-6), so the column renders nowhere -- `hasUnstaged` is
// the gate. But the whole argument of this page is that its totals are complete, and
// if a stage code ever arrives that this file does not know, the alternatives are a
// row total that silently exceeds the sum of its own cells, or a bill dropped off the
// page entirely. Both of those look exactly like clean data. A column that appears
// only when it has something in it does not, and it costs nothing while the data
// stays clean.
//
// The invariant that buys, asserted in the tests: cells + unstaged == total, on every
// row and on the totals row.
export function buildMatrix(bills: readonly StateBill[]): Matrix {
  const byState = new Map<string, MatrixRow>();
  const stageTotals = STAGE_ORDER.map(() => 0);
  let unstagedTotal = 0;

  for (const b of bills) {
    let row = byState.get(b.state);
    if (!row) {
      row = { state: b.state, cells: STAGE_ORDER.map(() => 0), unstaged: 0, total: 0 };
      byState.set(b.state, row);
    }
    const stage = stageOf(b);
    if (stage === null) {
      row.unstaged += 1;
      unstagedTotal += 1;
    } else {
      const i = STAGE_ORDER.indexOf(stage);
      row.cells[i] += 1;
      stageTotals[i] += 1;
    }
    row.total += 1;
  }

  const rows = [...byState.values()].sort((a, b) => a.state.localeCompare(b.state));
  return {
    rows,
    stageTotals,
    unstagedTotal,
    total: bills.length,
    hasUnstaged: unstagedTotal > 0,
  };
}

// --- ordering and filtering -------------------------------------------------
// NO `new Date()` ANYWHERE IN THIS FILE. `last_action_at` is a naive ISO string, and
// the lexical order of ISO strings IS chronological order -- parsing them through
// Date applies the runtime's zone and can shift the calendar day, the defect
// lib/format.ts documents at length. Comparing the strings skips the parse rather
// than correcting it.
//
// Nulls sort LAST: "" loses to every real date under a descending localeCompare.
//
// THE TIEBREAK IS LOAD-BEARING, and the mock does not have one. Legislatures act in
// batches, so a same-day last action is the common case rather than the edge -- Texas
// alone has 198 bills across a handful of action dates. Untiebroken, the top ten is
// whatever order the rows arrived in, which makes a server-rendered page reorder
// itself for no reason a reader can see.
function byRecency(a: StateBill, b: StateBill): number {
  return (
    (b.last_action_at ?? "").localeCompare(a.last_action_at ?? "") ||
    a.state.localeCompare(b.state) ||
    a.bill_number.localeCompare(b.bill_number)
  );
}

export function sortByRecent(bills: readonly StateBill[]): StateBill[] {
  return [...bills].sort(byRecency);
}

// The ten most recent last-actions across every state -- the page's answer to "what
// moved", which the matrix cannot give because a count carries no date.
export function latestMovement(bills: readonly StateBill[], limit = 10): StateBill[] {
  return sortByRecent(bills).slice(0, limit);
}

export type StateBillFilters = { state?: string | null; status?: string | null };

export function filterStateBills(
  bills: readonly StateBill[],
  { state, status }: StateBillFilters,
): StateBill[] {
  return bills.filter(
    (b) => (!state || b.state === state) && (!status || b.status === status),
  );
}

export type StateGroup = { state: string; bills: StateBill[] };

// Grouped for the `?sort=state` view: states alphabetical, bills recent-first inside
// each. Same comparator as the flat list, so the two orderings cannot drift.
export function groupByState(bills: readonly StateBill[]): StateGroup[] {
  const byState = new Map<string, StateBill[]>();
  for (const b of bills) {
    const group = byState.get(b.state);
    if (group) group.push(b);
    else byState.set(b.state, [b]);
  }
  return [...byState.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([state, group]) => ({ state, bills: group.sort(byRecency) }));
}

// --- the URL is the state ---------------------------------------------------
// Every view of this page is a link, so the filters live in search params and no
// client component holds anything. `?all=1` is what makes "browse all" distinguishable
// from the bare page: both carry no state and no status, and only one of them should
// render 484 rows.
export type StateBillParams = {
  state: string | null;
  status: string | null;
  sort: "recent" | "state";
  listing: boolean;
};

function one(value: string | string[] | undefined): string | null {
  if (value === undefined) return null;
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length > 0 ? v : null;
}

// An unknown state or status code is passed through rather than dropped: it filters
// to zero rows and the page says so, which is honest about a bad URL. Ignoring it
// would render all 484 under a heading naming the filter that was ignored.
export function parseStateBillParams(
  sp: Record<string, string | string[] | undefined>,
): StateBillParams {
  const state = one(sp.state)?.toUpperCase() ?? null;
  const status = one(sp.status);
  const all = one(sp.all);
  return {
    state,
    status,
    sort: one(sp.sort) === "state" ? "state" : "recent",
    listing: Boolean(state || status || all),
  };
}

// The list heading: "All states", "TX", "TX - passed". Lowercased stage so the heading
// reads as a phrase rather than two proper nouns bolted together.
export function listTitle({ state, status }: StateBillFilters): string {
  const parts = [state || "All states"];
  const label = status ? stateBillStatus(status) : null;
  if (label) parts.push(label.toLowerCase());
  return parts.join(" · ");
}
