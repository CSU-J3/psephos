// EVERY TEXT AN ENTRY HAS BEEN SERVED WITH, beside when psephos first held it (R1, Corey's
// rulings of 2026-09-30: every row and id kept, the page shows one entry per CourtListener
// object with its survivor text, and "every earlier description kept beside when it was
// seen").
//
// PURE, over two reads db.ts makes: the case's rows with the object each belongs to, and
// the ledger's items. An entry is the END of its object's twin_of chain -- the object
// record_entries counts -- so a tier-2 twin's texts sit under the entry they fold into,
// marked as a separate CourtListener record, which is what they are.

import { formatDate, utcDay } from "@/lib/format";

export type HistoryRow = {
  cl_entry_id: number;
  twin_of: number | null;
  /** The object's current row (cl_entries.current_row): the text the entry shows. */
  current_row: number | null;
  id: number;
  entry_at: string | null;
  description: string | null;
  seen_at: string | null;
  seen_by: string | null;
};

export type EarlierText = {
  text: string;
  entry_at: string | null;
  seen_at: string | null;
  seen_by: string | null;
  /** The text is a second CourtListener record for the entry (tier 2), not an earlier
   *  description of the same record (tier 1). */
  twin: boolean;
};

/** The entry an object belongs to: the end of its twin_of chain, a cycle stopping it. */
export function entryOf(id: number, twinOf: ReadonlyMap<number, number | null>): number {
  let at = id;
  const seen = new Set<number>();
  for (;;) {
    const next = twinOf.get(at);
    if (next == null || !twinOf.has(next) || seen.has(at)) return at;
    seen.add(at);
    at = next;
  }
}

/** Per item, in the items' order: the entry's other texts, earliest seen first, or
 *  undefined when there are none (an item with no object, or an entry never re-described).
 *  The text the item shows -- its survivor -- is left out, once. */
export function earlierTexts(
  history: readonly HistoryRow[],
  items: readonly { cl_entry_id: number | null; summary: string | null }[],
): (EarlierText[] | undefined)[] {
  const twinOf = new Map<number, number | null>();
  for (const r of history) twinOf.set(r.cl_entry_id, r.twin_of);
  const byEntry = new Map<number, HistoryRow[]>();
  for (const r of history) {
    const e = entryOf(r.cl_entry_id, twinOf);
    const list = byEntry.get(e);
    if (list) list.push(r);
    else byEntry.set(e, [r]);
  }
  return items.map((it) => {
    if (it.cl_entry_id == null) return undefined;
    const entry = entryOf(it.cl_entry_id, twinOf);
    const rows = byEntry.get(entry);
    if (!rows) return undefined;
    // THE SURVIVOR IS A ROW, NOT A TEXT: the entry's own current row, the one the fold
    // took the shown text from (collectors/cl_fold.py). Matching by text would leave out
    // the wrong row when the court re-dated an entry without changing its words -- the
    // Nevada shape, two rows with one text -- and list the current row as "earlier".
    const current = rows.find((r) => r.cl_entry_id === entry)?.current_row ?? null;
    const out: EarlierText[] = [];
    for (const r of rows) {
      if (current != null && r.id === current) continue;
      if (!r.description) continue;
      out.push({
        text: r.description,
        entry_at: r.entry_at,
        seen_at: r.seen_at,
        seen_by: r.seen_by,
        twin: r.cl_entry_id !== entry,
      });
    }
    out.sort((a, b) => (a.seen_at ?? "").localeCompare(b.seen_at ?? ""));
    return out.length ? out : undefined;
  });
}

/** "seen Jul 20, 2026", or "seen between Jul 20, 2026 and Jul 22, 2026" when psephos can
 *  only bound it (a row held before 2026-09-30 with no item: scripts/backfill_seen_at). */
export function seenLabel(e: Pick<EarlierText, "seen_at" | "seen_by">): string {
  if (!e.seen_at) return "seen: not recorded";
  if (!e.seen_by || utcDay(e.seen_by) === utcDay(e.seen_at)) return `seen ${formatDate(e.seen_at)}`;
  return `seen between ${formatDate(e.seen_at)} and ${formatDate(e.seen_by)}`;
}
