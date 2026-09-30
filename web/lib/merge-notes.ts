// THE DATED NOTES THE R1 SWITCH LEAVES ON EVERY SURFACE WHOSE FIGURE IT MOVES (Corey's
// ruling 5, 2026-09-30): "a dated note on each surface whose figure moves, saying duplicate
// court-entry rows were merged, with the before and after. Not silent, and not only a
// commit message."
//
// The figures are read once, at the switch, by tools/merge_notes.py -- rows against
// entries from ONE state of the record -- into lib/entry-merge.json. A surface whose
// figure did not move carries no note. Before the switch the file carries no date and
// every function here returns null.
//
// EVERY NOTE PRINTS BOTH FIGURES, the before and the after as recorded at the switch,
// never the live count beside it: a docket that gains entries later must not make the
// merge look larger or smaller than it was.
//
// THE DATE IS THE SWITCH'S, never a clock read: the dated-ahead rule allows a dated line
// the record's clock or a hand-authored date, and this is the second.

import raw from "@/lib/entry-merge.json";
import { formatDate } from "@/lib/format";

type Pair = [number, number];
type CaseMove = {
  entries?: Pair;
  apart?: number;
  ledger?: Pair;
  timeline?: Pair;
  latest_entry_at?: [string | null, string | null];
};
export type MergeFigures = {
  on: string | null;
  why: string;
  clock: string | null;
  wire: {
    litigation?: { total: Pair; day: Pair; week: Pair; history?: Pair; tracker_notes?: number };
  };
  map: { entries: Pair; dockets_changed: number; apart?: number };
  rejected?: { count: Pair; states: Record<string, [string | null, string | null]> };
  cases: Record<string, CaseMove>;
};

export const MERGE = raw as MergeFigures;

const n = (x: number) => x.toLocaleString("en-US");
const plural = (x: number, one: string, many = `${one}s`) => `${n(x)} ${x === 1 ? one : many}`;

function on(m: MergeFigures): string | null {
  return m.on ? formatDate(m.on) : null;
}

/** An entry count can RISE at the switch: a CourtListener entry whose text and day were
 *  another entry's row was absorbed by the old key and is counted apart now. The note
 *  says so rather than calling a rise a merge. */
function apartClause(apart: number | undefined): string {
  return apart ? `, and ${plural(apart, "entry", "entries")} that shared another entry's text and day now counted apart` : "";
}

/** The Wire's litigation cell: its counts are entries now. The fold also takes the
 *  tracker's repeated notes (ruling 7), so the reason names them when they are part of
 *  the drop. */
export function wireNote(channel: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const w = m.wire.litigation;
  if (!d || channel !== "litigation" || !w) return null;
  const keys = (["total", "day", "week", "history"] as const).filter((k) => w[k] && w[k]![0] !== w[k]![1]);
  if (!keys.length) return null;
  const label = { total: "the total", day: "+24h", week: "+7d", history: "already older than 7 days when collected" };
  const parts = keys.map((k) => `${label[k]} ${n(w[k]![0])} before, ${n(w[k]![1])} after`);
  const why = w.tracker_notes
    ? `duplicate court-entry rows and repeated tracker notes were merged (${plural(w.tracker_notes, "tracker note")} of the drop)`
    : m.why;
  return `${d}: ${why}; ${parts.join("; ")}.`;
}

/** A docket line on the map: its "· N entries". */
export function entriesNote(caseId: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const c = m.cases[caseId];
  if (!d || !c?.entries) return null;
  const [b, a] = c.entries;
  return `${d}: ${m.why}${apartClause(c.apart)}; ${n(b)} before, ${n(a)} after`;
}

/** The map panel as a whole. */
export function mapNote(m: MergeFigures = MERGE): string | null {
  const d = on(m);
  if (!d || !m.map.dockets_changed) return null;
  const [b, a] = m.map.entries;
  return `${d}: ${m.why}${apartClause(m.map.apart)}. The campaign's dockets held ${n(b)} entries ` +
    `before, ${n(a)} after; ${plural(m.map.dockets_changed, "docket")} changed.`;
}

/** A /case page's "N entries". */
export function ledgerNote(caseId: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const l = m.cases[caseId]?.ledger;
  if (!d || !l) return null;
  return `${d}: ${m.why}; this docket read ${n(l[0])} entries before, ${n(l[1])} after.`;
}

/** A docket's latest-entry date, wherever it is shown. */
export function latestNote(caseId: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const l = m.cases[caseId]?.latest_entry_at;
  if (!d || !l) return null;
  return `${d}: ${m.why}; the latest entry's date read ${formatDate(l[0])} before, ` +
    `${formatDate(l[1])} after.`;
}

/** The homepage's rejected-demands figure: the outcome reads each entry's current text
 *  now, so a clerk's strike or a re-date can move it (ruling 2). */
export function rejectedNote(m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const r = m.rejected;
  if (!d || !r) return null;
  const moved = Object.keys(r.states);
  if (r.count[0] === r.count[1] && !moved.length) return null;
  const which = moved.length ? ` (${moved.join(", ")})` : "";
  return `${d}: ${m.why}, and the outcome now reads each entry's current text; ` +
    `${n(r.count[0])} before, ${n(r.count[1])} after${which}.`;
}
