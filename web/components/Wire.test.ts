import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bill } from "@/lib/db";
import { CHANNELS, type ActivityRow } from "@/lib/activity";
import { Wire } from "@/components/Wire";
import type {
  BillsRead,
  ExecutiveRead,
  LitigationRead,
  NewsRead,
  StateBillsRead,
} from "@/lib/read";

// THE WIRE'S VOCABULARY, which is the one thing about it no render on this machine can
// be trusted to show. Every other property of this component is visible on the page and
// deliberately untested, per vitest.config.ts. What is NOT visible is what happens when
// the query returns fewer channels than exist, or a channel nobody has seen before:
// production has never yet dropped a channel or grown a sixth, so the branches that
// zero-fill and append draw on no page anyone can visit today.
//
// It is the same argument StateBillRow.test.ts makes for the Vehicle badge, and the
// Vehicle badge is here too -- it moved into the legislation cell in this commit, and
// on live data it renders only because S. 1383 happens to be the most recently actioned
// of the six watched bills. That is a property of the data, not of the component: the
// day a non-vehicle bill takes an action, the badge stops drawing and nothing fails.
// A fixture is the only place that branch is pinned independent of what the cron holds.
//
// Same idiom as StateBillRow.test.ts and StateMatrix.test.ts: renderToStaticMarkup, no
// jsdom, no testing library.

function row(channel: string, over: Partial<ActivityRow> = {}): ActivityRow {
  return { channel, total: 0, day: 0, week: 0, day_history: 0, ...over };
}

const NEWS: NewsRead = {
  datedInWindow: 0,
  collectedLast24h: 0,
  lead: null,
  mostRecent: null,
  windowDays: 7,
};
const LITIGATION: LitigationRead = {
  latestFiling: null,
  filedOnLatest: [],
  movedSinceFiling: false,
  totalCases: 0,
};
const BILLS: BillsRead = {
  total: 0,
  movedInWindow: [],
  latest: null,
  latestActionAt: null,
  latestAction: null,
};
const EXECUTIVE: ExecutiveRead = {
  relevant: 0,
  total: 0,
  latest: null,
  latestInWindow: false,
};
const STATE_BILLS: StateBillsRead = {
  bills: 0,
  states: 0,
  actedInWindow: [],
  latest: null,
  latestActionAt: null,
};

function render(rows: ActivityRow[], over: Partial<Parameters<typeof Wire>[0]> = {}) {
  return renderToStaticMarkup(
    createElement(Wire, {
      rows,
      news: NEWS,
      litigation: LITIGATION,
      bills: BILLS,
      executive: EXECUTIVE,
      stateBills: STATE_BILLS,
      ...over,
    }),
  );
}

const cellsOf = (html: string) =>
  [...html.matchAll(/data-channel="([^"]+)"/g)].map((m) => m[1]);

const full = CHANNELS.map((c) => row(c, { day: 1, week: 2, total: 3 }));

describe("Wire — the channel vocabulary", () => {
  it("renders every canonical channel exactly once", () => {
    const cells = cellsOf(render(full));
    expect(cells).toEqual([...CHANNELS]);
    for (const channel of CHANNELS) {
      expect(cells.filter((c) => c === channel)).toHaveLength(1);
    }
  });

  it("renders five cells even when the query returned none", () => {
    // `GROUP BY channel` omits a channel with no rows at all. A wire that silently
    // drops to four cells reads as a layout quirk rather than as the fact it is.
    expect(cellsOf(render([]))).toEqual([...CHANNELS]);
  });

  it("keeps canonical order regardless of the order rows arrive in", () => {
    const shuffled = [...full].reverse();
    expect(cellsOf(render(shuffled))).toEqual([...CHANNELS]);
  });

  it("appends a non-canonical channel rather than dropping it", () => {
    const cells = cellsOf(render([...full, row("tribal", { day: 4, total: 9 })]));
    expect(cells).toEqual([...CHANNELS, "tribal"]);
  });

  it("gives a channel with no row a zero cell rather than a blank one", () => {
    const html = render([]);
    expect(html).toContain('data-zero="true"');
    expect(html).toContain("+0");
  });
});

describe("Wire — zero-delta styling", () => {
  // Zero is information on this data: measured 2026-08-14, three of five channels
  // collected nothing in 24h. It is styled DOWN, not out, so a quiet channel reads as
  // quiet rather than as broken -- and the marker has to be assertable, because the
  // difference between "quiet" and "broken" is exactly what a reader gets wrong.
  const oneZero = [
    row("legislation", { day: 0, week: 0, total: 73 }),
    row("executive", { day: 5, week: 9, total: 129 }),
    row("litigation", { day: 3, week: 10, total: 2245 }),
    row("news", { day: 91, week: 301, total: 4268 }),
    row("state", { day: 0, week: 0, total: 3882 }),
  ];

  it("marks a +0 delta and does not mark a non-zero one", () => {
    const html = render(oneZero);
    expect([...html.matchAll(/data-zero="true"/g)]).toHaveLength(2);
    expect([...html.matchAll(/data-zero="false"/g)]).toHaveLength(3);
  });

  it("dims the zero and keeps the non-zero bright", () => {
    const html = render(oneZero);
    // The two styles must differ; a single style would make the marker decorative.
    expect(html).toContain("font-normal leading-none text-neutral-600");
    expect(html).toContain("font-semibold leading-none text-neutral-100");
  });

  it("renders the lifetime total as context beside the delta", () => {
    expect(render(oneZero)).toContain("2,245");
  });
});

describe("Wire — the legislation cell carries the Vehicle badge", () => {
  function bill(over: Partial<Bill> = {}): Bill {
    return {
      bill_id: "s1383-119",
      bill_type: "s",
      number: 1383,
      congress: 119,
      short_title: null,
      title: "An Act",
      sponsor: null,
      status: null,
      is_vehicle: 1,
      latest_action: "Held at the desk",
      latest_action_at: "2026-03-26T00:00:00",
      introduced_at: null,
      ...over,
    };
  }

  it("names the vehicle when the latest watched bill carries the flag", () => {
    const html = render(full, {
      bills: { ...BILLS, total: 6, latest: bill(), latestActionAt: "2026-03-26T00:00:00" },
    });
    expect(html).toContain("Vehicle");
    expect(html).toContain("S. 1383");
  });

  it("draws no badge when the latest watched bill is not a vehicle", () => {
    const html = render(full, {
      bills: {
        ...BILLS,
        total: 6,
        latest: bill({ is_vehicle: 0, bill_id: "hr22-119", bill_type: "hr", number: 22 }),
        latestActionAt: "2026-03-26T00:00:00",
      },
    });
    expect(html).not.toContain("Vehicle");
  });

  it("says the watchlist is empty rather than saying nothing", () => {
    // Every cell can say "nothing", and says it with a date where it has one. The rule
    // is TheRead's and it survives the merge: "no movement" tells a reader nothing about
    // whether the system is quiet or broken.
    expect(render(full)).toContain("No bills on the watchlist.");
  });
});
