import Link from "next/link";
import {
  STAGE_ORDER,
  STAGE_STYLE,
  STATUS_LABELS,
  stageEncoding,
  type Matrix,
  type StageCode,
} from "@/lib/statebill";

// The state x stage matrix. THIS IS THE PAGE: the list below it is a drill-down, and
// every count here is the link that opens it.
//
// It is also the page's key. The column headers carry the ramp dots, so the colour a
// row's tick uses is defined at the top of the same screen rather than in a legend
// somewhere else -- there is exactly one place a reader learns what violet means here.
//
// A ZERO IS NOT A LINK. It renders the mock's dim middot, so no link on the page can
// lead to an empty list, and the eye reads the occupied cells as the shape of the
// data rather than scanning a field of noughts.

// #list is where the drill-down renders. Jumping to it replicates the mock's
// scrollIntoView with no client JS -- the fragment is the whole mechanism.
function href(params: Record<string, string>): string {
  return `/state-bills?${new URLSearchParams(params).toString()}#list`;
}

const CELL = "block px-1.5 py-1.5 font-mono text-[0.82rem]";

// `stage` is the encoding this count claims to be; assert-encodings.mjs reads it and
// then checks the computed colour against what the key declares for that stage.
//
// THE TOTALS ROW PASSES NO STAGE, and the reason is paint rather than semantics. Its
// per-stage cells ARE stage-specific -- 338 introduced, 42 engrossed -- so calling them
// aggregates over the ramp would be wrong. What makes them not a stage claim is that
// they are painted a flat neutral for every column, deliberately, so the totals read as
// one row rather than a second copy of the ramp. Handing them a `data-stage` would
// assert #a3a3a3 against six different declared colours and fail all six, correctly:
// they are painted in the totals vocabulary, not the stage vocabulary. The `All` column
// and grand total are aggregates across stages and have no stage to claim either way.
//
// A ZERO IS MARKED `data-zero` RATHER THAN LEFT TO FALL THROUGH. The middot is frame
// furniture: it is not a stage, it is the absence of one, and it is self-decoding in a
// table of numbers. The board script's own rule is that exclusions are written down
// rather than implied by whatever the classifier happens not to match, so this one is
// an attribute the script excludes by name.
function Count({
  n,
  params,
  color,
  bold,
  stage,
}: {
  n: number;
  params: Record<string, string>;
  color: string;
  bold?: boolean;
  stage?: string;
}) {
  if (n === 0) {
    return (
      <span className={`${CELL} text-[#2e2e2e]`} aria-label="none" data-zero="">
        ·
      </span>
    );
  }
  return (
    <Link
      href={href(params)}
      className={`${CELL} hover:bg-neutral-900`}
      style={{ color, fontWeight: bold ? 600 : 400 }}
      data-stage={stage}
    >
      {n}
    </Link>
  );
}

// One column header: the dot, the label, and the ramp this stage DECLARES on all four
// surfaces. The script resolves these through the page rather than transcribing them,
// so `var(--leg-dim)` stays one value with one definition. `tick` is written "none" for
// Introduced rather than omitted -- a missing attribute and a deliberately absent rule
// look identical to a reader of the DOM, and only one of them is correct here.
function StageHeader({ code, className }: { code: StageCode; className: string }) {
  const style = STAGE_STYLE[code];
  return (
    <th
      className={className}
      scope="col"
      data-encoding={stageEncoding(code)}
      data-paint-dot={style.dot}
      data-paint-cell={style.cell}
      data-paint-tick={style.tick ?? "none"}
      data-paint-chip={style.chip}
    >
      <span
        className="mr-1 inline-block size-1.5 rounded-full align-[1px]"
        style={{ background: style.dot }}
      />
      {STATUS_LABELS[code]}
    </th>
  );
}

export function StateMatrix({ matrix }: { matrix: Matrix }) {
  const thRule =
    "px-1 py-1 text-[0.68rem] font-medium tracking-wider whitespace-nowrap text-neutral-500 uppercase";
  const th = `${thRule} text-right`;
  // TWO CONSTANTS, NOT ONE WITH AN OVERRIDE. `${td} text-left` does not left-align
  // anything: Tailwind emits text-left and text-right into the same layer at the same
  // specificity, so the winner is decided by their order in the generated stylesheet
  // and never by their order in the class attribute. text-right won, and the state
  // labels rendered hard against their numbers. The rule is the same one the map's
  // filter chain records -- an override that depends on emission order is not an
  // override -- so the label cell simply never receives the alignment it must beat.
  const tdRule = "border-t border-[#1c1c1c] p-0";
  const td = `${tdRule} text-right`;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse tabular-nums">
        {/* THE COLUMN HEADERS ARE THE KEY, so they are marked as one. There is exactly
            one `data-key` block on this page; assert-encodings.mjs asserts that count,
            because the board's lesson was a second key silently diverging from the
            first while both looked present. */}
        <thead data-key="">
          <tr>
            <th className={`${thRule} text-left`}>
              <span className="sr-only">State</span>
            </th>
            {STAGE_ORDER.map((code) => (
              <StageHeader key={code} code={code} className={th} />
            ))}
            {/* DECLARED, NOT CLAIMED. This header carries `data-unreachable` and
                deliberately NOT `data-encoding`: live data has never contained a bill
                outside stages 1-6, so the script cannot sample this column and must not
                pretend it did. The branch is pinned by StateMatrix.test.ts instead.
                Same shape as `data-unpainted` on the board's key. */}
            {matrix.hasUnstaged && (
              <th className={th} scope="col" data-unreachable="unstaged">
                <span
                  className="mr-1 inline-block size-1.5 rounded-full align-[1px]"
                  style={{ background: "#404040" }}
                />
                Unstaged
              </th>
            )}
            <th className={`${th} border-l border-neutral-800`} scope="col">
              All
            </th>
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.state}>
              <th scope="row" className={`${tdRule} text-left font-semibold`}>
                <Link
                  href={href({ state: row.state })}
                  className="block px-1.5 py-1.5 text-[0.85rem] hover:bg-neutral-900"
                >
                  {row.state}
                </Link>
              </th>
              {STAGE_ORDER.map((code, i) => (
                <td key={code} className={td}>
                  <Count
                    n={row.cells[i]}
                    params={{ state: row.state, status: code }}
                    color={STAGE_STYLE[code].cell}
                    bold={STAGE_STYLE[code].bold}
                    stage={stageEncoding(code)}
                  />
                </td>
              ))}
              {matrix.hasUnstaged && (
                <td className={td}>
                  {/* No status param exists that selects these -- the count is a
                      disclosure, not a filter, so it stays unlinked at any value. */}
                  <span
                    className={CELL}
                    style={{ color: row.unstaged ? "#a3a3a3" : "#2e2e2e" }}
                  >
                    {row.unstaged || "·"}
                  </span>
                </td>
              )}
              <td className={`${td} border-l border-neutral-800`}>
                <Count
                  n={row.total}
                  params={{ state: row.state }}
                  color="#d4d4d4"
                />
              </td>
            </tr>
          ))}
          <tr>
            <th
              scope="row"
              className="border-t border-neutral-800 p-0 text-left text-[0.8rem] font-medium"
            >
              <Link
                href={href({ all: "1" })}
                className="block px-1.5 py-1.5 text-neutral-500 hover:bg-neutral-900"
              >
                All states
              </Link>
            </th>
            {STAGE_ORDER.map((code, i) => (
              <td key={code} className="border-t border-neutral-800 p-0 text-right">
                <Count
                  n={matrix.stageTotals[i]}
                  params={{ status: code }}
                  color="#a3a3a3"
                />
              </td>
            ))}
            {matrix.hasUnstaged && (
              <td className="border-t border-neutral-800 p-0 text-right">
                <span className={`${CELL} text-neutral-400`}>{matrix.unstagedTotal}</span>
              </td>
            )}
            <td className="border-t border-l border-neutral-800 p-0 text-right">
              <Count n={matrix.total} params={{ all: "1" }} color="#d4d4d4" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
