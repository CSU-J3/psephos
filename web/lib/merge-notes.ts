// THE DATED NOTES THE R1 SWITCH LEAVES ON EVERY SURFACE WHOSE FIGURE IT MOVES (Corey's
// ruling 5, 2026-09-30): "a dated note on each surface whose figure moves, saying duplicate
// court-entry rows were merged, with the before and after. Not silent, and not only a
// commit message."
//
// The figures are read once, at the switch, by tools/merge_notes.py -- every figure from
// ONE state of the record -- into lib/entry-merge.json, as a list of MOVES. The first is the
// merge of duplicate rows (tier 1). A tier-2 link that moved a figure is a later move with
// its OWN dated note (Corey, 2026-10-02: "Tier 2's links, when decided, get their own dated
// note"), so a surface carries one dated sentence per move that moved its figure. A surface
// whose figure no move touched carries no note. Before the switch the file carries no date
// and every function here returns null.
//
// EVERY NOTE PRINTS BOTH FIGURES, the before and the after as recorded at its move, never
// the live count beside it: a docket that gains entries later must not make the merge look
// larger or smaller than it was.
//
// THE DATE IS THE MOVE'S, never a clock read: the dated-ahead rule allows a dated line the
// record's clock or a hand-authored date, and this is the second.

import raw from "@/lib/entry-merge.json";
import { formatDate } from "@/lib/format";

// [before, after]. Typed as arrays, not tuples, because a JSON import infers number[] for
// them: the tuple type made `raw as MergeFigures` a compile error the day the file was
// written with figures in it, which the empty placeholder hid, and the double cast that
// would silence it is what assert-casts exists to refuse.
type Pair = number[];
type CaseMove = {
  entries?: Pair;
  apart?: number;
  ledger?: Pair;
  timeline?: Pair;
  latest_entry_at?: (string | null)[];
};
export type Move = {
  kind: "merge" | "link";
  on: string | null;
  why: string;
  clock: string | null;
  /** A link move: how many tier-2 links it made. The switch's move made every link psephos
   *  then held (8); a later batch is its own move, counting its own (tools/merge_notes.py
   *  --append-link-move). */
  links?: number;
  wire: {
    litigation?: { total: Pair; day: Pair; week: Pair; history?: Pair; tracker_notes?: number };
  };
  map: { entries: Pair; dockets_changed: number; apart?: number };
  rejected?: { count: Pair; states: Record<string, (string | null)[]> };
  /** Only the dockets the move moved. A JSON import reads the moves as one union, giving
   *  each move every other move's dockets as undefined, so a docket may map to nothing; the
   *  type without it stopped the cast compiling the day a third move was written. */
  cases: Record<string, CaseMove | undefined>;
};
export type MergeFigures = { on: string | null; clock: string | null; moves: Move[] };

export const MERGE = raw as MergeFigures;

const n = (x: number) => x.toLocaleString("en-US");
const plural = (x: number, one: string, many = `${one}s`) => `${n(x)} ${x === 1 ? one : many}`;

/** One dated sentence per move that has one for this figure, a line each (MergeNote puts
 *  each on its own line, so a link's note stands apart from the merge's), or null when no
 *  move has one. */
function notes(m: MergeFigures, one: (mv: Move, on: string) => string | null): string | null {
  if (!m.on) return null;
  const out = m.moves.flatMap((mv) => {
    const s = mv.on ? one(mv, formatDate(mv.on)) : null;
    return s ? [s] : [];
  });
  return out.length ? out.join("\n") : null;
}

/** A link move's reason, counted. Corey (2026-10-02): "the links' dated line counts 8".
 *  Each linked pair takes exactly one entry off its docket's count, so an entry count's own
 *  drop is how many links moved it: a docket says its own, the map panel the campaign's,
 *  and the Wire, which counts every docket, all of them. */
function linkWhy(pairs: number): string {
  return `${plural(pairs, "pair")} of court records that describe one entry ${pairs === 1 ? "was" : "were"} linked`;
}

/** Why an entry count moved, naming only what happened to it. A count can RISE at the
 *  merge: a CourtListener entry whose text and day were another entry's row was absorbed
 *  by the old key and is counted apart now. Each such entry adds one, so the rows the
 *  merge folded are `apart + before - after`; a docket where none folded is said to have
 *  counted entries apart, never to have merged anything. */
function entriesWhy(mv: Move, before: number, after: number, apart = 0): string {
  if (mv.kind === "link") return linkWhy(before - after);
  if (mv.kind !== "merge") return mv.why;
  const rose = apart ? `${plural(apart, "entry", "entries")} that shared another entry's text and day now counted apart` : "";
  if (apart + before - after > 0) return rose ? `${mv.why}, and ${rose}` : mv.why;
  return rose || mv.why;
}

/** The reason on a docket's own figure that is not its entry count (its ledger): a link
 *  move counts the docket's links by its entry count's drop. */
function docketWhy(mv: Move, caseId: string): string {
  const e = mv.cases[caseId]?.entries;
  return mv.kind === "link" && e ? linkWhy(e[0] - e[1]) : mv.why;
}

/** The Wire's litigation cell: its counts are entries now. The merge also folds the
 *  tracker's repeated notes (ruling 7), so the reason names them when they are part of
 *  the drop. */
export function wireNote(channel: string, m: MergeFigures = MERGE): string | null {
  if (channel !== "litigation") return null;
  return notes(m, (mv, d) => {
    const w = mv.wire.litigation;
    if (!w) return null;
    const keys = (["total", "day", "week", "history"] as const).filter((k) => w[k] && w[k]![0] !== w[k]![1]);
    if (!keys.length) return null;
    const label = { total: "the total", day: "+24h", week: "+7d", history: "already older than 7 days when collected" };
    const parts = keys.map((k) => `${label[k]} ${n(w[k]![0])} before, ${n(w[k]![1])} after`);
    const why = w.tracker_notes
      ? `duplicate court-entry rows and repeated tracker notes were merged (${plural(w.tracker_notes, "tracker note")} of the drop)`
      : mv.kind === "link" && mv.links
        ? linkWhy(mv.links)
        : mv.why;
    return `${d}: ${why}; ${parts.join("; ")}.`;
  });
}

/** A docket line on the map: its "· N entries". */
export function entriesNote(caseId: string, m: MergeFigures = MERGE): string | null {
  return notes(m, (mv, d) => {
    const c = mv.cases[caseId];
    if (!c?.entries) return null;
    const [b, a] = c.entries;
    return `${d}: ${entriesWhy(mv, b, a, c.apart)}; ${n(b)} before, ${n(a)} after.`;
  });
}

/** The map panel as a whole. */
export function mapNote(m: MergeFigures = MERGE): string | null {
  return notes(m, (mv, d) => {
    if (!mv.map.dockets_changed) return null;
    const [b, a] = mv.map.entries;
    return `${d}: ${entriesWhy(mv, b, a, mv.map.apart)}. The campaign's dockets held ${n(b)} entries ` +
      `before, ${n(a)} after; ${plural(mv.map.dockets_changed, "docket")} changed.`;
  });
}

/** A /case page's "N entries". */
export function ledgerNote(caseId: string, m: MergeFigures = MERGE): string | null {
  return notes(m, (mv, d) => {
    const l = mv.cases[caseId]?.ledger;
    if (!l) return null;
    return `${d}: ${docketWhy(mv, caseId)}; this docket read ${n(l[0])} entries before, ${n(l[1])} after.`;
  });
}

/** A docket's latest-entry date, wherever it is shown. */
export function latestNote(caseId: string, m: MergeFigures = MERGE): string | null {
  return notes(m, (mv, d) => {
    const l = mv.cases[caseId]?.latest_entry_at;
    if (!l) return null;
    return `${d}: ${mv.why}; the latest entry's date read ${formatDate(l[0])} before, ` +
      `${formatDate(l[1])} after.`;
  });
}

/** The homepage's rejected-demands figure: the outcome reads each entry's current text
 *  now, so a clerk's strike or a re-date can move it (ruling 2). */
export function rejectedNote(m: MergeFigures = MERGE): string | null {
  return notes(m, (mv, d) => {
    const r = mv.rejected;
    if (!r) return null;
    const moved = Object.keys(r.states);
    if (r.count[0] === r.count[1] && !moved.length) return null;
    const which = moved.length ? ` (${moved.join(", ")})` : "";
    const why = mv.kind === "link" && mv.links ? linkWhy(mv.links) : mv.why;
    return `${d}: ${why}, and the outcome now reads each entry's current text; ` +
      `${n(r.count[0])} before, ${n(r.count[1])} after${which}.`;
  });
}
