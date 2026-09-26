/**
 * Asserts that EVERY VISUAL ENCODING THESE PAGES EMIT IS NAMED ON THE PAGE.
 *
 *   node scripts/assert-encodings.mjs [origin]  # default http://localhost:3001
 *
 * TWO ROUTES, ONE INSTRUMENT: `/` (the board) and `/state-bills` (the stage matrix).
 * The argument is now an ORIGIN rather than a URL, because the script picks its own
 * routes; a full URL still works, its origin is taken. Both sections use the same
 * `check()` and share one exit code.
 *
 * Exit code is the alarm: 0 every emitted encoding is named, 1 otherwise.
 *
 * WHY THIS EXISTS. The board shipped with no key for its own map, through a
 * verification pass that included a "legend count" assertion. That check counted the
 * source-grade legend at the top of the page and passed, while the map below it had
 * no legend at all. A check can name the thing it is missing and still be pointed at
 * a different object -- the count was never the question, and a count can only ever
 * be wrong about how many, never about which.
 *
 * SO THE ASSERTION IS A JOIN, NOT A COUNT. One side is enumerated from the emitted
 * DOM; the other is read from `[data-key] [data-encoding]`. Both directions fail:
 *
 *   emitted but not named   an encoding the reader has no way to decode
 *   named but not emitted   a key entry claiming paint the page does not lay down
 *
 * AND THAT JOIN IS A SELF-JOIN, WHICH IS THE CONTRACT THIS FILE NOW STATES RATHER THAN
 * IMPLIES. Both of its sides are read out of the same rendered document, so what the two
 * directions above establish is that the page AGREES WITH ITSELF. That is worth
 * establishing and it is not the same as the page being right. A commit that drops a
 * mark from the paint and its row from the key moves both sides at once: every check
 * here stays green, at a smaller number, with nothing in the file able to notice the
 * number moved. **A set that can shrink silently is the one failure this script exists
 * to prevent, and until the expected set arrived it was the one shape it could not see.**
 *
 * SO THERE IS A THIRD SIDE: `encodings.expected.mjs`, written by hand from the spec and
 * derived from no render. The reconciliation at the foot of this file compares it against
 * both of the other two in four named directions. It is deliberately NOT generated —
 * a fixture regenerated from the DOM is the self-join again with an extra file in it.
 *
 * A RECONCILIATION FAILURE IS A QUESTION. It says a set moved; it does not say whether
 * moving was correct. A human rules, and a "deliberate" ruling is spent by editing the
 * fixture in the same commit as the paint.
 *
 * AND IT ENUMERATES FROM THE DOM, NEVER FROM A COMPONENT'S HEADER COMMENT. The
 * comment at RecordsMap.tsx names five encodings; it is a map-only list, it says
 * nothing about the chart directly above the map, and the chart emits six more. A
 * comment is a claim by a file's author about that file. Only the DOM is evidence.
 *
 * THE EMITTED SIDE HAS THREE ROOTS, NOT TWO. The map SVG, the chart SVG, and the
 * chart's HTML label layer -- because the chart's glyphs left the coordinate system
 * and its milestone markers left with them. The two SVG roots are classified by
 * COMPUTED PAINT; the HTML root is the one place an encoding is read by name, and it
 * is fenced accordingly: a named element must render a real box, unsuppressed, before
 * the join counts it. See the sweep for why that fence is the whole of its honesty.
 *
 * IT SWEEPS FRAMES, and that is load-bearing rather than merely thorough. The chart's
 * LIT filing dot (r=3.4, opacity 1) emits ZERO instances at the landing frame --
 * every dot is dim at "to date", because the newest filing is months old. It appears
 * only when the scrubber sits within a month of a filing. A single-frame enumeration
 * concludes the encoding does not exist, which is the same error as reading the
 * comment: certifying a set nobody sampled the whole of.
 *
 * COLOURS ARE RESOLVED FROM THE PAGE'S OWN VARIABLES, never transcribed. A script
 * carrying its own copy of `oklch(0.62 0.19 24)` is a third vocabulary, free to drift
 * from the two it was written to compare.
 *
 * DEPENDENCY, same as assert-layout.mjs and for the same reason: this needs
 * `playwright-core` and a Chromium build, and NEITHER is a dependency of this app.
 *
 *   npm --prefix <scratch> install playwright-core
 *   NODE_PATH=<scratch>/node_modules node scripts/assert-encodings.mjs
 *
 * The server must already be running, and it must be a PRODUCTION build.
 */

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { offRampCount, reconcileSets } from "./reconcile.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

// THE WITNESS FOR THE ONE CONDITIONAL ROW, read before the browser opens. The snapshot
// export/snapshots.py writes from Turso, never read by web code -- see offRampCount in
// reconcile.mjs for why that independence is the point and what its one limit is. The
// override exists for the same reason ENCODINGS_EXPECTED's does: red-proofs against a
// scratch copy, never against the tracked file.
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const STATE_BILLS_PATH = process.env.STATE_BILLS_PATH ?? resolve(REPO, "data", "state_bills.json");
// The record's clock as of the export: export/snapshots.py writes generated_at.json in the
// same run, off the same connection, as state_bills.json. It is MAX(items.fetched_at), a
// LOWER bound on when the export ran -- a state run that writes no items does not move it.
// Printed beside the witness so a disagreement with the page can be read against the lag.
const GENERATED_AT_PATH = process.env.GENERATED_AT_PATH ?? resolve(REPO, "data", "generated_at.json");
let offRamp = null;
let offRampError = null;
try {
  offRamp = offRampCount(JSON.parse(readFileSync(STATE_BILLS_PATH, "utf8")));
} catch (e) {
  offRampError = `${STATE_BILLS_PATH}: ${e.message}`;
}
let snapshotAt = "unreadable";
try {
  snapshotAt = JSON.parse(readFileSync(GENERATED_AT_PATH, "utf8")).generated_at ?? "null";
} catch {
  // Context only: the witness itself does not depend on it.
}

const ORIGIN = new URL(process.argv[2] ?? "http://localhost:3001").origin;
const BOARD_URL = ORIGIN + "/";

// THE EXPECTED SET, and the override exists for ONE purpose: red-proving this check
// against mutated copies without touching the repo's fixture. A red-proof that edits the
// file under test leaves the question of whether it was restored, and this project has a
// falsified entry about instruments whose subject moved underneath them. Default is the
// tracked file; the scratch copies live outside the repo and never enter a commit.
const EXPECTED_PATH = process.env.ENCODINGS_EXPECTED ?? "./encodings.expected.mjs";
const expectedMod = await import(
  EXPECTED_PATH.startsWith(".") ? EXPECTED_PATH : pathToFileURL(EXPECTED_PATH).href
);
const EXPECTED = expectedMod.EXPECTED;
const EXE =
  process.env.CHROMIUM_PATH ??
  "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

/** Frames to sample. The landing frame alone does not emit the lit dot. */
const FRAME_FRACTIONS = [1, 0.78, 0.6, 0.35, 0.12];

let failures = 0;
// `detail` prints under a FAIL only: context a reader needs to act on that failure and
// would be noise beside a pass.
const check = (name, actual, expected, detail) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    "  " +
      (ok ? "PASS" : "FAIL") +
      "  " +
      name +
      ": " +
      JSON.stringify(actual) +
      (ok ? "" : "  (expected " + JSON.stringify(expected) + ")") +
      (!ok && detail ? "\n        " + detail : ""),
  );
};

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 2542, height: 1400 } });
await page.goto(BOARD_URL, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);

// The classifier runs IN THE PAGE, so it reads computed values rather than attributes.
// An unknown signature is a failure and not a shrug: a mark nobody can classify is a
// new encoding nobody named, which is the whole subject of this script.
const emittedAt = () =>
  page.evaluate(() => {
    // Resolve the page's own paint values instead of carrying copies of them.
    const probe = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    probe.appendChild(rect);
    probe.style.position = "absolute";
    probe.style.opacity = "0";
    document.body.appendChild(probe);
    const resolve = (v) => {
      rect.setAttribute("fill", v);
      return getComputedStyle(rect).fill;
    };
    const C = {
      litigation: resolve("var(--c-litigation)"),
      legislation: resolve("var(--c-legislation)"),
      executive: resolve("var(--c-executive)"),
      ended: resolve("color-mix(in oklch, var(--c-litigation) 42%, #171717)"),
      none: resolve("#1f1f1f"),
      outcome: resolve("var(--c-outcome)"),
    };
    probe.remove();

    const svgs = [...document.querySelectorAll("svg[role=img]")];
    const chart = svgs.find((s) =>
      /Cumulative jurisdictions/i.test(s.getAttribute("aria-label") || ""),
    );
    const map = svgs.find((s) =>
      /voter-data suits/i.test(s.getAttribute("aria-label") || ""),
    );

    const found = new Set();
    const unknown = [];

    // Frame furniture, excluded EXPLICITLY so the exclusions are visible rather than
    // implied by whatever the classifier happens to fall through. Text, containers,
    // and the neutral greys drawing axis, ticks, the 51 ceiling, the scrubber edge
    // and the callout leaders -- every one a grey, i.e. r === g === b.
    const NEUTRAL = /^rgb\((\d+), \1, \1\)$/;

    const classify = (el, where) => {
      const tag = el.tagName;
      if (tag === "text" || tag === "g" || tag === "title" || tag === "defs") return;
      const cs = getComputedStyle(el);
      const fill = cs.fill;
      const stroke = cs.stroke;
      if (tag === "line" && NEUTRAL.test(stroke)) return;

      if (where === "map") {
        // READ BEFORE THE FILLS AND WITHOUT RETURNING. A rejected jurisdiction emits
        // TWO encodings from one element -- its posture fill and its outcome stroke --
        // which is what "one property, one meaning" buys: the two are independent, so
        // the classifier must record both rather than pick. Returning here would hide
        // whichever posture the rejected states happen to carry.
        if ((tag === "path" || tag === "rect") && stroke === C.outcome) {
          found.add("outcome-stroke");
        }
        if (tag === "path" || tag === "rect") {
          if (fill === C.litigation) return void found.add("posture-live");
          if (fill === C.ended) return void found.add("posture-ended");
          if (fill === C.none) return void found.add("posture-none");
        }
        if (tag === "circle" && fill === C.legislation) {
          return void found.add("state-bill-dot");
        }
      }

      if (where === "chart") {
        if (tag === "path" && stroke === C.litigation) {
          return void found.add("filings-cumulative");
        }
        if (tag === "path" && stroke === C.outcome) {
          return void found.add("outcome-cumulative");
        }
        if (tag === "path" && stroke === C.legislation) {
          return void found.add("legislation-monthly");
        }
        if (tag === "rect" && fill === C.legislation) {
          return void found.add("state-bills-monthly");
        }
        if (tag === "line" && stroke === C.executive) {
          return void found.add("executive-order-tick");
        }
        if (tag === "circle" && fill === C.litigation) {
          return void found.add("filing-date-dot");
        }
        // An empty series renders as a path with nothing painted either side.
        if (tag === "path" && fill === "none" && stroke === "none") return;
      }

      unknown.push({ where, tag, fill, stroke, r: el.getAttribute("r") });
    };

    for (const pair of [
      [map, "map"],
      [chart, "chart"],
    ]) {
      const root = pair[0];
      if (!root) continue;
      for (const el of root.querySelectorAll("*")) {
        if (el.closest("defs")) continue;
        classify(el, pair[1]);
      }
    }

    // --- THE HTML LABEL LAYER, swept as a third root ------------------------------
    //
    // NOT EVERY MARK THIS PAGE PAINTS IS SVG ANY MORE. The chart's lettering moved out
    // of the coordinate system, and one of its marks moved with it: milestone markers
    // are HTML positioned over the plot. The two loops above walk `svg` roots only, so
    // a marker is invisible to them -- and the key entry naming it would then fail the
    // "named but not emitted" arm, which would be the old rule applied correctly to
    // reach a false conclusion about the page.
    //
    // A MARK COUNTS AS EMITTED ONLY IF IT IS ACTUALLY RENDERED. Reading `data-encoding`
    // off the DOM and believing it would turn this arm from an observation into a
    // declaration -- the page asserting its own encodings -- and a declaration is
    // exactly what "present, valid and inert" defeats. That is the defect assert-layout
    // was written for, and this file's own header describes the same shape from the
    // other direction. So a candidate must have a real box and no visibility or display
    // suppression before the join believes it. An element that is in the markup but
    // paints nothing is NOT emitted, and the join is entitled to say so.
    const labels = document.querySelector(".board-labels");
    if (labels) {
      for (const el of labels.querySelectorAll("[data-encoding]")) {
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (box.width < 1 || box.height < 1) continue;
        if (cs.visibility === "hidden" || cs.display === "none" || cs.opacity === "0") continue;
        found.add(el.getAttribute("data-encoding"));
      }
    }

    return { emitted: [...found].sort(), unknown };
  });

const setFrame = (v) =>
  page.$eval(
    "input[type=range]",
    (e, v) => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(e, String(v));
      e.dispatchEvent(new Event("input", { bubbles: true }));
      e.dispatchEvent(new Event("change", { bubbles: true }));
    },
    v,
  );

const max = await page.$eval("input[type=range]", (e) => Number(e.max));

const emitted = new Set();
const unknown = [];
const perFrame = [];
for (const f of FRAME_FRACTIONS) {
  const idx = Math.round(max * f);
  await setFrame(idx);
  await page.waitForTimeout(140);
  const r = await emittedAt();
  perFrame.push({ frame: idx, n: r.emitted.length });
  r.emitted.forEach((e) => emitted.add(e));
  unknown.push(...r.unknown);
}

// --- selection, PROVED WITH A REAL POINTER ------------------------------------
//
// THE POINTER BEING REAL IS THE ENTIRE ASSERTION, and the next person to read this
// will be tempted to simplify it into page.click() or dispatchEvent. Do not.
//
// Selection and hover are both the CSS `filter` property. A dispatched click moves no
// pointer, so :hover never matches, so the element reports the selection filter alone
// and the check passes -- while a human, whose pointer is by definition sitting on the
// shape they just clicked, sees something different. That is not a hypothetical: the
// collision shipped and survived a verification pass for exactly this reason.
//
// So each case is measured twice: with the pointer resting on the shape it clicked
// (both states must hold, composed) and with the pointer moved away (selection alone
// must survive). A composition failure shows up as the glow missing in the first
// reading and present in the second.
//
// The three targets are one large polygon, one callout square, and DC -- the callout
// whose `ab` comes from `feature?.ab ?? c.code` and whose panel title proves the
// lookup resolved rather than fell through.
const readFilter = (ab) =>
  page.evaluate((ab) => {
    const el = document.querySelector(`svg [data-ab="${ab}"]`);
    const f = getComputedStyle(el).filter;
    return {
      glow: /url\(.*#map-glow.*\)/.test(f),
      brightness: /brightness/.test(f),
      pressed: el.getAttribute("aria-pressed") === "true",
      raw: f,
    };
  }, ab);

const selection = [];
for (const ab of ["CA", "MA", "DC"]) {
  // SCROLL IT INTO VIEW FIRST, and this is not a nicety. getBoundingClientRect is
  // VIEWPORT-relative and page.mouse.click takes VIEWPORT coordinates, so reading the
  // box without scrolling makes this block silently depend on the map being above the
  // fold -- a dependency on the page's LENGTH, which has nothing to do with what these
  // six assertions are about.
  //
  // It broke the moment a section was added above the zones: the map moved to y=2331
  // in a 950px viewport, every click landed on nothing, and the script reported six
  // failures about glow, brightness and pressed-state on a map whose paint was
  // perfect. That is this file's own documented failure mode arriving from the other
  // side -- a check that names the thing it is missing while pointed at a different
  // object -- and it would have recurred on any future page-length change.
  await page.$eval(`svg [data-ab="${ab}"]`, (e) => e.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(120);
  const at = await page.$eval(`svg [data-ab="${ab}"]`, (e) => {
    const b = e.getBoundingClientRect();
    // The bbox centre of a concave state (FL, HI, MI, LA) is outside its own paint --
    // the Michigan-centroid problem that LABEL_ANCHOR already exists for, biting a
    // second instrument. These three are convex enough for the centre to land inside,
    // which is why they are the three and not an arbitrary sample.
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  });

  await page.mouse.click(at.x, at.y);
  await page.waitForTimeout(220);
  selection.push({ label: `${ab} selected, pointer ON it`, hovered: true, ...(await readFilter(ab)) });

  // Move the pointer well clear, without clicking: selection must survive on its own.
  await page.mouse.move(4, 4);
  await page.waitForTimeout(220);
  selection.push({ label: `${ab} selected, pointer AWAY`, hovered: false, ...(await readFilter(ab)) });

  await page.mouse.click(at.x, at.y);
  await page.mouse.move(4, 4);
  await page.waitForTimeout(120);
}

const named = await page.$$eval("[data-key] [data-encoding]", (els) =>
  els.map((e) => e.getAttribute("data-encoding")).sort(),
);
const keyCount = await page.$$eval("[data-key]", (els) => els.length);

// --- the line against the key -------------------------------------------------
//
// A SECOND JOIN, over a different pair of sets, and it exists because the first one
// cannot see this failure at all. The encodings join asks whether every MARK is
// named. This asks whether every FIGURE the summary line prints is either painted by
// the map or disclaimed as unpainted -- the ambiguity the board shipped with, where a
// three-fill map sat above a six-figure line and nothing said which figures the fills
// carried.
const figures = await page.$$eval("[data-figure]", (els) =>
  els.map((e) => e.getAttribute("data-figure")).sort(),
);
const unpainted = await page.$$eval("[data-key] [data-unpainted]", (els) =>
  els.map((e) => e.getAttribute("data-unpainted")).sort(),
);
const legendCount = await page.$$eval("[data-legend]", (els) => els.length);

// --- the line's posture wordings against the key's ------------------------------
//
// A THIRD JOIN, and it is over words rather than marks. The first asks whether every
// painted encoding is named; the second whether every figure the line prints is painted
// or disclaimed. Neither can see two surfaces naming the SAME jurisdictions differently,
// which is what the page did: the line said "29 active" directly above a key saying
// "suit live" about exactly those 29, and every existing check passed the whole time.
//
// BOTH SIDES ARE READ FROM THE DOM, so the script holds no copy of either wording. It
// compares the line's rendered text against the key entry's rendered text for the same
// posture -- a transcription here would be a third vocabulary, free to agree with a
// stale version of both.
const postureWording = await page.evaluate(() => {
  const text = (el) => (el ? el.textContent.trim() : null);
  const out = [];
  for (const el of document.querySelectorAll("[data-posture]")) {
    const p = el.getAttribute("data-posture");
    out.push({
      posture: p,
      line: text(el),
      key: text(document.querySelector(`[data-key] [data-encoding="posture-${p}"]`)),
    });
  }
  return out;
});

// --- /state-bills: the stage matrix -------------------------------------------
//
// SAME JOIN, SECOND PAGE. The matrix column headers are that page's key, and until this
// section existed nothing checked them -- docs/status.md carried "the matrix's key is
// asserted by nothing" as a stated gap. The board's argument applies unchanged: a key
// that drifts from the ink it decodes fails silently and looks fine.
//
// IDENTITY COMES FROM AN ATTRIBUTE HERE, NOT FROM COLOUR, and that is a real difference
// from the board rather than a convenience. Stages 2 and 3 (Engrossed, Enrolled) are
// painted IDENTICALLY -- both `var(--leg-dim)` on all four surfaces -- so a classifier
// reading only computed colour cannot tell them apart and would be reporting a
// resolution it does not have. So each mark declares which stage it CLAIMS via
// `data-stage`, and the script checks that claim against the paint the key declares for
// that stage. Identity from the attribute, verification from the pixel. A row that says
// Passed and is painted like Failed fails `paint disagreeing with the key`, which is
// the failure colour-only classification cannot see.
//
// THE SWEEP IS LOAD-BEARING, exactly like the board's frames. The default view carries
// ten movement rows, which cannot paint all six stages; tick and chip coverage only
// completes under `?all=1`. A single-view enumeration concludes half the ramp is unused
// -- the same error as sampling one frame.
//
// TWO PAINTED SURFACES ARE EXCLUDED BY NAME rather than by falling through the
// classifier, which is the board section's rule applied here. The zero middot carries
// `data-zero`: it is the ABSENCE of a stage, not a stage, and self-decoding in a table
// of numbers. The totals row carries no `data-stage`: its cells are stage-specific but
// painted a flat neutral for every column on purpose, so they belong to the totals
// vocabulary and would fail against all six declared colours if claimed. Both are
// counted and printed, so an exclusion that starts swallowing real marks is visible.
//
// ONE BRANCH IS UNREACHABLE ON LIVE DATA AND THIS SCRIPT DOES NOT CLAIM IT:
//
//   Vehicle badge     draws only for is_vehicle = 1, and that is 0 on every row.
//                     Pinned by components/StateBillRow.test.ts (since 82487df).
//
// It is asserted to be absent rather than silently skipped: if it ever becomes reachable,
// the check below fails and forces this comment to be re-read. That is the point -- an
// unreachable branch that quietly becomes reachable is how a key goes stale.
//
// THERE WERE TWO, AND THE OTHER ONE FIRED. The unstaged column and the off-ramp row
// were declared unreachable through 484 rows, their header carrying `data-unreachable`
// instead of `data-encoding`. On 2026-09-25 the state run 36131273689 wrote PA HR632
// with a null status and the branch was reached; on 2026-09-26 this check failed on it,
// exactly as this paragraph said it would. The ruling was the one the check prescribed:
// the key owes it an entry. So `unstaged` is now keyed like the six stages and joined
// like them, and encodings.expected.mjs carries it as a CONDITIONAL row -- expected
// whenever the render shows it or the snapshot's witness says the data holds one.
const STATE_VIEWS = [
  ["default", "/state-bills"],
  ["one state", "/state-bills?state=TX"],
  ["all bills", "/state-bills?all=1"],
];

// Surfaces whose absence is meaningful. `dot` and `cell` come from the matrix, which
// every view renders; `tick` and `chip` come from bill rows and are what the sweep is
// for. Introduced declares no tick and is still expected in the tick set -- see the
// coverage check, which deliberately excludes nothing.
const SURFACES = ["dot", "cell", "tick", "chip"];

const sbEmitted = new Set();
const sbClaimed = new Set();
let sbRowsUnclaimed = 0;
const sbMismatch = [];
const sbUnknown = [];
const sbPerView = [];
const sbBySurface = { dot: new Set(), cell: new Set(), tick: new Set(), chip: new Set() };
let sbNamed = [];
let sbDeclared = {}; // reported, not asserted -- see the ramp note below
let sbKeyCount = null;
let sbUnstagedSampled = 0;
let sbOffRampRows = null; // off-ramp bill rows in the ?all=1 view: the page's own count
const sbUnstagedTickStyles = [];
let sbVehicleSampled = 0;

for (const [label, path] of STATE_VIEWS) {
  await page.goto(ORIGIN + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(180);

  const r = await page.evaluate(() => {
    // Resolve the page's own values instead of carrying copies. The key declares each
    // stage's four surface colours as authored (`var(--leg-dim)`, `#404040`); this turns
    // them into the same rgb strings getComputedStyle returns, so the comparison is
    // between two computed values and never between a computed value and a transcript.
    const probe = document.createElement("span");
    probe.style.position = "absolute";
    probe.style.opacity = "0";
    document.body.appendChild(probe);
    const resolve = (v) => {
      if (!v || v === "none") return "none";
      probe.style.color = "";
      probe.style.color = v;
      return getComputedStyle(probe).color;
    };

    const keyBlocks = document.querySelectorAll("[data-key]");
    const heads = [...document.querySelectorAll("[data-key] [data-encoding]")];
    const declared = {};
    for (const h of heads) {
      declared[h.getAttribute("data-encoding")] = {
        dot: resolve(h.getAttribute("data-paint-dot")),
        cell: resolve(h.getAttribute("data-paint-cell")),
        tick: resolve(h.getAttribute("data-paint-tick")),
        chip: resolve(h.getAttribute("data-paint-chip")),
      };
    }
    probe.remove();

    const found = { dot: [], cell: [], tick: [], chip: [] };
    const mismatch = [];
    const unknown = [];
    const claimed = [];

    // A mark's claim, its surface, and the colour it actually carries.
    //
    // THE CLAIM IS RECORDED BEFORE THE KEY IS CONSULTED, and that ordering is the whole
    // reason `emitted but not named` can fail at all. An earlier draft of this section
    // built the emitted set out of `declared`, so every emitted encoding was by
    // construction one the key named and the join could not fail -- a check that reads as
    // the strongest one here and asserts nothing. It is precisely the defect this file
    // exists to catch, in the file that catches it. So: claim first, verify second, and a
    // claim the key does not name survives into the join rather than being swallowed.
    const record = (surface, encoding, painted) => {
      if (!encoding) {
        unknown.push({ surface, painted });
        return;
      }
      claimed.push(encoding);
      if (!(encoding in declared)) return; // unnamed -> the join below reports it
      const want = declared[encoding][surface];
      // Introduced declares no tick; the row paints a transparent border for it.
      const ok =
        want === "none"
          ? /rgba\(0, 0, 0, 0\)|transparent/.test(painted)
          : painted === want;
      if (ok) found[surface].push(encoding);
      else mismatch.push({ surface, encoding, painted, declared: want });
    };

    // 1. the key's own dots
    for (const h of heads) {
      const dot = h.querySelector("span[style]");
      if (!dot) continue;
      record("dot", h.getAttribute("data-encoding"), getComputedStyle(dot).backgroundColor);
    }

    // 2. matrix counts. Zeros are frame furniture -- the middot is the ABSENCE of a
    //    stage, not a stage -- and are excluded by name rather than by falling through.
    for (const c of document.querySelectorAll("table [data-stage]")) {
      record("cell", c.getAttribute("data-stage"), getComputedStyle(c).color);
    }

    // 3. row ticks and 4. row chips. Counted against ALL row links, so a row rendered
    //    by some other path -- painting a tick while claiming nothing -- is caught
    //    rather than skipped by the selector that only looks for claims.
    const rowLinks = document.querySelectorAll("li > a");
    const rowClaims = document.querySelectorAll("li > a[data-stage]");
    for (const row of rowClaims) {
      const enc = row.getAttribute("data-stage");
      record("tick", enc, getComputedStyle(row).borderLeftColor);
      const chip = row.querySelector("[data-chip]");
      if (chip) record("chip", enc, getComputedStyle(chip).color);
    }

    return {
      claimed: [...new Set(claimed)].sort(),
      rowsUnclaimed: rowLinks.length - rowClaims.length,
      declared,
      named: [...new Set(heads.map((h) => h.getAttribute("data-encoding")))].sort(),
      keyCount: keyBlocks.length,
      zeros: document.querySelectorAll("[data-zero]").length,
      // The conditional encoding, counted and printed so a reader can see whether this
      // render showed it. It is printed beside the snapshot's witness, which is what
      // decides whether it was owed.
      unstagedSampled: document.querySelectorAll('[data-stage="unstaged"]').length,
      // The page's count of off-ramp bills: rows in the #list section, which under ?all=1
      // lists every bill exactly once. Scoped to #list because "Latest movement" renders
      // on every view too, and a recently-moved off-ramp bill would otherwise count twice.
      // The tick-style sweep below stays unscoped: a movement row for such a bill must be
      // dashed as well, so every row is checked.
      offRampRows: document.querySelectorAll('#list li > a[data-stage="unstaged"]').length,
      unstagedTickStyles: [...document.querySelectorAll('li > a[data-stage="unstaged"]')].map(
        (a) => getComputedStyle(a).borderLeftStyle,
      ),
      // The branch this script states it cannot reach, counted so that becoming reachable
      // is an alarm rather than a silent change of what the sweep covers.
      vehicleSampled: [...document.querySelectorAll("li > a[data-stage] span")].filter(
        (e) => e.textContent.trim() === "Vehicle",
      ).length,
      found,
      mismatch,
      unknown,
    };
  });

  sbNamed = r.named;
  sbDeclared = r.declared;
  sbKeyCount = r.keyCount;
  sbUnstagedSampled += r.unstagedSampled;
  if (path.endsWith("?all=1")) sbOffRampRows = r.offRampRows;
  sbUnstagedTickStyles.push(...r.unstagedTickStyles);
  sbVehicleSampled += r.vehicleSampled;
  sbMismatch.push(...r.mismatch);
  sbUnknown.push(...r.unknown);
  sbRowsUnclaimed += r.rowsUnclaimed;
  r.claimed.forEach((e) => sbClaimed.add(e));
  for (const surface of SURFACES) {
    for (const e of r.found[surface]) {
      sbEmitted.add(e);
      sbBySurface[surface].add(e);
    }
  }
  sbPerView.push({
    view: label,
    marks: SURFACES.reduce((a, s) => a + r.found[s].length, 0),
    stages: new Set(SURFACES.flatMap((s) => r.found[s])).size,
    zeros: r.zeros,
  });
}

await browser.close();

const emittedSorted = [...emitted].sort();
const namedSet = new Set(named);

console.log("\nframes sampled: " + JSON.stringify(perFrame));
console.log("emitted: " + JSON.stringify(emittedSorted));
console.log("named:   " + JSON.stringify(named));
console.log("figures: " + JSON.stringify(figures));
console.log("unpainted: " + JSON.stringify(unpainted) + "\n");

check("unclassified marks", unknown.slice(0, 6), []);
check(
  "emitted but not named",
  emittedSorted.filter((e) => !namedSet.has(e)),
  [],
);
check(
  "named but not emitted",
  named.filter((e) => !emitted.has(e)),
  [],
);

// The two keys stay countable apart. Had the board's key reused `data-legend`, the
// older assertion would have gone on proving nothing at a larger number.
check("data-key blocks", keyCount, 1);
check("data-legend blocks", legendCount, 1);

// ONE VOCABULARY, JOINED DOM-TO-DOM. Each posture the line names must be spelled
// exactly as the key spells it. This is the check that would have caught active/live,
// and none of the three that already existed could: the figure was disclaimed, the
// marks were all named, and the two surfaces simply used different words for one set.
console.log("posture wording, line vs key: " + JSON.stringify(postureWording));
check(
  "line and key spell each posture identically",
  postureWording.filter((p) => p.line === null || p.key === null || p.line !== p.key),
  [],
);

// The line names exactly the two postures it has figures for. `none` is absent on
// purpose -- it is the complement of `sued`, the map paints it, and a figure for it
// would put a third posture in a sentence about two. Asserted rather than left to
// convention, because "the line renders what it renders" is how a surface quietly
// stops naming something it should.
check(
  "postures the line names",
  postureWording.map((p) => p.posture).sort(),
  ["ended", "live"],
);

// ONE DIRECTION ONLY, and the asymmetry is deliberate rather than a half-finished
// join. Every figure the line prints that the map does not paint must be disclaimed
// in the key. The reverse arm is NOT asserted, because `unlinkedEndings` renders
// behind a `> 0` conditional: on a day when nothing is unlinked the line does not
// print it while the key still names it. That is the key being complete, not the key
// lying, and an assertion that failed on it would be demanding the key go quiet
// whenever a count reached zero.
//
// The exclusion list is FOUR here where board.test.ts has five. `none` is missing
// from this one because the line never renders it -- there is no [data-figure="none"]
// to exclude. It is excluded in the unit test on the different ground that the map
// paints it. Same key, two lists, two reasons.
//
// `live` WAS `active` UNTIL THE POSTURE-WORDING UNIT, and this line had to move with
// the figure or the check below would have failed on a rename that broke nothing --
// reporting `live` as an undisclaimed figure when what actually changed was its name.
// `rejected` joins the set because the map PAINTS it -- teal stroke on the shape --
// which is the same ground `live` and `ended` are here on. It does NOT join the list in
// lib/board.test.ts, and the asymmetry is not an oversight: that one is computed over
// `Object.keys(summarize())`, and this figure is derived by lib/outcomes.ts rather than
// by summarize, so it never appears there. Same key, two lists, two reasons -- still.
const AGGREGATE_OR_PAINTED = new Set(["sued", "total", "live", "ended", "rejected"]);
check(
  "line figures the map does not paint, disclaimed in the key",
  figures.filter((f) => !AGGREGATE_OR_PAINTED.has(f) && !unpainted.includes(f)),
  [],
);

console.log("");
console.log("selection under a real pointer:");
for (const r of selection) {
  check(
    r.label,
    { glow: r.glow, brightness: r.brightness, pressed: r.pressed },
    { glow: true, brightness: r.hovered, pressed: true },
  );
}

console.log("");
console.log("--- /state-bills -------------------------------------------------");
console.log("views swept: " + JSON.stringify(sbPerView));
console.log("claimed: " + JSON.stringify([...sbClaimed].sort()));
console.log("verified: " + JSON.stringify([...sbEmitted].sort()));
console.log("named:   " + JSON.stringify(sbNamed));
// TWO NUMBERS, AND ONLY ONE OF THEM IS ABOUT THE DATA. The render's count says what the
// page showed; the witness says what the snapshot holds. A render cannot tell clean data
// from a branch it dropped, so this line never reads a zero mark count as "no off-ramp
// bill" -- that is the witness's to say.
const witnessLine =
  `page: ${sbOffRampRows ?? "?"} off-ramp bill(s) in ?all=1's list; ` +
  `snapshot (the witness): ${offRamp === null ? "UNREADABLE" : offRamp}, generated_at ${snapshotAt}`;
console.log("unstaged marks sampled: " + sbUnstagedSampled + "; " + witnessLine);
for (const surface of SURFACES) {
  console.log("  " + surface.padEnd(5) + " paints: " + JSON.stringify([...sbBySurface[surface]].sort()));
}
console.log("");

// THE SWATCH IS A SAMPLE OF THE INK. `dot === cell` on every stage, asserted below.
//
// This was a printed finding for exactly one unit and is now a check, which is the whole
// life-cycle the reporting form exists for: print a divergence nobody has ruled on, get
// a ruling, assert it. What it caught was not deliberate design, as the finding first
// claimed -- the mock's dot painted a per-stage colour that was sometimes the cell and
// sometimes not, plus a ternary overriding stage 1 alone, and the first port of it here
// normalised Failed and stopped. Introduced and Passed were the half it did not finish.
//
// TWO AXES, AND ONLY ONE IS ASSERTED. An earlier version of this report tested
// `dot === tick && dot === cell` and printed one DIFFERS column for both, which
// overstated the dot/cell divergence as four stages when it was two. They are separate
// questions. `tick` is a 2px rule against a near-black ground -- a different contrast
// problem from 0.4rem of text, where the ramp's dim step is nearly invisible -- so it is
// free to run brighter or darker than the count it accompanies. It is printed beside the
// others every run so the divergence stays visible, and nothing is asserted about it.
const ramp = Object.entries(sbDeclared).map(([stage, p]) => ({
  stage: stage.replace("stage-", ""),
  dot: p.dot,
  tick: p.tick,
  cell: p.cell,
  swatchIsInk: p.dot === p.cell,
  tickMatchesDot: p.dot === p.tick,
}));
console.log("key swatch vs the ink it decodes (dot/cell asserted, tick reported only):");
for (const r of ramp) {
  console.log(
    "  " +
      (r.swatchIsInk ? "dot=cell" : "DIFFERS ") +
      "  " +
      r.stage.padEnd(11) +
      " dot " +
      r.dot.padEnd(22) +
      " cell " +
      r.cell.padEnd(22) +
      " tick " +
      r.tick +
      (r.tickMatchesDot ? "" : "  (own channel)"),
  );
}
console.log("");

const sbNamedSet = new Set(sbNamed);

// An unrecognised mark is a FAILURE, never a shrug -- the board's rule, and the reason
// this instrument exists. A painted surface carrying a stage the key does not name is
// exactly the encoding nobody can decode.
check("state-bills: unclassified marks", sbUnknown.slice(0, 6), []);

// THE CHECK COLOUR-ONLY CLASSIFICATION CANNOT MAKE. Every mark declares a stage; this
// asserts the paint it carries is the paint that stage declares in the key. It catches a
// row that says Passed and is inked like Failed -- invisible to a classifier that infers
// the stage FROM the ink, because there the two can never disagree.
check("state-bills: paint disagreeing with the key", sbMismatch.slice(0, 6), []);

// CLAIMED, not verified -- see record(). A stage the page paints and the key omits must
// reach this line even though nothing could check its colour against a key entry that
// does not exist. NOTHING IS EXCLUDED BY NAME ANY MORE. "unstaged" was, as the
// declared-unreachable branch, until the key took an entry for it (the branch was reached
// on 2026-09-25, PA HR632); it is held to this check like every stage.
check(
  "state-bills: emitted but not named",
  [...sbClaimed].sort().filter((e) => !sbNamedSet.has(e)),
  [],
);

// Every row link claims a stage; a tick painted by a row that claims nothing is an
// encoding with no possible entry in any key.
check("state-bills: row links painting a tick without claiming a stage", sbRowsUnclaimed, 0);
check(
  "state-bills: named but not emitted",
  sbNamed.filter((e) => !sbEmitted.has(e)),
  [],
);

// PER-SURFACE, AND THIS IS WHAT THE SWEEP BUYS. The union above passes as soon as any
// one surface paints a stage, so a tick that silently stopped painting Vetoed would hide
// behind the matrix cell that still does. Ticks and chips only reach every stage under
// ?all=1, which is why three views are visited rather than one.
//
// `dot` and `cell` are not asserted this way: the key draws all six dots on every view
// by construction, and the matrix draws all six columns, so the assertion would be
// vacuous rather than merely redundant.
//
// NO STAGE IS EXCLUDED HERE, and the one that looks like it should be is the point.
// Introduced declares `tick: "none"`, so an exclusion for it reads as obviously needed
// -- and would be inert, because a declared-none tick is recorded as painted when the
// row actually paints a transparent border. That recording IS the assertion that
// Introduced draws no rule: drop the tick and the row paints something, and the
// mismatch check fires. An exclusion here would have quietly removed that.
for (const surface of ["tick", "chip"]) {
  const painted = sbBySurface[surface];
  check(
    "state-bills: every named stage painted on " + surface,
    sbNamed.filter((e) => !painted.has(e)),
    [],
  );
}

// AND `cell` FOR THE ONE ENCODING WHERE IT IS NOT VACUOUS. The six stages are exempt from
// a cell check because the matrix draws their columns on every view. `unstaged` is the
// reverse: its header renders only when some row holds a non-zero count, so a keyed
// `unstaged` with no claimed count means the column's cells stopped claiming -- which
// the key's own dot would otherwise hide, since a key dot is itself a claim (record()).
check(
  "state-bills: unstaged, when keyed, painted on cell",
  sbNamed.includes("unstaged") && !sbBySurface.cell.has("unstaged") ? ["unstaged"] : [],
  [],
);

// THE LINE STYLE THE COLOUR CHECKS CANNOT SEE. `paint disagreeing with the key` compares
// colours, and an off-ramp row's tick is Introduced's chip grey on a rule Introduced does
// not draw -- what separates the two rows is that the rule is DASHED (ruled 2026-09-26).
// A class or a restyle that rendered it solid would pass every colour check here.
check(
  "state-bills: every off-ramp row's tick is dashed",
  sbUnstagedTickStyles.filter((s) => s !== "dashed"),
  [],
);

// THE RULING, ASSERTED. A key whose swatch is merely NEAR the colour it explains is one
// the reader has to squint past, and it drifts one stage at a time because each step
// looks close enough on its own.
//
// THIS COMPARES THE TWO DECLARED VALUES, not the rendered dot against a declared one --
// worth saying, because the stronger reading is the tempting one and it is wrong. It
// closes the loop only in company: `paint disagreeing with the key` above already checks
// each rendered dot against its own declaration, so a dot restyled in the component
// fails THERE. Between them, rendered dot == declared dot == declared cell. Neither
// check spans that chain alone, and reading this one as though it did would leave the
// component-restyle case looking covered twice and the pair looking redundant.
check(
  "state-bills: key swatch is the cell ink",
  ramp.filter((r) => !r.swatchIsInk).map((r) => r.stage),
  [],
);

// One key, asserted for the board's own reason: two keys diverging while both look
// present is the failure that opened this file.
check("state-bills: data-key blocks", sbKeyCount, 1);

// THE STATED BOUNDARY, ASSERTED RATHER THAN ASSUMED. The Vehicle badge is unpaintable on
// live data, so the sweep cannot have sampled it and must not imply it did. If this count
// ever moves off zero the branch has become reachable, the key owes it an entry, and the
// comment above owes a rewrite -- which is the alarm, not a nuisance.
//
// IT FIRED ONCE, FOR THE OTHER BRANCH. A matching check on `unstaged` stood here until the
// key took the entry this comment prescribed. The branch was reached on 2026-09-25, when
// the state run 36131273689 wrote PA HR632 with a null status, and on 2026-09-26 the
// check read `state-bills: unstaged sampled (unreachable by construction): 1`. It retired
// with the keying: `unstaged` is joined above and reconciled below like a stage.
check("state-bills: vehicle badges sampled (unreachable on live data; pinned by StateBillRow.test.ts)", sbVehicleSampled, 0);

// --- THE THIRD SIDE: reconciliation against the expected set ----------------------
//
// EVERYTHING ABOVE IS A SELF-JOIN. `emitted` and `named` are both read out of the same
// rendered document, so together they prove the page agrees with itself — worth proving,
// and not the same as proving the page is right. Drop a mark from the paint and its row
// from the key in one commit and both sides move together: every check above stays green
// at a smaller number, with nothing to compare that number against. The set can shrink
// silently, which is the one failure the join was built to prevent and the one shape it
// cannot see.
//
// `encodings.expected.mjs` is written by hand from the spec and derived from no render,
// so it is the side the page cannot vote on. ONE QUALIFICATION: a conditional row's
// presence is decided at run time, by the render OR by a witness counted from the data
// snapshot -- and it is the witness, not the render, that keeps the page from voting on
// that row (see reconcile.mjs). Reconciliation is FOUR DIRECTIONS per route
// rather than a set equality, because the four mean four different things and a reader
// needs to know which one fired:
//
//   emitted but not expected   the page paints something the fixture does not list —
//                              a new encoding shipped without its fixture row
//   expected but not emitted   the fixture lists paint the page does not lay down —
//                              a mark removed, or a fixture row that was never real
//   named but not expected     the key names something the fixture does not list
//   expected but not named     the fixture lists something the key does not name
//
// A FAILURE HERE IS A QUESTION, NOT A VERDICT, and the script does not pretend to answer
// it. A divergence is either a defect or a deliberate set change; only a human can rule.
// If the ruling is "deliberate", the fixture is edited IN THE SAME COMMIT as the paint —
// the precedent the milestone-marker row set, where paint, key row and expected row
// landed together and the join moved 9→10 with nothing red in between.
//
// THE ARITHMETIC IS scripts/reconcile.mjs, pure, so components/StateMatrix.test.ts can
// run it on rendered markup without a browser. A row carrying `when` is CONDITIONAL:
// expected when the render emits it or names it, or when the witness says the data holds
// one, and then held to all four directions. A conditional row that none of the three
// calls for is printed, never failed.
const reconcile = (label, expectedRows, emittedSet, namedList, witnessed = [], detail) => {
  const r = reconcileSets(expectedRows, emittedSet, namedList, witnessed);
  console.log(
    `\n${label}: expected ${r.expected.length}, emitted ${r.emitted.length}, named ${r.named.length}` +
      (r.conditionalAbsent.length ? `  (conditional, not called for: ${JSON.stringify(r.conditionalAbsent)})` : ""),
  );
  check(`${label}: emitted but not expected`, r.emittedNotExpected, []);
  check(`${label}: expected but not emitted`, r.expectedNotEmitted, [], detail);
  check(`${label}: named but not expected`, r.namedNotExpected, []);
  check(`${label}: expected but not named`, r.expectedNotNamed, [], detail);
};

console.log("\nreconciliation against the expected set (the side the page cannot vote on)");
reconcile("board", EXPECTED.board, emitted, named);
// NO NAME IS FILTERED OUT OF EITHER SIDE. `unstaged` was, as the declared-unreachable
// branch, until the key took an entry for it (reached 2026-09-25, PA HR632); it is now a
// conditional row of the fixture, and the snapshot's witness decides whether it is owed.
// An unreadable snapshot is a failure, not a pass: without the witness this row would be
// back to the page voting on itself.
check("state-bills: the off-ramp witness was read", offRampError, null);
// WHEN THE PAGE AND THE WITNESS DISAGREE, the expected-side failure lines carry both
// counts and the snapshot's generated_at. That is the only failure the witness can add,
// and it has two readings: the page dropped the branch, or the snapshot trails a status
// filled in since. generated_at settles that one way only, being a lower bound on the
// export: later than the state run rules out the lag reading; earlier leaves both open,
// and only the bill's live status in Turso decides -- which this lane cannot read.
const disagree = (sbOffRampRows ?? 0) > 0 !== (offRamp ?? 0) > 0;
reconcile(
  "state-bills",
  EXPECTED.stateBills,
  sbClaimed,
  sbNamed,
  offRamp > 0 ? ["unstaged"] : [],
  disagree ? `page and witness disagree -- ${witnessLine}` : undefined,
);

console.log(failures === 0 ? "\nOK" : "\n" + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
