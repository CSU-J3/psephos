// Date display: MMM D, YYYY (e.g. "Mar 25, 2025"). No date libraries.
//
// occurred_at values are naive ISO strings (a date "2025-03-25" or a naive
// timestamp "2025-03-25T00:00:00"). Parsing those through `new Date()` would
// apply the runtime's local zone and can shift the calendar day. Instead we read
// the YYYY-MM-DD parts directly and format in UTC, so the day is stable and
// matches the date-only comparisons the collectors and snapshots use.
const fmt = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—"; // em dash for missing dates
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return "—";
  const [, y, mo, d] = m;
  return fmt.format(new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d))));
}
