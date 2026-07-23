import Link from "next/link";
import {
  getChannelCounts,
  getBills,
  getCases,
  getExecutiveAll,
} from "@/lib/db";
import { relevanceScore } from "@/lib/relevance";
import { ChannelStrip } from "@/components/ChannelStrip";
import { BillRow } from "@/components/BillRow";
import { CaseRow } from "@/components/CaseRow";
import { ExecutiveSection } from "@/components/ExecutiveSection";

// Render per request against live Turso. No ISR: a single-user read-only
// dashboard saves nothing by caching, and force-dynamic removes the build-time
// Turso dependency (no env vars needed at build, data is always current).
export const dynamic = "force-dynamic";

function SectionHeading({ title, count }: { title: string; count: number }) {
  return (
    <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
      {title}
      <span className="text-sm font-normal tabular-nums text-neutral-500">{count}</span>
    </h2>
  );
}

export default async function Home() {
  const [counts, bills, cases, executiveAll] = await Promise.all([
    getChannelCounts(),
    getBills(),
    getCases(),
    getExecutiveAll(),
  ]);
  // Score the broad channel server-side; the section toggles relevant vs all.
  const relevant = executiveAll.filter((it) => relevanceScore(it.title) > 0);

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">psephos</h1>
        <p className="mt-1 text-sm text-neutral-400">
          The erosion of voting rights across five channels of pressure, federal and state.
        </p>
      </header>

      <section className="mt-8">
        <ChannelStrip counts={counts} />
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
        <SectionHeading title="Cases" count={cases.length} />
        {cases.length === 0 ? (
          <p className="text-sm text-neutral-500">No cases yet.</p>
        ) : (
          <ul className="space-y-3">
            {cases.map((c) => (
              <CaseRow key={c.case_id} c={c} />
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">State legislation</h2>
        <Link
          href="/state-bills"
          className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm text-neutral-300 transition-colors hover:border-neutral-700"
        >
          Election bills across the watched states, subject-filtered via LegiScan →
        </Link>
      </section>

      <section className="mt-10">
        <ExecutiveSection relevant={relevant} all={executiveAll} />
      </section>
    </main>
  );
}
