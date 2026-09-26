import { aheadTitle, datedAhead, dayIso, type RecordClock } from "@/lib/dated";
import type { ReactNode } from "react";
import { formatDate } from "@/lib/format";

// A SOURCE'S DATE, RENDERED. Every date the record holds from a source -- an action, a
// filing, a docket entry, a publication -- is rendered through this, and nothing else
// renders one. It emits a `<time>` carrying the date for machines (`data-record-date`,
// the `YYYY-MM-DD` the day comparison reads), and, when the date is after the record's
// clock, a "dated ahead" marker as the `<time>`'s NEXT SIBLING (ruled 2026-09-26).
//
// SIBLINGS, NOT NESTED, so `className` styles the `<time>` alone -- the ledgers' mono
// date type is not the marker's. Where the date has a fixed-width column, wrap the
// component in DATE_COLUMN below rather than styling the `<time>` to that width.
//
// web/scripts/assert-dated.mjs reads exactly this shape: for every `[data-record-date]`
// it compares the date against the page's `[data-record-clock]` itself, and requires a
// `[data-dated-ahead]` next sibling exactly when the date is after the clock. It never
// parses the rendered text.
//
// NOT FOR OUR OWN CLOCK'S READINGS. A collection time or a status-check receipt is
// psephos's clock, not a source's date; it cannot be "ahead" of the record in the
// sense the marker means, and rendering it here would mark a receipt taken after
// midnight UTC as though the source had dated something in advance.
export function RecordDate({
  value,
  clock,
  className,
  format = formatDate,
}: {
  value: string | null | undefined;
  clock: RecordClock;
  className?: string;
  /** The visible text only; the machine-readable date is always `YYYY-MM-DD`. */
  format?: (value: string | null | undefined) => string | null;
}) {
  const iso = dayIso(value);
  if (!iso) return <span className={className}>{formatDate(value)}</span>;
  return (
    <>
      <time dateTime={iso} data-record-date={iso} className={className}>
        {format(value) ?? formatDate(value)}
      </time>
      {datedAhead(value, clock) && <DatedAhead value={value} clock={clock} />}
    </>
  );
}

// The marker. Words, not a glyph: "dated ahead" says what is true -- the source's date is
// after the record's clock -- and never "upcoming" or "scheduled", because HB6414's own
// text says the reproduction happened on 09/24. The title carries both dates.
function DatedAhead({ value, clock }: { value: string | null | undefined; clock: RecordClock }) {
  return (
    <span
      data-dated-ahead=""
      title={aheadTitle(value, clock)}
      className="ml-1.5 inline-block shrink-0 rounded-sm border border-neutral-700 px-1 align-[1px] text-[0.62rem] leading-[1.35] whitespace-nowrap text-neutral-400"
    >
      dated ahead
    </span>
  );
}

// A FIXED-WIDTH DATE COLUMN -- the ledgers', /news's and campaign movement's 6.2rem
// column; the caller adds the width. The marker stacks UNDER the date instead of beside
// it, so a row dated ahead keeps the column's width and the grade and text after it stay
// aligned with every other row. Beside the date, it pushed HB6414's ledger row about 5rem
// right of the three rows above it (checkpoint, 2026-09-26). The `<time>` and the marker
// stay siblings inside it, which is the shape the assertion reads.
export const DATE_COLUMN =
  "flex shrink-0 flex-col items-start [&>[data-dated-ahead]]:ml-0 [&>[data-dated-ahead]]:mt-0.5";

// ROWS DATED AHEAD, BELOW A DIVIDER, after a list whose heading counts the rows above
// it -- "Latest movement: ten most recent actions" on /state-bills, "eight most recent
// docket entries" on /campaign. The heading stays true of its ten; the row dated ahead
// is shown, marked by its own RecordDate, and never cut (ruled 2026-09-26). Its
// children are the list's own <li> rows, so a row reads the same above and below.
export function AheadRows({ children }: { children: ReactNode }) {
  return (
    <ul data-dated-ahead-rows="" className="mt-3 border-t border-dashed border-neutral-700 pt-1">
      {children}
    </ul>
  );
}

// A COUNTED LIST AND ITS ROWS DATED AHEAD, rendered from the one object
// lib/dated.ts#recentAndAhead returns: the counted rows, then AheadRows. The page hands
// over the whole object, so it cannot render the ten and drop the row dated ahead
// without writing that it did -- an adversarial review, 2026-09-26, found nothing
// else would catch a page that stopped rendering its `ahead` half. `row` renders one
// row, with its key, the same above the divider and below it.
export function CountedList<T>({
  rows,
  row,
}: {
  rows: { recent: readonly T[]; ahead: readonly T[] };
  row: (r: T) => ReactNode;
}) {
  return (
    <>
      <ul>{rows.recent.map(row)}</ul>
      {rows.ahead.length > 0 && <AheadRows>{rows.ahead.map(row)}</AheadRows>}
    </>
  );
}

// The page's clock, for machines only: the anchor every RecordDate on the page was
// compared against. Rendered once per page, hidden, so the assertion reads the same
// value the components did rather than a second read that could straddle a collection.
export function RecordClockMark({ iso }: { iso: string | null | undefined }) {
  return <span hidden data-record-clock={iso ?? ""} />;
}
