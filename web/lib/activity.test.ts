import { describe, it, expect } from "vitest";
import { windowStarts, toCells, CHANNELS, WINDOW_DAYS } from "@/lib/activity";
import type { ActivityRow } from "@/lib/activity";

// Fixed clock and constructed fixtures, same discipline as campaign.test.ts: window
// arithmetic is arithmetic against a clock, and a test that passes `new Date()`
// re-dates itself every run.
const NOW = new Date("2026-08-14T02:45:00.000Z");

const row = (over: Partial<ActivityRow> & Pick<ActivityRow, "channel">): ActivityRow => ({
  total: 0,
  day: 0,
  week: 0,
  day_history: 0,
  last_fetch: null,
  ...over,
});

describe("window starts", () => {
  it("computes the 24h and 7d boundaries in UTC", () => {
    expect(windowStarts(NOW)).toEqual({
      day: "2026-08-13T02:45:00.000+00:00",
      week: "2026-08-07T02:45:00.000+00:00",
    });
  });

  it("emits +00:00 rather than Z, so a boundary row is not excluded by sort order", () => {
    // The SQL compares fetched_at lexicographically. Every fetched_at is written by
    // common.now_iso() and suffixed +00:00 (verified 0 rows otherwise in production),
    // so the bound must carry the same suffix: on timestamps equal to the microsecond,
    // 'Z' (0x5A) sorts ABOVE '+' (0x2B) and a Z-suffixed bound would drop the row
    // sitting exactly on the boundary.
    const { day } = windowStarts(NOW);
    expect(day.endsWith("+00:00")).toBe(true);
    expect(day).not.toContain("Z");
    const boundaryRow = "2026-08-13T02:45:00.000+00:00";
    expect(boundaryRow >= day).toBe(true);          // inclusive, matching SQL's >=
    expect("2026-08-13T02:44:59.999+00:00" >= day).toBe(false);
    // The bug this guards, spelled out: with a Z bound the boundary row falls out.
    expect(boundaryRow >= day.replace("+00:00", "Z")).toBe(false);
  });

  it("crosses month and year boundaries by absolute elapsed time, not calendar", () => {
    expect(windowStarts(new Date("2026-03-03T00:00:00.000Z")).week)
      .toBe("2026-02-24T00:00:00.000+00:00");
    expect(windowStarts(new Date("2027-01-04T12:00:00.000Z")).week)
      .toBe("2026-12-28T12:00:00.000+00:00");
    // A leap day is not special: 7 days back from 2028-03-01 is 2028-02-23.
    expect(windowStarts(new Date("2028-03-01T00:00:00.000Z")).week)
      .toBe("2028-02-23T00:00:00.000+00:00");
  });

  it("keeps the two windows ordered and the constants honest", () => {
    const { day, week } = windowStarts(NOW);
    expect(week < day).toBe(true);           // the 7d window strictly contains the 24h one
    expect(WINDOW_DAYS).toEqual({ day: 1, week: 7 });
  });
});

describe("zero-filling the strip", () => {
  it("renders all five channels when the query returned none of them", () => {
    // An all-zero day is the empty-result case, and it must produce five cells rather
    // than an empty strip. GROUP BY omits a channel with no rows at all.
    const cells = toCells([]);
    expect(cells.map((c) => c.channel)).toEqual([...CHANNELS]);
    expect(cells.every((c) => c.total === 0 && c.day === 0 && c.week === 0)).toBe(true);
  });

  it("fills the channels the query skipped and keeps the ones it returned", () => {
    // The measured shape on 2026-08-14: only litigation and news moved.
    const cells = toCells([
      row({ channel: "litigation", total: 1960, day: 2, week: 27 }),
      row({ channel: "news", total: 3416, day: 29, week: 255 }),
    ]);
    expect(cells).toHaveLength(5);
    expect(cells.map((c) => c.channel)).toEqual([...CHANNELS]);
    expect(cells.find((c) => c.channel === "news")).toMatchObject({ day: 29, week: 255 });
    expect(cells.find((c) => c.channel === "state")).toMatchObject({ total: 0, day: 0 });
  });

  it("renders in canonical order regardless of the order rows arrive in", () => {
    // The query sorts alphabetically; the strip does not. Legislation leads because it
    // is the first channel of the spec's four, not because of its name.
    const cells = toCells([
      row({ channel: "state", total: 3882 }),
      row({ channel: "executive", total: 118 }),
      row({ channel: "legislation", total: 73 }),
    ]);
    expect(cells.map((c) => c.channel)).toEqual([
      "legislation", "executive", "litigation", "news", "state",
    ]);
  });

  it("appends an unknown channel rather than dropping it", () => {
    // A sixth channel appearing in `items` is something to see, not something to hide
    // behind a constant written before it existed.
    const cells = toCells([row({ channel: "coercion", total: 4, day: 1, week: 4 })]);
    expect(cells).toHaveLength(6);
    expect(cells[5]).toMatchObject({ channel: "coercion", day: 1 });
  });

  it("zero-fills the history sub-count too", () => {
    // A channel the query skipped must get 0 rather than undefined: the strip
    // renders the line on `> 0`, and undefined > 0 is false but reads as a bug
    // waiting to happen the first time someone sums the column.
    const cells = toCells([row({ channel: "litigation", day: 174, day_history: 174 })]);
    expect(cells.find((c) => c.channel === "litigation")?.day_history).toBe(174);
    expect(cells.filter((c) => c.channel !== "litigation").every((c) => c.day_history === 0))
      .toBe(true);
  });

  it("never reports more history than it collected in the window", () => {
    // The invariant that makes the line readable: it is a SUB-count of `day`, so a
    // cell can read "174 history" under "+174/24h" but never above it.
    const cells = toCells([
      row({ channel: "litigation", day: 174, day_history: 174 }),
      row({ channel: "news", day: 18, day_history: 11 }),
    ]);
    expect(cells.every((c) => c.day_history <= c.day)).toBe(true);
  });

  it("null-fills the collection time rather than inventing one", () => {
    // The four counts zero-fill because zero is the true count for a channel with no
    // rows. There is NO true timestamp for such a channel, so it gets null -- and the
    // distinction has to hold at the type as well as the value, because a stand-in
    // date would render as a real reading with nothing on the page to mark it as
    // manufactured. That is the defect this whole unit removes, reintroduced one
    // layer down.
    const cells = toCells([row({ channel: "news", total: 3416, last_fetch: "2026-09-03T20:26:11.004+00:00" })]);
    expect(cells.find((c) => c.channel === "news")?.last_fetch)
      .toBe("2026-09-03T20:26:11.004+00:00");
    expect(cells.filter((c) => c.channel !== "news").every((c) => c.last_fetch === null))
      .toBe(true);
    // Not undefined, not "", not an epoch date. Explicitly null.
    for (const c of cells.filter((c) => c.channel !== "news")) {
      expect(c.last_fetch).toBeNull();
    }
  });

  it("does not mutate the rows it was handed", () => {
    const rows = [row({ channel: "news", total: 10, day: 1, week: 3 })];
    const snapshot = JSON.parse(JSON.stringify(rows));
    toCells(rows);
    expect(rows).toEqual(snapshot);
  });
});
