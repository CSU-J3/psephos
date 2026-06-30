import Link from "next/link";
import { notFound } from "next/navigation";
import { getBill, getBillTimeline } from "@/lib/db";
import { billLabel } from "@/lib/bill";
import { formatDate } from "@/lib/format";
import { Timeline } from "@/components/Timeline";

// Live Turso per request, no build-time dependency -- same as home.
export const dynamic = "force-dynamic";

export default async function BillPage({
  params,
}: {
  params: Promise<{ bill_id: string }>; // Next 15: params is a Promise
}) {
  const { bill_id } = await params;
  const bill = await getBill(bill_id);
  if (!bill) notFound();
  const items = await getBillTimeline(bill_id);

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="font-mono text-sm text-neutral-400">{billLabel(bill)}</span>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              {bill.short_title ?? bill.title ?? bill.bill_id}
            </h1>
          </div>
          {bill.is_vehicle === 1 && (
            <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-400">
              Vehicle
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
          {bill.sponsor && <span>{bill.sponsor}</span>}
          {bill.status && <span>{bill.status}</span>}
        </div>
        {bill.latest_action && (
          <p className="mt-2 text-sm text-neutral-300">
            <span className="text-neutral-500">
              {formatDate(bill.latest_action_at)} —{" "}
            </span>
            {bill.latest_action}
          </p>
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
