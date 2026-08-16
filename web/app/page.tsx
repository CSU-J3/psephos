import Link from "next/link";
import {
  getChannelActivity,
  getFeed,
  getBills,
  getCases,
  getCampaignRows,
  getExecutiveAll,
} from "@/lib/db";
import type { Case, CaseRef } from "@/lib/db";
import { buildCells, summarize } from "@/lib/campaign";
import { relevanceScore } from "@/lib/relevance";
import { ChannelStrip } from "@/components/ChannelStrip";
import { ActivityFeed } from "@/components/ActivityFeed";
import { BillRow } from "@/components/BillRow";
import { CaseRow } from "@/components/CaseRow";
import { ExecutiveSection } from "@/components/ExecutiveSection";

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
  const [activity, feed, bills, cases, campaignRows, executiveAll] = await Promise.all([
    getChannelActivity(),
    getFeed(),
    getBills(),
    getCases(),
    getCampaignRows(),
    getExecutiveAll(),
  ]);
  // Score the broad channel server-side; the section toggles relevant vs all.
  const relevant = executiveAll.filter((it) => relevanceScore(it.title) > 0);

  // The same three functions /campaign runs, over the same rows, so the two pages
  // cannot report different numbers for the same moment.
  const campaign = summarize(buildCells(campaignRows, new Date()));

  const chainFor = buildChains(cases);
  const recentCases = cases.slice(0, RECENT_CASES);
  const restCases = cases.slice(RECENT_CASES);
  // A DATA RULE, not a constant. All 46 rows read `voter-data` today, so the badge
  // is decoration and is hidden; it returns on its own the day a second kind of
  // suit lands, with no code change.
  const showCategory = new Set(cases.map((c) => c.category)).size > 1;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">psephos</h1>
        <p className="mt-1 text-sm text-neutral-400">
          The erosion of voting rights across five channels of pressure, federal and state.
        </p>
      </header>

      <section className="mt-8">
        <ChannelStrip rows={activity} />
      </section>

      {/* Directly below the strip, and reading the same 24h window off the same
          column at the same TTL. The strip says how much moved; this says what. */}
      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Recent activity</h2>
        <ActivityFeed rows={feed} />
      </section>

      {/* ONE OBJECT, NOT DOZENS OF NEAR-IDENTICAL ROWS -- the redesign block's move
          3, whose home half had not been done. /campaign was built to replace the
          flat list and the flat list stayed, so the page carried both: a link to the
          grid, and then 46 rows underneath it repeating what the grid says. The
          summary is now the section, the eight most recently moved dockets are the
          detail, and the rest is one disclosure away. */}
      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">
          The DOJ voter-data campaign
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
              // ExecutiveSection is a client component because it SWAPS two arrays;
              // this only shows and hides one, which the platform already does.
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

      <section className="mt-10">
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
      </section>

      <section className="mt-10">
        <ExecutiveSection relevant={relevant} all={executiveAll} />
      </section>

      {/* The two channels that have their own route and no summary worth putting
          here, as one row at the bottom rather than two full-width sections in the
          middle. They were padding the page between the live channels and the
          executive one: EO 14248 and EO 14399 are the executive channel's headline
          documents, and they sat below two one-line link cards on a 13,000-pixel
          page. Order across the whole page is now liveness -- what moves, then what
          does not, then the archives. */}
      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Archives</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Link
            href="/state-bills"
            className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm text-neutral-300 transition-colors hover:border-neutral-700"
          >
            <span className="font-medium text-neutral-100">State legislation</span>
            <span className="mt-1 block text-xs text-neutral-500">
              Election bills across the watched states, subject-filtered via LegiScan →
            </span>
          </Link>
          <Link
            href="/news"
            className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm text-neutral-300 transition-colors hover:border-neutral-700"
          >
            <span className="font-medium text-neutral-100">Reporting</span>
            <span className="mt-1 block text-xs text-neutral-500">
              Coverage from the maintained trackers, B2 sources only →
            </span>
          </Link>
        </div>
      </section>
    </main>
  );
}
