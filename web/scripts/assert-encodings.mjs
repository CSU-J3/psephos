/**
 * Asserts that EVERY VISUAL ENCODING THE BOARD EMITS IS NAMED ON THE PAGE.
 *
 *   node scripts/assert-encodings.mjs [url]     # default http://localhost:3001/
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

const URL = process.argv[2] ?? "http://localhost:3001/";
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
await page.goto(URL, { waitUntil: "networkidle" });
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
const legendCount = await page.$$eval("[data-legend]", (els) => els.length);

await browser.close();

const emittedSorted = [...emitted].sort();
const namedSet = new Set(named);

console.log("\nframes sampled: " + JSON.stringify(perFrame));
console.log("emitted: " + JSON.stringify(emittedSorted));
console.log("named:   " + JSON.stringify(named) + "\n");

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

console.log("");
console.log("selection under a real pointer:");
for (const r of selection) {
  check(
    r.label,
    { glow: r.glow, brightness: r.brightness, pressed: r.pressed },
    { glow: true, brightness: r.hovered, pressed: true },
  );
}

console.log(failures === 0 ? "\nOK" : "\n" + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
