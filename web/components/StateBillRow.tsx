import Link from "next/link";
import type { StateBill } from "@/lib/db";
import { formatDate } from "@/lib/format";
import {
  STAGE_STYLE,
  stageEncoding,
  stageOf,
  stateBillLabel,
  stateBillStatus,
} from "@/lib/statebill";

// One state election bill with its latest action, as a hairline row rather than a
// card. The card version cost ~110px each and the page renders these in runs of 198
// (Texas); at that length the border, the background and the padding stop separating
// rows and just add scroll. A 1px rule and a 2px stage tick separate them for less
// than half the height.
//
// THE TICK IS THE ONLY COLOUR ON THE ROW, and it carries the stage -- the same ramp
// the matrix column headers key. Failed rows dim their title to neutral-500 at normal
// weight; Vetoed keeps full weight, because a veto is an act and a session ending is
// not (see STAGE_STYLE).
//
// The amber Vehicle badge stays wired for 5b-b. Nothing is flagged today -- is_vehicle
// is 0 across all 484 rows -- and it is kept because the column exists and a state
// vehicle is the one thing on this page that would deserve to interrupt the ramp.
// BECAUSE it is unpaintable on live data, assert-encodings.mjs cannot sample it and
// says so rather than certifying a set it never reached. Unlike the matrix's unstaged
// column, this branch is pinned by no test at all -- a stated gap, not a covered one.
// No sponsor field: state bills carry none.
//
// TWO ATTRIBUTES EXIST FOR THE ENCODINGS JOIN, and they are not decoration. `data-stage`
// on the link names the stage this row CLAIMS -- the link's own border-left-color is the
// tick -- and `data-chip` marks the stage name beside the title. The script reads the
// claim, then checks the paint against what the key declares for that stage, which is
// the only way to catch a row that says Passed and is painted like something else.
// Colour alone cannot do it: stages 2 and 3 are painted identically.
export function StateBillRow({ bill }: { bill: StateBill }) {
  const stage = stageOf(bill);
  const style = stage ? STAGE_STYLE[stage] : null;
  const status = stateBillStatus(bill.status);
  const failed = stage === "6";

  return (
    <li>
      <Link
        href={`/state-bill/${bill.state_bill_id}`}
        className="block border-b border-[#1c1c1c] border-l-2 py-2 pr-3 pl-3.5 transition-colors hover:bg-neutral-900"
        style={{ borderLeftColor: style?.tick ?? "transparent" }}
        data-stage={stage ? stageEncoding(stage) : "unstaged"}
      >
        <div className="flex items-baseline gap-2.5">
          <span className="shrink-0 font-mono text-[0.8rem] whitespace-nowrap text-neutral-500">
            {stateBillLabel(bill)}
          </span>
          <span
            className={`line-clamp-2 min-w-0 flex-1 text-[0.9rem] ${
              failed ? "font-normal text-neutral-500" : "font-medium"
            }`}
          >
            {bill.title ?? bill.state_bill_id}
          </span>
          {bill.is_vehicle === 1 && (
            <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-[0.68rem] font-semibold tracking-wide text-amber-400 uppercase">
              Vehicle
            </span>
          )}
          {status && (
            <span
              className="shrink-0 text-[0.72rem] whitespace-nowrap"
              style={{ color: style?.chip ?? "#737373", fontWeight: style?.bold ? 600 : 400 }}
              data-chip=""
            >
              {status}
            </span>
          )}
        </div>
        {bill.last_action && (
          <p className="mt-1 truncate text-[0.8rem] text-neutral-400">
            <span className="tabular-nums text-neutral-600">
              {formatDate(bill.last_action_at)}
            </span>
            {" — "}
            {bill.last_action}
          </p>
        )}
      </Link>
    </li>
  );
}
