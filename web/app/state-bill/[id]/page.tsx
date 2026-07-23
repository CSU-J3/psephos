import Link from "next/link";
import { notFound } from "next/navigation";
import { getStateBill, getStateBillTimeline } from "@/lib/db";
import { stateBillLabel, stateBillStatus } from "@/lib/statebill";
import { formatDate } from "@/lib/format";
import { Timeline } from "@/components/Timeline";

// Live Turso per request, no build-time dependency -- same as the bill page.
export const dynamic = "force-dynamic";

export default async function StateBillPage({
  params,
}: {
  params: Promise<{ id: string }>; // Next 15: params is a Promise
}) {
  const { id } = await params;
  const bill = await getStateBill(id);
  if (!bill) notFound();
  const items = await getStateBillTimeline(id);
  const status = stateBillStatus(bill.status);

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/state-bills" className="text-sm text-neutral-400 hover:underline">
        ← State legislation
      </Link>

      <header className="mt-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="font-mono text-sm text-neutral-400">{stateBillLabel(bill)}</span>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              {bill.title ?? bill.state_bill_id}
            </h1>
          </div>
          {bill.is_vehicle === 1 && (
            <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-400">
              Vehicle
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
          {bill.session && <span>{bill.session}</span>}
          {status && <span>{status}</span>}
        </div>
        {bill.description && bill.description !== bill.title && (
          <p className="mt-2 text-sm text-neutral-300">{bill.description}</p>
        )}
        {bill.last_action && (
          <p className="mt-2 text-sm text-neutral-300">
            <span className="text-neutral-500">{formatDate(bill.last_action_at)} — </span>
            {bill.last_action}
          </p>
        )}
        {bill.url && (
          <a
            href={bill.url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-sm text-sky-400 hover:underline"
          >
            View on LegiScan ↗
          </a>
        )}
      </header>

      <section className="mt-8">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Timeline
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {items.length}
          </span>
        </h2>
        <Timeline items={items} />
      </section>
    </main>
  );
}
