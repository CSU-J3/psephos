/**
 * Asserts the LegiScan CC BY 4.0 attribution is RENDERED, with both links, on the
 * three kinds of page that must carry it:
 *
 *   node scripts/assert-attribution.mjs http://localhost:3001
 *
 * Exit code is the alarm: 0 every assertion passed; 1 an assertion failed OR the run
 * threw mid-way. As with assert-encodings and assert-layout there is no exit 3: the
 * dom-checks preflight removes the dominant cause of a throw, so 1 most likely means
 * the page, not the instrument.
 *
 * WHY THIS EXISTS AND WHY IT IS SCHEDULED. LegiScan's API data is CC BY 4.0, and from
 * 2026-11-01 LegiScan audits keys against those terms; a key in violation is
 * PERMANENTLY banned (LegiScan API Team email, 2026-09-23). That is the state channel
 * gone, with no appeal. The audit is ongoing, not a one-time pass, so a redesign that
 * drops the footer or rewords the line has to fail loudly the next morning rather than
 * be found by LegiScan. Handoff 98, Part B.
 *
 * WHAT IS ASSERTED, per page, at a desktop and a phone width:
 *   1. The attribution sentence is present, found by its TEXT, whitespace-normalised
 *      and matched exactly. Not by `data-attribution`: an attribute survives a
 *      rewording that the licence would not.
 *   2. Every instance holds both links, each with its exact text and its exact href.
 *   3. Both links are visible: checkVisibility() with opacity and visibility, and a
 *      non-empty box. A footer hidden at a phone breakpoint is a missing footer.
 *   4. The instance count per page, and exactly one of them inside a <footer>. This pins
 *      the PLACEMENT, not only the presence: / has the site-wide footer only;
 *      /state-bills and a state-bill page each have their own line AND the footer.
 *      Dropping any one placement moves a count.
 *
 * THE SENTENCE IS COPIED HERE ON PURPOSE, not imported from the component. A check that
 * read the text back from components/LegiScanAttribution.tsx would pass any edit made
 * there. This copy is the brief's text (Corey, 2026-09-23). Changing it is a decision
 * that belongs in the same commit as the component, stated in its message.
 *
 * THE STATE-BILL PAGE IS DISCOVERED, NOT NAMED. It follows the first /state-bill/ link
 * on /state-bills, so no bill id is pinned that the data could later drop. No such
 * link is itself a failure, since then the page under test does not exist.
 */

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const ORIGIN = (process.argv[2] ?? "http://localhost:3001").replace(/\/+$/, "");
const EXE =
  process.env.CHROMIUM_PATH ??
  "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

const SENTENCE =
  "State legislation data from the LegiScan API by LegiScan LLC, licensed under " +
  "CC BY 4.0. Filtered to election-related bills and reformatted by psephos.";
const LINKS = [
  { text: "LegiScan API", href: "https://legiscan.com/legiscan" },
  { text: "CC BY 4.0", href: "https://creativecommons.org/licenses/by/4.0/" },
];

// [label, how many instances, of which in a <footer>]
const PAGES = [
  ["/", 1, 1],
  ["/state-bills", 2, 1],
  ["state-bill detail", 2, 1],
];
const WIDTHS = [1280, 390];

let failures = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    `  ${ok ? "PASS" : "FAIL"}  ${name}: ${JSON.stringify(actual)}` +
      (ok ? "" : `  (expected ${JSON.stringify(expected)})`),
  );
};

/** Every innermost element whose normalised text is the sentence, described. */
async function readAttributions(page) {
  return page.evaluate(
    ({ sentence, links }) => {
      const norm = (s) => (s ?? "").replace(/\s+/g, " ").trim();
      const all = [...document.body.querySelectorAll("*")].filter(
        (el) => norm(el.textContent) === sentence,
      );
      // Innermost only: a <footer> wrapping a <p> matches too, and is the same instance.
      const inner = all.filter((el) => !all.some((o) => o !== el && el.contains(o)));
      return inner.map((el) => ({
        inFooter: el.closest("footer") !== null,
        links: links.map(({ text, href }) => {
          const a = [...el.querySelectorAll("a")].find((x) => norm(x.textContent) === text);
          if (!a) return { text, found: false };
          const r = a.getBoundingClientRect();
          return {
            text,
            found: true,
            href: a.getAttribute("href"),
            visible:
              a.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) &&
              r.width > 0 &&
              r.height > 0,
          };
        }),
      }));
    },
    { sentence: SENTENCE, links: LINKS },
  );
}

function assertPage(label, width, found, total, footer) {
  const at = `${label} @${width}`;
  check(`${at} attribution instances`, found.length, total);
  check(`${at} instances inside <footer>`, found.filter((f) => f.inFooter).length, footer);
  found.forEach((f, i) => {
    for (const [j, l] of f.links.entries()) {
      const want = LINKS[j];
      check(
        `${at} #${i + 1}${f.inFooter ? " (footer)" : ""} link "${want.text}"`,
        { found: l.found, href: l.href ?? null, visible: l.visible ?? false },
        { found: true, href: want.href, visible: true },
      );
    }
  });
}

const browser = await chromium.launch({ executablePath: EXE });
try {
  for (const width of WIDTHS) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    let detail = null;
    for (const [label, total, footer] of PAGES) {
      let path = label;
      if (label === "state-bill detail") {
        if (!detail) {
          check(`${label} @${width} reachable from /state-bills`, "no /state-bill/ link", "a link");
          continue;
        }
        path = detail;
      }
      const resp = await page.goto(ORIGIN + path, { waitUntil: "networkidle" });
      check(`${label} @${width} HTTP status`, resp?.status() ?? null, 200);
      if (label === "/state-bills") {
        detail = await page.evaluate(
          () => document.querySelector('a[href^="/state-bill/"]')?.getAttribute("href") ?? null,
        );
      }
      assertPage(label === "state-bill detail" ? `${label} ${path}` : label, width,
        await readAttributions(page), total, footer);
    }
    await page.close();
  }
} catch (err) {
  failures++;
  console.log(`  FAIL  run threw before it finished: ${err?.stack ?? err}`);
} finally {
  await browser.close();
}

console.log(`\n${failures === 0 ? "OK" : failures + " FAILED"}`);
process.exit(failures === 0 ? 0 : 1);
