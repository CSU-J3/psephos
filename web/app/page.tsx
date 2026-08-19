import Link from "next/link";
import {
  getChannelActivity,
  getFeed,
  getBills,
  getCases,
  getCampaignRows,
  getExecutiveAll,
  getStateBills,
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
  const [activity, feed, bills, cases, campaignRows, executiveAll, stateBills] =
    await Promise.all([
      getChannelActivity(),
      getFeed(),
      getBills(),
      getCases(),
      getCampaignRows(),
      getExecutiveAll(),
      getStateBills(),
    ]);

  const now = new Date();

  // THE NEWS LINE READS getFeed, NOT getNewsFeed, and the choice is load-bearing.
  //
  // getNewsFeed is the /news query: B2 only, unwindowed, ~436 rows. Feeding it here
  // would make the grade sort a no-op -- every candidate is B2, so "highest-graded"
  // silently degrades to "newest" and the lead is always a tracker item, which is
  // not what the line claims to say.
  //
  // getFeed is every channel, every grade, over a 24h `fetched_at` window with no
  // row cap, and it already applies outlet promotion. Filtered to the news channel
  // it IS the denominator the line needs: section 4.2 asks for "dated within 7 days
  // against total collected in 24h", and that is one set partitioned by date rather
  // than two independently-sourced numbers. The mock's own lead was a B2 Democracy
  // Docket item drawn out of a mixed set, which only the mixed query can reproduce.
  //
  // The consequence, stated rather than hidden: `datedInWindow` counts backdated
  // items among TODAY'S COLLECTION, not every news item dated in the last week. A
  // story dated four days ago and collected three days ago is in neither number.
  // That is the intended reading -- the pairing is what exposes an aggregator
  // delivering old news as new -- but it is not "all news dated this week".
  const newsToday = feed.filter((e) => e.channel === "news") as NewsItem[];
  const collectedLast24h =
    activity.find((r) => r.channel === "news")?.day ?? newsToday.length;

  const timeline = buildTimeline(feed, now);
  const news = readNews(newsToday, collectedLast24h, now);
  const litigation = readLitigation(campaignRows);
  const campaign = readCampaign(campaignRows, now);
  const billsRead = readBills(bills, now);
  const executive = readExecutive(executiveAll, now);
  const stateBillsRead = readStateBills(stateBills, now);

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
      <div className="mt-10 grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1.32fr)_minmax(440px,1.16fr)] min-[1900px]:grid-cols-[minmax(0,1.32fr)_minmax(440px,1.16fr)_minmax(340px,.86fr)]">
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
