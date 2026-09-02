import type { Cell } from "@/lib/campaign";

// The view-layer derivations /campaign needs and lib/campaign.ts does not own: which
// section a grid cell opens, who belongs to each section, and which docket entries are
// the most recent. Kept out of campaign.ts deliberately -- that module builds cells from
// rows and is pinned by its own suite; this one answers questions the PAGE asks.

export type SectionKey = "continued" | "unlinked" | "ended" | "quiet";

export const SECTION_ORDER: readonly SectionKey[] = [
  "continued",
  "unlinked",
  "ended",
  "quiet",
];

export const SECTION_TITLE: Record<SectionKey, string> = {
  continued: "Continued elsewhere",
  unlinked: "Ended, with no link asserted",
  ended: "Ended in this record",
  quiet: "Quiet",
};

// --- membership -------------------------------------------------------------
// What each section CONTAINS. Unchanged from the four filters the page has always
// used, lifted here so the roster on a section line and the rows inside that section
// are computed from one function rather than two expressions that agree today.
export function isMember(c: Cell, key: SectionKey): boolean {
  switch (key) {
    case "continued":
      return c.chain !== null;
    case "unlinked":
      return c.unlinked.length > 0;
    case "ended":
      return c.status === "ended";
    case "quiet":
      return c.dormant;
  }
}

export function membersOf(cells: readonly Cell[], key: SectionKey): Cell[] {
  return cells.filter((c) => isMember(c, key));
}

// --- where a cell goes when clicked -----------------------------------------
// MEMBERSHIP AND DESTINATION ARE DIFFERENT QUESTIONS, and conflating them is the
// mistake this file exists to avoid. A state can be in two sections at once --
// Arizona is `continued` AND `quiet` today -- so its roster entry appears twice while
// its grid cell can only open one place.
//
// The mock resolved this with a hardcoded map from state to section. A map is an
// answer, not a rule: it is correct exactly until the overlaps move, and it gives a
// reader no way to tell which of two memberships was meant to win. This is the rule
// instead, and it reproduces the mock's map exactly on today's data.
//
// PRECEDENCE IS BY STRENGTH OF CLAIM ABOUT THE DOCKET'S FATE. `ended` is terminal.
// `unlinked` is an ending the record cannot connect forward, which is a claim about an
// ending too. `continued` says the case moved. `quiet` says only that a LIVE docket has
// been silent -- the weakest of the four, and the one that should never hide a
// terminal fact behind it. So quiet loses to everything, which is why Arizona's cell
// opens `continued` while Arizona stays in the quiet roster.
//
// Not cosmetic: handoff 92 established that `ended` and `unlinked` are disjoint TODAY
// but not by construction, so the order between them will eventually be exercised.
const PRECEDENCE: readonly SectionKey[] = ["ended", "unlinked", "continued", "quiet"];

// The section this cell's grid square opens, or null when it belongs to none.
//
// NULL IS A REAL ANSWER AND NOT AN EDGE CASE. Nine sued jurisdictions are live dockets
// that are not continued, unlinked, ended or quiet -- they are simply running. Their
// cells and their movement rows carry no section affordance, because inventing one
// would be a link to nowhere. The mock never shows this state; its sample happened to
// be all `unlinked`.
export function sectionOf(c: Cell): SectionKey | null {
  return PRECEDENCE.find((k) => isMember(c, k)) ?? null;
}

/** state code -> the section its cell opens. Built once, read by cells and by
 *  movement rows, so the two cannot disagree about where a state lives. */
export function sectionByState(cells: readonly Cell[]): Map<string, SectionKey> {
  const m = new Map<string, SectionKey>();
  for (const c of cells) {
    const k = sectionOf(c);
    if (k) m.set(c.code, k);
  }
  return m;
}

// --- latest movement --------------------------------------------------------
export type MovementRow = {
  id: number;
  case_id: string;
  /** The jurisdiction as `cases.state` spells it -- "New Hampshire", not "NH". */
  state: string;
  occurred_at: string;
  text: string;
  grade: string;
};

// The most recent docket entries across every campaign docket.
//
// NO `new Date()`. `occurred_at` is a naive ISO string and lexical order IS
// chronological, so comparing the strings skips the zone-shifting parse lib/format.ts
// documents at length. Same rule as lib/statebill.ts's recency sort.
//
// `id DESC` is the tiebreak and it is load-bearing rather than tidy: a collector run
// writes many rows inside one second and a docket walk writes a whole history at one
// timestamp, so `occurred_at` alone leaves within-batch order to whatever the engine
// returns. Same reasoning the feed's ordering comment gives for the same pair.
//
// A NULL `occurred_at` IS EXCLUDED UPSTREAM, in the query, and this function does not
// see one. Stated because the alternative is tempting and wrong: sorting undated rows
// last would place them in the list as though their position meant something. 68 of
// the 2,079 campaign litigation items carry no date, and "most recent" is a claim none
// of them can support.
export function latestMovement(rows: readonly MovementRow[], limit = 8): MovementRow[] {
  return [...rows]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.id - a.id)
    .slice(0, limit);
}
