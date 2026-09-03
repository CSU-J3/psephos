import Link from "next/link";
import {
  getChannelActivity,
  getTimelineEntries,
  getBills,
  getCases,
  getCampaignRows,
  getExecutiveAll,
  getStateBills,
  getBoardMonthly,
  getTrackerNotes,
} from "@/lib/db";
import type { Case, CaseRef, NewsItem } from "@/lib/db";
import {
  readBills,
  readCampaign,
  readExecutive,
  readLitigation,
  readNews,
  readStateBills,
} from "@/lib/read";
import { relevanceScore } from "@/lib/relevance";
import { Wire } from "@/components/Wire";
import { billLabel } from "@/lib/bill";
import { formatDate } from "@/lib/format";
import { DayTimeline } from "@/components/DayTimeline";
import { BillRow } from "@/components/BillRow";
import { CaseRow } from "@/components/CaseRow";
import { ExecutiveSection } from "@/components/ExecutiveSection";
import { RotatingTime } from "@/components/RotatingTime";
import { buildTimeline } from "@/lib/timeline";
import {
  boardDomain,
  cumulativeFilings,
  frames,
  isEoNumbered,
  OVERLAY_LABEL,
  POSTURE_LABEL,
} from "@/lib/board";
import { RecordsMap, type MapState } from "@/components/RecordsMap";
import { buildCells, continuesOf, trackerStatus } from "@/lib/campaign";
import { tryResolveState } from "@/lib/map";
import { SourceLegend } from "@/components/SourceLegend";

// Route stays force-dynamic: it removes the build-time Turso dependency (no env
// vars needed at build) and keeps the bills/cases/executive queries live per
// request, where freshness is cheap. The exception is the channel-activity query,
// which scans the whole `items` spine (~9.4k index rows for 15 integers); that one
// is cached in lib/db.ts (unstable_cache, 1h) so the scan leaves the per-render
// path. This comment used to claim a read-only dashboard "saves nothing by
// caching" -- the per-render scan disproved that. The strip's counts and its 24h/7d
// windows both carry up to 1h of staleness, since the window start is computed
// inside the cached call; every other query on the page is current.
export const dynamic = "force-dynamic";

// SectionHeading was deleted here: its only caller was the "Watched bills" heading in
// the old column 3, and the rail's fold carries that reading in its <summary> instead.

// How many of the top dockets to show before the disclosure. Eight is enough to
// read the campaign's last week without the section becoming the 46-row list it
// replaced.
const RECENT_CASES = 8;

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/campaign", label: "DOJ voter-data campaign" },
  { href: "/state-bills", label: "State legislation" },
  { href: "/news", label: "Reporting" },
] as const;

// The supersession pair, resolved from rows the page already holds -- no extra
// query, and no reverse lookup in SQL. `superseded_by` is set on the DEAD row and
// points forward, so the forward direction is a lookup by id and the backward
// direction is this map.
//
// BUILT FROM ALL ROWS, NOT THE VISIBLE SLICE. The top-8 window currently contains
// LWV v. DHS (D.D.C.) whose successor is the D.C. Circuit row further down the
// list; keyed on the slice, its chain line would silently disappear.
function buildChains(cases: Case[]) {
  const byId = new Map(cases.map((c) => [c.case_id, c]));
  const bySuccessor = new Map<string, Case>();
  for (const c of cases) if (c.superseded_by) bySuccessor.set(c.superseded_by, c);
  return (c: Case): { successor?: CaseRef | null; predecessor?: CaseRef | null } => ({
    successor: c.superseded_by ? byId.get(c.superseded_by) : null,
    predecessor: bySuccessor.get(c.case_id) ?? null,
  });
}

export default async function Home() {
  const [activity, entries, bills, cases, campaignRows, executiveAll, stateBills, monthly, trackerNotes] =
    await Promise.all([
      getChannelActivity(),
      getTimelineEntries(),
      getBills(),
      getCases(),
      getCampaignRows(),
      getExecutiveAll(),
      getStateBills(),
      getBoardMonthly(),
      getTrackerNotes(),
    ]);

  const now = new Date();

  // ONE QUERY FEEDS BOTH, because the timeline's set is a strict superset of the
  // news line's. getTimelineEntries returns everything dated in the band range plus
  // everything collected in the last 24h; filtering that on fetched_at recovers
  // exactly what the old 24h feed query returned, so nothing is fetched twice.
  //
  // THE NEWS LINE STILL COUNTS TODAY'S COLLECTION, not the 7-day dated set, and that
  // is the line's own claim: "N of the M stories collected today are dated in the
  // last 7 days". The pairing is what exposes an aggregator delivering old news as
  // new, so both halves must come from the collected set.
  //
  // It reads these rows rather than getNewsFeed for a second reason: getNewsFeed is
  // B2-only, which would make the grade sort a no-op and always lead with a tracker
  // item. These rows are every grade, with outlet promotion already applied.
  const collectedSince = new Date(now.getTime() - 24 * 3_600_000).toISOString();
  const newsToday = entries.filter(
    (e) => e.channel === "news" && e.fetched_at >= collectedSince,
  ) as NewsItem[];
  const collectedLast24h =
    activity.find((r) => r.channel === "news")?.day ?? newsToday.length;

  const timeline = buildTimeline(entries, now);
  const news = readNews(newsToday, collectedLast24h, now);
  const litigation = readLitigation(campaignRows);
  const campaign = readCampaign(campaignRows, now);
  const billsRead = readBills(bills, now);
  // The vehicle, for the fold's summary line. Read off the watchlist rather than off
  // billsRead.latest, which is only the vehicle by coincidence of S. 1383 holding the
  // most recent action -- the day another bill moves, latest stops being the vehicle
  // and the summary would silently drop the one flag this project exists to surface.
  const vehicleBill = bills.find((b) => b.is_vehicle === 1) ?? null;
  const executive = readExecutive(executiveAll, now);
  const stateBillsRead = readStateBills(stateBills, now);

  // --- the records chart -------------------------------------------------------
  // Every input is derived from rows, none is a literal. cumulativeFilings collapses
  // one row per state into one step per DISTINCT filing date -- 31 states, 14 dates on
  // 2026-08-18 -- and the domain floors on whichever series starts first rather than on
  // the filings, which is currently the state-bill series at 2024-11.
  const firstFiledByState = [
    ...campaignRows
      .reduce((m, r) => {
        const prev = m.get(r.state);
        if (!prev || (r.filed_at && r.filed_at < prev)) m.set(r.state, r.filed_at);
        return m;
      }, new Map<string, string | null>())
      .entries(),
  ].map(([state, filed_at]) => ({ state, filed_at }));

  const filings = cumulativeFilings(firstFiledByState);
  const eoTicks = executiveAll
    .filter((it) => isEoNumbered(it.title) && relevanceScore(it.title) > 0 && it.occurred_at)
    .map((it) => ({
      date: it.occurred_at!.slice(0, 10),
      t: Date.parse(`${it.occurred_at!.slice(0, 10)}T00:00:00Z`),
      title: it.title,
    }));

  const boardInput = {
    filings,
    stateBills: monthly.stateBillsFirstSeen,
    legislation: monthly.legislationActions,
    eos: eoTicks,
  };
  const domain = boardDomain(boardInput, now);
  const boardFrames = frames(domain, now);

  // --- the map's per-jurisdiction rows -------------------------------------------
  // Posture comes from buildCells, the SAME classifier /campaign renders, so the two
  // pages cannot disagree about whether a suit is live. The note is the tracker's own
  // Status field, extracted verbatim -- trackerStatus pulls the field out of a
  // pipe-delimited string, it does not interpret it, and nothing here classifies an
  // outcome from prose.
  const cells = buildCells(campaignRows, now);
  const mapStates: MapState[] = cells.map((c) => {
    const rows = [c.live, ...c.predecessors, ...c.unlinked].filter(
      (r): r is NonNullable<typeof r> => r !== null,
    );
    const feature = tryResolveState(c.name) ?? tryResolveState(c.code);
    return {
      ab: feature?.ab ?? c.code,
      name: feature?.name ?? c.name,
      // NO TRANSLATION HERE ANY MORE. This line used to be a ternary mapping the
      // cell's vocabulary onto the map's, which is what a two-vocabulary system looks
      // like from the inside: a working conversion nobody reads as a problem. Cells and
      // postures are now the same type, so there is nothing to convert.
      posture: c.status,
      bills: 0, // the running total is per-frame and computed in the component
      dockets: rows.map((r) => ({
        caseId: r.case_id,
        court: r.court,
        docket: r.docket_number,
        filed: r.filed_at,
        status: r.status,
        // The RAW docket length. It shipped as null because CampaignRow carried no
        // count, and a made-up number on a docket line is a false claim about a
        // court record -- a missing figure was the honest form until the query
        // existed. It does now.
        entries: r.entry_count,
        // TWO DIRECTIONS, AND THEY BELONG ON DIFFERENT ROWS. `superseded_by` is set
        // on the dead row pointing FORWARD, so "continued as" renders on the
        // predecessor. "continues" is the reverse and belongs on the row being
        // continued INTO -- the successor -- naming what it continues. This
        // previously fired on the predecessor and pointed at the live case, so one
        // row said both "continued as X" and "continues X" about the same id, which
        // is circular and false, while the successor said nothing at all.
        supersededBy: r.superseded_by,
        // An ARRAY, because a successor can continue more than one docket and a
        // single-valued field would silently show one and hide the rest -- the same
        // shape as the predecessor-lookup defect recorded in the falsified list.
        continues: continuesOf(rows, r),
      })),
      notes: c.live ? trackerStatus(trackerNotes.get(c.live.case_id)) : null,
    };
  });

  // The executive section still swaps two arrays client-side; the read's line above
  // reports the same split from the same lens.
  const relevant = executiveAll.filter((it) => relevanceScore(it.title) > 0);

  const chainFor = buildChains(cases);
  const recentCases = cases.slice(0, RECENT_CASES);
  const restCases = cases.slice(RECENT_CASES);
  // A DATA RULE, not a constant. All 46 rows read `voter-data` today, so the badge
  // is decoration and is hidden; it returns on its own the day a second kind of
  // suit lands, with no code change.
  const showCategory = new Set(cases.map((c) => c.category)).size > 1;

  return (
    <main className="mx-auto max-w-[2200px] p-10">
      <header>
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">psephos</h1>
          <p className="text-xs text-neutral-500">
            collected <RotatingTime iso={now.toISOString()} />
          </p>
        </div>
        <p className="mt-1 text-sm text-neutral-400">
          The erosion of voting rights across five channels of pressure, federal and
          state.
        </p>

        <nav className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {NAV.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              aria-current={t.href === "/" ? "page" : undefined}
              className={
                t.href === "/"
                  ? "border-b border-neutral-300 pb-1 text-neutral-100"
                  : "border-b border-transparent pb-1 text-neutral-400 transition-colors hover:text-neutral-200"
              }
            >
              {t.label}
            </Link>
          ))}
        </nav>

        {/* Exactly once, here, before the reader meets the vocabulary. */}
        <SourceLegend />
      </header>

      {/* The wire: the read and the strip merged into one row of five cells, a
          channel's numbers and its sentence in the same cell rather than 200px
          apart. The campaign sentence is not carried over -- the board states it. */}
      <section className="mt-8">
        <Wire
          rows={activity}
          news={news}
          litigation={litigation}
          bills={billsRead}
          executive={executive}
          stateBills={stateBillsRead}
          vehicle={vehicleBill}
        />
      </section>

      {/* THE ZONES, three named areas rather than three tracks -- see .zones in
          globals.css for the shape and why it is declared there. One column below
          1280; feed beside rail with the board full-width beneath at 1280; all three
          side by side at 1900. The board moving between rows is a reflow the old
          track-based grid could not express: it could only drop the third column's
          content under the second. */}
      <div className="zones mt-10">
        {/* Feed -- the last 7 days, every channel on one axis by occurred_at. */}
        <section className="z-feed">
          <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
            The last 7 days
            <span className="text-sm font-normal text-neutral-500">UTC days</span>
          </h2>
          <DayTimeline timeline={timeline} now={now} />
        </section>

        {/* Board -- state voter records: the chart, map, scrubber and detail panel.
            Recently-moved used to sit at the bottom of this column and is now in the
            rail; the board keeps only what the replay drives. */}
        <section className="z-board">
          <h2 className="mb-3 text-lg font-semibold tracking-tight">
            State voter records
          </h2>

          <div className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900/40 p-3">
            <RecordsMap
              domain={domain}
              filings={filings}
              stateBillMonths={monthly.stateBillsFirstSeen}
              legislation={monthly.legislationActions}
              eos={eoTicks}
              frames={boardFrames}
              states={mapStates}
              billsByStateMonth={monthly.stateBillsByState}
            />
          </div>

          <Link
            href="/campaign"
            className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-700"
          >
            {/*
              EVERY FIGURE CARRIES data-figure, including the two that are aggregates
              rather than postures. The attribute is what lets assert-encodings join
              the line against the key without either side holding a list of the
              other's contents -- a list is the thing that drifts. The unpainted
              wordings are READ FROM OVERLAY_LABEL and the posture wordings from
              POSTURE_LABEL, never typed here: the key makes a claim about these exact
              words and a second copy could stop matching it silently.

              TWO CLAUSES, AND THE SPLIT IS THE FIX RATHER THAN DECORATION. The
              postures PARTITION the 31 sued; the overlays are ATTRIBUTES those same
              jurisdictions can carry, and more than one at once. Run as a single flat
              list they read as one series, so "2 ended" followed by "6 carrying an
              unlinked ending" invited the arithmetic a reader cannot make work -- the
              larger number looking like a subset of the smaller. Nothing about the
              figures was wrong; they were in one sentence that implied a relationship
              they do not have. "among those N" names the set the second clause is over.

              POSTURE_LABEL.none IS DELIBERATELY ABSENT. The line counts what DOJ did,
              and "never sued" is the complement -- total minus sued -- which the map
              paints and the /campaign copy explains. A figure for it here would be a
              third posture in a sentence about two.
            */}
            <p className="text-sm text-neutral-300">
              <span className="font-medium text-neutral-100">
                <span data-figure="sued">{campaign.sued}</span> of{" "}
                <span data-figure="total">{campaign.total}</span> jurisdictions sued
              </span>{" "}
              · <span data-figure="live">{campaign.live}</span>{" "}
              <span data-posture="live">{POSTURE_LABEL.live}</span> ·{" "}
              <span data-figure="ended">{campaign.ended}</span>{" "}
              <span data-posture="ended">{POSTURE_LABEL.ended}</span>
            </p>
            <p className="mt-1 text-sm text-neutral-400">
              among those {campaign.sued}:{" "}
              <span data-figure="chains">{campaign.chains}</span>{" "}
              {OVERLAY_LABEL.chains} ·{" "}
              <span data-figure="dormant">{campaign.dormant}</span>{" "}
              {OVERLAY_LABEL.dormant}
              {campaign.unlinkedEndings > 0 && (
                <>
                  {" "}
                  ·{" "}
                  <span data-figure="unlinkedEndings">
                    {campaign.unlinkedEndings}
                  </span>{" "}
                  {OVERLAY_LABEL.unlinkedEndings}
                </>
              )}
            </p>
            <p className="mt-1 text-xs text-neutral-500">
              One grid over all 50 states and DC: where DOJ sued, where it lost, and
              where it has not acted →
            </p>
          </Link>

        </section>

        {/* THE RAIL: recently-moved, then the two federal channels as folds. All three
            were previously columns 2 and 3; the rail is where the page puts what a
            reader consults rather than reads. */}
        <div className="z-side">
          <section>
            <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
              Recently moved
              <span className="text-xs font-normal tabular-nums text-neutral-600">
                {recentCases.length} of {cases.length}
              </span>
              <Link
                href="/campaign"
                className="ml-auto text-xs font-normal normal-case tracking-normal text-neutral-500 hover:text-neutral-300"
              >
                All {cases.length} →
              </Link>
            </h3>
            {cases.length === 0 ? (
              <p className="text-sm text-neutral-500">No cases yet.</p>
            ) : (
              <>
                <ul className="rounded-lg border border-neutral-800 bg-neutral-900/40 py-1">
                  {recentCases.map((c) => (
                    <CaseRow
                      key={c.case_id}
                      c={c}
                      showCategory={showCategory}
                      chain={chainFor(c)}
                      compact
                    />
                  ))}
                </ul>
                {restCases.length > 0 && (
                  // A native <details>: no client bundle for a disclosure.
                  <details className="group mt-2">
                    <summary className="cursor-pointer list-none px-3.5 py-2 text-xs text-neutral-500 transition-colors hover:text-neutral-300">
                      <span className="group-open:hidden">
                        The other {restCases.length} dockets →
                      </span>
                      <span className="hidden group-open:inline">
                        Hide the other {restCases.length} ↑
                      </span>
                    </summary>
                    <ul className="mt-1 rounded-lg border border-neutral-800 bg-neutral-900/40 py-1">
                      {restCases.map((c) => (
                        <CaseRow
                          key={c.case_id}
                          c={c}
                          showCategory={showCategory}
                          chain={chainFor(c)}
                          compact
                        />
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}
          </section>

          {/* Watched bills, folded. The summary carries the reading so the fold is
              worth leaving shut: the count, whether anything moved, and the vehicle.
              Native <details> again -- a disclosure does not need a client bundle. */}
          <details className="group rounded-lg border border-neutral-800 bg-neutral-900">
            <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2.5 gap-y-1 px-4 py-3">
              <span className="text-sm font-semibold tracking-tight text-neutral-100">
                Watched bills
              </span>
              <span className="text-xs text-neutral-500">
                {bills.length}
                {billsRead.movedInWindow.length === 0 && billsRead.latestActionAt ? (
                  <> · none moved since {formatDate(billsRead.latestActionAt)}</>
                ) : (
                  <> · {billsRead.movedInWindow.length} moved in 7 days</>
                )}
              </span>
              {vehicleBill && (
                <>
                  <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                    Vehicle
                  </span>
                  <span className="text-xs text-neutral-500">
                    {billLabel(vehicleBill)}
                  </span>
                </>
              )}
              <span className="ml-auto text-xs text-neutral-600 group-open:hidden">↓</span>
              <span className="ml-auto hidden text-xs text-neutral-600 group-open:inline">
                ↑
              </span>
            </summary>
            <div className="border-t border-neutral-800 px-3 py-3">
              {bills.length === 0 ? (
                <p className="text-sm text-neutral-500">No bills yet.</p>
              ) : (
                <ul className="space-y-3">
                  {bills.map((b) => (
                    <BillRow key={b.bill_id} bill={b} />
                  ))}
                </ul>
              )}
            </div>
          </details>

          {/* Executive, folded. ExecutiveSection keeps its own client-side
              relevant/all swap; the fold wraps it rather than replacing it. */}
          <details className="group rounded-lg border border-neutral-800 bg-neutral-900">
            <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2.5 gap-y-1 px-4 py-3">
              <span className="text-sm font-semibold tracking-tight text-neutral-100">
                Executive
              </span>
              <span className="text-xs text-neutral-500">
                {executive.relevant} election-relevant of {executive.total}
                {executive.latest && <> · latest {formatDate(executive.latest.occurred_at)}</>}
              </span>
              <span className="ml-auto text-xs text-neutral-600 group-open:hidden">↓</span>
              <span className="ml-auto hidden text-xs text-neutral-600 group-open:inline">
                ↑
              </span>
            </summary>
            <div className="border-t border-neutral-800 px-3 py-3">
              <ExecutiveSection relevant={relevant} all={executiveAll} />
            </div>
          </details>
        </div>
      </div>
    </main>
  );
}
