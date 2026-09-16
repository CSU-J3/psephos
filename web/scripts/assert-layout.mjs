/**
 * Asserts the board's COMPUTED LAYOUT STRUCTURE against a running server.
 *
 *   node scripts/assert-layout.mjs [url]        # default http://localhost:3001/
 *
 * Exit code is the alarm: 0 all assertions held, 1 one or more failed.
 *
 * WHY THIS EXISTS, and it is not a general test harness. The three-column shell
 * specified by handoff 87 never rendered at any width. `min-[1900px]:grid-cols-...`
 * was present in the markup and compiled to a real rule, but Tailwind v4 emits
 * arbitrary media variants AHEAD of the named breakpoints, so above 1900px the
 * `xl:` rule (80rem) matched later on equal specificity and won. The class was
 * present, valid and inert, and nothing about the page looked broken -- the third
 * column simply stacked below, which reads as a deliberate narrow layout.
 *
 * So THE ASSERTION IS ON THE COMPUTED TRACK COUNT, NEVER ON A CLASS NAME. A class
 * that is present and inert is exactly what this defect was; asserting the class
 * would have passed throughout. Same reason the font check enumerates computed
 * `fontFamily` rather than checking that a declaration exists.
 *
 * It was caught by section 7's check 2, three commits after it shipped, because the
 * earlier renders were looked at rather than compared against an expected structure.
 *
 * AND IT CLICKS THE TABS, because for its whole life it measured ONE OF THREE PANELS
 * while the record said otherwise. "Where this stands" renders three `role="tabpanel"`
 * divs, two of them `hidden`, and a `display:none` subtree GENERATES NO BOXES: measured
 * in chromium-1228, a 3000px element inside a hidden panel leaves
 * `documentElement.scrollWidth` at 380 in a 380px viewport and reads 3000 with the same
 * panel shown. So the overflow check below could not see anything behind a tab, at any
 * width, and the 2026-09-14 03:17Z run was recorded as "the first Linux read of the
 * stacked Path" when it never laid that Path out. All five Paths are in `wts-next`.
 *
 * THE OVERFLOW CHECK IS THE ONE THAT REPEATS PER TAB, and the rest deliberately do not.
 * The zone and wire grids are never inside a panel. The board height and the font sweep
 * stay DEFAULT-TAB ONLY: the sweep reads `getComputedStyle`, which resolves through
 * `display:none` (measured -- a stack declared behind a hidden panel appears in the
 * swept set), so clicking adds nothing to it, and the board is not in a panel either.
 * Each width therefore ends by clicking back to `now`, so everything after this loop
 * reads the tab the page actually serves.
 *
 * DEPENDENCY, stated plainly: this needs `playwright-core` and a Chromium build,
 * and NEITHER is a dependency of this app -- adding a browser to web/'s dependency
 * tree is its own decision and has not been taken. Run it from a scratch install:
 *
 *   npm --prefix <scratch> install playwright-core
 *   NODE_PATH=<scratch>/node_modules node scripts/assert-layout.mjs
 *
 * The server must already be running, and for anything touching fonts it must be a
 * PRODUCTION build: `next dev` injects <nextjs-portal>, whose stack is a third value
 * that does not exist in what ships.
 */

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const URL = process.argv[2] ?? "http://localhost:3001/";
const EXE =
  process.env.CHROMIUM_PATH ??
  "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

/**
 * THE ZONE MATRIX: viewport width -> [zone tracks, wire tracks, last wire cell's
 * grid-column]. Every row is a width the layout is supposed to hold, and the
 * boundaries are pinned FROM BOTH SIDES -- 1900/1899, 1280/1279, 1180/1179, 640/639 --
 * because a breakpoint that never fires and a breakpoint off by one look identical in
 * a table sampled at round numbers only. The three-width table this replaced could not
 * have caught either.
 *
 * WHAT CHANGED AND WHY THE OLD ROWS WERE STALE RATHER THAN WRONG. The second column
 * used to be "read tracks", the grid holding TheRead's six channel sentences. The wire
 * replaced TheRead and ChannelStrip, TheRead was deleted, and the finder -- which
 * matches on content, `/REPORTING|LITIGATION/i` -- then landed on the wire, whose
 * arrangement is five across rather than three. So the script went on measuring a real
 * grid against another grid's expectations and failed 3 of 3 while the page was right.
 * That is the failure mode this file's own header warns about, arriving from the other
 * direction: not a class present and inert, but an expectation outliving its subject.
 *
 * THE WIRE'S STEPS ARE ITS OWN, not the zones'. Five cells want 1180 to sit across;
 * three zones want 1280 and 1900. They are independent grids and the matrix says so --
 * at 1279 the zones have collapsed to one column while the wire is still five across.
 */
const EXPECTED_ZONES = [
  [2542, 3, 5, "auto"],
  [1920, 3, 5, "auto"],
  [1900, 3, 5, "auto"],
  [1899, 2, 5, "auto"],
  [1280, 2, 5, "auto"],
  [1279, 1, 5, "auto"],
  [1180, 1, 5, "auto"],
  [1179, 1, 2, "1 / -1"],
  [900, 1, 2, "1 / -1"],
  [640, 1, 2, "1 / -1"],
  [639, 1, 1, "auto"],
  [500, 1, 1, "auto"],
];

/**
 * The named areas at each zone count. Track count alone does not say WHERE the board
 * sits, and the middle band is the whole point of the reflow: two columns carrying
 * feed beside rail with the board on a full-width row of its own beneath them. A
 * two-track grid that stacked feed/board with the rail underneath would satisfy the
 * count and be the wrong page.
 */
const EXPECTED_AREAS = {
  3: "feed board side",
  2: "feed side board board",
  1: "feed board side",
};

let failures = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    `  ${ok ? "PASS" : "FAIL"}  ${name}: ${JSON.stringify(actual)}` +
      (ok ? "" : `  (expected ${JSON.stringify(expected)})`),
  );
};

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 2542, height: 1400 } });
await page.goto(URL, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);

/* --- the tab controls ----------------------------------------------------- */
//
// PANELS ARE ADDRESSED THROUGH THE BUTTON THAT CONTROLS THEM, `aria-controls`, never a
// class or an nth-child: that attribute is the component's own join between the two, and
// it is what a reader of `WhereThisStands.tsx` will recognise.
//
// AND THEIR ABSENCE IS A FAILURE, NEVER A SKIP. A sweep that quietly stops clicking when
// the markup moves is this file's own defect arriving by a new door: everything below
// would go on passing, on one panel, exactly as it did before this loop existed.
const TAB_IDS = ["now", "next", "em"];
const tabsPresent = await page.evaluate(
  (ids) => ids.every((id) => !!document.querySelector(`[role="tab"][aria-controls="wts-${id}"]`)),
  TAB_IDS,
);

// waitForSelector on the panel's own `:not([hidden])`, never a fixed sleep. The swap is
// a React state change, so the condition is observable, and a timeout would be a guess
// in both directions.
const showTab = async (id) => {
  await page.click(`[role="tab"][aria-controls="wts-${id}"]`);
  await page.waitForSelector(`#wts-${id}:not([hidden])`);
};
const overflows = () =>
  page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);

console.log(`\nassert-layout against ${URL}`);

// Asserted once, before the widths, rather than per width: it is a fact about the
// markup, and repeating it twelve times would bury the reading it produces.
console.log("\ntab controls");
check("the three tab controls are present", tabsPresent, true);

/* --- computed grid tracks at each width ---------------------------------- */
console.log("\ngrid tracks (computed, not classes)");
for (const [w, zonesExp, wireExp, spanExp] of EXPECTED_ZONES) {
  await page.setViewportSize({ width: w, height: 1400 });
  await page.waitForTimeout(600);
  const got = await page.evaluate(() => {
    const grids = [...document.querySelectorAll("*")].filter(
      (el) => getComputedStyle(el).display === "grid",
    );
    const tracks = (el) =>
      getComputedStyle(el).gridTemplateColumns.split(/\s+/).filter(Boolean).length;
    // The zone grid is the one that contains the map; the wire is the one holding the
    // channel cells. Both are found by CONTENT -- the map's aria-label, the cells' own
    // data-channel -- never by a styling class, for the reason in this file's header:
    // a class can be present, valid and inert, which is the defect it exists to catch.
    const zones = grids.find((g) => g.querySelector('svg[aria-label^="DOJ voter-data"]'));
    const wire = grids.find((g) => g.querySelector('[data-channel="legislation"]'));
    const cells = wire ? [...wire.children] : [];
    const last = cells[cells.length - 1];
    return {
      zones: zones ? tracks(zones) : -1,
      wire: wire ? tracks(wire) : -1,
      areas: zones
        ? getComputedStyle(zones).gridTemplateAreas.replace(/"/g, "").trim()
        : "",
      span: last ? getComputedStyle(last).gridColumn : "",
      cells: cells.length,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
  check(`${w}px zones/wire tracks`, [got.zones, got.wire], [zonesExp, wireExp]);
  check(`${w}px zone areas`, got.areas, EXPECTED_AREAS[zonesExp]);
  // The five-cell wire leaves a bordered hole in its two-column band unless the last
  // cell spans the row. Asserted as a computed grid-column so the rule is measured
  // where it applies and NOT where it does not: stretching that cell in the five- or
  // one-column arrangement would be its own defect, and "auto" is the assertion there.
  check(`${w}px last wire cell span`, got.span, spanExp);
  // LABELLED BY TAB, all three of them, so a red names the panel that overflowed and not
  // the width alone. The default tab is asserted off the same read as the grids above it
  // -- one evaluate, rather than a second that could land on a different frame.
  check(`${w}px no horizontal overflow (tab now)`, got.overflow, false);
  // Guarded on the assertion above rather than on a fresh query: if the controls are
  // gone this run has already FAILED, and clicking a selector that matches nothing
  // would replace that verdict with a timeout, twelve times over.
  if (tabsPresent) {
    for (const id of TAB_IDS.slice(1)) {
      await showTab(id);
      check(`${w}px no horizontal overflow (tab ${id})`, await overflows(), false);
    }
    await showTab("now");
  }
}

/* --- board height is one value across every frame ------------------------ */
await page.setViewportSize({ width: 2542, height: 1400 });
await page.waitForTimeout(600);
const frames = await page.evaluate(async () => {
  const input = document.querySelector('input[type="range"][aria-label="Month"]');
  // THE WHOLE BOARD, reached by `closest`, never by `parentElement`. This read
  // `.parentElement` and meant the board's root -- until the chart gained a wrapper for
  // its grid area, at which point the same expression silently began measuring the
  // chart alone. The check went on passing while its subject shrank, which is the
  // weaker assertion: the board can reflow across frames through the detail panel
  // without the chart moving at all. `closest(".board")` names what is meant, and it
  // is the grid root whether or not the chart is wrapped.
  const root = document
    .querySelector('svg[aria-label^="Cumulative jurisdictions"]')
    .closest(".board");
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  ).set;
  const seen = [];
  for (let i = 0; i <= +input.max; i++) {
    setter.call(input, String(i));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    seen.push(+root.getBoundingClientRect().height.toFixed(2));
  }
  return { n: seen.length, distinct: [...new Set(seen)] };
});
console.log("\nboard height across frames");
console.log(`  frames measured: ${frames.n}   values: ${frames.distinct.join(", ")}`);
check("one distinct board height", frames.distinct.length, 1);

/* --- the chart's lettering is width-independent --------------------------- */
//
// THE REGRESSION GUARD AGAINST LETTERING RE-ENTERING THE COORDINATE SYSTEM, and it has
// to be measured in a browser because the defect was invisible everywhere else. The
// chart's labels used to be SVG <text> at `font-size="13"` -- thirteen USER UNITS, so
// the rendered size was 13 * (chart width / 900). Measured on the production build
// before this changed: 9.16px at a 740px viewport and 11.22px at 883px, and worse where
// the board actually reflows -- 8.44px at 1400px, where the chart shares the board row
// at 584px, against 12.37px at 2560px, where it is stacked at 857px. One declaration,
// four sizes, none of them the specified one.
//
// TWO WIDTHS, NOT ONE, AND THEY MUST AGREE. A single width could be satisfied by any
// declaration that happens to land on 12 there; the claim is that the size does not
// move with the container, and only a pair can say that. 740 and 883 are both wide
// enough that the container rule leaves the minors alone, so the same two nodes exist
// in both frames.
//
// ASSERTED ON A MAJOR LABEL, whose presence is not conditional. The minors are reported
// beside it rather than asserted: they are dropped below 560px of chart by design, so a
// missing one is a correct render at some widths and this row is not where that belongs.
console.log("\nchart lettering (CSS pixels, not user units)");
for (const w of [740, 883]) {
  await page.setViewportSize({ width: w, height: 1400 });
  await page.waitForTimeout(600);
  const type = await page.evaluate(() => {
    const major = document.querySelector(".board-lbl.axis:not(.minor)");
    const minor = document.querySelector(".board-lbl.axis.minor");
    const chart = document.querySelector(".board-plot");
    return {
      major: major ? getComputedStyle(major).fontSize : "(absent)",
      minor: minor ? getComputedStyle(minor).fontSize : "(absent)",
      chartW: chart ? +chart.getBoundingClientRect().width.toFixed(2) : -1,
    };
  });
  console.log(`    chart ${type.chartW}px   minor ${type.minor}`);
  check(`${w}px chart label font-size`, type.major, "12px");
}

/* --- exactly two type stacks (production build only) --------------------- */
const fonts = await page.evaluate(() => {
  const s = new Set();
  document.querySelectorAll("*").forEach((el) => s.add(getComputedStyle(el).fontFamily));
  return { stacks: [...s], portals: document.querySelectorAll("nextjs-portal").length };
});
console.log("\ntype stacks");
fonts.stacks.forEach((f) => console.log("    " + f));
if (fonts.portals > 0) {
  console.log(
    `  SKIP  ${fonts.portals} <nextjs-portal> present -- this is a dev server, not what ships`,
  );
} else {
  check("exactly two computed font stacks", fonts.stacks.length, 2);
}

await browser.close();
console.log(`\n${failures === 0 ? "OK" : failures + " FAILED"}`);
process.exit(failures === 0 ? 0 : 1);
