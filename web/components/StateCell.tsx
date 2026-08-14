import Link from "next/link";
import type { Cell } from "@/lib/campaign";

// One jurisdiction in the campaign grid. Deliberately small: the code, the live
// docket, and two markers. The claims that need words -- which court ended it,
// what the chain is, why a docket is quiet -- live in the prose rows below the
// grid, where there is room to grade them. A badge per cell at 51 cells is noise.
//
// Empty cells stay in the grid at low contrast. Their absence is the point: DOJ
// demanded data from all 50 states and DC and sued 31, so the 20 blanks are a
// finding, not padding. They are NOT a claim about compliance -- psephos holds no
// compliance data, and the page says so under the grid.
const TINT: Record<Cell["status"], string> = {
  active: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  ended: "border-neutral-700 bg-neutral-800/60 text-neutral-400",
  none: "border-neutral-800/60 bg-transparent text-neutral-600",
};

export function StateCell({ cell }: { cell: Cell }) {
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-1">
        <span className="font-mono text-sm font-semibold tracking-wide">{cell.code}</span>
        <span className="flex items-center gap-1 text-xs leading-none">
          {/* Appeal and refile are different events and get different glyphs. */}
          {cell.chain === "appeal" && <span title="continued as a circuit appeal">↑</span>}
          {cell.chain === "refile" && <span title="refiled in another district">↻</span>}
          {cell.dormant && (
            <span
              title={`no docket activity in ${cell.quietDays} days`}
              className="text-amber-400"
            >
              ●
            </span>
          )}
        </span>
      </div>
      <div className="mt-1 truncate font-mono text-[11px] text-neutral-500">
        {cell.live?.docket_number ?? "—"}
      </div>
    </>
  );

  const className = `block rounded-md border px-2 py-1.5 ${TINT[cell.status]}`;

  // Only a cell with a docket links anywhere. An empty cell is inert by design --
  // there is no page behind "DOJ has not sued Ohio".
  if (!cell.live) {
    return (
      <div className={className} title={`${cell.name} — no DOJ suit in the record`}>
        {body}
      </div>
    );
  }
  return (
    <Link
      href={`/case/${cell.live.case_id}`}
      title={`${cell.name} — ${cell.live.court ?? ""} ${cell.live.docket_number ?? ""}`}
      className={`${className} transition-colors hover:border-neutral-500`}
    >
      {body}
    </Link>
  );
}
