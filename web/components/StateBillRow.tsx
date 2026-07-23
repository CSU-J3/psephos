import Link from "next/link";
import type { StateBill } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { stateBillLabel, stateBillStatus } from "@/lib/statebill";

// One state election bill with its latest action. Mirrors BillRow; the amber
// Vehicle badge is wired for 5b-b (state vehicle detection) though nothing is
// flagged yet. No sponsor field -- state bills carry none.
export function StateBillRow({ bill }: { bill: StateBill }) {
  const status = stateBillStatus(bill.status);
  return (
    <li>
      <Link
        href={`/state-bill/${bill.state_bill_id}`}
        className="block rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-700"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="font-mono text-sm text-neutral-400">{stateBillLabel(bill)}</span>
            <span className="ml-2 font-medium">{bill.title ?? bill.state_bill_id}</span>
          </div>
          {bill.is_vehicle === 1 && (
            <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-400">
              Vehicle
            </span>
          )}
        </div>
        {status && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
            <span>{status}</span>
          </div>
        )}
        {bill.last_action && (
          <p className="mt-2 text-sm text-neutral-300">
            <span className="text-neutral-500">{formatDate(bill.last_action_at)} — </span>
            {bill.last_action}
          </p>
        )}
      </Link>
    </li>
  );
}
