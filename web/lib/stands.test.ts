import { describe, it, expect } from "vitest";
import type { CampaignRow, Bill, StateBill } from "@/lib/db";
import {
  docketTotals,
  openSplit,
  stateOutcomes,
  wisconsinOutcomes,
  monthsSince,
  saveStallMonths,
  vehicleQuietSince,
  SAVE_SENATE_COMPANION,
} from "@/lib/stands";

// Fixtures are CONSTRUCTED, on the same rule campaign.test.ts states: a membership
// read from production goes stale by build time and teaches the suite to be ignored.
// Every row below is shaped like the real thing and owned by the test.
//
// The one exception is deliberate and narrow -- the LEDGER block at the foot of this
// file builds a fixture whose SHAPE reproduces the 2026-09-07 reading (52 dockets,
// 29 district, 23 circuit, 31 open = 9 + 22). It pins the arithmetic, not the record:
// the numbers are constructed from counted rows here, so live drift cannot fail it.

function caseRow(
  over: Partial<CampaignRow> & Pick<CampaignRow, "case_id">,
): CampaignRow {
  return {
    state: "Testland",
    caption: `case ${over.case_id}`,
    court: "District of Test",
    docket_number: "1:25-cv-00001",
    status: "pending",
    filed_at: "2025-12-01T00:00:00",
    latest_entry_at: "2026-08-10T00:00:00",
    status_checked_at: "2026-08-14T00:59:00+00:00",
    superseded_by: null,
    source_url: null,
    entry_count: 0,
    ...over,
  };
}

function bill(over: Partial<Bill> & Pick<Bill, "bill_id">): Bill {
  return {
    bill_type: "s",
    number: 1,
    congress: 119,
    short_title: null,
    title: null,
    sponsor: null,
    status: null,
    is_vehicle: 0,
    latest_action: null,
    latest_action_at: null,
    introduced_at: null,
    ...over,
  };
}

function stateBill(over: Partial<StateBill> & Pick<StateBill, "state_bill_id">): StateBill {
  return {
    state: "WI",
    bill_number: "AB1",
    session: "2025-2026",
    title: null,
    description: null,
    status: "1",
    url: null,
    is_vehicle: 0,
    last_action: null,
    last_action_at: null,
    ...over,
  };
}

// --- TRAP 1: 'Eighth District' ------------------------------------------------------

describe("the canonicalization trap: UW types 'Eighth District' for the Eighth Circuit", () => {
  // Five rows, one of them the tracker's misspelling. Raw /\bcircuit\b/ sees two
  // circuits here; through canonicalCourt it sees three. On the live table that one
  // row is the whole difference between 29/23 and 30/22, and between 9/22 and 10/21.
  const rows = [
    caseRow({ case_id: "d1", court: "District of Oregon" }),
    caseRow({ case_id: "d2", court: "Western District of Washington" }),
    caseRow({ case_id: "c1", court: "Ninth Circuit" }),
    caseRow({ case_id: "c2", court: "D.C. Circuit" }),
    caseRow({ case_id: "c3", court: "Eighth District" }), // <- the trap
  ];

  it("counts 'Eighth District' as a CIRCUIT, not a district", () => {
    expect(docketTotals(rows)).toEqual({ total: 5, district: 2, circuit: 3 });
  });

  it("would read 2/3 the other way round if the regex ran on the raw string", () => {
    // The defective implementation, written out so the test states what it is
    // guarding against rather than only asserting the right answer. If docketTotals
    // ever stops canonicalizing, the assertion above becomes this line's answer.
    const naive = rows.filter((r) => /\bcircuit\b/i.test(r.court ?? "")).length;
    expect(naive).toBe(2);
    expect(docketTotals(rows).circuit).toBe(3);
    expect(docketTotals(rows).circuit).not.toBe(naive);
  });

  it("carries the same trap into the open split", () => {
    // Terminate one true circuit; the misspelled one must still be counted as a
    // circuit among the open rows.
    const withEnding = rows.map((r) =>
      r.case_id === "c1" ? caseRow({ ...r, status: "terminated" }) : r,
    );
    expect(openSplit(withEnding)).toEqual({ total: 4, district: 2, circuit: 2 });
  });

  it("also canonicalizes 'DC Circuit', the tracker's other spelling", () => {
    const r = [caseRow({ case_id: "x", court: "DC Circuit" })];
    expect(docketTotals(r).circuit).toBe(1);
  });
});

// --- TRAP 2: the vehicle's timeline is newer than its last action -------------------

describe("the vehicle trap: a timeline is newer than the last legislative action", () => {
  const vehicle = bill({
    bill_id: "s1383-119",
    is_vehicle: 1,
    latest_action_at: "2026-03-26T00:00:00",
    latest_action: "Considered by Senate (Message from the House considered).",
  });

  it("reads latest_action_at, NOT the newest thing on the bill's timeline", () => {
    // The live shape as of 2026-09-07: S. 1383's timeline runs to 2026-09-02, a news
    // item, while its last floor action is 2026-03-26. A timeline maximum would
    // report the date a story ran under a label that says "quiet since".
    const withTimeline = {
      ...vehicle,
      timeline: [
        { occurred_at: "2026-03-26T00:00:00", kind: "action" },
        { occurred_at: "2026-09-02T20:27:07+00:00", kind: "news" },
      ],
    };
    expect(vehicleQuietSince([withTimeline])).toBe("2026-03-26T00:00:00");
  });

  it("reads the VEHICLE, not whichever bill holds the newest action", () => {
    // The already-shipped defect this guards: reading `bills.latest?.is_vehicle`
    // draws correctly only while the vehicle happens to be the most recent mover.
    const newerNonVehicle = bill({
      bill_id: "hr9999-119",
      is_vehicle: 0,
      latest_action_at: "2026-08-01T00:00:00",
    });
    expect(vehicleQuietSince([newerNonVehicle, vehicle])).toBe("2026-03-26T00:00:00");
  });

  it("is null when nothing on the watchlist is flagged a vehicle", () => {
    expect(vehicleQuietSince([bill({ bill_id: "hr22-119" })])).toBeNull();
  });

  it("takes the newest when more than one bill is flagged", () => {
    const second = bill({ bill_id: "s2-119", is_vehicle: 1, latest_action_at: "2026-05-01T00:00:00" });
    expect(vehicleQuietSince([vehicle, second])).toBe("2026-05-01T00:00:00");
  });
});

// --- the stall clock ----------------------------------------------------------------

describe("monthsSince -- whole months against the record's clock, never new Date()", () => {
  it("floors: the day of month must come round before the count moves", () => {
    expect(monthsSince("2025-01-16T00:00:00", "2026-09-07T21:38:51.725537+00:00")).toBe(19);
    expect(monthsSince("2025-01-16T00:00:00", "2026-09-15T00:00:00+00:00")).toBe(19);
    expect(monthsSince("2025-01-16T00:00:00", "2026-09-16T00:00:00+00:00")).toBe(20);
  });

  it("does not drift the way days/30 does", () => {
    // Two years to the day is 24 months. Dividing 730 days by 30 gives 24.33, and
    // flooring it still reads 24 -- but at 25 months the same arithmetic reads 25.36
    // and the drift keeps growing. Calendar fields do not drift at all.
    expect(monthsSince("2024-02-29T00:00:00", "2026-02-28T00:00:00+00:00")).toBe(23);
    expect(monthsSince("2024-03-01T00:00:00", "2026-03-01T00:00:00+00:00")).toBe(24);
  });

  it("is null when either end is missing, and never negative", () => {
    expect(monthsSince(null, "2026-09-07T00:00:00+00:00")).toBeNull();
    expect(monthsSince("2025-01-16T00:00:00", null)).toBeNull();
    expect(monthsSince("2026-12-01T00:00:00", "2026-09-07T00:00:00+00:00")).toBe(0);
  });

  it("saveStallMonths reads the SENATE companion, not the House bill", () => {
    const house = bill({ bill_id: "hr22-119", latest_action_at: "2025-04-10T00:00:00" });
    const senate = bill({ bill_id: SAVE_SENATE_COMPANION, latest_action_at: "2025-01-16T00:00:00" });
    const asOf = "2026-09-07T21:38:51.725537+00:00";
    expect(saveStallMonths([house, senate], asOf)).toBe(19);
    // The House bill is three months younger; reading it would understate the stall.
    expect(monthsSince(house.latest_action_at, asOf)).toBe(16);
  });

  it("saveStallMonths is null when the companion is not on the watchlist", () => {
    expect(saveStallMonths([bill({ bill_id: "hr22-119" })], "2026-09-07T00:00:00+00:00")).toBeNull();
  });
});

// --- state outcomes -----------------------------------------------------------------

describe("stateOutcomes -- vetoed and failed counted separately", () => {
  const bills = [
    ...Array.from({ length: 4 }, (_, i) => stateBill({ state_bill_id: `f${i}`, status: "6" })),
    stateBill({ state_bill_id: "v0", status: "5" }),
    stateBill({ state_bill_id: "i0", status: "1" }),
    stateBill({ state_bill_id: "other", state: "MN", status: "6" }),
  ];

  it("scopes to the state and counts the two terminal codes apart", () => {
    expect(wisconsinOutcomes(bills)).toEqual({ tracked: 6, failed: 4, vetoed: 1 });
  });

  it("does not fold a veto into a failure -- they are different events", () => {
    const o = wisconsinOutcomes(bills);
    expect(o.failed + o.vetoed).toBe(5);
    expect(o.failed).not.toBe(o.failed + o.vetoed);
  });

  it("tracked is the filter's denominator, not the legislature's", () => {
    expect(stateOutcomes(bills, "MN")).toEqual({ tracked: 1, failed: 1, vetoed: 0 });
    expect(stateOutcomes(bills, "TX")).toEqual({ tracked: 0, failed: 0, vetoed: 0 });
  });
});

// --- the ledger ---------------------------------------------------------------------

describe("the section's docket arithmetic reproduces the 2026-09-07 reading", () => {
  // 52 dockets: 23 circuit (one of them spelled 'Eighth District'), 29 district.
  // 21 rows ended -- 17 of them superseded by a successor, 4 terminated outright --
  // leaving 31 open, 22 of which are appeals.
  //
  // Built from counted rows so the assertions below are arithmetic over this fixture
  // and cannot fail when the live campaign moves. What they pin is that the SPLIT is
  // computed the documented way, which is the part that silently inverts.
  const rows: CampaignRow[] = [
    ...Array.from({ length: 9 }, (_, i) =>
      caseRow({ case_id: `dist-open-${i}`, court: "District of Test" }),
    ),
    ...Array.from({ length: 20 }, (_, i) =>
      caseRow({
        case_id: `dist-done-${i}`,
        court: "District of Test",
        status: "terminated",
        superseded_by: i < 17 ? `circ-open-${i}` : null,
      }),
    ),
    ...Array.from({ length: 21 }, (_, i) =>
      caseRow({ case_id: `circ-open-${i}`, court: "Ninth Circuit" }),
    ),
    caseRow({ case_id: "circ-open-eighth", court: "Eighth District" }),
    caseRow({ case_id: "circ-done", court: "Sixth Circuit", status: "terminated" }),
  ];

  it("counts 52 dockets, 29 district and 23 circuit", () => {
    expect(docketTotals(rows)).toEqual({ total: 52, district: 29, circuit: 23 });
  });

  it("counts 31 open -- 9 district and 22 on appeal", () => {
    expect(openSplit(rows)).toEqual({ total: 31, district: 9, circuit: 22 });
  });

  it("a superseded row is closed even where its status still reads pending", () => {
    // The chain direction that matters: superseded_by lives on the DEAD row. A row
    // carrying it is complete however its own status column reads.
    const r = [caseRow({ case_id: "x", status: "pending", superseded_by: "y" })];
    expect(openSplit(r).total).toBe(0);
  });

  it("without canonicalization the same fixture reads 30/22 and 10/21", () => {
    // The exact pair of wrong readings the D0 pass measured on the live table,
    // reproduced here so the numbers in the record have a test that names them.
    const naiveCircuit = rows.filter((r) => /\bcircuit\b/i.test(r.court ?? ""));
    const naiveOpen = rows.filter(
      (r) => !r.superseded_by && (r.status ?? "").toLowerCase() !== "terminated",
    );
    expect(naiveCircuit.length).toBe(22);
    expect(rows.length - naiveCircuit.length).toBe(30);
    const naiveOpenCircuit = naiveOpen.filter((r) => /\bcircuit\b/i.test(r.court ?? "")).length;
    expect(naiveOpenCircuit).toBe(21);
    expect(naiveOpen.length - naiveOpenCircuit).toBe(10);
  });
});
