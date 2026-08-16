import Link from "next/link";
import type { Case, CaseRef } from "@/lib/db";
import { formatDate } from "@/lib/format";

// One litigation docket. `status` tracks where it stands and is always shown.
//
// `category` IS RENDERED ONLY WHEN IT DISTINGUISHES SOMETHING. The schema separates
// the kinds of suit (voter-data vs EO-challenge vs registration-law) and this
// comment used to describe that intent as though the table showed it. It does not:
// all 46 rows read `voter-data` (measured against Turso 2026-08-16), so the badge
// was stamping one identical word on every card -- decoration, by the same argument
// the feed uses for a single-grade badge. The caller passes `showCategory` from a
// DATA RULE (more than one distinct category in the fetched rows), not a constant,
// so the badge returns by itself the day a second kind of suit lands.
export function CaseRow({
  c,
  showCategory = false,
  chain,
}: {
  c: Case;
  showCategory?: boolean;
  // The dockets this one continues into or from, resolved by the caller from rows
  // it already holds. Rendered OUTSIDE the card's Link -- an anchor cannot nest
  // inside another anchor, and these are links to somewhere else.
  chain?: { successor?: CaseRef | null; predecessor?: CaseRef | null };
}) {
  const successor = chain?.successor;
  const predecessor = chain?.predecessor;
  return (
    <li>
      <Link
        href={`/case/${c.case_id}`}
        className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-700"
      >
        <div className="flex items-start justify-between gap-3">
          <span className="min-w-0 font-medium">{c.caption}</span>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {showCategory && c.category && (
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
      </Link>
      {(successor || predecessor) && (
        <div className="mt-1 flex flex-col gap-0.5 pl-4 text-xs">
          {successor && (
            <Link
              href={`/case/${successor.case_id}`}
              className="text-sky-400/90 hover:underline"
            >
              → continued as {successor.court} {successor.docket_number}
            </Link>
          )}
          {predecessor && (
            <Link
              href={`/case/${predecessor.case_id}`}
              className="text-sky-400/90 hover:underline"
            >
              ← continues {predecessor.court} {predecessor.docket_number}
            </Link>
          )}
        </div>
      )}
    </li>
  );
}
