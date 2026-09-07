import { describe, it, expect } from "vitest";
import { canonicalCourt, COURT_ALIASES } from "@/lib/court";
import { isCircuit, buildCells } from "@/lib/campaign";
import type { CampaignRow } from "@/lib/db";

describe("canonicalCourt", () => {
  it("maps UW's two spellings onto the courts' names", () => {
    expect(canonicalCourt("Eighth District")).toBe("Eighth Circuit");
    expect(canonicalCourt("DC Circuit")).toBe("D.C. Circuit");
  });

  it("passes an unrecognized court through unchanged rather than guessing", () => {
    // The bridge covers the two spellings actually observed. A third one must reach
    // the page looking wrong, not be silently repaired into something plausible --
    // silent repair is how the first two survived seventeen days.
    expect(canonicalCourt("Ninth Circuit")).toBe("Ninth Circuit");
    expect(canonicalCourt("Western District of Michigan")).toBe("Western District of Michigan");
    expect(canonicalCourt("Fifth District")).toBe("Fifth District");
    expect(canonicalCourt("")).toBe("");
  });

  it("passes null through", () => {
    expect(canonicalCourt(null)).toBeNull();
  });

  it("is idempotent, because readers get canonical values and may re-apply it", () => {
    for (const [raw, name] of Object.entries(COURT_ALIASES)) {
      expect(canonicalCourt(canonicalCourt(raw))).toBe(name);
      expect(canonicalCourt(name)).toBe(name);
    }
  });

  it("never maps two spellings onto each other's court", () => {
    // A transposed alias would classify correctly and render a real court name, so
    // nothing downstream could catch it. Pin the pairs.
    expect(COURT_ALIASES["Eighth District"]).not.toContain("D.C.");
    expect(COURT_ALIASES["DC Circuit"]).not.toContain("Eighth");
  });
});

describe("isCircuit through canonicalCourt", () => {
  it("is TRUE on 'Eighth District' -- the whole point of the bridge", () => {
    // Before canonicalization this read false: /\bcircuit\b/ does not match
    // 'Eighth District', so Minnesota's cell would have drawn the refile glyph for a
    // circuit appeal.
    expect(isCircuit("Eighth District")).toBe(true);
    expect(isCircuit("Eighth Circuit")).toBe(true);
  });

  it("was already TRUE on 'DC Circuit', which is why only MN's glyph moves", () => {
    expect(isCircuit("DC Circuit")).toBe(true);
    expect(isCircuit("D.C. Circuit")).toBe(true);
  });

  it("stays FALSE on districts and on null", () => {
    expect(isCircuit("District of Minnesota")).toBe(false);
    expect(isCircuit("Northern District of Georgia")).toBe(false);
    expect(isCircuit(null)).toBe(false);
    expect(isCircuit("")).toBe(false);
  });
});

describe("chain kind on the two Unit A pairs", () => {
  const row = (r: Partial<CampaignRow>): CampaignRow => ({
    case_id: "x", state: "Minnesota", caption: "United States v. X", court: null,
    docket_number: null, status: "pending", filed_at: null, latest_entry_at: null,
    status_checked_at: null, superseded_by: null, source_url: null, entry_count: 0,
    ...r,
  });
  const cellFor = (state: string, rows: CampaignRow[]) =>
    buildCells(rows, new Date("2026-09-07T00:00:00Z")).find((c) => c.name === state)!;

  it("MN reads 'appeal', not 'refile', on the tracker's spelling", () => {
    const c = cellFor("Minnesota", [
      row({ case_id: "71453336", state: "Minnesota", status: "terminated",
            court: "District of Minnesota", superseded_by: "74687843" }),
      row({ case_id: "74687843", state: "Minnesota", court: "Eighth District",
            docket_number: "26-2679", filed_at: "2026-08-21T00:00:00" }),
    ]);
    expect(c.live?.case_id).toBe("74687843");
    expect(c.chain).toBe("appeal");
    // And the stored string reaches the derivation canonicalized, so the page renders
    // the court's name while the database keeps UW's.
    expect(canonicalCourt(c.live!.court)).toBe("Eighth Circuit");
  });

  it("DC reads 'appeal' too", () => {
    const c = cellFor("DC", [
      row({ case_id: "72055344", state: "DC", status: "terminated",
            court: "District of Columbia", superseded_by: "74671625" }),
      row({ case_id: "74671625", state: "DC", court: "DC Circuit",
            docket_number: "26-5296", filed_at: "2026-08-19T00:00:00" }),
    ]);
    expect(c.chain).toBe("appeal");
  });
});
