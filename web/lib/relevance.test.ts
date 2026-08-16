import { describe, it, expect } from "vitest";
import { relevanceScore } from "@/lib/relevance";

// Real Federal Register titles, pinned as static strings. Unlike a date-bearing
// fixture these cannot re-date themselves, so copying them from the corpus is safe
// -- the discipline the other suites keep is about values that drift, and a
// published document's title does not.

describe("the leading word boundary", () => {
  it("does not match a term inside another word", () => {
    // The failure this closes. "election" was matching the middle of "Selection",
    // putting an H-1B immigration notice in the executive channel's relevant view.
    expect(
      relevanceScore(
        "Weighted Selection Process for Registrants and Petitioners Seeking " +
          "To File Cap-Subject H-1B Petitions",
      ),
    ).toBe(0);
  });

  it("still matches the executive orders the lens exists to surface", () => {
    expect(
      relevanceScore("Ensuring Citizenship Verification and Integrity in Federal Elections"),
    ).toBeGreaterThan(0);
  });

  it("still matches plurals and inflections", () => {
    // Why the boundary is LEADING ONLY. A trailing \b would drop every one of
    // these, which is a far bigger loss than the one false positive it removes.
    expect(relevanceScore("Elections")).toBeGreaterThan(0);
    expect(relevanceScore("Voters and voting")).toBeGreaterThan(0);
    expect(relevanceScore("Ballots cast by absentee")).toBeGreaterThan(0);
  });

  it("scores each distinct term that matches", () => {
    // The score is a count, not a boolean, and the section sorts on nothing else.
    const one = relevanceScore("Election procedures");
    const many = relevanceScore("Election and voting and ballot procedures");
    expect(many).toBeGreaterThan(one);
  });
});
