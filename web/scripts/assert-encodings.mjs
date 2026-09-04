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

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const ORIGIN = new URL(process.argv[2] ?? "http://localhost:3001").origin;
const BOARD_URL = ORIGIN + "/";
const EXE =
  process.env.CHROMIUM_PATH ??
  "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

/** Frames to sample. The landing frame alone does not emit the lit dot. */
const FRAME_FRACTIONS = [1, 0.78, 0.6, 0.35, 0.12];

let failures = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    "  " +
      (ok ? "PASS" : "FAIL") +
      "  " +
      name +
      ": " +
      JSON.stringify(actual) +
      (ok ? "" : "  (expected " + JSON.stringify(expected) + ")"),
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
// TWO BRANCHES ARE UNREACHABLE ON LIVE DATA AND THIS SCRIPT DOES NOT CLAIM THEM:
//
//   unstaged column   draws only for a bill outside stages 1-6, and all 484 rows are
//                     inside them. The header carries `data-unreachable`, not
//                     `data-encoding`, so it never enters the join. That branch is
//                     pinned by components/StateMatrix.test.ts instead.
//   Vehicle badge     draws only for is_vehicle = 1, and that is 0 across all 484.
//                     Pinned by NOTHING. Stated here so it is a known gap rather than
//                     a discovered one.
//
// Both are asserted to be absent rather than silently skipped: if either ever becomes
// reachable, the check below fails and forces this comment to be re-read. That is the
// point -- an unreachable branch that quietly becomes reachable is how a key goes stale.
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
let sbUnreachable = [];
let sbUnstagedSampled = 0;
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
      unreachable: [...document.querySelectorAll("[data-unreachable]")].map((e) =>
        e.getAttribute("data-unreachable"),
      ),
      zeros: document.querySelectorAll("[data-zero]").length,
      // The two branches this script states it cannot reach, counted so that becoming
      // reachable is an alarm rather than a silent change of what the sweep covers.
      unstagedSampled: document.querySelectorAll('[data-stage="unstaged"]').length,
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
  sbUnreachable = r.unreachable;
  sbUnstagedSampled += r.unstagedSampled;
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
const AGGREGATE_OR_PAINTED = new Set(["sued", "total", "live", "ended"]);
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
// EMPTY IS THE EXPECTED READING, and it does not mean "nothing was declared". The
// unstaged header only renders when a bill is outside stages 1-6, so on live data there
// is no [data-unreachable] element in the DOM at all. A non-empty list here means the
// branch became reachable, which the check further down turns into a failure.
console.log(
  "unreachable markers in the DOM: " +
    JSON.stringify(sbUnreachable) +
    (sbUnreachable.length === 0 ? "  (none rendered -- branch not reached, as expected)" : ""),
);
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
// does not exist. "unstaged" is excluded here and counted on its own below: it is the
// declared-unreachable branch, not an encoding the key owes an entry.
check(
  "state-bills: emitted but not named",
  [...sbClaimed].sort().filter((e) => e !== "unstaged" && !sbNamedSet.has(e)),
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

// THE STATED BOUNDARY, ASSERTED RATHER THAN ASSUMED. Both branches are unpaintable on
// live data, so the sweep cannot have sampled them and must not imply it did. If either
// count ever moves off zero the branch has become reachable, the key owes it an entry,
// and the comment above owes a rewrite -- which is the alarm, not a nuisance.
check("state-bills: unstaged sampled (unreachable by construction)", sbUnstagedSampled, 0);
check("state-bills: vehicle badges sampled (unreachable, and pinned by no test)", sbVehicleSampled, 0);

console.log(failures === 0 ? "\nOK" : "\n" + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
