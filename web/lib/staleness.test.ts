import { describe, expect, it } from "vitest";
import {
  HEARTBEAT_FAR_MS,
  SLOT_HOURS,
  SLOT_MINUTE,
  missingSlots,
  slotLabel,
  slotsBetween,
  durationLabel,
  stampLabel,
  type Heartbeat,
} from "@/lib/staleness";

// EVERY TEST HERE PASSES `now` AS A NUMBER, which is the point of splitting the clock
// read into its own function: the arithmetic is exercised at fixed instants and nothing
// has to mock a clock. The one function that reads the clock has no arithmetic in it and
// so has nothing to test beyond the fence clock.test.ts puts around it.

const T = (iso: string) => Date.parse(iso);
const hb = (finishedAt: string, itemsWritten = 5): Heartbeat => ({
  slot: "17 0 * * *",
  finishedAt,
  itemsWritten,
  conclusion: "success",
});

describe("slotsBetween", () => {
  it("walks the four daily slots, oldest first", () => {
    const got = slotsBetween(T("2026-09-17T00:00:00Z"), T("2026-09-17T23:59:00Z"));
    expect(got.map((d) => d.toISOString())).toEqual([
      "2026-09-17T00:17:00.000Z",
      "2026-09-17T06:17:00.000Z",
      "2026-09-17T12:17:00.000Z",
      "2026-09-17T18:17:00.000Z",
    ]);
  });

  it("crosses midnight without dropping the day it opened in", () => {
    // The loop starts at midnight of the OPENING day rather than at `afterMs`, so a
    // window opening at 19:00 still sees nothing before it and everything after.
    const got = slotsBetween(T("2026-09-16T19:00:00Z"), T("2026-09-17T07:00:00Z"));
    expect(got.map((d) => d.toISOString())).toEqual([
      "2026-09-17T00:17:00.000Z",
      "2026-09-17T06:17:00.000Z",
    ]);
  });

  it("is exclusive at the open and inclusive at the close", () => {
    const exact = T("2026-09-17T06:17:00Z");
    expect(slotsBetween(exact, exact + 1)).toHaveLength(0);
    expect(slotsBetween(exact - 1, exact)).toHaveLength(1);
  });

  it("returns nothing for an inverted or unreadable window", () => {
    expect(slotsBetween(T("2026-09-17T12:00:00Z"), T("2026-09-17T06:00:00Z"))).toEqual([]);
    expect(slotsBetween(NaN, T("2026-09-17T06:00:00Z"))).toEqual([]);
  });
});

describe("missingSlots", () => {
  // The record's real cadence: a slot fires, a run finishes some hours later, and the
  // heartbeat lands inside [slot, slot + heartbeat_far].
  const slot = T("2026-09-17T06:17:00Z");
  const landed = new Date(slot + 5 * 3600_000).toISOString(); // 5h after, well inside

  it("says nothing while every passed slot has a heartbeat", () => {
    const now = slot + HEARTBEAT_FAR_MS + 60_000;
    expect(missingSlots([hb(landed)], now, T("2026-09-17T00:20:00Z"))).toEqual([]);
  });

  it("names a slot only once heartbeat_far has passed", () => {
    // A LOWER bound, so the error runs toward "declared missed while a late run could
    // still land" -- never toward missing a real one. One second early says nothing.
    const early = slot + HEARTBEAT_FAR_MS - 1000;
    expect(missingSlots([], early, T("2026-09-17T00:20:00Z"))).toEqual([]);
    const late = slot + HEARTBEAT_FAR_MS + 1000;
    expect(missingSlots([], late, T("2026-09-17T00:20:00Z")).map(slotLabel)).toEqual([
      "09-17 06:17Z",
    ]);
  });

  it("a run that collected nothing still covers its slot", () => {
    // THE QUIET DAY, which is the half of this the anchor could never express: a
    // heartbeat with items_written 0 is a run that HAPPENED, not a missing one.
    const now = slot + HEARTBEAT_FAR_MS + 60_000;
    expect(missingSlots([hb(landed, 0)], now, T("2026-09-17T00:20:00Z"))).toEqual([]);
  });

  it("says nothing when there is no heartbeat at all", () => {
    // A fresh database, or the table before its first run. Rendering "every slot since
    // 1970 is missing" would be the element's own first red.
    expect(missingSlots([], T("2026-09-17T23:00:00Z"), null)).toEqual([]);
  });

  it("names several slots in order when a run of them is skipped", () => {
    const from = T("2026-09-16T18:20:00Z");
    const now = T("2026-09-17T23:00:00Z");
    expect(missingSlots([], now, from).map(slotLabel)).toEqual([
      "09-17 00:17Z",
      "09-17 06:17Z",
      "09-17 12:17Z",
    ]);
  });
});

describe("the constants", () => {
  it("heartbeat_far is 6h10m19s", () => {
    expect(HEARTBEAT_FAR_MS).toBe(22_219_000);
  });

  it("the slots are the cron's", () => {
    expect([...SLOT_HOURS]).toEqual([0, 6, 12, 18]);
    expect(SLOT_MINUTE).toBe(17);
  });
});

describe("labels", () => {
  it("stampLabel slices rather than parses, so no zone can enter", () => {
    expect(stampLabel("2026-09-17T08:42:03.518569+00:00")).toBe("08:42Z");
    expect(stampLabel("2026-01-01T00:00:00Z")).toBe("00:00Z");
    expect(stampLabel(null)).toBeNull();
    expect(stampLabel("not a date")).toBeNull();
  });

  it("durationLabel rounds to the minute, not the hour", () => {
    // 6h10m19s must not render as "6h": a page figure that disagrees with the
    // constant behind it gives a reader two numbers and no way to choose.
    expect(durationLabel(HEARTBEAT_FAR_MS)).toBe("6h10m");
    expect(durationLabel(6 * 3600_000)).toBe("6h");
    expect(durationLabel(3600_000 + 5 * 60_000)).toBe("1h05m");
  });

  it("slotLabel renders month-day and time in Z", () => {
    expect(slotLabel(new Date("2026-09-17T18:17:00Z"))).toBe("09-17 18:17Z");
  });
});
