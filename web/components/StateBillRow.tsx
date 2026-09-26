import Link from "next/link";
import type { StateBill } from "@/lib/db";
import { RecordDate } from "@/components/RecordDate";
import type { RecordClock } from "@/lib/dated";
import {
  STAGE_STYLE,
  UNSTAGED_ENCODING,
  UNSTAGED_LABEL,
  UNSTAGED_STYLE,
  UNSTAGED_TICK_STYLE,
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
// is 0 on every row -- and it is kept because the column exists and a state vehicle is
// the one thing on this page that would deserve to interrupt the ramp. BECAUSE it is
// unpaintable on live data, assert-encodings.mjs cannot sample it and says so rather
// than certifying a set it never reached; StateBillRow.test.ts pins it instead (since
// 82487df).
//
// A ROW OFF THE RAMP -- no status, or a code the ramp does not know -- claims the
// `unstaged` encoding, paints a DASHED tick in the key's grey, and carries a chip in the
// same grey: the raw code if there is one, and "No status" if LegiScan has given none.
// That branch was declared unreachable and was reached on 2026-09-25 (PA HR632, state run
// 36131273689). Until it was keyed, a null-status row painted no chip at all, which the
// key had no entry to explain. The tick is dashed because Introduced paints no tick and
// the same chip grey: without it the two rows carried identical paint (ruled 2026-09-26).
// No sponsor field: state bills carry none.
//
// TWO ATTRIBUTES EXIST FOR THE ENCODINGS JOIN, and they are not decoration. `data-stage`
// on the link names the stage this row CLAIMS -- the link's own border-left-color is the
// tick -- and `data-chip` marks the stage name beside the title. The script reads the
// claim, then checks the paint against what the key declares for that stage, which is
// the only way to catch a row that says Passed and is painted like something else.
// Colour alone cannot do it: stages 2 and 3 are painted identically.
export function StateBillRow({ bill, clock }: { bill: StateBill; clock: RecordClock }) {
  const stage = stageOf(bill);
  const style = stage ? STAGE_STYLE[stage] : UNSTAGED_STYLE;
  const status = stateBillStatus(bill.status) ?? UNSTAGED_LABEL;
  const failed = stage === "6";

  return (
    <li>
      <Link
        href={`/state-bill/${bill.state_bill_id}`}
        className="block border-b border-[#1c1c1c] border-l-2 py-2 pr-3 pl-3.5 transition-colors hover:bg-neutral-900"
        style={{
          borderLeftColor: style.tick ?? "transparent",
          ...(stage ? {} : { borderLeftStyle: UNSTAGED_TICK_STYLE }),
        }}
        data-stage={stage ? stageEncoding(stage) : UNSTAGED_ENCODING}
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
          <span
            className="shrink-0 text-[0.72rem] whitespace-nowrap"
            style={{ color: style.chip, fontWeight: style.bold ? 600 : 400 }}
            data-chip=""
          >
            {status}
          </span>
        </div>
        {bill.last_action && (
          <p className="mt-1 truncate text-[0.8rem] text-neutral-400">
            <span className="tabular-nums text-neutral-600">
              <RecordDate value={bill.last_action_at} clock={clock} />
            </span>
            {" — "}
            {bill.last_action}
          </p>
        )}
      </Link>
    </li>
  );
}
