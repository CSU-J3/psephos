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
  compact = false,
}: {
  c: Case;
  showCategory?: boolean;
  // The dockets this one continues into or from, resolved by the caller from rows
  // it already holds. Rendered OUTSIDE the card's Link -- an anchor cannot nest
  // inside another anchor, and these are links to somewhere else.
  chain?: { successor?: CaseRef | null; predecessor?: CaseRef | null };
  // THE RAIL VARIANT: two lines instead of a card. Recently-moved moved out of the
  // board column into a ~360px rail, where the card's four stacked rows and its
  // padding cost more vertical space than the eight dockets are worth. The FULL
  // variant is still the default and is what /campaign renders -- that page is a
  // reference list read one docket at a time, and compacting it there would be
  // fitting one page's layout to another page's constraint.
  //
  // The chain link folds INTO the second line here rather than hanging beneath the
  // card, so a row is exactly two lines whether or not it continues elsewhere. It
  // stays outside the Link for the same reason as below: no nested anchors.
  compact?: boolean;
}) {
  const successor = chain?.successor;
  const predecessor = chain?.predecessor;

  if (compact) {
    return (
      <li>
        <Link
          href={`/case/${c.case_id}`}
          className="block rounded-lg px-3.5 py-2.5 transition-colors hover:bg-neutral-900"
        >
          <div className="flex min-w-0 items-baseline gap-2.5">
            <span className="min-w-0 flex-1 truncate text-[13px] leading-5 text-neutral-100">
              {c.caption}
            </span>
            {c.status && (
              <span
                className={
                  c.status === "terminated"
                    ? "shrink-0 text-xs text-neutral-500"
                    : "shrink-0 text-xs text-neutral-400"
                }
              >
                {c.status}
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-neutral-500">
            {c.court && <span className="font-mono">{c.court}</span>}
            {c.docket_number && <span className="font-mono">· {c.docket_number}</span>}
            <span className="font-mono">→ {formatDate(c.latest_entry_at)}</span>
          </div>
        </Link>
        {(successor || predecessor) && (
          <div className="-mt-1 flex flex-col gap-0.5 px-3.5 pb-2 text-xs">
            {successor && (
              <Link
                href={`/case/${successor.case_id}`}
                className="truncate text-sky-400/90 hover:underline"
              >
                → continued as {successor.court} {successor.docket_number}
              </Link>
            )}
            {predecessor && (
              <Link
                href={`/case/${predecessor.case_id}`}
                className="truncate text-sky-400/90 hover:underline"
              >
                ← continues {predecessor.court} {predecessor.docket_number}
              </Link>
            )}
          </div>
        )}
      </li>
    );
  }

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
