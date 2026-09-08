import { describe, it, expect } from "vitest";
import type { Bill, StateBill } from "@/lib/db";
import {
  docketTotals,
  openSplit,
  isDojFiling,
  dojFilings,
  relatedSuits,
  stateOutcomes,
  wisconsinOutcomes,
  monthsSince,
  saveStallMonths,
  vehicleQuietSince,
  SAVE_SENATE_COMPANION,
  type DocketLike,
} from "@/lib/stands";

// Fixtures are CONSTRUCTED, on the same rule campaign.test.ts states: a membership
// read from production goes stale by build time and teaches the suite to be ignored.
// Every row below is shaped like the real thing and owned by the test.
//
// The LEDGER block at the foot builds a fixture whose SHAPE reproduces the 2026-09-07
// reading. It pins the arithmetic, not the record: the numbers are counted out of
// rows constructed here, so live drift cannot fail it. What it guards is that the
// splits are computed the documented way, which is the part that silently inverts.

type Row = DocketLike & { case_id: string; state: string | null; caption: string };

function caseRow(over: Partial<Row> & Pick<Row, "case_id">): Row {
  return {
    state: "Testland",
    caption: `case ${over.case_id}`,
    court: "District of Test",
    status: "pending",
    superseded_by: null,
    plaintiff: "United States",
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

// --- SCOPE: who filed, never who has a state ---------------------------------------

describe("DOJ scope is read off the plaintiff column, not inherited from a state filter", () => {
  it("counts a DOJ suit that names no state", () => {
    // THE FIRST OF THE TWO FAILURES A STATE FILTER CANNOT SEE. `WHERE state IS NOT
    // NULL` selects the right 49 rows today only because the three it drops happen to
    // be the three DOJ did not file. A DOJ suit with no state would be dropped from
    // DOJ's own count, silently.
    const row = caseRow({ case_id: "doj-stateless", state: null, plaintiff: "United States" });
    expect(isDojFiling(row)).toBe(true);
    expect(dojFilings([row])).toHaveLength(1);
    expect(relatedSuits([row])).toHaveLength(0);
  });

  it("excludes a related suit even when it names a state", () => {
    // THE SECOND, in the other direction. A related suit that acquired a state would
    // be added to DOJ's count by a state filter, and nothing would say so.
    const row = caseRow({
      case_id: "related-with-state",
      state: "Michigan",
      plaintiff: "League of Women Voters",
    });
    expect(isDojFiling(row)).toBe(false);
    expect(dojFilings([row])).toHaveLength(0);
    expect(relatedSuits([row])).toHaveLength(1);
  });

  it("accepts both spellings of the United States that the table carries", () => {
    expect(isDojFiling(caseRow({ case_id: "a", plaintiff: "United States" }))).toBe(true);
    expect(isDojFiling(caseRow({ case_id: "b", plaintiff: "United States of America" }))).toBe(true);
  });

  it("treats a missing plaintiff as not-DOJ rather than guessing", () => {
    expect(isDojFiling(caseRow({ case_id: "c", plaintiff: null }))).toBe(false);
  });

  it("names the three real related suits when they are the input", () => {
    const rows = [
      caseRow({ case_id: "71499795", state: null, court: "D.D.C.", plaintiff: "League of Women Voters" }),
      caseRow({ case_id: "73218916", state: null, court: "D.D.C.", plaintiff: "Common Cause" }),
      caseRow({ case_id: "73544809", state: null, court: "D.C. Circuit", plaintiff: "League of Women Voters" }),
      caseRow({ case_id: "doj-1", state: "Oregon" }),
    ];
    expect(relatedSuits(rows).map((r) => r.case_id)).toEqual(["71499795", "73218916", "73544809"]);
    expect(dojFilings(rows).map((r) => r.case_id)).toEqual(["doj-1"]);
  });
});

// --- TRAP 1: 'Eighth District' ------------------------------------------------------

describe("the canonicalization trap: UW types 'Eighth District' for the Eighth Circuit", () => {
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
    // The defective implementation, written out so the test states what it guards
    // against rather than only asserting the right answer.
    const naive = rows.filter((r) => /\bcircuit\b/i.test(r.court ?? "")).length;
    expect(naive).toBe(2);
    expect(docketTotals(rows).circuit).toBe(3);
    expect(docketTotals(rows).circuit).not.toBe(naive);
  });

  it("carries the same trap into the open split", () => {
    const withEnding = rows.map((r) =>
      r.case_id === "c1" ? caseRow({ ...r, status: "terminated" }) : r,
    );
    expect(openSplit(withEnding)).toEqual({ total: 4, district: 2, circuit: 2 });
  });

  it("also canonicalizes 'DC Circuit', the tracker's other spelling", () => {
    expect(docketTotals([caseRow({ case_id: "x", court: "DC Circuit" })]).circuit).toBe(1);
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

describe("the section's docket arithmetic, DOJ-scoped, reproduces the ruled figures", () => {
  // 52 rows in `cases`: 49 DOJ filings and 3 related suits.
  //
  //   DOJ       27 district (8 open, 19 ended) + 22 circuit (21 open, 1 ended) = 49
  //   related    2 district (1 open, 1 ended) +  1 circuit (1 open)            =  3
  //
  // One DOJ circuit row is spelled 'Eighth District'. One DOJ circuit row is ended --
  // Michigan's, the only terminated circuit row in the record.
  const doj: Row[] = [
    ...Array.from({ length: 8 }, (_, i) => caseRow({ case_id: `dj-dist-open-${i}` })),
    ...Array.from({ length: 19 }, (_, i) =>
      caseRow({
        case_id: `dj-dist-done-${i}`,
        status: "terminated",
        superseded_by: i < 17 ? `dj-circ-open-${i}` : null,
      }),
    ),
    ...Array.from({ length: 20 }, (_, i) =>
      caseRow({ case_id: `dj-circ-open-${i}`, court: "Ninth Circuit" }),
    ),
    caseRow({ case_id: "dj-circ-open-eighth", court: "Eighth District" }),
    caseRow({ case_id: "dj-circ-done", court: "Sixth Circuit", status: "terminated" }),
  ];
  const related: Row[] = [
    caseRow({
      case_id: "71499795", state: null, court: "D.D.C.", status: "terminated",
      superseded_by: "73544809", plaintiff: "League of Women Voters",
    }),
    caseRow({ case_id: "73218916", state: null, court: "D.D.C.", plaintiff: "Common Cause" }),
    caseRow({ case_id: "73544809", state: null, court: "D.C. Circuit", plaintiff: "League of Women Voters" }),
  ];
  const all = [...doj, ...related];

  it("holds 52 rows, of which 49 are DOJ filings and 3 are not", () => {
    expect(all).toHaveLength(52);
    expect(dojFilings(all)).toHaveLength(49);
    expect(relatedSuits(all)).toHaveLength(3);
  });

  it("counts 49 dockets DOJ filed -- 27 district and 22 appeals", () => {
    expect(docketTotals(dojFilings(all))).toEqual({ total: 49, district: 27, circuit: 22 });
  });

  it("counts 29 of them open -- 8 district and 21 on appeal", () => {
    expect(openSplit(dojFilings(all))).toEqual({ total: 29, district: 8, circuit: 21 });
  });

  it("the unscoped count is the ledger that was withdrawn, and differs by exactly the three", () => {
    // 52 / 29 / 23 and 31 = 9 + 22 were issued as the DOJ campaign's figures. They
    // are the arithmetic over ALL rows, and they fold in a docket whose defendant is
    // DOJ. Kept as an assertion so the difference is a measured three rows rather
    // than a remembered anecdote.
    expect(docketTotals(all)).toEqual({ total: 52, district: 29, circuit: 23 });
    expect(openSplit(all)).toEqual({ total: 31, district: 9, circuit: 22 });
    expect(docketTotals(all).total - docketTotals(dojFilings(all)).total).toBe(3);
  });

  it("a superseded row is closed even where its status still reads pending", () => {
    const r = [caseRow({ case_id: "x", status: "pending", superseded_by: "y" })];
    expect(openSplit(r).total).toBe(0);
  });

  it("without canonicalization the DOJ split reads 28/21 and 9/20", () => {
    // The pair of wrong readings a raw regex produces on this fixture, written out so
    // the failure mode has a test that names its numbers.
    const d = dojFilings(all);
    const naiveCircuit = d.filter((r) => /\bcircuit\b/i.test(r.court ?? "")).length;
    expect(naiveCircuit).toBe(21);
    expect(d.length - naiveCircuit).toBe(28);
    const naiveOpen = d.filter(
      (r) => !r.superseded_by && (r.status ?? "").toLowerCase() !== "terminated",
    );
    const naiveOpenCircuit = naiveOpen.filter((r) => /\bcircuit\b/i.test(r.court ?? "")).length;
    expect(naiveOpenCircuit).toBe(20);
    expect(naiveOpen.length - naiveOpenCircuit).toBe(9);
  });
});
