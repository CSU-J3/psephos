import Link from "next/link";
import type { ActivityRow } from "@/lib/activity";
import type { Bill } from "@/lib/db";
import { CHANNELS, WINDOW_DAYS } from "@/lib/activity";
import { billLabel } from "@/lib/bill";
import { formatDate } from "@/lib/format";
import type {
  BillsRead,
  ExecutiveRead,
  LitigationRead,
  NewsRead,
  StateBillsRead,
} from "@/lib/read";

// The wire: one cell per channel, fusing what the strip counted with what the read
// said. It replaces both -- TheRead's six sentences and ChannelStrip's five cells --
// because they answered the same question twice, a channel's numbers in one place and
// its sentence 200px below in another, and a reader had to join them by eye.
//
// THE CAMPAIGN SENTENCE IS NOT HERE, and that is the one line the merge drops rather
// than moves. The board states the campaign in figures and a map; a sixth cell
// restating it above them would be the duplication this component exists to remove.
// Five cells, five channels, and the campaign reads on the board.
//
// COLOUR COMES FROM THE PAGE'S OWN VOCABULARY, never from the mock's hexes. globals.css
// declares --c-litigation, --c-legislation and --c-executive with an argued rationale
// ("Red is DOJ in court and violet is legislation... Any future palette change has to
// clear the same test"), and the board below paints from exactly those. The v42 mock
// assigns different hues -- litigation violet, legislation sky, state teal -- which on
// one page would mean litigation is red in the map and violet in the wire. State takes
// --leg-dim because state bills already are legislation ink here (STAGE_STYLE, and the
// map's state-bill dot resolves var(--c-legislation)); news takes a neutral, as it does
// in the mock. Teal is NOT used: --c-outcome reserves it.
//
// ALL DERIVATION STAYS IN lib/read.ts. This component receives computed values and turns
// them into prose, exactly as TheRead did, so the tests keep asserting on numbers.
const CHANNEL_INK: Record<string, string> = {
  legislation: "var(--c-legislation)",
  executive: "var(--c-executive)",
  litigation: "var(--c-litigation)",
  news: "#3f3f3f",
  state: "var(--leg-dim)",
};

const CHANNEL_LABEL: Record<string, string> = {
  legislation: "Legislation",
  executive: "Executive",
  litigation: "Litigation",
  news: "News",
  state: "State",
};

const CHANNEL_HREF: Record<string, string | undefined> = {
  litigation: "/campaign",
  news: "/news",
  state: "/state-bills",
};

function plural(n: number, one: string, many = `${one}s`) {
  return n === 1 ? one : many;
}

function Cell({
  channel,
  row,
  children,
}: {
  channel: string;
  row: ActivityRow | undefined;
  children: React.ReactNode;
}) {
  const day = row?.day ?? 0;
  const week = row?.week ?? 0;
  const total = row?.total ?? 0;
  const historyCount = row?.day_history ?? 0;
  const href = CHANNEL_HREF[channel];
  const label = CHANNEL_LABEL[channel] ?? channel;
  return (
    <div data-channel={channel} className="min-w-0 bg-neutral-900 px-4 pt-3.5 pb-[15px]">
      <div className="flex items-center gap-[7px] whitespace-nowrap text-[11px] uppercase tracking-[0.08em] text-neutral-500">
        <i
          aria-hidden="true"
          className="inline-block h-2 w-2 flex-none rounded-[2px]"
          style={{ background: CHANNEL_INK[channel] ?? "#3f3f3f" }}
        />
        {href ? (
          <Link href={href} className="transition-colors hover:text-neutral-300">
            {label}
          </Link>
        ) : (
          label
        )}
      </div>

      {/* Zero renders as 0, never blank -- the strip's rule, kept. A channel that
          collected nothing is a reading, and on this data it is the common case:
          measured 2026-08-14, three of five collected nothing in 24h. The zero is
          styled DOWN rather than out, so a quiet channel reads as quiet rather than
          as broken. */}
      <div
        data-zero={day === 0 ? "true" : "false"}
        className="mt-[9px] flex items-baseline gap-[9px] whitespace-nowrap tabular-nums"
      >
        <span
          className={
            day === 0
              ? "text-xl font-normal leading-none text-neutral-600"
              : "text-xl font-semibold leading-none text-neutral-100"
          }
        >
          +{day}
        </span>
        <span className="text-xs text-neutral-500">
          /{WINDOW_DAYS.day * 24}h &middot; +{week} /{WINDOW_DAYS.week}d
        </span>
        <span className="ml-auto text-xs text-neutral-500">{total.toLocaleString()}</span>
      </div>

      <p className="mt-[9px] text-xs leading-[17px] text-neutral-400">
        {children}
        {/* WHICH KIND OF COLLECTION PRODUCED THE DELTA, restored from the strip. The
            wire's first draft dropped it and nothing else on the page carried it, so a
            seed day and a busy day looked alike: on 2026-08-16 four dockets were seeded
            and walked, and litigation read +174/24h with all 174 dated between Sep 2025
            and Jul 2026. The delta is not wrong, it is a different question, and this
            clause is what says which one it answered.

            ONLY WHEN NON-ZERO, unlike the delta above it. Zero is information for
            "+0 collected"; a "0 already older" clause on every quiet cell is not, and
            the wire is five cells wide. */}
        {historyCount > 0 && (
          <span
            className="text-neutral-600"
            title={`${historyCount} of the last 24 hours' ${day} items were already more than ${WINDOW_DAYS.week} days old when collected`}
          >
            {" "}
            {historyCount} of them already older than {WINDOW_DAYS.week} days when
            collected.
          </span>
        )}
      </p>
    </div>
  );
}

export function Wire({
  rows,
  news,
  litigation,
  bills,
  executive,
  stateBills,
  vehicle = null,
}: {
  rows: ActivityRow[];
  news: NewsRead;
  litigation: LitigationRead;
  bills: BillsRead;
  executive: ExecutiveRead;
  stateBills: StateBillsRead;
  // THE VEHICLE, READ OFF THE FLAG RATHER THAN OFF THE ORDERING. This used to be
  // `bills.latest?.is_vehicle === 1`, which draws the badge today only because S. 1383
  // happens to hold the most recent action of the six watched bills. That is a property
  // of the data, not of the page: the day any other watched bill takes an action,
  // `latest` stops being the vehicle and the badge silently stops drawing -- on exactly
  // the day the watchlist moved, which is when a reader most needs it.
  //
  // BillsRead cannot answer the question, so the caller does: it holds the full
  // watchlist and finds the flagged row. lib/read.ts stays untouched, which was the
  // constraint; a prop was never the thing being avoided.
  vehicle?: Bill | null;
}) {
  const byChannel = new Map(rows.map((r) => [r.channel, r]));

  const clause: Record<string, React.ReactNode> = {
    legislation:
      bills.total === 0 ? (
        <>No bills on the watchlist.</>
      ) : (
        <>
          {bills.movedInWindow.length === 0 ? (
            <>
              None of the {bills.total} watched {plural(bills.total, "bill")} has moved
              since{" "}
              <span className="text-neutral-200">{formatDate(bills.latestActionAt)}</span>
              .
            </>
          ) : (
            <>
              <span className="text-neutral-200">
                {bills.movedInWindow.length} of {bills.total}
              </span>{" "}
              watched {plural(bills.total, "bill")} moved in the last {WINDOW_DAYS.week}{" "}
              days. Latest: {bills.latest?.short_title ?? bills.latest?.bill_id} (
              {formatDate(bills.latestActionAt)}).
            </>
          )}{" "}
          {vehicle && (
            <>
              <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                Vehicle
              </span>{" "}
              <span className="whitespace-nowrap">{billLabel(vehicle)}</span>.
            </>
          )}
        </>
      ),

    executive:
      executive.total === 0 ? (
        <>Nothing collected on the executive channel.</>
      ) : executive.latest === null ? (
        <>
          <span className="text-neutral-200">0 of {executive.total}</span> collected
          documents score as election-relevant.
        </>
      ) : (
        <>
          <span className="text-neutral-200">{executive.relevant}</span>{" "}
          election-relevant of {executive.total}. Latest:{" "}
          <a
            href={executive.latest.source_url}
            className="text-neutral-200 underline decoration-neutral-700 underline-offset-2 hover:decoration-neutral-400"
          >
            {executive.latest.title}
          </a>{" "}
          ({formatDate(executive.latest.occurred_at)}).
        </>
      ),

    litigation:
      litigation.latestFiling === null ? (
        <>No dockets in the record yet.</>
      ) : (
        <>
          Latest filing{" "}
          <span className="text-neutral-200">{formatDate(litigation.latestFiling)}</span>,{" "}
          {litigation.filedOnLatest.length}{" "}
          {plural(litigation.filedOnLatest.length, "case")}
          {litigation.filedOnLatest.length > 0 && (
            <>
              {" ("}
              {litigation.filedOnLatest
                .map((c) => c.state)
                .slice(0, 3)
                .join(", ")}
              {")"}
            </>
          )}
          .{" "}
          {litigation.movedSinceFiling
            ? "Dockets have moved since."
            : "Nothing has moved since."}
        </>
      ),

    news:
      news.collectedLast24h === 0 ? (
        <>
          Nothing collected in the last 24 hours. The most recent story is dated{" "}
          {formatDate(news.mostRecent?.occurred_at)}.
        </>
      ) : news.lead ? (
        <>
          <span className="text-neutral-200">
            {news.datedInWindow} of {news.collectedLast24h}
          </span>{" "}
          {plural(news.collectedLast24h, "story", "stories")} collected today{" "}
          {plural(news.datedInWindow, "is", "are")} dated in the last {news.windowDays}{" "}
          days. Best-graded:{" "}
          <a
            href={news.lead.source_url}
            className="text-neutral-200 underline decoration-neutral-700 underline-offset-2 hover:decoration-neutral-400"
          >
            {news.lead.title}
          </a>{" "}
          ({news.lead.admiralty_source}
          {news.lead.admiralty_info}, {formatDate(news.lead.occurred_at)}).
        </>
      ) : (
        <>
          {news.collectedLast24h} {plural(news.collectedLast24h, "story", "stories")}{" "}
          collected today, none dated in the last {news.windowDays} days &mdash; the
          newest is dated {formatDate(news.mostRecent?.occurred_at)}.
        </>
      ),

    state:
      stateBills.bills === 0 ? (
        <>No state bills in the dimension yet.</>
      ) : (
        <>
          <span className="text-neutral-200">
            {stateBills.bills} {plural(stateBills.bills, "bill")}
          </span>{" "}
          across {stateBills.states} {plural(stateBills.states, "state")},{" "}
          {stateBills.actedInWindow.length === 0 ? (
            <>
              none dated in the last {WINDOW_DAYS.week} days; latest action{" "}
              {formatDate(stateBills.latestActionAt)}.
            </>
          ) : (
            <>
              {stateBills.actedInWindow.length} dated in the last {WINDOW_DAYS.week} days.
            </>
          )}
        </>
      ),
  };

  // CANONICAL ORDER, not query order -- the rule lib/activity.ts already states for the
  // strip, applied here for the same reason. A channel with no row still gets a cell
  // reading +0, because a wire that silently drops to four cells reads as a layout quirk
  // rather than as the fact it is. Any non-canonical channel in `rows` is appended
  // rather than dropped: a sixth channel appearing in `items` is something to see.
  const extra = rows
    .map((r) => r.channel)
    .filter((c) => !(CHANNELS as readonly string[]).includes(c));

  return (
    // The grid itself is `.wire` in globals.css, not utilities: the utility form
    // rendered two columns at 1900 because Tailwind emitted the arbitrary min-[1180px]
    // variant ahead of the named `sm`, so the wrong rule won above 640. See the comment
    // there, which also covers why the fifth cell spans the row in the two-column band.
    <div className="wire overflow-hidden rounded-lg border border-neutral-800 bg-neutral-800">
      {[...CHANNELS, ...extra].map((channel) => (
        <Cell key={channel} channel={channel} row={byChannel.get(channel)}>
          {clause[channel] ?? <>No reading for this channel.</>}
        </Cell>
      ))}
    </div>
  );
}
