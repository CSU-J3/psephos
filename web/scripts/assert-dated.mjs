/**
 * Asserts that EVERY SOURCE DATE A PAGE RENDERS IS MARKED "DATED AHEAD" EXACTLY WHEN IT
 * IS AFTER THE RECORD'S CLOCK, AND THAT NO RECENCY LIST PUTS SUCH A ROW BEFORE A ROW
 * DATED UP TO IT OR FOLDS IT AWAY.
 *
 *   node scripts/assert-dated.mjs [origin]      # default http://localhost:3001
 *
 * Exit code is the alarm: 0 every check passed, 1 otherwise. Like assert-encodings,
 * assert-layout and assert-attribution it has no exit-3 vocabulary: a throw mid-run is
 * also 1, and the dom-checks preflight is what removes the dominant cause of that. A
 * route that answers other than 200 is reported as exactly that, on one line, and its
 * page checks are not run -- a 500 is not a page that lost its clock.
 *
 * WHY IT EXISTS (ruled 2026-09-26). A source can date a row after psephos collected it:
 * LegiScan dated MI HB6414's "Bill Electronically Reproduced 09/24/2026" to 2026-09-29,
 * and on 2026-09-26 that row headed /state-bills' "Latest movement", headed its bill's
 * ledger, and was counted on the homepage as "dated before" a window it was dated after.
 * The ruling: the date stays the source's, a "dated ahead" marker sits beside it, rows
 * dated ahead sort after the rows dated up to the clock and are never truncated away, and
 * every date surface takes the rule. This script is how a surface that stops taking it is
 * found.
 *
 * IT READS MACHINE-READABLE DATES AND NEVER PARSES TEXT. Every source date renders
 * through components/RecordDate.tsx as `<time data-record-date="YYYY-MM-DD">`, with the
 * marker, `[data-dated-ahead]`, as its NEXT SIBLING. The page's clock is its
 * `[data-record-clock]` element: the anchor the components compared against, rendered
 * once. This script compares the two ITSELF -- it does not trust any "ahead" flag the page
 * might emit, because the page emits none.
 *
 * PER ROUTE, after the route answers 200:
 *   1. the clock is present and carries a date
 *   2. at least one [data-record-date] renders
 *   3. every date after the clock has the marker as its next sibling, and every date up
 *      to it has none; and no marker stands anywhere without a date before it
 *   4. inside every [data-recency-list], once a row dated ahead appears no row dated up
 *      to the clock follows it -- which is also "Latest movement never opens with one"
 *   5. inside every recency list, no date after the clock sits in a closed <details>
 *      of that list's own, other than in that element's <summary> -- a row dated ahead
 *      is never folded away from its list. (A ledger row is its own <details> with its
 *      date in its summary; that is a row, not a fold. A <details> AROUND a whole list
 *      -- the homepage's Executive and Watched bills sections -- folds every row alike
 *      and is not this: an adversarial review, 2026-09-26, showed the first form of the
 *      check reding a correct homepage on a relevant Federal Register document dated to
 *      the next Monday.)
 *   6. in a list built with a segment for rows dated ahead -- Latest movement on
 *      /state-bills and /campaign, below its divider; the ledgers, the cases rail and
 *      /news, after their folds -- every date after the clock sits inside that
 *      `[data-dated-ahead-rows]` segment. On a counted list this is the ruling that the
 *      heading stays true of its ten (2026-09-26): a row dated ahead rendered among the
 *      ten, even last, is counted as one of them
 *   7. on the fixed routes, the recency lists the page is built with are all tagged, so
 *      a list that loses its tag goes red here instead of leaving check 4 with nothing
 *      to read
 *   8. where a page renders both /state-bills' list and its Latest movement, every state
 *      bill the list dates ahead of the clock is also in Latest movement, below its
 *      divider. Checks 3-6 read only dates that render, so a Latest movement that stopped
 *      rendering its row dated ahead -- the cut ruling (c) forbids -- gave them nothing
 *      to fail on; the list beside it is the witness that the row exists
 *
 * WHAT IT CANNOT SEE, stated rather than implied. A date rendered AROUND RecordDate --
 * plain text, no `data-record-date` -- is invisible to this script; check 2 catches that
 * only when it empties a page. The half that catches it is lib/source-dates.test.ts,
 * which fails the suite on a source-date column rendered through `formatDate`, `.slice`
 * or raw in any page or component, and the component tests (components/RecordDate.test.ts,
 * lib/dated.test.ts), which render each surface's rows. Content that renders only after
 * a click -- the map's docket panel -- is also out of reach here and is covered there.
 *
 * THE ROUTES ARE DISCOVERED, NOT NAMED, beyond the fixed six (/state-bills' list is
 * read in both of its orders, recent and by state). Each detail page is found BY DATE,
 * never by the marker, so a sweep with the marker gone still reads the page that shows
 * the fault: the /state-bill/ page is the first row on /state-bills?all=1 whose date is
 * after the clock, else the first row; the /bill/ and /case/ pages are the first such
 * links on the homepage whose row carries a date after the clock, else the first link.
 * A discovery that finds no link at all is a failure, not a shorter sweep.
 *
 * It prints two counts at the end: dates after the clock, and how many of them carried
 * the marker. On a green run they are equal; a count of 0 is an ordinary day, and says
 * the run could not have exercised the marked branch.
 *
 * DEPENDENCY, same as its siblings: playwright-core and a Chromium build, neither a
 * dependency of this app.
 *
 *   npm --prefix <scratch> install playwright-core
 *   NODE_PATH=<scratch>/node_modules node scripts/assert-dated.mjs
 */

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const ORIGIN = new URL(process.argv[2] ?? "http://localhost:3001").origin;
const EXE =
  process.env.CHROMIUM_PATH ??
  "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

let failures = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    "  " + (ok ? "PASS" : "FAIL") + "  " + name + ": " + JSON.stringify(actual) +
      (ok ? "" : "  (expected " + JSON.stringify(expected) + ")"),
  );
};

// Everything below runs IN THE PAGE and returns plain data; the comparisons are
// string comparisons on YYYY-MM-DD, which order the same as the days do.
const readPage = () => {
  const clockEl = document.querySelector("[data-record-clock]");
  const clockIso = clockEl ? clockEl.getAttribute("data-record-clock") : null;
  const clockDay = clockIso && /^\d{4}-\d{2}-\d{2}/.test(clockIso) ? clockIso.slice(0, 10) : null;
  const isAhead = (el) => clockDay !== null && el.getAttribute("data-record-date") > clockDay;
  const dates = [...document.querySelectorAll("[data-record-date]")];
  const wrong = [];
  let ahead = 0;
  let marked = 0;
  for (const el of dates) {
    const hasMarker = !!el.nextElementSibling && el.nextElementSibling.hasAttribute("data-dated-ahead");
    if (isAhead(el)) {
      ahead++;
      if (hasMarker) marked++;
    }
    if (isAhead(el) !== hasMarker) {
      wrong.push({ date: el.getAttribute("data-record-date"), clock: clockDay, marked: hasMarker });
    }
  }
  const orphans = [...document.querySelectorAll("[data-dated-ahead]")].filter(
    (m) => !m.previousElementSibling || !m.previousElementSibling.hasAttribute("data-record-date"),
  ).length;
  // Placement: per list, the sequence of row dates in document order. A list's rows are
  // its date elements; a row dated up to the clock after one dated ahead is the fault.
  const misplaced = [];
  for (const list of document.querySelectorAll("[data-recency-list]")) {
    let seenAhead = null;
    for (const el of list.querySelectorAll("[data-record-date]")) {
      const d = el.getAttribute("data-record-date");
      if (isAhead(el) && seenAhead === null) seenAhead = d;
      else if (!isAhead(el) && seenAhead !== null) {
        misplaced.push({ list: list.getAttribute("data-recency-list"), ahead: seenAhead, after: d });
        break;
      }
    }
  }
  // Folded away: an ahead date inside a closed <details> OF ITS OWN LIST -- a fold the
  // list contains -- other than in that element's own <summary>. A <details> around the
  // whole list is outside `list`, and `list.contains` stops the walk at it.
  const folded = [];
  for (const list of document.querySelectorAll("[data-recency-list]")) {
    for (const el of list.querySelectorAll("[data-record-date]")) {
      if (!isAhead(el)) continue;
      for (let d = el.parentElement?.closest("details"); d && list.contains(d); d = d.parentElement?.closest("details")) {
        if (d.open) continue;
        const summary = d.querySelector(":scope > summary");
        if (!summary || !summary.contains(el)) {
          folded.push({ list: list.getAttribute("data-recency-list"), date: el.getAttribute("data-record-date") });
          break;
        }
      }
    }
  }
  // The cut: a state bill the list dates ahead that Latest movement's segment lacks.
  const aheadHrefs = (root) =>
    [...root.querySelectorAll('a[href^="/state-bill/"]')]
      .filter((a) => [...a.querySelectorAll("[data-record-date]")].some(isAhead))
      .map((a) => a.getAttribute("href"));
  const movement = document.querySelector('[data-recency-list="latest-movement"]');
  const listViews = [...document.querySelectorAll('[data-recency-list="list"], [data-recency-list="state-group"]')];
  let cut = null;
  if (movement && listViews.length > 0) {
    const segment = movement.querySelector("[data-dated-ahead-rows]");
    const below = new Set(segment ? aheadHrefs(segment) : []);
    cut = [...new Set(listViews.flatMap(aheadHrefs))].filter((h) => !below.has(h));
  }
  // Segmented lists: every date after the clock inside the list's own ahead segment.
  const SEGMENTED = ["latest-movement", "campaign-movement", "ledger", "cases-rail", "news-archive"];
  const unsegmented = [];
  for (const list of document.querySelectorAll("[data-recency-list]")) {
    const name = list.getAttribute("data-recency-list");
    if (!SEGMENTED.includes(name)) continue;
    for (const el of list.querySelectorAll("[data-record-date]")) {
      if (isAhead(el) && !el.closest("[data-dated-ahead-rows]")) {
        unsegmented.push({ list: name, date: el.getAttribute("data-record-date") });
        break;
      }
    }
  }
  const lists = [
    ...new Set([...document.querySelectorAll("[data-recency-list]")].map((l) => l.getAttribute("data-recency-list"))),
  ].sort();
  return {
    clockIso, clockDay, dates: dates.length, ahead, marked, wrong: wrong.slice(0, 6), orphans, misplaced,
    folded: folded.slice(0, 6), unsegmented, cut, lists,
  };
};

// Discovery, in the page: the first link matching `selector` whose row (its closest
// `li`, else the link itself) carries a date after the page's clock, else the first link.
const discover = (selector) => {
  const clock = (document.querySelector("[data-record-clock]")?.getAttribute("data-record-clock") ?? "").slice(0, 10);
  const links = [...document.querySelectorAll(selector)];
  const ahead = links.find((a) =>
    [...(a.closest("li") ?? a).querySelectorAll("[data-record-date]")].some(
      (el) => clock !== "" && el.getAttribute("data-record-date") > clock,
    ),
  );
  return (ahead ?? links[0])?.getAttribute("href") ?? null;
};

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

// The fixed routes, each with the recency lists it is built with (check 7), then the
// discovered ones, which carry none: a ledger page with no entries renders no list.
const LISTS = {
  "/": ["cases-rail", "executive", "watched-bills"],
  "/state-bills": ["latest-movement"],
  "/state-bills?all=1": ["latest-movement", "list"],
  "/state-bills?all=1&sort=state": ["latest-movement", "state-group"],
  "/news": ["news-archive"],
  "/campaign": ["campaign-movement"],
};
const routes = Object.keys(LISTS);

await page.goto(ORIGIN + "/", { waitUntil: "networkidle" });
const billHref = await page.evaluate(discover, 'a[href^="/bill/"]');
const caseHref = await page.evaluate(discover, 'a[href^="/case/"]');
await page.goto(ORIGIN + "/state-bills?all=1", { waitUntil: "networkidle" });
const stateBillHref = await page.evaluate(discover, '#list a[href^="/state-bill/"]');
check("a /state-bill/ page was discovered", stateBillHref !== null, true);
check("a /bill/ page was discovered", billHref !== null, true);
check("a /case/ page was discovered", caseHref !== null, true);
for (const h of [stateBillHref, billHref, caseHref]) if (h) routes.push(h);
console.log("routes: " + JSON.stringify(routes));

let totalAhead = 0;
let totalMarked = 0;
for (const path of routes) {
  const res = await page.goto(ORIGIN + path, { waitUntil: "networkidle" });
  const status = res ? res.status() : null;
  if (status !== 200) {
    console.log(`\n${path}: HTTP ${status}; the page did not render, so no page check ran`);
    check(`${path}: the route answered 200`, status, 200);
    continue;
  }
  await page.waitForTimeout(150);
  const r = await page.evaluate(readPage);
  totalAhead += r.ahead;
  totalMarked += r.marked;
  console.log(
    `\n${path}: clock ${r.clockIso}; ${r.dates} date(s), ${r.ahead} after the clock, ${r.marked} marked; ` +
      `recency lists ${JSON.stringify(r.lists)}`,
  );
  check(`${path}: the page's clock is present`, r.clockDay !== null, true);
  check(`${path}: renders source dates`, r.dates > 0, true);
  check(`${path}: every date after the clock is marked, and only those`, r.wrong, []);
  check(`${path}: no marker without a date beside it`, r.orphans, 0);
  check(`${path}: no row dated up to the clock follows one dated ahead`, r.misplaced, []);
  check(`${path}: no date after the clock is folded away`, r.folded, []);
  check(`${path}: every date after the clock sits in its list's ahead segment`, r.unsegmented, []);
  if (r.cut !== null) {
    check(`${path}: every state bill the list dates ahead is in Latest movement, below its divider`, r.cut, []);
  }
  if (LISTS[path]) check(`${path}: every recency list it is built with is tagged`, r.lists, [...LISTS[path]].sort());
}

await browser.close();

// Printed, not asserted: a count of 0 is an ordinary day. The two counts say whether this
// run's data exercised the marked branch at all, and, on a red run, how many of the dates
// after the clock went unmarked.
console.log(`\ndates after the clock across the sweep: ${totalAhead}; of them marked "dated ahead": ${totalMarked}`);
console.log(failures === 0 ? "\nOK" : "\n" + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
