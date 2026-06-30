import type { TimelineItem } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { Grade } from "./Grade";

// Left-border tint by channel so action vs reporting reads at a glance; the Grade
// badge carries the reliability colour, the border just separates the kinds.
const CHANNEL_ACCENT: Record<string, string> = {
  legislation: "border-l-sky-500/60",
  news: "border-l-neutral-500/60",
  litigation: "border-l-violet-500/60",
};

// The interleave, rendered: one bill's or case's items in date order. Each entry
// links to its source and carries its Admiralty grade, so the action and the
// reporting that explains it sit together, each traceable.
export function Timeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-neutral-500">No timeline items yet.</p>;
  }
  return (
    <ol className="space-y-3">
      {items.map((it) => (
        <li
          key={it.id}
          className={`rounded-lg border border-l-2 border-neutral-800 bg-neutral-900 p-4 ${
            CHANNEL_ACCENT[it.channel] ?? "border-l-neutral-700"
          }`}
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="flex items-baseline gap-2 text-xs text-neutral-500">
              <span className="uppercase tracking-wide">{it.channel}</span>
              {formatDate(it.occurred_at)}
            </span>
            <Grade grade={`${it.admiralty_source}${it.admiralty_info}`} />
          </div>
          <a
            href={it.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block font-medium hover:underline"
          >
            {it.title}
          </a>
          {it.summary && <p className="mt-1 text-sm text-neutral-400">{it.summary}</p>}
        </li>
      ))}
    </ol>
  );
}
