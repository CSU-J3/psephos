// Turso read client and typed query helpers. Server-only: these run in server
// components, never in the browser (the auth token must not ship to the client).
// Read-only by design -- collection is the Python cron's job; this app only reads.
import { createClient } from "@libsql/client";
import { unstable_cache } from "next/cache";
import { windowStarts, toCells } from "@/lib/activity";
import type { ActivityRow } from "@/lib/activity";
import { FEED_WINDOW } from "@/lib/feed";
import type { FeedEntry } from "@/lib/feed";

export const db = createClient({
  url: process.env.TURSO_DATABASE_URL!,
  authToken: process.env.TURSO_AUTH_TOKEN!,
});

// Row types mirror schema.sql columns exactly. Columns that are nullable in the
// schema are nullable here. @libsql/client returns INTEGER as JS number (these
// are all small -- ids, bill numbers, the 0/1 vehicle flag), so number is safe.

export type Bill = {
  bill_id: string;
  bill_type: string;
  number: number;
  congress: number;
  short_title: string | null;
  title: string | null;
  sponsor: string | null;
  status: string | null;
  is_vehicle: number; // 0 | 1
  latest_action: string | null;
  latest_action_at: string | null;
  introduced_at: string | null;
};

export type Case = {
  case_id: string;
  caption: string;
  court: string | null;
  docket_number: string | null;
  status: string | null;
  category: string | null;
  filed_at: string | null;
  latest_entry_at: string | null;
  source_url: string | null;
  plaintiff: string | null;
  defendant: string | null;
  superseded_by: string | null; // the appeal or refile that replaced this docket
};

// Court + docket only, no timeline -- for rendering a supersession link either way.
export type CaseRef = {
  case_id: string;
  caption: string;
  court: string | null;
  docket_number: string | null;
};

export type StateBill = {
  state_bill_id: string;
  state: string;
  bill_number: string;
  session: string | null;
  title: string | null;
  description: string | null;
  status: string | null; // LegiScan numeric progress code as text; mapped for display
  url: string | null;
  is_vehicle: number; // 0 | 1
  last_action: string | null;
  last_action_at: string | null;
};

// One row of a per-bill or per-case timeline: an action/docket entry (A1) or the
// reporting that explains it (B2/C3), carrying enough to render and grade it.
export type TimelineItem = {
  id: number;
  channel: string; // legislation | news | litigation
  title: string;
  summary: string | null;
  source_url: string;
  occurred_at: string | null;
  admiralty_source: string;
  admiralty_info: string;
};

export type ExecItem = {
  id: number;
  title: string;
  source_url: string;
  occurred_at: string | null;
  admiralty_source: string;
  admiralty_info: string;
};

// Channel activity: what psephos collected recently, with the lifetime total as
// context. This is the one homepage query that scans the whole `items` table -- an
// index scan reading one row per item (~9.4k) to return 15 integers -- so it is the
// only query cached. unstable_cache pulls the scan out of the per-render path and
// caps it at the revalidate window (<=24/day) instead of once per render. The route
// stays force-dynamic and the other homepage queries stay live (freshness is cheap
// there, the scan is not); unstable_cache is a data-cache primitive, independent of
// the route's render mode.
//
// THE DELTAS ARE FREE. Folded into the existing GROUP BY as SUM(CASE WHEN ...) rather
// than issued as separate windowed queries, so this costs exactly what the plain
// counts cost: EXPLAIN QUERY PLAN reads `SCAN items USING INDEX idx_items_channel`
// with or without them. That is also why no index on `fetched_at` was added -- there
// is no windowed lookup to accelerate, and a new index would tax every insert to
// speed up a scan that already has to visit every row to compute the totals.
//
// `fetched_at`, NOT `occurred_at`, and the difference is the whole meaning of the
// strip. It answers "what did psephos collect in this window", which is a fact about
// the tool. `occurred_at` is the publication or docket date, and RSS routinely carries
// items dated days or weeks back -- the same publication-vs-collection artifact the
// litigation poll already handles by keying its high-water mark on `date_modified`
// rather than `date_filed`. Keyed on `occurred_at`, a backfilled week-old article
// would either vanish from the window or report as today's movement depending on which
// side of the boundary it fell, and neither is "what changed since you last looked".
//
// `now` is computed INSIDE the cached function deliberately: taking it as an argument
// would put a moving value in the cache key and the entry would never be hit. The
// window therefore drifts by up to the 1h TTL, which on a 24h span is a <=4% error on
// the number least sensitive to being current.
export const getChannelActivity = unstable_cache(
  async (): Promise<ActivityRow[]> => {
    const { day, week } = windowStarts(new Date());
    const rs = await db.execute({
      sql: `SELECT channel,
                   COUNT(*) AS total,
                   SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS day,
                   SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS week
            FROM items
            GROUP BY channel
            ORDER BY channel`,
      args: [day, week],
    });
    // COUNT/SUM can arrive as bigint; coerce for the view.
    return toCells(
      rs.rows.map((r) => ({
        channel: String(r.channel),
        total: Number(r.total),
        day: Number(r.day),
        week: Number(r.week),
      })),
    );
  },
  ["channel-activity"],
  { revalidate: 3600 },
);

// Watched bills. `bills` already stores the latest action, so no join is needed;
// most-recently-active first.
export async function getBills(): Promise<Bill[]> {
  const rs = await db.execute(
    `SELECT bill_id, bill_type, number, congress, short_title, title, sponsor,
            status, is_vehicle, latest_action, latest_action_at, introduced_at
     FROM bills
     ORDER BY COALESCE(latest_action_at, introduced_at) DESC, bill_id`,
  );
  return rs.rows as unknown as Bill[];
}

// One watched bill by id, or null if not found (the detail page 404s on null).
export async function getBill(billId: string): Promise<Bill | null> {
  const rs = await db.execute({
    sql: `SELECT bill_id, bill_type, number, congress, short_title, title, sponsor,
                 status, is_vehicle, latest_action, latest_action_at, introduced_at
          FROM bills WHERE bill_id = ?`,
    args: [billId],
  });
  return (rs.rows[0] as unknown as Bill) ?? null;
}

// The interleave: one bill's items in date order. Legislation actions (A1) and
// the news that explains them (C3/B2) land in the same list -- the correlation a
// plain bill tracker can't produce. Ascending so the maneuver reads top to bottom.
export async function getBillTimeline(billId: string): Promise<TimelineItem[]> {
  const rs = await db.execute({
    sql: `SELECT id, channel, title, summary, source_url, occurred_at,
                 admiralty_source, admiralty_info
          FROM items WHERE bill_id = ?
          ORDER BY occurred_at, id`,
    args: [billId],
  });
  return rs.rows as unknown as TimelineItem[];
}

// Cases. `cases` already stores the latest entry; most-recently-moved first.
export async function getCases(): Promise<Case[]> {
  const rs = await db.execute(
    `SELECT case_id, caption, court, docket_number, status, category,
            filed_at, latest_entry_at, source_url, plaintiff, defendant, superseded_by
     FROM cases
     ORDER BY COALESCE(latest_entry_at, filed_at) DESC, case_id`,
  );
  return rs.rows as unknown as Case[];
}

// One case by id (CourtListener numeric id or a hand-seeded slug), or null.
export async function getCase(caseId: string): Promise<Case | null> {
  const rs = await db.execute({
    sql: `SELECT case_id, caption, court, docket_number, status, category,
                 filed_at, latest_entry_at, source_url, plaintiff, defendant, superseded_by
          FROM cases WHERE case_id = ?`,
    args: [caseId],
  });
  return (rs.rows[0] as unknown as Case) ?? null;
}

// The successor: the row this case names via superseded_by. Court + docket only.
export async function getCaseRef(caseId: string): Promise<CaseRef | null> {
  const rs = await db.execute({
    sql: `SELECT case_id, caption, court, docket_number FROM cases WHERE case_id = ?`,
    args: [caseId],
  });
  return (rs.rows[0] as unknown as CaseRef) ?? null;
}

// The predecessor: the row whose superseded_by names this case. Reverse of the column.
export async function getPredecessorRef(caseId: string): Promise<CaseRef | null> {
  const rs = await db.execute({
    sql: `SELECT case_id, caption, court, docket_number FROM cases WHERE superseded_by = ?`,
    args: [caseId],
  });
  return (rs.rows[0] as unknown as CaseRef) ?? null;
}

// One case's items in date order: docket entries (A1) interleaved with the
// tracker framing (B2). No news join on the litigation side.
export async function getCaseTimeline(caseId: string): Promise<TimelineItem[]> {
  const rs = await db.execute({
    sql: `SELECT id, channel, title, summary, source_url, occurred_at,
                 admiralty_source, admiralty_info
          FROM items WHERE case_id = ?
          ORDER BY occurred_at, id`,
    args: [caseId],
  });
  return rs.rows as unknown as TimelineItem[];
}

// All state bills, grouped-render order: by state, then most-recently-acted first.
export async function getStateBills(): Promise<StateBill[]> {
  const rs = await db.execute(
    `SELECT state_bill_id, state, bill_number, session, title, description,
            status, url, is_vehicle, last_action, last_action_at
     FROM state_bills
     ORDER BY state, COALESCE(last_action_at, updated_at) DESC, state_bill_id`,
  );
  return rs.rows as unknown as StateBill[];
}

// One state bill by id (str LegiScan bill_id), or null -> the detail page 404s.
export async function getStateBill(id: string): Promise<StateBill | null> {
  const rs = await db.execute({
    sql: `SELECT state_bill_id, state, bill_number, session, title, description,
                 status, url, is_vehicle, last_action, last_action_at
          FROM state_bills WHERE state_bill_id = ?`,
    args: [id],
  });
  return (rs.rows[0] as unknown as StateBill) ?? null;
}

// One state bill's items in date order (all channel="state" / B2 today; the news
// collector doesn't tag state bills yet, so no interleave -- a clean action list).
export async function getStateBillTimeline(id: string): Promise<TimelineItem[]> {
  const rs = await db.execute({
    sql: `SELECT id, channel, title, summary, source_url, occurred_at,
                 admiralty_source, admiralty_info
          FROM items WHERE state_bill_id = ?
          ORDER BY occurred_at, id`,
    args: [id],
  });
  return rs.rows as unknown as TimelineItem[];
}

// The whole executive channel, date-ordered (newest first). Relevance scoring
// runs over this in the page -- ~112 rows scored in TS per request, trivial. No
// limit: the on-topic EOs sit deep (EO 14248 is ~rank 88), so the relevance lens,
// not a recency window, is what surfaces them.
export async function getExecutiveAll(): Promise<ExecItem[]> {
  const rs = await db.execute(
    `SELECT id, title, source_url, occurred_at, admiralty_source, admiralty_info
     FROM items WHERE channel = 'executive'
     ORDER BY occurred_at DESC, id DESC`,
  );
  return rs.rows as unknown as ExecItem[];
}

// --- the B2 news feed -------------------------------------------------------
// NOT the news channel: 436 of 3,422 items, measured against Turso 2026-08-14.
// The 2,986 excluded are Google News aggregates, which config/sources.yaml
// grades C3 with "corroborate before promoting an item" -- the spec's own rule,
// not a source blocklist. Both counts move every cron, which is why the page
// renders the excluded count from getNewsExcludedCount() rather than a literal.
//
// DIVISION OF LABOUR WITH THE HOMEPAGE FEED, so the two are not read as
// inconsistent. This route is the B2 EVIDENTIARY ARCHIVE: the whole graded-B2
// set, back to the beginning, which is what an item cited in an argument has to
// be findable in. The homepage feed is the ACTIVITY SURFACE: every channel,
// every grade, one 24h window, capped. A C3 item therefore appears on the
// homepage and not here, by design and not by oversight.
//
// The filter joins `sources` so it tests the SOURCE's grade, never the item's.
// collectors/news.py classify() demotes an item to C3 when it attaches to the
// vehicle bill by inference, so a handful of Democracy Docket items are stored
// C3 despite coming from a B2 outlet; filtering on items.admiralty_source would
// silently drop exactly those. Mirrors export.snapshots.build_news -- if one
// changes, change both.
export type NewsItem = {
  id: number;
  source_id: string;
  title: string;
  source_url: string;
  occurred_at: string | null;
  admiralty_source: string;
  admiralty_info: string;
  bill_id: string | null;
};

export async function getNewsFeed(): Promise<NewsItem[]> {
  const rs = await db.execute(
    `SELECT i.id, i.source_id, i.title, i.source_url, i.occurred_at,
            i.admiralty_source, i.admiralty_info, i.bill_id
     FROM items i JOIN sources s ON s.id = i.source_id
     WHERE i.channel = 'news' AND s.admiralty_source = 'B'
     ORDER BY i.occurred_at DESC, i.id DESC`,
  );
  return rs.rows as unknown as NewsItem[];
}

// --- the merged cross-channel activity feed (move 2) -------------------------
// Every channel, every grade, one fetched_at window, most recent first.
//
// NO JOIN ON `sources`, and its absence is the point. getNewsFeed above joins
// because it FILTERS on reliability; this one filters on nothing, so there is no
// grade test to get wrong. The grade it renders is the ITEM's own
// (admiralty_source/admiralty_info), which is the per-item value the spec
// provides for -- "defaults live in config/sources.yaml and may be overridden
// per item". Displaying the item's grade and filtering on the source's are the
// right answers to two different questions.
//
// C3 IS INCLUDED, decided on measurement 2026-08-14. Excluding it would drop
// 2,986 of the news channel's 3,422 items and leave the feed reporting 4 news
// entries in a 24h window where the strip directly above it counts 26 -- two
// components on one page disagreeing by 85% about the same channel. The spec's
// rule is that an uncorroborated aggregate must not DRIVE the timeline, and the
// mitigation the spec itself prescribes is the grade badge, which every entry
// carries. See lib/feed.ts for the ordering contract.
//
// Cached at the SAME 1h TTL as getChannelActivity deliberately: the strip and
// the feed describe the same window on the same page, and different TTLs would
// let them disagree about it. `now` is computed inside the cached function for
// the reason given there -- an argument would put a moving value in the cache key.
export const getFeed = unstable_cache(
  async (): Promise<FeedEntry[]> => {
    const { day, week } = windowStarts(new Date());
    const rs = await db.execute({
      sql: `SELECT id, channel, title, source_url, source_id, occurred_at,
                   fetched_at, admiralty_source, admiralty_info,
                   bill_id, case_id, state_bill_id
            FROM items
            WHERE fetched_at >= ?
            ORDER BY fetched_at DESC, id DESC`,
      args: [FEED_WINDOW === "day" ? day : week],
    });
    return rs.rows as unknown as FeedEntry[];
  },
  ["activity-feed"],
  { revalidate: 3600 },
);

// The complement, so the feed can never be read as "the news channel". Shown
// beside the count on the page for the same reason the export prints it.
export async function getNewsExcludedCount(): Promise<number> {
  const rs = await db.execute(
    `SELECT COUNT(*) AS n FROM items i JOIN sources s ON s.id = i.source_id
     WHERE i.channel = 'news' AND s.admiralty_source <> 'B'`,
  );
  return Number((rs.rows[0] as unknown as { n: number }).n);
}

// --- the DOJ voter-data campaign ---------------------------------------------
// One row per docket in the campaign, keyed by the jurisdiction DOJ sued. The
// filter is `state IS NOT NULL`, which is the campaign's own definition rather
// than a hand-maintained id list: collectors/litigation.py writes `state` from
// the tracker artifact and leaves it NULL for the two config seeds, which sue
// federal agencies (Common Cause v. DOJ, LWV v. DHS) and belong to no state.
// 38 of 40 rows as of 2026-08-14 -- both counts move as the tracker does.
//
// `status_checked_at` comes back because it is the ONLY honest "last checked"
// receipt. `entries_synced_at` is the upstream CourtListener date_modified
// high-water, held on an empty window by design, so a docket polled 4x/day and
// quiet for a month carries a month-old mark -- Hawaii reads 2026-07-15 there
// against a status_checked_at of 2026-08-14. Rendering the former would report
// psephos asleep on a docket it had just read. It is NOT selected here, so the
// wrong column is not in reach of the view at all.
export type CampaignRow = {
  case_id: string;
  state: string;
  caption: string;
  court: string | null;
  docket_number: string | null;
  status: string | null;
  filed_at: string | null;
  latest_entry_at: string | null;
  status_checked_at: string | null;
  superseded_by: string | null;
  source_url: string | null;
};

// The tracker's own status prose, one string per case: the latest B2 subject item
// written by collectors/litigation.py:write_b2_item from the artifact's `notes`.
// These are VERSIONED -- the collector writes a new item whenever the notes change
// and dedups on content_hash, so there are 81 rows over 40 cases -- hence MAX(id)
// rather than a plain join, which would fan out to every historical revision.
//
// This is the only thing on the page that can tell a stayed docket from a dead
// one. Arizona's reads "On 6/22/26, the 9th Circuit stayed DOJ's appeal pending
// resolution of the appeals in DOJ's cases against CA and OR" -- a fact no docket
// date carries. It is B2 and must render as B2: it is the tracker's summary, not
// a court record, and the page grades it separately from the docket facts.
export async function getTrackerNotes(): Promise<Map<string, string>> {
  const rs = await db.execute(
    `SELECT i.case_id, i.summary
     FROM items i
     JOIN (SELECT case_id, MAX(id) AS mid FROM items
           WHERE channel = 'litigation' AND admiralty_source = 'B'
             AND case_id IS NOT NULL
           GROUP BY case_id) m ON m.mid = i.id`,
  );
  const out = new Map<string, string>();
  for (const r of rs.rows as unknown as { case_id: string; summary: string | null }[]) {
    if (r.summary) out.set(r.case_id, r.summary);
  }
  return out;
}

export async function getCampaignRows(): Promise<CampaignRow[]> {
  const rs = await db.execute(
    `SELECT case_id, state, caption, court, docket_number, status, filed_at,
            latest_entry_at, status_checked_at, superseded_by, source_url
     FROM cases
     WHERE state IS NOT NULL
     ORDER BY state, case_id`,
  );
  return rs.rows as unknown as CampaignRow[];
}
