// Turso read client and typed query helpers. Server-only: these run in server
// components, never in the browser (the auth token must not ship to the client).
// Read-only by design -- collection is the Python cron's job; this app only reads.
import { createClient } from "@libsql/client";

export const db = createClient({
  url: process.env.TURSO_DATABASE_URL!,
  authToken: process.env.TURSO_AUTH_TOKEN!,
});

// Row types mirror schema.sql columns exactly. Columns that are nullable in the
// schema are nullable here. @libsql/client returns INTEGER as JS number (these
// are all small -- ids, bill numbers, the 0/1 vehicle flag), so number is safe.

export type ChannelCount = { channel: string; n: number };

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

// Channel counts -- proves the items spine is readable and shows the breadth.
export async function getChannelCounts(): Promise<ChannelCount[]> {
  const rs = await db.execute(
    "SELECT channel, COUNT(*) AS n FROM items GROUP BY channel ORDER BY channel",
  );
  // COUNT(*) can arrive as bigint; coerce to number for the view.
  return rs.rows.map((r) => ({ channel: String(r.channel), n: Number(r.n) }));
}

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
            filed_at, latest_entry_at, source_url, plaintiff, defendant
     FROM cases
     ORDER BY COALESCE(latest_entry_at, filed_at) DESC, case_id`,
  );
  return rs.rows as unknown as Case[];
}

// One case by id (CourtListener numeric id or a hand-seeded slug), or null.
export async function getCase(caseId: string): Promise<Case | null> {
  const rs = await db.execute({
    sql: `SELECT case_id, caption, court, docket_number, status, category,
                 filed_at, latest_entry_at, source_url, plaintiff, defendant
          FROM cases WHERE case_id = ?`,
    args: [caseId],
  });
  return (rs.rows[0] as unknown as Case) ?? null;
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
