import { describe, it, expect } from "vitest";
import type { CampaignRow } from "@/lib/db";
import { buildCells } from "@/lib/campaign";
import {
  isMember,
  latestMovement,
  membersOf,
  sectionByState,
  sectionOf,
  SECTION_ORDER,
  type MovementRow,
} from "@/lib/movement";

// Constructed fixtures, never read from production -- the rule campaign.test.ts states
// and the dormancy set kept demonstrating: a fixture copied from live data re-dates
// itself and pins nothing. NOW is fixed for the same reason, since dormancy is
// arithmetic against a clock.
const NOW = new Date("2026-09-02T00:00:00Z");

function row(over: Partial<CampaignRow> & Pick<CampaignRow, "case_id" | "state">): CampaignRow {
  return {
    caption: `case ${over.case_id}`,
    court: "District of Test",
    docket_number: "1:25-cv-00001",
    status: "pending",
    filed_at: "2025-06-01",
    latest_entry_at: "2026-09-01T00:00:00",
    status_checked_at: "2026-09-01T00:00:00",
    superseded_by: null,
    source_url: null,
    entry_count: 3,
    ...over,
  };
}

const cellFor = (rows: CampaignRow[], name: string) =>
  buildCells(rows, NOW).find((c) => c.name === name)!;

function mv(over: Partial<MovementRow> & Pick<MovementRow, "id">): MovementRow {
  return {
    case_id: "c1",
    state: "Nevada",
    occurred_at: "2026-08-20T00:00:00",
    text: "District docket 3:25-cv-00728 terminated.",
    grade: "A1",
    ...over,
  };
}

describe("section membership", () => {
  it("puts a terminated-only jurisdiction in ended", () => {
    const c = cellFor([row({ case_id: "A", state: "Michigan", status: "terminated" })], "Michigan");
    expect(isMember(c, "ended")).toBe(true);
    expect(isMember(c, "continued")).toBe(false);
  });

  it("puts a jurisdiction with a predecessor in continued", () => {
    const c = cellFor(
      [
        row({ case_id: "old", state: "Oregon", status: "terminated", superseded_by: "new" }),
        row({ case_id: "new", state: "Oregon", court: "Ninth Circuit" }),
      ],
      "Oregon",
    );
    expect(isMember(c, "continued")).toBe(true);
  });

  it("puts a jurisdiction holding an unlinked ending in unlinked", () => {
    const c = cellFor(
      [
        row({ case_id: "live", state: "Colorado" }),
        row({ case_id: "dead", state: "Colorado", status: "terminated" }),
      ],
      "Colorado",
    );
    expect(isMember(c, "unlinked")).toBe(true);
    // The cell itself is live -- the ending is beside it, not on it.
    expect(isMember(c, "ended")).toBe(false);
  });

  it("puts a long-silent live docket in quiet", () => {
    const c = cellFor(
      [row({ case_id: "A", state: "Hawaii", latest_entry_at: "2026-01-01T00:00:00" })],
      "Hawaii",
    );
    expect(isMember(c, "quiet")).toBe(true);
  });

  it("membersOf and isMember cannot disagree", () => {
    const cells = buildCells(
      [
        row({ case_id: "A", state: "Michigan", status: "terminated" }),
        row({ case_id: "B", state: "Hawaii", latest_entry_at: "2026-01-01T00:00:00" }),
      ],
      NOW,
    );
    for (const key of SECTION_ORDER) {
      expect(membersOf(cells, key)).toEqual(cells.filter((c) => isMember(c, key)));
    }
  });
});

describe("which section a cell opens", () => {
  // THE OVERLAP THE MOCK HARDCODED. Arizona is continued AND quiet; its roster entry
  // appears in both while its grid cell can open only one. The mock answered with a
  // state->section map, which is correct until the overlaps move and silent about why.
  it("sends a continued-and-quiet jurisdiction to continued, not quiet", () => {
    const c = cellFor(
      [
        row({ case_id: "old", state: "Arizona", status: "terminated", superseded_by: "new" }),
        row({
          case_id: "new",
          state: "Arizona",
          court: "Ninth Circuit",
          latest_entry_at: "2026-01-01T00:00:00", // long silent -> also quiet
        }),
      ],
      "Arizona",
    );
    expect(isMember(c, "continued")).toBe(true);
    expect(isMember(c, "quiet")).toBe(true);
    expect(sectionOf(c)).toBe("continued");
  });

  // Disjoint today, not by construction -- handoff 92. A jurisdiction whose every
  // unsuperseded docket is terminated lands in both, so the order gets exercised.
  it("sends an ended-and-unlinked jurisdiction to ended", () => {
    const c = cellFor(
      [
        row({ case_id: "a", state: "Michigan", status: "terminated" }),
        row({ case_id: "b", state: "Michigan", status: "terminated" }),
      ],
      "Michigan",
    );
    expect(isMember(c, "ended")).toBe(true);
    expect(isMember(c, "unlinked")).toBe(true);
    expect(sectionOf(c)).toBe("ended");
  });

  // NULL IS A REAL ANSWER. Nine sued jurisdictions are live and plain -- not continued,
  // unlinked, ended or quiet. The mock never shows one.
  it("returns null for a live docket in no section", () => {
    const c = cellFor([row({ case_id: "A", state: "Maine" })], "Maine");
    expect(sectionOf(c)).toBeNull();
  });

  it("returns null for a jurisdiction never sued", () => {
    const c = cellFor([row({ case_id: "A", state: "Maine" })], "Texas");
    expect(c.status).toBe("none");
    expect(sectionOf(c)).toBeNull();
  });

  it("omits sectionless jurisdictions from the lookup rather than mapping them to a default", () => {
    const cells = buildCells(
      [
        row({ case_id: "A", state: "Maine" }),
        row({ case_id: "B", state: "Michigan", status: "terminated" }),
      ],
      NOW,
    );
    const by = sectionByState(cells);
    expect(by.get("MI")).toBe("ended");
    expect(by.has("ME")).toBe(false);
    expect(by.has("TX")).toBe(false);
  });
});

describe("latest movement", () => {
  it("takes the most recent first and caps at eight by default", () => {
    const rows = Array.from({ length: 12 }, (_, i) =>
      mv({ id: i, occurred_at: `2026-08-${String(i + 1).padStart(2, "0")}T00:00:00` }),
    );
    const top = latestMovement(rows);
    expect(top).toHaveLength(8);
    expect(top[0].id).toBe(11);
    expect(top[7].id).toBe(4);
  });

  it("stops short when there are fewer than the limit", () => {
    expect(latestMovement([mv({ id: 1 }), mv({ id: 2 })])).toHaveLength(2);
  });

  it("honours an explicit limit", () => {
    const rows = [mv({ id: 1 }), mv({ id: 2 }), mv({ id: 3 })];
    expect(latestMovement(rows, 2).map((r) => r.id)).toEqual([3, 2]);
  });

  // A docket walk writes a whole history at one timestamp and a collector run writes
  // many rows inside one second, so the tie is the common case, not the edge.
  it("breaks a same-timestamp tie on id descending, deterministically", () => {
    const same = "2026-08-28T00:00:00";
    const rows = [
      mv({ id: 5, occurred_at: same }),
      mv({ id: 9, occurred_at: same }),
      mv({ id: 7, occurred_at: same }),
    ];
    expect(latestMovement(rows).map((r) => r.id)).toEqual([9, 7, 5]);
  });

  // Naive timestamps and bare dates both appear on this column; comparing the strings
  // keeps them comparable without normalising either, and never shifts a calendar day.
  it("compares strings, so a bare date orders against a naive timestamp", () => {
    const rows = [
      mv({ id: 1, occurred_at: "2026-08-28" }),
      mv({ id: 2, occurred_at: "2026-08-28T14:02:00" }),
    ];
    expect(latestMovement(rows).map((r) => r.id)).toEqual([2, 1]);
  });

  it("does not mutate the rows it was handed", () => {
    const rows = [mv({ id: 1, occurred_at: "2026-01-01" }), mv({ id: 2, occurred_at: "2026-09-01" })];
    latestMovement(rows);
    expect(rows.map((r) => r.id)).toEqual([1, 2]);
  });

  it("is empty on no rows", () => {
    expect(latestMovement([])).toEqual([]);
  });
});
