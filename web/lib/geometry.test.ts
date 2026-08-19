import { describe, expect, it } from "vitest";
import {
  MIN_RING_AREA,
  boxesOverlap,
  edgeMidpoints,
  parseRings,
  pathBounds,
  pointInPath,
  pointInRings,
  ringArea,
  significantRings,
} from "@/lib/geometry";
import { CALLOUTS, LABEL_ANCHOR, US_STATES } from "@/lib/map";

const byAb = (ab: string) => US_STATES.find((s) => s.ab === ab)!;

describe("parseRings", () => {
  it("splits a multi-ring path on Z", () => {
    const rings = parseRings("M0,0L10,0L10,10L0,10ZM20,20L30,20L30,30Z");
    expect(rings).toHaveLength(2);
    expect(rings[0]).toHaveLength(4);
  });

  it("throws on a command it cannot parse rather than mis-reading the shape", () => {
    expect(() => parseRings("M0,0C10,10 20,20 30,30Z")).toThrow(/unsupported path command/);
  });
});

describe("ringArea and the sliver filter", () => {
  it("measures a unit square", () => {
    expect(ringArea(parseRings("M0,0L10,0L10,10L0,10Z")[0])).toBe(100);
  });

  it("drops the degenerate slivers the simplified paths carry", () => {
    // Measured: these are exactly the counts handoff 87 section 4.1 names.
    const dropped = (ab: string) =>
      parseRings(byAb(ab).d).length - significantRings(byAb(ab).d).length;
    expect(dropped("MI")).toBe(9);
    expect(dropped("FL")).toBe(9);
    expect(dropped("WI")).toBe(10);
    expect(dropped("NC")).toBe(2);
    expect(dropped("OH")).toBe(2);
  });

  it("keeps every ring at or above the threshold", () => {
    for (const r of significantRings(byAb("MI").d)) {
      expect(ringArea(r)).toBeGreaterThanOrEqual(MIN_RING_AREA);
    }
  });
});

describe("pointInRings", () => {
  const square = parseRings("M0,0L10,0L10,10L0,10Z");

  it("is true inside and false outside", () => {
    expect(pointInRings({ x: 5, y: 5 }, square)).toBe(true);
    expect(pointInRings({ x: 15, y: 5 }, square)).toBe(false);
  });

  it("treats an inner ring as a hole, by even-odd parity", () => {
    const withHole = parseRings("M0,0L20,0L20,20L0,20ZM5,5L15,5L15,15L5,15Z");
    expect(pointInRings({ x: 10, y: 10 }, withHole)).toBe(false); // in the hole
    expect(pointInRings({ x: 2, y: 2 }, withHole)).toBe(true); // in the ring
  });
});

describe("LABEL_ANCHOR sits in real interior", () => {
  // The full label BOX is asserted in the browser, where getComputedTextLength gives a
  // real width. What is checkable offline is the anchor itself, and it is the input
  // every box is centred on -- an anchor outside the polygon cannot produce a box
  // inside it.
  for (const ab of Object.keys(LABEL_ANCHOR)) {
    it(`${ab}: the anchor is inside the polygon`, () => {
      const [x, y] = LABEL_ANCHOR[ab];
      expect(pointInPath({ x, y }, byAb(ab).d)).toBe(true);
    });
  }

  it("is NOT the bounding-box centre, for the states where that would be water", () => {
    // Michigan's bbox centre is in Lake Michigan and Florida's is offshore. This is the
    // same reason hit-testing must be on the path rather than the box.
    for (const ab of ["MI", "FL"]) {
      const b = pathBounds(byAb(ab).d);
      expect(
        pointInPath({ x: b.x + b.width / 2, y: b.y + b.height / 2 }, byAb(ab).d),
        `${ab} bbox centre`,
      ).toBe(false);
    }
  });
});

describe("callout squares", () => {
  it("cover the nine small jurisdictions", () => {
    expect(CALLOUTS.map((c) => c.ab).sort()).toEqual(
      ["CT", "DC", "DE", "MA", "MD", "NH", "NJ", "RI", "VT"].sort(),
    );
  });

  it("do not overlap ANY of the 51 state bounding boxes", () => {
    // The gutter starts right of Maine's easternmost point; this asserts it rather than
    // trusting the constant.
    const offenders: string[] = [];
    for (const c of CALLOUTS) {
      const box = { x: c.x, y: c.y, width: c.size, height: c.size };
      for (const s of US_STATES) {
        if (boxesOverlap(box, pathBounds(s.d))) offenders.push(`${c.ab} over ${s.ab}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("do not overlap each other", () => {
    const offenders: string[] = [];
    for (let i = 0; i < CALLOUTS.length; i++) {
      for (let j = i + 1; j < CALLOUTS.length; j++) {
        const a = CALLOUTS[i];
        const b = CALLOUTS[j];
        if (
          boxesOverlap(
            { x: a.x, y: a.y, width: a.size, height: a.size },
            { x: b.x, y: b.y, width: b.size, height: b.size },
          )
        ) {
          offenders.push(`${a.ab}/${b.ab}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("edgeMidpoints and boxesOverlap", () => {
  it("returns the four edge midpoints, not the corners", () => {
    const pts = edgeMidpoints({ x: 0, y: 0, width: 10, height: 20 });
    expect(pts).toEqual([
      { x: 5, y: 0 },
      { x: 5, y: 20 },
      { x: 0, y: 10 },
      { x: 10, y: 10 },
    ]);
  });

  it("detects overlap and permits touching edges", () => {
    const a = { x: 0, y: 0, width: 10, height: 10 };
    expect(boxesOverlap(a, { x: 5, y: 5, width: 10, height: 10 })).toBe(true);
    expect(boxesOverlap(a, { x: 10, y: 0, width: 10, height: 10 })).toBe(false);
  });
});
