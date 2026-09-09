/**
 * Asserts that EVERY CLAIM THE "WHERE THIS STANDS" SECTION MAKES IS REGISTERED,
 * AND THAT NO REGISTERED CLAIM HAS QUIETLY EXPIRED.
 *
 *   node scripts/assert-gates.mjs [origin]      # all three checks; needs a server
 *   node scripts/assert-gates.mjs --expiry-only # check 3 alone; no browser, no server
 *
 * Exit code is the alarm, and it is SPLIT so a red run says which half failed:
 *
 *   0  every requested check passed
 *   1  EXPIRY failed -- an authored claim is past its recheck date
 *   2  DOM JOIN failed -- an ungated claim, or a gate the page never renders
 *   3  the check could not run -- missing file, unreadable schema, bad usage
 *
 * 3 is deliberately not 1. A check that could not run is not a check that passed
 * and is not a claim that failed; collapsing those is how a broken instrument
 * reads as a clean bill of health.
 *
 * WHY TWO ENTRY POINTS, and this is the shape recon section 7 settled on. Checks 1
 * and 2 join against the rendered DOM, so they need `playwright-core`, a Chromium
 * build and a running production server -- exactly the dependencies that keep
 * `assert-encodings.mjs` and `assert-layout.mjs` out of CI, run by hand instead.
 * Check 3 needs a YAML file and a date string. It is the check recon says EARNS
 * this file -- an authored claim goes stale invisibly, and `recheck_after` is the
 * only property of it a machine can fail on -- so it must not inherit the browser's
 * dependencies and sit unrun beside its siblings. `--expiry-only` runs in ci.yml.
 *
 * THIS IS CI, NOT A BUILD STEP, and the distinction is load-bearing. Recon section
 * 7.7 declined a build gate because a stale claim would then block an unrelated
 * deploy, and the pressure that creates is to widen the gate rather than recheck
 * the claim. Vercel deploys from git on its own; a red run here notifies and
 * blocks nothing.
 *
 * THE CLOCK IS THE DATA'S, NEVER THE RENDER'S. Expiry compares against
 * `data/generated_at.json`, written by the export each cron from `MAX(fetched_at)`
 * over `items` -- the same instrument the page header's "collected" label reads.
 * `new Date()` appears nowhere in this file. A check that consults the wall clock
 * reports a different answer on a machine whose clock is wrong, with no symptom.
 *
 * COMPARISON IS STRING COMPARISON ON ISO DATES, which is why the loader insists
 * every date be a `YYYY-MM-DD` STRING and refuses a parsed Date. The `yaml`
 * package's default core schema leaves an unquoted ISO date as a string, but that
 * is a property of a default rather than of the file, and a Date arriving here
 * would compare against a string by coercion and silently answer wrong.
 */

import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const GATES_PATH = process.env.GATES_PATH ?? resolve(REPO, "docs", "gates.yaml");
const GENERATED_AT_PATH =
  process.env.GENERATED_AT_PATH ?? resolve(REPO, "data", "generated_at.json");

/** The attributes D4's component must carry: one on the section root, one on each
 *  element making a registered claim. Named here so both sides read one string. */
const SECTION_SELECTOR = '[data-section="where-this-stands"]';
const GATE_ATTR = "data-gate";

const EXIT_OK = 0;
const EXIT_EXPIRY = 1;
const EXIT_DOM = 2;
const EXIT_CANNOT_RUN = 3;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

let pass = 0;
let fail = 0;
function check(ok, label, detail) {
  if (ok) {
    pass += 1;
    console.log(`PASS  ${label}`);
  } else {
    fail += 1;
    console.log(`FAIL  ${label}${detail ? `\n        ${detail}` : ""}`);
  }
  return ok;
}

function cannotRun(message) {
  console.error(`CANNOT RUN  ${message}`);
  process.exit(EXIT_CANNOT_RUN);
}

// --- loading ----------------------------------------------------------------------

/** Parse and VALIDATE the register. Validation is not politeness: check 3 reads one
 *  named field, so a misspelled `recheck_after` would make an expired claim pass by
 *  being invisible rather than by being current. Every shape error is fatal. */
function loadGates() {
  if (!existsSync(GATES_PATH)) cannotRun(`no gates file at ${GATES_PATH}`);
  let YAML;
  try {
    YAML = require("yaml");
  } catch {
    cannotRun("the `yaml` package is not installed -- run `pnpm install` in web/");
  }

  let doc;
  try {
    doc = YAML.parse(readFileSync(GATES_PATH, "utf8"));
  } catch (e) {
    cannotRun(`${GATES_PATH} is not valid YAML: ${e.message}`);
  }
  if (!Array.isArray(doc)) cannotRun(`${GATES_PATH} must be a list of gates`);

  const seen = new Set();
  const problems = [];
  for (const [i, g] of doc.entries()) {
    const at = `entry ${i}${g && g.id ? ` (${g.id})` : ""}`;
    if (!g || typeof g !== "object") {
      problems.push(`${at}: not a mapping`);
      continue;
    }
    if (typeof g.id !== "string" || !g.id) problems.push(`${at}: missing string \`id\``);
    else if (seen.has(g.id)) problems.push(`${at}: duplicate id`);
    else seen.add(g.id);

    if (g.kind !== "authored" && g.kind !== "derived")
      problems.push(`${at}: \`kind\` must be authored or derived, got ${JSON.stringify(g.kind)}`);

    if (g.renders_as !== undefined && typeof g.renders_as !== "string")
      problems.push(`${at}: \`renders_as\` must be a string`);

    if (g.kind === "authored") {
      for (const f of ["claim", "source", "falsified_by"])
        if (typeof g[f] !== "string" || !g[f]) problems.push(`${at}: missing string \`${f}\``);
      for (const f of ["asserted_on", "recheck_after"]) {
        if (typeof g[f] !== "string")
          problems.push(`${at}: \`${f}\` must be a YYYY-MM-DD STRING, got ${typeof g[f]}`);
        else if (!ISO_DATE.test(g[f]))
          problems.push(`${at}: \`${f}\` is not YYYY-MM-DD: ${g[f]}`);
      }
      if (!["active", "stale", "falsified"].includes(g.status))
        problems.push(`${at}: \`status\` must be active, stale or falsified`);
      if (!g.grade || typeof g.grade.source !== "string" || typeof g.grade.info !== "number")
        problems.push(`${at}: \`grade\` must be {source: <letter>, info: <number>}`);
    }

    if (g.kind === "derived") {
      if (typeof g.produced_by !== "string" || !g.produced_by)
        problems.push(`${at}: missing string \`produced_by\``);
      // THE ONE RULE THIS FILE EXISTS FOR. A derived entry naming a number is a
      // literal that looks maintained; `renders_as` carries {placeholders} only.
      const literal =
        typeof g.renders_as === "string" &&
        g.renders_as.replace(/\{[^}]*\}/g, "").match(/\d/);
      if (literal)
        problems.push(
          `${at}: \`renders_as\` holds a digit outside a {placeholder} -- derived entries carry no values`
        );
    }
  }
  if (problems.length)
    cannotRun(`${GATES_PATH} is malformed:\n        ${problems.join("\n        ")}`);
  return doc;
}

/** The record's own clock, as a YYYY-MM-DD string. */
function loadGeneratedAt() {
  if (!existsSync(GENERATED_AT_PATH))
    cannotRun(
      `no ${GENERATED_AT_PATH} -- the export writes it each run; run \`python -m export.snapshots\``
    );
  let obj;
  try {
    obj = JSON.parse(readFileSync(GENERATED_AT_PATH, "utf8"));
  } catch (e) {
    cannotRun(`${GENERATED_AT_PATH} is not valid JSON: ${e.message}`);
  }
  const raw = obj?.generated_at;
  // Null is a real answer -- nothing has ever been collected -- and it is not a date.
  // The page renders that case as its own statement rather than falling back to a
  // clock, and this check refuses to invent one either.
  if (raw === null)
    cannotRun(
      `${GENERATED_AT_PATH} holds null: nothing collected, so there is no date to compare against`
    );
  if (typeof raw !== "string" || !ISO_DATE.test(raw.slice(0, 10)))
    cannotRun(`${GENERATED_AT_PATH} has no usable \`generated_at\`: ${JSON.stringify(raw)}`);
  return raw.slice(0, 10);
}

// --- check 3: expiry --------------------------------------------------------------

function checkExpiry(gates, today) {
  console.log(`\n--- expiry, against the record's clock ${today} ---`);
  const authored = gates.filter((g) => g.kind === "authored");
  check(authored.length > 0, "the register holds at least one authored claim");

  for (const g of authored) {
    const expired = g.recheck_after < today;
    if (!expired) {
      check(true, `${g.id} -- recheck ${g.recheck_after}, not yet due`);
      continue;
    }
    // Expired. `stale` is a human acknowledgement and passes; `active` fails.
    if (g.status === "stale") {
      check(
        true,
        `${g.id} -- recheck ${g.recheck_after} PAST, acknowledged (status: stale, renders grey)`
      );
    } else if (g.status === "falsified") {
      check(true, `${g.id} -- recheck ${g.recheck_after} PAST, claim already falsified`);
    } else {
      check(
        false,
        `${g.id} -- recheck ${g.recheck_after} PAST and status is \`${g.status}\``,
        `Recheck the claim and move \`asserted_on\`/\`recheck_after\`, or set \`status: stale\`.\n        ` +
          `Do NOT backdate: "${g.claim}" (${g.source}). Falsified by: ${g.falsified_by}`
      );
    }
  }
}

// --- checks 1 and 2: the DOM join -------------------------------------------------

async function checkDom(gates, origin) {
  console.log(`\n--- DOM join, against ${origin} ---`);
  let chromium;
  try {
    ({ chromium } = require("playwright-core"));
  } catch {
    cannotRun(
      "playwright-core is not installed. It is deliberately not a dependency of this app:\n" +
        "          npm --prefix <scratch> install playwright-core\n" +
        "          NODE_PATH=<scratch>/node_modules node scripts/assert-gates.mjs\n" +
        "        Or run `--expiry-only`, which needs no browser."
    );
  }
  const exe =
    process.env.CHROMIUM_PATH ??
    "C:/Users/meh/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";

  const browser = await chromium.launch({ executablePath: exe });
  let rendered;
  let status = null;
  try {
    const page = await browser.newPage();
    // The response is CAPTURED rather than discarded, and that capture is the whole of
    // the instrument the CANNOT RUN message below gained. `page.goto` returns null only
    // for a same-document navigation, which a fresh page cannot make -- so the null is
    // handled rather than asserted away.
    const response = await page.goto(origin, { waitUntil: "networkidle" });
    status = response === null ? null : response.status();
    rendered = await page.evaluate(
      ([sel, attr]) => {
        const root = document.querySelector(sel);
        if (!root) return null;
        return [...root.querySelectorAll(`[${attr}]`)].map((el) => el.getAttribute(attr));
      },
      [SECTION_SELECTOR, GATE_ATTR]
    );
  } finally {
    await browser.close();
  }

  if (rendered === null) {
    // Not a FAIL: nothing was compared, and it must not read as "the join passed".
    //
    // AND IT REPORTS WHAT IT SAW, NEVER WHY. This message used to assert a cause it had
    // no instrument for -- "the section is not rendered there ... until the component
    // ships" -- which was true while D4 was unbuilt and then went stale, silently, on
    // the day D4 shipped. A message whose entire job is to report what could NOT be
    // determined is the worst place in this file to state an unverified reason.
    //
    // The HTTP status is the one thing this function actually observes about the page,
    // and it was being thrown away at the `goto` above. Captured, it separates a 200
    // that lacks the section from a 500 that lacks everything -- without either being
    // claimed as the cause.
    cannotRun(
      `${SECTION_SELECTOR} not found on ${origin}` +
        (status === null
          ? " -- no HTTP response was recorded for the navigation.\n"
          : ` -- the page returned HTTP ${status}.\n`) +
        "        That is the whole of what was observed. The selector's absence has more\n" +
        "        than one cause -- the section not rendering, the route erroring, a server\n" +
        "        that is not this app -- and nothing here distinguishes them.\n" +
        "        `--expiry-only` is the half that runs without a page."
    );
  }

  const emitted = new Set(rendered);
  const registered = new Set(
    gates.filter((g) => g.renders_as !== undefined).map((g) => g.id)
  );

  const ungated = [...emitted].filter((id) => !registered.has(id));
  const orphan = [...registered].filter((id) => !emitted.has(id));

  check(
    ungated.length === 0,
    `every rendered ${GATE_ATTR} is registered (${emitted.size} on the page)`,
    ungated.length ? `ungated claims: ${ungated.join(", ")}` : undefined
  );
  check(
    orphan.length === 0,
    `every registered gate with \`renders_as\` is rendered (${registered.size} in the register)`,
    orphan.length ? `registered but never rendered: ${orphan.join(", ")}` : undefined
  );
}

// --- main -------------------------------------------------------------------------

const argv = process.argv.slice(2);
const expiryOnly = argv.includes("--expiry-only");
const positional = argv.filter((a) => !a.startsWith("--"));
if (positional.length > 1)
  cannotRun(`expected at most one origin, got: ${positional.join(" ")}`);
const origin = positional[0] ?? "http://localhost:3001";

const gates = loadGates();
const nAuthored = gates.filter((g) => g.kind === "authored").length;
const nDerived = gates.filter((g) => g.kind === "derived").length;
console.log(`gates: ${gates.length} (${nAuthored} authored, ${nDerived} derived) from ${GATES_PATH}`);

checkExpiry(gates, loadGeneratedAt());
const expiryFailed = fail > 0;

if (!expiryOnly) {
  await checkDom(gates, origin);
}

console.log(`\n${pass} PASS / ${fail} FAIL`);
// Expiry wins the exit code when both halves fail: it is the half that runs
// unattended, so it is the half a red CI run is most likely to be about.
process.exit(fail === 0 ? EXIT_OK : expiryFailed ? EXIT_EXPIRY : EXIT_DOM);
