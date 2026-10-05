// CHECK 5 AND THE READINGS, EACH SEEN TO FAIL (Corey, 2026-09-29). assert-gates.mjs runs
// its checks at import and exits, so it is exercised the way ci.yml runs it: a child
// process on `--expiry-only`, pointed by its path overrides at copies of the real
// register, seeds and record, each copy mutated to plant one fault. The real files must
// pass; every planted fault must fail with the exit code its check owns -- 5 for a
// coverage fault, 3 for a malformed reason or reading. A check never seen to fail is not
// known to work.
//
// It lives beside the script and runs in ci.yml's web job, where node and the `yaml`
// package are installed; the python job has neither.
import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import YAML from "yaml";

const WEB = resolve(import.meta.dirname, "..");
const REPO = resolve(WEB, "..");
const SCRIPT = join(WEB, "scripts", "assert-gates.mjs");

type Seed = Record<string, unknown> & { case_id?: string; category?: string };
type Gate = Record<string, unknown> & { id: string };

const realGates = (): Gate[] => YAML.parse(readFileSync(join(REPO, "docs", "gates.yaml"), "utf8"));
const realSources = () => YAML.parse(readFileSync(join(REPO, "config", "sources.yaml"), "utf8"));
const realCases = () => JSON.parse(readFileSync(join(REPO, "data", "cases.json"), "utf8"));

function run(
  mutate: { gates?: (g: Gate[]) => void; seeds?: (s: Seed[]) => void; clock?: string } = {}
) {
  const dir = mkdtempSync(join(tmpdir(), "assert-gates-"));
  const gates = realGates();
  const sources = realSources();
  const clock = mutate.clock ?? defaultClock();
  mutate.gates?.(gates);
  mutate.seeds?.(sources.litigation.seed_cases);
  writeFileSync(join(dir, "gates.yaml"), YAML.stringify(gates));
  writeFileSync(join(dir, "sources.yaml"), YAML.stringify(sources));
  writeFileSync(join(dir, "cases.json"), JSON.stringify(realCases()));
  // A clock before every real recheck date, so check 3 stays quiet and each case fails
  // on its planted fault alone.
  writeFileSync(join(dir, "generated_at.json"),
    JSON.stringify({ generated_at: `${clock}T12:00:00+00:00` }));
  const r = spawnSync(process.execPath, [SCRIPT, "--expiry-only"], {
    encoding: "utf8",
    env: {
      ...process.env,
      GATES_PATH: join(dir, "gates.yaml"),
      SOURCES_PATH: join(dir, "sources.yaml"),
      CASES_PATH: join(dir, "cases.json"),
      GENERATED_AT_PATH: join(dir, "generated_at.json"),
    },
  });
  return { code: r.status, out: `${r.stdout}${r.stderr}` };
}

const CLOCK_FLOOR = "2026-09-29";
/** The default clock moves with the real seeds: never before the latest real
 *  no-claim-order `read_through`, so a real reason read after the floor does not turn
 *  this suite red while ci.yml, on the real clock, passes. Read off the committed config,
 *  so a planted date never moves it. A case that judges a planted reason against the clock
 *  takes its dates from here, never from a literal (EPIC's real Oct 2 reason, 2026-10-05,
 *  turned two literal-clock cases red). */
function defaultClock(): string {
  const reads = (realSources().litigation.seed_cases as Seed[])
    .map((s) => (s.gate_coverage as { read_through?: unknown } | undefined)?.read_through)
    .filter((d): d is string => typeof d === "string");
  return [CLOCK_FLOOR, ...reads].sort().at(-1)!;
}
const plusDays = (day: string, n: number) =>
  new Date(Date.parse(`${day}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
const LEAD = "73131864"; // 1:26-cv-01114, listed on eo-14399-usps-rule-enjoined-ddc
const NOTICE_ITEM = "115671"; // the clerk's consolidation notice of Apr 14 on the lead
const MEMBERS = ["73134260", "73143746"]; // 01132 and 01151, consolidated into the lead
const seed = (s: Seed[], id: string) => {
  const found = s.find((x) => String(x.case_id) === id);
  if (!found) throw new Error(`no seed ${id}`);
  return found;
};
const gate = (g: Gate[], id: string) => {
  const found = g.find((x) => x.id === id);
  if (!found) throw new Error(`no gate ${id}`);
  return found;
};
const newSeed = (extra: Record<string, unknown>): Seed => ({
  caption: "Planted v. Test", docket_number: "1:26-cv-99999", court: "D.D.C.", court_id: "dcd",
  category: "executive-order", order: "EO 14399", case_id: "99999999", notes: "planted", ...extra,
});

describe("check 5, coverage, on the real files", () => {
  it("passes, with both consolidated members found on the lead's timeline", () => {
    const { code, out } = run();
    expect(code, out).toBe(0);
    // The notice itself, not the lead's other item of that day (a standing order).
    for (const m of MEMBERS)
      expect(out).toMatch(new RegExp(`PASS  ${m} \\S+ -- consolidated into ${LEAD} .*on the record as item ${NOTICE_ITEM},`));
  });
});

describe("check 5 fails every planted gap with exit 5", () => {
  it("without the two reasons, both members fail -- the D0's seed-commit case", () => {
    const { code, out } = run({ seeds: (s) => MEMBERS.forEach((m) => delete seed(s, m).gate_coverage) });
    expect(code, out).toBe(5);
    for (const m of MEMBERS) expect(out).toMatch(new RegExp(`FAIL  ${m} .*carries no recorded reason`));
  });

  it("a listed docket carrying a reason fails: remove the reason", () => {
    const { code, out } = run({
      seeds: (s) => { seed(s, LEAD).gate_coverage = seed(s, MEMBERS[0]).gate_coverage; },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73131864 .*listed on[\s\S]*remove the reason/);
  });

  it("a reason cannot chain through an unlisted lead", () => {
    const { code, out } = run({
      gates: (g) => {
        const d = gate(g, "eo-14399-usps-rule-enjoined-ddc");
        d.status = "falsified"; // a retracted claim lists nothing
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73131864 .*carries no recorded reason/);
    expect(out).toMatch(/FAIL  73134260 .*consolidated into 73131864, which is on no gate's list/);
  });

  it("a quote that is not on the lead's timeline on that date fails", () => {
    const { code, out } = run({
      seeds: (s) => {
        const gc = seed(s, MEMBERS[0]).gate_coverage as { record: { entry_at: string } };
        gc.record.entry_at = "2026-04-15";
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73134260 .*\n\s+73131864's timeline holds no item dated 2026-04-15/);
  });

  it("a quote the dated items do not carry fails, though the date has items", () => {
    const { code, out } = run({
      seeds: (s) => {
        (seed(s, MEMBERS[0]).gate_coverage as { record: { quote: string } }).record.quote =
          "a quote that appears on no entry at all";
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73134260 .*\n\s+none of 73131864's \d+ timeline item\(s\) dated 2026-04-14 carries the quote/);
  });

  it("a quote matches across case and runs of whitespace", () => {
    const { code, out } = run({
      seeds: (s) => {
        (seed(s, MEMBERS[0]).gate_coverage as { record: { quote: string } }).record.quote =
          "THE FOLLOWING   cases have been\nconsolidated with this case";
      },
    });
    expect(code, out).toBe(0);
    expect(out).toMatch(new RegExp(`PASS  73134260 .*item ${NOTICE_ITEM},`));
  });

  it("a member consolidated into a listed docket outside the class fails", () => {
    const { code, out } = run({
      seeds: (s) => {
        const gc = seed(s, MEMBERS[0]).gate_coverage as Record<string, unknown>;
        gc.into = "73544809"; // 26-5243: voter-data, listed on dhs-save-system-stayed
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73134260 .*consolidated into 73544809, which is not a class docket/);
  });

  it("a stale gate still lists its dockets, and a lead listed there still clears its members", () => {
    const { code, out } = run({
      gates: (g) => { gate(g, "eo-14399-usps-rule-enjoined-ddc").status = "stale"; },
    });
    expect(code, out).toBe(0);
    expect(out).toMatch(/PASS  73131864 .*listed on eo-14399-usps-rule-enjoined-ddc/);
    for (const m of MEMBERS) expect(out).toMatch(new RegExp(`PASS  ${m} .*consolidated into ${LEAD}`));
  });

  it("a record naming neither the member nor its lead fails", () => {
    const { code, out } = run({
      seeds: (s) => {
        (seed(s, MEMBERS[0]).gate_coverage as { record: { case_id: string } }).record.case_id = "74701505";
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  73134260 .*its record names 74701505, neither it nor its lead/);
  });

  it("a new class seed with no reason fails at its seed commit -- no grace", () => {
    const { code, out } = run({ seeds: (s) => { s.push(newSeed({})); } });
    expect(code, out).toBe(5);
    expect(out).toMatch(/FAIL  99999999 1:26-cv-99999 -- on no gate's record_instruments/);
  });

  it("a reason on a seed outside the class fails", () => {
    const { code, out } = run({
      seeds: (s) => {
        const other = s.find((x) => x.case_id && x.category !== "executive-order");
        if (!other) throw new Error("no non-class seed");
        other.gate_coverage = { unlisted: "no-claim-order", read_through: "2026-09-29", ruled: "test" };
      },
    });
    expect(code, out).toBe(5);
    expect(out).toMatch(/carries a coverage reason outside the class/);
  });

  it("no-claim-order past the record's clock plus a day fails; on it, passes", () => {
    const reason = (d: string) => ({ unlisted: "no-claim-order", read_through: d, ruled: "test, 2026-09-29" });
    const clock = defaultClock();
    const late = run({ clock, seeds: (s) => { s.push(newSeed({ gate_coverage: reason(plusDays(clock, 2)) })); } });
    expect(late.code, late.out).toBe(5);
    expect(late.out).toContain(`read_through is after the record's clock ${clock} plus a day`);
    const ok = run({ clock, seeds: (s) => { s.push(newSeed({ gate_coverage: reason(plusDays(clock, 1)) })); } });
    expect(ok.code, ok.out).toBe(0);
  });

  it("a consolidated record on a docket not yet held is pending, and passes", () => {
    const { code, out } = run({
      seeds: (s) => {
        s.push(newSeed({
          gate_coverage: {
            unlisted: "consolidated", into: LEAD, ruled: "test",
            record: { case_id: "99999999", entry_at: "2026-09-29", quote: "consolidated with the lead case" },
          },
        }));
      },
    });
    expect(code, out).toBe(0);
    expect(out).toMatch(/PASS  99999999 .*its record on 99999999 is PENDING, not yet held/);
  });
});

describe("the ruled verdict classes", () => {
  it("accepts duplicate and unread beside operative, noise and missed", () => {
    const { code, out } = run({
      gates: (g) => {
        (gate(g, "eo-14399-s2-3-stayed").record_read as Array<Record<string, unknown>>)[0].verdicts =
          { 1: "operative", 2: "noise", 3: "missed", 4: "duplicate", 5: "unread" };
      },
    });
    expect(code, out).toBe(0);
  });
});

describe("a no-claim-order reason may carry its flags' verdicts", () => {
  const withVerdicts = (v: Record<string, unknown>) => (s: Seed[]) => {
    s.push(newSeed({ gate_coverage: { unlisted: "no-claim-order", read_through: "2026-09-29",
      ruled: "test", verdicts: v } }));
  };
  it("accepts the ruled classes", () => {
    const { code, out } = run({ seeds: withVerdicts({ 950: "operative", 951: "duplicate" }) });
    expect(code, out).toBe(0);
  });
  it("refuses a verdict outside them, exit 3", () => {
    const { code, out } = run({ seeds: withVerdicts({ 950: "maybe" }) });
    expect(code, out).toBe(3);
    expect(out).toMatch(/gate_coverage.verdicts` 950: "maybe"/);
  });
});

describe("a malformed reason or reading is a malformed register: exit 3", () => {
  const cases: Array<[string, Parameters<typeof run>[0], RegExp]> = [
    ["a reason outside the vocabulary",
      { seeds: (s) => { (seed(s, MEMBERS[0]).gate_coverage as Record<string, unknown>).unlisted = "merged"; } },
      /gate_coverage.unlisted` must be consolidated or no-claim-order/],
    ["a reason with no ruling",
      { seeds: (s) => { delete (seed(s, MEMBERS[0]).gate_coverage as Record<string, unknown>).ruled; } },
      /needs ruled/],
    ["a reason with a key its kind does not take",
      { seeds: (s) => { (seed(s, MEMBERS[0]).gate_coverage as Record<string, unknown>).read_through = "2026-09-29"; } },
      /does not take read_through/],
    ["a listed docket with no reading",
      { gates: (g) => { delete gate(g, "eo-14399-s2-3-stayed").record_read; } },
      /eo-14399-s2-3-stayed.*lists 73568304, 73141063 and carries no `record_read`/],
    ["a reading of a docket the gate does not list",
      { gates: (g) => {
        (gate(g, "eo-14399-s2-3-stayed").record_read as Array<Record<string, unknown>>)[0].docket = "74701505";
      } },
      /docket 74701505 is not in `record_instruments`/],
    ["a verdict outside the vocabulary",
      { gates: (g) => {
        (gate(g, "eo-14399-s2-3-stayed").record_read as Array<Record<string, unknown>>)[0].verdicts = { 92338: "maybe" };
      } },
      /verdict 92338: "maybe"/],
    ["a watermark that is not an integer",
      { gates: (g) => {
        (gate(g, "eo-14399-s2-3-stayed").record_read as Array<Record<string, unknown>>)[0].through_entry_id = "92338";
      } },
      /`through_entry_id` must be a non-negative integer/],
  ];
  it.each(cases)("%s", (_, mutate, pattern) => {
    const { code, out } = run(mutate);
    expect(code, out).toBe(3);
    expect(out).toMatch(pattern);
  });
});
