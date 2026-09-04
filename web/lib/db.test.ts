import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

// THE SOURCE IS READ AS TEXT, NEVER IMPORTED. `lib/db.ts` calls createClient() at
// module load against TURSO_DATABASE_URL, so importing it from a test would either
// need credentials or blow up on undefined -- and neither has anything to do with the
// property under test. What is asserted here is the SHAPE OF A QUERY, which is a fact
// about the file, so the file is what gets read.
const SOURCE = readFileSync(new URL("./db.ts", import.meta.url), "utf8");

// The select list of getChannelActivity, from its first column to its FROM.
function selectList(): string {
  const start = SOURCE.indexOf("SELECT channel,");
  expect(start).toBeGreaterThan(-1);
  const end = SOURCE.indexOf("FROM items", start);
  expect(end).toBeGreaterThan(start);
  return SOURCE.slice(start, end);
}

describe("getChannelActivity's collection-time aggregate", () => {
  // WHAT THIS PINS, and why it is asserted on the query rather than on a function.
  //
  // `readCollectedAt` is pure over rows: hand it old rows and it returns the oldest
  // max, hand it fresh ones and it returns the freshest. It cannot tell you whether
  // the rows it was handed were windowed before they arrived -- so a "stalled data"
  // fixture against the pure function would pass no matter what the SQL did, and
  // would prove only that a max is a max. The stall property lives HERE, in whether
  // the aggregate carries a CASE guard, and this is the only place it can be checked
  // without a database.
  it("computes last_fetch with no window guard", () => {
    const select = selectList();
    const line = select
      .split("\n")
      .find((l) => l.includes("AS last_fetch"));
    expect(line, "getChannelActivity no longer selects last_fetch").toBeDefined();
    expect(line!).toContain("MAX(fetched_at)");
    // The guard that must not appear. A windowed MAX -- MAX(CASE WHEN fetched_at >= ?
    // THEN fetched_at END) -- returns NULL once collection stops for longer than the
    // window, which the header would render as "no collection recorded" on a record
    // whose true answer is a timestamp just outside it. The label exists to expose a
    // stalled cron; the figure behind it must outlive the stall.
    expect(line!).not.toMatch(/CASE|WHEN|>=|\?/);
  });

  it("still windows the three counts beside it, so the asymmetry is the assertion", () => {
    // The control. Without this, the test above would also pass on a query that had
    // dropped every window -- it would be reporting "last_fetch is unguarded" about a
    // file where nothing is guarded, which is true and worthless. These three are
    // windowed BECAUSE they answer "how much arrived recently"; last_fetch is not
    // BECAUSE it answers "when did the record last move". Both halves or neither.
    const select = selectList();
    const guarded = select
      .split("\n")
      .filter((l) => /CASE WHEN fetched_at >= \?/.test(l));
    expect(guarded.map((l) => l.trim().split(" AS ")[1])).toEqual(["day,", "week,"]);
    // day_history's guard is interpolated from HISTORY_SUM, so it is checked there.
    expect(select).toContain("${HISTORY_SUM} AS day_history");
    expect(SOURCE).toMatch(/const HISTORY_SUM = `SUM\(CASE WHEN fetched_at >= \?/);
  });

  it("takes no new bind parameter, so the aggregate rides the existing scan", () => {
    // MAX takes no argument, which is what makes this free: same GROUP BY, same index
    // scan, same args in the same order. A `?` appearing on the last_fetch line would
    // misalign the args array -- and the failure would surface on `day` reading a
    // window it was never given, not here, so it is worth catching at the shape.
    //
    // TWO literal `?` in the select list, not four: `day` and `week` carry theirs
    // inline while day_history's pair lives inside the interpolated HISTORY_SUM. The
    // four args are 2 + 2, and the split is invisible in this string -- which is
    // exactly why the count is pinned against the args line rather than eyeballed.
    const select = selectList();
    expect((select.match(/\?/g) ?? []).length).toBe(2);
    expect((SOURCE.match(/const HISTORY_SUM = `[^`]*`/)![0].match(/\?/g) ?? []).length).toBe(2);
    expect(SOURCE).toContain("args: [day, week, day, HISTORY_AFTER_DAYS],");
  });
});
