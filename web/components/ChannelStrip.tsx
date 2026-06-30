import type { ChannelCount } from "@/lib/db";

// The four channels of federal pressure as a count strip across the top: the
// breadth of the items spine at a glance (legislation / executive / litigation /
// news, whichever are present).
export function ChannelStrip({ counts }: { counts: ChannelCount[] }) {
  if (counts.length === 0) {
    return <p className="text-sm text-neutral-500">No items yet.</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {counts.map((c) => (
        <div
          key={c.channel}
          className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3"
        >
          <div className="text-xs uppercase tracking-wide text-neutral-500">
            {c.channel}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{c.n}</div>
        </div>
      ))}
    </div>
  );
}
