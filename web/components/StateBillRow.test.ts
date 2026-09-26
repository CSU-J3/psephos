import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StateBill } from "@/lib/db";
import { StateBillRow } from "@/components/StateBillRow";
import { STAGE_STYLE, UNSTAGED_LABEL, UNSTAGED_STYLE } from "@/lib/statebill";

// THE BRANCH LIVE DATA CANNOT REACH, and until this file existed it was pinned by nothing
// at all -- docs/status.md carried it as a stated gap while the matrix's unstaged column
// next to it had a test. `is_vehicle` is 0 on every row, so the amber badge draws on no
// page anyone can visit, and assert-encodings.mjs says so explicitly rather than
// certifying a set it never reached. That leaves exactly one place the branch can be
// exercised: a render with a fixture that live data does not supply.
//
// It used to be the second such branch. The first, a row with no stage, was reached on
// 2026-09-25 (PA HR632, state run 36131273689) and is now keyed; its tests are at the
// foot of this file.
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

// A far clock: nothing in these fixtures is dated ahead; the rule has its own tests.
const FAR_CLOCK = "2100-01-01T00:00:00+00:00";
const render = (b: StateBill) =>
  renderToStaticMarkup(createElement(StateBillRow, { bill: b, clock: FAR_CLOCK }));

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

// A ROW WITH NO STAGE. PA HR632 is the live case: status, last_action and last_action_at
// all NULL. Before it was keyed, such a row claimed `unstaged` and painted no chip at
// all, so the one mark it carried was one the key had no entry for.
describe("StateBillRow — a status-less row", () => {
  const hr632 = () =>
    render(bill({ state_bill_id: "2159038", state: "PA", status: null, last_action: null, last_action_at: null }));

  it("claims the unstaged encoding", () => {
    expect(hr632()).toContain('data-stage="unstaged"');
  });

  it("paints a chip saying what the record holds, in the key's declared chip grey", () => {
    const chip = /<span[^>]*data-chip=""[^>]*>([^<]*)<\/span>/.exec(hr632());
    expect(chip?.[1]).toBe(UNSTAGED_LABEL);
    expect(chip?.[0]).toContain(`color:${UNSTAGED_STYLE.chip}`);
  });

  // RULED 2026-09-26. With no tick and Introduced's chip grey the row carried exactly
  // Introduced's paint; the dashed rule is what separates them, in the key's one grey.
  it("paints a dashed tick in the key's grey, the one thing Introduced does not draw", () => {
    expect(UNSTAGED_STYLE.tick).toBe(UNSTAGED_STYLE.dot);
    expect(hr632()).toContain(`border-left-color:${UNSTAGED_STYLE.tick}`);
    expect(hr632()).toContain("border-left-style:dashed");
    const introduced = render(bill({ state_bill_id: "1", state: "TX", status: "1" }));
    expect(introduced).toContain("border-left-color:transparent");
    expect(introduced).not.toContain("dashed");
  });

  it("draws the dashed rule for an unmapped code too, and never on a staged row", () => {
    expect(render(bill({ state_bill_id: "1", state: "TX", status: "9" }))).toContain("border-left-style:dashed");
    for (const status of ["1", "2", "3", "4", "5", "6"]) {
      expect(render(bill({ state_bill_id: "1", state: "TX", status }))).not.toContain("dashed");
    }
  });

  // An unmapped code is off the ramp too, but it IS a status: the chip shows it raw
  // rather than saying there is none.
  it("shows an unmapped code raw on the chip, still claiming unstaged", () => {
    const html = render(bill({ state_bill_id: "1", state: "TX", status: "9" }));
    expect(html).toContain('data-stage="unstaged"');
    expect(/<span[^>]*data-chip=""[^>]*>([^<]*)<\/span>/.exec(html)?.[1]).toBe("9");
  });
});
