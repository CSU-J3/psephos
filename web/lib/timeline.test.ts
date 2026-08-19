import { describe, expect, it } from "vitest";
import type { FeedEntry } from "@/lib/feed";
import {
  BAND_DAYS,
  FRESH_HOURS,
  NEWS_ROWS_PER_DAY,
  buildTimeline,
  dayKeyOf,
  foldNews,
  isFresh,
} from "@/lib/timeline";

const NOW = new Date("2026-08-16T18:16:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();

let nextId = 1;
function entry(over: Partial<FeedEntry> = {}): FeedEntry {
  return {
    id: nextId++,
    channel: "news",
    title: "a story",
    summary: null,
    source_url: "https://example.test/x",
    source_id: "google-news",
    occurred_at: "2026-08-16T09:00:00Z",
    fetched_at: hoursAgo(1),
    admiralty_source: "C",
    admiralty_info: "3",
    bill_id: null,
    case_id: null,
    state_bill_id: null,
    ...over,
  };
}

describe("ordering is by occurred_at, freshness is not", () => {
  it("places an entry on its own date, not its collection date", () => {
    const backdated = entry({
      occurred_at: "2026-08-12T10:00:00Z",
      fetched_at: hoursAgo(2),
    });
    expect(dayKeyOf(backdated)).toBe("2026-08-12");
  });

  it("THE PAIRING: a backdated item lands on its own date AND is still fresh", () => {
    // The whole reason the timeline replaced the feed. The feed could show arrival or
    // occurrence, never both; here the date positions it and the dot marks it.
    const backdated = entry({
      occurred_at: "2026-08-12T10:00:00Z", // four days back
      fetched_at: hoursAgo(2), // collected this morning
    });
    const t = buildTimeline([backdated], NOW);
    const band = t.bands.find((b) => b.day === "2026-08-12")!;
    expect(band.entries).toHaveLength(1);
    expect(band.hasFresh).toBe(true);
    // And it is NOT on today's band.
    expect(t.bands.find((b) => b.day === "2026-08-16")!.empty).toBe(true);
  });

  it("an old item re-read today is placed old and is fresh; a new item collected days ago is not", () => {
    const staleCollection = entry({
      occurred_at: "2026-08-16T09:00:00Z",
      fetched_at: hoursAgo(FRESH_HOURS + 1),
    });
    expect(isFresh(staleCollection, NOW)).toBe(false);
    expect(isFresh(entry({ fetched_at: hoursAgo(FRESH_HOURS - 1) }), NOW)).toBe(true);
  });

  it("orders entries within a day newest first", () => {
    const early = entry({ occurred_at: "2026-08-16T02:00:00Z" });
    const late = entry({ occurred_at: "2026-08-16T16:00:00Z" });
    const band = buildTimeline([early, late], NOW).bands[0];
    expect(band.entries.map((e) => e.id)).toEqual([late.id, early.id]);
  });

  it("falls back to fetched_at for an undated entry rather than dropping it", () => {
    const undated = entry({ occurred_at: null, fetched_at: "2026-08-15T12:00:00Z" });
    expect(dayKeyOf(undated)).toBe("2026-08-15");
  });
});

describe("empty days", () => {
  it("renders a band for a day with nothing in it", () => {
    const t = buildTimeline(
      [
        entry({ occurred_at: "2026-08-16T09:00:00Z" }),
        entry({ occurred_at: "2026-08-14T09:00:00Z" }),
      ],
      NOW,
    );
    const days = t.bands.map((b) => b.day);
    expect(days.slice(0, 3)).toEqual(["2026-08-16", "2026-08-15", "2026-08-14"]);
    // The gap is visible, not omitted.
    expect(t.bands.find((b) => b.day === "2026-08-15")!.empty).toBe(true);
  });

  it("always renders exactly BAND_DAYS bands, so a quiet week is all visible", () => {
    const t = buildTimeline([entry({ occurred_at: "2026-08-16T09:00:00Z" })], NOW);
    expect(t.bands).toHaveLength(BAND_DAYS);
    expect(t.bands.filter((b) => b.empty)).toHaveLength(BAND_DAYS - 1);
  });

  it("surfaces an item dated before the range instead of dropping it", () => {
    const ancient = entry({
      occurred_at: "2025-06-04T00:00:00Z",
      fetched_at: hoursAgo(1),
    });
    const t = buildTimeline([ancient], NOW);
    expect(t.olderThanWindow.map((e) => e.id)).toEqual([ancient.id]);
    expect(t.bands.every((b) => b.empty)).toBe(true);
  });
});

describe("seed rows", () => {
  // A docket walk: many entries, one anchor, all dated far behind their collection.
  const walk = (caseId: string, n: number, startDay: number) =>
    Array.from({ length: n }, (_, i) =>
      entry({
        channel: "litigation",
        case_id: caseId,
        source_id: "courtlistener",
        admiralty_source: "A",
        admiralty_info: "1",
        occurred_at: `2025-${String(9 + (i % 3)).padStart(2, "0")}-${String(
          startDay + (i % 5),
        ).padStart(2, "0")}T00:00:00Z`,
        fetched_at: hoursAgo(1),
      }),
    );

  it("collapses a docket walk to ONE row per anchor, not one per entry", () => {
    const rows = [...walk("c1", 55, 10), ...walk("c2", 40, 12)];
    const t = buildTimeline(rows, NOW);
    const today = t.bands.find((b) => b.day === "2026-08-16")!;
    expect(today.seeds).toHaveLength(2); // not 95
    expect(today.seeds.map((s) => s.count).sort((a, b) => b - a)).toEqual([55, 40]);
  });

  it("carries the span so the row can say what it covers", () => {
    const t = buildTimeline(walk("c1", 12, 10), NOW);
    const seed = t.bands.find((b) => b.day === "2026-08-16")!.seeds[0];
    expect(seed.count).toBe(12);
    expect(seed.firstOccurredAt! < seed.lastOccurredAt!).toBe(true);
  });

  it("sits on the collection day, not scattered across its own dates", () => {
    const t = buildTimeline(walk("c1", 20, 10), NOW);
    // Every one of the 20 entries is dated in 2025; none of them generates a band.
    expect(t.bands.every((b) => b.day.startsWith("2026-08"))).toBe(true);
    expect(t.bands.find((b) => b.day === "2026-08-16")!.seeds).toHaveLength(1);
  });

  it("a seed day is not empty", () => {
    const t = buildTimeline(walk("c1", 3, 10), NOW);
    expect(t.bands.find((b) => b.day === "2026-08-16")!.empty).toBe(false);
  });
});

describe("news fold", () => {
  const b2 = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      entry({
        admiralty_source: "B",
        admiralty_info: "2",
        source_id: `outlet-${i}`,
        occurred_at: `2026-08-16T0${i % 9}:00:00Z`,
      }),
    );

  it("shows up to three and folds the rest with their sources", () => {
    const fold = foldNews(b2(7));
    expect(fold.shown).toHaveLength(NEWS_ROWS_PER_DAY);
    expect(fold.foldedCount).toBe(4);
    expect(fold.sources).toHaveLength(4);
  });

  it("folds nothing when the day is under the limit", () => {
    const fold = foldNews(b2(2));
    expect(fold.shown).toHaveLength(2);
    expect(fold.foldedCount).toBe(0);
    expect(fold.sources).toEqual([]);
  });

  it("ranks grade before recency, so a newer C3 does not push a B2 below the fold", () => {
    const olderB2 = entry({
      admiralty_source: "B",
      admiralty_info: "2",
      occurred_at: "2026-08-16T01:00:00Z",
      source_id: "democracy-docket",
    });
    const newerC3s = Array.from({ length: 3 }, (_, i) =>
      entry({ occurred_at: `2026-08-16T1${i}:00:00Z` }),
    );
    const fold = foldNews([...newerC3s, olderB2]);
    expect(fold.shown.map((e) => e.id)).toContain(olderB2.id);
    expect(fold.foldedCount).toBe(1);
  });

  it("applies per day, not across the window", () => {
    const t = buildTimeline(
      [
        ...b2(5).map((e) => ({ ...e, occurred_at: "2026-08-16T09:00:00Z" })),
        ...b2(5).map((e) => ({ ...e, occurred_at: "2026-08-15T09:00:00Z" })),
      ],
      NOW,
    );
    for (const day of ["2026-08-16", "2026-08-15"]) {
      const band = t.bands.find((b) => b.day === day)!;
      expect(band.news.shown).toHaveLength(NEWS_ROWS_PER_DAY);
      expect(band.news.foldedCount).toBe(2);
    }
  });
});

describe("litigation grouping", () => {
  it("groups a day's docket entries per case", () => {
    const rows = [
      entry({ channel: "litigation", case_id: "c1", occurred_at: "2026-08-16T09:00:00Z" }),
      entry({ channel: "litigation", case_id: "c1", occurred_at: "2026-08-16T10:00:00Z" }),
      entry({ channel: "litigation", case_id: "c2", occurred_at: "2026-08-16T11:00:00Z" }),
    ];
    const band = buildTimeline(rows, NOW).bands[0];
    expect(band.cases).toHaveLength(2);
    expect(band.cases.find((c) => c.caseId === "c1")!.entries).toHaveLength(2);
  });

  it("keeps non-news, non-case channels as their own rows", () => {
    const rows = [
      entry({ channel: "executive", source_id: "federal-register", occurred_at: "2026-08-16T09:00:00Z" }),
      entry({ channel: "legislation", bill_id: "hr-22", occurred_at: "2026-08-16T10:00:00Z" }),
    ];
    const band = buildTimeline(rows, NOW).bands[0];
    expect(band.other).toHaveLength(2);
    expect(band.news.shown).toEqual([]);
  });
});
