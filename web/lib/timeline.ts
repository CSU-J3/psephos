// Day bands for the board's timeline: every channel on one axis, ordered by WHEN
// THINGS HAPPENED rather than when they arrived.
//
// WHY THIS IS NOT IN feed.ts. That module orders on `fetched_at` and says at length
// why -- a feed keyed on occurred_at has items appearing in the middle of the list as
// they age into the window, which no reader can follow. Both orderings are correct for
// their own object, and putting two contradictory sort contracts in one module is how
// a later reader picks the wrong one. The types are shared; the ordering is not.
//
// The pairing this exists for: a story dated four days ago but collected this morning
// lands on ITS OWN DATE and still carries the collected-today dot. The feed could only
// show one of those two facts. Here the date positions it and the dot marks it, and the
// two instruments are independent by construction -- see `isFresh`, which reads
// `fetched_at`, against `dayKeyOf`, which reads `occurred_at`.

import { isHistoryEntry, type FeedEntry } from "@/lib/feed";
import { utcDay } from "@/lib/format";

/** Collected within this many hours counts as fresh -- the filled dot. */
export const FRESH_HOURS = 24;

/** Individually-rendered news rows per day before the rest fold into one line. */
export const NEWS_ROWS_PER_DAY = 3;

/**
 * How many day bands the column shows. It is headed "The last 7 days" and it means it.
 *
 * A fixed range rather than one derived from the data, because the alternative was
 * measured and is worse: the live 08-16 window carried unanchored items dated as far
 * back as 2025-06-04, and a data-derived range emits 400+ bands of which all but a
 * handful are empty. Items collected in the window but dated before the range are NOT
 * dropped -- they are reported in `olderThanWindow`, because a silent truncation reads
 * as "this is everything".
 */
export const BAND_DAYS = 7;

const DAY_MS = 86_400_000;

/** `YYYY-MM-DD` in UTC, or null. Date-only, matching format.utcDay's rule. */
export function dayKey(value: string | null | undefined): string | null {
  const d = utcDay(value);
  return d === null ? null : new Date(d).toISOString().slice(0, 10);
}

/**
 * The day an entry belongs on: its own `occurred_at`, falling back to `fetched_at`
 * when it has no date. 41 litigation rows carry no date at all, and dropping them
 * would lose real events; placing them on their collection day is the only honest
 * placement available and is marked as undated in the row.
 */
export function dayKeyOf(e: FeedEntry): string {
  return dayKey(e.occurred_at) ?? dayKey(e.fetched_at)!;
}

/**
 * Collected in the last `FRESH_HOURS`. Reads `fetched_at` and NOTHING ELSE, so it is
 * independent of where the entry sits on the axis. That independence is the point:
 * a backdated item is fresh, and a re-read old item on today's date is not.
 */
export function isFresh(e: FeedEntry, now: Date): boolean {
  const t = Date.parse(e.fetched_at);
  if (Number.isNaN(t)) return false;
  return now.getTime() - t <= FRESH_HOURS * 3_600_000;
}

function grade(e: FeedEntry): string {
  return `${e.admiralty_source}${e.admiralty_info}`;
}

/** One docket's entries on one day: the caption once, the entry text beneath. */
export type CaseGroup = {
  caseId: string;
  entries: FeedEntry[];
  fresh: boolean;
};

/**
 * A seed row: one anchor's back-history collapsed to a single line.
 *
 * ONE ROW PER ANCHOR GROUP, NEVER PER ENTRY. A bootstrap poll writes an entire
 * docket's history in one run, so on 2026-08-16 four dockets landed 174 entries dated
 * across Sep 2025 - Jul 2026. Rendered per entry that is 174 rows scattered over ten
 * months of bands, which buries the day's actual news under an import. Rendered per
 * anchor it is four lines that say what was added and over what span.
 *
 * These sit on the day they were COLLECTED, not on their own dates -- the event being
 * reported is "this arrived in the record", and it has one date.
 */
export type SeedRow = {
  key: string;
  anchorId: string;
  count: number;
  firstOccurredAt: string | null;
  lastOccurredAt: string | null;
  sample: FeedEntry;
};

export type NewsFold = {
  shown: FeedEntry[];
  foldedCount: number;
  /** Distinct source ids behind the fold, in first-seen order. */
  sources: string[];
};

export type DayBand = {
  day: string; // YYYY-MM-DD, UTC
  empty: boolean;
  /** Everything placed on this day, newest first, before splitting by channel. */
  entries: FeedEntry[];
  cases: CaseGroup[];
  news: NewsFold;
  other: FeedEntry[]; // legislation, executive, state -- one row each
  seeds: SeedRow[];
  /** Any entry on this band collected inside the fresh window. */
  hasFresh: boolean;
};

export type Timeline = {
  bands: DayBand[];
  /**
   * Collected inside the window but dated before the band range. Surfaced, never
   * dropped: on 2026-08-16 this is 11 unanchored news items dated back to 2025-06-04.
   */
  olderThanWindow: FeedEntry[];
  totalEntries: number;
};

/** The anchor an entry groups on, or null when it has none. */
function anchorId(e: FeedEntry): string | null {
  return e.case_id ?? e.bill_id ?? e.state_bill_id ?? null;
}

/**
 * Up to `NEWS_ROWS_PER_DAY` individual rows, best-graded first, the rest folded.
 *
 * Grade before recency, so a B2 tracker report is never pushed below the fold by three
 * C3 aggregator hits that happen to be newer. Ties break on newest.
 */
export function foldNews(
  entries: readonly FeedEntry[],
  max: number = NEWS_ROWS_PER_DAY,
): NewsFold {
  const ranked = [...entries].sort((a, b) => {
    const g = grade(a).localeCompare(grade(b));
    if (g !== 0) return g;
    return Date.parse(b.occurred_at ?? b.fetched_at) -
      Date.parse(a.occurred_at ?? a.fetched_at);
  });
  const shown = ranked.slice(0, max);
  const folded = ranked.slice(max);
  const sources: string[] = [];
  for (const e of folded) if (!sources.includes(e.source_id)) sources.push(e.source_id);
  return { shown, foldedCount: folded.length, sources };
}

/**
 * Build the day bands.
 *
 * EVERY DAY IN RANGE GETS A BAND, including the ones holding nothing. A day the reader
 * can see is empty is information -- it says the system looked and found nothing. A day
 * silently omitted is indistinguishable from a day the collector never ran, which is
 * the failure a monitor most needs to make visible.
 */
export function buildTimeline(
  rows: readonly FeedEntry[],
  now: Date,
  bandDays: number = BAND_DAYS,
): Timeline {
  // A SEED IS ANCHORED BACK-HISTORY, NOT MERELY OLD, and getting this wrong was
  // measured rather than reasoned about. Routing every history entry to a seed row
  // turned 11 unanchored news items -- backdated stories collected today -- into
  // "Added to the record" lines on the collection day, which is the exact opposite of
  // what the timeline exists to do: a backdated story must land on ITS OWN DATE and
  // still carry the fresh dot. Only entries carrying a case/bill/state anchor form
  // seed rows, and on 2026-08-16 that is 4 rows covering 66+55+43+10 = 174 entries.
  const seedRows: FeedEntry[] = [];
  const dated: FeedEntry[] = [];
  for (const e of rows) {
    if (isHistoryEntry(e) && anchorId(e) !== null) seedRows.push(e);
    else dated.push(e);
  }

  const todayKey = dayKey(now.toISOString())!;
  const days: string[] = [];
  for (let i = 0; i < bandDays; i++) {
    days.push(new Date(Date.parse(`${todayKey}T00:00:00Z`) - i * DAY_MS).toISOString().slice(0, 10));
  }
  const inRange = new Set(days);

  const placed = new Map<string, FeedEntry[]>();
  const olderThanWindow: FeedEntry[] = [];
  for (const e of dated) {
    const k = dayKeyOf(e);
    if (!inRange.has(k)) {
      olderThanWindow.push(e);
      continue;
    }
    const list = placed.get(k);
    if (list) list.push(e);
    else placed.set(k, [e]);
  }

  const seedsByDay = new Map<string, Map<string, FeedEntry[]>>();
  for (const e of seedRows) {
    const k = dayKey(e.fetched_at)!;
    if (!inRange.has(k)) continue;
    const byAnchor = seedsByDay.get(k) ?? new Map<string, FeedEntry[]>();
    const id = anchorId(e)!;
    const list = byAnchor.get(id);
    if (list) list.push(e);
    else byAnchor.set(id, [e]);
    seedsByDay.set(k, byAnchor);
  }

  const bands: DayBand[] = days.map((day) => {
    const entries = [...(placed.get(day) ?? [])].sort(
      (a, b) =>
        Date.parse(b.occurred_at ?? b.fetched_at) -
          Date.parse(a.occurred_at ?? a.fetched_at) || b.id - a.id,
    );

    const caseMap = new Map<string, FeedEntry[]>();
    const news: FeedEntry[] = [];
    const other: FeedEntry[] = [];
    for (const e of entries) {
      if (e.channel === "news") news.push(e);
      else if (e.case_id) {
        const list = caseMap.get(e.case_id);
        if (list) list.push(e);
        else caseMap.set(e.case_id, [e]);
      } else other.push(e);
    }

    const seedGroups = seedsByDay.get(day);
    const seeds: SeedRow[] = seedGroups
      ? [...seedGroups.entries()].map(([id, es]) => {
          const dates = es
            .map((e) => e.occurred_at)
            .filter((d): d is string => !!d)
            .sort();
          return {
            key: `${day}:${id}`,
            anchorId: id,
            count: es.length,
            firstOccurredAt: dates[0] ?? null,
            lastOccurredAt: dates.at(-1) ?? null,
            sample: es[0],
          };
        })
      : [];
    seeds.sort((a, b) => b.count - a.count);

    const seedEntries = seedGroups ? [...seedGroups.values()].flat() : [];
    return {
      day,
      empty: entries.length === 0 && seeds.length === 0,
      entries,
      cases: [...caseMap.entries()].map(([caseId, es]) => ({
        caseId,
        entries: es,
        fresh: es.some((e) => isFresh(e, now)),
      })),
      news: foldNews(news),
      other,
      seeds,
      hasFresh: [...entries, ...seedEntries].some((e) => isFresh(e, now)),
    };
  });

  return { bands, olderThanWindow, totalEntries: rows.length };
}
