// Channel-activity arithmetic for the homepage strip. Pure functions only -- no
// database client, no next/cache -- so the windowing and the zero-filling can be
// tested without standing up either.

// The five channels of pressure, in render order. A CANONICAL list rather than
// whatever the query returned: `GROUP BY channel` omits a channel with no rows at
// all, and a strip that silently drops to four cells would read as a layout quirk
// rather than as the fact it is. Zero is information here -- measured 2026-08-14,
// three of five channels collected nothing in 24h and the same three nothing in 7d,
// so blanks would be the common case and not the exception.
export const CHANNELS = [
  "legislation",
  "executive",
  "litigation",
  "news",
  "state",
] as const;

export type Channel = (typeof CHANNELS)[number];

export type ActivityRow = {
  channel: string;
  total: number;
  day: number;
  week: number;
  // How much of `day` was ALREADY OLD when it was collected -- the docket-walk
  // signature. See getChannelActivity for the arithmetic.
  //
  // RENDERED BY NOTHING SINCE THE WIRE REPLACED THE STRIP. ChannelStrip drew it as a
  // "N history" line on non-zero cells; the v42 wire has no such line, so the figure is
  // computed and unread. That is a deliberate consequence of the mock rather than an
  // oversight, and it costs something real: on 2026-08-16 four dockets were seeded and
  // walked, and the litigation cell read +174/24h with nothing on the page to say all
  // 174 were dated between Sep 2025 and Jul 2026. A seed day and a busy day now look
  // alike. Kept computed because the query is free and the alternative -- deleting it
  // and rediscovering the need -- is worse. Delete it only with the query.
  day_history: number;
  // The most recent `fetched_at` on this channel, or NULL when the channel has no
  // rows at all -- which is why it is nullable rather than zero-filled like the four
  // counts above. A channel that has never been collected has no collection time, and
  // any stand-in date here would be the exact invention the header label exists to
  // remove: it would render as a real reading and there would be nothing on the page
  // to say it was manufactured. See `readCollectedAt`, which skips nulls.
  last_fetch: string | null;
};

export const WINDOW_DAYS = { day: 1, week: 7 } as const;

// `fetched_at` is written by common.now_iso() -- datetime.now(timezone.utc).isoformat()
// -- so every value is UTC and suffixed `+00:00`; verified 0 rows otherwise against
// production. Because the suffix is invariant, ISO-8601 strings compare correctly with
// a plain lexicographic `>=`, which is what the SQL does.
//
// The bound is emitted with the SAME `+00:00` suffix rather than JS's `Z`. They denote
// the same instant, but they do not sort the same: on two timestamps equal to the
// microsecond, 'Z' (0x5A) sorts above '+' (0x2B), so a `Z`-suffixed bound would exclude
// a row fetched at exactly the boundary instant. Vanishingly rare and free to avoid.
export function windowStarts(now: Date): { day: string; week: string } {
  const back = (days: number) =>
    new Date(now.getTime() - days * 86_400_000).toISOString().replace("Z", "+00:00");
  return { day: back(WINDOW_DAYS.day), week: back(WINDOW_DAYS.week) };
}

// Query rows -> one cell per canonical channel, zero-filled and in render order. Any
// channel the query returns that is NOT canonical is appended rather than dropped: a
// sixth channel appearing in `items` is something to see on the page, not to hide
// behind a constant that was written before it existed.
export function toCells(rows: ActivityRow[]): ActivityRow[] {
  const byChannel = new Map(rows.map((r) => [r.channel, r]));
  const canonical: ActivityRow[] = CHANNELS.map(
    (channel) =>
      byChannel.get(channel) ??
      // `last_fetch: null`, NOT a date. See the field's comment: zero is the honest
      // fill for a count and there is no honest fill for a timestamp.
      { channel, total: 0, day: 0, week: 0, day_history: 0, last_fetch: null },
  );
  const extra = rows.filter((r) => !(CHANNELS as readonly string[]).includes(r.channel));
  return [...canonical, ...extra];
}
