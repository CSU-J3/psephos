import type { TimelineItem } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { entryText, gradeOf, pagePrefix } from "@/lib/ledger";
import { Grade } from "./Grade";

// Left-border tint by channel so action vs reporting reads at a glance; the Grade
// badge carries the reliability colour, the border just separates the kinds.
const CHANNEL_ACCENT: Record<string, string> = {
  legislation: "border-l-sky-500/60",
  news: "border-l-neutral-500/60",
  litigation: "border-l-violet-500/60",
  state: "border-l-teal-500/60",
};

// The interleave, rendered as a LEDGER rather than a stack of cards: one line per
// entry, date-anchored, expanding in place to its full stored text and its source.
//
// The card layout it replaces printed the title and the summary one above the other on
// every row, which on a docket is the same sentence twice -- the collector writes
// `title = "<caption>: " + desc[:180]` and `summary = desc` -- inside a bordered box.
// 43 entries came to 9,489px of page. `lib/ledger.ts` decides which single text a row
// carries; this file only draws it.
//
// NO CLIENT JS. Expansion is a native <details>, so the page stays a server component
// and every row is open to find-in-page and to a reader with scripting off.
export function Timeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-neutral-500">No timeline items yet.</p>;
  }

  const prefix = pagePrefix(items);
  // The channel label earns its column only where a page actually mixes channels --
  // in production that is /bill/s1383-119 and nothing else. On a docket or a state
  // bill every row would repeat one word, which is noise dressed as metadata.
  const mixed = new Set(items.map((it) => it.channel)).size > 1;

  return (
    <ol className="border-t border-neutral-900">
      {items.map((it) => {
        const text = entryText(it, prefix);
        return (
          <li key={it.id} className="border-b border-neutral-900">
            <details className="group">
              <summary
                className={`flex cursor-pointer list-none items-baseline gap-2.5 border-l-2 py-2 pl-2.5 pr-1 hover:bg-neutral-900/60 [&::-webkit-details-marker]:hidden ${
                  CHANNEL_ACCENT[it.channel] ?? "border-l-neutral-700"
                }`}
              >
                <span className="w-[6.2rem] shrink-0 font-mono text-[0.72rem] text-neutral-600">
                  {formatDate(it.occurred_at)}
                </span>
                <Grade grade={gradeOf(it)} dense />
                {mixed && (
                  <span className="w-[4.6rem] shrink-0 text-[0.6rem] uppercase tracking-wide text-neutral-600">
                    {it.channel}
                  </span>
                )}
                <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-sm text-neutral-300 group-open:whitespace-normal group-open:text-neutral-200">
                  {text.line}
                </span>
              </summary>
              <div className="mb-2.5 ml-[8.7rem] mt-0.5 pr-1 text-[0.82rem] leading-relaxed text-neutral-400 max-md:ml-2.5">
                {text.body}
                <a
                  href={it.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1.5 whitespace-nowrap text-[0.72rem] text-neutral-500 hover:text-neutral-200"
                >
                  source ↗
                </a>
              </div>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
