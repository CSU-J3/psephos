import Link from "next/link";
import { Grade } from "@/components/Grade";
import { buildFeed, entryLink, type FeedEntry } from "@/lib/feed";
import { formatDate } from "@/lib/format";

// Move 2: one reverse-chronological list across all five channels, each entry
// carrying its channel and its Admiralty grade. This is the redesign's answer to
// "what changed", where the strip above answers "how much".
//
// EVERY GRADE APPEARS HERE, including C3. That is what makes the badge worth
// rendering -- a feed filtered to one grade stamps an identical badge on every
// row, which is decoration rather than information. It also keeps this list
// consistent with the strip directly above it, which counts all grades: a
// B2-only feed would show 4 news entries under a strip reading 26.
//
// The channel tag is deliberately plain text rather than a second coloured
// badge. The grade already carries the only colour in the row, and two competing
// accents per line is the clutter the redesign block was written against.
const CHANNEL_LABEL: Record<string, string> = {
  legislation: "legislation",
  executive: "executive",
  litigation: "litigation",
  news: "news",
  state: "state",
};

export function ActivityFeed({ rows }: { rows: FeedEntry[] }) {
  const { entries, total, truncated } = buildFeed(rows);

  if (entries.length === 0) {
    // A quiet window is a reading, not an error. Three of five channels collected
    // nothing in 24h when this was built, so an empty feed is reachable and must
    // say which window it is empty for.
    return (
      <p className="text-sm text-neutral-500">
        Nothing collected in the last 24 hours.
      </p>
    );
  }

  return (
    <>
      <ul className="space-y-2">
        {entries.map((e) => {
          const link = entryLink(e);
          return (
            <li
              key={e.id}
              className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 transition-colors hover:border-neutral-700"
            >
              <a
                href={e.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium text-neutral-100 hover:underline"
              >
                {e.title}
              </a>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
                <span className="uppercase tracking-wide text-neutral-400">
                  {CHANNEL_LABEL[e.channel] ?? e.channel}
                </span>
                {/* The entry's OWN occurred_at, not the fetched_at the list is
                    ordered by. A backdated RSS item sorts to the top as newly
                    collected and still reads as the older story it is. */}
                <span className="tabular-nums">{formatDate(e.occurred_at)}</span>
                <span>{e.source_id}</span>
                <Grade grade={`${e.admiralty_source}${e.admiralty_info}`} />
                {link && (
                  <Link href={link.href} className="text-neutral-400 hover:underline">
                    {link.label} →
                  </Link>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {/* Never a silent top-N. A capped list that does not say so reads as the
          whole window, which is the failure the standing rule names. */}
      {truncated && (
        <p className="mt-3 text-xs text-neutral-500">
          Showing {entries.length} of {total} items collected in the last 24 hours.{" "}
          <Link href="/news" className="text-neutral-400 hover:underline">
            The full B2 news archive is at /news →
          </Link>
        </p>
      )}
    </>
  );
}
