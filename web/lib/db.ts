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
     ORDER BY COALESCE(latest_action_at, introduced_at) DESC`,
  );
  return rs.rows as unknown as Bill[];
}

// Cases. `cases` already stores the latest entry; most-recently-moved first.
export async function getCases(): Promise<Case[]> {
  const rs = await db.execute(
    `SELECT case_id, caption, court, docket_number, status, category,
            filed_at, latest_entry_at, source_url
     FROM cases
     ORDER BY COALESCE(latest_entry_at, filed_at) DESC`,
  );
  return rs.rows as unknown as Case[];
}

// Latest executive-channel documents as a flat, date-ordered list. Intentionally
// unfiltered: the channel is broad (~16 EOs, ~2 on-topic); relevance ranking is a
// later concern. The skeleton just proves the read.
export async function getExecutiveLatest(limit = 20): Promise<ExecItem[]> {
  const rs = await db.execute({
    sql: `SELECT id, title, source_url, occurred_at, admiralty_source, admiralty_info
          FROM items WHERE channel = 'executive'
          ORDER BY occurred_at DESC LIMIT ?`,
    args: [limit],
  });
  return rs.rows as unknown as ExecItem[];
}
