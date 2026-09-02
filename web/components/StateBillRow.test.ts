import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StateBill } from "@/lib/db";
import { StateBillRow } from "@/components/StateBillRow";
import { STAGE_STYLE } from "@/lib/statebill";

// THE SECOND BRANCH LIVE DATA CANNOT REACH, and until this file existed it was pinned by
// nothing at all -- docs/status.md carried it as a stated gap while the matrix's unstaged
// column next to it had a test. `is_vehicle` is 0 across all 484 rows, so the amber badge
// draws on no page anyone can visit, and assert-encodings.mjs says so explicitly rather
// than certifying a set it never reached. That leaves exactly one place the branch can be
// exercised: a render with a fixture that live data does not supply.
//
// It matters more than an unused branch usually would. 5b-b -- state-level vehicle
// detection -- is CLOSED as a free-tier limitation, not abandoned: LegiScan's `sasts`
// relations express companionship rather than substitution, so nothing currently sets the
// flag. If that ever changes, the first bill to carry it is by definition the most
// important row on the page, and the badge will draw for the first time in production on
// exactly that row. A branch whose debut is its most consequential appearance is the one
// worth pinning.
//
// Same idiom as StateMatrix.test.ts: renderToStaticMarkup, no jsdom, no testing library.
// react-dom is already a dependency and markup is all these assertions need.
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

const render = (b: StateBill) => renderToStaticMarkup(createElement(StateBillRow, { bill: b }));

describe("StateBillRow — the Vehicle badge", () => {
  it("paints nothing on an ordinary bill", () => {
    const html = render(bill({ state_bill_id: "1", state: "TX" }));
    expect(html).not.toContain("Vehicle");
    expect(html).not.toContain("amber");
  });

  it("paints the badge when is_vehicle is 1", () => {
    const html = render(bill({ state_bill_id: "1", state: "TX", is_vehicle: 1 }));
    expect(html).toContain("Vehicle");
  });

  // THE POINT OF THE BADGE IS THAT IT IS NOT ON THE RAMP. The component's own comment
  // says a state vehicle is the one thing on this page that deserves to interrupt the
  // stage ramp; amber is how it does that, against a page painted in violet and greys.
  // A badge restyled into the ramp would still say "Vehicle" and would no longer
  // interrupt anything, so the colour is asserted rather than just the word.
  it("paints it amber, outside the violet-and-grey ramp", () => {
    const html = render(bill({ state_bill_id: "1", state: "TX", is_vehicle: 1 }));
    expect(html).toMatch(/amber-\d{3}/);
    for (const stage of Object.values(STAGE_STYLE)) {
      // No ramp colour may appear on the badge's own element.
      const badge = /<span[^>]*amber[^>]*>[\s\S]*?<\/span>/.exec(html)?.[0] ?? "";
      expect(badge).not.toContain(stage.cell);
    }
  });

  // The badge ADDS to the row; it does not stand in for the stage. A vehicle is still at
  // a stage, and a reader who loses that has lost the more useful of the two facts.
  it("coexists with the stage chip rather than replacing it", () => {
    const html = render(
      bill({ state_bill_id: "1", state: "TX", is_vehicle: 1, status: "4" }),
    );
    expect(html).toContain("Vehicle");
    expect(html).toContain("Passed");
    expect(html).toContain("data-chip");
  });

  it("draws on any stage, not only the moving ones", () => {
    for (const status of ["1", "2", "3", "4", "5", "6"]) {
      const html = render(bill({ state_bill_id: "1", state: "TX", is_vehicle: 1, status }));
      expect(html).toContain("Vehicle");
    }
  });

  // is_vehicle is `number` in the row type, and the collector writes 0 or 1. Anything
  // else is upstream drift; the row must not paint a badge on a value it does not
  // recognise, which is the same rule stageOf applies to an unknown status code.
  it("draws nothing for a value that is neither 0 nor 1", () => {
    for (const v of [2, -1]) {
      const html = render(bill({ state_bill_id: "1", state: "TX", is_vehicle: v }));
      expect(html).not.toContain("Vehicle");
    }
  });
});
