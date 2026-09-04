// "The read": six computed sentences, one per channel, replacing the channel strip's
// bare counts on the board homepage.
//
// EVERY FUNCTION HERE IS PURE AND TAKES ITS ROWS AS ARGUMENTS. None issues a query,
// none imports the database client, and all of them are callable from a test with no
// database and no network. The page fetches; this module derives. Where a function
// needs something the page does not already fetch, the page fetches it and passes it
// in -- see `readNews`, which takes the 24-hour collection count rather than reaching
// for `getChannelActivity` itself.
//
// Each function returns VALUES, never a formatted string. The component does the
// formatting, so a test can assert on a number or a date instead of on prose, and so
// the same figure can be rendered two ways without duplicating the derivation.
//
// Each function must also be able to say "nothing", and say it with a date attached
// where the record has one. "No movement" is not an answer -- the empty case is what a
// reader hits on a quiet day, and a sentence that carries no date tells them nothing
// about whether the system is quiet or broken. That is why several of these types keep
// a `mostRecent`/`latestActionAt` field that is populated even when the in-window count
// is zero: the empty sentence is built from it.

import type { Bill, CampaignRow, ExecItem, NewsItem, StateBill } from "@/lib/db";
import type { ActivityRow } from "@/lib/activity";
import { buildCells, summarize, type CampaignSummary } from "@/lib/campaign";
import { relevanceScore } from "@/lib/relevance";

/** The read's window, in days. Shared so the tests and the components cannot drift. */
export const READ_WINDOW_DAYS = 7;

const DAY_MS = 86_400_000;

/** Start of the window, inclusive. An item dated exactly on it is INSIDE. */
export function windowStart(now: Date, days: number = READ_WINDOW_DAYS): Date {
  return new Date(now.getTime() - days * DAY_MS);
}

function inWindow(value: string | null, now: Date, days = READ_WINDOW_DAYS): boolean {
  if (!value) return false;
  const t = Date.parse(value);
  if (Number.isNaN(t)) return false;
  // Inclusive at the far edge, exclusive of the future.
  return t >= windowStart(now, days).getTime() && t <= now.getTime();
}

function newest<T>(rows: readonly T[], at: (row: T) => string | null): T | null {
  let best: T | null = null;
  let bestT = -Infinity;
  for (const row of rows) {
    const v = at(row);
    if (!v) continue;
    const t = Date.parse(v);
    if (Number.isNaN(t) || t <= bestT) continue;
    best = row;
    bestT = t;
  }
  return best;
}

/**
 * Admiralty rank, lower is better: A1 beats B2 beats C3.
 *
 * Source reliability dominates credibility, matching the spec's ordering -- an A source
 * outranks a B source regardless of the numeral. An unparseable numeral sorts last
 * rather than throwing, because a grading defect must not blank the homepage.
 */
export function gradeRank(source: string | null, info: string | null): number {
  const letter = (source ?? "Z").trim().toUpperCase().charCodeAt(0) || 90;
  const numeral = Number.parseInt((info ?? "").trim(), 10);
  return letter * 10 + (Number.isFinite(numeral) ? numeral : 9);
}

// --- collection time -----------------------------------------------------------------

/**
 * When the record last moved: the maximum `last_fetch` across every channel, or null
 * when nothing has ever been collected.
 *
 * THE HEADER USED TO RENDER `new Date()`, which made "collected <time>" a statement
 * about when the page was loaded. It agreed with the record only by coincidence, and
 * it agreed most convincingly when the cron had stopped -- the one case where a
 * reader needs it to disagree. This reads the rows instead.
 *
 * Nulls are skipped rather than treated as zero. A channel with no rows has no
 * collection time, and a channel that has never collected must not drag the maximum
 * down or stand in for one that has.
 *
 * Null out means NOTHING has been collected on any channel. The caller must render
 * that as its own statement -- "no collection recorded" -- and must not fall back to
 * the clock, which would restore the defect precisely where the record is most
 * suspect. See app/page.tsx.
 */
export function readCollectedAt(rows: readonly ActivityRow[]): string | null {
  return newest(rows, (r) => r.last_fetch)?.last_fetch ?? null;
}

// --- news --------------------------------------------------------------------------

export type NewsRead = {
  /** Items whose `occurred_at` falls in the window. */
  datedInWindow: number;
  /** Everything the news channel collected in the last 24 h, passed in by the page. */
  collectedLast24h: number;
  /** Best-graded item in the window, ties broken by newest. Null when the window is empty. */
  lead: NewsItem | null;
  /** Newest item at any date, so the empty case can still name a date. */
  mostRecent: NewsItem | null;
  windowDays: number;
};

/**
 * `collectedLast24h` is the news row's `day` from `getChannelActivity`, passed in rather
 * than queried. It is deliberately a different instrument from `datedInWindow`: one
 * counts what arrived, the other what happened. They diverge whenever the aggregator
 * delivers a backdated story, which is exactly the case the board is built to show.
 */
export function readNews(
  items: readonly NewsItem[],
  collectedLast24h: number,
  now: Date,
): NewsRead {
  const windowed = items.filter((i) => inWindow(i.occurred_at, now));
  const lead = [...windowed].sort((a, b) => {
    const byGrade =
      gradeRank(a.admiralty_source, a.admiralty_info) -
      gradeRank(b.admiralty_source, b.admiralty_info);
    if (byGrade !== 0) return byGrade;
    return Date.parse(b.occurred_at ?? "") - Date.parse(a.occurred_at ?? "");
  })[0] ?? null;

  return {
    datedInWindow: windowed.length,
    collectedLast24h,
    lead,
    mostRecent: newest(items, (i) => i.occurred_at),
    windowDays: READ_WINDOW_DAYS,
  };
}

// --- litigation --------------------------------------------------------------------

export type LitigationRead = {
  /** Most recent `filed_at` across the campaign rows. */
  latestFiling: string | null;
  /** The cases sharing that filing date -- five states filed together on 2026-02-26. */
  filedOnLatest: CampaignRow[];
  /** Whether any docket has taken an entry since that filing. */
  movedSinceFiling: boolean;
  totalCases: number;
};

/**
 * Takes no `now`. The reading is relative to the record -- latest filing, what shares
 * it, whether anything moved after it -- and none of that consults the clock. The other
 * five take a `now` because they window against it; a sixth parameter here purely for
 * signature symmetry would misdescribe what the function reads. Add it when something
 * needs it.
 */
export function readLitigation(rows: readonly CampaignRow[]): LitigationRead {
  const latest = newest(rows, (r) => r.filed_at);
  const latestFiling = latest?.filed_at ?? null;
  const filedAtT = latestFiling ? Date.parse(latestFiling) : NaN;

  return {
    latestFiling,
    filedOnLatest: latestFiling
      ? rows.filter((r) => r.filed_at === latestFiling)
      : [],
    movedSinceFiling: Number.isNaN(filedAtT)
      ? false
      : rows.some((r) => {
          const t = r.latest_entry_at ? Date.parse(r.latest_entry_at) : NaN;
          return !Number.isNaN(t) && t > filedAtT;
        }),
    totalCases: rows.length,
  };
}

// --- DOJ campaign ------------------------------------------------------------------

/**
 * DELEGATES. This is `summarize(buildCells(rows, now))` and nothing else -- no local
 * recount, no second pass, no "while we're here" extra field.
 *
 * The homepage and /campaign must not be able to disagree about the same number at the
 * same moment, and the only way to guarantee that is for one of them to have no
 * arithmetic of its own. A test asserts this equals `summarize(buildCells(...))` on
 * identical input, so a future edit that "optimises" a count into this function fails
 * rather than forking the two pages quietly.
 */
export function readCampaign(rows: readonly CampaignRow[], now: Date): CampaignSummary {
  return summarize(buildCells([...rows], now));
}

// --- watched bills -----------------------------------------------------------------

export type BillsRead = {
  total: number;
  /** Bills whose latest action falls in the window. */
  movedInWindow: Bill[];
  /** Most recently actioned bill, in or out of the window. */
  latest: Bill | null;
  latestActionAt: string | null;
  latestAction: string | null;
};

export function readBills(bills: readonly Bill[], now: Date): BillsRead {
  const latest = newest(bills, (b) => b.latest_action_at);
  return {
    total: bills.length,
    movedInWindow: bills.filter((b) => inWindow(b.latest_action_at, now)),
    latest,
    // Populated even when nothing moved, so the empty sentence can read "None of the 6
    // watched bills has moved since Mar 26, 2026" rather than "no movement".
    latestActionAt: latest?.latest_action_at ?? null,
    latestAction: latest?.latest_action ?? null,
  };
}

// --- executive ---------------------------------------------------------------------

export type ExecutiveRead = {
  /** Documents scoring above zero on the title-only lens. */
  relevant: number;
  /** Everything collected on the channel -- the "12 of 118" denominator. */
  total: number;
  /** Most recent relevant document. */
  latest: ExecItem | null;
  latestInWindow: boolean;
};

export function readExecutive(items: readonly ExecItem[], now: Date): ExecutiveRead {
  // Title-only, per the settled decision: scoring title+summary floods the lens with
  // EAC abstracts. relevanceScore is imported rather than reimplemented.
  const relevant = items.filter((i) => relevanceScore(i.title) > 0);
  const latest = newest(relevant, (i) => i.occurred_at);
  return {
    relevant: relevant.length,
    total: items.length,
    latest,
    latestInWindow: inWindow(latest?.occurred_at ?? null, now),
  };
}

// --- state bills ---------------------------------------------------------------------

export type StateBillsRead = {
  bills: number;
  states: number;
  /** Bills whose last action falls in the window. */
  actedInWindow: StateBill[];
  latest: StateBill | null;
  latestActionAt: string | null;
};

/**
 * The line is bills, states, and whether anything is dated in the window:
 * "484 bills across 9 states, none dated in the last 7 days".
 *
 * NO "TOTAL ACTIONS", and this is settled rather than deferred. Section 4.2 asked for
 * one and quoted 3,882, but that figure was read off `data/state_bills.json`'s
 * timelines -- a count of `items` carrying a `state_bill_id` -- and written as though it
 * came from the bills table. It is a number from the wrong artifact wearing the right
 * label. `getStateBills` returns bills, not their items, so the count is not derivable
 * here, and the fix is to drop the claim rather than to add a fetch that recovers it:
 * the sentence is complete without it.
 */
export function readStateBills(bills: readonly StateBill[], now: Date): StateBillsRead {
  const latest = newest(bills, (b) => b.last_action_at);
  return {
    bills: bills.length,
    states: new Set(bills.map((b) => b.state)).size,
    actedInWindow: bills.filter((b) => inWindow(b.last_action_at, now)),
    latest,
    latestActionAt: latest?.last_action_at ?? null,
  };
}
