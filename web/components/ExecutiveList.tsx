import type { ExecItem } from "@/lib/db";
import { RecordDate } from "@/components/RecordDate";
import { splitByClock, type RecordClock } from "@/lib/dated";
import { Grade } from "./Grade";

// Latest executive-channel documents as a flat, date-ordered list. Deliberately
// dumb: no relevance filtering or ranking (that is a later concern). The channel
// is broad; EO-prefixed titles surface the executive orders among the rules.
//
// A DOCUMENT DATED AHEAD OF THE RECORD'S CLOCK follows every document dated up to it,
// marked (lib/dated.ts, ruled 2026-09-26). The Federal Register dates a Friday's or a
// Saturday's document to the next Monday; three such rows arrived before their dates.
export function ExecutiveList({ items, clock }: { items: ExecItem[]; clock: RecordClock }) {
  if (items.length === 0) {
    return <p className="text-sm text-neutral-500">No executive documents yet.</p>;
  }
  const { upTo, ahead } = splitByClock(items, (it) => it.occurred_at, clock);
  return (
    <ul
      data-recency-list="executive"
      className="divide-y divide-neutral-800 rounded-lg border border-neutral-800 bg-neutral-900"
    >
      {[...upTo, ...ahead].map((it) => (
        <li
          key={it.id}
          className="flex items-baseline justify-between gap-3 px-4 py-3"
        >
          <a
            href={it.source_url}
            target="_blank"
            rel="noreferrer"
            className="min-w-0 text-sm hover:underline"
          >
            {it.title}
          </a>
          <span className="flex shrink-0 items-center gap-2 text-xs text-neutral-500">
            <Grade grade={`${it.admiralty_source}${it.admiralty_info}`} />
            <RecordDate value={it.occurred_at} clock={clock} />
          </span>
        </li>
      ))}
    </ul>
  );
}
