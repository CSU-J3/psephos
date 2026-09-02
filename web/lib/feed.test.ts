import { describe, it, expect } from "vitest";
import {
  entryLink,
  isHistoryEntry,
  HISTORY_AFTER_DAYS,
  type FeedEntry,
} from "@/lib/feed";

// WHAT IS LEFT HERE AFTER THE CARD LAYER WENT. This file held 28 tests; 17 of them
// drove buildFeed, the cap and the anchor grouping, which existed for a component
// mounted by nothing. They were deleted with it rather than kept green -- a test whose
// subject no route reaches reads as coverage and is worse than none.
//
// The 11 that remain pin things the live page depends on: isHistoryEntry, which
// lib/timeline.ts uses to route seed rows, and entryLink/anchorLabel, which name every
// anchor the timeline renders. Nothing was left unpinned by the deletion -- the
// ordering contract is timeline.test.ts's, and so is the grade fold that keeps C3
// items reachable.
//
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

});

describe("cross-channel links", () => {
  // THESE THREE ARE THE FALLBACK PATH, and they did not have to change when the labels
  // did. `entry()` sets no anchor, so each of these carries an id with no dimension row
  // behind it -- exactly the case where the id is the only true thing left to print.
  // That they still read the same after the change is the evidence the fallback works;
  // the anchored assertions below are what pin the new behaviour.
  it("falls back to the raw id when an entry carries no anchor", () => {
    expect(entryLink(entry({ id: 1, bill_id: "s1383-119" })))
      .toEqual({ href: "/bill/s1383-119", label: "s1383-119" });
    expect(entryLink(entry({ id: 2, case_id: "72347022" })))
      .toEqual({ href: "/case/72347022", label: "case 72347022" });
    expect(entryLink(entry({ id: 3, state_bill_id: "TX-1234" })))
      .toEqual({ href: "/state-bill/TX-1234", label: "TX-1234" });
  });

  // ALL THREE ARMS, because all three had the same defect. Only the case arm was
  // reported -- two hand-seeded rows key on slugs, so it could print `case
  // united-states-v-minnesota`, which is visibly wrong. `1890243` is a bare LegiScan id
  // and strictly harder to read; it drew no complaint because a number looks chosen.
  it("labels each anchor by its name when the dimension row is present", () => {
    expect(
      entryLink(
        entry({
          id: 1,
          bill_id: "s1383-119",
          anchor: {
            kind: "bill",
            id: "s1383-119",
            bill_type: "s",
            number: 1383,
            short_title: null,
            title: null,
            is_vehicle: 1,
          },
        }),
      ),
    ).toEqual({ href: "/bill/s1383-119", label: "S. 1383" });

    expect(
      entryLink(
        entry({
          id: 3,
          state_bill_id: "1890243",
          anchor: {
            kind: "state",
            id: "1890243",
            state: "TX",
            bill_number: "HB1235",
            title: null,
          },
        }),
      ),
    ).toEqual({ href: "/state-bill/1890243", label: "TX HB1235" });
  });

  // THE SHAPE THAT MOTIVATED THE UNIT, pinned as itself. A hand-seeded slug key with a
  // perfectly good caption beside it: the record was never wrong, the label just read
  // past it. No `case ` prefix once a caption is available -- the caption already reads
  // as a case name, and the prefix only exists to stop a bare key looking like a stray
  // number next to a headline.
  it("labels a slug-keyed case by its caption, prefix and all", () => {
    const link = entryLink(
      entry({
        id: 2,
        case_id: "united-states-v-minnesota",
        anchor: {
          kind: "case",
          id: "united-states-v-minnesota",
          caption: "United States v. Minnesota",
          court: "District of Minnesota",
          docket_number: "0:25-cv-02001",
          status: "pending",
          successor: null,
          predecessor: null,
        },
      }),
    );
    expect(link).toEqual({
      href: "/case/united-states-v-minnesota",
      label: "United States v. Minnesota",
    });
    expect(link?.label).not.toContain("united-states-v");
    expect(link?.label).not.toContain("case ");
  });

  // A numeric docket id is no better than a slug once a caption exists; the slug is
  // just the version somebody noticed.
  it("labels a numerically keyed case by its caption too", () => {
    expect(
      entryLink(
        entry({
          id: 4,
          case_id: "72347022",
          anchor: {
            kind: "case",
            id: "72347022",
            caption: "United States v. Weber",
            court: "N.D. Cal.",
            docket_number: "3:25-cv-01234",
            status: "pending",
            successor: null,
            predecessor: null,
          },
        }),
      )?.label,
    ).toBe("United States v. Weber");
  });

  // The href is the id on every path. Only the LABEL changed, and a route keyed on a
  // caption would 404 -- worth a test, because "use the caption" applied one field too
  // far is the obvious way to break this.
  it("routes on the id even when it labels by the caption", () => {
    const link = entryLink(
      entry({
        id: 5,
        case_id: "united-states-v-dc",
        anchor: {
          kind: "case",
          id: "united-states-v-dc",
          caption: "United States v. DC",
          court: "D.D.C.",
          docket_number: "1:25-cv-09999",
          status: "pending",
          successor: null,
          predecessor: null,
        },
      }),
    );
    expect(link?.href).toBe("/case/united-states-v-dc");
  });

  it("returns null for an unanchored item", () => {
    // The common case by a wide margin: most news items anchor to nothing.
    expect(entryLink(entry({ id: 1 }))).toBeNull();
  });

  it("prefers the bill when an item somehow carries two anchors", () => {
    // Measured 2026-08-13, zero items carry both, so this pins a decision rather
    // than a behaviour anyone has seen. The point is that it is a decision.
    const both = entry({ id: 1, bill_id: "s1383-119", case_id: "72347022" });
    expect(entryLink(both)?.href).toBe("/bill/s1383-119");
  });
});
