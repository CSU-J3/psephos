import { describe, expect, it } from "vitest";
import {
  entriesNote,
  latestNote,
  ledgerNote,
  mapNote,
  MERGE,
  rejectedNote,
  wireNote,
  type MergeFigures,
  type Move,
} from "@/lib/merge-notes";

// The tier-1 merge as the D0 measured it (docs/status.md, 2026-09-30), and the tier-2 links
// as a second move with its own date (Corey, 2026-10-02).
const MERGE_MOVE: Move = {
  kind: "merge",
  on: "2026-10-02",
  why: "duplicate court-entry rows were merged",
  clock: "2026-10-02T06:30:00+00:00",
  wire: { litigation: { total: [2955, 2619], day: [7, 7], week: [594, 551], history: [2, 2], tracker_notes: 89 } },
  rejected: { count: [19, 19], states: {} },
  map: { entries: [4952, 4474], dockets_changed: 36, apart: 0 },
  cases: {
    "71457474": { entries: [230, 125], ledger: [86, 48] },
    "72026664": { latest_entry_at: ["2026-08-24T00:00:00", "2026-08-20T00:00:00"] },
  },
};
const LINK_MOVE: Move = {
  kind: "link",
  on: "2026-10-03",
  why: "pairs of court records that describe one entry were linked",
  clock: "2026-10-03T06:30:00+00:00",
  links: 7,
  wire: { litigation: { total: [2619, 2614], day: [7, 7], week: [551, 551], history: [2, 2] } },
  rejected: { count: [19, 19], states: {} },
  map: { entries: [4474, 4471], dockets_changed: 3 },
  cases: { "71457474": { entries: [125, 124] } },
};
const F: MergeFigures = { on: "2026-10-02", clock: MERGE_MOVE.clock, moves: [MERGE_MOVE] };
const BOTH: MergeFigures = { ...F, moves: [MERGE_MOVE, LINK_MOVE] };

describe("the switch's dated notes", () => {
  it("say what moved, when, why, and the before and after", () => {
    expect(wireNote("litigation", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows and repeated tracker notes were merged (89 tracker notes " +
        "of the drop); the total 2,955 before, 2,619 after; +7d 594 before, 551 after.",
    );
    expect(mapNote(F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged. The campaign's dockets held 4,952 " +
        "entries before, 4,474 after; 36 dockets changed.",
    );
    expect(entriesNote("71457474", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; 230 before, 125 after.",
    );
    expect(ledgerNote("71457474", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; this docket read 86 entries before, 48 after.",
    );
    expect(latestNote("72026664", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; the latest entry's date read " +
        "Aug 24, 2026 before, Aug 20, 2026 after.",
    );
  });

  it("give a tier-2 link its own dated note, a line after the merge's, where it moved the figure", () => {
    // Counted (Corey, 2026-10-04, amending 2026-10-02): each note's headline number is the
    // change on its own surface. The Wire leads with the items it merged, the pairs linked
    // its context; the map panel and a docket line count the entries' drop, one per pair.
    expect(wireNote("litigation", BOTH)).toBe(
      "Oct 2, 2026: duplicate court-entry rows and repeated tracker notes were merged (89 tracker notes " +
        "of the drop); the total 2,955 before, 2,619 after; +7d 594 before, 551 after.\n" +
        "Oct 3, 2026: 5 duplicate items merged (2,619 before, 2,614 after), from 7 entry pairs linked.",
    );
    expect(entriesNote("71457474", BOTH)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; 230 before, 125 after.\n" +
        "Oct 3, 2026: 1 pair of court records that describe one entry was linked; 125 before, 124 after.",
    );
    expect(mapNote(BOTH)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged. The campaign's dockets held 4,952 " +
        "entries before, 4,474 after; 36 dockets changed.\nOct 3, 2026: 3 pairs of court records that " +
        "describe one entry were linked. The campaign's dockets held 4,474 entries before, 4,471 after; 3 dockets changed.",
    );
    // Where only the merge moved the figure, the link adds nothing.
    expect(ledgerNote("71457474", BOTH)).toBe(ledgerNote("71457474", F));
    expect(latestNote("72026664", BOTH)).toBe(latestNote("72026664", F));
    // A docket's ledger leads with its own drop, the docket's pairs (its entry count's drop)
    // its context.
    const LWV: MergeFigures = {
      ...BOTH,
      moves: [MERGE_MOVE, { ...LINK_MOVE, cases: { "71499795": { entries: [239, 234], ledger: [139, 134] } } }],
    };
    expect(ledgerNote("71499795", LWV)).toBe(
      "Oct 3, 2026: 5 duplicate entries merged (139 before, 134 after), from 5 entry pairs linked.",
    );
  });

  it("count a link's own drop where a twin carried no item, the pairs linked as context", () => {
    // Corey's two examples (2026-10-04): 259 pairs merge 120 items on the Wire, and 28 pairs
    // 18 entries on a docket's ledger, because a twin with no item takes nothing off them.
    const BATCH: Move = {
      ...LINK_MOVE,
      on: "2026-10-04",
      links: 259,
      wire: { litigation: { total: [2754, 2634], day: [0, 0], week: [43, 43], history: [0, 0] } },
      map: { entries: [4754, 4572], dockets_changed: 24 },
      cases: {
        "73133197": { entries: [210, 182], ledger: [201, 183], timeline: [201, 183] },
        "72193752": { entries: [234, 213] },
        "1": { entries: [5, 4], ledger: [10, 9] },
        "2": { ledger: [7, 6] },
      },
    };
    const G: MergeFigures = { ...F, moves: [BATCH] };
    expect(wireNote("litigation", G)).toBe(
      "Oct 4, 2026: 120 duplicate items merged (2,754 before, 2,634 after), from 259 entry pairs linked.",
    );
    expect(ledgerNote("73133197", G)).toBe(
      "Oct 4, 2026: 18 duplicate entries merged (201 before, 183 after), from 28 entry pairs linked.",
    );
    expect(ledgerNote("1", G)).toBe("Oct 4, 2026: 1 duplicate entry merged (10 before, 9 after), from 1 entry pair linked.");
    // A ledger that moved where the entries did not counts its own drop as the pairs.
    expect(ledgerNote("2", G)).toBe("Oct 4, 2026: 1 duplicate entry merged (7 before, 6 after), from 1 entry pair linked.");
    // The Wire's other windows that moved follow the total inside the brackets.
    const W: MergeFigures = { ...F, moves: [{ ...BATCH, wire: { litigation: { ...BATCH.wire.litigation!, week: [589, 588] } } }] };
    expect(wireNote("litigation", W)).toBe(
      "Oct 4, 2026: 120 duplicate items merged (2,754 before, 2,634 after; +7d 589 before, 588 after), " +
        "from 259 entry pairs linked.",
    );
    // The map stays as built: its lines and panel count entries, one per pair.
    expect(entriesNote("72193752", G)).toBe(
      "Oct 4, 2026: 21 pairs of court records that describe one entry were linked; 234 before, 213 after.",
    );
    expect(mapNote(G)).toBe(
      "Oct 4, 2026: 182 pairs of court records that describe one entry were linked. The campaign's dockets " +
        "held 4,754 entries before, 4,572 after; 24 dockets changed.",
    );
    // A link move that does not say how many pairs it linked keeps its reason on the Wire.
    const { links: _links, ...unsaid } = BATCH;
    expect(wireNote("litigation", { ...F, moves: [unsaid] })).toBe(
      "Oct 4, 2026: pairs of court records that describe one entry were linked; the total 2,754 before, 2,634 after.",
    );
  });

  it("never call a rise a merge, and name the court-entry reason alone when no note folded", () => {
    const G: MergeFigures = {
      ...F,
      moves: [{
        ...MERGE_MOVE,
        map: { entries: [10, 11], dockets_changed: 1, apart: 1 },
        cases: {
          "1": { entries: [10, 11], apart: 1 },          // only a rise: nothing merged here
          "2": { entries: [22, 24], apart: 2 },          // Oklahoma's shape on 2026-10-02
          "3": { entries: [70, 69], apart: 1 },          // two rows merged, one entry apart
        },
        wire: { litigation: { total: [5, 4], day: [0, 0], week: [0, 0], history: [3, 2], tracker_notes: 0 } },
      }],
    };
    expect(entriesNote("1", G)).toBe(
      "Oct 2, 2026: 1 entry that shared another entry's text and day now counted apart; 10 before, 11 after.",
    );
    expect(entriesNote("2", G)).toBe(
      "Oct 2, 2026: 2 entries that shared another entry's text and day now counted apart; 22 before, 24 after.",
    );
    expect(entriesNote("3", G)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged, and 1 entry that shared another entry's text " +
        "and day now counted apart; 70 before, 69 after.",
    );
    expect(mapNote(G)).toBe(
      "Oct 2, 2026: 1 entry that shared another entry's text and day now counted apart. The campaign's " +
        "dockets held 10 entries before, 11 after; 1 docket changed.",
    );
    expect(wireNote("litigation", G)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; the total 5 before, 4 after; " +
        "already older than 7 days when collected 3 before, 2 after.",
    );
  });

  it("note the rejected-demands figure only when the outcome moved", () => {
    expect(rejectedNote(BOTH)).toBeNull();
    const G: MergeFigures = {
      ...F,
      moves: [{ ...MERGE_MOVE, rejected: { count: [19, 18], states: { Nevada: ["2026-08-20", null] } } }],
    };
    expect(rejectedNote(G)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged, and the outcome now reads each entry's " +
        "current text; 19 before, 18 after (Nevada).",
    );
  });

  it("stay silent where nothing moved, on other channels, and before the switch", () => {
    expect(wireNote("news", BOTH)).toBeNull();
    expect(ledgerNote("72026664", BOTH)).toBeNull();
    expect(latestNote("71457474", BOTH)).toBeNull();
    const unset = { ...BOTH, on: null };
    expect([wireNote("litigation", unset), mapNote(unset), entriesNote("71457474", unset)]).toEqual([null, null, null]);
  });

  it("the committed figures file has the shape the notes read", () => {
    // tools/merge_notes.py writes it at the switch; until then it carries no date.
    expect(MERGE.on === null || /^\d{4}-\d{2}-\d{2}$/.test(MERGE.on)).toBe(true);
    expect(Array.isArray(MERGE.moves)).toBe(true);
    for (const mv of MERGE.moves) {
      expect(["merge", "link"]).toContain(mv.kind);
      expect(Array.isArray(mv.map.entries)).toBe(true);
    }
  });
});
