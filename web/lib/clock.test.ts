import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { windowEndLabel } from "@/lib/format";

// THE SINGLE-WRITER CLOCK INVARIANT, ENFORCED RATHER THAN DESCRIBED.
//
// docs/status.md rules it: the collectors stamp wall clock into each row they write,
// generated_at is the record's own maximum of those stamps, and every figure a reader
// sees is anchored to the record's clock -- never to the clock of whatever machine is
// rendering. The entry this superseded FAILED as a description: it said `new Date()` was
// prohibited in the web layer while two live sites called it. The difference between
// that entry and this file is that this one runs.
//
// WHAT IS ASSERTED IS THE ABSENCE OF A BARE WALL-CLOCK READ, not the presence of an
// anchor. `new Date(iso)` is a parse and is fine; `new Date(0)` is a constant and is fine;
// only the no-argument form reads the machine's clock, and it is the one form that cannot
// be anchored to anything.
//
// TWO SPELLINGS, NOT ONE. This banned `new Date()` alone until 2026-09-17, and
// `Date.now()` is the same read by another name -- it would have passed a green test
// while doing exactly what the rule forbids. Neither spelling appears in the layer today
// (grepped before the ban was widened, so this closes a hole rather than a breach), and
// the list is what a reader extends when a third spelling turns up.
//
// OUT OF SCOPE, deliberately: `performance.now()`. It is a MONOTONIC counter measured
// from an arbitrary origin, not a wall clock, so it cannot render a date and cannot drift
// against the record. Banning it would be banning a stopwatch. Also absent and unbanned,
// checked the same day: `new Date` without parentheses, a bare `Date()` call, and
// `Intl.DateTimeFormat(...).format()` with no argument -- each of which DOES read the
// clock. They are named here so the next reader knows the list is a list of what was
// looked for, not a claim that these two are the only ways to ask a machine the time.
const CLOCK_READS: ReadonlyArray<readonly [RegExp, string]> = [
  [/new Date\(\s*\)/, "new Date()"],
  [/\bDate\.now\s*\(/, "Date.now()"],
];
const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const DIRS = ["app", "lib", "components"];

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...sources(p));
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

// Comments are stripped before the search, because this rule is about what the code
// DOES. Six files in this layer carry a "NO `new Date()`" comment explaining why they
// hold the line, and a check that failed on those would be a check that punishes the
// documentation of the rule it enforces.
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

describe("the clock invariant", () => {
  it("no rendered figure reads the machine's clock", () => {
    const offenders: string[] = [];
    for (const dir of DIRS) {
      for (const file of sources(join(ROOT, dir))) {
        const src = code(readFileSync(file, "utf8"));
        for (const [re, label] of CLOCK_READS) {
          if (re.test(src)) offenders.push(`${file.slice(ROOT.length)} (${label})`);
        }
      }
    }
    expect(
      offenders,
      "a bare wall-clock read in the read layer: anchor it to the record (see docs/status.md, one writer many readers)",
    ).toEqual([]);
  });

  it("the anchor is MAX(fetched_at) over items, with no window guard", () => {
    // Asserted on the SQL for the reason db.test.ts gives: the file cannot be imported
    // without credentials, and the property under test is the shape of the query. A
    // guarded max -- MAX(CASE WHEN fetched_at >= ? ...) -- would return NULL once
    // collection stopped for longer than the guard, which is the exact failure the
    // anchor exists to survive: a frozen record must still say when it froze.
    const src = readFileSync(join(ROOT, "lib", "db.ts"), "utf8");
    const m = /export async function getRecordAnchor[\s\S]*?db\.execute\(\s*"([^"]+)"/.exec(src);
    expect(m, "getRecordAnchor no longer executes a single string query").not.toBeNull();
    const sql = m![1];
    expect(sql).toMatch(/MAX\(fetched_at\)/);
    expect(sql).toMatch(/FROM items/);
    expect(sql).not.toMatch(/WHERE/i);
    expect(sql).not.toMatch(/CASE/i);
  });

  it("both cached queries take the anchor, so it enters the cache key", () => {
    // next@15.5.19 keys an unstable_cache entry on cb.toString() + keyParts +
    // JSON.stringify(args) (dist/server/web/spec-extension/unstable-cache.js:55,82), so
    // an anchor passed as an argument invalidates the entry when the record moves. If
    // either of these goes back to computing its own value, the cache silently returns
    // to a timer and the two windows can drift apart again.
    const src = readFileSync(join(ROOT, "lib", "db.ts"), "utf8");
    expect(src).toMatch(/getChannelActivity = unstable_cache\(\s*\n\s*async \(anchorIso/);
    expect(src).toMatch(/getTimelineEntries = unstable_cache\(\s*\n\s*async \(anchorIso/);
  });
});

describe("windowEndLabel", () => {
  it("renders the record's edge in Z, minutes only", () => {
    expect(windowEndLabel("2026-09-16T17:02:40.518569+00:00")).toBe("17:02Z");
  });

  it("slices rather than parses, so no zone conversion can enter", () => {
    // A parse would render this in the runtime's zone on a machine set to anything but
    // UTC. The string is the value.
    expect(windowEndLabel("2026-01-01T00:00:00+00:00")).toBe("00:00Z");
  });

  it("is null when there is nothing to label", () => {
    expect(windowEndLabel(null)).toBeNull();
    expect(windowEndLabel("")).toBeNull();
    expect(windowEndLabel("not a date")).toBeNull();
  });
});
