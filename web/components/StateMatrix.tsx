import Link from "next/link";
import { STAGE_ORDER, STAGE_STYLE, STATUS_LABELS, type Matrix } from "@/lib/statebill";

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

function Count({
  n,
  params,
  color,
  bold,
}: {
  n: number;
  params: Record<string, string>;
  color: string;
  bold?: boolean;
}) {
  if (n === 0) {
    return (
      <span className={`${CELL} text-[#2e2e2e]`} aria-label="none">
        ·
      </span>
    );
  }
  return (
    <Link
      href={href(params)}
      className={`${CELL} hover:bg-neutral-900`}
      style={{ color, fontWeight: bold ? 600 : 400 }}
    >
      {n}
    </Link>
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
        <thead>
          <tr>
            <th className={`${thRule} text-left`}>
              <span className="sr-only">State</span>
            </th>
            {STAGE_ORDER.map((code) => (
              <th key={code} className={th} scope="col">
                <span
                  className="mr-1 inline-block size-1.5 rounded-full align-[1px]"
                  style={{ background: STAGE_STYLE[code].dot }}
                />
                {STATUS_LABELS[code]}
              </th>
            ))}
            {matrix.hasUnstaged && (
              <th className={th} scope="col">
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
                <Count n={matrix.stageTotals[i]} params={{ status: code }} color="#a3a3a3" />
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
