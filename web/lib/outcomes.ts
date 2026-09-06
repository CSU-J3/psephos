// THE OUTCOMES DERIVATION: which records demands a court has ruled against.
//
// Teal is an EVENT, orthogonal to posture. A court ruling against the demand is not a
// third value of "is there a live suit here" -- United States v. Weber was rejected on
// 2026-01-15 AND appealed, so California carries a teal stroke over a live-red fill.
// Anything that tried to express this as a posture would have to choose one and lose
// the other.
//
// DERIVED STRUCTURALLY, NOT CLASSIFIED FROM TEXT ALONE, and the difference is the whole
// reason `cases.date_terminated` exists. RecordsMap's own rule warns against asserting
// outcomes the record does not structure, and a docket's INTERLOCUTORY orders use the
// same vocabulary as its terminal one: "Motion to Compel is DENIED" and "Motions to
// Dismiss are GRANTED" both appear months before the order that ends the case, and
// "Motion for Leave to File a Reply to Plaintiff's Response to the Motion to Dismiss is
// GRANTED" satisfies any pattern loose enough to catch the real ones.
//
// Measured against a per-case eyeball of all twenty terminated campaign dockets
// (handoff 97 H0): scoped to the docket's own termination date these patterns agree
// 20/20; run over the whole docket they agree 10/20, misclassifying four outright and
// dating six more to orders months early -- Colorado to 2026-03-18 where the judgment
// is 08-03, New York to 01-09 where it is 07-10. The date is the whole difference
// between a derivation and an editorial list.
//
// SO THE WINDOW IS THE STRUCTURE AND THE TEXT ONLY BREAKS A TIE. Inside ±1 day of
// `date_terminated` the only question left is which KIND of disposition it was: a court
// ruling against the United States, or a withdrawal, or a forum problem. That is a
// question three narrow patterns can answer; "what happened in this docket" is not.

/** One docket entry, as the join hands it over. */
export type DocketEntry = {
  case_id: string;
  entry_at: string | null;
  description: string | null;
};

/** A terminated docket with the date the court disposed of it. */
export type TerminatedCase = {
  case_id: string;
  state: string;
  date_terminated: string;
};

export type Rejection = {
  state: string;
  case_id: string;
  /** The entry date of the order, which is not always `date_terminated` itself --
   *  New Hampshire's order is 06-29 and its judgment 06-30. The order is the event. */
  rejected_at: string;
  /** Which pattern matched, carried so a reader can audit a cell without the docket. */
  pattern: string;
};

// A PARTY FILING IS NOT A RULING, and this gate is not optional. Notices of appeal
// quote the titles of the orders they appeal -- "Order on Motion to Dismiss,,,, Order
// on Motion to Compel" -- so without it the loser's own paperwork matches and the
// rejection is dated to the appeal. Every hit in the twenty-docket corpus survives it.
const FILING =
  /notice\s+of\s+appeal|voluntary\s+dismissal|^\s*(motion|response|brief|reply|letter|notice\s+of\s+(appearance|supplemental)|entry\s+of\s+appearance|amicus|designation)/i;

// A DISMISSAL FOR WANT OF JURISDICTION IS NOT A RULING ON THE DEMAND. The court is
// declining the forum, not refusing the records: M.D. Ga. dismissed without prejudice
// for lack of subject-matter jurisdiction on 2026-01-23 and DOJ refiled in N.D. Ga.,
// where the case is live. Painting Georgia teal would report a defeat against a suit
// that is still running, and would count one demand twice.
const JURISDICTIONAL = /lacks?\s+subject\s+matter\s+jurisdiction/i;

/** The dispositions that are a court ruling against the party that brought the suit. */
const REJECT: ReadonlyArray<readonly [string, RegExp]> = [
  // The granted object must BE the motion to dismiss. Periods are allowed inside the
  // span ("Docs. 91, 106", "ECF Nos. 46, 48") -- affordable only because the window
  // has already excluded the leave-to-file and intervention orders that a whole-docket
  // sweep with this span would match.
  [
    "mtd-granted",
    /grant(?:ing|ed)\s+[^;]{0,80}?motions?\s+to\s+dismiss|motions?\s+to\s+dismiss[^;]{0,80}?\b(?:are|is)\s+(?:hereby\s+)?granted/i,
  ],
  // The purest form of the event, and the one a dismissal-only rule would miss. D.D.C.
  // denied the motions to dismiss AS MOOT and denied DOJ's motion to compel records --
  // the demand itself refused, with no dismissal in the sentence.
  [
    "compel-denied",
    /motion\s+(?:for\s+order\s+)?to\s+compel[^;]{0,90}?\bis\s+denied|deny(?:ing)?\s+[^;]{0,60}?motion\s+to\s+compel/i,
  ],
  [
    "judgment-for-defendants",
    /judgment\s+entered\s+in\s+favor\s+of[^;]{0,60}defendants?|judgment\s+in\s+favor\s+of\s+(?!the\s+united\s+states|usa\b)/i,
  ],
  ["take-nothing", /plaintiff\s+to\s+take\s+nothing/i],
  ["dismissing-the-case", /dismissing\s+the\s+case|this\s+case\s+is\s+dismissed/i],
  // The appellate form. Michigan's row IS the Sixth Circuit -- the first appeals court
  // to rule in this campaign -- so the event is an affirmance, not a dismissal.
  ["affirmed", /opinion\s+and\s+judgment\s+filed\s*:?\s*affirmed/i],
];

const DAY = 86_400_000;

/** Date-only prefix. Entry timestamps and `date_terminated` are both ISO and both
 *  carry a time on some rows and not others, so every comparison is on the prefix. */
const day = (iso: string) => iso.slice(0, 10);

function withinWindow(entry: string, terminated: string): boolean {
  const e = Date.parse(`${day(entry)}T00:00:00Z`);
  const t = Date.parse(`${day(terminated)}T00:00:00Z`);
  if (Number.isNaN(e) || Number.isNaN(t)) return false;
  return Math.abs(e - t) <= DAY;
}

/**
 * Every jurisdiction whose records demand a court has ruled against.
 *
 * One rejection per case at most, taken from the FIRST matching order in the window:
 * a disposition is often entered two or three times the same day (an order, an amended
 * order, a clerk's judgment), and they are one event.
 */
export function rejections(
  cases: readonly TerminatedCase[],
  entries: readonly DocketEntry[],
): Rejection[] {
  const byCase = new Map<string, DocketEntry[]>();
  for (const e of entries) {
    const list = byCase.get(e.case_id);
    if (list) list.push(e);
    else byCase.set(e.case_id, [e]);
  }

  const out: Rejection[] = [];
  for (const c of cases) {
    if (!c.date_terminated || !c.state) continue;
    const window = (byCase.get(c.case_id) ?? [])
      .filter((e) => e.entry_at && withinWindow(e.entry_at, c.date_terminated))
      .sort((a, b) => (a.entry_at! < b.entry_at! ? -1 : a.entry_at! > b.entry_at! ? 1 : 0));

    for (const e of window) {
      const d = (e.description ?? "").replace(/\s+/g, " ");
      if (!d || FILING.test(d) || JURISDICTIONAL.test(d)) continue;
      const hit = REJECT.find(([, pat]) => pat.test(d));
      if (hit) {
        out.push({
          state: c.state,
          case_id: c.case_id,
          rejected_at: day(e.entry_at!),
          pattern: hit[0],
        });
        break;
      }
    }
  }
  return out;
}

/** The jurisdictions, deduped: a state with two rejected dockets is one rejected
 *  demand. Nothing in today's data has two, and the map cell is per state either way. */
export function rejectedStates(rows: readonly Rejection[]): Set<string> {
  return new Set(rows.map((r) => r.state));
}

/**
 * The cumulative teal line, in the same shape `cumulativeFilings` returns so the chart
 * can gate it with the same `visibleAt` and draw it with the same step geometry.
 *
 * Deduped by state BEFORE accumulating, on its earliest rejection: the line counts
 * jurisdictions against the same denominator the red line uses, so a state entering it
 * twice would push the total past a ceiling it shares with a line that cannot.
 */
export function cumulativeRejections(
  rows: readonly Rejection[],
): { date: string; t: number; added: number; total: number; states: string[] }[] {
  const earliest = new Map<string, string>();
  for (const r of rows) {
    const prev = earliest.get(r.state);
    if (!prev || r.rejected_at < prev) earliest.set(r.state, r.rejected_at);
  }
  const byDay = new Map<string, string[]>();
  for (const [state, date] of earliest) {
    const list = byDay.get(date);
    if (list) list.push(state);
    else byDay.set(date, [state]);
  }
  let total = 0;
  return [...byDay.keys()].sort().map((date) => {
    const states = byDay.get(date)!.sort();
    total += states.length;
    return { date, t: Date.parse(`${date}T00:00:00Z`), added: states.length, total, states };
  });
}
