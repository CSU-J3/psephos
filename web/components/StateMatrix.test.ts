import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StateBill } from "@/lib/db";
import { StateMatrix } from "@/components/StateMatrix";
import { StateBillRow } from "@/components/StateBillRow";
import {
  buildMatrix,
  STAGE_ORDER,
  UNSTAGED_LABEL,
  UNSTAGED_LABEL_MIXED,
  UNSTAGED_STYLE,
} from "@/lib/statebill";
import { EXPECTED } from "../scripts/encodings.expected.mjs";
import { offRampCount, RAMP_CODES, reconcileSets } from "../scripts/reconcile.mjs";

// THE FIRST COMPONENT IN THIS APP WHOSE CORRECTNESS A RENDER COULD NOT SHOW.
//
// vitest.config.ts declines component rendering on the grounds that the read layer's
// components are thin and what they do is visible at the render. That reasoning failed
// here first; other component tests have since argued their own exceptions in their
// headers. The matrix's seventh column draws only when a bill carries no stage the ramp
// knows. Through 484 rows none did, and the branch was dead code waiting to execute first
// in production. It did: on 2026-09-25 the state run 36131273689 wrote PA HR632 with a
// null status, and on 2026-09-26 assert-encodings.mjs failed on it, as it was written to.
// The column is now keyed, but it is still DATA-CONDITIONAL -- it disappears again the
// day no bill lacks a stage -- so a render of live data can show either branch and never
// both. This file renders both.
//
// So the exception is narrow and argued rather than a general loosening. No jsdom and no
// testing library -- renderToStaticMarkup is in react-dom, which is already a dependency,
// and static markup is all an assertion about which columns exist needs.

function bill(over: Partial<StateBill> & Pick<StateBill, "state_bill_id" | "state">): StateBill {
  return {
    bill_number: "HB1",
    session: "2025",
    title: `bill ${over.state_bill_id}`,
    description: null,
    status: "1",
    url: null,
    is_vehicle: 0,
    last_action: "Referred to Elections",
    last_action_at: "2025-03-10",
    ...over,
  };
}

const render = (bills: StateBill[]) =>
  renderToStaticMarkup(createElement(StateMatrix, { matrix: buildMatrix(bills) }));

// The markup a single state's row emits, sliced out by its label link.
function rowMarkup(html: string, state: string): string {
  const rows = html.split("<tr");
  const row = rows.find((r) => r.includes(`>${state}</a>`));
  if (!row) throw new Error(`no row for ${state} in rendered matrix`);
  return row;
}

// Every number the row actually PAINTED, in column order. Zero cells render a middot
// rather than a "0", so they contribute nothing here -- which is the point: this reads
// what a person would read off the screen, not what the model holds.
function numbersIn(row: string): number[] {
  return [...row.matchAll(/>(\d+)</g)].map((m) => Number(m[1]));
}

const CLEAN = [
  bill({ state_bill_id: "1", state: "TX", status: "4" }),
  bill({ state_bill_id: "2", state: "TX", status: "4" }),
  bill({ state_bill_id: "3", state: "TX", status: "1" }),
  bill({ state_bill_id: "4", state: "WI", status: "6" }),
];

describe("StateMatrix — the unstaged column", () => {
  it("draws no seventh column while every bill carries a known stage", () => {
    const html = render(CLEAN);
    expect(html).not.toContain(UNSTAGED_LABEL);
    expect(html).not.toContain('data-encoding="unstaged"');
    // Six stage headers plus All, and nothing else.
    expect(html).toContain("Introduced");
    expect(html).toContain("Failed");
  });

  it("draws the seventh column as soon as one bill carries an unknown stage code", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: "9" })]);
    expect(html).toContain('data-encoding="unstaged"');
  });

  it("draws it for a null status too, not only an unrecognised code", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: null })]);
    expect(html).toContain(UNSTAGED_LABEL);
  });

  // THE ASSERTION THE COLUMN EXISTS FOR. Without it the unknown bill either vanishes
  // from the page or inflates the row total past the sum of its own cells, and both
  // read as clean data. This checks the RENDERED numbers, so it fails if the column is
  // computed correctly and then not drawn.
  it("keeps a row's total equal to the sum of the cells it painted", () => {
    const html = render([
      ...CLEAN,
      bill({ state_bill_id: "5", state: "TX", status: "9" }),
      bill({ state_bill_id: "6", state: "TX", status: null }),
    ]);
    const painted = numbersIn(rowMarkup(html, "TX"));
    const total = painted[painted.length - 1];
    const cells = painted.slice(0, -1);
    expect(total).toBe(5); // 3 clean TX bills + the two unstaged
    expect(cells.reduce((a, b) => a + b, 0)).toBe(total);
    expect(cells).toContain(2); // the unstaged pair, drawn rather than swallowed
  });

  it("holds the same arithmetic on the totals row", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "TX", status: "9" })]);
    const painted = numbersIn(rowMarkup(html, "All states"));
    const total = painted[painted.length - 1];
    expect(total).toBe(5);
    expect(painted.slice(0, -1).reduce((a, b) => a + b, 0)).toBe(total);
  });

  it("still balances every row when the unknown code is the only thing a state has", () => {
    const html = render([...CLEAN, bill({ state_bill_id: "5", state: "AZ", status: "unknown" })]);
    for (const state of ["AZ", "TX", "WI"]) {
      const painted = numbersIn(rowMarkup(html, state));
      const total = painted[painted.length - 1];
      expect(painted.slice(0, -1).reduce((a, b) => a + b, 0)).toBe(total);
    }
  });
});

// ---------------------------------------------------------------------------------
// THE KEY ENTRY. Until it was keyed, this header carried `data-unreachable` and no
// `data-encoding`; PA HR632 reached the branch on 2026-09-25 and the ruling was to key
// it. What these assert is the same join assert-encodings.mjs runs against the live page,
// run here on markup from a fixture so both branches -- keyed and absent -- are
// exercised every time.

// One bill at every rung of the ramp, so all six stage encodings are claimed, plus a
// status-less bill so the conditional one is too.
const RAMP = ["1", "2", "3", "4", "5", "6"].map((status, i) =>
  bill({ state_bill_id: `r${i}`, state: "TX", status }),
);
const OFF_RAMP = bill({ state_bill_id: "hr632", state: "PA", status: null, last_action: null, last_action_at: null });

// The page the script sweeps, reduced to its two painters: the matrix (the key and the
// counts) and a list of rows (the ticks and chips).
const page = (bills: StateBill[]) =>
  render(bills) +
  bills.map((b) => renderToStaticMarkup(createElement(StateBillRow, { bill: b }))).join("");

// The two sides of the join, read the way the script reads them. NAMED is every
// data-encoding inside the one data-key block. CLAIMED is what record() claims: each key
// header's own dot -- record() claims before it consults the key, so a key entry with a
// swatch is itself a claim -- plus every data-stage anywhere.
const keyBlock = (html: string) => /<thead data-key="">([\s\S]*?)<\/thead>/.exec(html)?.[1] ?? "";
function named(html: string): string[] {
  return [...keyBlock(html).matchAll(/data-encoding="([^"]+)"/g)].map((m) => m[1]);
}
function claimed(html: string): string[] {
  const dots = [...keyBlock(html).matchAll(/<th[^>]*data-encoding="([^"]+)"[^>]*><span[^>]*style=/g)];
  const stages = [...html.matchAll(/data-stage="([^"]+)"/g)];
  return [...dots, ...stages].map((m) => m[1]);
}
const attr = (tag: string, name: string) => new RegExp(`${name}="([^"]*)"`).exec(tag)?.[1];

describe("StateMatrix — the unstaged key entry", () => {
  it("names the column in the key, with its paint declared and no unreachable marker", () => {
    const html = render([...CLEAN, OFF_RAMP]);
    const header = /<th[^>]*data-encoding="unstaged"[^>]*>/.exec(html)?.[0];
    expect(header).toBeDefined();
    expect(named(html)).toContain("unstaged");
    expect(html).not.toContain("data-unreachable");
    expect(attr(header!, "data-paint-dot")).toBe(UNSTAGED_STYLE.dot);
    expect(attr(header!, "data-paint-cell")).toBe(UNSTAGED_STYLE.cell);
    expect(attr(header!, "data-paint-tick")).toBe(UNSTAGED_STYLE.tick);
    expect(attr(header!, "data-paint-chip")).toBe(UNSTAGED_STYLE.chip);
  });

  // The page's own ruling, applied to the new entry: the key's swatch IS the ink. And
  // the 2026-09-26 ruling on the dashed tick: swatch and tick stay one grey.
  it("declares a swatch equal to the ink its counts are painted in, and to its tick", () => {
    expect(UNSTAGED_STYLE.dot).toBe(UNSTAGED_STYLE.cell);
    expect(UNSTAGED_STYLE.tick).toBe(UNSTAGED_STYLE.dot);
  });

  it("claims the encoding on a non-zero count, painted in the declared ink, and middots a zero", () => {
    const html = render([...CLEAN, OFF_RAMP]);
    const pa = rowMarkup(html, "PA");
    expect(pa).toContain('data-stage="unstaged"');
    expect(pa).toContain(`color:${UNSTAGED_STYLE.cell}`);
    // TX has no off-ramp bill: its unstaged cell is the ordinary zero, not a claim. TX
    // has zero stage cells too, so compare against the same row without the column: the
    // column adds exactly one middot.
    const zeros = (row: string) => (row.match(/data-zero/g) ?? []).length;
    const tx = rowMarkup(html, "TX");
    expect(tx).not.toContain('data-stage="unstaged"');
    expect(zeros(tx)).toBe(zeros(rowMarkup(render(CLEAN), "TX")) + 1);
  });
});

describe("StateMatrix — the reconciliation, run on rendered markup", () => {
  it("reconciles cleanly when a status-less bill is present: expected, claimed and named", () => {
    const r = reconcileSets(EXPECTED.stateBills, claimed(page([...RAMP, OFF_RAMP])), named(page([...RAMP, OFF_RAMP])));
    expect(r.expected).toContain("unstaged");
    expect(r.conditionalAbsent).toEqual([]);
    expect(r.emittedNotExpected).toEqual([]);
    expect(r.expectedNotEmitted).toEqual([]);
    expect(r.namedNotExpected).toEqual([]);
    expect(r.expectedNotNamed).toEqual([]);
  });

  // THE CONDITIONAL HALF. On clean data neither side shows `unstaged`, and the fixture
  // must not demand it: that would be asking the page to invent a status-less bill.
  it("does not demand the conditional row on data with no status-less bill", () => {
    const html = page(RAMP);
    const r = reconcileSets(EXPECTED.stateBills, claimed(html), named(html));
    expect(r.conditionalAbsent).toEqual(["unstaged"]);
    expect([r.emittedNotExpected, r.expectedNotEmitted, r.namedNotExpected, r.expectedNotNamed]).toEqual([[], [], [], []]);
  });

  // THE RED-PROOF THE RULING ASKED FOR. Strip the header's data-encoding while the rows
  // still claim the stage: the key no longer names what the page paints, and the
  // reconciliation must say so in the direction that names the defect.
  it("fails, as expected-but-not-named, when the header's data-encoding is removed", () => {
    const html = page([...RAMP, OFF_RAMP]).replace('data-encoding="unstaged"', "");
    const r = reconcileSets(EXPECTED.stateBills, claimed(html), named(html));
    expect(r.expectedNotNamed).toEqual(["unstaged"]);
    // And the self-join the script runs beside it catches the same thing from its side.
    expect(claimed(html).filter((e) => !named(html).includes(e))).toContain("unstaged");
  });

  // THE WITNESS, AND WHY IT EXISTS. A null status coerced into a stage -- the option the
  // ruling struck -- renders neither the key entry nor a mark, so the page alone gives no
  // reason to expect the row. Without a witness that render passes; with the snapshot's
  // count saying a status-less bill exists, it fails in both expected-side directions.
  it("passes a coerced render without the witness, which is the hole the witness closes", () => {
    const coerced = page([...RAMP, { ...OFF_RAMP, status: "1" }]);
    const r = reconcileSets(EXPECTED.stateBills, claimed(coerced), named(coerced));
    expect(r.conditionalAbsent).toEqual(["unstaged"]);
    expect([r.emittedNotExpected, r.expectedNotEmitted, r.namedNotExpected, r.expectedNotNamed]).toEqual([[], [], [], []]);
  });

  it("fails a coerced render when the witness counts a status-less bill", () => {
    const coerced = page([...RAMP, { ...OFF_RAMP, status: "1" }]);
    const witness = offRampCount([...RAMP, OFF_RAMP]) > 0 ? ["unstaged"] : [];
    const r = reconcileSets(EXPECTED.stateBills, claimed(coerced), named(coerced), witness);
    expect(r.expectedNotNamed).toEqual(["unstaged"]);
    expect(r.expectedNotEmitted).toEqual(["unstaged"]);
  });
});

describe("the off-ramp witness", () => {
  // Written out twice on purpose (see reconcile.mjs); asserted equal so the copy cannot
  // drift by accident, while a defect in stageOf cannot move the witness with it.
  it("uses the same ramp as the page", () => {
    expect(RAMP_CODES).toEqual([...STAGE_ORDER]);
  });

  it("counts null and unmapped statuses, and nothing on the ramp", () => {
    expect(offRampCount(RAMP)).toBe(0);
    expect(offRampCount([...RAMP, OFF_RAMP])).toBe(1);
    expect(offRampCount([...RAMP, OFF_RAMP, { ...OFF_RAMP, status: "9" }])).toBe(2);
  });
});

describe("StateMatrix — the unstaged header says only what the column holds", () => {
  it("reads No status when every bill in the column has no status", () => {
    const html = render([...CLEAN, OFF_RAMP]);
    const header = /<th[^>]*data-encoding="unstaged"[^>]*>[\s\S]*?<\/th>/.exec(html)?.[0] ?? "";
    expect(header).toContain(`>${UNSTAGED_LABEL}</th>`);
    expect(attr(header, "title")).toBe("LegiScan has given these bills no status yet");
  });

  // A bill with an unmapped code HAS a status, so "No status" would be false for it.
  it("reads No stage once an unmapped code is in the column", () => {
    const html = render([...CLEAN, OFF_RAMP, bill({ state_bill_id: "9", state: "TX", status: "9" })]);
    const header = /<th[^>]*data-encoding="unstaged"[^>]*>[\s\S]*?<\/th>/.exec(html)?.[0] ?? "";
    expect(header).toContain(`>${UNSTAGED_LABEL_MIXED}</th>`);
    expect(attr(header, "title")).toContain("a status code this page does not map");
  });
});
