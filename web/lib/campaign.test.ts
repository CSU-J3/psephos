import { describe, it, expect } from "vitest";
import type { CampaignRow } from "@/lib/db";
import {
  buildCells,
  continuesOf,
  summarize,
  trackerStatus,
  contestsEnding,
  isCircuit,
  daysSince,
  JURISDICTIONS,
  DORMANT_AFTER_DAYS,
} from "@/lib/campaign";

// Fixtures are CONSTRUCTED, never read from production. A concrete membership goes
// stale by build time -- the campaign's 253-day dormancy flagship left the set within
// a day of being written into a spec, and West Virginia's 91 days turned out to be a
// defective column. A test seeded from live rows inherits that half-life and starts
// failing on healthy data, which teaches the suite to be ignored. Every row below is
// shaped like the real thing and owned by the test.
//
// NOW is fixed for the same reason: dormancy is arithmetic against a clock, and a test
// that passes `new Date()` re-dates itself every run.
const NOW = new Date("2026-08-14T00:00:00Z");

function row(over: Partial<CampaignRow> & Pick<CampaignRow, "case_id" | "state">): CampaignRow {
  return {
    caption: `case ${over.case_id}`,
    court: "District of Test",
    docket_number: "1:25-cv-00001",
    status: "pending",
    filed_at: "2025-12-01T00:00:00",
    latest_entry_at: "2026-08-10T00:00:00",
    status_checked_at: "2026-08-14T00:59:00+00:00",
    // Raw docket length. Defaulted rather than made optional: CampaignRow requires it,
    // and a fixture that could omit a required field would drift from the real shape.
    entry_count: 0,
    superseded_by: null,
    source_url: null,
    ...over,
  };
}

const cellFor = (rows: CampaignRow[], name: string) =>
  buildCells(rows, NOW).find((c) => c.name === name)!;

describe("the 51-cell census", () => {
  it("covers 50 states plus DC with unique codes", () => {
    expect(JURISDICTIONS).toHaveLength(51);
    expect(new Set(JURISDICTIONS.map(([, code]) => code)).size).toBe(51);
    expect(JURISDICTIONS.map(([name]) => name)).toContain("DC");
  });

  it("renders every jurisdiction even when nothing was sued", () => {
    const cells = buildCells([], NOW);
    expect(cells).toHaveLength(51);
    expect(cells.every((c) => c.status === "none")).toBe(true);
    expect(summarize(cells)).toMatchObject({ sued: 0, none: 51, chains: 0, dormant: 0 });
  });
});

describe("chain traversal", () => {
  // superseded_by is set on the DEAD row pointing forward, so the live row is the one
  // carrying null. Getting this backwards would render the terminated docket as live.
  const chain = [
    row({ case_id: "P", state: "Pennsylvania", status: "terminated",
          court: "Western District of Pennsylvania", docket_number: "2:25-cv-01481",
          superseded_by: "S" }),
    row({ case_id: "S", state: "Pennsylvania", court: "Third Circuit",
          docket_number: "26-2684" }),
  ];

  it("puts the live docket on the cell and the terminated one behind it", () => {
    const c = cellFor(chain, "Pennsylvania");
    expect(c.live?.case_id).toBe("S");
    expect(c.predecessors.map((p) => p.case_id)).toEqual(["P"]);
    expect(c.status).toBe("active");
  });

  it("calls a district-to-circuit continuation an appeal", () => {
    expect(cellFor(chain, "Pennsylvania").chain).toBe("appeal");
  });

  it("calls an intra-state district-to-district continuation a refile", () => {
    // Georgia: M.D. Ga. terminated, N.D. Ga. live. No circuit step, so not an appeal --
    // and the two rows must collapse into ONE cell, not two Georgias. The artifact
    // disambiguates them as `Georgia (1)` / `Georgia (2)`; normalize_state strips that
    // upstream, so by the time rows reach here both read `Georgia`.
    const ga = [
      row({ case_id: "G1", state: "Georgia", status: "terminated",
            court: "Middle District of Georgia", docket_number: "5:25-cv-00548",
            superseded_by: "G2" }),
      row({ case_id: "G2", state: "Georgia", court: "Northern District of Georgia",
            docket_number: "1:26-cv-00485" }),
    ];
    const cells = buildCells(ga, NOW);
    expect(cells.filter((c) => c.name === "Georgia")).toHaveLength(1);
    const c = cellFor(ga, "Georgia");
    expect(c.chain).toBe("refile");
    expect(c.live?.case_id).toBe("G2");
    expect(summarize(cells).sued).toBe(1);
  });

  it("counts one chain per jurisdiction across the real seven-pair shape", () => {
    // Six appeals and one refile, which is the campaign's actual composition.
    const pairs: Array<[string, string, string]> = [
      ["Pennsylvania", "Western District of Pennsylvania", "Third Circuit"],
      ["New Hampshire", "District of New Hampshire", "First Circuit"],
      ["Maryland", "District of Maryland", "Fourth Circuit"],
      ["New Mexico", "District of New Mexico", "Tenth Circuit"],
      ["Virginia", "Eastern District of Virginia", "Fourth Circuit"],
      ["Kentucky", "Eastern District of Kentucky", "Sixth Circuit"],
      ["Georgia", "Middle District of Georgia", "Northern District of Georgia"],
    ];
    const rows = pairs.flatMap(([state, from, to], i) => [
      row({ case_id: `d${i}`, state, court: from, status: "terminated", superseded_by: `s${i}` }),
      row({ case_id: `s${i}`, state, court: to }),
    ]);
    const cells = buildCells(rows, NOW);
    const s = summarize(cells);
    expect(s.sued).toBe(7);
    expect(s.chains).toBe(7);
    expect(cells.filter((c) => c.chain === "appeal")).toHaveLength(6);
    expect(cells.filter((c) => c.chain === "refile")).toHaveLength(1);
  });
});

describe("the three cell states", () => {
  it("treats a pending live docket as active", () => {
    expect(cellFor([row({ case_id: "A", state: "Nevada" })], "Nevada").status).toBe("active");
  });

  it("treats a state with no rows as none, and does not link it", () => {
    const c = cellFor([row({ case_id: "A", state: "Nevada" })], "Ohio");
    expect(c.status).toBe("none");
    expect(c.live).toBeNull();
    expect(c.chain).toBeNull();
  });

  it("treats Michigan's terminated circuit row as ended, keeping the court", () => {
    // The cell that forced three states rather than two: terminated at a CIRCUIT with
    // no successor and no district row held. Collapsed into "not active" it would read
    // identically to a district dismissal, losing that this is an appellate loss. The
    // court is what the ended prose row renders, so assert it survives on the cell.
    const mi = [row({ case_id: "72347022", state: "Michigan", status: "terminated",
                      court: "Sixth Circuit", docket_number: "26-1225" })];
    const c = cellFor(mi, "Michigan");
    expect(c.status).toBe("ended");
    expect(c.chain).toBeNull();
    expect(c.live?.court).toBe("Sixth Circuit");
    expect(isCircuit(c.live!.court)).toBe(true);
  });

  it("never flags a terminated docket as dormant, however old", () => {
    // Finished is not quiet. Oklahoma is terminated at 143 days and belongs in ended.
    const ok = [row({ case_id: "OK", state: "Oklahoma", status: "terminated",
                      latest_entry_at: "2026-03-24T00:00:00" })];
    const c = cellFor(ok, "Oklahoma");
    expect(c.status).toBe("ended");
    expect(c.quietDays).toBeGreaterThan(DORMANT_AFTER_DAYS);
    expect(c.dormant).toBe(false);
  });
});

describe("the display invariant: no row is dropped", () => {
  // THE WINDOW. Between a successor landing and its supersession being asserted, a
  // state holds TWO rows with superseded_by IS NULL. buildCells used to take the
  // most recently filed as `live` and drop the other on the floor -- it is not a
  // predecessor (that requires superseded_by), so no section could render it.
  //
  // Observed on CT and NY: the cell flipped active on the live Second Circuit row,
  // `Ended in this record` fell 8 -> 6, and the district dismissal appeared nowhere
  // on the page. KY, VA and NM each passed through it unobserved. The window
  // reopens whenever the tracker rewrites a row before the pair is asserted, which
  // is the ordinary case rather than the exotic one.
  const window = [
    row({ case_id: "CT-D", state: "Connecticut", status: "terminated",
          court: "District of Connecticut", docket_number: "3:26-cv-00021",
          filed_at: "2025-11-01T00:00:00" }),
    row({ case_id: "CT-C", state: "Connecticut", court: "Second Circuit",
          docket_number: "26-2064", filed_at: "2026-07-28T00:00:00" }),
  ];

  it("keeps an unlinked terminated row reachable instead of discarding it", () => {
    const c = cellFor(window, "Connecticut");
    expect(c.live?.case_id).toBe("CT-C");
    expect(c.status).toBe("active");
    // Nothing is asserted between them, so this is NOT a chain -- rendering it as
    // one would invent the link the record does not have.
    expect(c.chain).toBeNull();
    expect(c.predecessors).toEqual([]);
    expect(c.unlinked.map((r) => r.case_id)).toEqual(["CT-D"]);
  });

  it("holds the partition total for every cell, which is the invariant itself", () => {
    // The property, not an instance: each input row appears in exactly one of
    // live / predecessors / unlinked. This is what stops the next bucket from being
    // added by quietly dropping rows again.
    const mixed = [
      ...window,
      row({ case_id: "NV", state: "Nevada" }),                       // single live
      row({ case_id: "P", state: "Pennsylvania", status: "terminated",
            superseded_by: "S" }),                                   // linked chain
      row({ case_id: "S", state: "Pennsylvania", court: "Third Circuit" }),
      row({ case_id: "MI", state: "Michigan", status: "terminated",
            court: "Sixth Circuit" }),                               // ended, final
    ];
    const cells = buildCells(mixed, NOW);
    const seen = cells.flatMap((c) => [
      ...(c.live ? [c.live.case_id] : []),
      ...c.predecessors.map((r) => r.case_id),
      ...c.unlinked.map((r) => r.case_id),
    ]);
    expect(seen.sort()).toEqual(mixed.map((r) => r.case_id).sort());
    expect(new Set(seen).size).toBe(mixed.length);   // exactly one bucket each
  });

  it("prefers a pending row as live even when the terminated one was filed later", () => {
    // Filing order alone is not the rule. A successor is normally filed later, so
    // filed_at picked correctly by luck; invert it and the old rule would put a
    // terminated docket on the cell and call the whole state ended.
    const inverted = [
      row({ case_id: "LIVE", state: "Maine", filed_at: "2025-01-01T00:00:00" }),
      row({ case_id: "DEAD", state: "Maine", status: "terminated",
            filed_at: "2026-08-01T00:00:00" }),
    ];
    const c = cellFor(inverted, "Maine");
    expect(c.live?.case_id).toBe("LIVE");
    expect(c.status).toBe("active");
    expect(c.unlinked.map((r) => r.case_id)).toEqual(["DEAD"]);
  });

  it("stays empty on healthy data, so the new section is an alarm and not decoration", () => {
    const healthy = [
      row({ case_id: "NV", state: "Nevada" }),
      row({ case_id: "P", state: "Pennsylvania", status: "terminated", superseded_by: "S" }),
      row({ case_id: "S", state: "Pennsylvania", court: "Third Circuit" }),
      row({ case_id: "MI", state: "Michigan", status: "terminated", court: "Sixth Circuit" }),
    ];
    const cells = buildCells(healthy, NOW);
    expect(cells.every((c) => c.unlinked.length === 0)).toBe(true);
    expect(summarize(cells).unlinkedEndings).toBe(0);
  });

  it("counts cells, not rows, the same way chains and dormant do", () => {
    const two = [
      ...window,
      row({ case_id: "NY-D", state: "New York", status: "terminated",
            court: "Northern District of New York", filed_at: "2025-11-01T00:00:00" }),
      row({ case_id: "NY-C", state: "New York", court: "Second Circuit",
            filed_at: "2026-07-28T00:00:00" }),
    ];
    expect(summarize(buildCells(two, NOW)).unlinkedEndings).toBe(2);
  });
});

describe("dormancy", () => {
  const quiet = (latest: string) =>
    cellFor([row({ case_id: "H", state: "Hawaii", latest_entry_at: latest })], "Hawaii");

  it("counts whole days in UTC from a naive ISO date", () => {
    expect(daysSince("2026-04-27T00:00:00", NOW)).toBe(109);
    expect(daysSince("2026-08-14T00:00:00", NOW)).toBe(0);
    expect(daysSince(null, NOW)).toBeNull();
    expect(daysSince("not a date", NOW)).toBeNull();
  });

  it("flags past the threshold and not at it", () => {
    expect(quiet("2026-04-27T00:00:00").dormant).toBe(true);      // 109d
    expect(quiet("2026-06-15T00:00:00").dormant).toBe(false);     // 60d, the boundary
    expect(quiet("2026-06-14T00:00:00").dormant).toBe(true);      // 61d
  });

  it("carries the receipt on a pending cell so the page can date the silence", () => {
    // status_checked_at, never entries_synced_at -- the latter is an upstream
    // date_modified high-water held on empty windows, so it reports psephos asleep on
    // a docket it just polled. It is not even selected by getCampaignRows, and the
    // CampaignRow type has no field for it; this asserts the right one arrives.
    const c = quiet("2026-04-27T00:00:00");
    expect(c.live?.status_checked_at).toBe("2026-08-14T00:59:00+00:00");
    expect(c.live).not.toHaveProperty("entries_synced_at");
  });

  it("tolerates a missing latest_entry_at rather than counting from epoch", () => {
    const c = cellFor([row({ case_id: "N", state: "Nevada", latest_entry_at: null })], "Nevada");
    expect(c.quietDays).toBeNull();
    expect(c.dormant).toBe(false);
  });
});

describe("tracker prose", () => {
  const NOTES =
    "Claims: 1. National Voter Registration Act 2. HAVA | Status: On 7/23/26, DOJ filed " +
    "a notice that it will appeal the district court's dismissal to the 2nd Circuit. | " +
    "Key decisions: District Court's 7/10/26 dismissal.";

  it("pulls only the Status segment out of the three-field string", () => {
    expect(trackerStatus(NOTES)).toBe(
      "On 7/23/26, DOJ filed a notice that it will appeal the district court's " +
        "dismissal to the 2nd Circuit.",
    );
  });

  it("returns null on prose with no segments, which is what the config seeds carry", () => {
    expect(trackerStatus("Challenges the DOJ master voter database under the Privacy Act."))
      .toBeNull();
    expect(trackerStatus(undefined)).toBeNull();
  });

  it("flags Connecticut's ending as contested, and a plain dismissal as not", () => {
    // CT is the live fixture: a terminated district row whose tracker line names an
    // appeal psephos holds no successor for. Both sources render and the disagreement
    // is flagged rather than resolved, per the spec's grading rule.
    expect(contestsEnding(trackerStatus(NOTES))).toBe(true);
    expect(contestsEnding("On 8/3/26, the district dismissed DOJ's claims on the merits."))
      .toBe(false);
    expect(contestsEnding("The parties settled on 3/24/2026.")).toBe(false);
    expect(contestsEnding(null)).toBe(false);
  });
});

describe("continuesOf -- the reverse chain direction", () => {
  // The defect this replaced rendered BOTH directions on the predecessor, pointing
  // at the same id: "continued as 73582123 - continues 73582123" on the Western
  // District of Pennsylvania row, while the Third Circuit row that actually
  // continues it said nothing. All twelve chained jurisdictions rendered that way
  // in production. Asserted here as the TRUTH of the claim, not its presence.
  const pred = row({ case_id: "71453026", state: "Pennsylvania", superseded_by: "73582123" });
  const succ = row({ case_id: "73582123", state: "Pennsylvania" });
  const group = [pred, succ];

  it("puts 'continues' on the SUCCESSOR, naming the predecessor", () => {
    expect(continuesOf(group, succ)).toEqual(["71453026"]);
  });

  it("puts NOTHING on the predecessor -- it is continued as, not continuing", () => {
    expect(continuesOf(group, pred)).toEqual([]);
  });

  it("never names a row as continuing itself", () => {
    for (const r of group) expect(continuesOf(group, r)).not.toContain(r.case_id);
  });

  it("returns every predecessor when a successor absorbs more than one", () => {
    const a = row({ case_id: "a", state: "Test", superseded_by: "z" });
    const b = row({ case_id: "b", state: "Test", superseded_by: "z" });
    const z = row({ case_id: "z", state: "Test" });
    expect(continuesOf([a, b, z], z).sort()).toEqual(["a", "b"]);
  });
});
