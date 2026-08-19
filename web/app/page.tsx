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
import { ChannelStrip } from "@/components/ChannelStrip";
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
} from "@/lib/board";
import { RecordsMap, type MapState } from "@/components/RecordsMap";
import { buildCells, trackerStatus } from "@/lib/campaign";
import { tryResolveState } from "@/lib/map";
import { SourceLegend } from "@/components/SourceLegend";
import { TheRead } from "@/components/TheRead";

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

function SectionHeading({ title, count }: { title: string; count: number }) {
  return (
    <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
      {title}
      <span className="text-sm font-normal tabular-nums text-neutral-500">{count}</span>
    </h2>
  );
}

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
      posture: c.status === "active" ? "live" : c.status === "ended" ? "ended" : "none",
      bills: 0, // the running total is per-frame and computed in the component
      dockets: rows.map((r) => ({
        caseId: r.case_id,
        court: r.court,
        docket: r.docket_number,
        filed: r.filed_at,
        status: r.status,
        entries: null,
        supersededBy: r.superseded_by,
        predecessorOf: c.predecessors.some((p) => p.case_id === r.case_id)
          ? (c.live?.case_id ?? null)
          : null,
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

      <section className="mt-8">
        <TheRead
          news={news}
          litigation={litigation}
          campaign={campaign}
          bills={billsRead}
          executive={executive}
          stateBills={stateBillsRead}
        />
        {/* The strip's numbers survive the read as one muted line beneath it: the
            read says what happened, this says how much. */}
        <div className="mt-6 border-t border-neutral-900 pt-4">
          <ChannelStrip rows={activity} />
        </div>
      </section>

      {/* Three columns above 1900px, two above 1280 with the third column's content
          moving under the second, one below. The tracks are the handoff's:
          1.32fr / 1.16fr / .86fr with floors, so the middle column can hold the
          board's 1041-unit viewBox without the timeline collapsing. */}
      <div className="mt-10 grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1.32fr)_minmax(440px,1.16fr)] 3xl:grid-cols-[minmax(0,1.32fr)_minmax(440px,1.16fr)_minmax(340px,.86fr)]">
        {/* Column 1 -- the last 7 days, every channel on one axis by occurred_at. */}
        <section>
          <h2 className="mb-3 text-lg font-semibold tracking-tight">The last 7 days</h2>
          <DayTimeline timeline={timeline} />
        </section>

        {/* Column 2 -- state voter records. The chart, map, scrubber and detail
            panel land here in commits 5 and 6; until then the column carries the
            campaign's dockets so the shell is never a placeholder. */}
        <section>
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
            <p className="text-sm text-neutral-300">
              <span className="font-medium text-neutral-100">
                {campaign.sued} of {campaign.total} jurisdictions sued
              </span>{" "}
              · {campaign.active} active · {campaign.ended} ended ·{" "}
              {campaign.chains} continued elsewhere · {campaign.dormant} quiet
              {campaign.unlinkedEndings > 0 && (
                <> · {campaign.unlinkedEndings} ended, no link asserted</>
              )}
            </p>
            <p className="mt-1 text-xs text-neutral-500">
              One grid over all 50 states and DC: where DOJ sued, where it lost, and
              where it has not acted →
            </p>
          </Link>

          {cases.length === 0 ? (
            <p className="mt-4 text-sm text-neutral-500">No cases yet.</p>
          ) : (
            <>
              <h3 className="mt-6 mb-3 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
                Recently moved
                <span className="text-xs font-normal tabular-nums text-neutral-600">
                  {recentCases.length} of {cases.length}
                </span>
              </h3>
              <ul className="space-y-3">
                {recentCases.map((c) => (
                  <CaseRow
                    key={c.case_id}
                    c={c}
                    showCategory={showCategory}
                    chain={chainFor(c)}
                  />
                ))}
              </ul>
              {restCases.length > 0 && (
                // A native <details>: no client bundle for a disclosure.
                <details className="mt-3 group">
                  <summary className="cursor-pointer list-none rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 text-sm text-neutral-400 transition-colors hover:border-neutral-700">
                    <span className="group-open:hidden">All {cases.length} dockets →</span>
                    <span className="hidden group-open:inline">
                      Hide the other {restCases.length} ↑
                    </span>
                  </summary>
                  <ul className="mt-3 space-y-3">
                    {restCases.map((c) => (
                      <CaseRow
                        key={c.case_id}
                        c={c}
                        showCategory={showCategory}
                        chain={chainFor(c)}
                      />
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </section>

        {/* Column 3 -- watched bills and the executive channel. */}
        <section>
          <SectionHeading title="Watched bills" count={bills.length} />
          {bills.length === 0 ? (
            <p className="text-sm text-neutral-500">No bills yet.</p>
          ) : (
            <ul className="space-y-3">
              {bills.map((b) => (
                <BillRow key={b.bill_id} bill={b} />
              ))}
            </ul>
          )}

          <div className="mt-10">
            <ExecutiveSection relevant={relevant} all={executiveAll} />
          </div>
        </section>
      </div>
    </main>
  );
}
