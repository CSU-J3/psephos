import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bill, Case, ExecItem, StateBill, TimelineItem } from "@/lib/db";
import type { FeedEntry } from "@/lib/feed";
import { buildTimeline } from "@/lib/timeline";
import { AheadRows, CountedList, RecordDate, RecordClockMark } from "@/components/RecordDate";
import { StateBillRow } from "@/components/StateBillRow";
import { Timeline } from "@/components/Timeline";
import { ExecutiveList } from "@/components/ExecutiveList";
import { CaseRow } from "@/components/CaseRow";
import { BillRow } from "@/components/BillRow";
import { DayTimeline } from "@/components/DayTimeline";

// THE RENDERED HALF OF THE RULE (ruled 2026-09-26). A live render shows a row dated
// ahead only while one exists -- MI HB6414 until the record's clock reaches 2026-09-29 --
// so both branches are rendered here from fixtures, every surface's own component. The
// shape asserted is the one web/scripts/assert-dated.mjs reads on the live pages: a
// `<time data-record-date>`, and a `[data-dated-ahead]` marker as its NEXT SIBLING exactly
// when the date is after the clock.
const CLOCK = "2026-09-26T11:32:04.123456+00:00";
const AHEAD = "2026-09-29T00:00:00";
const EARLIER = "2026-09-24T00:00:00";
const html = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el);
const MARKER = /<time[^>]*data-record-date="2026-09-29"[^>]*>[^<]*<\/time><span data-dated-ahead=""/;

describe("RecordDate", () => {
  it("renders a date after the clock with the marker as its next sibling, titled", () => {
    const out = html(createElement(RecordDate, { value: AHEAD, clock: CLOCK }));
    expect(out).toMatch(MARKER);
    expect(out).toContain(">dated ahead</span>");
    expect(out).toContain(
      'title="The source dates this Sep 29, 2026. This record&#x27;s clock reads Sep 26, 2026, 11:32Z."',
    );
    expect(out).toContain(">Sep 29, 2026</time>"); // the source's date, verbatim
  });

  it("renders a date up to the clock with no marker", () => {
    const out = html(createElement(RecordDate, { value: EARLIER, clock: CLOCK }));
    expect(out).toContain('data-record-date="2026-09-24"');
    expect(out).not.toContain("data-dated-ahead");
  });

  it("renders no machine date for a missing one", () => {
    const out = html(createElement(RecordDate, { value: null, clock: CLOCK }));
    expect(out).not.toContain("data-record-date");
    expect(out).toContain("—");
  });

  it("marks the page's clock once, hidden", () => {
    expect(html(createElement(RecordClockMark, { iso: CLOCK }))).toBe(
      `<span hidden="" data-record-clock="${CLOCK}"></span>`,
    );
  });
});

const stateBill = (at: string): StateBill => ({
  state_bill_id: "2158970", state: "MI", bill_number: "HB6414", session: null, title: "t",
  description: null, status: "1", url: null, is_vehicle: 0,
  last_action: "Bill Electronically Reproduced 09/24/2026", last_action_at: at,
});

describe("each surface carries the marker on a date dated ahead", () => {
  it("StateBillRow (/state-bills lists and Latest movement)", () => {
    expect(html(createElement(StateBillRow, { bill: stateBill(AHEAD), clock: CLOCK }))).toMatch(MARKER);
    expect(html(createElement(StateBillRow, { bill: stateBill(EARLIER), clock: CLOCK }))).not.toContain(
      "data-dated-ahead",
    );
  });

  it("CaseRow and BillRow", () => {
    const c = {
      case_id: "1", caption: "U.S. v. X", court: null, docket_number: null, status: null,
      category: null, filed_at: EARLIER, latest_entry_at: AHEAD, source_url: null,
      plaintiff: null, defendant: null, superseded_by: null,
    } as Case;
    expect(html(createElement(CaseRow, { c, clock: CLOCK, compact: true }))).toMatch(MARKER);
    expect(html(createElement(CaseRow, { c, clock: CLOCK }))).toMatch(MARKER);
    const b = {
      bill_id: "s1-119", bill_type: "s", number: 1, congress: 119, short_title: null, title: "t",
      sponsor: null, status: null, is_vehicle: 0, latest_action: "x", latest_action_at: AHEAD,
      introduced_at: null,
    } as Bill;
    expect(html(createElement(BillRow, { bill: b, clock: CLOCK }))).toMatch(MARKER);
  });
});

const item = (id: number, occurred_at: string): TimelineItem => ({
  id, channel: "state", title: `entry ${id}`, summary: null, source_url: "https://x",
  occurred_at, admiralty_source: "B", admiralty_info: "2",
});

describe("placement: after every row dated up to the clock, never truncated away", () => {
  it("Timeline: the ahead entry renders after the fold, outside it, marked", () => {
    const items = [item(1, AHEAD), ...Array.from({ length: 12 }, (_, i) => item(10 + i, EARLIER))];
    const out = html(createElement(Timeline, { items, clock: CLOCK }));
    // Every ledger row is its own <details>, so "the next </details>" is a row's close,
    // not the fold's (adversarial review, 2026-09-26: the first version of this test
    // passed with the ahead rows moved INSIDE the fold). The fold is the <details> whose
    // body is the folded <ol>; the ahead <ol> must open right after it closes.
    expect(out).toMatch(/<\/ol><\/details><ol data-dated-ahead-rows="">/);
    const aheadList = out.slice(out.indexOf('<ol data-dated-ahead-rows="">'));
    expect(aheadList).toContain('data-record-date="2026-09-29"');
    expect(out.indexOf('data-record-date="2026-09-29"')).toBe(out.indexOf('<ol data-dated-ahead-rows="">') + aheadList.indexOf('data-record-date="2026-09-29"'));
    expect(out).toMatch(MARKER);
  });

  // Checkpoint 2026-09-26: beside the date, the marker widened the ledger's date column
  // and pushed that one row's grade and text right of every other row. Inside the
  // fixed-width column it stacks under the date, still the `<time>`'s next sibling.
  it("Timeline: the marker stays inside the fixed-width date column", () => {
    const out = html(createElement(Timeline, { items: [item(1, AHEAD), item(2, EARLIER)], clock: CLOCK }));
    expect(out).toMatch(
      /<span class="[^"]*flex-col[^"]*w-\[6\.2rem\]"><time[^>]*data-record-date="2026-09-29"[^>]*>[^<]*<\/time><span data-dated-ahead=""[^>]*>dated ahead<\/span><\/span>/,
    );
  });

  // RULED 2026-09-26: a counted list ("ten most recent actions") keeps its count; the
  // row dated ahead sits below a divider after it. The divider is this segment's own.
  it("AheadRows: the segment dated ahead opens with a divider and holds the rows as given", () => {
    const out = html(
      createElement(AheadRows, null, createElement(StateBillRow, { bill: stateBill(AHEAD), clock: CLOCK })),
    );
    expect(out).toMatch(/^<ul data-dated-ahead-rows="" class="[^"]*border-t border-dashed[^"]*"><li>/);
    expect(out).toMatch(MARKER);
  });

  // The shape both Latest movements render (ruled 2026-09-26, ruling (c)): the counted
  // rows, then the divider, then every row dated ahead -- none cut, none among the ten.
  it("CountedList: the counted rows, then a divider, then the rows dated ahead", () => {
    const row = (b: StateBill) => createElement(StateBillRow, { key: b.state_bill_id, bill: b, clock: CLOCK });
    const ten = Array.from({ length: 10 }, (_, i) => ({ ...stateBill(EARLIER), state_bill_id: `r${i}` }));
    const out = html(createElement(CountedList<StateBill>, { rows: { recent: ten, ahead: [stateBill(AHEAD)] }, row }));
    const divider = out.indexOf("<ul data-dated-ahead-rows");
    expect(divider).toBeGreaterThan(0);
    expect((out.slice(0, divider).match(/<li>/g) ?? []).length).toBe(10);
    expect(out.slice(0, divider)).not.toContain('data-record-date="2026-09-29"');
    expect(out.slice(divider)).toMatch(MARKER);
    // No row dated ahead: no divider at all.
    const plain = html(createElement(CountedList<StateBill>, { rows: { recent: ten, ahead: [] }, row }));
    expect(plain).not.toContain("data-dated-ahead-rows");
  });

  it("ExecutiveList: a document dated ahead sorts after the rest, marked", () => {
    const exec = (id: number, at: string): ExecItem => ({
      id, title: `doc ${id}`, source_url: "https://x", occurred_at: at,
      admiralty_source: "A", admiralty_info: "1",
    });
    const out = html(createElement(ExecutiveList, { items: [exec(1, AHEAD), exec(2, EARLIER)], clock: CLOCK }));
    expect(out.indexOf("doc 2")).toBeLessThan(out.indexOf("doc 1"));
    expect(out).toMatch(MARKER);
  });
});

const feed = (id: number, occurred_at: string, fetched_at: string): FeedEntry => ({
  id, channel: "state", title: `feed ${id}`, summary: null, source_url: "https://x",
  source_id: "legiscan", occurred_at, fetched_at, admiralty_source: "B",
  admiralty_info: "2", bill_id: null, case_id: null, state_bill_id: null,
});

describe("the homepage timeline", () => {
  const anchor = new Date(CLOCK);
  const render = (rows: FeedEntry[]) =>
    html(createElement(DayTimeline, { timeline: buildTimeline(rows, anchor), anchor, windowEnd: "11:32Z" }));

  it("says each count in its own sentence, and never 'before' of a row dated after", () => {
    const out = render([
      feed(112734, AHEAD, "2026-09-24T21:35:47+00:00"),
      feed(112972, "2026-09-06T07:00:00", "2026-09-25T15:11:52+00:00"),
    ]);
    expect(out).toContain(
      "<p>1 further item collected in the record&#x27;s last 24 h is dated before these seven days.</p>" +
        "<p>1 further item is dated after these seven days.</p>",
    );
  });

  it("gives each row its own fresh dot, not its band's (ruled 2026-09-26)", () => {
    // Same band: one row collected an hour before the clock, one collected two days before.
    const out = render([
      feed(1, "2026-09-26T00:00:00", "2026-09-26T10:30:00+00:00"),
      feed(2, "2026-09-26T00:00:00", "2026-09-24T09:00:00+00:00"),
    ]);
    const dots = (out.match(/aria-label="collected in the record&#x27;s last 24 h"/g) ?? []).length;
    expect(dots).toBe(1); // the band-level flag gave both rows the dot
  });

  // News rows render through their own branch (band.news.shown), the one with the most
  // rows per band; the test above reaches only `other` (adversarial review, 2026-09-26).
  it("gives each NEWS row its own fresh dot too", () => {
    const news = (id: number, fetched_at: string): FeedEntry => ({
      ...feed(id, "2026-09-26T00:00:00+00:00", fetched_at),
      channel: "news",
      source_id: "votebeat",
    });
    const out = render([news(1, "2026-09-26T10:30:00+00:00"), news(2, "2026-09-24T09:00:00+00:00")]);
    expect(out).toContain("feed 1");
    expect(out).toContain("feed 2");
    const dots = (out.match(/aria-label="collected in the record&#x27;s last 24 h"/g) ?? []).length;
    expect(dots).toBe(1);
  });
});
