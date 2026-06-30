import type { Bill } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { billLabel } from "@/lib/bill";

// One watched bill with its latest action. The `is_vehicle` flag is surfaced
// loudly: an unrelated bill carrying voting provisions (S. 1383) is the whole
// point of the project, the maneuver a plain bill tracker misses.
export function BillRow({ bill }: { bill: Bill }) {
  return (
    <li className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="font-mono text-sm text-neutral-400">{billLabel(bill)}</span>
          <span className="ml-2 font-medium">
            {bill.short_title ?? bill.title ?? bill.bill_id}
          </span>
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
          <span className="text-neutral-500">{formatDate(bill.latest_action_at)} — </span>
          {bill.latest_action}
        </p>
      )}
    </li>
  );
}
