import { describe, it, expect } from "vitest";
import type { NewsItem } from "@/lib/db";
import { groupByMonth, monthKey, sourceRoster } from "@/lib/news";

function item(over: Partial<NewsItem> & Pick<NewsItem, "id">): NewsItem {
  return {
    source_id: "votebeat",
    title: `headline ${over.id}`,
    source_url: `https://example.test/${over.id}`,
    occurred_at: "2026-08-01T00:00:00+00:00",
    admiralty_source: "B",
    admiralty_info: "2",
    bill_id: null,
    ...over,
  };
}

// Deterministic reordering, so a fixture proves the function orders rather than
// restating the ORDER BY that happens to feed it in production.
const shuffled = <T,>(rows: T[]) => [
  ...rows.filter((_, i) => i % 2 === 1).reverse(),
  ...rows.filter((_, i) => i % 2 === 0),
];

describe("monthKey", () => {
  it("slices the stored string and never constructs a Date", () => {
    expect(monthKey("2026-08-25T15:55:20+00:00")).toBe("2026-08");
    expect(monthKey("2022-04-01T00:00:00")).toBe("2022-04");
  });

  it("does not shift the month at a boundary the local zone would move", () => {
    // The reason this is a slice. `new Date("2026-09-01T00:30:00+00:00").getMonth()`
    // is August anywhere behind UTC, so a browser in Denver would file the first
    // rows of a month under the previous one -- silently, and only near the edge.
    // Same rule lib/format.ts's utcDay exists for.
    expect(monthKey("2026-09-01T00:30:00+00:00")).toBe("2026-09");
    expect(monthKey("2026-08-31T23:30:00+00:00")).toBe("2026-08");
  });

  it("files a null date as undated", () => {
    expect(monthKey(null)).toBe("undated");
  });
});

describe("groupByMonth", () => {
  const dated = (id: number, occurred_at: string) => item({ id, occurred_at });

  it("returns months newest first", () => {
    const rows = [
      dated(1, "2026-07-04T00:00:00+00:00"),
      dated(2, "2026-09-02T00:00:00+00:00"),
      dated(3, "2026-08-11T00:00:00+00:00"),
    ];
    expect(groupByMonth(shuffled(rows)).map((g) => g.month)).toEqual([
      "2026-09", "2026-08", "2026-07",
    ]);
  });

  it("sorts inside a month by occurred_at desc then id desc, matching sliceLedger", () => {
    // Same-day rows are the common case here -- 218 items landed in 2026-08 alone --
    // so the tiebreak is what a reader actually sees most of the time. Untiebroken,
    // the order is arrival order, which is not a property anyone chose.
    const rows = [
      dated(10, "2026-08-04T09:00:00+00:00"),
      dated(30, "2026-08-04T09:00:00+00:00"), // same instant, higher id
      dated(20, "2026-08-04T18:00:00+00:00"), // later that day
      dated(40, "2026-08-01T00:00:00+00:00"),
    ];
    const [aug] = groupByMonth(shuffled(rows));
    expect(aug.items.map((r) => r.id)).toEqual([20, 30, 10, 40]);
  });

  it("compares occurred_at as a string, never through Date.parse", () => {
    const a = dated(1, "2026-08-04T00:00:00");
    const b = dated(2, "2026-08-04T06:00:00+00:00");
    const [aug] = groupByMonth([a, b]);
    expect(aug.items.map((r) => r.id)).toEqual([2, 1]);
  });

  it("counts each month exactly, and the counts sum to the input", () => {
    const rows = [
      dated(1, "2026-09-02T00:00:00+00:00"),
      dated(2, "2026-08-11T00:00:00+00:00"),
      dated(3, "2026-08-12T00:00:00+00:00"),
      dated(4, "2026-08-13T00:00:00+00:00"),
    ];
    const groups = groupByMonth(rows);
    expect(groups.map((g) => [g.month, g.items.length])).toEqual([
      ["2026-09", 1], ["2026-08", 3],
    ]);
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(rows.length);
  });

  it("gives a month of exactly one its own group", () => {
    // Reachable: 8 of the 18 months hold a single row, the oldest back to 2022-04,
    // so the singular label draws in production rather than only here.
    const rows = [
      dated(1, "2026-09-02T00:00:00+00:00"),
      dated(2, "2022-04-15T00:00:00+00:00"),
    ];
    const groups = groupByMonth(rows);
    expect(groups.at(-1)).toEqual({ month: "2022-04", items: [rows[1]] });
  });

  it("puts undated rows last, behind even the oldest real month", () => {
    // 0 rows carry a null date today, so this branch draws on no page anyone can
    // visit; it is pinned because the sort would otherwise place "undated" by string
    // comparison, which sorts it ABOVE every "2..." month.
    const rows = [
      item({ id: 1, occurred_at: null }),
      dated(2, "2022-04-15T00:00:00+00:00"),
      dated(3, "2026-09-02T00:00:00+00:00"),
    ];
    expect(groupByMonth(rows).map((g) => g.month)).toEqual([
      "2026-09", "2022-04", "undated",
    ]);
  });

  it("returns one group when the whole corpus is one month, so nothing folds", () => {
    // Unreachable: the smallest source spans 4 months, so no ?source= view collapses
    // to one either. The page uses `groups.length` to decide whether a fold exists.
    const rows = [dated(1, "2026-09-01T00:00:00+00:00"), dated(2, "2026-09-09T00:00:00+00:00")];
    const groups = groupByMonth(rows);
    expect(groups).toHaveLength(1);
    expect(groups[0].items.map((r) => r.id)).toEqual([2, 1]);
  });

  it("returns nothing for an empty set", () => {
    expect(groupByMonth([])).toEqual([]);
  });

  it("does not mutate the array it was given", () => {
    const rows = shuffled([
      dated(1, "2026-08-01T00:00:00+00:00"),
      dated(2, "2026-09-01T00:00:00+00:00"),
      dated(3, "2026-07-01T00:00:00+00:00"),
    ]);
    const before = rows.map((r) => r.id);
    groupByMonth(rows);
    expect(rows.map((r) => r.id)).toEqual(before);
  });
});

describe("sourceRoster", () => {
  const from = (pairs: [string, number][]) =>
    pairs.flatMap(([s, n]) => Array.from({ length: n }, (_, i) => item({ id: Number(`${n}${i}`), source_id: s })));

  it("counts each source, busiest first", () => {
    const roster = sourceRoster(from([["bolts", 2], ["votebeat", 5], ["democracy-docket", 3]]));
    expect(roster).toEqual([
      { source_id: "votebeat", count: 5 },
      { source_id: "democracy-docket", count: 3 },
      { source_id: "bolts", count: 2 },
    ]);
  });

  it("breaks a count tie on the name, so the order is stable run to run", () => {
    const roster = sourceRoster(from([["votebeat", 2], ["bolts", 2]]));
    expect(roster.map((r) => r.source_id)).toEqual(["bolts", "votebeat"]);
  });

  it("is empty for an empty set", () => {
    expect(sourceRoster([])).toEqual([]);
  });

  it("is computed over the UNFILTERED set the caller passes, counting all five sources", () => {
    // The roster must keep every source visible on a filtered view -- a filter the
    // reader cannot see the way out of is a trap. The page passes the full list here
    // and the filtered list to groupByMonth, which is the whole reason these are two
    // functions rather than one pass.
    const roster = sourceRoster(from([["a", 1], ["b", 1], ["c", 1], ["d", 1], ["e", 1]]));
    expect(roster).toHaveLength(5);
  });
});
