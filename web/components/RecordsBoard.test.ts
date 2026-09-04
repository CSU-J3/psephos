import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RecordsBoard, MILESTONES } from "@/components/RecordsBoard";
import type { Domain, EoTick, FilingStep, Frame, MonthCount } from "@/lib/board";

// THE LABEL LAYER, ASSERTED IN PIXELS AND PERCENTAGES.
//
// This is the second component in this suite, and it earns the exception the same way
// StateMatrix did: what is tested here is NOT visible on the page. The chart's lettering
// used to be SVG text, whose size is a function of the container -- 8.44px where the
// chart shares the board row, 12.37px where it is stacked -- and every render on this
// machine showed a plausible chart at both. The defect was invisible precisely because
// it looked like a design choice.
//
// So the assertions divide by what a render can and cannot show:
//
//   PINNED HERE      the arithmetic that positions a glyph (percentages of the viewBox),
//                    frame gating at boundaries the live scrubber cannot land on, the
//                    chip's binding to lastVisible, and the STRUCTURAL claim that no
//                    glyph remains inside the coordinate system.
//   PINNED IN THE    the rendered font-size in CSS pixels at two widths -- which needs a
//   BROWSER          real layout and lives in scripts/assert-layout.mjs.
//
// Neither instrument can make the other's claim. A markup test cannot see a computed
// font-size, and the browser script cannot construct a frame that sits between two
// milestones. Both are here because the defect this unit closes was a size that no test
// asserted and no render made obvious.

const day = (v: string) => Date.parse(`${v}T00:00:00Z`);

// A DOMAIN CHOSEN SO ONE POSITION IS EXACT RATHER THAN INCIDENTAL. 2025-09-16 sits
// exactly 100 days after the start and 100 before the end, so its marker must land at
// the plot's midpoint: x = PAD_L + PLOT/2 = 34 + 425 = 459, i.e. 51.000% of 900. An
// arbitrary domain would make every expected value a transcription of the same
// arithmetic the component runs, which proves only that a number was copied twice.
const domain: Domain = { start: day("2025-06-08"), end: day("2025-12-25") };

const filings: FilingStep[] = [
  { date: "2025-09-16", t: day("2025-09-16"), added: 1, total: 1, states: ["Oregon"] },
  { date: "2025-11-01", t: day("2025-11-01"), added: 2, total: 3, states: ["Maine", "Utah"] },
];

const stateBills: MonthCount[] = [
  { month: "2025-07", n: 4 },
  { month: "2025-10", n: 8 },
];
const legislation: MonthCount[] = [
  { month: "2025-07", n: 2 },
  { month: "2025-10", n: 5 },
];
const eos: EoTick[] = [{ date: "2025-08-01", t: day("2025-08-01"), title: "EO 14248: Something" }];

const frameAt = (end: string, label = end): Frame => ({
  key: end.slice(0, 7),
  endsAt: day(end),
  label,
  toDate: false,
});

function render(frame: Frame): string {
  return renderToStaticMarkup(
    createElement(RecordsBoard, { domain, filings, stateBills, legislation, eos, frame }),
  );
}

const count = (markup: string, needle: RegExp) => (markup.match(needle) ?? []).length;

describe("RecordsBoard label layer", () => {
  // The thesis of the whole unit, and the only assertion here that would fail on the
  // shape this replaced. Every other test below would pass against SVG text.
  it("leaves no glyph inside the coordinate system", () => {
    const markup = render(frameAt("2026-12-31"));
    const svg = markup.slice(markup.indexOf("<svg"), markup.indexOf("</svg>"));
    expect(svg).not.toContain("<text");
    expect(svg).not.toContain("font-size");
    expect(svg).not.toContain("fontSize");
  });

  it("positions the rail numerals off the shared scale, not off the text baseline", () => {
    const markup = render(frameAt("2026-12-31"));
    // yOfTotal(51) = 12 of 260 -> 4.615%; the axis is AXIS_Y = 130 of 260 -> 50%.
    // Both hang at PAD_L - 6 = 28 of 900 -> 3.111%, right-aligned by transform.
    expect(markup).toContain('style="left:3.111%;top:4.615%"');
    expect(markup).toContain('style="left:3.111%;top:50.000%"');
  });

  it("puts every quarter label on one row and marks the minors", () => {
    const markup = render(frameAt("2026-12-31"));
    // AXIS_Y + H_BOT + 22 = 248 of 260 -> 95.385%, the same row for all of them.
    const rows = count(markup, /top:95\.385%/g);
    expect(rows).toBeGreaterThan(1);
    // Q2/Q3/Q4 thin out under the container rule; a four-character year never does.
    expect(markup).toContain("board-lbl axis minor");
    expect(markup).toMatch(/class="board-lbl axis"[^>]*>2025</);
  });

  it("lands a milestone on the plot midpoint when its date is the domain midpoint", () => {
    const markup = render(frameAt("2026-12-31"));
    // 2025-09-16: x = 34 + 850/2 = 459 -> 51.000%. y is the line's own height at a
    // running total of 1: 130 - (1/51)*118 = 127.686 of 260 -> 49.110%.
    expect(markup).toContain('style="left:51.000%;top:49.110%"');
  });

  // THE ANCHOR IS THE CLAIM, not decoration. The cumulative line counts suits FILED, so
  // a marker on it asserts that its event is a filing. Two of the four are not filings
  // -- a bill reaching the Senate and a court granting motions to dismiss -- and both
  // sit on the axis instead. Pinned as a rule over the set rather than as a spot check,
  // because the failure mode is a future entry defaulting to "line" without anyone
  // deciding, which is exactly how the Apr 28 entry this replaced was drawn.
  it("anchors every non-filing milestone to the axis, never to a suit total", () => {
    const markup = render(frameAt("2026-12-31"));
    const onAxis = MILESTONES.filter((m) => m.anchor === "axis").map((m) => m.date);
    const onLine = MILESTONES.filter((m) => m.anchor === "line").map((m) => m.date);
    expect(onAxis).toEqual(["2025-04-10", "2026-01-15"]);
    // The two line-anchored entries are the campaign's outer filing dates, which ARE
    // steps on the series they sit on.
    expect(onLine).toEqual(["2025-09-16", "2026-06-15"]);
    // The axis is 50.000%; a marker there is making no claim about the line.
    expect(markup).toMatch(/data-encoding="milestone-marker"[^>]*top:50\.000%/);
  });

  // Ordering is what the numerals mean: the caption strip numbers 1-4 in the order the
  // constant holds, and the markers take their numeral from the frame-filtered slice.
  // If the constant ever fell out of date order the two would disagree silently.
  it("keeps the caption numerals in date order 1-4", () => {
    expect(MILESTONES.map((m) => m.date)).toEqual([
      "2025-04-10",
      "2025-09-16",
      "2026-01-15",
      "2026-06-15",
    ]);
  });

  // FRAME GATING AT BOUNDARIES THE SCRUBBER CANNOT LAND ON. The live control steps by
  // month, so no render reachable by dragging it sits between 2025-04-10 and 2025-09-16
  // with exactly one milestone shown. Constructed frames are the only place this is
  // pinned, which is the same argument vitest.config.ts makes for StateMatrix.
  it("shows a milestone only once the frame reaches its date", () => {
    const before = render(frameAt("2025-01-01"));
    const two = render(frameAt("2025-09-30"));
    const all = render(frameAt("2026-12-31"));
    expect(count(before, /data-encoding="milestone-marker"/g)).toBe(0);
    expect(count(two, /data-encoding="milestone-marker"/g)).toBe(2);
    expect(count(all, /data-encoding="milestone-marker"/g)).toBe(MILESTONES.length);
  });

  it("keeps every caption in the flow and hides the ones not yet reached", () => {
    const two = render(frameAt("2025-09-30"));
    // All four are always rendered: the strip's height must not move across frames,
    // because assert-layout asserts one distinct board height across all of them.
    expect(count(two, /<li data-reached=/g)).toBe(MILESTONES.length);
    expect(count(two, /data-reached="true"/g)).toBe(2);
    expect(count(two, /data-reached="false"/g)).toBe(2);
    // And the unreached ones must not name their dates to a reader mid-replay --
    // `visibility` in globals.css is what makes the invisible half invisible.
    expect(two).toContain(MILESTONES[3].label);
  });

  it("binds the chip to lastVisible rather than to the series total", () => {
    expect(render(frameAt("2025-01-01"))).toContain("0 of 51");
    expect(render(frameAt("2025-09-30"))).toContain("1 of 51");
    expect(render(frameAt("2026-12-31"))).toContain("3 of 51");
  });

  it("flips the chip to the right of the leading edge while there is no left to use", () => {
    // clipW = 0 in the first frame: hanging left would put the chip off the plot.
    expect(render(frameAt("2025-01-01"))).toContain("board-chip leads");
    expect(render(frameAt("2025-12-01"))).toContain('class="board-chip"');
  });

  // The chip sits ABOVE the line's end so it cannot cover the marker nearest that end,
  // which is what it did at 1400px. Near the ceiling there is no above, so it drops.
  // Neither case is reachable from live data today -- the campaign stands at 31 of 51 --
  // so a fixture is the only place the second branch is pinned.
  it("drops the chip below the line only when the line is near the ceiling", () => {
    const high: FilingStep[] = [
      { date: "2025-09-16", t: day("2025-09-16"), added: 50, total: 50, states: ["x"] },
    ];
    const low = renderToStaticMarkup(
      createElement(RecordsBoard, { domain, filings, stateBills, legislation, eos, frame: frameAt("2026-12-31") }),
    );
    const near = renderToStaticMarkup(
      createElement(RecordsBoard, {
        domain,
        filings: high,
        stateBills,
        legislation,
        eos,
        frame: frameAt("2026-12-31"),
      }),
    );
    expect(low).not.toContain("board-chip below");
    expect(near).toContain("below");
    expect(near).toContain("50 of 51");
  });
});

describe("MILESTONES", () => {
  it("is ordered, dated and consistent with its own parsed timestamps", () => {
    const ts = MILESTONES.map((m) => m.t);
    expect(ts).toEqual([...ts].sort((a, b) => a - b));
    for (const m of MILESTONES) {
      expect(m.t).toBe(day(m.date));
      expect(m.label).toContain(",");
      expect(Number.isNaN(m.t)).toBe(false);
    }
  });

  // The two derived-and-checked entries name the dates this chart's own steps carry.
  // If a future snapshot moves the first or last filing, the marker is wrong -- the
  // comment on each entry says so, and this pins the pair the comments claim.
  it("keeps the two data-checked milestones on the campaign's outer filing dates", () => {
    expect(MILESTONES.map((m) => m.date)).toContain("2025-09-16");
    expect(MILESTONES.map((m) => m.date)).toContain("2026-06-15");
  });
});
