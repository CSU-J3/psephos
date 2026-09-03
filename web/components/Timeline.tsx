import type { TimelineItem } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { entryText, gradeOf, pagePrefix, sliceLedger } from "@/lib/ledger";
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
// carries and where the fold falls; this file only draws it.
//
// NO CLIENT JS. Expansion is a native <details>, so the page stays a server component
// and every row is open to find-in-page and to a reader with scripting off.
export function Timeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-neutral-500">No timeline items yet.</p>;
  }

  // BOTH OF THESE READ `items`, NEVER THE SLICE, and that is the load-bearing line in
  // this file. They are page-level facts, so computing them over the visible rows alone
  // would make a row render differently above and below the fold. It is not
  // hypothetical: the 10 newest rows on /bill/s1383-119 are ALL news today, so a
  // per-slice `mixed` sees one channel and drops every label, and a per-slice cohort
  // holds no A1 row so `s1383-119: ` stops being stripped -- both silently returning
  // when the reader expands.
  const prefix = pagePrefix(items);
  // The channel label earns its column only where a page actually mixes channels --
  // in production that is /bill/s1383-119 and nothing else. On a docket or a state
  // bill every row would repeat one word, which is noise dressed as metadata.
  const mixed = new Set(items.map((it) => it.channel)).size > 1;

  const { head, rest } = sliceLedger(items);
  const row = (it: TimelineItem) => {
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
  };

  return (
    <>
      <ol className="border-t border-neutral-900">{head.map(row)}</ol>
      {rest.length > 0 && (
        // NO `group` CLASS ON THIS <details>, deliberately. Tailwind compiles
        // `group-open:` to `:is(:where(.group):open *)` -- a DESCENDANT selector -- so a
        // wrapper carrying `group` would match the line span of every row nested inside
        // it, and opening this one control would un-clip all 131 folded lines at once.
        // The rows keep their own `group`; this element is styled directly.
        <details>
          <summary className="flex cursor-pointer list-none items-baseline gap-2 border-b border-neutral-900 py-2 pl-2.5 text-[0.72rem] text-neutral-500 hover:bg-neutral-900/60 hover:text-neutral-300 [&::-webkit-details-marker]:hidden">
            <span aria-hidden="true" className="font-mono">
              ▸
            </span>
            Earlier {rest.length} {rest.length === 1 ? "entry" : "entries"}
          </summary>
          <ol>{rest.map(row)}</ol>
        </details>
      )}
    </>
  );
}
