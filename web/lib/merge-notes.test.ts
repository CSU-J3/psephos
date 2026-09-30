import { describe, expect, it } from "vitest";
import { entriesNote, latestNote, ledgerNote, mapNote, MERGE, wireNote, type MergeFigures } from "@/lib/merge-notes";

// The D0's own figures (docs/status.md, 2026-09-30), as the switch would record them.
const F: MergeFigures = {
  on: "2026-10-02",
  why: "duplicate court-entry rows were merged",
  clock: "2026-10-02T06:30:00+00:00",
  wire: { litigation: { total: [2955, 2708], day: [7, 7], week: [594, 553] } },
  map: { entries: [4952, 4474], dockets_changed: 36 },
  cases: {
    "71457474": { entries: [230, 125], ledger: [86, 48] },
    "72026664": { latest_entry_at: ["2026-08-24T00:00:00", "2026-08-20T00:00:00"] },
  },
};

describe("the switch's dated notes", () => {
  it("say what moved, when, why, and the before and after", () => {
    expect(wireNote("litigation", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; the total 2,955 before, 2,708 after; " +
        "+7d 594 before, 553 after.",
    );
    expect(mapNote(F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged. The campaign's dockets held 4,952 " +
        "entries before, 4,474 after; 36 dockets changed.",
    );
    expect(entriesNote("71457474", F)).toBe("230 before Oct 2, 2026, when duplicate court-entry rows were merged");
    expect(ledgerNote("71457474", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; this docket read 86 entries before, 48 after.",
    );
    expect(latestNote("72026664", F)).toBe(
      "Oct 2, 2026: duplicate court-entry rows were merged; the latest entry's date read " +
        "Aug 24, 2026 before, Aug 20, 2026 after.",
    );
  });

  it("stay silent where nothing moved, on other channels, and before the switch", () => {
    expect(wireNote("news", F)).toBeNull();
    expect(ledgerNote("72026664", F)).toBeNull();
    expect(latestNote("71457474", F)).toBeNull();
    const unset = { ...F, on: null };
    expect([wireNote("litigation", unset), mapNote(unset), entriesNote("71457474", unset)]).toEqual([null, null, null]);
  });

  it("the committed figures file has the shape the notes read", () => {
    // tools/merge_notes.py writes it at the switch; until then it carries no date.
    expect(MERGE.why).toBe("duplicate court-entry rows were merged");
    expect(MERGE.on === null || /^\d{4}-\d{2}-\d{2}$/.test(MERGE.on)).toBe(true);
    expect(Array.isArray(MERGE.map.entries)).toBe(true);
  });
});
