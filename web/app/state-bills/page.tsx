import Link from "next/link";
import { getStateBills } from "@/lib/db";
import type { StateBill } from "@/lib/db";
import { StateBillRow } from "@/components/StateBillRow";

// Live Turso per request, no build-time dependency -- same as home.
export const dynamic = "force-dynamic";

export default async function StateBillsPage() {
  const bills = await getStateBills();
  // Rows arrive ordered by state, then recency -- group in one linear pass, no re-sort.
  const byState = new Map<string, StateBill[]>();
  for (const b of bills) {
    const group = byState.get(b.state);
    if (group) group.push(b);
    else byState.set(b.state, [b]);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">State legislation</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {bills.length} election bills across {byState.size} states, subject-filtered via LegiScan.
        </p>
      </header>

      {[...byState.entries()].map(([state, group]) => (
        <section key={state} className="mt-10">
          <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
            {state}
            <span className="text-sm font-normal tabular-nums text-neutral-500">
              {group.length}
            </span>
          </h2>
          <ul className="space-y-3">
            {group.map((b) => (
              <StateBillRow key={b.state_bill_id} bill={b} />
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
