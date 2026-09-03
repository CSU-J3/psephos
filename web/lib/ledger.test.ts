import { describe, it, expect } from "vitest";
import type { TimelineItem } from "@/lib/db";
import {
  bestGrade,
  entryText,
  pagePrefix,
  promoteStatus,
  sliceLedger,
  SLICE_HEAD,
} from "@/lib/ledger";

// Fixtures, not live rows. Three of the six cases these assertions cover cannot be
// reached by any page a reader can visit -- see the "unreachable" describe blocks --
// and the reachable ones are pinned here anyway because the rules are derivations,
// which is exactly what vitest.config.ts says this suite is for.
function item(over: Partial<TimelineItem> & Pick<TimelineItem, "id" | "title">): TimelineItem {
  return {
    channel: "litigation",
    summary: null,
    source_url: "https://example.test/x",
    occurred_at: "2026-01-01T00:00:00",
    admiralty_source: "A",
    admiralty_info: "1",
    ...over,
  };
}

const CAPTION = "United States v. Hawaii: ";

describe("bestGrade", () => {
  it("is the best Admiralty grade present, not a fixed A1", () => {
    expect(bestGrade([item({ id: 1, title: "x" })])).toBe("A1");
    // The whole reason the cohort is not hardcoded to A1: every one of the 3,882
    // state-bill items is B2 and no state page holds a single A1 row.
    expect(
      bestGrade([
        item({ id: 1, title: "x", admiralty_source: "B", admiralty_info: "2" }),
        item({ id: 2, title: "y", admiralty_source: "C", admiralty_info: "3" }),
      ]),
    ).toBe("B2");
  });

  it("is null on an empty page", () => {
    expect(bestGrade([])).toBeNull();
  });
});

describe("pagePrefix", () => {
  it("finds the caption shared by every entry of the best-graded cohort", () => {
    const prefix = pagePrefix([
      item({ id: 1, title: `${CAPTION}COMPLAINT against Scott Nago` }),
      item({ id: 2, title: `${CAPTION}ORDER GRANTING MOTION TO INTERVENE` }),
      item({ id: 3, title: `${CAPTION}MOTION to Stay` }),
    ]);
    expect(prefix).toBe(CAPTION);
  });

  it("reads the cohort at B2 when the page holds no A1 row at all", () => {
    // /state-bill/2007389 in miniature. Under a literal "every A1 entry" rule this
    // page has no cohort, the prefix computes null, and every collapsed line keeps
    // "TX SB2753: " while its expansion shows LESS text than the line above it.
    const b2 = { admiralty_source: "B", admiralty_info: "2" } as const;
    expect(
      pagePrefix([
        item({ id: 1, title: "TX SB2753: Filed", ...b2 }),
        item({ id: 2, title: "TX SB2753: Read first time", ...b2 }),
      ]),
    ).toBe("TX SB2753: ");
  });

  it("ignores entries outside the cohort, so an interleaved news row cannot veto it", () => {
    // /bill/s1383-119: 18 legislation A1 rows carrying the prefix, 122 news rows
    // carrying none. The cohort is the A1 rows and the news titles are not consulted.
    const prefix = pagePrefix([
      item({ id: 1, title: "s1383-119: Received in the Senate." }),
      item({ id: 2, title: "s1383-119: On passage Passed by the Yeas and Nays" }),
      item({
        id: 3,
        channel: "news",
        title: "House passes proof-of-citizenship amendment 218-213",
        admiralty_source: "B",
        admiralty_info: "2",
      }),
    ]);
    expect(prefix).toBe("s1383-119: ");
  });

  it("computes false when the cohort's own titles disagree", () => {
    expect(
      pagePrefix([
        item({ id: 1, title: "United States v. Hawaii: COMPLAINT" }),
        item({ id: 2, title: "United States v. Oregon: COMPLAINT" }),
      ]),
    ).toBeNull();
  });

  it("computes false when the cohort carries no ': ' at all", () => {
    expect(
      pagePrefix([
        item({ id: 1, title: "Sunshine Act Meetings" }),
        item({ id: 2, title: "Sunshine Act Meetings again" }),
      ]),
    ).toBeNull();
  });

  it("computes false on an empty page", () => {
    expect(pagePrefix([])).toBeNull();
  });

  // THE SMALL-COHORT OVERSTRIP RESIDUAL, pinned as behaviour rather than fixed.
  //
  // The prefix is the longest common prefix of the cohort truncated at its last ": ".
  // With one entry in the cohort the "common prefix" is that entry's whole title, so a
  // second ": " inside the entry text is taken as part of the caption and the collapsed
  // line loses a real piece of its own text.
  //
  // It is contained by construction and that containment is the reason it is accepted:
  // the strip touches THE COLLAPSED LINE ONLY. The expanded body is a stored column
  // verbatim in all three branches, so every character remains one click away and
  // nothing is unrecoverable. Ruled 2026-09-02: pin it, do not mitigate it.
  it("overstrips a lone-entry cohort whose text holds a second ': '", () => {
    const items = [item({ id: 1, title: `${CAPTION}EO: ORDER granting the motion` })];
    expect(pagePrefix(items)).toBe(`${CAPTION}EO: `);
  });

  it("leaves the overstripped entry's stored text reachable in the body", () => {
    const it0 = item({
      id: 1,
      title: `${CAPTION}EO: ORDER granting the motion`,
      summary: null,
    });
    const text = entryText(it0, pagePrefix([it0]));
    expect(text.line).toBe("ORDER granting the motion"); // the residual, visible
    expect(text.body).toBe(`${CAPTION}EO: ORDER granting the motion`); // nothing lost
  });
});

describe("entryText — strip first, then compare", () => {
  // The assertion the whole rule turns on. `summary.startsWith(title)` is true for 0 of
  // 10,538 production items, because the collector writes title = "<caption>: " +
  // desc[:180] and summary = desc. Compared raw, the summary branch never fires and the
  // rule collapses to "always title"; compared after the strip it fires on 6,102 items.
  it("picks the summary that extends the STRIPPED title, which raw comparison misses", () => {
    const long = "COMPLAINT against Scott Nago, filed by United States of America. " +
      "(Attachments: # 1 Civil Cover Sheet)(Neff, Eric) (Entered: 12/11/2025)";
    const it0 = item({ id: 1, title: `${CAPTION}${long.slice(0, 40)}`, summary: long });

    expect(long.startsWith(it0.title)).toBe(false); // raw compare: no match, ever
    const text = entryText(it0, CAPTION);
    expect(text.line).toBe(long); // stripped compare: the full stored text wins
  });

  it("renders the extending summary once — the line carries it, the body adds nothing", () => {
    const long = "MOTION to Stay Thomas J. Hughes appearing for Defendant Scott Nago";
    const text = entryText(
      item({ id: 1, title: `${CAPTION}${long.slice(0, 20)}`, summary: long }),
      CAPTION,
    );
    expect(text.line).toBe(long);
    expect(text.body).toBeNull(); // de-dupe: the <details> un-clips the line
  });

  it("keeps both when the summary is a DIFFERENT text, not an extension", () => {
    // A news lede does not extend a headline. Both render; neither prints twice.
    const text = entryText(
      item({
        id: 1,
        channel: "news",
        title: "Judge dismisses DOJ lawsuit seeking Pennsylvania voter data",
        summary: "A federal judge dismissed the department's attempt to obtain records.",
        admiralty_source: "B",
        admiralty_info: "2",
      }),
      "s1383-119: ",
    );
    expect(text.line).toBe("Judge dismisses DOJ lawsuit seeking Pennsylvania voter data");
    expect(text.body).toBe("A federal judge dismissed the department's attempt to obtain records.");
  });

  // THE AGGREGATOR RESTATEMENT, which is neither of the two shapes the rule was written
  // for and is the single most common item on the news channel: 3,174 of 4,189. Google
  // News delivers a summary that is the headline again with "&nbsp;&nbsp; " where the
  // title has " - " before the publisher. Not an extension, so branch 1 misses it; not a
  // distinct text either, so branch 3 printed the same sentence twice -- the exact
  // double-print this handoff exists to remove, reachable today on /bill/s1383-119.
  it("folds a summary that restates the title, and keeps the cleaner of the two", () => {
    const text = entryText(
      item({
        id: 1,
        channel: "news",
        title: "Trump slips on affordability message amid battle in GOP over SAVE America Act - The Hill",
        summary: "Trump slips on affordability message amid battle in GOP over SAVE America Act &nbsp;&nbsp; The Hill",
        admiralty_source: "C",
        admiralty_info: "3",
      }),
      null,
    );
    // The title, not the summary: React prints "&nbsp;" verbatim, so of two strings
    // carrying the same words the escaped one is the wrong one to show.
    expect(text.line).toBe(
      "Trump slips on affordability message amid battle in GOP over SAVE America Act - The Hill",
    );
    expect(text.body).toBeNull();
  });

  it("does not fold a summary that merely quotes the title inside a longer, different text", () => {
    // The conservative side of the same line, and it is worth being conservative: 8 news
    // items look like extensions once punctuation is discarded but are genuinely other
    // sentences. Both texts render rather than guessing which one contains the other.
    const text = entryText(
      item({
        id: 1,
        channel: "news",
        title: "You're invited: Will the midterms happen? Your election questions, answered",
        summary: '"Will the midterms happen? Your election questions, answered" is an event hosted by Votebeat.',
        admiralty_source: "B",
        admiralty_info: "2",
      }),
      null,
    );
    expect(text.line).toBe("You're invited: Will the midterms happen? Your election questions, answered");
    expect(text.body).toContain("event hosted by Votebeat");
  });

  it("falls back to keeping both when the page prefix computed false", () => {
    // Case (b): with no strip the summary cannot extend the still-prefixed title, so
    // the row degrades to the two-text branch instead of losing the summary.
    const long = "Received in the Senate.";
    const text = entryText(
      item({ id: 1, title: `hr22-119: ${long}`, summary: long }),
      null,
    );
    expect(text.line).toBe(`hr22-119: ${long}`);
    expect(text.body).toBe(long);
  });

  it("strips the prefix from the line and leaves the body's stored text untouched", () => {
    // Case (d): title only, no summary. The one branch where the strip is visible as a
    // difference between the collapsed line and the expansion.
    const text = entryText(
      item({ id: 1, title: `${CAPTION}Order on Motion for Leave to File`, summary: null }),
      CAPTION,
    );
    expect(text.line).toBe("Order on Motion for Leave to File");
    expect(text.body).toBe(`${CAPTION}Order on Motion for Leave to File`);
  });

  it("treats a whitespace-only summary as no summary", () => {
    const text = entryText(item({ id: 1, title: `${CAPTION}Order`, summary: "   " }), CAPTION);
    expect(text.body).toBe(`${CAPTION}Order`);
  });

  it("adds no body when there is nothing to strip and no summary", () => {
    const text = entryText(item({ id: 1, title: "Sunshine Act Meetings", summary: null }), null);
    expect(text.line).toBe("Sunshine Act Meetings");
    expect(text.body).toBeNull();
  });
});

describe("promoteStatus", () => {
  const status = (id: number, tail: string) =>
    item({
      id,
      title: "United States v. Michigan — voter-data",
      summary: `Claims: 1. NVRA 2. HAVA | Status: ${tail}`,
      admiralty_source: "B",
      admiralty_info: "2",
      occurred_at: null,
    });

  it("promotes the highest id, NOT the last row in timeline order", () => {
    // Case 72347022 holds five status rows: four undated re-reads and one dated
    // 2026-02-27. The page's own `ORDER BY occurred_at, id` puts the dated row last,
    // and that row is the OLDEST by id -- so reusing the timeline's order would put a
    // stale tracker reading in the header. Measured: highest-id and timeline-last
    // disagree on all 8 multi-status cases sampled.
    const rows = [
      status(7416, "On 6/2 the court..."),
      status(19114, "On 7/9 the court..."),
      status(80308, "On 8/14 the court..."),
    ];
    rows[0] = { ...rows[0], occurred_at: "2026-02-27T00:00:00" };
    const { status: promoted, ledger } = promoteStatus(rows);
    expect(promoted?.id).toBe(80308);
    expect(ledger).toEqual([]);
  });

  it("takes every status re-read out of the ledger, docket entries stay", () => {
    const rows = [
      item({ id: 1, title: `${CAPTION}COMPLAINT`, summary: "COMPLAINT" }),
      status(50, "pending"),
      status(60, "stayed"),
      item({ id: 2, title: `${CAPTION}ORDER`, summary: "ORDER" }),
    ];
    const { status: promoted, ledger } = promoteStatus(rows);
    expect(promoted?.id).toBe(60);
    expect(ledger.map((r) => r.id)).toEqual([1, 2]);
  });

  it("leaves a B2 row on another channel alone", () => {
    // The discriminator is grade AND channel. Every one of the 3,882 state items is
    // B2 and none of them is a tracker status row.
    const rows = [
      item({
        id: 1,
        channel: "state",
        title: "TX SB2753: Filed",
        summary: "Filed",
        admiralty_source: "B",
        admiralty_info: "2",
      }),
    ];
    const { status: promoted, ledger } = promoteStatus(rows);
    expect(promoted).toBeNull();
    expect(ledger.map((r) => r.id)).toEqual([1]);
  });

  // UNREACHABLE IN PRODUCTION: all 40 cases carry at least one B2 status row, so this
  // branch draws on no page anyone can visit. Same argument as StateBillRow's Vehicle
  // badge -- a branch whose debut would be unwatched is the one worth pinning.
  it("returns no status when the page has none to promote", () => {
    const rows = [item({ id: 1, title: `${CAPTION}COMPLAINT`, summary: "COMPLAINT" })];
    const { status: promoted, ledger } = promoteStatus(rows);
    expect(promoted).toBeNull();
    expect(ledger.map((r) => r.id)).toEqual([1]);
  });

  // UNREACHABLE IN PRODUCTION: 0 cases, 0 bills and 0 state bills hold zero items.
  it("survives an empty timeline", () => {
    const { status: promoted, ledger } = promoteStatus([]);
    expect(promoted).toBeNull();
    expect(ledger).toEqual([]);
  });
});

describe("sliceLedger", () => {
  // Fixtures are handed to the function OUT OF ORDER on purpose. The three queries
  // already `ORDER BY occurred_at, id`, so a test built on pre-sorted input would pass
  // against a function that does nothing but reverse -- and would keep passing if a
  // query's ORDER BY were ever dropped. Shuffled input is what makes the assertion
  // about this function rather than about the SQL behind it.
  const row = (id: number, occurred_at: string | null, channel = "litigation") =>
    item({ id, title: `entry ${id}`, occurred_at, channel });

  const days = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      row(i + 1, `2026-01-${String(i + 1).padStart(2, "0")}T00:00:00`));

  const shuffled = (rows: TimelineItem[]) => {
    // Deterministic reordering -- odd indices first, then even, reversed.
    const odd = rows.filter((_, i) => i % 2 === 1).reverse();
    const even = rows.filter((_, i) => i % 2 === 0);
    return [...odd, ...even];
  };

  it("puts the newest first, from input in no particular order", () => {
    const { head } = sliceLedger(shuffled(days(5)));
    expect(head.map((r) => r.id)).toEqual([5, 4, 3, 2, 1]);
  });

  it("compares occurred_at as a STRING, the way the query does", () => {
    // `occurred_at` is naive on litigation rows and "+00:00"-suffixed on news, and
    // Date.parse applies the runtime's local zone to the naive form -- the whole reason
    // lib/format.ts has utcDay. SQLite compared these as TEXT; so does this. Run in a
    // zone behind UTC, a Date.parse implementation puts the naive Feb row on top.
    const naive = row(1, "2026-02-01T00:00:00", "litigation");
    const suffixed = row(2, "2026-02-01T06:00:00+00:00", "news");
    const { head } = sliceLedger([naive, suffixed]);
    expect(head.map((r) => r.id)).toEqual([2, 1]);
  });

  it("breaks a tie on id, newest id first", () => {
    const a = row(7, "2026-03-01T00:00:00");
    const b = row(9, "2026-03-01T00:00:00");
    const { head } = sliceLedger([a, b]);
    expect(head.map((r) => r.id)).toEqual([9, 7]);
  });

  it("shows everything and offers no fold at exactly the boundary", () => {
    // 403 of the 542 pages in production sit at or under 10, so this is the common
    // render rather than the edge one. /state-bill/2032448 is exactly 10.
    const { head, rest } = sliceLedger(shuffled(days(10)));
    expect(head).toHaveLength(10);
    expect(rest).toEqual([]);
  });

  it("folds exactly one entry at 11", () => {
    // Reachable: 2 cases (73544809, 73582123) and 5 state bills sit at exactly 11, so
    // the singular label draws on a real page rather than only in this file.
    const { head, rest } = sliceLedger(shuffled(days(11)));
    expect(head).toHaveLength(10);
    expect(rest.map((r) => r.id)).toEqual([1]);
  });

  it("folds the remainder on a long docket, losing nothing", () => {
    const all = days(43);
    const { head, rest } = sliceLedger(shuffled(all));
    expect(head).toHaveLength(10);
    expect(rest).toHaveLength(33);
    // The partition is total and ordered: head ++ rest is the whole list, newest-first.
    expect([...head, ...rest].map((r) => r.id)).toEqual(
      all.map((r) => r.id).reverse());
  });

  it("interleaves channels inside one slice, ordering on date and never on channel", () => {
    // The /bill/s1383-119 shape. A slice that grouped by channel would put the four
    // legislation rows together; the timeline's whole claim is that an action and the
    // reporting that explains it sit adjacent when they happened adjacently.
    const rows = [
      row(1, "2026-02-01T00:00:00", "legislation"),
      row(2, "2026-02-02T00:00:00+00:00", "news"),
      row(3, "2026-02-03T00:00:00", "legislation"),
      row(4, "2026-02-04T00:00:00+00:00", "news"),
    ];
    const { head } = sliceLedger(shuffled(rows));
    expect(head.map((r) => [r.id, r.channel])).toEqual([
      [4, "news"], [3, "legislation"], [2, "news"], [1, "legislation"],
    ]);
  });

  it("leaves an empty timeline empty, with no fold", () => {
    const { head, rest } = sliceLedger([]);
    expect(head).toEqual([]);
    expect(rest).toEqual([]);
  });

  it("does not mutate the array it was given", () => {
    // It sorts, and Array.prototype.sort is in-place. The three pages pass the same
    // array to pagePrefix and the channel-label check BEFORE slicing; reordering it
    // under them would not throw, it would quietly change what those two computed.
    const rows = shuffled(days(4));
    const before = rows.map((r) => r.id);
    sliceLedger(rows);
    expect(rows.map((r) => r.id)).toEqual(before);
  });

  it("takes a custom head size, so the constant is not baked into the split", () => {
    const { head, rest } = sliceLedger(days(5), 2);
    expect(head.map((r) => r.id)).toEqual([5, 4]);
    expect(rest.map((r) => r.id)).toEqual([3, 2, 1]);
  });

  it("SLICE_HEAD is the shipped default", () => {
    expect(SLICE_HEAD).toBe(10);
  });
});
