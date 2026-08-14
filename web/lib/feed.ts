// Merged cross-channel activity feed -- move 2 of the dashboard redesign. Pure
// functions only (no database client, no next/cache) so the ordering, the cap and
// the cross-link resolution test without standing either up. Same split as
// lib/activity.ts, for the same reason.

export type FeedEntry = {
  id: number;
  channel: string;
  title: string;
  source_url: string;
  source_id: string;
  occurred_at: string | null;
  fetched_at: string;
  admiralty_source: string;
  admiralty_info: string;
  bill_id: string | null;
  case_id: string | null;
  state_bill_id: string | null;
};

// The homepage shows one window. 24h, not 7d: measured 2026-08-14 the 7d window
// holds 260 entries against 24h's 29, and a 260-entry list below the fold is an
// archive, not an activity feed. /news remains the place to read the whole B2 set.
export const FEED_WINDOW: "day" | "week" = "day";

// A cap, and the count it hides, always rendered together. The standing rule is
// that a workflow bounding its coverage says what it dropped -- a silent top-N
// reads as "this is everything" when it is not.
export const FEED_LIMIT = 50;

// Ordering, stated once. `fetched_at DESC, id DESC`.
//
// THE WINDOW AND THE ORDER SHARE A COLUMN DELIBERATELY. Order on anything else --
// occurred_at being the obvious candidate -- and an item enters the list in the
// middle as it ages into the window, because RSS routinely carries publication
// dates days behind collection. A reader watching the top of the feed would never
// see it arrive. Keying both on fetched_at means new entries always appear at the
// top and leave from the bottom, which is the only behaviour a feed can be read
// as having. Each entry still DISPLAYS its own occurred_at, so a backdated story
// is legible as backdated rather than silently re-dated.
//
// `id DESC` is the tiebreak, and it is load-bearing rather than cosmetic: a
// collector run writes many rows inside the same second, so fetched_at alone
// leaves within-batch order to whatever the engine returns. Same reason
// export.snapshots sorts on the (occurred_at, id) pair rather than on the
// timestamp alone.
export function compareEntries(a: FeedEntry, b: FeedEntry): number {
  if (a.fetched_at !== b.fetched_at) return a.fetched_at < b.fetched_at ? 1 : -1;
  return b.id - a.id;
}

export type Feed = {
  entries: FeedEntry[];
  total: number;
  truncated: boolean;
};

// Sort and cap. The SQL orders by the same pair, so this re-sort is redundant
// against a working database and is kept anyway: it is what lets the ordering
// contract be pinned by a test that needs no Turso, and it costs a comparison
// over at most a few hundred rows. `total` is the count BEFORE the cap.
export function buildFeed(rows: FeedEntry[], limit: number = FEED_LIMIT): Feed {
  const sorted = [...rows].sort(compareEntries);
  return {
    entries: sorted.slice(0, limit),
    total: sorted.length,
    truncated: sorted.length > limit,
  };
}

// The cross-channel link, which is most of why the feed is worth building: an
// entry that belongs to a bill, a case or a state bill says so and goes there.
// Checked in that order and at most one is returned -- items carry at most one
// anchor today (measured 2026-08-13: zero items carry both a bill_id and a
// case_id), and if that ever stops being true the first match is still a link
// to somewhere real rather than a rendering decision made at random.
export function entryLink(e: FeedEntry): { href: string; label: string } | null {
  if (e.bill_id) return { href: `/bill/${e.bill_id}`, label: e.bill_id };
  if (e.case_id) return { href: `/case/${e.case_id}`, label: `case ${e.case_id}` };
  if (e.state_bill_id) {
    return { href: `/state-bill/${e.state_bill_id}`, label: e.state_bill_id };
  }
  return null;
}
