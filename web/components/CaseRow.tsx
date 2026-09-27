import Link from "next/link";
import type { Case, CaseRef } from "@/lib/db";
import { RecordDate } from "@/components/RecordDate";
import type { RecordClock } from "@/lib/dated";
import { isEoChallenge } from "@/lib/stands";

// One litigation docket. `status` tracks where it stands and is always shown.
//
// `category` IS RENDERED ONLY WHEN IT DISTINGUISHES SOMETHING. The schema separates
// the kinds of suit (voter-data vs EO-challenge vs registration-law) and this
// comment used to describe that intent as though the table showed it. It does not:
// all 46 rows read `voter-data` (measured against Turso 2026-08-16), so the badge
// was stamping one identical word on every card -- decoration, by the same argument
// the feed uses for a single-grade badge. The caller passes `showCategory` from a
// DATA RULE (more than one distinct category in the fetched rows), not a constant.
// But only the FULL card reads it, and no page renders the full card as of
// 2026-09-26: the rail's compact row ignores `showCategory`. So the day a second kind
// of suit lands, this badge does NOT come back by itself; the rail marks the EO class
// with its own mark instead (below).
export function CaseRow({
  c,
  clock,
  showCategory = false,
  chain,
  compact = false,
}: {
  c: Case;
  clock: RecordClock;
  showCategory?: boolean;
  // The dockets this one continues into or from, resolved by the caller from rows
  // it already holds. Rendered OUTSIDE the card's Link -- an anchor cannot nest
  // inside another anchor, and these are links to somewhere else.
  chain?: { successor?: CaseRef | null; predecessor?: CaseRef | null };
  // THE RAIL VARIANT: two lines instead of a card. Recently-moved moved out of the
  // board column into a rail about 400-460px wide (1280 to 1440; its 360px track
  // floor never binds), where the card's four stacked rows and its
  // padding cost more vertical space than the eight dockets are worth. The FULL
  // variant is still the default, and no page renders it as of 2026-09-26: the rail
  // is this component's only caller. (This line said /campaign rendered it; that
  // page opens on its grid.)
  //
  // The chain links hang BENEATH the two-line body, one truncated line per direction,
  // outside the Link for the same reason as below: no nested anchors. The body --
  // caption and status, then court, docket and date -- is two lines at desktop widths,
  // and a row that continues elsewhere adds one chain line per direction. (This line
  // said the chain folded into the second line; it never did.)
  //
  // THE RAIL MARKS THE EO CLASS, AND ONLY THAT CLASS. The rail lists every docket in
  // `cases`, newest movement first, and most of them are DOJ's voter-roll suits; a
  // challenge to an election executive order interleaved among them without a mark
  // reads as one more of DOJ's. The marker reads `category` through the one predicate
  // the section's count uses (lib/stands.ts#isEoChallenge). The predicate is shared;
  // the read is not: the rail's rows come from `getCases` and the sentence's from
  // `getDocketRows`, two SELECTs, so a render test pins the mark
  // (components/CaseRow.test.ts). It is not the full card's category
  // badge: that one is a general label behind `showCategory`, and this is a class
  // mark that shows whenever the class does. Neutral outline on purpose -- amber is
  // the vehicle and dated-ahead marks, sky and emerald are grades.
  //
  // BESIDE THE STATUS FROM 640px, ON ITS OWN LINE BELOW IT (Corey, 2026-09-26). The
  // second line was tried first, and at 1440 the mark pushed the date onto a third
  // line in the ~460px rail, breaking the two-line body above. On the first line at
  // every width, it cut a 390px caption to about sixteen characters. So one element
  // moves: below `sm` the first line wraps and the mark's wrapper takes a full line
  // after the caption and status; from `sm` up the line does not wrap and the mark
  // sits before the status. The caption is `flex-1`, a zero basis, so it never forces
  // the wrap itself. The wrapper is `flex` so its height is the 17px badge rather
  // than an inherited 24px line box, and `sm:self-center` centres it on the line: as
  // a plain span it deepened a desktop row's first line from 19px to 24px. The
  // ruling's fallback, if this fought the layout checks, was the second line at both
  // widths: a readable caption beats a uniform row.
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
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1 sm:flex-nowrap">
            <span className="min-w-0 flex-1 truncate text-[14px] leading-[19px] text-neutral-100">
              {c.caption}
            </span>
            {isEoChallenge(c) && (
              <span className="order-last flex basis-full sm:order-none sm:basis-auto sm:shrink-0 sm:self-center">
                <span
                  data-class-mark="eo-challenge"
                  className="inline-block rounded border border-neutral-600 px-1 text-[10px] font-semibold uppercase leading-[15px] tracking-wide text-neutral-300"
                >
                  EO challenge
                </span>
              </span>
            )}
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
            <span className="font-mono">
              → <RecordDate value={c.latest_entry_at} clock={clock} />
            </span>
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
          Filed <RecordDate value={c.filed_at} clock={clock} /> · Updated{" "}
          <RecordDate value={c.latest_entry_at} clock={clock} />
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
