import { describe, expect, it } from "vitest";
import type { Bill, CampaignRow, ExecItem, NewsItem, StateBill } from "@/lib/db";
import { buildCells, summarize } from "@/lib/campaign";
import {
  READ_WINDOW_DAYS,
  gradeRank,
  readBills,
  readCampaign,
  readExecutive,
  readLitigation,
  readNews,
  readStateBills,
  windowStart,
} from "@/lib/read";

const NOW = new Date("2026-08-16T18:16:00Z");
const iso = (d: Date) => d.toISOString();
const daysAgo = (n: number, seconds = 0) =>
  iso(new Date(NOW.getTime() - n * 86_400_000 - seconds * 1000));

function news(over: Partial<NewsItem> = {}): NewsItem {
  return {
    id: 1,
    source_id: "google-news",
    title: "a story",
    source_url: "https://example.test/1",
    occurred_at: daysAgo(1),
    admiralty_source: "C",
    admiralty_info: "3",
    bill_id: null,
    ...over,
  };
}

function bill(over: Partial<Bill> = {}): Bill {
  return {
    bill_id: "hr-22-119",
    bill_type: "hr",
    number: 22,
    congress: 119,
    short_title: "SAVE Act",
    title: "SAVE Act",
    sponsor: "Roy",
    status: null,
    is_vehicle: 0,
    latest_action: "Referred to committee",
    latest_action_at: daysAgo(1),
    introduced_at: null,
    ...over,
  };
}

function campaignRow(over: Partial<CampaignRow> = {}): CampaignRow {
  return {
    case_id: "1",
    state: "Oregon",
    caption: "United States v. Oregon",
    court: "District of Oregon",
    docket_number: "3:25-cv-01",
    status: "pending",
    filed_at: daysAgo(30),
    latest_entry_at: daysAgo(2),
    status_checked_at: daysAgo(0),
    superseded_by: null,
    source_url: null,
    ...over,
  };
}

function exec(over: Partial<ExecItem> = {}): ExecItem {
  return {
    id: 1,
    title: "Executive Order on Election Integrity",
    source_url: "https://example.test/eo",
    occurred_at: daysAgo(2),
    admiralty_source: "A",
    admiralty_info: "1",
    ...over,
  };
}

function stateBill(over: Partial<StateBill> = {}): StateBill {
  return {
    state_bill_id: "TX-SB1",
    state: "TX",
    bill_number: "SB1",
    session: null,
    title: "Relating to elections",
    description: null,
    status: "1",
    url: null,
    is_vehicle: 0,
    last_action: "Referred",
    last_action_at: daysAgo(1),
    ...over,
  };
}

describe("window", () => {
  it("is 7 days and starts inclusively", () => {
    expect(READ_WINDOW_DAYS).toBe(7);
    expect(windowStart(NOW).toISOString()).toBe("2026-08-09T18:16:00.000Z");
  });
});

describe("gradeRank", () => {
  it("orders A1 before B2 before C3, source dominating credibility", () => {
    expect(gradeRank("A", "1")).toBeLessThan(gradeRank("B", "2"));
    expect(gradeRank("B", "2")).toBeLessThan(gradeRank("C", "3"));
    // An A source outranks a B source whatever the numeral.
    expect(gradeRank("A", "6")).toBeLessThan(gradeRank("B", "1"));
  });

  it("sorts an unparseable grade last instead of throwing", () => {
    expect(() => gradeRank(null, null)).not.toThrow();
    expect(gradeRank("C", "3")).toBeLessThan(gradeRank(null, null));
  });
});

describe("readNews", () => {
  it("counts items dated in the window against what was collected in 24h", () => {
    const r = readNews([news(), news({ id: 2, occurred_at: daysAgo(30) })], 18, NOW);
    expect(r.datedInWindow).toBe(1);
    expect(r.collectedLast24h).toBe(18);
  });

  it("includes an item dated exactly 7 days before now", () => {
    const edge = news({ id: 9, occurred_at: daysAgo(READ_WINDOW_DAYS) });
    expect(readNews([edge], 0, NOW).datedInWindow).toBe(1);
  });

  it("excludes an item one second outside the window", () => {
    const past = news({ id: 10, occurred_at: daysAgo(READ_WINDOW_DAYS, 1) });
    expect(readNews([past], 0, NOW).datedInWindow).toBe(0);
  });

  it("leads on grade before recency: a newer C3 loses to an older B2", () => {
    const newerC3 = news({ id: 1, occurred_at: daysAgo(0), admiralty_source: "C", admiralty_info: "3" });
    const olderB2 = news({ id: 2, occurred_at: daysAgo(5), admiralty_source: "B", admiralty_info: "2" });
    expect(readNews([newerC3, olderB2], 5, NOW).lead?.id).toBe(2);
  });

  it("breaks a grade tie on newest", () => {
    const older = news({ id: 1, occurred_at: daysAgo(5), admiralty_source: "B", admiralty_info: "2" });
    const newerTie = news({ id: 2, occurred_at: daysAgo(1), admiralty_source: "B", admiralty_info: "2" });
    expect(readNews([older, newerTie], 2, NOW).lead?.id).toBe(2);
  });

  it("says nothing with a date: empty window still names the most recent item", () => {
    const stale = news({ id: 4, occurred_at: daysAgo(40) });
    const r = readNews([stale], 0, NOW);
    expect(r.datedInWindow).toBe(0);
    expect(r.lead).toBeNull();
    // The date the empty sentence is built from.
    expect(r.mostRecent?.occurred_at).toBe(daysAgo(40));
  });

  it("survives an empty corpus entirely", () => {
    const r = readNews([], 0, NOW);
    expect(r).toMatchObject({ datedInWindow: 0, lead: null, mostRecent: null });
  });
});

describe("readLitigation", () => {
  it("finds the latest filing and the cases sharing it", () => {
    const rows = [
      campaignRow({ case_id: "a", filed_at: daysAgo(60) }),
      campaignRow({ case_id: "b", state: "Utah", filed_at: daysAgo(10) }),
      campaignRow({ case_id: "c", state: "Nevada", filed_at: daysAgo(10) }),
    ];
    const r = readLitigation(rows, NOW);
    expect(r.latestFiling).toBe(daysAgo(10));
    expect(r.filedOnLatest.map((x) => x.case_id).sort()).toEqual(["b", "c"]);
    expect(r.totalCases).toBe(3);
  });

  it("reports whether a docket has moved since that filing", () => {
    const moved = [campaignRow({ filed_at: daysAgo(10), latest_entry_at: daysAgo(2) })];
    const quiet = [campaignRow({ filed_at: daysAgo(10), latest_entry_at: daysAgo(20) })];
    expect(readLitigation(moved, NOW).movedSinceFiling).toBe(true);
    expect(readLitigation(quiet, NOW).movedSinceFiling).toBe(false);
  });

  it("says nothing on an empty corpus without inventing a date", () => {
    const r = readLitigation([], NOW);
    expect(r).toMatchObject({ latestFiling: null, movedSinceFiling: false, totalCases: 0 });
    expect(r.filedOnLatest).toEqual([]);
  });
});

describe("readCampaign", () => {
  // The pin: the homepage's DOJ line and /campaign cannot fork.
  const rows = [
    campaignRow({ case_id: "1", state: "Oregon", status: "terminated", superseded_by: "2" }),
    campaignRow({ case_id: "2", state: "Oregon", court: "Ninth Circuit", status: "pending" }),
    campaignRow({ case_id: "3", state: "Utah", status: "pending" }),
  ];

  it("equals summarize(buildCells(...)) on identical input", () => {
    expect(readCampaign(rows, NOW)).toEqual(summarize(buildCells([...rows], NOW)));
  });

  it("still equals it on the empty case", () => {
    expect(readCampaign([], NOW)).toEqual(summarize(buildCells([], NOW)));
  });

  it("keeps the 51-cell denominator rather than counting the rows it was given", () => {
    // If someone reimplements this as rows.length the total stops being 51 and this
    // fails -- which is the fork the delegation exists to prevent.
    expect(readCampaign(rows, NOW).total).toBe(summarize(buildCells([...rows], NOW)).total);
  });
});

describe("readBills", () => {
  it("reports which of the watched bills moved in the window", () => {
    const bills = [bill({ bill_id: "a", latest_action_at: daysAgo(1) }),
                   bill({ bill_id: "b", latest_action_at: daysAgo(40) })];
    const r = readBills(bills, NOW);
    expect(r.total).toBe(2);
    expect(r.movedInWindow.map((b) => b.bill_id)).toEqual(["a"]);
    expect(r.latest?.bill_id).toBe("a");
  });

  it("says nothing with a date: no movement still names the last action and its date", () => {
    const bills = [
      bill({ bill_id: "a", latest_action_at: "2026-03-26T00:00:00Z", latest_action: "Read twice" }),
      bill({ bill_id: "b", latest_action_at: "2026-01-02T00:00:00Z" }),
    ];
    const r = readBills(bills, NOW);
    expect(r.movedInWindow).toEqual([]);
    // "None of the 2 watched bills has moved since Mar 26, 2026" is buildable from this.
    expect(r.total).toBe(2);
    expect(r.latestActionAt).toBe("2026-03-26T00:00:00Z");
    expect(r.latestAction).toBe("Read twice");
  });

  it("survives an empty watchlist", () => {
    expect(readBills([], NOW)).toMatchObject({ total: 0, latest: null, latestActionAt: null });
  });
});

describe("readExecutive", () => {
  it("counts relevant against total and names the most recent relevant document", () => {
    const items = [
      exec({ id: 1, title: "Executive Order on Election Integrity", occurred_at: daysAgo(5) }),
      exec({ id: 2, title: "Executive Order on voter registration", occurred_at: daysAgo(1) }),
      exec({ id: 3, title: "Airworthiness Directives; Transport Category Airplanes" }),
    ];
    const r = readExecutive(items, NOW);
    expect(r.total).toBe(3);
    expect(r.relevant).toBe(2);
    expect(r.latest?.id).toBe(2);
    expect(r.latestInWindow).toBe(true);
  });

  it("says nothing with a date when the only relevant document is old", () => {
    const items = [exec({ id: 1, occurred_at: "2026-02-01T00:00:00Z" })];
    const r = readExecutive(items, NOW);
    expect(r.relevant).toBe(1);
    expect(r.latestInWindow).toBe(false);
    expect(r.latest?.occurred_at).toBe("2026-02-01T00:00:00Z");
  });

  it("reports 0 of N rather than failing when nothing is relevant", () => {
    const r = readExecutive([exec({ title: "Airworthiness Directives" })], NOW);
    expect(r).toMatchObject({ relevant: 0, total: 1, latest: null, latestInWindow: false });
  });

  it("survives an empty channel", () => {
    expect(readExecutive([], NOW)).toMatchObject({ relevant: 0, total: 0, latest: null });
  });
});

describe("readStateBills", () => {
  it("counts bills and distinct states, and which acted in the window", () => {
    const bills = [
      stateBill({ state_bill_id: "1", state: "TX", last_action_at: daysAgo(1) }),
      stateBill({ state_bill_id: "2", state: "TX", last_action_at: daysAgo(40) }),
      stateBill({ state_bill_id: "3", state: "WI", last_action_at: daysAgo(2) }),
    ];
    const r = readStateBills(bills, NOW);
    expect(r.bills).toBe(3);
    expect(r.states).toBe(2);
    expect(r.actedInWindow.map((b) => b.state_bill_id)).toEqual(["1", "3"]);
  });

  it("says nothing with a date when no state bill moved", () => {
    const bills = [stateBill({ last_action_at: "2026-06-26T00:00:00Z" })];
    const r = readStateBills(bills, NOW);
    expect(r.actedInWindow).toEqual([]);
    expect(r.latestActionAt).toBe("2026-06-26T00:00:00Z");
  });

  it("survives an empty dimension", () => {
    expect(readStateBills([], NOW)).toMatchObject({ bills: 0, states: 0, latestActionAt: null });
  });
});
