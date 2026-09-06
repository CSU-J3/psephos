import { describe, expect, it } from "vitest";
import {
  cumulativeRejections,
  rejectedStates,
  rejections,
  type DocketEntry,
  type TerminatedCase,
} from "@/lib/outcomes";

// Fixtures are REAL DOCKET TEXT, trimmed, from the twenty terminated campaign dockets
// this rule was measured against. Paraphrased text would test the paraphrase: every
// near-miss below is a sentence a court actually wrote, and the two hardest cases in
// the corpus are the two the handoff named in advance.
const CASES: TerminatedCase[] = [
  { case_id: "71452580", state: "California", date_terminated: "2026-01-15T00:00:00" },
  { case_id: "72336804", state: "Oklahoma", date_terminated: "2026-04-17T00:00:00" },
  { case_id: "72053306", state: "Georgia", date_terminated: "2026-01-23T00:00:00" },
  { case_id: "72055344", state: "DC", date_terminated: "2026-08-06T00:00:00" },
  { case_id: "72347022", state: "Michigan", date_terminated: "2026-06-24T00:00:00" },
];

const ENTRIES: DocketEntry[] = [
  // CALIFORNIA -- REJECTED THEN APPEALED. The order is in the window; the notice of
  // appeal three weeks later quotes the order's title and must not match.
  {
    case_id: "71452580",
    entry_at: "2026-01-14",
    description:
      "Order by Judge David O. Carter: Per the Court's Order on 12/8/25 [Dkt. 98], the Court accepts all amicus briefs filed by the 12/22/2025 deadline.",
  },
  {
    case_id: "71452580",
    entry_at: "2026-01-15",
    description:
      "ORDER by Judge David O. Carter: Granting 37 Defendant's MOTION to Dismiss and Intervenors' Motions to Dismiss [62-1], 67 . Therefore, the motions are DISMISSED WITHOUT LEAVE TO AMEND. (MD JS-6. Case Terminated)",
  },
  {
    case_id: "71452580",
    entry_at: "2026-02-25",
    description:
      "NOTICE OF APPEAL to the 9th Circuit Court of Appeals filed by Plaintiff United States of America. Appeal of Order on Motion to Dismiss,, Order on Motion for Leave to File Document,,, 128 .",
  },
  // OKLAHOMA -- WITHDRAWN, NOT REJECTED. DOJ dismissed its own suit, and the docket
  // carries nothing at all on the termination date.
  {
    case_id: "72336804",
    entry_at: "2026-03-24",
    description: "NOTICE of Voluntary Dismissal by United States of America (Gardner, Christopher)",
  },
  // GEORGIA -- FORUM, NOT MERITS. Dismissed without prejudice for want of jurisdiction
  // and refiled in N.D. Ga., where it is live.
  {
    case_id: "72053306",
    entry_at: "2026-01-23",
    description:
      "ORDER DISMISSING CASE WITHOUT PREJUDICE. This Court finds it lacks subject matter jurisdiction over this action and DISMISSES this action without prejudice. re 1 Complaint (IFP)",
  },
  { case_id: "72053306", entry_at: "2026-01-23", description: "JUDGMENT of Dismissal. (ksl)" },
  // DC -- THE DEMAND REFUSED WITH NO DISMISSAL IN THE SENTENCE.
  {
    case_id: "72055344",
    entry_at: "2026-08-06",
    description:
      "ORDER: For the reasons explained in the Court's memorandum opinion, Dkt. 80, it is hereby ORDERED that Plaintiff's motion to compel records, Dkt. 2, is DENIED; Defendants' motion to dismiss, Dkt. 41, is DENIED as MOOT",
  },
  // MICHIGAN -- THE APPELLATE FORM.
  {
    case_id: "72347022",
    entry_at: "2026-06-24",
    description:
      "OPINION and JUDGMENT filed : AFFIRMED. Mandate to issue. Decision for publication. R. Guy Cole, Jr., John B. Nalbandian (DISSENTING), and Andre B. Mathis (AUTHORING), Circuit Judges.",
  },
];

describe("rejections", () => {
  it("finds a rejected-then-appealed docket and dates it to the order", () => {
    // The handoff's own example: teal over a live-red fill. The event is the ruling,
    // not the end of the litigation, so an appeal does not undo it.
    const r = rejections(CASES, ENTRIES).find((x) => x.state === "California");
    expect(r).toBeDefined();
    expect(r!.rejected_at).toBe("2026-01-15");
    expect(r!.pattern).toBe("mtd-granted");
  });

  it("does not match the notice of appeal that quotes the order's title", () => {
    // Without the party-filing gate this dates California to 2026-02-25 -- the loser's
    // own paperwork read as the ruling against it.
    const r = rejections(CASES, ENTRIES).filter((x) => x.state === "California");
    expect(r).toHaveLength(1);
    expect(r[0].rejected_at).not.toBe("2026-02-25");
  });

  it("excludes a voluntary dismissal: the plaintiff withdrew, no court ruled", () => {
    expect(rejections(CASES, ENTRIES).some((x) => x.state === "Oklahoma")).toBe(false);
  });

  it("excludes a jurisdictional dismissal that was refiled elsewhere", () => {
    // "ORDER DISMISSING CASE" matches a reject pattern on its face; the jurisdictional
    // gate is the only thing standing between Georgia and a teal stroke over a suit
    // that is still running in another district of the same state.
    expect(rejections(CASES, ENTRIES).some((x) => x.state === "Georgia")).toBe(false);
  });

  it("counts a denied motion to compel with no dismissal in the sentence", () => {
    const r = rejections(CASES, ENTRIES).find((x) => x.state === "DC");
    expect(r?.pattern).toBe("compel-denied");
  });

  it("counts an appellate affirmance", () => {
    const r = rejections(CASES, ENTRIES).find((x) => x.state === "Michigan");
    expect(r?.pattern).toBe("affirmed");
  });

  it("ignores an order outside the termination window", () => {
    // The defect the window exists for: an interlocutory order using terminal
    // vocabulary, months before the disposition. Unscoped, this is what dated Colorado
    // to March and New York to January.
    const early: DocketEntry[] = [
      {
        case_id: "71452580",
        entry_at: "2025-11-17",
        description: "ORDER denying 2 MOTION to Compel Production of Documents without prejudice",
      },
    ];
    expect(rejections([CASES[0]], early)).toHaveLength(0);
  });

  it("takes one rejection per docket when the disposition is entered several times", () => {
    // Arizona enters an order, an amended order and two clerk's judgments on one day.
    const az: TerminatedCase[] = [
      { case_id: "72110941", state: "Arizona", date_terminated: "2026-04-28" },
    ];
    const many: DocketEntry[] = [
      {
        case_id: "72110941",
        entry_at: "2026-04-28",
        description:
          "ORDER granting Secretary Fontes' Motion to Dismiss (Doc. 25 ) and dismissing the case.",
      },
      {
        case_id: "72110941",
        entry_at: "2026-04-28",
        description:
          "AMENDED CLERK'S JUDGMENT - final judgment is entered. Plaintiff to take nothing, and the complaint and action are hereby dismissed.",
      },
    ];
    expect(rejections(az, many)).toHaveLength(1);
  });

  it("skips a case with no termination date rather than guessing", () => {
    const undated: TerminatedCase[] = [
      { case_id: "71452580", state: "California", date_terminated: "" },
    ];
    expect(rejections(undated, ENTRIES)).toHaveLength(0);
  });
});

describe("rejectedStates", () => {
  it("dedupes to jurisdictions", () => {
    const s = rejectedStates(rejections(CASES, ENTRIES));
    expect([...s].sort()).toEqual(["California", "DC", "Michigan"]);
  });
});

describe("cumulativeRejections", () => {
  it("accumulates by date with a running total", () => {
    const steps = cumulativeRejections(rejections(CASES, ENTRIES));
    expect(steps.map((s) => s.date)).toEqual(["2026-01-15", "2026-06-24", "2026-08-06"]);
    expect(steps.map((s) => s.total)).toEqual([1, 2, 3]);
  });

  it("counts a jurisdiction once, at its earliest rejection", () => {
    // The line shares a ceiling with the red one, which cannot exceed 51 because a
    // jurisdiction is sued once. A state rejected in a district AND on appeal would
    // push this line past that ceiling if it accumulated rows rather than states.
    const twice = [
      { state: "Michigan", case_id: "a", rejected_at: "2026-03-01", pattern: "mtd-granted" },
      { state: "Michigan", case_id: "b", rejected_at: "2026-06-24", pattern: "affirmed" },
    ];
    const steps = cumulativeRejections(twice);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({ date: "2026-03-01", total: 1, added: 1 });
  });
});
