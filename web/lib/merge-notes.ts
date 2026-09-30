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
// THE DATE IS THE SWITCH'S, never a clock read: the dated-ahead rule allows a dated line
// the record's clock or a hand-authored date, and this is the second.

import raw from "@/lib/entry-merge.json";
import { formatDate } from "@/lib/format";

type Pair = [number, number];
type CaseMove = {
  entries?: Pair;
  ledger?: Pair;
  latest_entry_at?: [string | null, string | null];
};
export type MergeFigures = {
  on: string | null;
  why: string;
  clock: string | null;
  wire: { litigation?: { total: Pair; day: Pair; week: Pair } };
  map: { entries: Pair; dockets_changed: number };
  cases: Record<string, CaseMove>;
};

export const MERGE = raw as MergeFigures;

const n = (x: number) => x.toLocaleString("en-US");

function on(m: MergeFigures): string | null {
  return m.on ? formatDate(m.on) : null;
}

/** The Wire's litigation cell: its three counts are entries now. */
export function wireNote(channel: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const w = m.wire.litigation;
  if (!d || channel !== "litigation" || !w) return null;
  const moved = (["total", "day", "week"] as const).filter((k) => w[k][0] !== w[k][1]);
  if (!moved.length) return null;
  const label = { total: "the total", day: "+24h", week: "+7d" };
  const parts = moved.map((k) => `${label[k]} ${n(w[k][0])} before, ${n(w[k][1])} after`);
  return `${d}: ${m.why}; ${parts.join("; ")}.`;
}

/** A docket line on the map: its "· N entries". */
export function entriesNote(caseId: string, m: MergeFigures = MERGE): string | null {
  const d = on(m);
  const e = m.cases[caseId]?.entries;
  if (!d || !e) return null;
  return `${n(e[0])} before ${d}, when ${m.why}`;
}

/** The map panel as a whole. */
export function mapNote(m: MergeFigures = MERGE): string | null {
  const d = on(m);
  if (!d || !m.map.dockets_changed) return null;
  const [b, a] = m.map.entries;
  return `${d}: ${m.why}. The campaign's dockets held ${n(b)} entries before, ${n(a)} after; ` +
    `${m.map.dockets_changed} docket${m.map.dockets_changed === 1 ? "" : "s"} changed.`;
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
