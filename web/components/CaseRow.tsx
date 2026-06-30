import type { Case } from "@/lib/db";
import { formatDate } from "@/lib/format";

// One litigation docket. category separates the kinds of suit (voter-data vs
// EO-challenge vs registration-law); status tracks where it stands. Both are
// shown as tags. The caption links to the source docket when present.
export function CaseRow({ c }: { c: Case }) {
  return (
    <li className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-start justify-between gap-3">
        {c.source_url ? (
          <a
            href={c.source_url}
            target="_blank"
            rel="noreferrer"
            className="min-w-0 font-medium hover:underline"
          >
            {c.caption}
          </a>
        ) : (
          <span className="min-w-0 font-medium">{c.caption}</span>
        )}
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {c.category && (
            <span className="rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
              {c.category}
            </span>
          )}
          {c.status && (
            <span className="rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
              {c.status}
            </span>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
        {c.court && <span>{c.court}</span>}
        {c.docket_number && <span className="font-mono">{c.docket_number}</span>}
      </div>
      <div className="mt-1 text-xs text-neutral-500">
        Filed {formatDate(c.filed_at)} · Updated {formatDate(c.latest_entry_at)}
      </div>
    </li>
  );
}
