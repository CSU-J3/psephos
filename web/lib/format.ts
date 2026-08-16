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

// The YYYY-MM-DD prefix as a UTC epoch, or null when there isn't one. Extracted
// so the three places that need date-only arithmetic share ONE parse: this file's
// formatDate, campaign.daysSince, and feed's history classifier. They disagreed
// about nothing before, and the way to keep it that way is to have one of them.
//
// DATE-ONLY AND FORMAT-BLIND ON PURPOSE. `occurred_at` is naive
// (`YYYY-MM-DDTHH:MM:SS`) on litigation rows and `+00:00`-suffixed on news, while
// `fetched_at` is always suffixed. Reading only the first ten characters makes the
// two comparable without normalizing either, which is the same rule the SQL side
// takes with substr(...,1,10).
export function utcDay(value: string | null | undefined): number | null {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return null;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

// Whole days from `earlier` to `later`, or null if either has no parseable date.
//
// ARGUMENT ORDER IS (earlier, later) AND THE SIGN IS LOAD-BEARING. The one caller
// asks how far an item's publication/docket date lags its collection, so it passes
// (occurred_at, fetched_at) and reads a POSITIVE number -- matching
// `julianday(fetched_at) - julianday(occurred_at)` in the SQL that measured this.
// Swapped, every comparison against a positive threshold silently returns false and
// the classifier reports nothing is history, which is exactly what it looks like
// when the feature is broken.
export function daysBetween(
  earlier: string | null | undefined,
  later: string | null | undefined,
): number | null {
  const a = utcDay(earlier);
  const b = utcDay(later);
  if (a === null || b === null) return null;
  return Math.floor((b - a) / 86_400_000);
}

export function formatDate(value: string | null | undefined): string {
  const day = utcDay(value);
  if (day === null) return "—"; // em dash for missing dates
  return fmt.format(new Date(day));
}
