import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DayTimeline } from "@/components/DayTimeline";
import { buildTimeline } from "@/lib/timeline";
import type { FeedEntry } from "@/lib/feed";

// THE PURE TEST CANNOT SEE WHETHER THE LABEL REACHES THE PAGE.
//
// entryLink is pure and lib/feed.test.ts pins every branch of it, so what is left is the
// wiring: a component that resolved the link and then rendered the anchor id anyway
// would leave those assertions green while the slug went on printing. The defect being
// fixed here was exactly a rendering one -- the record held a correct caption the whole
// time and one function on the way to the DOM read past it -- so a pure test alone would
// have been the wrong instrument for it.
//
// THIS TESTS DayTimeline, AND THE COMPONENT NAMED AFTER THE FEED IS WHY THAT IS WORTH
// SAYING. `ActivityFeed` also called entryLink and was the obvious file to test -- and
// it was mounted by no route, having gone up in a9fb298 and come down in 4703298 when
// the day-grouped timeline replaced it. A render test on it would have covered dead
// code while the live surface stayed untested, which is worse than no test because it
// reads as coverage. It has since been deleted; this note stays because the trap was
// the NAME, and the next reader looking for "the feed" will still start there.
//
// No jsdom: renderToStaticMarkup only, same as StateMatrix.test.ts, on constructed
// fixtures through the real buildTimeline the page uses.
const NOW = new Date("2026-08-14T12:00:00Z");

function entry(over: Partial<FeedEntry> & Pick<FeedEntry, "id">): FeedEntry {
  return {
    channel: "litigation",
    title: `item ${over.id}`,
    summary: null,
    source_url: "https://example.test/a",
    source_id: "courtlistener",
    occurred_at: "2026-08-14T00:00:00+00:00",
    fetched_at: "2026-08-14T06:00:00+00:00",
    admiralty_source: "A",
    admiralty_info: "1",
    bill_id: null,
    case_id: null,
    state_bill_id: null,
    ...over,
  };
}

const render = (rows: FeedEntry[]) =>
  renderToStaticMarkup(
    createElement(DayTimeline, { timeline: buildTimeline(rows, NOW), now: NOW }),
  );

const slugCase = (over: Partial<FeedEntry> = {}) =>
  entry({
    id: 1,
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
    ...over,
  });

describe("DayTimeline — the anchor chip", () => {
  it("prints the caption, not the slug key", () => {
    const html = render([slugCase()]);
    expect(html).toContain("United States v. Minnesota");
    // The slug stays legitimately in the href, so this asserts on rendered TEXT rather
    // than on the whole document -- otherwise the href would mask the regression.
    const asText = [...html.matchAll(/>([^<>]*united-states-v[^<>]*)</g)].map((m) => m[1]);
    expect(asText).toEqual([]);
  });

  // THE FOURTH INSTANCE, and the only one that reached a reader. A litigation entry
  // routes into the band's docket GROUP, whose header hardcoded `case ${caseId}` and
  // never called entryLink -- so fixing entryLink alone would have left the live page
  // printing exactly the slug this unit was opened about. Measured on the running
  // homepage before the fix: four occurrences of `case <id>` as visible text.
  it("names the docket group, which never went through entryLink at all", () => {
    const html = render([slugCase(), slugCase({ id: 9 })]);
    expect(html).toContain("United States v. Minnesota");
    expect(html).not.toMatch(/>\s*case\s*<!-- -->/);
  });

  // THE SEED ROW IS THE ONLY PLACE DayTimeline CALLS entryLink WITH A CASE, and it
  // needed its own test rather than being assumed covered. A case entry inside the
  // window routes to the docket GROUP, which labels through anchorLabel -- so every
  // other assertion here exercises that path and none of them touches entryLink's case
  // arm. Back-history entries become "added to the record" seed rows instead, and
  // SeedLine labels those through entryLink. Two labelling paths, one component; a
  // suite that only knew about the first would report the second as covered.
  it("names a seeded docket, the one path here that labels through entryLink", () => {
    const html = render([
      slugCase({
        id: 8,
        occurred_at: "2025-09-01T00:00:00+00:00", // long before it was collected
        fetched_at: "2026-08-14T06:00:00+00:00", // -> isHistoryEntry, so a seed row
      }),
    ]);
    expect(html).toContain("United States v. Minnesota");
    expect(html).not.toMatch(/>[^<>]*united-states-v[^<>]*</);
  });

  it("still routes on the id it stopped displaying", () => {
    expect(render([slugCase()])).toContain('href="/case/united-states-v-minnesota"');
  });

  it("names a state bill rather than printing a bare LegiScan id", () => {
    const html = render([
      entry({
        id: 2,
        channel: "state",
        state_bill_id: "1890243",
        anchor: {
          kind: "state",
          id: "1890243",
          state: "TX",
          bill_number: "HB1235",
          title: "Relating to the ability of a voter registrar",
        },
      }),
    ]);
    expect(html).toContain("TX HB1235");
    expect(html).toContain('href="/state-bill/1890243"');
    expect(html).not.toMatch(/>[^<>]*\b1890243\b[^<>]*</);
  });

  it("names a bill rather than printing its slug key", () => {
    const html = render([
      entry({
        id: 3,
        channel: "legislation",
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
    ]);
    expect(html).toContain("S. 1383");
    expect(html).toContain('href="/bill/s1383-119"');
  });

  // The fallback has to survive the render too. An entry can carry an id with no
  // dimension row behind it, and a component assuming an anchor would throw rather than
  // degrade -- on what is by a wide margin the most common path.
  it("falls back to the id when the entry carries no anchor", () => {
    const html = render([entry({ id: 4, case_id: "72347022" })]);
    expect(html).toContain("case 72347022");
    expect(html).toContain('href="/case/72347022"');
  });

  it("renders an unanchored news item with no chip at all", () => {
    const html = render([entry({ id: 5, channel: "news", source_id: "google-news" })]);
    expect(html).toContain("item 5");
    expect(html).not.toContain("/case/");
    expect(html).not.toContain("/bill/");
  });
});

// THE LEDGER ROW, added when the feed's rows went single-line. What is worth pinning is
// not that the row renders -- it is visible on the page -- but the TRADE the shape makes.
// A one-line row has to drop something when the title is long, and which thing it drops
// is a decision the page cannot show you until a long title arrives on a narrow column.
// The title truncates because it is a link and is recoverable; the grade does not,
// because a story whose grade scrolled off is exactly what this project refuses to show.
// Those two classes sit on two different elements and nothing but a test says they must.
describe("DayTimeline — the ledger row", () => {
  const long = (over: Partial<FeedEntry> = {}) =>
    entry({
      id: 40,
      channel: "news",
      title: "A".repeat(400),
      source_id: "democracy-docket",
      admiralty_source: "B",
      admiralty_info: "2",
      ...over,
    });

  it("truncates the title rather than wrapping it", () => {
    // Pinned to the title element's own class string, not to the bare word: `truncate`
    // appears on the docket row too, so a looser assertion would pass with the news
    // title wrapping exactly as it did before the ledger.
    expect(render([long()])).toContain("min-w-0 flex-1 truncate");
  });

  it("keeps the grade off the truncating element, so it cannot be clipped away", () => {
    const html = render([long()]);
    // The grade sits in a shrink-0 group; were it inside the truncating title, a long
    // headline would push the provenance out of the row entirely. Asserting the group's
    // own class string, so moving the grade into the title fails here.
    expect(html).toContain("flex shrink-0 items-baseline gap-2");
    expect(html).toContain("B2");
  });

  it("names the delivering source on the row", () => {
    expect(render([long()])).toContain("democracy-docket");
  });

  it("still renders the anchor link beside the row it belongs to", () => {
    // The entryLink path the file above exists to cover: the ledger reshaped the row
    // around it and must not have dropped it.
    const html = render([long({ bill_id: "s1383-119" })]);
    expect(html).toContain("/bill/s1383-119");
  });

  it("renders a docket entry on one line under its caption", () => {
    const html = render([
      slugCase({ id: 50, summary: "ORDER granting motion to extend time." }),
    ]);
    expect(html).toContain("ORDER granting motion to extend time.");
    expect(html).toContain("A1");
  });
});
