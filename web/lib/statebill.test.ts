import { describe, it, expect } from "vitest";
import type { StateBill } from "@/lib/db";
import {
  STAGE_ORDER,
  buildMatrix,
  filterStateBills,
  groupByState,
  latestMovement,
  listTitle,
  parseStateBillParams,
  sortByRecent,
  stageOf,
} from "@/lib/statebill";

// Fixtures are CONSTRUCTED, never read from production -- the same rule campaign.test.ts
// states and for the same reason. The live shape of this page moves every cron: the state
// bill dimension went 179 -> 455 -> 484 inside two months, so a suite seeded from a
// snapshot starts failing on healthy data and teaches itself to be ignored. Every row
// below is shaped like the real thing and owned by the test.
//
// The one production fact worth pinning is a RATIO the mock and the live snapshot agree
// on: Wisconsin holds 3 vetoed against 56 failed, which is why the ramp separates those
// two stages. That is asserted as a design property of STAGE_STYLE, not as a count.
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

describe("stageOf", () => {
  it("maps the six LegiScan codes and nothing else", () => {
    for (const code of STAGE_ORDER) {
      expect(stageOf({ status: code })).toBe(code);
    }
    expect(stageOf({ status: null })).toBeNull();
    expect(stageOf({ status: "" })).toBeNull();
    expect(stageOf({ status: "7" })).toBeNull(); // a code LegiScan might add
    expect(stageOf({ status: "Passed" })).toBeNull(); // a label, not a code
  });
});

describe("buildMatrix", () => {
  const bills = [
    bill({ state_bill_id: "1", state: "TX", status: "4" }),
    bill({ state_bill_id: "2", state: "TX", status: "4" }),
    bill({ state_bill_id: "3", state: "TX", status: "1" }),
    bill({ state_bill_id: "4", state: "WI", status: "6" }),
    bill({ state_bill_id: "5", state: "WI", status: "5" }),
    bill({ state_bill_id: "6", state: "AZ", status: "2" }),
  ];

  it("counts each state x stage cell", () => {
    const m = buildMatrix(bills);
    const tx = m.rows.find((r) => r.state === "TX")!;
    // index 3 is stage "4" (Passed) -- STAGE_ORDER is 1..6, zero-based
    expect(tx.cells[STAGE_ORDER.indexOf("4")]).toBe(2);
    expect(tx.cells[STAGE_ORDER.indexOf("1")]).toBe(1);
    expect(tx.cells[STAGE_ORDER.indexOf("6")]).toBe(0);

    const wi = m.rows.find((r) => r.state === "WI")!;
    expect(wi.cells).toEqual([0, 0, 0, 0, 1, 1]);
  });

  it("orders rows alphabetically by state", () => {
    expect(buildMatrix(bills).rows.map((r) => r.state)).toEqual(["AZ", "TX", "WI"]);
  });

  it("carries row totals, column totals and a grand total", () => {
    const m = buildMatrix(bills);
    expect(m.rows.map((r) => r.total)).toEqual([1, 3, 2]);
    // stages 1..6: one Introduced, one Engrossed, two Passed, one Vetoed, one Failed
    expect(m.stageTotals).toEqual([1, 1, 0, 2, 1, 1]);
    expect(m.total).toBe(6);
  });

  it("hides the unstaged column on clean data", () => {
    const m = buildMatrix(bills);
    expect(m.hasUnstaged).toBe(false);
    expect(m.unstagedTotal).toBe(0);
  });

  it("holds a null or unknown status in unstaged rather than dropping the bill", () => {
    const m = buildMatrix([
      ...bills,
      bill({ state_bill_id: "7", state: "TX", status: null }),
      bill({ state_bill_id: "8", state: "TX", status: "9" }),
    ]);
    expect(m.hasUnstaged).toBe(true);
    expect(m.unstagedTotal).toBe(2);
    const tx = m.rows.find((r) => r.state === "TX")!;
    expect(tx.unstaged).toBe(2);
    expect(tx.total).toBe(5);
    expect(m.total).toBe(8);
  });

  // The reason unstaged exists at all: a bill the ramp does not recognise must still be
  // counted somewhere the reader can see, or the page's totals quietly stop adding up.
  it("keeps cells + unstaged == total on every row and on the margins", () => {
    const m = buildMatrix([
      ...bills,
      bill({ state_bill_id: "7", state: "TX", status: null }),
      bill({ state_bill_id: "8", state: "WI", status: "x" }),
    ]);
    for (const row of m.rows) {
      const sum = row.cells.reduce((a, b) => a + b, 0) + row.unstaged;
      expect(sum).toBe(row.total);
    }
    const marginSum = m.stageTotals.reduce((a, b) => a + b, 0) + m.unstagedTotal;
    expect(marginSum).toBe(m.total);
    expect(m.rows.reduce((a, r) => a + r.total, 0)).toBe(m.total);
  });

  it("is empty, not broken, on no bills", () => {
    const m = buildMatrix([]);
    expect(m.rows).toEqual([]);
    expect(m.total).toBe(0);
    expect(m.stageTotals).toEqual([0, 0, 0, 0, 0, 0]);
    expect(m.hasUnstaged).toBe(false);
  });
});

describe("sortByRecent / latestMovement", () => {
  it("puts the most recent last action first", () => {
    const rows = sortByRecent([
      bill({ state_bill_id: "a", state: "TX", last_action_at: "2025-01-05" }),
      bill({ state_bill_id: "b", state: "TX", last_action_at: "2026-08-30" }),
      bill({ state_bill_id: "c", state: "TX", last_action_at: "2025-06-11" }),
    ]);
    expect(rows.map((b) => b.state_bill_id)).toEqual(["b", "c", "a"]);
  });

  it("breaks a same-day tie on state then bill number, deterministically", () => {
    const same = "2026-08-30";
    const rows = sortByRecent([
      bill({ state_bill_id: "3", state: "TX", bill_number: "HB9", last_action_at: same }),
      bill({ state_bill_id: "1", state: "AZ", bill_number: "SB2", last_action_at: same }),
      bill({ state_bill_id: "2", state: "TX", bill_number: "HB1", last_action_at: same }),
    ]);
    expect(rows.map((b) => b.state_bill_id)).toEqual(["1", "2", "3"]);
  });

  it("sorts a missing date last rather than first", () => {
    const rows = sortByRecent([
      bill({ state_bill_id: "none", state: "TX", last_action_at: null }),
      bill({ state_bill_id: "dated", state: "TX", last_action_at: "2025-01-01" }),
    ]);
    expect(rows.map((b) => b.state_bill_id)).toEqual(["dated", "none"]);
  });

  // Naive timestamps and bare dates both appear on this column; comparing the strings
  // keeps them comparable without normalising either, and never shifts a calendar day.
  it("compares strings, so a naive timestamp orders against a bare date", () => {
    const rows = sortByRecent([
      bill({ state_bill_id: "date", state: "TX", last_action_at: "2026-08-30" }),
      bill({ state_bill_id: "stamp", state: "TX", last_action_at: "2026-08-30T14:02:00" }),
    ]);
    expect(rows.map((b) => b.state_bill_id)).toEqual(["stamp", "date"]);
  });

  it("does not mutate its input", () => {
    const input = [
      bill({ state_bill_id: "a", state: "TX", last_action_at: "2025-01-01" }),
      bill({ state_bill_id: "b", state: "TX", last_action_at: "2026-01-01" }),
    ];
    sortByRecent(input);
    expect(input.map((b) => b.state_bill_id)).toEqual(["a", "b"]);
  });

  it("takes ten by default and stops short when there are fewer", () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      bill({
        state_bill_id: String(i),
        state: "TX",
        // descending dates, so id 24 is the newest
        last_action_at: `2026-08-${String(i + 1).padStart(2, "0")}`,
      }),
    );
    const top = latestMovement(many);
    expect(top).toHaveLength(10);
    expect(top[0].state_bill_id).toBe("24");
    expect(top[9].state_bill_id).toBe("15");
    expect(latestMovement(many.slice(0, 3))).toHaveLength(3);
    expect(latestMovement(many, 2).map((b) => b.state_bill_id)).toEqual(["24", "23"]);
  });
});

describe("filterStateBills", () => {
  const bills = [
    bill({ state_bill_id: "1", state: "TX", status: "4" }),
    bill({ state_bill_id: "2", state: "TX", status: "1" }),
    bill({ state_bill_id: "3", state: "WI", status: "4" }),
  ];

  it("returns everything with no filter", () => {
    expect(filterStateBills(bills, {})).toHaveLength(3);
    expect(filterStateBills(bills, { state: null, status: null })).toHaveLength(3);
  });

  it("filters on state alone", () => {
    expect(filterStateBills(bills, { state: "TX" }).map((b) => b.state_bill_id)).toEqual([
      "1",
      "2",
    ]);
  });

  it("filters on status alone", () => {
    expect(filterStateBills(bills, { status: "4" }).map((b) => b.state_bill_id)).toEqual([
      "1",
      "3",
    ]);
  });

  it("intersects the two", () => {
    expect(
      filterStateBills(bills, { state: "TX", status: "4" }).map((b) => b.state_bill_id),
    ).toEqual(["1"]);
  });

  it("returns nothing for a code no bill carries, rather than everything", () => {
    expect(filterStateBills(bills, { status: "9" })).toEqual([]);
    expect(filterStateBills(bills, { state: "ZZ" })).toEqual([]);
  });
});

describe("groupByState", () => {
  it("orders groups alphabetically and bills recent-first inside each", () => {
    const groups = groupByState([
      bill({ state_bill_id: "1", state: "TX", last_action_at: "2025-01-01" }),
      bill({ state_bill_id: "2", state: "AZ", last_action_at: "2025-05-05" }),
      bill({ state_bill_id: "3", state: "TX", last_action_at: "2026-02-02" }),
    ]);
    expect(groups.map((g) => g.state)).toEqual(["AZ", "TX"]);
    expect(groups[1].bills.map((b) => b.state_bill_id)).toEqual(["3", "1"]);
    expect(groups.reduce((a, g) => a + g.bills.length, 0)).toBe(3);
  });

  it("is empty on no bills", () => {
    expect(groupByState([])).toEqual([]);
  });
});

describe("parseStateBillParams", () => {
  it("renders no list on the bare page", () => {
    expect(parseStateBillParams({})).toEqual({
      state: null,
      status: null,
      sort: "recent",
      listing: false,
    });
  });

  // ?all=1 is the ONLY thing separating "browse all" from the bare page: neither has a
  // state or a status, and only one of them should render every bill.
  it("opens the full list on ?all=1 without setting a filter", () => {
    const p = parseStateBillParams({ all: "1" });
    expect(p.listing).toBe(true);
    expect(p.state).toBeNull();
    expect(p.status).toBeNull();
  });

  it("opens the list on a state or a status alone", () => {
    expect(parseStateBillParams({ state: "TX" }).listing).toBe(true);
    expect(parseStateBillParams({ status: "4" }).listing).toBe(true);
  });

  it("upper-cases the state so a hand-typed URL still matches", () => {
    expect(parseStateBillParams({ state: "tx" }).state).toBe("TX");
  });

  it("defaults sort to recent and takes only the one alternative", () => {
    expect(parseStateBillParams({ all: "1" }).sort).toBe("recent");
    expect(parseStateBillParams({ all: "1", sort: "state" }).sort).toBe("state");
    expect(parseStateBillParams({ all: "1", sort: "sideways" }).sort).toBe("recent");
  });

  it("treats an empty value as absent", () => {
    expect(parseStateBillParams({ state: "", status: "", all: "" }).listing).toBe(false);
  });

  it("takes the first of a repeated param", () => {
    expect(parseStateBillParams({ state: ["TX", "WI"] }).state).toBe("TX");
  });

  it("passes an unknown code through rather than silently dropping the filter", () => {
    expect(parseStateBillParams({ status: "9" }).status).toBe("9");
  });
});

describe("listTitle", () => {
  it("names the unfiltered list", () => {
    expect(listTitle({})).toBe("All states");
  });

  it("names a state, a stage, and both", () => {
    expect(listTitle({ state: "TX" })).toBe("TX");
    expect(listTitle({ status: "4" })).toBe("All states · passed");
    expect(listTitle({ state: "TX", status: "6" })).toBe("TX · failed");
  });

  it("shows an unmapped code rather than hiding it", () => {
    expect(listTitle({ state: "TX", status: "9" })).toBe("TX · 9");
  });
});
