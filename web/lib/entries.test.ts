import { describe, expect, it } from "vitest";
import { earlierTexts, entryOf, seenLabel, type HistoryRow } from "@/lib/entries";

const row = (o: Partial<HistoryRow> & Pick<HistoryRow, "id" | "cl_entry_id" | "description">): HistoryRow => ({
  twin_of: null,
  current_row: null,
  entry_at: "2026-08-21T00:00:00",
  seen_at: null,
  seen_by: null,
  ...o,
});

describe("earlierTexts", () => {
  it("lists an entry's earlier description once, leaving out the text the row shows", () => {
    // #141 on 71499795: the short form, then the full text, one CourtListener record.
    const history = [
      row({ id: 86725, cl_entry_id: 475375313, current_row: 86794,
            description: "Notice of Appeal to DC Circuit", seen_at: "2026-08-21T20:00:00Z" }),
      row({ id: 86794, cl_entry_id: 475375313, current_row: 86794,
            description: "NOTICE OF APPEAL TO DC CIRCUIT COURT", seen_at: "2026-08-22T08:00:00Z" }),
    ];
    const [got] = earlierTexts(history, [{ cl_entry_id: 475375313, summary: "NOTICE OF APPEAL TO DC CIRCUIT COURT" }]);
    expect(got).toEqual([{ text: "Notice of Appeal to DC Circuit", entry_at: "2026-08-21T00:00:00",
                           seen_at: "2026-08-21T20:00:00Z", seen_by: null, twin: false }]);
  });

  it("puts a tier-2 twin's text under the entry it folds into, marked as a second record", () => {
    const history = [
      row({ id: 67589, cl_entry_id: 471527695, current_row: 67589,
            description: "MINUTE ORDER: The Court has reviewed" }),
      row({ id: 67651, cl_entry_id: 471517786, twin_of: 471527695, current_row: 67651,
            description: "Order on Motion to Enforce" }),
    ];
    // The item presenting the pair is the short form's own (earliest fetched), showing the long form.
    const [got] = earlierTexts(history, [{ cl_entry_id: 471517786, summary: "MINUTE ORDER: The Court has reviewed" }]);
    expect(got?.map((e) => [e.text, e.twin])).toEqual([["Order on Motion to Enforce", true]]);
  });

  it("returns nothing for an item with no record or an entry never re-described", () => {
    const history = [row({ id: 1, cl_entry_id: 9, current_row: 1, description: "ORDER one" })];
    expect(earlierTexts(history, [{ cl_entry_id: null, summary: "x" }, { cl_entry_id: 9, summary: "ORDER one" }]))
      .toEqual([undefined, undefined]);
  });

  it("leaves out the entry's current ROW, so a re-date lists the old date's row", () => {
    // Nevada 72026664: one text, re-dated Aug 24 -> Aug 20. Two rows, one words.
    const history = [
      row({ id: 1, cl_entry_id: 9, current_row: 2, description: "USCA Order Time Schedule",
            entry_at: "2026-08-24T00:00:00", seen_at: "2026-08-25T00:00:00Z" }),
      row({ id: 2, cl_entry_id: 9, current_row: 2, description: "USCA Order Time Schedule",
            entry_at: "2026-08-20T00:00:00", seen_at: "2026-08-26T00:00:00Z" }),
    ];
    const [got] = earlierTexts(history, [{ cl_entry_id: 9, summary: "USCA Order Time Schedule" }]);
    expect(got?.map((e) => [e.entry_at, e.seen_at])).toEqual([["2026-08-24T00:00:00", "2026-08-25T00:00:00Z"]]);
  });

  it("follows a twin chain to its end and survives a cycle", () => {
    const map = new Map<number, number | null>([[1, 2], [2, 3], [3, null]]);
    expect(entryOf(1, map)).toBe(3);
    const loop = new Map<number, number | null>([[1, 2], [2, 1]]);
    expect([1, 2]).toContain(entryOf(1, loop));
  });
});

describe("seenLabel", () => {
  it("names one day when psephos knows it, and a range when it can only bound it", () => {
    expect(seenLabel({ seen_at: "2026-07-20T19:31:18Z", seen_by: null })).toBe("seen Jul 20, 2026");
    expect(seenLabel({ seen_at: "2026-07-20T10:00:00+00:00", seen_by: "2026-07-20T10:05:00+00:00" }))
      .toBe("seen Jul 20, 2026");
    expect(seenLabel({ seen_at: "2026-07-20T10:00:00+00:00", seen_by: "2026-07-22T18:00:00+00:00" }))
      .toBe("seen between Jul 20, 2026 and Jul 22, 2026");
    expect(seenLabel({ seen_at: null, seen_by: null })).toBe("seen: not recorded");
  });
});
