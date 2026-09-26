// DATED AHEAD OF THE RECORD'S CLOCK: the one predicate every date surface uses.
//
// A source can date a row after the moment psephos collected it. LegiScan dates MI's
// "Bill Electronically Reproduced 09/24/2026" to 2026-09-29, five days after the text's
// own date, and the Federal Register dates a Friday's document to the next Monday. The
// date stays the source's, verbatim -- storage is never rewritten -- and the page says
// so beside it: a small "dated ahead" marker, whose title names the source's date and
// the record's clock (ruled 2026-09-26).
//
// THE CLOCK IS THE RECORD'S, NEVER THE RENDERER'S. `clock` is the page's anchor,
// MAX(items.fetched_at), read by `getRecordAnchor`. Nothing here reads `Date.now()`:
// a row is "ahead" relative to what the record has collected, which is the same edge
// every window on the homepage is cut at (see the single-writer invariant).
//
// BY UTC DAY, NOT BY INSTANT. The date prefix is compared, through `utcDay`, exactly as
// `formatDate`, the homepage's day bands and the SQL `substr(...,1,10)` read dates. An
// instant rule would mark a news item "Sep 26" as ahead of a clock reading Sep 26,
// 11:32Z, which the reader would see as the same day. No row in the record's history has
// ever differed between the two readings (D0, 2026-09-26), and one meaning of "ahead"
// across every surface is the point.
//
// ONE MEANING OF "LATEST". A row dated ahead is never the latest: `newestUpTo` skips it,
// and every recency list sorts it after the rows dated up to the clock, marked, and
// never truncated away. So "Latest movement" cannot open with one.

import { formatDate, utcDay, windowEndLabel } from "@/lib/format";
import type { Bill, Case } from "@/lib/db";

/** The page's clock: the anchor's ISO string, or a Date built from it. */
export type RecordClock = string | Date | null | undefined;

function clockDay(clock: RecordClock): number | null {
  if (!clock) return null;
  return utcDay(typeof clock === "string" ? clock : clock.toISOString());
}

function clockIso(clock: RecordClock): string | null {
  if (!clock) return null;
  return typeof clock === "string" ? clock : clock.toISOString();
}

/**
 * True when `value`'s UTC day is after the record clock's UTC day. False for a missing
 * or unparseable date, and false when there is no clock: with nothing collected there
 * is no edge to be ahead of, and a marker would claim one.
 */
export function datedAhead(value: string | null | undefined, clock: RecordClock): boolean {
  const day = utcDay(value);
  const edge = clockDay(clock);
  return day !== null && edge !== null && day > edge;
}

/**
 * Split rows into those dated up to the clock and those dated ahead of it, keeping each
 * part in its input order. A row with no date belongs with `upTo`: it makes no claim to
 * be ahead, and the surfaces already decide where an undated row sits.
 */
export function splitByClock<T>(
  rows: readonly T[],
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
): { upTo: T[]; ahead: T[] } {
  const upTo: T[] = [];
  const ahead: T[] = [];
  for (const r of rows) (datedAhead(at(r), clock) ? ahead : upTo).push(r);
  return { upTo, ahead };
}

/**
 * Sort with the surface's own comparator, then move every row dated ahead after the
 * rows dated up to the clock. Both parts keep the comparator's order. For a list that
 * shows only its first `limit` rows, pass the limit: the rows dated up to the clock are
 * cut to it and the ahead rows are appended whole, because a row dated ahead is never
 * truncated away (ruled 2026-09-26).
 */
export function orderByClock<T>(
  rows: readonly T[],
  compare: (a: T, b: T) => number,
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
  limit?: number,
): T[] {
  const { recent, ahead } = recentAndAhead(rows, compare, at, clock, limit);
  return [...recent, ...ahead];
}

/**
 * A COUNTED LIST, KEPT TRUE TO ITS COUNT: the `limit` most recent rows dated up to the
 * clock, and, separately, every row dated ahead -- sorted, uncut. For a list whose
 * heading states its length ("ten most recent actions"): the heading describes
 * `recent` alone, and `ahead` renders below a divider after it (ruled 2026-09-26).
 * Two fields rather than one array, so a caller cannot render the ten and lose the row
 * dated ahead without writing that it did.
 */
export function recentAndAhead<T>(
  rows: readonly T[],
  compare: (a: T, b: T) => number,
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
  limit?: number,
): { recent: T[]; ahead: T[] } {
  const sorted = [...rows].sort(compare);
  const { upTo, ahead } = splitByClock(sorted, at, clock);
  return { recent: limit === undefined ? upTo : upTo.slice(0, limit), ahead };
}

/**
 * The newest row by `at`, skipping rows dated ahead of the clock. Ordered by
 * `Date.parse`, exactly as lib/read.ts's `newest` always has; the skip is the only
 * difference, so a surface moved onto this changes in one way and one way only.
 */
/**
 * THE SHAPE OF EVERY FOLDED RECENCY LIST: the rows dated up to the clock, cut at `head`,
 * the remainder of them for the fold, and every row dated ahead -- uncut, for after the
 * fold. Keeps input order, so the caller sorts first (or passes rows already sorted).
 * The homepage's cases rail and the detail ledgers (lib/ledger.ts#sliceLedger) use it.
 */
export function foldByClock<T>(
  rows: readonly T[],
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
  head: number,
): { head: T[]; rest: T[]; ahead: T[] } {
  const { upTo, ahead } = splitByClock(rows, at, clock);
  return { head: upTo.slice(0, head), rest: upTo.slice(head), ahead };
}

/** The date the homepage's cases rail orders a docket by: its latest entry, else its filing. */
export const caseDate = (c: Pick<Case, "latest_entry_at" | "filed_at">) => c.latest_entry_at ?? c.filed_at;

/** The date the watched-bills fold orders a bill by: its latest action, else its introduction. */
export const billDate = (b: Pick<Bill, "latest_action_at" | "introduced_at">) =>
  b.latest_action_at ?? b.introduced_at;

/** Input order, with every row dated ahead moved after the rest: an unfolded list. */
export function aheadLast<T>(
  rows: readonly T[],
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
): T[] {
  const { upTo, ahead } = splitByClock(rows, at, clock);
  return [...upTo, ...ahead];
}

export function newestUpTo<T>(
  rows: readonly T[],
  at: (row: T) => string | null | undefined,
  clock: RecordClock,
): T | null {
  let best: T | null = null;
  let bestT = -Infinity;
  for (const r of rows) {
    const v = at(r);
    if (!v || datedAhead(v, clock)) continue;
    const t = Date.parse(v);
    if (Number.isNaN(t) || t <= bestT) continue;
    best = r;
    bestT = t;
  }
  return best;
}

/** The marker's title: the source's date and the record's clock, and nothing else. */
export function aheadTitle(value: string | null | undefined, clock: RecordClock): string {
  const iso = clockIso(clock);
  const edge = iso ? `${formatDate(iso)}, ${windowEndLabel(iso) ?? ""}`.replace(/, $/, "") : "not set";
  return `The source dates this ${formatDate(value)}. This record's clock reads ${edge}.`;
}

/** The `YYYY-MM-DD` a date element carries for machines, or null when there is none. */
export function dayIso(value: string | null | undefined): string | null {
  return utcDay(value) === null ? null : value!.slice(0, 10);
}
