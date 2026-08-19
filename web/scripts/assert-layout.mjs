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

/** viewport width -> [shell tracks, read tracks]. Below 1000 both collapse to one. */
const EXPECTED_TRACKS = [
  [2542, 3, 3],
  [1280, 2, 2],
  [900, 1, 1],
];

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

console.log(`\nassert-layout against ${URL}`);

/* --- computed grid tracks at each width ---------------------------------- */
console.log("\ngrid tracks (computed, not classes)");
for (const [w, shellExp, readExp] of EXPECTED_TRACKS) {
  await page.setViewportSize({ width: w, height: 1400 });
  await page.waitForTimeout(600);
  const got = await page.evaluate(() => {
    const grids = [...document.querySelectorAll("*")].filter(
      (el) => getComputedStyle(el).display === "grid",
    );
    const tracks = (el) =>
      getComputedStyle(el).gridTemplateColumns.split(/\s+/).filter(Boolean).length;
    // The shell is the grid that contains the map; the read is the one that holds
    // the six channel sentences. Both are found by content, not by class.
    const shell = grids.find((g) => g.querySelector('svg[aria-label^="DOJ voter-data"]'));
    const read = grids.find((g) => /REPORTING|LITIGATION/i.test(g.innerText ?? ""));
    return {
      shell: shell ? tracks(shell) : -1,
      read: read ? tracks(read) : -1,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
  check(`${w}px shell/read`, [got.shell, got.read], [shellExp, readExp]);
  check(`${w}px no horizontal overflow`, got.overflow, false);
}

/* --- board height is one value across every frame ------------------------ */
await page.setViewportSize({ width: 2542, height: 1400 });
await page.waitForTimeout(600);
const frames = await page.evaluate(async () => {
  const input = document.querySelector('input[type="range"][aria-label="Month"]');
  const root = document
    .querySelector('svg[aria-label^="Cumulative jurisdictions"]')
    .parentElement;
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
