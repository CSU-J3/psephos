import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StateBill } from "@/lib/db";
import { StateMatrix } from "@/components/StateMatrix";
import { buildMatrix } from "@/lib/statebill";

// THE ONE COMPONENT IN THIS APP WHOSE CORRECTNESS IS NOT VISIBLE ON THE PAGE.
//
// vitest.config.ts declines component rendering on the grounds that the read layer's
// components are thin and what they do is visible at the render. That reasoning holds
// everywhere except here. The matrix's seventh column draws only when a bill carries a
// stage code the ramp does not know, and live data has never contained one -- 484 rows,
// every status in 1-6 -- so the branch is dead code that first executes in production,
// on the day something upstream changes, with nobody watching. "Visible on the page"
// is exactly what it is not.
//
// So the exception is narrow and argued rather than a general loosening: render the
// branch that live data cannot reach. No jsdom and no testing library -- renderToStaticMarkup
// is in react-dom, which is already a dependency, and static markup is all an
// assertion about which columns exist needs.

function bill(over: Partial<StateBill> & Pick<StateBill, "state_bill_id" | "state">): StateBill {
  return {
    bill_number: "HB1",
    session: "2025",
    title: `bill ${over.state_bill_id}`,
    description: null,
    status: "1",
    url: null,
    is_vehicle: 0,
    last_action: "Referred to Elections",
    last_action_at: "2025-03-10",
    ...over,
  };
}

const render = (bills: StateBill[]) =>
  renderToStaticMarkup(createElement(StateMatrix, { matrix: buildMatrix(bills) }));

// The markup a single state's row emits, sliced out by its label link.
function rowMarkup(html: string, state: string): string {
  const rows = html.split("<tr");
  const row = rows.find((r) => r.includes(`>${state}</a>`));
  if (!row) throw new Error(`no row for ${state} in rendered matrix`);
  return row;
}

// Every number the row actually PAINTED, in column order. Zero cells render a middot
// rather than a "0", so they contribute nothing here -- which is the point: this reads
// what a person would read off the screen, not what the model holds.
function numbersIn(row: string): number[] {
  return [...row.matchAll(/>(\d+)</g)].map((m) => Number(m[1]));
}

const CLEAN = [
  bill({ state_bill_id: "1", state: "TX", status: "4" }),
  bill({ state_bill_id: "2", state: "TX", status: "4" }),
  bill({ state_bill_id: "3", state: "TX", status: "1" }),
  bill({ state_bill_id: "4", state: "WI", status: "6" }),
];

describe("StateMatrix — the unstaged column", () => {
  it("draws no seventh column while every bill carries a known stage", () => {
    const html = render(CLEAN);
    expect(html).not.toContain("Unstaged");
    // Six stage headers plus All, and nothing else.
    expect(html).toContain("Introduced");
    expect(html).toContain("Failed");
  });

  it("draws the seventh column as soon as one bill carries an unknown stage code", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: "9" })]);
    expect(html).toContain("Unstaged");
  });

  it("draws it for a null status too, not only an unrecognised code", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: null })]);
    expect(html).toContain("Unstaged");
  });

  // THE ASSERTION THE COLUMN EXISTS FOR. Without it the unknown bill either vanishes
  // from the page or inflates the row total past the sum of its own cells, and both
  // read as clean data. This checks the RENDERED numbers, so it fails if the column is
  // computed correctly and then not drawn.
  it("keeps a row's total equal to the sum of the cells it painted", () => {
    const html = render([
      ...CLEAN,
      bill({ state_bill_id: "5", state: "TX", status: "9" }),
      bill({ state_bill_id: "6", state: "TX", status: null }),
    ]);
    const painted = numbersIn(rowMarkup(html, "TX"));
    const total = painted[painted.length - 1];
    const cells = painted.slice(0, -1);
    expect(total).toBe(5); // 3 clean TX bills + the two unstaged
    expect(cells.reduce((a, b) => a + b, 0)).toBe(total);
    expect(cells).toContain(2); // the unstaged pair, drawn rather than swallowed
  });

  it("holds the same arithmetic on the totals row", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: "9" })]);
    const painted = numbersIn(rowMarkup(html, "All states"));
    const total = painted[painted.length - 1];
    expect(total).toBe(5);
    expect(painted.slice(0, -1).reduce((a, b) => a + b, 0)).toBe(total);
  });

  it("still balances every row when the unknown code is the only thing a state has", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "AZ", status: "unknown" })]);
    for (const state of ["AZ", "TX", "WI"]) {
      const painted = numbersIn(rowMarkup(html, state));
      const total = painted[painted.length - 1];
      expect(painted.slice(0, -1).reduce((a, b) => a + b, 0)).toBe(total);
    }
  });
});
