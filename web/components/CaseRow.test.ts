import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Case } from "@/lib/db";
import { CaseRow } from "@/components/CaseRow";

// THE RAIL'S CLASS MARK, RENDERED. The section's count and the rail's mark share one
// predicate (lib/stands.ts#isEoChallenge) but read `category` through two SELECTs,
// `getDocketRows` and `getCases`. No DOM lane can see the mark before the seeds land,
// since production holds no marked row, so this fixture render is the automated guard.
const CLOCK = "2026-09-26T11:32:04.123456+00:00";
const html = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el);
const MARK = /data-class-mark="eo-challenge"/;

function row(category: string | null): Case {
  return {
    case_id: "73133197", caption: "League of Women Voters of Massachusetts v. Trump",
    court: "D. Mass.", docket_number: "1:26-cv-11549", status: "pending", category,
    filed_at: "2026-04-02T00:00:00", latest_entry_at: "2026-09-24T00:00:00",
    source_url: null, plaintiff: "League of Women Voters of Massachusetts",
    defendant: "Trump", superseded_by: null,
  };
}

describe("the rail marks the EO class, and only it", () => {
  it("marks a compact row whose category is executive-order, once", () => {
    const out = html(createElement(CaseRow, { c: row("executive-order"), clock: CLOCK, compact: true }));
    expect(out).toMatch(MARK);
    expect(out.match(/data-class-mark=/g)).toHaveLength(1);
    expect(out).toContain("EO challenge");
  });

  it("does not mark a voter-data row, or a row with no category", () => {
    for (const category of ["voter-data", null]) {
      const out = html(createElement(CaseRow, { c: row(category), clock: CLOCK, compact: true }));
      expect(out).not.toMatch(/data-class-mark/);
    }
  });

  it("does not mark the full card, which carries its own category badge instead", () => {
    const out = html(createElement(CaseRow, { c: row("executive-order"), clock: CLOCK }));
    expect(out).not.toMatch(/data-class-mark/);
  });
});
