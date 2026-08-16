import { describe, it, expect } from "vitest";
import {
  buildFeed,
  compareEntries,
  entryLink,
  cardLink,
  isHistoryEntry,
  FEED_LIMIT,
  HISTORY_AFTER_DAYS,
  type FeedEntry,
} from "@/lib/feed";

// Constructed fixtures, never read from production -- same discipline as
// campaign.test.ts and activity.test.ts, and for the reason the dormancy set kept
// demonstrating: a fixture copied from live data re-dates itself and pins nothing.
const entry = (over: Partial<FeedEntry> & Pick<FeedEntry, "id">): FeedEntry => ({
  channel: "news",
  title: `item ${over.id}`,
  summary: null,
  source_url: "https://example.test/a",
  source_id: "google-news",
  occurred_at: "2026-08-14T00:00:00+00:00",
  fetched_at: "2026-08-14T12:00:00+00:00",
  admiralty_source: "C",
  admiralty_info: "3",
  bill_id: null,
  case_id: null,
  state_bill_id: null,
  ...over,
});

// Every fixture below is unanchored unless it says otherwise, so one card holds
// exactly one entry and card order IS entry order. That keeps the ordering tests
// reading as they did before grouping existed.
const ids = (rows: FeedEntry[]) => buildFeed(rows).cards.map((c) => c.entries[0].id);

describe("ordering", () => {
  it("puts the most recently fetched entry first", () => {
    expect(
      ids([
        entry({ id: 1, fetched_at: "2026-08-14T06:00:00+00:00" }),
        entry({ id: 2, fetched_at: "2026-08-14T18:00:00+00:00" }),
        entry({ id: 3, fetched_at: "2026-08-14T12:00:00+00:00" }),
      ]),
    ).toEqual([2, 3, 1]);
  });

  it("breaks a fetched_at tie by id descending, deterministically", () => {
    // A collector run writes many rows inside the same second, so this is the
    // common case and not an edge one. Without the tiebreak the within-batch
    // order is whatever the engine returns, and the same data renders two ways.
    const same = "2026-08-14T12:35:07+00:00";
    const a = entry({ id: 11, fetched_at: same });
    const b = entry({ id: 12, fetched_at: same });
    expect(compareEntries(a, b)).toBeGreaterThan(0); // 12 sorts ahead of 11
    expect(ids([a, b])).toEqual([12, 11]);
    // Same input in the opposite order must produce the same output.
    expect(ids([b, a])).toEqual([12, 11]);
  });

  it("orders on fetched_at even when occurred_at disagrees", () => {
    // The backdated-RSS case, which is why window and order share a column. The
    // older story collected later belongs at the top: it is what just arrived.
    const backdated = entry({
      id: 1,
      occurred_at: "2026-08-01T00:00:00+00:00",
      fetched_at: "2026-08-14T18:00:00+00:00",
    });
    const fresh = entry({
      id: 2,
      occurred_at: "2026-08-14T00:00:00+00:00",
      fetched_at: "2026-08-14T06:00:00+00:00",
    });
    expect(ids([fresh, backdated])).toEqual([1, 2]);
  });

  it("sorts a card by its newest entry, not its oldest", () => {
    // The seed-day shape: a docket walked in one run holds the window's OLDEST
    // occurred_at values while being the most recently collected thing on the page.
    // Sorting a card on its oldest entry would bury the very card the reader needs.
    const walk = [
      entry({
        id: 50,
        case_id: "71363789",
        occurred_at: "2025-09-16T00:00:00",
        fetched_at: "2026-08-16T06:25:00+00:00",
      }),
      entry({
        id: 51,
        case_id: "71363789",
        occurred_at: "2026-03-12T00:00:00",
        fetched_at: "2026-08-16T06:25:00+00:00",
      }),
    ];
    const older = entry({ id: 9, fetched_at: "2026-08-16T00:44:00+00:00" });
    const { cards } = buildFeed([older, ...walk]);
    expect(cards.map((c) => c.key)).toEqual(["case:71363789", "item:9"]);
    expect(cards[0].newest_id).toBe(51);
    expect(cards[0].first_occurred_at).toBe("2025-09-16T00:00:00");
    expect(cards[0].last_occurred_at).toBe("2026-03-12T00:00:00");
  });

  it("does not mutate the rows it was handed", () => {
    const rows = [entry({ id: 1 }), entry({ id: 2, case_id: "c1" })];
    const snapshot = JSON.parse(JSON.stringify(rows));
    buildFeed(rows);
    expect(rows).toEqual(snapshot);
  });
});

describe("grouping by anchor", () => {
  it("folds two entries sharing a case_id into one card of two", () => {
    const { cards, total_cards, total_entries } = buildFeed([
      entry({ id: 1, case_id: "71363789", channel: "litigation" }),
      entry({ id: 2, case_id: "71363789", channel: "litigation" }),
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].key).toBe("case:71363789");
    expect(cards[0].anchor).toBe("case");
    expect(cards[0].entries.map((e) => e.id)).toEqual([2, 1]);
    expect(total_cards).toBe(1);
    expect(total_entries).toBe(2); // both numbers render; neither alone is the window
  });

  it("keeps an unanchored entry as a card of one", () => {
    const { cards } = buildFeed([entry({ id: 7 })]);
    expect(cards).toHaveLength(1);
    expect(cards[0].key).toBe("item:7");
    expect(cards[0].anchor).toBeNull();
    expect(cards[0].entries).toHaveLength(1);
  });

  it("never puts a bill entry and a case entry on the same card", () => {
    // Different dimensions with ids that could collide as bare strings; the key is
    // namespaced by kind precisely so they cannot.
    const { cards } = buildFeed([
      entry({ id: 1, bill_id: "123" }),
      entry({ id: 2, case_id: "123" }),
      entry({ id: 3, state_bill_id: "123" }),
    ]);
    expect(cards).toHaveLength(3);
    expect(cards.map((c) => c.key).sort()).toEqual(["bill:123", "case:123", "state:123"]);
  });

  it("groups on the same anchor entryLink resolves to", () => {
    // An entry carrying two anchors must not group on one and link to the other.
    const both = entry({ id: 1, bill_id: "s1383-119", case_id: "72347022" });
    const { cards } = buildFeed([both]);
    expect(cards[0].key).toBe("bill:s1383-119");
    expect(cardLink(cards[0])?.href).toBe("/bill/s1383-119");
  });
});

describe("history", () => {
  // fetched 2026-08-16 throughout; the threshold is the strip's own week.
  const fetched = "2026-08-16T06:25:00+00:00";
  const walked = (id: number, occurred_at: string | null) =>
    entry({ id, case_id: "c1", channel: "litigation", occurred_at, fetched_at: fetched });

  it("is true for an entry collected long after it happened", () => {
    expect(isHistoryEntry(walked(1, "2026-03-12T00:00:00"))).toBe(true);
  });

  it("is false inside the threshold", () => {
    expect(isHistoryEntry(walked(1, "2026-08-12T00:00:00"))).toBe(false);
  });

  it("is false for a NULL occurred_at", () => {
    // An unknown date is not evidence of an old one. 41 litigation rows carry none.
    expect(isHistoryEntry(walked(1, null))).toBe(false);
  });

  it("uses the strip's week, so the two cannot disagree", () => {
    expect(HISTORY_AFTER_DAYS).toBe(7);
    // Exactly at the threshold is not yet history -- the test is `>`, not `>=`.
    expect(isHistoryEntry(walked(1, "2026-08-09T00:00:00"))).toBe(false);
    expect(isHistoryEntry(walked(1, "2026-08-08T00:00:00"))).toBe(true);
  });

  it("marks a card history only when every entry is", () => {
    const old3 = [
      walked(1, "2025-09-16T00:00:00"),
      walked(2, "2026-01-06T00:00:00"),
      walked(3, "2026-03-12T00:00:00"),
    ];
    expect(buildFeed(old3).cards[0].history).toBe(true);
    // One entry dated yesterday and the docket is not history -- it moved.
    const mixed = buildFeed([...old3, walked(4, "2026-08-15T00:00:00")]).cards[0];
    expect(mixed.history).toBe(false);
    expect(mixed.first_occurred_at).toBe("2025-09-16T00:00:00");
    expect(mixed.last_occurred_at).toBe("2026-08-15T00:00:00"); // the range shows the mix
  });
});

describe("the cap, and the count it would otherwise hide", () => {
  it("counts cards, not entries", () => {
    // The seed-day failure, pinned. 174 entries across four dockets is four cards,
    // so a cap that binds on entries would hide the rest of the window for nothing.
    const walk = Array.from({ length: 174 }, (_, i) =>
      entry({ id: i + 1, case_id: `c${i % 4}`, channel: "litigation" }),
    );
    const feed = buildFeed(walk);
    expect(feed.cards).toHaveLength(4);
    expect(feed.truncated).toBe(false);
    expect(feed.total_cards).toBe(4);
    expect(feed.total_entries).toBe(174);
  });

  it("reports the pre-cap totals so the page can say what it dropped", () => {
    const rows = Array.from({ length: 60 }, (_, i) => entry({ id: i + 1 }));
    const feed = buildFeed(rows);
    expect(feed.cards).toHaveLength(FEED_LIMIT);
    expect(feed.total_cards).toBe(60); // NOT 50 -- a silent top-N reads as "everything"
    expect(feed.total_entries).toBe(60);
    expect(feed.truncated).toBe(true);
  });

  it("is not truncated when the window fits", () => {
    const feed = buildFeed(Array.from({ length: 29 }, (_, i) => entry({ id: i + 1 })));
    expect(feed.cards).toHaveLength(29);
    expect(feed.total_cards).toBe(29);
    expect(feed.truncated).toBe(false);
  });

  it("treats exactly-at-the-limit as untruncated", () => {
    const feed = buildFeed(
      Array.from({ length: FEED_LIMIT }, (_, i) => entry({ id: i + 1 })),
    );
    expect(feed.truncated).toBe(false);
  });

  it("handles an empty window", () => {
    expect(buildFeed([])).toEqual({
      cards: [],
      total_cards: 0,
      total_entries: 0,
      truncated: false,
    });
  });
});

describe("grades", () => {
  it("keeps C3 items in the feed carrying their own grade", () => {
    // The move-2 decision, pinned. The feed is the activity surface and shows
    // every grade; /news is the B2 evidentiary archive. A filter creeping back in
    // here would drop 87% of the news channel and put the feed silently at odds
    // with the channel strip above it, which counts all grades.
    const feed = buildFeed([
      entry({ id: 1, admiralty_source: "C", admiralty_info: "3" }),
      entry({ id: 2, source_id: "votebeat", admiralty_source: "B", admiralty_info: "2" }),
      entry({ id: 3, channel: "litigation", admiralty_source: "A", admiralty_info: "1" }),
    ]);
    expect(feed.cards).toHaveLength(3);
    expect(feed.cards.flatMap((c) => c.grades).sort()).toEqual(["A1", "B2", "C3"]);
  });

  it("collects a card's distinct grades in first-seen order", () => {
    // A docket carries A1 court records and B2 tracker framing; the card badges
    // both. Distinct, so 55 A1 entries do not stamp 55 identical badges.
    const feed = buildFeed([
      entry({
        id: 1,
        case_id: "c1",
        admiralty_source: "B",
        admiralty_info: "2",
        fetched_at: "2026-08-16T01:00:00+00:00",
      }),
      entry({
        id: 2,
        case_id: "c1",
        admiralty_source: "A",
        admiralty_info: "1",
        fetched_at: "2026-08-16T02:00:00+00:00",
      }),
      entry({
        id: 3,
        case_id: "c1",
        admiralty_source: "A",
        admiralty_info: "1",
        fetched_at: "2026-08-16T03:00:00+00:00",
      }),
    ]);
    // First-seen is in card order (newest first), so A1 leads and B2 follows once.
    expect(feed.cards[0].grades).toEqual(["A1", "B2"]);
  });
});

describe("cross-channel links", () => {
  it("links a bill, a case and a state bill to their timelines", () => {
    expect(entryLink(entry({ id: 1, bill_id: "s1383-119" })))
      .toEqual({ href: "/bill/s1383-119", label: "s1383-119" });
    expect(entryLink(entry({ id: 2, case_id: "72347022" })))
      .toEqual({ href: "/case/72347022", label: "case 72347022" });
    expect(entryLink(entry({ id: 3, state_bill_id: "TX-1234" })))
      .toEqual({ href: "/state-bill/TX-1234", label: "TX-1234" });
  });

  it("returns null for an unanchored item", () => {
    // The common case by a wide margin: most news items anchor to nothing.
    expect(entryLink(entry({ id: 1 }))).toBeNull();
    expect(cardLink(buildFeed([entry({ id: 1 })]).cards[0])).toBeNull();
  });

  it("prefers the bill when an item somehow carries two anchors", () => {
    // Measured 2026-08-13, zero items carry both, so this pins a decision rather
    // than a behaviour anyone has seen. The point is that it is a decision.
    const both = entry({ id: 1, bill_id: "s1383-119", case_id: "72347022" });
    expect(entryLink(both)?.href).toBe("/bill/s1383-119");
  });
});
