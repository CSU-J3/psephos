import { describe, expect, it } from "vitest";
import {
  boardDomain,
  bucketByMonth,
  clipWidth,
  cumulativeFilings,
  frames,
  monthlyMax,
  quarterTicks,
  isEoNumbered,
  POSTURE_FILL,
  POSTURE_LABEL,
  visibleAt,
  xOf,
  type Domain,
} from "@/lib/board";

const NOW = new Date("2026-08-19T02:00:00Z");
const D: Domain = {
  start: Date.parse("2024-11-01T00:00:00Z"),
  end: NOW.getTime(),
};

// The real per-state first filings, from board_prework section 2a on 2026-08-18.
// 31 states collapsing to 14 distinct dates.
const FILINGS = [
  ["Oregon", "2025-09-16"], ["California", "2025-09-25"], ["Minnesota", "2025-09-25"],
  ["New Hampshire", "2025-09-25"], ["New York", "2025-09-25"], ["Pennsylvania", "2025-09-25"],
  ["Maryland", "2025-12-01"], ["Vermont", "2025-12-01"], ["Delaware", "2025-12-02"],
  ["New Mexico", "2025-12-02"], ["Washington", "2025-12-02"], ["Colorado", "2025-12-11"],
  ["Hawaii", "2025-12-11"], ["Nevada", "2025-12-11"], ["DC", "2025-12-18"],
  ["Georgia", "2025-12-18"], ["Illinois", "2025-12-18"], ["Arizona", "2026-01-06"],
  ["Connecticut", "2026-01-06"], ["Virginia", "2026-01-16"], ["Kentucky", "2026-02-26"],
  ["New Jersey", "2026-02-26"], ["Oklahoma", "2026-02-26"], ["Utah", "2026-02-26"],
  ["West Virginia", "2026-02-26"], ["Michigan", "2026-02-27"], ["Idaho", "2026-04-01"],
  ["Wisconsin", "2026-06-05"], ["Massachusetts", "2026-06-09"], ["Rhode Island", "2026-06-09"],
  ["Maine", "2026-06-15"],
].map(([state, filed_at]) => ({ state, filed_at: `${filed_at}T00:00:00` }));

describe("xOf", () => {
  it("puts the domain ends at 0 and the full width", () => {
    expect(xOf(D.start, D, 900)).toBe(0);
    expect(xOf(D.end, D, 900)).toBe(900);
  });

  it("puts the midpoint in the middle", () => {
    const mid = D.start + (D.end - D.start) / 2;
    expect(xOf(mid, D, 900)).toBeCloseTo(450, 6);
  });

  it("clamps rather than drawing off-canvas", () => {
    expect(xOf(D.start - 10 * 86_400_000, D, 900)).toBe(0);
    expect(xOf(D.end + 10 * 86_400_000, D, 900)).toBe(900);
  });

  it("is monotonic across the domain", () => {
    let prev = -1;
    for (let i = 0; i <= 20; i++) {
      const x = xOf(D.start + ((D.end - D.start) * i) / 20, D, 900);
      expect(x).toBeGreaterThanOrEqual(prev);
      prev = x;
    }
  });
});

describe("cumulativeFilings", () => {
  it("produces ONE step per distinct date, not one per case", () => {
    const steps = cumulativeFilings(FILINGS);
    expect(steps).toHaveLength(14);
    expect(FILINGS).toHaveLength(31);
  });

  it("accumulates to the jurisdiction count and never decreases", () => {
    const steps = cumulativeFilings(FILINGS);
    expect(steps.at(-1)!.total).toBe(31);
    let prev = 0;
    for (const s of steps) {
      expect(s.total).toBeGreaterThan(prev);
      prev = s.total;
    }
  });

  it("keeps a batch as one step: five states on 2026-02-26", () => {
    const steps = cumulativeFilings(FILINGS);
    const batch = steps.find((s) => s.date === "2026-02-26")!;
    expect(batch.added).toBe(5);
    expect(batch.states).toContain("Kentucky");
    // and a lone filing is a step of one
    expect(steps[0]).toMatchObject({ date: "2025-09-16", added: 1, total: 1 });
  });

  it("skips a NULL filed_at rather than throwing or charting it at zero", () => {
    const steps = cumulativeFilings([...FILINGS, { state: "Nowhere", filed_at: null }]);
    expect(steps.at(-1)!.total).toBe(31);
  });

  it("is empty for no rows", () => {
    expect(cumulativeFilings([])).toEqual([]);
  });
});

describe("bucketByMonth / monthlyMax", () => {
  it("counts per month and omits months with nothing", () => {
    const b = bucketByMonth(["2025-03-04", "2025-03-31", "2025-05-01"]);
    expect(b).toEqual([
      { month: "2025-03", n: 2 },
      { month: "2025-05", n: 1 },
    ]);
  });

  it("ignores nulls", () => {
    expect(bucketByMonth([null, "2025-03-01", null])).toEqual([{ month: "2025-03", n: 1 }]);
  });

  it("takes the maximum across both series, never a literal", () => {
    const a = [{ month: "2025-03", n: 92 }];
    const b = [{ month: "2026-03", n: 19 }];
    expect(monthlyMax(a, b)).toBe(92);
    expect(monthlyMax([], [])).toBe(1); // never divide by zero
  });
});

describe("boardDomain", () => {
  const steps = cumulativeFilings(FILINGS);

  it("ends at now(), so moving the system date moves the right edge", () => {
    const later = new Date(NOW.getTime() + 30 * 86_400_000);
    const a = boardDomain({ filings: steps, stateBills: [], legislation: [], eos: [] }, NOW);
    const b = boardDomain({ filings: steps, stateBills: [], legislation: [], eos: [] }, later);
    expect(a.end).toBe(NOW.getTime());
    expect(b.end).toBe(later.getTime());
    expect(b.end).toBeGreaterThan(a.end);
    expect(b.start).toBe(a.start); // only the right edge moves
  });

  it("floors on the EARLIEST series, not on the filings", () => {
    // The state-bill first-seen series starts 2024-11, before the first filing.
    const d = boardDomain(
      {
        filings: steps,
        stateBills: [{ month: "2024-11", n: 66 }],
        legislation: [{ month: "2025-01", n: 3 }],
        eos: [],
      },
      NOW,
    );
    expect(new Date(d.start).toISOString().slice(0, 7)).toBe("2024-11");
  });
});

describe("frames", () => {
  const f = frames(D, NOW);

  it("maps each stop to that month's last day", () => {
    const nov = f.find((x) => x.key === "2024-11")!;
    expect(new Date(nov.endsAt).toISOString().slice(0, 10)).toBe("2024-11-30");
    const feb = f.find((x) => x.key === "2025-02")!;
    expect(new Date(feb.endsAt).toISOString().slice(0, 10)).toBe("2025-02-28");
  });

  it("ends with a to-date stop at now(), not at a month boundary", () => {
    const last = f.at(-1)!;
    expect(last.toDate).toBe(true);
    expect(last.label).toBe("to date");
    expect(last.endsAt).toBe(NOW.getTime());
  });

  it("is strictly increasing", () => {
    for (let i = 1; i < f.length; i++) expect(f[i].endsAt).toBeGreaterThan(f[i - 1].endsAt);
  });
});

describe("the replay shows nothing past its frame", () => {
  const steps = cumulativeFilings(FILINGS);
  const f = frames(D, NOW);

  it("frame 0 has NO event mark visible", () => {
    // The domain floors on 2024-11 and the first filing is 2025-09-16, so the opening
    // frame must be empty. A replay that opens on its endpoint is not a replay.
    expect(visibleAt(steps, f[0])).toEqual([]);
    expect(clipWidth(f[0], D, 900)).toBeLessThan(900);
  });

  it("the visible count is monotonically non-decreasing across every frame", () => {
    let prev = -1;
    for (const frame of f) {
      const n = visibleAt(steps, frame).length;
      expect(n).toBeGreaterThanOrEqual(prev);
      prev = n;
    }
  });

  it("the last frame shows every step and the first shows none", () => {
    expect(visibleAt(steps, f.at(-1)!)).toHaveLength(14);
    expect(visibleAt(steps, f[0])).toHaveLength(0);
  });

  it("clip width is non-decreasing and reaches full width only at the end", () => {
    let prev = -1;
    for (const frame of f) {
      const w = clipWidth(frame, D, 900);
      expect(w).toBeGreaterThanOrEqual(prev);
      prev = w;
    }
    expect(clipWidth(f.at(-1)!, D, 900)).toBeCloseTo(900, 6);
  });
});

describe("quarterTicks", () => {
  const t = quarterTicks(D);

  it("steps by quarter and stays inside the domain", () => {
    for (const x of t) {
      expect(x.t).toBeGreaterThanOrEqual(D.start);
      expect(x.t).toBeLessThanOrEqual(D.end);
    }
    for (let i = 1; i < t.length; i++) expect(t[i].t).toBeGreaterThan(t[i - 1].t);
  });

  it("labels Q1 with the year and the others with the quarter", () => {
    const jan2025 = t.find((x) => new Date(x.t).toISOString().slice(0, 7) === "2025-01")!;
    expect(jan2025.label).toBe("2025");
    const apr2025 = t.find((x) => new Date(x.t).toISOString().slice(0, 7) === "2025-04")!;
    expect(apr2025.label).toBe("Q2");
  });

  it("gives the LAST tick the year, since there is no end label to carry it", () => {
    expect(t.at(-1)!.label).toBe(String(new Date(t.at(-1)!.t).getUTCFullYear()));
  });
});

describe("isEoNumbered", () => {
  it("accepts a numbered executive order", () => {
    expect(isEoNumbered("EO 14248: Preserving and Protecting the Integrity")).toBe(true);
    expect(isEoNumbered("  EO 14144: Strengthening and Promoting Innovation")).toBe(true);
  });

  it("rejects agency rules and notices, which are not executive orders", () => {
    // The channel carries 118 documents and only a handful are numbered orders; a tick
    // per document would say something the marker layer does not mean.
    expect(isEoNumbered("Airworthiness Directives; Transport Category Airplanes")).toBe(false);
    expect(isEoNumbered("Privacy Act of 1974; System of Records")).toBe(false);
    expect(isEoNumbered("Executive Order on something unnumbered")).toBe(false);
  });
});

describe("the paint vocabulary", () => {
  // These live in lib/ rather than in the component precisely so the key and the mark
  // read one value. That only holds while both records stay TOTAL over Posture: a
  // posture missing from either is a jurisdiction the map paints and the key cannot
  // name, which is the defect the board shipped with at a larger scale.
  const POSTURES = ["live", "ended", "none"] as const;

  it("covers every posture in both records", () => {
    expect(Object.keys(POSTURE_FILL).sort()).toEqual([...POSTURES].sort());
    expect(Object.keys(POSTURE_LABEL).sort()).toEqual([...POSTURES].sort());
  });

  it("gives each posture a distinct fill, since the fill IS the distinction", () => {
    expect(new Set(Object.values(POSTURE_FILL)).size).toBe(POSTURES.length);
  });

  it("gives each posture a distinct wording", () => {
    expect(new Set(Object.values(POSTURE_LABEL)).size).toBe(POSTURES.length);
  });

  it("derives the ended fill FROM the live one rather than restating it", () => {
    // Not decoration: "ended" is meant to read as the same channel dimmed, so it must
    // move when --c-litigation moves. A hardcoded oklch would silently stop matching.
    expect(POSTURE_FILL.ended).toContain("var(--c-litigation)");
    expect(POSTURE_FILL.live).toContain("var(--c-litigation)");
  });
});
