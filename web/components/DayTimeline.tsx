import Link from "next/link";
import { Grade } from "@/components/Grade";
import { anchorLabel, entryLink, type FeedEntry } from "@/lib/feed";
import { formatDate } from "@/lib/format";
import { dayKey, type DayBand, type SeedRow, type Timeline } from "@/lib/timeline";

// Every channel on one axis, ordered by the date things happened, with a date rail
// down the left.
//
// TWO INSTRUMENTS, NEVER ONE. The band an entry sits in answers "when did this
// happen"; the dot answers "did we only just learn it". A filled dot is collected in
// the last 24 hours, a hollow dashed dot is back-history added to the record. That
// pairing is why this replaced the activity feed: the feed could order by arrival or
// by occurrence and had to pick, so a backdated story either posed as today's news or
// vanished into the middle of the list.
//
// THE AXIS IS UTC-DAYED ON PURPOSE, following dayKey's rule; banding on the viewer's
// local day was rejected because two readers in different zones would then disagree
// about which day an item happened on, and the axis would contradict the Z-stamps the
// record itself carries. The cost is that the top band opens at 00:00Z, which is 6 PM
// the previous evening in Denver, so it can sit empty for hours of the reader's own
// day -- the "UTC days" qualifier on the header and the word "yet" in an open day's
// empty copy are the whole accommodation.

/** Roughly how many rows the newest days may spend before the rest fold to one line. */
const ROW_BUDGET = 12;

function FreshDot({ fresh }: { fresh: boolean }) {
  return fresh ? (
    <span
      aria-label="collected in the last 24 hours"
      title="collected in the last 24 hours"
      className="mt-[7px] inline-block h-2 w-2 shrink-0 rounded-full bg-neutral-300"
    />
  ) : (
    <span aria-hidden className="mt-[7px] inline-block h-2 w-2 shrink-0" />
  );
}

function Row({
  fresh,
  children,
}: {
  fresh: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <FreshDot fresh={fresh} />
      <div className="min-w-0 flex-1">{children}</div>
    </li>
  );
}

function EntryLine({ e, fresh }: { e: FeedEntry; fresh: boolean }) {
  const link = entryLink(e);
  return (
    <Row fresh={fresh}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <a
          href={e.source_url}
          className="text-sm text-neutral-200 underline decoration-neutral-800 underline-offset-2 hover:decoration-neutral-500"
        >
          {e.title}
        </a>
        <Grade grade={`${e.admiralty_source}${e.admiralty_info}`} />
        {link && (
          <Link href={link.href} className="text-xs text-neutral-500 hover:text-neutral-300">
            {link.label}
          </Link>
        )}
      </div>
    </Row>
  );
}

function SeedLine({ s }: { s: SeedRow }) {
  const link = entryLink(s.sample);
  const span =
    s.firstOccurredAt && s.lastOccurredAt
      ? `${formatDate(s.firstOccurredAt)} – ${formatDate(s.lastOccurredAt)}`
      : "dates unknown";
  return (
    <li className="flex gap-3">
      {/* Hollow and dashed: added to the record, dated earlier. Its own line, never
          one line per entry -- four dockets, not 174 rows. */}
      <span
        aria-label="added to the record, dated earlier"
        title="added to the record, dated earlier"
        className="mt-[7px] inline-block h-2 w-2 shrink-0 rounded-full border border-dashed border-neutral-500"
      />
      <p className="min-w-0 flex-1 text-sm text-neutral-400">
        Added to the record:{" "}
        {link ? (
          <Link href={link.href} className="text-neutral-300 hover:text-neutral-100">
            {link.label}
          </Link>
        ) : (
          <span className="text-neutral-300">{s.anchorId}</span>
        )}{" "}
        <span className="text-neutral-500">
          · {s.count} past {s.count === 1 ? "entry" : "entries"}, {span}
        </span>
      </p>
    </li>
  );
}

function Band({
  band,
  collapsed,
  isToday,
}: {
  band: DayBand;
  collapsed: boolean;
  isToday: boolean;
}) {
  const rowCount =
    band.cases.length + band.news.shown.length + band.other.length + band.seeds.length;

  return (
    <li className="flex gap-4 border-t border-neutral-900 py-3 first:border-t-0">
      <div className="w-24 shrink-0">
        <div className="text-xs tabular-nums text-neutral-400">{formatDate(band.day)}</div>
        {/* "collected", never "today". The band is grouped on occurred_at and this
            flag is computed from fetched_at, so it fires on any band holding
            something read in the last 24 hours -- which on this page means bands
            dated Aug 19, 18 and 17 all carried the word "today" directly under
            their own dates. The mechanism is right and the copy contradicted the
            date one line above it. Same word as the strip's headline, for the same
            reason: two instruments answering different questions have to say which
            question they answered. */}
        {band.hasFresh && (
          <div className="mt-0.5 text-[10px] text-neutral-600">collected</div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        {band.empty ? (
          // A gap the reader can see is information; a gap they cannot is not.
          // The current UTC day is still open, so its gap is "yet": nothing has
          // landed AND the day is not over. A finished day's gap is settled.
          <p className="text-sm text-neutral-600">
            {isToday ? "Nothing recorded yet" : "Nothing recorded"}
          </p>
        ) : collapsed ? (
          <p className="text-sm text-neutral-500">
            {rowCount} {rowCount === 1 ? "entry" : "entries"}
            {band.cases.length > 0 && <> · {band.cases.length} dockets</>}
            {band.news.shown.length + band.news.foldedCount > 0 && (
              <> · {band.news.shown.length + band.news.foldedCount} reports</>
            )}
            {band.seeds.length > 0 && <> · {band.seeds.length} added to the record</>}
          </p>
        ) : (
          <ul className="space-y-2">
            {band.cases.map((g) => (
              <Row key={g.caseId} fresh={g.fresh}>
                {/* THE CAPTION, WHICH THIS ROW'S OWN TYPE ALWAYS SAID IT RENDERED --
                    CaseGroup is documented as "the caption once, the entry text
                    beneath", and it printed `case ${g.caseId}` instead. The group's
                    entries carry the anchor, so the name was one property away the
                    whole time; this was the copy a reader actually met, since the
                    homepage renders this component -- the similarly-named ActivityFeed
                    was mounted by nothing and has since been deleted.

                    NOT `uppercase` any more. That class suited a bare key and ruins a
                    caption -- "UNITED STATES V. MINNESOTA" loses the "v." a case name
                    is read by. The styling was fitted to the defect. */}
                <Link
                  href={`/case/${g.caseId}`}
                  className="text-xs tracking-wide text-neutral-500 hover:text-neutral-300"
                >
                  {anchorLabel(g.entries[0]?.anchor) ?? `case ${g.caseId}`}
                </Link>
                <ul className="mt-1 space-y-1">
                  {g.entries.map((e) => (
                    <li key={e.id} className="text-sm text-neutral-300">
                      {e.summary ?? e.title}
                    </li>
                  ))}
                </ul>
              </Row>
            ))}

            {band.news.shown.map((e) => (
              <EntryLine key={e.id} e={e} fresh={band.hasFresh} />
            ))}

            {band.news.foldedCount > 0 && (
              <li className="flex gap-3">
                <span aria-hidden className="mt-[7px] inline-block h-2 w-2 shrink-0" />
                <p className="text-sm text-neutral-500">
                  {band.news.foldedCount} more{" "}
                  {band.news.foldedCount === 1 ? "report" : "reports"}
                  {band.news.sources.length > 0 && (
                    <> · {band.news.sources.slice(0, 4).join(", ")}</>
                  )}
                </p>
              </li>
            )}

            {band.other.map((e) => (
              <EntryLine key={e.id} e={e} fresh={band.hasFresh} />
            ))}

            {band.seeds.map((s) => (
              <SeedLine key={s.key} s={s} />
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export function DayTimeline({
  timeline,
  now,
}: {
  timeline: Timeline;
  now: Date;
}) {
  // The page already holds the clock and hands it to buildTimeline; take it from
  // there rather than reading one here, so the bands and this comparison cannot be
  // computed against two different instants.
  const todayKey = dayKey(now.toISOString());
  // Newest days expand until the budget is spent, then the rest fold to one line
  // each. The fold is by position, not by age: a quiet week at the top leaves more
  // budget for the days that follow it.
  let spent = 0;
  const collapsed = timeline.bands.map((b) => {
    if (b.empty) return false;
    const rows =
      b.cases.length + b.news.shown.length + b.other.length + b.seeds.length;
    const over = spent >= ROW_BUDGET;
    if (!over) spent += rows;
    return over;
  });

  return (
    <div>
      <ul>
        {timeline.bands.map((b, i) => (
          <Band
            key={b.day}
            band={b}
            collapsed={collapsed[i]}
            isToday={b.day === todayKey}
          />
        ))}
      </ul>
      {timeline.olderThanWindow.length > 0 && (
        // No silent caps. These were collected inside the window but are dated before
        // the band range, so they have no day to sit on and must still be visible.
        <p className="mt-3 text-xs text-neutral-600">
          {timeline.olderThanWindow.length} further{" "}
          {timeline.olderThanWindow.length === 1 ? "item" : "items"} collected in this
          window are dated before it.
        </p>
      )}
    </div>
  );
}
