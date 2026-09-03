// Grouping rules for the reporting archive: which month a row belongs to, and who
// published what. Pure derivations over stored columns, tested on constructed rows --
// the same division `lib/ledger.ts` keeps with `Timeline.tsx`.

import type { NewsItem } from "@/lib/db";

/** Rows filed under this key sort last, behind every real month. */
export const UNDATED = "undated";

/**
 * The month a row belongs to: `YYYY-MM`, by STRING SLICE and never `new Date()`.
 *
 * `occurred_at` on this channel is `+00:00`-suffixed, but the constructor still reads
 * it into the runtime's local zone, and a month boundary is exactly where that shows:
 * `new Date("2026-09-01T00:30:00+00:00").getMonth()` is August anywhere behind UTC, so
 * a reader in Denver would find the first rows of a month filed under the previous one
 * -- silently, only near the edge, and only for some viewers. This is the same rule
 * `lib/format.ts` keeps with `utcDay`, applied one field wider.
 */
export function monthKey(occurred_at: string | null): string {
  return occurred_at ? occurred_at.slice(0, 7) : UNDATED;
}

export type MonthGroup = {
  /** `YYYY-MM`, or `UNDATED`. */
  month: string;
  /** That month's rows, newest first. */
  items: NewsItem[];
};

/**
 * Group into months, newest month first, newest row first inside each.
 *
 * THE INTRA-MONTH TIEBREAK IS `occurred_at` DESC THEN `id` DESC -- identical to
 * `sliceLedger`, and it is not decoration. Same-day rows are the common case here, not
 * the exception: 218 items landed in 2026-08 alone, so most adjacent pairs on this page
 * share a date and the tiebreak decides what the reader actually sees. Left untiebroken
 * the order is arrival order, which is a property nobody chose and which changes when a
 * backfill runs.
 *
 * The key is compared as a STRING, matching the query's TEXT collation and `monthKey`'s
 * reasoning above. `UNDATED` is forced last rather than left to that comparison, which
 * would sort "undated" ABOVE every month beginning "2".
 *
 * Sorts a copy: the page hands the same array to `sourceRoster`, and `Array.sort` is
 * in-place.
 */
export function groupByMonth(items: readonly NewsItem[]): MonthGroup[] {
  const byMonth = new Map<string, NewsItem[]>();
  for (const it of items) {
    const key = monthKey(it.occurred_at);
    const group = byMonth.get(key);
    if (group) group.push(it);
    else byMonth.set(key, [it]);
  }

  const groups = [...byMonth.entries()].map(([month, rows]) => ({
    month,
    items: [...rows].sort(
      (a, b) =>
        (b.occurred_at ?? "").localeCompare(a.occurred_at ?? "") || b.id - a.id,
    ),
  }));

  return groups.sort((a, b) => {
    if (a.month === UNDATED) return 1;
    if (b.month === UNDATED) return -1;
    return b.month.localeCompare(a.month);
  });
}

export type SourceCount = { source_id: string; count: number };

/**
 * Who published what, busiest first.
 *
 * CALLED WITH THE UNFILTERED LIST even when the page is filtered, which is why this is
 * a second pass rather than a fold into `groupByMonth`. A roster computed over the
 * filtered rows would show only the source already selected, leaving no way back out of
 * the filter from inside the page -- and the empty view, where the filter matched
 * nothing, would show no roster at all and strand the reader completely.
 *
 * Ties break on the name so the order is stable between runs rather than dependent on
 * insertion order.
 */
export function sourceRoster(items: readonly NewsItem[]): SourceCount[] {
  const counts = new Map<string, number>();
  for (const it of items) counts.set(it.source_id, (counts.get(it.source_id) ?? 0) + 1);
  return [...counts.entries()]
    .map(([source_id, count]) => ({ source_id, count }))
    .sort((a, b) => b.count - a.count || a.source_id.localeCompare(b.source_id));
}
