/**
 * Asserts that EVERY CLAIM THE "WHERE THIS STANDS" SECTION MAKES IS REGISTERED,
 * AND THAT NO REGISTERED CLAIM HAS QUIETLY EXPIRED.
 *
 *   node scripts/assert-gates.mjs [origin]      # all five checks; needs a server
 *   node scripts/assert-gates.mjs --expiry-only # checks 3, 4 and 5; no browser, no server
 *
 * (`--expiry-only` is older than checks 4 and 5 and kept for ci.yml's sake: it means "the
 * half that needs no browser".)
 *
 * Exit code is the alarm, and it is SPLIT so a red run says which check failed -- the
 * highest in precedence (expiry, then held, then coverage, then DOM); the FAIL lines
 * give the rest:
 *
 *   0  every requested check passed
 *   1  EXPIRY failed -- an authored claim is past its recheck date
 *   2  DOM JOIN failed -- an ungated claim, a gate the page never renders, or a
 *      `data-gate-ref` pointer with nothing valid to point at
 *   3  the check could not run -- missing file, unreadable schema, bad usage
 *   4  HELD failed -- a docket an authored claim lists in `record_instruments` is
 *      neither held in data/cases.json nor a pinned seed awaiting its bind
 *   5  COVERAGE failed -- a class docket on no active or stale claim's list with no valid
 *      reason, a listed docket still carrying a reason, a reason on a seed outside the
 *      class, or an empty class; the FAIL lines say which, and each carries its own fix
 *
 * CHECK 5, COVERAGE (Corey, 2026-09-29). Check 4 confirms that a LISTED docket is held;
 * it reads none of its orders (the recheck flags, tools/recheck_flags.py and
 * coverage_audit section 9, report order-like entries above a listed docket's reading).
 * Neither could have caught the case that prompted this check, 1:26-cv-01114, whose
 * Sep 13 injunction sat unread on a docket no gate listed until a hand-read found it.
 * So every docket of the class -- `category: executive-order`, on a seed or a held
 * row -- must be on some active or stale authored claim's `record_instruments`, or carry
 * a reason on its seed in config/sources.yaml, `gate_coverage`, in a closed vocabulary:
 *
 *   consolidated    -- `into` a class docket that is itself listed (reasons do not
 *                      chain; a member cannot clear before its lead is read), with the
 *                      `record` that says so: a case_id (the member or its lead), the
 *                      entry's filing date and a quote of its text. Checked against that
 *                      docket's timeline in data/cases.json once it is held; pending
 *                      until then. THE QUOTE'S WINDOW: the timeline holds only entries
 *                      the collector promoted (is_substantive), each titled
 *                      "caption: " plus the first 180 characters of its description
 *                      (collectors/litigation.py). So the quote must come from that
 *                      window; case and runs of whitespace are ignored.
 *   no-claim-order  -- `read_through`, the day a person last read the docket's orders and
 *                      found none bearing on a claim, on or before the record's clock
 *                      plus a day. WATCHED FROM THAT DATE (Corey, 2026-09-29): the recheck
 *                      flags treat it as the docket's watermark, and an order-like entry
 *                      filed after it flags, saying the reason needs re-ruling.
 *
 * Both carry `ruled`: who decided, and when. A listed docket carrying a reason fails
 * ("remove the reason"), and so does a reason on a seed outside the class. There is NO
 * GRACE PERIOD: at a seed commit the docket is not yet held and nothing can see its
 * orders, so the rule requires the written outcome of a person reading them. What the
 * machine verifies is that a dated, attributed reading was written, not that it
 * happened. The recheck flags are the backstop: they watch every listed docket above its
 * reading, and every no-claim-order docket from its read-through date. A consolidated
 * member is watched only as far as its orders land on its listed lead. A shape error in a
 * reason is exit 3, like any malformed register.
 *
 * THE CLASS IS THE EXECUTIVE-ORDER DOCKETS ONLY (ruled). The voter-data rows' page
 * figures are derived gates, read from the record every render; scoping them in would
 * turn 53 rows red to be cleared by 53 stamps.
 *
 * READINGS (2026-09-29). An authored claim with `record_instruments` carries
 * `record_read`, one item per listed docket and no other, each with `docket`, `read_on`,
 * `through_entry_id` (MAX(case_entries.id) held at the reading), `through_entry_at` and
 * `verdicts` (entry id -> operative | noise | missed | duplicate | unread, the classes
 * ruled 2026-09-29). The loader refuses any other shape
 * (exit 3). tools/recheck_flags.py reads the watermark; nothing here compares it with
 * the record, since data/cases.json carries no entry ids.
 *
 * CHECK 4, HELD INSTRUMENTS (2026-09-27). An authored claim may list, in
 * `record_instruments`, the held dockets among those its `falsified_by` names. A
 * listed docket must be held -- a row in data/cases.json -- or be PENDING: a seed in
 * config/sources.yaml pinned to that id, not yet bound, while the record's clock is
 * on or before the entry's `record_instruments_due`. Pending is what keeps a seed
 * commit's own push green -- its dockets bind on the next collect run, not on the push
 * -- and the due date is what ends it, so a seed that never binds turns this check red
 * instead of passing forever.
 *
 * IT WITNESSES THE BIND, NEVER THE WALK. The collector writes a seed's row before it
 * decides whether to walk or defer (collectors/litigation.py), and data/cases.json
 * carries every row with no entries_synced_at, so a seed stops being pending at the
 * first data commit after it binds, walked or not. The walk is coverage_audit section
 * 6's reading. A pin the collector BYPASSED -- a held row for the seed's docket number
 * and court under another id, which the collector reuses without fetching the pin --
 * is missing at once. The failure this exists for is the `rekey_slug_cases` shape: a
 * docket re-keyed or dropped while a claim still sends its recheck there.
 *
 * ALIASES (2026-09-27). An entry may carry `aliases`, the ids it was known by before
 * a rename. Every check that resolves an id -- the DOM join's `data-gate` and
 * `data-gate-ref` -- resolves an alias to its entry, so a page or a record still
 * naming the old id is not an ungated claim. An alias that collides with an id or with
 * another alias is a malformed register (exit 3).
 *
 * 3 is deliberately not 1. A check that could not run is not a check that passed
 * and is not a claim that failed; collapsing those is how a broken instrument
 * reads as a clean bill of health.
 *
 * CHECK 4 RIDES THE SAME ENTRY POINT AS CHECK 3: it needs data/cases.json and
 * config/sources.yaml, both committed, and no browser. It reads neither when every
 * list is empty.
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
const CASES_PATH = process.env.CASES_PATH ?? resolve(REPO, "data", "cases.json");
const SOURCES_PATH = process.env.SOURCES_PATH ?? resolve(REPO, "config", "sources.yaml");

/** The attributes D4's component must carry: one on the section root, one on each
 *  element making a registered claim. Named here so both sides read one string. */
const SECTION_SELECTOR = '[data-section="where-this-stands"]';
const GATE_ATTR = "data-gate";
/** A POINTER to a gated claim, for text that names a claim without restating it --
 *  tab 2's "In force today" step names two provisions and sends the reader to their
 *  gated claims on tab 1. It carries no `renders_as` and no register entry of its
 *  own, which is the point: one entry per claim, and no second wording of it that
 *  nothing compares. What is checked is that the pointer has a target. */
const GATE_REF_ATTR = "data-gate-ref";

const EXIT_OK = 0;
const EXIT_EXPIRY = 1;
const EXIT_DOM = 2;
const EXIT_CANNOT_RUN = 3;
const EXIT_HELD = 4;
const EXIT_COVERAGE = 5;

/** The class check 5 covers (ruled 2026-09-29): read off `category` alone, as the page
 *  reads it (web/lib/stands.ts isEoChallenge). */
const COVERAGE_CLASS = new Set(["executive-order"]);
/** Each reason kind's exact keys. A key outside them is a malformed register. */
const COVERAGE_KEYS = {
  consolidated: ["unlisted", "into", "record", "ruled"],
  "no-claim-order": ["unlisted", "read_through", "ruled"],
};
const COVERAGE_RECORD_KEYS = ["case_id", "entry_at", "quote"];
/** Keys a reason kind MAY carry beside its required ones: a no-claim-order docket's verdicts
 *  on its recheck flags, since it has no reading to carry them (2026-09-29). */
const COVERAGE_OPTIONAL = { "no-claim-order": ["verdicts"] };
const READING_KEYS = ["docket", "read_on", "through_entry_id", "through_entry_at", "verdicts"];
const VERDICTS = new Set(["operative", "noise", "missed", "duplicate", "unread"]);

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

    if (g.aliases !== undefined &&
        (!Array.isArray(g.aliases) || g.aliases.some((a) => typeof a !== "string" || !a)))
      problems.push(`${at}: \`aliases\` must be a list of non-empty strings`);

    if (g.record_instruments !== undefined) {
      if (g.kind !== "authored")
        problems.push(`${at}: \`record_instruments\` belongs on an authored claim`);
      else if (!Array.isArray(g.record_instruments) ||
               g.record_instruments.some((c) => !/^\d+$/.test(String(c))))
        problems.push(`${at}: \`record_instruments\` must be a list of CourtListener docket ids`);
    }
    if (g.record_read !== undefined || Array.isArray(g.record_instruments)) {
      const listed = Array.isArray(g.record_instruments) ? g.record_instruments.map(String) : [];
      const rr = g.record_read;
      if (rr === undefined) {
        if (listed.length) problems.push(`${at}: lists ${listed.join(", ")} and carries no \`record_read\``);
      } else if (!Array.isArray(rr)) {
        problems.push(`${at}: \`record_read\` must be a list`);
      } else {
        const seenDockets = new Map();
        for (const [j, r] of rr.entries()) {
          const rat = `${at}: record_read[${j}]`;
          if (!r || typeof r !== "object" || Array.isArray(r)) {
            problems.push(`${rat}: not a mapping`);
            continue;
          }
          const extra = Object.keys(r).filter((k) => !READING_KEYS.includes(k));
          if (extra.length) problems.push(`${rat}: unknown keys ${extra.join(", ")}`);
          const d = String(r.docket ?? "");
          seenDockets.set(d, (seenDockets.get(d) ?? 0) + 1);
          if (!listed.includes(d)) problems.push(`${rat}: docket ${d} is not in \`record_instruments\``);
          for (const f of ["read_on", "through_entry_at"])
            if (typeof r[f] !== "string" || !ISO_DATE.test(r[f]))
              problems.push(`${rat}: \`${f}\` must be a YYYY-MM-DD STRING`);
          if (!Number.isInteger(r.through_entry_id) || r.through_entry_id < 0)
            problems.push(`${rat}: \`through_entry_id\` must be a non-negative integer`);
          const v = r.verdicts ?? {};
          if (!v || typeof v !== "object" || Array.isArray(v))
            problems.push(`${rat}: \`verdicts\` must map entry ids to a verdict`);
          else
            for (const [k, val] of Object.entries(v))
              if (!/^\d+$/.test(k) || !VERDICTS.has(val))
                problems.push(`${rat}: verdict ${k}: ${JSON.stringify(val)} (operative | noise | missed | duplicate | unread)`);
        }
        for (const d of listed)
          if ((seenDockets.get(d) ?? 0) !== 1)
            problems.push(`${at}: listed docket ${d} has ${seenDockets.get(d) ?? 0} readings in \`record_read\` (expect 1)`);
      }
    }
    if (g.record_instruments_due !== undefined) {
      if (!Array.isArray(g.record_instruments))
        problems.push(`${at}: \`record_instruments_due\` without \`record_instruments\``);
      else if (typeof g.record_instruments_due !== "string" || !ISO_DATE.test(g.record_instruments_due))
        problems.push(`${at}: \`record_instruments_due\` must be a YYYY-MM-DD STRING`);
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
  // An alias may not shadow an id or another alias: two entries answering to one name
  // is a join that resolves either way depending on order.
  for (const g of doc) {
    if (!g || !Array.isArray(g.aliases)) continue;
    for (const a of g.aliases) {
      const owners = doc.filter((h) => h && (h.id === a || (Array.isArray(h.aliases) && h.aliases.includes(a))));
      if (owners.length > 1) problems.push(`alias ${a} (on ${g.id}) is also ${owners.filter((h) => h !== g).map((h) => h.id).join(", ")}'s`);
    }
  }
  if (problems.length)
    cannotRun(`${GATES_PATH} is malformed:\n        ${problems.join("\n        ")}`);
  return doc;
}

/** Every name an entry answers to -- its id and its aliases -- mapped to its id. */
function namesOf(gates) {
  const names = new Map();
  for (const g of gates) {
    names.set(g.id, g.id);
    for (const a of Array.isArray(g.aliases) ? g.aliases : []) if (!names.has(a)) names.set(a, g.id);
  }
  return names;
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
        `${g.id} -- recheck ${g.recheck_after} PAST, marked stale by hand (status: stale)`
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
  let present;
  let refs = [];
  let status = null;
  try {
    const page = await browser.newPage();
    // The response is CAPTURED rather than discarded, and that capture is the whole of
    // the instrument the CANNOT RUN message below gained. `page.goto` returns null only
    // for a same-document navigation, which a fresh page cannot make -- so the null is
    // handled rather than asserted away.
    const response = await page.goto(origin, { waitUntil: "networkidle" });
    status = response === null ? null : response.status();
    present = await page.evaluate(
      ([sel, attr]) => {
        const root = document.querySelector(sel);
        if (!root) return null;
        return [...root.querySelectorAll(`[${attr}]`)].map((el) => el.getAttribute(attr));
      },
      [SECTION_SELECTOR, GATE_ATTR]
    );
    refs =
      (await page.evaluate(
        ([sel, attr]) => {
          const root = document.querySelector(sel);
          if (!root) return null;
          return [...root.querySelectorAll(`[${attr}]`)].map((el) => el.getAttribute(attr));
        },
        [SECTION_SELECTOR, GATE_REF_ATTR]
      )) ?? [];
  } finally {
    await browser.close();
  }

  if (present === null) {
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

  // PRESENT, NOT RENDERED, and the labels below say so. This join is
  // `querySelectorAll`, which returns an element inside a `hidden` panel exactly as it
  // returns a visible one -- measured in chromium-1228 on a page of that shape. Five of
  // the section's seventeen gates sit behind `wts-next` as of 2026-09-28, so a green join has never
  // been evidence that a claim was on screen. Rendering is `assert-layout`'s question,
  // and it could not answer it either until it learned to click the tabs.
  // Resolved through aliases: a page still carrying an entry's former id is joined to
  // the entry, and said so, rather than reported as an ungated claim.
  const names = namesOf(gates);
  const canonical = (id) => names.get(id) ?? id;
  const viaAlias = [...new Set([...present, ...refs])].filter((id) => names.has(id) && names.get(id) !== id);
  if (viaAlias.length)
    console.log(`INFO  resolved through an alias: ${viaAlias.map((id) => `${id} -> ${names.get(id)}`).join(", ")}`);
  const emitted = new Set(present.map(canonical));
  const registered = new Set(
    gates.filter((g) => g.renders_as !== undefined).map((g) => g.id)
  );

  const ungated = [...emitted].filter((id) => !registered.has(id));
  const orphan = [...registered].filter((id) => !emitted.has(id));

  check(
    ungated.length === 0,
    `every ${GATE_ATTR} present in the section is registered (${emitted.size} on the page)`,
    ungated.length ? `ungated claims: ${ungated.join(", ")}` : undefined
  );
  check(
    orphan.length === 0,
    `every registered gate with \`renders_as\` is present (${registered.size} in the register)`,
    orphan.length ? `registered but never present: ${orphan.join(", ")}` : undefined
  );

  // POINTERS. A ref must name an AUTHORED gate -- a derived figure is rendered where
  // it is used, never pointed at -- that is registered, NOT FALSIFIED, and itself
  // present in the section, so the reader sent to it finds it. It does NOT check WHERE
  // in the section: the pointer's words "the first tab" are the component's, and a
  // target moved to another tab would pass here.
  //
  // NOT FALSIFIED RATHER THAN ACTIVE, deliberately. `stale` is a human's
  // acknowledgement that a claim is past due (docs/gates.yaml's header), and the claim
  // still renders, grey. Failing the pointer on `stale` would make that acknowledgement
  // cost a second edit on another tab, which is pressure against acknowledging at all.
  // A falsified claim is different: the pointer would send a reader to something the
  // register itself has retracted.
  const byId = new Map(gates.map((g) => [g.id, g]));
  const badRefs = [];
  for (const raw of new Set(refs)) {
    const id = canonical(raw);
    const label = raw === id ? raw : `${raw} (alias of ${id})`;
    const g = byId.get(id);
    if (!g) badRefs.push(`${raw}: not in the register`);
    else if (g.kind !== "authored") badRefs.push(`${label}: ${g.kind}, not authored`);
    else if (g.status === "falsified") badRefs.push(`${label}: falsified`);
    else if (!emitted.has(id)) badRefs.push(`${label}: no ${GATE_ATTR} for it in the section`);
  }
  check(
    badRefs.length === 0,
    `every ${GATE_REF_ATTR} points at a registered, unfalsified authored gate present in the section (${refs.length} on the page)`,
    badRefs.length ? badRefs.join("; ") : undefined
  );
}

// --- check 4: held instruments ---------------------------------------------------

/** config/sources.yaml's seeds that pin a CourtListener id, keyed by that id. Returns
 *  a string, not a Map, when the file cannot be read: see checkHeld. */
function pinnedSeeds() {
  if (!existsSync(SOURCES_PATH)) return `no sources file at ${SOURCES_PATH}`;
  let doc;
  try {
    doc = require("yaml").parse(readFileSync(SOURCES_PATH, "utf8"));
  } catch (e) {
    return `${SOURCES_PATH} is not valid YAML: ${e.message}`;
  }
  const seeds = doc?.litigation?.seed_cases;
  if (!Array.isArray(seeds)) return `${SOURCES_PATH} has no litigation.seed_cases list`;
  return new Map(
    seeds.filter((s) => s?.case_id !== undefined && s?.case_id !== null).map((s) => [String(s.case_id), s])
  );
}

/** Check 4. Returns a cannot-run message instead of exiting, so a record-file problem
 *  is reported AFTER the DOM join rather than instead of it. */
function checkHeld(gates, today) {
  console.log(`\n--- held instruments, against ${CASES_PATH} ---`);
  // An empty list names nothing to hold, and reads no file: the rewording push ships
  // both 14399 lists empty.
  const listed = gates.filter((g) => Array.isArray(g.record_instruments) && g.record_instruments.length > 0);
  if (listed.length === 0) {
    check(true, "no authored claim lists a record instrument yet");
    return null;
  }
  if (!existsSync(CASES_PATH))
    return `no ${CASES_PATH} -- the export writes it each run; run \`python -m export.snapshots\``;
  let rows;
  try {
    rows = JSON.parse(readFileSync(CASES_PATH, "utf8"));
  } catch (e) {
    return `${CASES_PATH} is not valid JSON: ${e.message}`;
  }
  if (!Array.isArray(rows)) return `${CASES_PATH} must be a list of cases`;
  const seeds = pinnedSeeds();
  if (typeof seeds === "string") return seeds;
  const held = new Set(rows.map((r) => String(r?.case_id)));
  for (const g of listed) {
    const due = g.record_instruments_due ?? null;
    const ids = g.record_instruments.map(String);
    const missing = [];
    const pending = [];
    for (const c of ids) {
      if (held.has(c)) continue;
      const seed = seeds.get(c);
      if (!seed) {
        missing.push(`${c} (neither held nor a pinned seed)`);
        continue;
      }
      // The collector's reuse path: a held row for this seed's docket and court under
      // another id is used as found, and the pin is never fetched.
      const other = rows.find(
        (r) => r?.docket_number === seed.docket_number && r?.court === seed.court && String(r?.case_id) !== c
      );
      if (other) missing.push(`${c} (its seed's docket is held as ${other.case_id}; the pin was bypassed)`);
      else if (due !== null && today > due) missing.push(`${c} (pinned, never bound, due ${due})`);
      else pending.push(c);
    }
    const nHeld = ids.length - missing.length - pending.length;
    check(
      missing.length === 0,
      `${g.id} -- ${nHeld} of ${ids.length} listed dockets held` +
        (pending.length ? `; ${pending.length} seeded, not yet bound${due ? ` (due ${due})` : ""}: ${pending.join(", ")}` : ""),
      missing.length ? missing.join("; ") : undefined
    );
  }
  return null;
}

// --- check 5: coverage -----------------------------------------------------------

/** The day after an ISO date, as an ISO date. From the date given, never the wall
 *  clock: `new Date(ms)` of a computed instant reads no clock. */
function nextDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d) + 86400000).toISOString().slice(0, 10);
}

/** Every recorded reason's SHAPE, on every seed. Shape errors are a malformed register
 *  (exit 3), returned as one message; what a well-formed reason claims is check 5's. */
function coverageShapeProblems(seeds) {
  const problems = [];
  for (const s of seeds) {
    const gc = s?.gate_coverage;
    if (gc === undefined) continue;
    const at = `seed ${s?.case_id ?? s?.docket_number}`;
    if (!gc || typeof gc !== "object" || Array.isArray(gc)) {
      problems.push(`${at}: \`gate_coverage\` must be a mapping`);
      continue;
    }
    const keys = COVERAGE_KEYS[gc.unlisted];
    if (!keys) {
      problems.push(`${at}: \`gate_coverage.unlisted\` must be ${Object.keys(COVERAGE_KEYS).join(" or ")}, got ${JSON.stringify(gc.unlisted)}`);
      continue;
    }
    const have = Object.keys(gc);
    const optional = COVERAGE_OPTIONAL[gc.unlisted] ?? [];
    const extra = have.filter((k) => !keys.includes(k) && !optional.includes(k));
    const missing = keys.filter((k) => !have.includes(k));
    if (extra.length) problems.push(`${at}: \`gate_coverage\` (${gc.unlisted}) does not take ${extra.join(", ")}`);
    if (missing.length) problems.push(`${at}: \`gate_coverage\` (${gc.unlisted}) needs ${missing.join(", ")}`);
    if (typeof gc.ruled !== "string" || !gc.ruled.trim()) problems.push(`${at}: \`gate_coverage.ruled\` must say who ruled, and when`);
    if (gc.unlisted === "consolidated") {
      if (!/^\d+$/.test(String(gc.into ?? ""))) problems.push(`${at}: \`gate_coverage.into\` must be a CourtListener docket id`);
      const rec = gc.record;
      if (!rec || typeof rec !== "object" || Array.isArray(rec)) {
        problems.push(`${at}: \`gate_coverage.record\` must be a mapping`);
      } else {
        const rx = Object.keys(rec).filter((k) => !COVERAGE_RECORD_KEYS.includes(k));
        const rm = COVERAGE_RECORD_KEYS.filter((k) => !(k in rec));
        if (rx.length || rm.length)
          problems.push(`${at}: \`gate_coverage.record\` takes exactly ${COVERAGE_RECORD_KEYS.join(", ")}`);
        if (!/^\d+$/.test(String(rec.case_id ?? ""))) problems.push(`${at}: \`gate_coverage.record.case_id\` must be a docket id`);
        if (typeof rec.entry_at !== "string" || !ISO_DATE.test(rec.entry_at))
          problems.push(`${at}: \`gate_coverage.record.entry_at\` must be a YYYY-MM-DD STRING`);
        if (typeof rec.quote !== "string" || rec.quote.trim().length < 12)
          problems.push(`${at}: \`gate_coverage.record.quote\` must quote the entry, not gesture at it`);
      }
    }
    if (gc.unlisted === "no-claim-order" && (typeof gc.read_through !== "string" || !ISO_DATE.test(gc.read_through)))
      problems.push(`${at}: \`gate_coverage.read_through\` must be a YYYY-MM-DD STRING`);
    if (gc.verdicts !== undefined) {
      const v = gc.verdicts;
      if (!v || typeof v !== "object" || Array.isArray(v))
        problems.push(`${at}: \`gate_coverage.verdicts\` must map entry ids to a verdict`);
      else
        for (const [k, val] of Object.entries(v))
          if (!/^\d+$/.test(k) || !VERDICTS.has(val))
            problems.push(`${at}: \`gate_coverage.verdicts\` ${k}: ${JSON.stringify(val)} (operative | noise | missed | duplicate | unread)`);
    }
  }
  return problems;
}

/** Check 5. Returns a cannot-run message instead of exiting, as check 4 does. */
function checkCoverage(gates, today) {
  console.log(`\n--- coverage, the executive-order class against the gates' lists ---`);
  if (!existsSync(SOURCES_PATH)) return `no sources file at ${SOURCES_PATH}`;
  let doc;
  try {
    doc = require("yaml").parse(readFileSync(SOURCES_PATH, "utf8"));
  } catch (e) {
    return `${SOURCES_PATH} is not valid YAML: ${e.message}`;
  }
  const seeds = doc?.litigation?.seed_cases;
  if (!Array.isArray(seeds)) return `${SOURCES_PATH} has no litigation.seed_cases list`;
  const shape = coverageShapeProblems(seeds);
  if (shape.length) return `${SOURCES_PATH} is malformed:\n        ${shape.join("\n        ")}`;
  if (!existsSync(CASES_PATH))
    return `no ${CASES_PATH} -- the export writes it each run; run \`python -m export.snapshots\``;
  let rows;
  try {
    rows = JSON.parse(readFileSync(CASES_PATH, "utf8"));
  } catch (e) {
    return `${CASES_PATH} is not valid JSON: ${e.message}`;
  }
  if (!Array.isArray(rows)) return `${CASES_PATH} must be a list of cases`;

  const heldById = new Map(rows.map((r) => [String(r?.case_id), r]));
  // The class: every seed marked, and every held row marked (a row the collector holds
  // under a mark its seed no longer carries is still on the page).
  const cls = new Map();
  for (const s of seeds)
    if (COVERAGE_CLASS.has(s?.category) && s?.case_id !== undefined && s?.case_id !== null)
      cls.set(String(s.case_id), { docket: s.docket_number, seed: s });
  for (const r of rows)
    if (COVERAGE_CLASS.has(r?.category) && !cls.has(String(r.case_id)))
      cls.set(String(r.case_id), { docket: r.docket_number, seed: null });
  // Active or stale, never falsified: a retracted claim reads nothing.
  const listed = new Map();
  for (const g of gates)
    if (g.kind === "authored" && g.status !== "falsified" && Array.isArray(g.record_instruments))
      for (const c of g.record_instruments.map(String)) listed.set(c, [...(listed.get(c) ?? []), g.id]);

  for (const s of seeds)
    if (s?.gate_coverage !== undefined && !COVERAGE_CLASS.has(s?.category))
      check(false, `seed ${s.case_id ?? s.docket_number} ${s.docket_number} -- carries a coverage reason outside the class`,
        `\`gate_coverage\` is read on ${[...COVERAGE_CLASS].join(", ")} seeds only; remove it`);

  check(cls.size > 0, `the class holds at least one docket (${cls.size})`);
  for (const [c, { docket, seed }] of [...cls].sort()) {
    const reason = seed?.gate_coverage;
    const label = `${c} ${docket}`;
    if (listed.has(c)) {
      check(!reason, `${label} -- listed on ${listed.get(c).join(", ")}`,
        reason ? "it also carries a coverage reason on its seed: a listed docket needs none; remove the reason" : undefined);
      continue;
    }
    if (!reason) {
      check(false, `${label} -- on no gate's record_instruments and carries no recorded reason`,
        "Read its orders. Then list it on the gate its orders bear on (that gate's falsifier names it; " +
          "an order bearing on no claim means a new gate), or record why not in `gate_coverage` on its seed.");
      continue;
    }
    if (reason.unlisted === "no-claim-order") {
      const limit = nextDay(today);
      check(reason.read_through <= limit,
        `${label} -- read through ${reason.read_through}, no order bearing on a claim (${reason.ruled})`,
        reason.read_through > limit ? `read_through is after the record's clock ${today} plus a day` : undefined);
      continue;
    }
    // consolidated
    const into = String(reason.into);
    const rec = reason.record;
    const recId = String(rec.case_id);
    if (into === c) check(false, `${label} -- consolidated into itself`);
    else if (!cls.has(into)) check(false, `${label} -- consolidated into ${into}, which is not a class docket`);
    else if (!listed.has(into))
      check(false, `${label} -- consolidated into ${into}, which is on no gate's list`,
        "Reasons do not chain: read the lead's orders and list it first.");
    else if (recId !== c && recId !== into)
      check(false, `${label} -- its record names ${recId}, neither it nor its lead ${into}`);
    else if (!heldById.has(recId))
      check(true, `${label} -- consolidated into ${into} (listed on ${listed.get(into).join(", ")}); ` +
        `its record on ${recId} is PENDING, not yet held`);
    else {
      const squash = (s) => String(s ?? "").toLowerCase().replace(/\s+/g, " ").trim();
      const quote = squash(rec.quote);
      const onDate = (heldById.get(recId).timeline ?? []).filter(
        (t) => String(t?.occurred_at ?? "").slice(0, 10) === rec.entry_at);
      const hit = onDate.find((t) => squash(t?.title).includes(quote));
      check(Boolean(hit),
        `${label} -- consolidated into ${into} (listed on ${listed.get(into).join(", ")})` +
          (hit ? `; on the record as item ${hit.id}, ${rec.entry_at}` : ""),
        hit ? undefined
          : onDate.length === 0
            ? `${recId}'s timeline holds no item dated ${rec.entry_at}`
            : `none of ${recId}'s ${onDate.length} timeline item(s) dated ${rec.entry_at} carries the quote ` +
              `"${rec.quote}" in its title (the caption plus the first 180 characters of a promoted entry)`);
    }
  }
  return null;
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

const today = loadGeneratedAt();
checkExpiry(gates, today);
const expiryFailed = fail > 0;

const beforeHeld = fail;
const heldCannot = checkHeld(gates, today);
const heldFailed = fail > beforeHeld;

const beforeCoverage = fail;
const coverageCannot = checkCoverage(gates, today);
const coverageFailed = fail > beforeCoverage;

if (!expiryOnly) {
  await checkDom(gates, origin);
}
if (heldCannot) cannotRun(`check 4: ${heldCannot}`);
if (coverageCannot) cannotRun(`check 5: ${coverageCannot}`);

console.log(`\n${pass} PASS / ${fail} FAIL`);
// Expiry wins the exit code when several checks fail: it is the half that runs
// unattended, so it is the half a red CI run is most likely to be about. Held comes
// next, for the same reason -- it runs in ci.yml too -- then coverage, which runs there
// as well, and the DOM join last.
process.exit(
  fail === 0 ? EXIT_OK
    : expiryFailed ? EXIT_EXPIRY
    : heldFailed ? EXIT_HELD
    : coverageFailed ? EXIT_COVERAGE
    : EXIT_DOM
);
