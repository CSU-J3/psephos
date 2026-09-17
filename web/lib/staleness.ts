/**
 * Is the record still moving? — the one place in this layer allowed to read the clock.
 *
 * THE INVARIANT'S EXEMPTION CLAUSE FINALLY HAS A MECHANISM. Every figure a reader sees
 * is anchored to the record's own clock, never to the machine rendering it, and
 * `clock.test.ts` enforces that by banning a bare wall-clock read outright. This file is
 * the single exemption, and the test names it: one function, in one file, asserted to be
 * the ONLY one, so a second exemption anywhere fails the suite rather than joining it.
 *
 * WHY AN EXEMPTION IS NECESSARY HERE AND NOWHERE ELSE. The rule exists because a figure
 * computed against the viewer's clock drifts away from the record and says something
 * false about the data. "Has a scheduled run gone missing" is not a figure about the
 * data at all — it is a question about the SCHEDULE, whose answer changes with real time
 * whether or not anything was collected, and there is no value in the record that can
 * stand in for now. The anchor certainly cannot: `MAX(fetched_at)` is the record's own
 * maximum stamp, and a run that collected nothing leaves it exactly where a run that
 * never happened would (measured 2026-09-17 — three of 51 scheduled runs since
 * `58c6aca` committed nothing at all).
 *
 * THE FENCE, which is what makes the exemption narrow rather than a hole: the clock is
 * read ONCE, by `clockNowMs`, and the value is compared only against `runs.finished_at`
 * and the slot times derived from it. It never touches `items`, `occurred_at`,
 * `fetched_at`, or anything a reader sees as a date. Every other function here is pure
 * and takes the number as an argument, so the arithmetic is testable without mocking a
 * clock — and the test asserts that this file holds exactly one clock read and that it
 * sits inside that function.
 */

/**
 * `heartbeat_far` — slot to the moment a run that fired has FINISHED.
 *
 * DERIVED IN `docs/bands.yaml`'s terms, `fire.far + wall_clock.far`, and carried here as
 * a literal because no route reads YAML. `tests/test_bands_agreement.py` joins this
 * number to that file and fails when the edges move, which is the same shape
 * `test_court_alias_agreement` and `test_presidential_types_agreement` use for the other
 * constants this layer duplicates.
 *
 * NOT `landing_far`, AND THE DIFFERENCE IS NOT A ROUNDING. `landing_far` (6h02m14s)
 * measures when a DATA COMMIT lands, mid-run. A heartbeat row is written at run END.
 * Run 34755670262 set both of landing_far's inputs, so its slot-to-commit equals that
 * edge to the second — and its slot-to-run-end is 6h02m20s, six seconds past it. A
 * check built on landing_far would have called that healthy run missed.
 */
export const HEARTBEAT_FAR_MS = (6 * 3600 + 10 * 60 + 19) * 1000; // 6h10m19s

/** The cron's slots, `17 0,6,12,18 * * *`. Joined to tools/window_table.py by the same test. */
export const SLOT_HOURS = [0, 6, 12, 18] as const;
export const SLOT_MINUTE = 17;

export type Heartbeat = {
  slot: string;
  finishedAt: string;
  itemsWritten: number;
  conclusion: string;
};

/**
 * THE ONE EXEMPT SITE. Reads the machine's clock, once, and returns milliseconds.
 *
 * Everything downstream takes this as an argument, so nothing else in the layer needs
 * the clock and the exemption cannot spread by accident. Compared only against
 * `runs.finished_at` and the slot times derived from it — never against record data.
 */
export function clockNowMs(): number {
  return Date.now();
}

/**
 * Every slot between `afterMs` (exclusive) and `nowMs`, oldest first.
 *
 * Pure, and the reason the clock read is one line above rather than in here: the slot
 * walk is the part worth testing at a fixed instant.
 */
export function slotsBetween(afterMs: number, nowMs: number): Date[] {
  const out: Date[] = [];
  if (!Number.isFinite(afterMs) || !Number.isFinite(nowMs) || nowMs <= afterMs) return out;
  // Start at midnight UTC of the day `afterMs` falls in, so no slot is skipped when the
  // window opens mid-day, and walk forward. A day is four slots; the loop is bounded by
  // the window, which the caller has already bounded by the last heartbeat.
  const d = new Date(afterMs);
  const cursor = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  for (let day = 0; ; day += 1) {
    const base = cursor + day * 86_400_000;
    if (base > nowMs) break;
    for (const h of SLOT_HOURS) {
      const t = base + h * 3_600_000 + SLOT_MINUTE * 60_000;
      if (t > afterMs && t <= nowMs) out.push(new Date(t));
    }
    if (day > 400) break; // a frozen record should render, not spin
  }
  return out;
}

/**
 * The slots that should have produced a heartbeat by now and did not.
 *
 * A slot counts only once `heartbeat_far` has passed, which is the whole of the
 * censoring story: the edge is a LOWER bound on the true one, so the error runs toward
 * *declared missed while a very late run could still land*, never the other way. There
 * is no overlap to worry about — a slot that fired produces a row and a slot that was
 * missed produces none, and empty is disjoint from everything.
 */
export function missingSlots(
  heartbeats: Heartbeat[],
  nowMs: number,
  lastFinishedMs: number | null,
): Date[] {
  if (lastFinishedMs === null) return [];
  const seen = new Set(
    heartbeats
      .map((h) => Date.parse(h.finishedAt))
      .filter((t) => Number.isFinite(t)),
  );
  return slotsBetween(lastFinishedMs, nowMs - HEARTBEAT_FAR_MS).filter((slot) => {
    // A slot is covered if some heartbeat finished inside its own window: at or after
    // the slot, and no later than heartbeat_far past it.
    const from = slot.getTime();
    const to = from + HEARTBEAT_FAR_MS;
    for (const t of seen) if (t >= from && t <= to) return false;
    return true;
  });
}

/** `2026-09-17T08:42:03+00:00` -> `08:42Z`. Slices, never parses: the string is the value. */
export function stampLabel(iso: string | null | undefined): string | null {
  if (!iso || iso.length < 16) return null;
  const m = /^\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]}Z` : null;
}

/** `2026-09-17T18:17:00.000Z` -> `09-17 18:17Z`, in the record's zone, by slice. */
export function slotLabel(slot: Date): string {
  const iso = slot.toISOString();
  return `${iso.slice(5, 10)} ${iso.slice(11, 16)}Z`;
}
