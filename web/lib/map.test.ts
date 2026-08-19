import { describe, expect, it } from "vitest";
import {
  FEATURE_COUNT,
  LABEL_ANCHOR,
  US_STATES,
  partitionByStates,
  resolveState,
  tryResolveState,
} from "@/lib/map";

// The 31 distinct `cases.state` values, read from Turso 2026-08-18 by
// tools/board_prework (section 2c). Held as a fixture rather than queried: the point is
// that every value the database has actually produced resolves, and a fixture is what
// makes that assertion reproducible offline. If the collector ever stores a new form,
// board_prework's 2c-i alarm is what catches it against live data -- this test catches
// a regression in the resolver.
const STORED_STATE_VALUES = [
  "Arizona", "California", "Colorado", "Connecticut", "DC", "Delaware", "Georgia",
  "Hawaii", "Idaho", "Illinois", "Kentucky", "Maine", "Maryland", "Massachusetts",
  "Michigan", "Minnesota", "Nevada", "New Hampshire", "New Jersey", "New Mexico",
  "New York", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "Utah", "Vermont",
  "Virginia", "Washington", "West Virginia", "Wisconsin",
];

describe("geometry", () => {
  it("carries all 51 jurisdictions", () => {
    expect(US_STATES).toHaveLength(FEATURE_COUNT);
  });

  it("has a unique code and a non-empty path for every feature", () => {
    expect(new Set(US_STATES.map((f) => f.ab)).size).toBe(FEATURE_COUNT);
    expect(US_STATES.filter((f) => !f.d)).toEqual([]);
  });

  it("carries numeric centroids, not strings", () => {
    // The generator emitted integers; a JSON edit that quotes them would still parse
    // and would then place markers at NaN with no error.
    for (const f of US_STATES) {
      expect(typeof f.cx, `${f.ab}.cx`).toBe("number");
      expect(typeof f.cy, `${f.ab}.cy`).toBe("number");
    }
  });
});

describe("resolveState", () => {
  it("resolves every stored cases.state value", () => {
    const unresolved = STORED_STATE_VALUES.filter((v) => !tryResolveState(v));
    expect(unresolved).toEqual([]);
  });

  it("resolves DC by its code, whose feature is named District of Columbia", () => {
    const dc = resolveState("DC");
    expect(dc.ab).toBe("DC");
    expect(dc.name).toBe("District of Columbia");
  });

  it("resolves a full name", () => {
    expect(resolveState("West Virginia").ab).toBe("WV");
  });

  it("throws loudly on an unmapped value rather than dropping it", () => {
    expect(() => resolveState("Atlantis")).toThrow(/no geometry for state/);
  });

  it("rejects the tracker's suffixed form, which cannot reach cases.state", () => {
    // normalize_state strips "(N)" at the collector boundary, so this arriving here
    // means the boundary was bypassed. Failing is the correct behaviour; resolving it
    // would be tolerating input the schema does not produce.
    expect(() => resolveState("Georgia (1)")).toThrow();
    expect(resolveState("Georgia").ab).toBe("GA");
  });
});

describe("LABEL_ANCHOR", () => {
  // The nine states carrying tracked bills, from board_prework section 2d.
  const BILL_STATES = ["TX", "WI", "PA", "AZ", "GA", "MI", "OH", "FL", "NC"];

  it("covers every bill-tracked state and nothing else", () => {
    expect(Object.keys(LABEL_ANCHOR).sort()).toEqual([...BILL_STATES].sort());
  });

  it("anchors a real feature and sits inside the canvas", () => {
    for (const ab of BILL_STATES) {
      const [x, y] = LABEL_ANCHOR[ab];
      expect(US_STATES.some((f) => f.ab === ab), `${ab} has geometry`).toBe(true);
      expect(x, `${ab}.x`).toBeGreaterThan(0);
      expect(x, `${ab}.x`).toBeLessThan(975);
      expect(y, `${ab}.y`).toBeGreaterThan(0);
      expect(y, `${ab}.y`).toBeLessThan(610);
    }
  });

  it("is not the centroid, for the states whose centroid is off-polygon", () => {
    // Michigan's centroid is in Lake Michigan; if someone replaces the anchors with
    // centroids this is the assertion that notices.
    for (const ab of ["MI", "FL", "WI"]) {
      const f = US_STATES.find((s) => s.ab === ab)!;
      const [x, y] = LABEL_ANCHOR[ab];
      expect([x, y], `${ab} anchor equals centroid`).not.toEqual([f.cx, f.cy]);
    }
  });
});

describe("partitionByStates", () => {
  it("derives the sued / never-sued split and covers all 51", () => {
    const { sued, neverSued } = partitionByStates(STORED_STATE_VALUES);
    expect(sued).toHaveLength(STORED_STATE_VALUES.length);
    expect(sued.length + neverSued.length).toBe(FEATURE_COUNT);
  });

  it("puts the four bill-tracked but never-sued states in the empty set", () => {
    // FL, NC, OH and TX carry tracked bills and no DOJ suit, which is why fill and dot
    // must stay separate properties. web/lib/campaign.ts records the same fact.
    const { neverSued } = partitionByStates(STORED_STATE_VALUES);
    const abs = neverSued.map((f) => f.ab);
    for (const ab of ["FL", "NC", "OH", "TX"]) expect(abs).toContain(ab);
  });

  it("throws rather than silently dropping an unmapped value", () => {
    expect(() => partitionByStates(["Maine", "Atlantis"])).toThrow();
  });
});
