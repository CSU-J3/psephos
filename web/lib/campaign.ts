import type { CampaignRow } from "@/lib/db";

// Derivation for the DOJ voter-data campaign grid. Pure functions over rows the
// page has already fetched -- no queries here, so the shape of a cell can be
// reasoned about (and changed) without touching the read path.

// The denominator is 51, not 31. A grid over the states DOJ sued shows the suits;
// a grid over every state shows where DOJ has NOT acted, which is the stronger
// claim and the reason the empty cells stay on the page. Four LegiScan-polled
// states (FL, NC, OH, TX) sit in the empty 20, so those cells carry state-bill
// activity with no federal suit -- a cross-channel reading the 31-cell version
// cannot produce.
//
// The artifact spells jurisdictions out ("New Hampshire", "DC"); the grid needs
// two-letter codes. This map is both the code lookup AND the full 51-cell census,
// so the two can never disagree.
export const JURISDICTIONS: ReadonlyArray<readonly [name: string, code: string]> = [
  ["Alabama", "AL"], ["Alaska", "AK"], ["Arizona", "AZ"], ["Arkansas", "AR"],
  ["California", "CA"], ["Colorado", "CO"], ["Connecticut", "CT"], ["Delaware", "DE"],
  ["DC", "DC"], ["Florida", "FL"], ["Georgia", "GA"], ["Hawaii", "HI"],
  ["Idaho", "ID"], ["Illinois", "IL"], ["Indiana", "IN"], ["Iowa", "IA"],
  ["Kansas", "KS"], ["Kentucky", "KY"], ["Louisiana", "LA"], ["Maine", "ME"],
  ["Maryland", "MD"], ["Massachusetts", "MA"], ["Michigan", "MI"], ["Minnesota", "MN"],
  ["Mississippi", "MS"], ["Missouri", "MO"], ["Montana", "MT"], ["Nebraska", "NE"],
  ["Nevada", "NV"], ["New Hampshire", "NH"], ["New Jersey", "NJ"], ["New Mexico", "NM"],
  ["New York", "NY"], ["North Carolina", "NC"], ["North Dakota", "ND"], ["Ohio", "OH"],
  ["Oklahoma", "OK"], ["Oregon", "OR"], ["Pennsylvania", "PA"], ["Rhode Island", "RI"],
  ["South Carolina", "SC"], ["South Dakota", "SD"], ["Tennessee", "TN"], ["Texas", "TX"],
  ["Utah", "UT"], ["Vermont", "VT"], ["Virginia", "VA"], ["Washington", "WA"],
  ["West Virginia", "WV"], ["Wisconsin", "WI"], ["Wyoming", "WY"],
];

// Quiet longer than this and the live docket is called dormant. 60 days rather
// than 30: at 30 the flag fires on a third of the campaign and stops reading as
// exceptional. The THRESHOLD lives here; the MEMBERSHIP is computed at render and
// is deliberately written down nowhere. A concrete list is stale by build time --
// the 253-day flagship case (W.D. Wash.) took entries and left the set within a
// day of being named in the spec.
export const DORMANT_AFTER_DAYS = 60;

export type CellStatus = "active" | "ended" | "none";
export type ChainKind = "appeal" | "refile";

export type Cell = {
  name: string;
  code: string;
  status: CellStatus;
  live: CampaignRow | null;
  // The terminated row(s) this jurisdiction continued FROM. superseded_by is set
  // on the dead row pointing forward, so the predecessor is the one carrying it.
  predecessors: CampaignRow[];
  // Rows that are neither the live docket nor a predecessor: an ending the record
  // holds with NO link asserted to whatever is live in the same state. These used
  // to be dropped -- see buildCells. The three buckets are exhaustive by
  // construction, which is the invariant the page depends on.
  unlinked: CampaignRow[];
  chain: ChainKind | null;
  quietDays: number | null;
  dormant: boolean;
};

// A circuit row is a row whose court names a circuit. Used to tell an appeal from
// a venue refile, which are NOT the same event and must not share a glyph: an
// appeal means a district ruled and the case went up, a refile means DOJ moved
// venue with no merits ruling. Georgia is the only refile in the campaign
// (M.D. Ga. -> N.D. Ga., intra-state, no circuit step -- see the circuit-map
// invariant in docs/status.md).
export function isCircuit(court: string | null): boolean {
  return !!court && /\bcircuit\b/i.test(court);
}

// Whole days between a naive ISO date and `now`, read in UTC for the same reason
// formatDate does: parsing through the runtime's local zone can shift the day.
export function daysSince(value: string | null, now: Date): number | null {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return null;
  const [, y, mo, d] = m;
  const then = Date.UTC(Number(y), Number(mo) - 1, Number(d));
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.floor((today - then) / 86_400_000);
}

// Group the campaign's rows into one cell per jurisdiction, in census order, with
// the 20 sued-by-nobody states present and empty.
export function buildCells(rows: CampaignRow[], now: Date): Cell[] {
  const byState = new Map<string, CampaignRow[]>();
  for (const r of rows) {
    const group = byState.get(r.state);
    if (group) group.push(r);
    else byState.set(r.state, [r]);
  }

  return JURISDICTIONS.map(([name, code]) => {
    const group = byState.get(name) ?? [];
    // The live docket is the one nothing supersedes. A jurisdiction usually has
    // exactly one -- but between a successor landing and its supersession being
    // asserted it has TWO, and that window is the whole reason this is written the
    // way it is.
    //
    // THIS USED TO DISCARD THE LOSER AND SAY SO: "if a future chain ever produced
    // two, take the most recently filed rather than rendering a broken cell." The
    // case was foreseen and mishandled. Taking one and dropping the other IS the
    // broken cell; it just failed silently. The dropped row carried no
    // superseded_by, so it was not a predecessor either, and no section on the
    // page could reach it. Observed on CT and NY: the cell flipped active on the
    // live Second Circuit row, `Ended in this record` fell 8 -> 6, and the
    // 3:26-cv-00021 dismissal was absent from the page in every section. KY, VA
    // and NM each passed through the same window unobserved.
    //
    // So the partition is now TOTAL: live + predecessors + unlinked === group, and
    // a test asserts it rather than a comment promising it.
    const liveRows = group.filter((r) => !r.superseded_by);
    // Ordering rule, in two parts. Pending beats terminated: filing order alone
    // picked correctly only by luck, since a successor is normally filed later, and
    // inverted it would put a terminated docket on the cell and call the whole
    // state ended. Most-recently-filed breaks the remaining ties.
    const live =
      liveRows.length <= 1
        ? liveRows[0] ?? null
        : [...liveRows].sort(
            (a, b) =>
              Number(a.status === "terminated") - Number(b.status === "terminated") ||
              (b.filed_at ?? "").localeCompare(a.filed_at ?? ""),
          )[0];
    const predecessors = group.filter((r) => r.superseded_by);
    const unlinked = liveRows.filter((r) => r !== live);

    // Three states, not two. A jurisdiction whose only live row is `terminated`
    // has ENDED -- distinct from never sued, and distinct from still running.
    // Michigan is why this matters: it is terminated at the Sixth Circuit with no
    // successor, the campaign's first appellate loss, and a two-state grid would
    // render it identically to Oklahoma's district dismissal.
    const status: CellStatus = !live
      ? "none"
      : live.status === "terminated"
        ? "ended"
        : "active";

    const quietDays = live ? daysSince(live.latest_entry_at, now) : null;
    return {
      name,
      code,
      status,
      live,
      predecessors,
      unlinked,
      // A chain is an ASSERTED continuation, so it keys off predecessors only. An
      // unlinked ending is precisely the case where no link exists, and giving it a
      // chain here would invent the relationship the record does not have.
      chain: predecessors.length && live ? (isCircuit(live.court) ? "appeal" : "refile") : null,
      quietDays,
      // Dormancy is a claim about a LIVE docket going quiet. A terminated docket is
      // not dormant, it is finished, and flagging it would put the campaign's
      // decided losses in the same bucket as its stalled suits.
      dormant: status === "active" && quietDays !== null && quietDays > DORMANT_AFTER_DAYS,
    };
  });
}

// The UW tracker packs three fields into one notes string:
//   "Claims: 1. NVRA 2. HAVA | Status: On 6/22/26, the 9th Circuit stayed ... |
//    Key decisions: District Court's 4/28/26 dismissal."
// Only the Status segment answers "is this docket stayed or dead", so pull that
// out rather than dumping the whole string. Returns null when the shape does not
// match -- the two config seeds carry a single free-text sentence with no
// segments, and a tracker format change should render nothing rather than
// something wrong.
export function trackerStatus(notes: string | undefined): string | null {
  if (!notes) return null;
  const m = /(?:^|\|)\s*Status:\s*([^|]+)/i.exec(notes);
  return m ? m[1].trim() || null : null;
}

// Does the tracker's B2 status line contradict an A1 "ended" reading? Three of the
// eight ended cells do, measured 2026-08-14: Connecticut and New York both carry
// "DOJ filed a notice that it will appeal ... to the 2nd Circuit" against a
// terminated district row with no successor held, and Michigan is awaiting an en
// banc decision (which stays on the same docket, so it is correctly not a
// supersession -- and equally correctly not an ending).
//
// The spec's grading rule is explicit: when two sources conflict, record both and
// flag the conflict, never silently pick one. So this does not reclassify the
// cell -- the A1 record still says terminated and still says so on the page. It
// adds a caution beside the B2 line the reader can then read for themselves.
//
// A regex over tracker prose is brittle, and that is tolerable HERE precisely
// because of what it drives: a false positive shows a caution next to a sentence
// that disproves it, and a false negative renders exactly as the page did before.
// It would not be tolerable if it decided which bucket a cell went in.
//
// PRECISION, measured by reading all eight members rather than counting hits
// (2026-08-14): fires on 3 of 8, and all three are genuine -- MI (en banc pending),
// CT and NY (notices of appeal to the 2nd Cir. against terminated district rows
// psephos holds no successor for). The five silent ones are four merits dismissals
// and Oklahoma's settlement, none of which should fire. 8 of 8 correct.
//
// DO NOT ADD THE MIRROR-IMAGE CHECK -- an A1 `pending` row whose tracker line
// reports an ending -- without redoing this measurement. It was tried and declined
// the same day: `dismiss|settled|affirm` over the 23 active cells fires 10 times
// and only ONE is real (West Virginia). "State's motion to dismiss" is a pending
// motion, not a dismissal, and NH/NM/VA are circuit successors whose status line
// correctly describes the district dismissal that produced the appeal. The
// distinction is beyond a keyword. West Virginia is recorded as its own unit in
// docs/status.md instead.
export function contestsEnding(status: string | null): boolean {
  return !!status && /\b(appeal|rehear|en banc|certiorari|cert petition)\b/i.test(status);
}

export type CampaignSummary = {
  sued: number;
  active: number;
  ended: number;
  none: number;
  chains: number;
  dormant: number;
  // Cells holding an ending with no link asserted to what is live beside it.
  // Counts CELLS, like chains and dormant, not rows.
  unlinkedEndings: number;
  total: number;
};

export function summarize(cells: Cell[]): CampaignSummary {
  const count = (p: (c: Cell) => boolean) => cells.filter(p).length;
  return {
    total: cells.length,
    sued: count((c) => c.status !== "none"),
    active: count((c) => c.status === "active"),
    ended: count((c) => c.status === "ended"),
    none: count((c) => c.status === "none"),
    chains: count((c) => c.chain !== null),
    dormant: count((c) => c.dormant),
    unlinkedEndings: count((c) => c.unlinked.length > 0),
  };
}
