import { describe, expect, it } from "vitest";
import type { Bill, CampaignRow, Case, ExecItem, NewsItem, StateBill, TimelineItem } from "@/lib/db";
import type { FeedEntry } from "@/lib/feed";
import type { MovementRow } from "@/lib/movement";
import {
  aheadLast,
  aheadTitle,
  billDate,
  caseDate,
  datedAhead,
  dayIso,
  foldByClock,
  newestUpTo,
  orderByClock,
  splitByClock,
} from "@/lib/dated";
import { rejectedStatesUpTo, type Rejection } from "@/lib/outcomes";
import { groupByState, latestMovement, sortByRecent } from "@/lib/statebill";
import { sliceLedger } from "@/lib/ledger";
import { latestMovement as campaignMovement } from "@/lib/movement";
import { newsByClock } from "@/lib/news";
import { readBills, readExecutive, readLitigation, readNews, readStateBills } from "@/lib/read";
import { buildTimeline, FRESH_CAPTION, furtherLines } from "@/lib/timeline";
import { vehicleQuietSince } from "@/lib/stands";
import { monthsUpTo } from "@/lib/board";

// THE ONE PREDICATE, AND EVERY SURFACE THAT USES IT (ruled 2026-09-26). The live case is
// MI HB6414: "Bill Electronically Reproduced 09/24/2026", dated 2026-09-29 by LegiScan,
// collected 2026-09-24, on a record whose clock read 2026-09-26. Every test below uses
// that clock, so each asserts what the page did with that row on that day.
const CLOCK = "2026-09-26T11:32:04.123456+00:00";
const CLOCK_DATE = new Date(CLOCK);
const AHEAD = "2026-09-29T00:00:00"; // HB6414's date
const TODAY = "2026-09-26T00:00:00"; // the clock's own day: NOT ahead
const EARLIER = "2026-09-24T00:00:00";

describe("datedAhead -- by UTC day against the record's clock", () => {
  it("is true for a date after the clock's day", () => {
    expect(datedAhead(AHEAD, CLOCK)).toBe(true);
    expect(datedAhead("2026-09-27", CLOCK)).toBe(true);
  });

  it("is false on the clock's own day, whatever the time", () => {
    expect(datedAhead(TODAY, CLOCK)).toBe(false);
    // A news stamp later than the clock's instant, same day: day-granular, so not ahead.
    expect(datedAhead("2026-09-26T23:00:00+00:00", CLOCK)).toBe(false);
  });

  it("is false for earlier dates, missing dates and garbage", () => {
    expect(datedAhead(EARLIER, CLOCK)).toBe(false);
    expect(datedAhead(null, CLOCK)).toBe(false);
    expect(datedAhead("not a date", CLOCK)).toBe(false);
  });

  it("is false with no clock: an empty record has no edge to be ahead of", () => {
    expect(datedAhead(AHEAD, null)).toBe(false);
    expect(datedAhead(AHEAD, undefined)).toBe(false);
  });

  it("takes the clock as an ISO string or a Date and answers the same", () => {
    expect(datedAhead(AHEAD, CLOCK_DATE)).toBe(datedAhead(AHEAD, CLOCK));
  });
});

describe("splitByClock / orderByClock / newestUpTo", () => {
  const rows = [{ at: AHEAD, id: 1 }, { at: EARLIER, id: 2 }, { at: null, id: 3 }, { at: TODAY, id: 4 }];

  it("splits, keeping input order, and keeps an undated row with upTo", () => {
    const { upTo, ahead } = splitByClock(rows, (r) => r.at, CLOCK);
    expect(upTo.map((r) => r.id)).toEqual([2, 3, 4]);
    expect(ahead.map((r) => r.id)).toEqual([1]);
  });

  it("orders ahead rows after upTo rows and never cuts them with the limit", () => {
    const desc = (a: { at: string | null }, b: { at: string | null }) =>
      (b.at ?? "").localeCompare(a.at ?? "");
    expect(orderByClock(rows, desc, (r) => r.at, CLOCK).map((r) => r.id)).toEqual([4, 2, 3, 1]);
    expect(orderByClock(rows, desc, (r) => r.at, CLOCK, 1).map((r) => r.id)).toEqual([4, 1]);
  });

  it("newestUpTo skips a row dated ahead", () => {
    expect(newestUpTo(rows, (r) => r.at, CLOCK)?.id).toBe(4);
    expect(newestUpTo([{ at: AHEAD }], (r) => r.at, CLOCK)).toBeNull();
  });
});

describe("the marker's title and the machine-readable date", () => {
  it("names the source's date and the record's clock", () => {
    expect(aheadTitle(AHEAD, CLOCK)).toBe(
      "The source dates this Sep 29, 2026. This record's clock reads Sep 26, 2026, 11:32Z.",
    );
  });
  it("reads YYYY-MM-DD off any stored shape, or null", () => {
    expect(dayIso(AHEAD)).toBe("2026-09-29");
    expect(dayIso("2026-09-06T07:00:00+00:00")).toBe("2026-09-06");
    expect(dayIso(null)).toBeNull();
  });
});

// --- the surfaces --------------------------------------------------------------------

function stateBill(id: string, at: string | null, over: Partial<StateBill> = {}): StateBill {
  return {
    state_bill_id: id, state: "MI", bill_number: `HB${id}`, session: null, title: id,
    description: null, status: "1", url: null, is_vehicle: 0, last_action: "x",
    last_action_at: at, ...over,
  };
}

describe("/state-bills: Latest movement and every list view", () => {
  const hb6414 = stateBill("6414", AHEAD);
  const many = Array.from({ length: 12 }, (_, i) =>
    stateBill(String(100 + i), `2026-09-${String(10 + i).padStart(2, "0")}T00:00:00`),
  );

  it("never opens Latest movement with a bill dated ahead", () => {
    const { recent } = latestMovement([hb6414, ...many], CLOCK);
    expect(recent[0].state_bill_id).not.toBe("6414");
  });

  // RULED 2026-09-26: the heading's "ten most recent actions" stays true of the ten; the
  // bill dated ahead is returned apart, for below a divider, and never cut.
  it("keeps the ten dated up to the clock as the ten, and returns the one dated ahead apart", () => {
    const { recent, ahead } = latestMovement([hb6414, ...many], CLOCK);
    expect(recent).toHaveLength(10);
    expect(recent.map((b) => b.state_bill_id)).not.toContain("6414");
    expect(ahead.map((b) => b.state_bill_id)).toEqual(["6414"]);
  });

  it("puts it last in the recent list and last inside its state group", () => {
    const pa = stateBill("2802", EARLIER, { state: "PA" });
    expect(sortByRecent([hb6414, pa], CLOCK).map((b) => b.state_bill_id)).toEqual(["2802", "6414"]);
    const mi = groupByState([hb6414, stateBill("7", EARLIER)], CLOCK).find((g) => g.state === "MI")!;
    expect(mi.bills.map((b) => b.state_bill_id)).toEqual(["7", "6414"]);
  });
});

function tl(id: number, occurred_at: string | null): TimelineItem {
  return {
    id, channel: "state", title: `t${id}`, summary: null, source_url: "https://x",
    occurred_at, admiralty_source: "B", admiralty_info: "2",
  };
}

describe("detail ledgers (/state-bill, /bill, /case): sliceLedger", () => {
  it("never heads the ledger with an entry dated ahead, and never folds it", () => {
    const entries = [tl(112734, AHEAD), tl(112731, EARLIER), tl(112732, EARLIER), tl(112733, EARLIER)];
    const { head, rest, ahead } = sliceLedger(entries, CLOCK, 2);
    expect(head.map((e) => e.id)).not.toContain(112734);
    expect(rest.map((e) => e.id)).not.toContain(112734);
    expect(ahead.map((e) => e.id)).toEqual([112734]);
  });
});

describe("/campaign: Latest movement", () => {
  const mv = (id: number, occurred_at: string): MovementRow => ({
    id, case_id: "c", state: "Michigan", occurred_at, text: "t", grade: "A1",
  });
  it("keeps the eight as the eight, and returns an entry dated ahead apart", () => {
    const rows = [mv(99, AHEAD), ...Array.from({ length: 9 }, (_, i) => mv(i, EARLIER))];
    const { recent, ahead } = campaignMovement(rows, CLOCK);
    expect(recent).toHaveLength(8);
    expect(recent.map((r) => r.id)).not.toContain(99);
    expect(ahead.map((r) => r.id)).toEqual([99]);
  });
});

function newsItem(id: number, occurred_at: string | null): NewsItem {
  return {
    id, source_id: "votebeat", title: `n${id}`, source_url: "https://x", occurred_at,
    admiralty_source: "B", admiralty_info: "2", bill_id: null,
  };
}

describe("/news: the archive", () => {
  it("keeps a row dated ahead out of the month groups and returns it separately", () => {
    const { groups, ahead } = newsByClock(
      [newsItem(1, "2026-10-02T00:00:00+00:00"), newsItem(2, "2026-09-25T00:00:00+00:00")],
      CLOCK,
    );
    expect(groups.map((g) => g.month)).toEqual(["2026-09"]);
    expect(ahead.map((i) => i.id)).toEqual([1]);
  });
});

describe("the wire: every 'latest' skips a row dated ahead", () => {
  it("state bills: not the latest, not in the 7-day count", () => {
    const r = readStateBills([stateBill("6414", AHEAD), stateBill("2802", EARLIER)], CLOCK_DATE);
    expect(r.latestActionAt).toBe(EARLIER);
    expect(r.actedInWindow.map((b) => b.state_bill_id)).toEqual(["2802"]);
  });

  it("watched bills, executive, news and litigation: the same", () => {
    const bill = (id: string, at: string): Bill => ({
      bill_id: id, bill_type: "s", number: 1, congress: 119, short_title: null, title: null,
      sponsor: null, status: null, is_vehicle: 0, latest_action: "x", latest_action_at: at,
      introduced_at: null,
    });
    expect(readBills([bill("a", AHEAD), bill("b", EARLIER)], CLOCK_DATE).latestActionAt).toBe(EARLIER);

    const exec = (id: number, at: string): ExecItem => ({
      id, title: "Executive Order 14999 on elections and voting", source_url: "https://x",
      occurred_at: at, admiralty_source: "A", admiralty_info: "1",
    });
    expect(readExecutive([exec(1, AHEAD), exec(2, EARLIER)], CLOCK_DATE).latest?.id).toBe(2);

    expect(
      readNews([newsItem(1, "2026-09-29T00:00:00+00:00"), newsItem(2, "2026-09-25T00:00:00+00:00")], 2, CLOCK_DATE)
        .mostRecent?.id,
    ).toBe(2);

    const filing = (id: string, filed_at: string): CampaignRow => ({
      case_id: id, state: "x", caption: "c", court: null, docket_number: null, status: null,
      filed_at, latest_entry_at: null, status_checked_at: null, superseded_by: null,
      source_url: null, entry_count: 0,
    });
    expect(readLitigation([filing("a", AHEAD), filing("b", EARLIER)], CLOCK_DATE).latestFiling).toBe(EARLIER);
  });
});

// The homepage's three uses of the predicate that sit in app/page.tsx: it calls these
// helpers with these accessors, so the tests reach what the page does (adversarial
// review, 2026-09-26: inline, the uses had no test at all).
describe("the homepage: cases rail, watched bills, and the rejection count", () => {
  const docket = (id: string, latest: string | null, filed: string | null): Case => ({
    case_id: id, caption: "c", court: null, docket_number: null, status: null, category: null,
    filed_at: filed, latest_entry_at: latest, source_url: null, plaintiff: null, defendant: null,
    superseded_by: null,
  });

  it("rail: the first eight are dated up to the clock; one dated ahead is after the fold, uncut", () => {
    const cases = [
      docket("ahead", AHEAD, EARLIER),
      ...Array.from({ length: 10 }, (_, i) => docket(`c${i}`, EARLIER, null)),
      docket("filed-only", null, EARLIER),
    ];
    const { head, rest, ahead } = foldByClock(cases, caseDate, CLOCK, 8);
    expect(head.map((c) => c.case_id)).toEqual(["c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7"]);
    expect(rest.map((c) => c.case_id)).toEqual(["c8", "c9", "filed-only"]);
    expect(ahead.map((c) => c.case_id)).toEqual(["ahead"]);
  });

  it("rail: a docket with no entry is placed by its filing date", () => {
    const { ahead } = foldByClock([docket("x", null, AHEAD)], caseDate, CLOCK, 8);
    expect(ahead.map((c) => c.case_id)).toEqual(["x"]);
  });

  it("watched bills: one dated ahead moves after the rest, the rest keep their order", () => {
    const bill = (id: string, latest: string | null, introduced: string | null): Bill => ({
      bill_id: id, bill_type: "s", number: 1, congress: 119, short_title: null, title: null,
      sponsor: null, status: null, is_vehicle: 0, latest_action: null, latest_action_at: latest,
      introduced_at: introduced,
    });
    const bills = [bill("s1383", AHEAD, null), bill("hr22", EARLIER, null), bill("s128", null, EARLIER)];
    expect(aheadLast(bills, billDate, CLOCK).map((b) => b.bill_id)).toEqual(["hr22", "s128", "s1383"]);
  });

  it("rejection count: a rejection dated ahead is not counted, as the chart does not draw it", () => {
    const r = (state: string, rejected_at: string) =>
      ({ state, case_id: state, rejected_at, pattern: "x" }) as Rejection;
    expect([...rejectedStatesUpTo([r("OR", EARLIER), r("ME", AHEAD)], CLOCK)]).toEqual(["OR"]);
  });
});

function feed(id: number, occurred_at: string, fetched_at: string): FeedEntry {
  return {
    id, channel: "state", title: `f${id}`, summary: null, source_url: "https://x",
    source_id: "legiscan", occurred_at, fetched_at, admiralty_source: "B",
    admiralty_info: "2", bill_id: null, case_id: null, state_bill_id: null,
  };
}

describe("the homepage timeline: before the window and after it are two clauses", () => {
  it("routes a row dated after the clock to datedAfterWindow, not olderThanWindow", () => {
    const t = buildTimeline(
      [feed(112734, AHEAD, "2026-09-24T21:35:47+00:00"), feed(112972, "2026-09-06T07:00:00", "2026-09-25T15:11:52+00:00")],
      CLOCK_DATE,
    );
    expect(t.datedAfterWindow.map((e) => e.id)).toEqual([112734]);
    expect(t.olderThanWindow.map((e) => e.id)).toEqual([112972]);
  });

  // RULED 2026-09-26. The before sentence says "collected in the record's last 24 h", so
  // it counts only rows collected there; the after sentence claims no collection window,
  // so it counts every row dated after the clock. The two cases the ruling named:
  it("counts a row collected three days ago and dated before the bands in neither sentence", () => {
    const t = buildTimeline([feed(1, "2026-09-06T07:00:00", "2026-09-23T11:00:00+00:00")], CLOCK_DATE);
    expect(t.olderThanWindow).toEqual([]);
    expect(t.datedAfterWindow).toEqual([]);
    expect(furtherLines(t.olderThanWindow.length, t.datedAfterWindow.length)).toEqual([]);
  });

  it("counts a row collected three days ago and dated after the clock in the second", () => {
    const t = buildTimeline([feed(2, AHEAD, "2026-09-23T11:00:00+00:00")], CLOCK_DATE);
    expect(t.olderThanWindow).toEqual([]);
    expect(t.datedAfterWindow.map((e) => e.id)).toEqual([2]);
  });

  // The commonest real case, and the one the named cases leave out: a Federal Register
  // document fetched on a Friday and dated the next Monday is FRESH and dated ahead at
  // once. It belongs to the after sentence -- "dated before" is the defect this unit
  // fixes -- so the date test must come first (adversarial review, 2026-09-26: the
  // branches swapped passed every test).
  it("counts a row collected in the last 24 h and dated after the clock in the second, not the first", () => {
    const t = buildTimeline([feed(4, AHEAD, "2026-09-26T10:30:00+00:00")], CLOCK_DATE);
    expect(t.olderThanWindow).toEqual([]);
    expect(t.datedAfterWindow.map((e) => e.id)).toEqual([4]);
  });

  it("counts a row dated before the bands if collected inside the record's last 24 h", () => {
    const t = buildTimeline([feed(3, "2026-09-06T07:00:00", "2026-09-25T11:32:05+00:00")], CLOCK_DATE);
    expect(t.olderThanWindow.map((e) => e.id)).toEqual([3]);
  });

  it.each([
    [2, 0, ["2 further items collected in the record's last 24 h are dated before these seven days."]],
    [1, 0, ["1 further item collected in the record's last 24 h is dated before these seven days."]],
    [0, 1, ["1 further item is dated after these seven days."]],
    [0, 2, ["2 further items are dated after these seven days."]],
    [
      2,
      1,
      [
        "2 further items collected in the record's last 24 h are dated before these seven days.",
        "1 further item is dated after these seven days.",
      ],
    ],
    [
      1,
      3,
      [
        "1 further item collected in the record's last 24 h is dated before these seven days.",
        "3 further items are dated after these seven days.",
      ],
    ],
  ])("furtherLines(%i, %i)", (before, after, want) => {
    expect(furtherLines(before, after)).toEqual(want);
  });

  it("says nothing when there is nothing", () => {
    expect(furtherLines(0, 0)).toEqual([]);
  });

  // "collected in the record's last 24 h" is the fresh dot's own caption: one window,
  // one string (ruled 2026-09-26: the before sentence keeps the window FRESH_CAPTION names).
  it("names the before sentence's window in the fresh dot's own words", () => {
    expect(furtherLines(1, 0)[0]).toContain(FRESH_CAPTION);
  });
});

describe("Where this stands: the vehicle's quiet-since date", () => {
  it("skips an action dated ahead of the clock", () => {
    const v = (at: string): Bill => ({
      bill_id: `s${at}`, bill_type: "s", number: 1, congress: 119, short_title: null, title: null,
      sponsor: null, status: null, is_vehicle: 1, latest_action: "x", latest_action_at: at,
      introduced_at: null,
    });
    expect(vehicleQuietSince([v(AHEAD), v(EARLIER)], CLOCK)).toBe(EARLIER);
  });
});

describe("the records board: monthly series stop at the clock's month", () => {
  it("drops a month after the clock's and keeps the clock's own", () => {
    const out = monthsUpTo(
      [{ month: "2026-08", n: 3 }, { month: "2026-09", n: 5 }, { month: "2026-10", n: 1 }],
      CLOCK,
    );
    expect(out.map((m) => m.month)).toEqual(["2026-08", "2026-09"]);
  });
});
