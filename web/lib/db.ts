// Turso read client and typed query helpers. Server-only: these run in server
// components, never in the browser (the auth token must not ship to the client).
// Read-only by design -- collection is the Python cron's job; this app only reads.
import { createClient } from "@libsql/client";
import { unstable_cache } from "next/cache";
import { windowStarts, toCells } from "@/lib/activity";
import type { ActivityRow } from "@/lib/activity";
import { FEED_WINDOW, HISTORY_AFTER_DAYS } from "@/lib/feed";
import { BAND_DAYS } from "@/lib/timeline";
import type { FeedAnchor, FeedEntry } from "@/lib/feed";

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

// HOW MUCH OF THE 24h DELTA WAS ALREADY OLD WHEN IT WAS COLLECTED. Same threshold
// constant the feed's card classifier uses, imported rather than written twice, so
// the strip and the feed cannot disagree about what "history" means. The strip
// counts ENTRIES and the feed labels CARDS, and every entry of a history card is
// counted here, so the two reconcile: this number is >= the sum over history cards,
// and equal when no card is mixed.
//
// THAT RECONCILIATION HOLDS AT A SHARED INSTANT, AND THE TWO DO NOT SHARE ONE.
// getChannelActivity and getFeed are cached separately and each computes `now`
// INSIDE its own cached call -- deliberately, since an argument would put a moving
// value in the cache key and the entry would never be hit. So the two 24h windows
// can sit up to the 1h TTL apart, and an item near the boundary can be inside one
// window and outside the other. Expect the strip's count and the feed's tagged
// cards to agree to within that drift, not exactly. Same TTL on both is what keeps
// the drift bounded; it is not what makes them simultaneous.
//
// The date arithmetic is date-only via substr(...,1,10), which is what makes it
// format-blind: occurred_at is naive on litigation rows and +00:00-suffixed on news
// while fetched_at is always suffixed, and comparing the YYYY-MM-DD prefixes needs
// neither normalized. A NULL occurred_at yields NULL and is not counted, the same
// rule lib/feed.ts:isHistoryEntry takes.
//
// STILL FREE. Folded into the same GROUP BY as the other three, so it costs what
// they cost: EXPLAIN QUERY PLAN reads `SCAN items USING INDEX idx_items_channel`
// with this column present, verified against production 2026-08-16 before it was
// written. If that ever stops being true, this is the column to drop.
const HISTORY_SUM = `SUM(CASE WHEN fetched_at >= ?
             AND julianday(substr(fetched_at,1,10)) - julianday(substr(occurred_at,1,10)) > ?
            THEN 1 ELSE 0 END)`;

export const getChannelActivity = unstable_cache(
  async (): Promise<ActivityRow[]> => {
    const { day, week } = windowStarts(new Date());
    const rs = await db.execute({
      sql: `SELECT channel,
                   COUNT(*) AS total,
                   SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS day,
                   SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS week,
                   ${HISTORY_SUM} AS day_history
            FROM items
            GROUP BY channel
            ORDER BY channel`,
      args: [day, week, day, HISTORY_AFTER_DAYS],
    });
    // COUNT/SUM can arrive as bigint; coerce for the view.
    return toCells(
      rs.rows.map((r) => ({
        channel: String(r.channel),
        total: Number(r.total),
        day: Number(r.day),
        week: Number(r.week),
        day_history: Number(r.day_history),
      })),
    );
  },
  // v2 for the same reason getFeed's key is bumped: the cached row shape gained a
  // column, and unstable_cache entries outlive a deploy. A stale v1 entry degrades
  // gently here (day_history undefined, so the line simply does not render) rather
  // than rendering wrong -- but for up to an hour the feed would be showing history
  // cards while the strip above it showed no history at all, which is exactly the
  // disagreement these two are cached at the same TTL to prevent.
  ["channel-activity", "v2"],
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

// --- outlet promotion (handoff 82) -------------------------------------------
// `source_id` is the DELIVERY PIPE, not the publisher, and one aggregator carries
// hundreds of outlets -- so filtering on the pipe's grade graded the same
// journalism B2 or C3 by which feed happened to carry it. 159 Google News items
// come from outlets this config already grades B2, read individually and correct
// 159 of 159 (2026-08-15).
//
// PROMOTION IS READ-TIME. Nothing rewrites items.admiralty_source: the item's
// stored grade records what the pipe said, which the spec's record-both rule
// wants kept, and a policy that may change should not be baked into rows.
//
// KEYS ARE MIRRORED FROM config/sources.yaml, where they are derived from the B2
// feed ids. A Python test pins this array against that file, so the export and
// this view can drift only through a failing test. Prefix-matched, because
// outlets spell themselves inconsistently: `Democracy Docket` (106 items),
// `democracydocket.com` (20), `States United Democracy Center` against a
// `states-united` feed id. Equality drops every variant.
export const B2_OUTLET_KEYS = ["bolts", "democracydocket", "statesunited", "votebeat"];

// The SQL spelling of the same fold: lowercase, then drop the two characters
// outlets actually vary on. Must stay identical to config.outlet_key/news_outlet_sql.
function outletPredicate(column: string): string {
  const norm = `REPLACE(REPLACE(LOWER(${column}), ' ', ''), '.', '')`;
  return B2_OUTLET_KEYS.map((k) => `${norm} LIKE '${k}%'`).join(" OR ");
}

// A B2 pipe, or a B2 outlet on any pipe.
const NEWS_FEED_PREDICATE = `s.admiralty_source = 'B' OR (${outletPredicate("i.outlet")})`;

// The displayed grade: promoted to B2 by the OUTLET, otherwise the item's own.
//
// NOT a flat 'B','2' for every feed member, and the difference is load-bearing.
// `classify()` demotes five Democracy Docket items to C3 when they attach to the
// vehicle bill by inference -- a deliberate per-item override, which the spec
// provides for and which stamping the feed's grade on every row would erase. Those
// five arrive on the outlet's own RSS feed, where `outlet` is NULL (the source_id
// already names the publisher), so this CASE leaves them exactly as they are.
const NEWS_GRADE = (col: string, promoted: string) =>
  `CASE WHEN ${outletPredicate("i.outlet")} THEN '${promoted}' ELSE ${col} END`;

export async function getNewsFeed(): Promise<NewsItem[]> {
  const rs = await db.execute(
    `SELECT i.id, i.source_id, i.title, i.source_url, i.occurred_at,
            ${NEWS_GRADE("i.admiralty_source", "B")} AS admiralty_source,
            ${NEWS_GRADE("i.admiralty_info", "2")} AS admiralty_info,
            i.bill_id
     FROM items i JOIN sources s ON s.id = i.source_id
     WHERE i.channel = 'news' AND (${NEWS_FEED_PREDICATE})
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
// THE DIMENSION JOINS ARE FOR THE CARD HEADER, NOT FOR A GRADE TEST, so the line
// above still holds: they are all LEFT JOINs on the anchor columns, they filter
// nothing, and an entry anchored to nothing comes back with every joined column
// NULL rather than being dropped. What they buy is a group card that can say
// "United States v. State of Oregon, D. Or. 6:25-cv-01666, terminated" once
// instead of repeating the caption on all 55 of its rows.
//
// THE CHAIN IS JOINED TWO DIFFERENT WAYS, ON PURPOSE. Measured against the
// 2026-08-16 window, resolving supersession from the feed's own rows fails on 4 of
// 4 case cards: Oregon, Weber and Fontes each point at a Ninth Circuit successor
// that is NOT in the window, and the fourth card (LWV v. DHS at the D.C. Circuit)
// carries no superseded_by at all -- it is the SUCCESSOR of a D.D.C. row, which is
// the only thing explaining why a pending circuit docket arrived with 10 entries.
//   - successor: a plain LEFT JOIN. `superseded_by` points at a primary key, so it
//     is many-to-one and cannot multiply rows.
//   - predecessor: correlated subqueries, NOT a join. The reverse lookup is
//     one-to-MANY in principle -- nothing in schema.sql makes `superseded_by`
//     unique, and two districts consolidating into one appeal is an ordinary shape
//     -- so a LEFT JOIN would silently duplicate every entry of that docket the day
//     it happened. Unique across all 13 today; the subquery is what keeps that from
//     being load-bearing.
//
// THE PREDECESSOR SUBQUERIES CARRY `ORDER BY p.case_id LIMIT 1`, AND BOTH HALVES
// EARN THEIR PLACE. SQLite silently returns the first row of a multi-row scalar
// subquery rather than erroring, so without LIMIT the choice is the engine's. But
// the sharper hazard is that these are THREE INDEPENDENT subqueries with nothing
// tying them to one row: on a case with two predecessors each resolves its own
// "first row", and a bare LIMIT 1 leaves them free to disagree. The failure would
// not be an arbitrary-but-coherent predecessor, it would be a SPLICED one --
// case_id from one row beside court and docket_number from another -- so the chain
// line would link to one docket while displaying a different docket's court. That
// is a false statement about the record, not an unstable choice among true ones.
// A total order over a unique column resolves all three to the SAME row.
//
// This changes no output today: every case has 0 or 1 predecessors (13 rows carry
// superseded_by, 13 distinct values). It pins the behaviour before the case that
// needs it exists, which is the only time the pinning is free.
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

// The flat row the query returns, before the anchor columns are folded into a
// nested object. Named so the mapping below is a typed transformation rather than
// a cast -- `rs.rows as unknown as FeedEntry[]` cannot build a nested `anchor`.
type FeedRow = {
  id: number;
  channel: string;
  title: string;
  summary: string | null;
  source_url: string;
  source_id: string;
  occurred_at: string | null;
  fetched_at: string;
  admiralty_source: string;
  admiralty_info: string;
  bill_id: string | null;
  case_id: string | null;
  state_bill_id: string | null;
  c_caption: string | null;
  c_court: string | null;
  c_docket: string | null;
  c_status: string | null;
  s_case_id: string | null;
  s_court: string | null;
  s_docket: string | null;
  p_case_id: string | null;
  p_court: string | null;
  p_docket: string | null;
  b_type: string | null;
  b_number: number | null;
  b_short_title: string | null;
  b_title: string | null;
  b_is_vehicle: number | null;
  sb_state: string | null;
  sb_bill_number: string | null;
  sb_title: string | null;
};

// Flat columns -> the discriminated anchor. Checked in the same order entryLink
// and feed.anchorOf use, so an entry can never group on one anchor and render the
// header of another.
function toAnchor(r: FeedRow): FeedAnchor | null {
  if (r.bill_id && r.b_type !== null && r.b_number !== null) {
    return {
      kind: "bill",
      id: r.bill_id,
      bill_type: r.b_type,
      number: r.b_number,
      short_title: r.b_short_title,
      title: r.b_title,
      is_vehicle: r.b_is_vehicle ?? 0,
    };
  }
  if (r.case_id && r.c_caption !== null) {
    return {
      kind: "case",
      id: r.case_id,
      caption: r.c_caption,
      court: r.c_court,
      docket_number: r.c_docket,
      status: r.c_status,
      successor: r.s_case_id
        ? { case_id: r.s_case_id, court: r.s_court, docket_number: r.s_docket }
        : null,
      predecessor: r.p_case_id
        ? { case_id: r.p_case_id, court: r.p_court, docket_number: r.p_docket }
        : null,
    };
  }
  if (r.state_bill_id && r.sb_state !== null && r.sb_bill_number !== null) {
    return {
      kind: "state",
      id: r.state_bill_id,
      state: r.sb_state,
      bill_number: r.sb_bill_number,
      title: r.sb_title,
    };
  }
  // An anchor id with no dimension row behind it: the entry still renders and still
  // groups, it just gets no header. Not expected, and not worth dropping a row over.
  return null;
}

// THE TIMELINE WINDOWS ON occurred_at, NOT fetched_at, and this replaced getFeed.
//
// The homepage column is headed "The last 7 days" and used to be fed a 24h fetched_at
// window arranged by date -- which is a different section: "what was collected today,
// arranged by date". Measured 2026-08-19, the difference is not cosmetic: of 232 items
// dated in the last 7 days, 114 were collected before the 24h window and were therefore
// invisible. 2026-08-14 rendered as one C3 news item while the record actually held a
// Nevada judgment, a Michigan order and a Washington transcript notice on that date,
// all fetched on 08-15 and 08-17.
//
// So the predicate is a UNION, and both halves are load-bearing:
//   substr(occurred_at,1,10) >= bandStart  -- everything DATED in the band range,
//                                             whenever it was collected. The bands.
//   fetched_at >= day                      -- everything COLLECTED in the last 24h,
//                                             whenever it is dated. Without this the
//                                             docket-walk back-history (dated Sep 2025
//                                             onward) drops out and the seed rows
//                                             vanish with it.
//
// substr(...,1,10) rather than a timestamp comparison because occurred_at is naive on
// litigation rows and +00:00-suffixed on news; the date-only form is what makes the two
// comparable, the same rule format.utcDay takes.
//
// The collected-in-24h flag is NOT computed here. It is derived per row from fetched_at
// at render time (lib/timeline.isFresh), which is what keeps the two instruments
// independent: the query decides what is in the window, the flag decides what is new.
export const getTimelineEntries = unstable_cache(
  async (): Promise<FeedEntry[]> => {
    const now = new Date();
    const { day } = windowStarts(now);
    const bandStart = new Date(now.getTime() - (BAND_DAYS - 1) * 86_400_000)
      .toISOString()
      .slice(0, 10);
    const rs = await db.execute({
      // The grade is derived, not raw, for the SAME reason the news feed derives
      // it: an outlet psephos grades B2 must not badge C3 here while badging B2 on
      // /news. Two components on one site disagreeing about one item's reliability
      // is the defect outlet promotion exists to remove, and the homepage is where
      // a reader meets these items first. The rule reads items.outlet, not the
      // source row, so this is still no join on `sources`.
      sql: `SELECT i.id, i.channel, i.title, i.summary, i.source_url, i.source_id,
                   i.occurred_at, i.fetched_at,
                   CASE WHEN ${outletPredicate("i.outlet")} THEN 'B'
                        ELSE i.admiralty_source END AS admiralty_source,
                   CASE WHEN ${outletPredicate("i.outlet")} THEN '2'
                        ELSE i.admiralty_info END AS admiralty_info,
                   i.bill_id, i.case_id, i.state_bill_id,
                   c.caption AS c_caption, c.court AS c_court,
                   c.docket_number AS c_docket, c.status AS c_status,
                   s.case_id AS s_case_id, s.court AS s_court,
                   s.docket_number AS s_docket,
                   (SELECT p.case_id FROM cases p
                     WHERE p.superseded_by = i.case_id
                     ORDER BY p.case_id LIMIT 1) AS p_case_id,
                   (SELECT p.court FROM cases p
                     WHERE p.superseded_by = i.case_id
                     ORDER BY p.case_id LIMIT 1) AS p_court,
                   (SELECT p.docket_number FROM cases p
                     WHERE p.superseded_by = i.case_id
                     ORDER BY p.case_id LIMIT 1) AS p_docket,
                   b.bill_type AS b_type, b.number AS b_number,
                   b.short_title AS b_short_title, b.title AS b_title,
                   b.is_vehicle AS b_is_vehicle,
                   sb.state AS sb_state, sb.bill_number AS sb_bill_number,
                   sb.title AS sb_title
            FROM items i
            LEFT JOIN cases c ON c.case_id = i.case_id
            LEFT JOIN cases s ON s.case_id = c.superseded_by
            LEFT JOIN bills b ON b.bill_id = i.bill_id
            LEFT JOIN state_bills sb ON sb.state_bill_id = i.state_bill_id
            WHERE substr(i.occurred_at, 1, 10) >= ? OR i.fetched_at >= ?
            ORDER BY i.fetched_at DESC, i.id DESC`,
      args: [bandStart, day],
    });
    return (rs.rows as unknown as FeedRow[]).map((r) => ({
      id: r.id,
      channel: r.channel,
      title: r.title,
      summary: r.summary,
      source_url: r.source_url,
      source_id: r.source_id,
      occurred_at: r.occurred_at,
      fetched_at: r.fetched_at,
      admiralty_source: r.admiralty_source,
      admiralty_info: r.admiralty_info,
      bill_id: r.bill_id,
      case_id: r.case_id,
      state_bill_id: r.state_bill_id,
      anchor: toAnchor(r),
    }));
  },
  // A NEW KEY, not a bump of "activity-feed": the window predicate changed, so v2
  // rows are a different set rather than a different shape, and unstable_cache
  // entries outlive a deploy.
  ["timeline-entries", "v1"],
  { revalidate: 3600 },
)

// The complement, so the feed can never be read as "the news channel". Shown
// beside the count on the page for the same reason the export prints it.
export async function getNewsExcludedCount(): Promise<number> {
  // The exact complement of getNewsFeed, so the pair always sums to the channel.
  // NOT `<> 'B'`: the membership rule is two clauses now, and negating one of them
  // would report every promoted item as both included and excluded.
  const rs = await db.execute(
    `SELECT COUNT(*) AS n FROM items i JOIN sources s ON s.id = i.source_id
     WHERE i.channel = 'news' AND NOT (${NEWS_FEED_PREDICATE})`,
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

// --- the records chart's two monthly series -----------------------------------------
// Aggregated in SQL rather than by pulling rows: both are counts over the whole spine,
// and the page needs 28 integers, not 9,000 rows.
export type MonthRow = { month: string; n: number };

export type BoardMonthly = {
  /** State bills by the month they FIRST appear in the record. */
  stateBillsFirstSeen: MonthRow[];
  /** Federal legislative actions per month -- channel='legislation' only. */
  legislationActions: MonthRow[];
  /** Per-state first-seen months, for the map's per-frame running dot totals. */
  stateBillsByState: Record<string, MonthRow[]>;
};

// FIRST SEEN IS MIN(items.occurred_at) PER BILL, NOT state_bills.last_action_at, and
// the two are different series rather than two spellings of one. Bucketed on
// last_action_at the March 2025 peak reads 108, because a bill counts in whatever month
// it most recently moved; bucketed on first appearance it reads 92, which is the number
// handoff 87 quotes and the question the bars actually answer -- how many NEW bills
// entered the record that month. last_action_at also re-dates a bill every time it acts,
// so the same bill can leave one bar and join another between two runs.
export const getBoardMonthly = unstable_cache(
  async (): Promise<BoardMonthly> => {
    const [sb, leg, byState] = await Promise.all([
      db.execute(
        `SELECT substr(first_seen, 1, 7) AS month, COUNT(*) AS n FROM (
           SELECT state_bill_id, MIN(occurred_at) AS first_seen FROM items
           WHERE state_bill_id IS NOT NULL AND occurred_at IS NOT NULL
           GROUP BY state_bill_id)
         GROUP BY month ORDER BY month`,
      ),
      db.execute(
        `SELECT substr(occurred_at, 1, 7) AS month, COUNT(*) AS n FROM items
         WHERE channel = 'legislation' AND occurred_at IS NOT NULL
         GROUP BY month ORDER BY month`,
      ),
      // Same first-seen definition, split by state. The map's dot is a RUNNING TOTAL to
      // the frame, so it needs the month a bill entered the record, not its latest action.
      db.execute(
        `SELECT sb.state AS state, substr(f.first_seen, 1, 7) AS month, COUNT(*) AS n
         FROM (SELECT state_bill_id, MIN(occurred_at) AS first_seen FROM items
               WHERE state_bill_id IS NOT NULL AND occurred_at IS NOT NULL
               GROUP BY state_bill_id) f
         JOIN state_bills sb ON sb.state_bill_id = f.state_bill_id
         GROUP BY state, month ORDER BY state, month`,
      ),
    ]);
    const rows = (rs: typeof sb) =>
      (rs.rows as unknown as { month: string; n: number }[]).map((r) => ({
        month: r.month,
        n: Number(r.n),
      }));
    const perState: Record<string, MonthRow[]> = {};
    for (const r of byState.rows as unknown as { state: string; month: string; n: number }[]) {
      (perState[r.state] ??= []).push({ month: r.month, n: Number(r.n) });
    }
    return {
      stateBillsFirstSeen: rows(sb),
      legislationActions: rows(leg),
      stateBillsByState: perState,
    };
  },
  ["board-monthly", "v2"],
  { revalidate: 3600 },
);
