import Link from "next/link";
import type { Cell } from "@/lib/campaign";
import type { SectionKey } from "@/lib/movement";

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
  live: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  ended: "border-neutral-700 bg-neutral-800/60 text-neutral-400",
  none: "border-neutral-800/60 bg-transparent text-neutral-600",
};

export function StateCell({
  cell,
  section,
}: {
  cell: Cell;
  section?: SectionKey | null;
}) {
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
          {/* A third marker, against this file's own "two markers" rule, and the
              exception is argued rather than assumed: the grid is the surface where
              the failure actually showed. With this cell reading `active` and its
              terminated docket rendered nowhere, a reader who scans only the grid
              sees a state whose dismissal has vanished. Like ● and unlike a badge,
              it is exceptional -- it marks a link psephos owes, so the healthy grid
              carries none at all. */}
          {cell.unlinked.length > 0 && (
            <span
              title={`${cell.unlinked.length} ended docket(s) here with no link asserted to the live one`}
              className="text-neutral-400"
            >
              †
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

  // A CELL IN NO SECTION KEEPS ITS DOCKET LINK, which the mock does not do. Nine sued
  // jurisdictions are simply live -- not continued, unlinked, ended or quiet -- and the
  // mock's cells for them carry a click handler that looks up an undefined key and
  // silently returns, so they render as links and do nothing. A dead affordance is
  // worse than none. The docket is a real destination and stays the fallback.
  const href = section
    ? `/campaign?section=${section}&state=${cell.code}#section`
    : `/case/${cell.live.case_id}`;
  const title = section
    ? `${cell.name} — open its row below`
    : `${cell.name} — ${cell.live.court ?? ""} ${cell.live.docket_number ?? ""}`;

  return (
    <Link
      href={href}
      title={title}
      className={`${className} transition-colors hover:border-neutral-500`}
    >
      {body}
    </Link>
  );
}
