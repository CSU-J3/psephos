import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, sep } from "node:path";

// EVERY SOURCE DATE RENDERS THROUGH RecordDate, ENFORCED RATHER THAN DESCRIBED (ruled
// 2026-09-26). components/RecordDate.tsx is what compares a source's date against the
// record's clock and marks it "dated ahead"; a date rendered around it is invisible to
// that rule and to web/scripts/assert-dated.mjs, which reads only `data-record-date`.
// The component tests render each row component, but a page header or a panel line
// written with `formatDate(...)` or `.slice(0, 10)` is reached by none of them -- the
// adversarial review of 2026-09-26 found the map panel's filed date doing exactly that,
// and showed a header reverted to `formatDate` would pass every test and the live lane.
//
// WHAT IS LISTED IS WHAT A SOURCE DATES, not what is exempt. The names are the record's
// source-date columns (items, bills, state_bills, cases, case_entries, bill_actions) and
// the props that carry them to the wire and the map. A receipt -- `status_checked_at`,
// `fetched_at`, a run's `finished_at` -- is psephos's own clock and is simply not on the
// list, so there is no exemption list to keep; a new source-date column is what a reader
// adds here.
const SOURCE_DATES = [
  "occurred_at",
  "last_action_at",
  "latest_action_at",
  "latest_entry_at",
  "filed_at",
  "introduced_at",
  "entry_at",
  "action_at",
  "rejected_at",
  "date_terminated",
  // carried under other names
  "latestActionAt",
  "latestFiling",
  "filed",
].join("|");

// The three ways a date gets rendered around the component. Each is anchored to a JSX
// expression container -- `{` not preceded by `$` (a template literal) or `=` (a prop,
// where `value={it.occurred_at}` is RecordDate's own input) -- or to a formatter call.
const RENDERED_AROUND: ReadonlyArray<readonly [RegExp, string]> = [
  [new RegExp(String.raw`\bformatDate\(\s*[^)]*\b(?:${SOURCE_DATES})\b`), "formatDate(<source date>)"],
  [
    new RegExp(String.raw`(?<![$=])\{\s*[\w.?!\[\]]*\b(?:${SOURCE_DATES})[?!]?\.slice\(`),
    "{<source date>.slice(...)}",
  ],
  [
    new RegExp(String.raw`(?<![$=])\{\s*[\w.?!\[\]]+\.(?:${SOURCE_DATES})[?!]?\s*\}`),
    "{<source date>}",
  ],
];

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const DIRS = ["app", "components"];
const RENDERER = "components/RecordDate.tsx";

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...sources(p));
    else if (/\.tsx$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

function rel(file: string): string {
  return file.slice(ROOT.length).split(sep).join("/");
}

// Comments stripped, as lib/clock.test.ts does: the rule is about what the code renders,
// and several files explain in a comment the very form this bans.
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

function offenders(src: string): string[] {
  return RENDERED_AROUND.filter(([re]) => re.test(src)).map(([, label]) => label);
}

describe("every source date renders through RecordDate", () => {
  it("no page or component renders one around it", () => {
    const found: string[] = [];
    for (const dir of DIRS) {
      for (const file of sources(join(ROOT, dir))) {
        if (rel(file) === RENDERER) continue;
        for (const label of offenders(code(readFileSync(file, "utf8")))) {
          found.push(`${rel(file)} (${label})`);
        }
      }
    }
    expect(
      found,
      "a source date rendered around components/RecordDate.tsx, so no 'dated ahead' rule reaches it",
    ).toEqual([]);
  });

  // The patterns are what stands between a regression and a green suite, so each is
  // pinned against the shape it exists to catch -- including the three real ones this
  // unit replaced -- and against the shapes it must leave alone.
  it.each([
    ["{formatDate(bill.last_action_at)} — ", true], // /state-bill/[id] header, before
    ['{d.docket} · filed {d.filed?.slice(0, 10) ?? "—"} · {d.status}', true], // the map panel, before
    ["<td>{c.latest_entry_at}</td>", true],
    ["<RecordDate value={bill.last_action_at} clock={clock} />", false],
    ["status last read {formatDate(c.live.status_checked_at)}", false], // a receipt
    ["date: it.occurred_at!.slice(0, 10),", false], // a computation, not a render
    ["t: Date.parse(`${it.occurred_at!.slice(0, 10)}T00:00:00Z`),", false],
    ["key={`${e.date}-${e.title}`}", false],
  ])("%s -> flagged %s", (line, flagged) => {
    expect(offenders(line).length > 0).toBe(flagged);
  });
});
