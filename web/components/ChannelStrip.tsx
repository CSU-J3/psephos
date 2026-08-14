import type { ActivityRow } from "@/lib/activity";
import { WINDOW_DAYS } from "@/lib/activity";

// The channels of federal pressure as an activity strip across the top: what psephos
// COLLECTED recently, with the lifetime total as context. Five channels -- legislation,
// executive, litigation, news, state -- hence grid-cols-5 on desktop. The comment here
// used to say "four" against a query returning five, which wrapped the fifth cell onto
// its own row; that is fixed rather than merely noted now.
//
// DELTA IS THE HEADLINE, TOTAL IS CONTEXT, and that resolves a conflict the redesign
// block carried both sides of. Raw totals alone say nothing on a monitoring tool. But
// deleting them was the other proposal, and measured against production on 2026-08-14
// it fails: three of five channels collected nothing in 24h and the same three nothing
// in 7d, so a deltas-only strip reads "+0 +0 +2 +29 +0" and looks broken rather than
// quiet. The total is the only scale cue a first-time reader gets. Two equal readouts
// would be the clutter the block was written against, so the total is small and muted.
//
// NO COLOUR ON THE DELTAS. Green-for-up reads as "growth is good" on a tool tracking
// the erosion of voting rights; these numbers are activity, not valence. Neutral
// throughout, and the only accent in the strip is the muted total.
export function ChannelStrip({ rows }: { rows: ActivityRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-neutral-500">No items yet.</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {rows.map((r) => (
        <div
          key={r.channel}
          className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3"
        >
          <div className="text-xs uppercase tracking-wide text-neutral-500">
            {r.channel}
          </div>
          {/* Zero renders as 0, never blank. A channel that collected nothing is a
              reading, and on this data it is the common case. */}
          <div className="mt-1 text-2xl font-semibold tabular-nums text-neutral-100">
            +{r.day}
            <span className="ml-1 text-xs font-normal text-neutral-500">
              /{WINDOW_DAYS.day * 24}h
            </span>
          </div>
          <div className="mt-0.5 text-sm tabular-nums text-neutral-400">
            +{r.week}
            <span className="ml-1 text-xs text-neutral-600">
              /{WINDOW_DAYS.week}d
            </span>
          </div>
          <div className="mt-1.5 text-xs tabular-nums text-neutral-600">
            {r.total.toLocaleString()} total
          </div>
        </div>
      ))}
    </div>
  );
}
