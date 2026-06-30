import type { ExecItem } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { Grade } from "./Grade";

// Latest executive-channel documents as a flat, date-ordered list. Deliberately
// dumb: no relevance filtering or ranking (that is a later concern). The channel
// is broad; EO-prefixed titles surface the executive orders among the rules.
export function ExecutiveList({ items }: { items: ExecItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-neutral-500">No executive documents yet.</p>;
  }
  return (
    <ul className="divide-y divide-neutral-800 rounded-lg border border-neutral-800 bg-neutral-900">
      {items.map((it) => (
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
            {formatDate(it.occurred_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}
