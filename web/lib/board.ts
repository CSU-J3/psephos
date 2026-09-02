// Scales and series for the records chart: cumulative jurisdictions above a shared
// day-resolution axis, monthly legislative counts below it, executive orders as ticks
// on it.
//
// EVERYTHING HERE IS DERIVED FROM ROWS PASSED IN. No literals for counts, dates or
// maxima. The handoff quoted "14 distinct filing dates" and "92 in Mar 2025" and both
// turned out to be right, but they were checked against the query rather than copied:
// a count written into a spec is stale by build time, and this project has a list of
// the ones that were.

import type { CampaignSummary } from "@/lib/campaign";

const DAY_MS = 86_400_000;

export type Domain = { start: number; end: number };

/** A step on the cumulative line: one per DISTINCT filing date, not one per case. */
export type FilingStep = {
  date: string; // YYYY-MM-DD
  t: number; // ms
  added: number;
  total: number;
  states: string[];
};

export type MonthCount = { month: string; n: number };

/** An executive order on the axis. A MARKER, not a series: it gets no scale. */
export type EoTick = { date: string; t: number; title: string };

export type Frame = {
  key: string; // YYYY-MM
  /** Inclusive right edge of the frame, in ms. */
  endsAt: number;
  label: string;
  /** True for the final frame, which ends at now() rather than a month boundary. */
  toDate: boolean;
};

const dayOf = (v: string) => Date.parse(`${v.slice(0, 10)}T00:00:00Z`);

/**
 * The domain: earliest of the record's floors to now().
 *
 * COMPUTED PER REQUEST, NEVER A LITERAL. The check is that moving the system date moves
 * the right edge and the "to date" marker with no other edit. The floor is whichever
 * series starts first -- measured 2026-08-19 that is the state-bill first-seen series at
 * 2024-11, earlier than the first filing (2025-09-16), the first federal action
 * (2025-01) and the first executive document (2025-01). Hardcoding any one of those
 * would silently clip a series the day another one moved.
 */
export function boardDomain(
  input: {
    filings: readonly FilingStep[];
    stateBills: readonly MonthCount[];
    legislation: readonly MonthCount[];
    eos: readonly EoTick[];
  },
  now: Date,
): Domain {
  const floors: number[] = [
    ...input.filings.map((f) => f.t),
    ...input.stateBills.map((m) => dayOf(`${m.month}-01`)),
    ...input.legislation.map((m) => dayOf(`${m.month}-01`)),
    ...input.eos.map((e) => e.t),
  ];
  const end = now.getTime();
  return { start: floors.length ? Math.min(...floors) : end - 365 * DAY_MS, end };
}

/** Position on the axis. Clamped, so a stray future date cannot draw off-canvas. */
export function xOf(t: number, domain: Domain, width: number): number {
  if (domain.end <= domain.start) return 0;
  const f = (t - domain.start) / (domain.end - domain.start);
  return Math.max(0, Math.min(1, f)) * width;
}

/**
 * The cumulative line, stepping on REAL FILING DATES.
 *
 * One step per distinct date, not one per month and not one per case: five states filed
 * together on 2026-02-26 and that is one step of +5, while Oregon on 2025-09-16 is a
 * step of +1. Monthly steps would flatten both into the same shape and lose the fact
 * that the campaign arrives in batches.
 *
 * Input is one row per state carrying its own earliest filing -- the MIN(filed_at)
 * GROUP BY state that board_prework section 2a reads.
 */
export function cumulativeFilings(
  rows: readonly { state: string; filed_at: string | null }[],
): FilingStep[] {
  const byDay = new Map<string, string[]>();
  for (const r of rows) {
    if (!r.filed_at) continue; // a NULL drops a jurisdiction with no error; 2b guards it
    const d = r.filed_at.slice(0, 10);
    const list = byDay.get(d);
    if (list) list.push(r.state);
    else byDay.set(d, [r.state]);
  }
  let total = 0;
  return [...byDay.keys()]
    .sort()
    .map((date) => {
      const states = byDay.get(date)!.sort();
      total += states.length;
      return { date, t: dayOf(date), added: states.length, total, states };
    });
}

/** Bucket ISO dates into YYYY-MM counts, ascending, months with nothing omitted. */
export function bucketByMonth(dates: readonly (string | null)[]): MonthCount[] {
  const m = new Map<string, number>();
  for (const d of dates) {
    if (!d) continue;
    const k = d.slice(0, 7);
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, n]) => ({ month, n }));
}

/** The below-axis scale: the window's own maximum across both monthly series. */
export function monthlyMax(...series: readonly MonthCount[][]): number {
  let max = 0;
  for (const s of series) for (const m of s) if (m.n > max) max = m.n;
  return max || 1;
}

/**
 * Scrubber stops: one per month, positioned at that month's LAST DAY, with the final
 * stop at now() and labelled "(to date)".
 *
 * The last stop is not a month boundary, and that is deliberate: a replay whose final
 * frame ends at the end of last month cannot show anything that happened this month,
 * which on a live monitor is the most interesting frame there is.
 */
export function frames(domain: Domain, now: Date): Frame[] {
  const out: Frame[] = [];
  const start = new Date(domain.start);
  let y = start.getUTCFullYear();
  let mo = start.getUTCMonth();
  const nowKey = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;

  for (;;) {
    const key = `${y}-${String(mo + 1).padStart(2, "0")}`;
    if (key >= nowKey) break;
    // Last instant of the month: day 0 of the next month.
    const endsAt = Date.UTC(y, mo + 1, 0, 23, 59, 59, 999);
    out.push({ key, endsAt, label: monthLabel(y, mo), toDate: false });
    mo += 1;
    if (mo > 11) { mo = 0; y += 1; }
  }
  out.push({ key: nowKey, endsAt: domain.end, label: "to date", toDate: true });
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function monthLabel(y: number, mo: number): string {
  return `${MONTHS[mo]} ${y}`;
}

/**
 * Quarterly ticks along the axis. NO END LABELS: the last tick and an end label collide,
 * so the final tick carries the year on its own.
 */
export function quarterTicks(domain: Domain): { t: number; label: string }[] {
  const out: { t: number; label: string }[] = [];
  const d = new Date(domain.start);
  let y = d.getUTCFullYear();
  let q = Math.floor(d.getUTCMonth() / 3);
  for (;;) {
    const t = Date.UTC(y, q * 3, 1);
    if (t > domain.end) break;
    if (t >= domain.start) out.push({ t, label: q === 0 ? String(y) : `Q${q + 1}` });
    q += 1;
    if (q > 3) { q = 0; y += 1; }
  }
  // The last tick takes the year, whatever quarter it is.
  if (out.length) {
    const last = out[out.length - 1];
    last.label = String(new Date(last.t).getUTCFullYear());
  }
  return out;
}

/**
 * What is visible at a frame. NOTHING MAY BE DRAWN PAST THE SCRUBBER -- a replay that
 * shows its endpoint is not a replay. The clip rect enforces this visually; this
 * enforces it in the data so the two cannot disagree.
 */
export function visibleAt<T extends { t: number }>(marks: readonly T[], frame: Frame): T[] {
  return marks.filter((m) => m.t <= frame.endsAt);
}

/** Clip width for a frame, in chart units. */
export function clipWidth(frame: Frame, domain: Domain, width: number): number {
  return xOf(frame.endsAt, domain, width);
}

/**
 * Is this executive document an EO with a number?
 *
 * The collector writes titles as "EO 14248: Preserving and Protecting ...", so the
 * number is in the title rather than a column. Only NUMBERED orders take a tick: the
 * channel also carries agency rules and notices, which are not executive orders and
 * would triple the tick count while saying something else.
 */
export function isEoNumbered(title: string): boolean {
  return /^EO\s+\d+/.test(title.trim());
}

// --- the board's paint vocabulary -------------------------------------------------
//
// HERE RATHER THAN IN THE COMPONENT, so the key and the mark it names read the SAME
// value. A key is a claim about what the page paints; a key holding its own copy of a
// colour is a claim that can quietly stop being true, which is the failure this unit
// is about. Everything else stays a CSS variable referenced by name for the same
// reason -- one definition, quoted, never transcribed.

export type Posture = "live" | "ended" | "none";

export const POSTURE_FILL: Record<Posture, string> = {
  live: "var(--c-litigation)",
  ended: "color-mix(in oklch, var(--c-litigation) 42%, #171717)",
  none: "#1f1f1f",
};

/** What each posture is called, in the key and in the detail panel. One wording. */
export const POSTURE_LABEL: Record<Posture, string> = {
  live: "suit live",
  ended: "suit ended",
  none: "never sued",
};

// --- the line's overlay vocabulary --------------------------------------------------
//
// THE FIGURES THE LINE COUNTS AND THE MAP DOES NOT PAINT, here for the same reason
// POSTURE_LABEL is here: the key and the line must read ONE value. The key makes a
// negative claim -- "these numbers have no mark" -- and a negative claim transcribed
// into a second place is a claim that can quietly stop matching the numbers it is
// about.
//
// KEYED OFF CampaignSummary RATHER THAN OFF THREE STRING LITERALS. Extract narrows to
// nothing if a field is renamed there, which makes the matching key in OVERLAY_LABEL an
// excess property and a compile error. A plain union would go on naming a field that no
// longer exists.

export type Overlay = Extract<
  keyof CampaignSummary,
  "chains" | "dormant" | "unlinkedEndings"
>;

/** What each unpainted figure is called, in the line and in the key. One wording. */
export const OVERLAY_LABEL: Record<Overlay, string> = {
  chains: "continued elsewhere",
  dormant: "quiet",
  // NOT "ended, no link asserted", which is what this said and which read as a subset
  // of the posture beside it. Measured on the live page: `ended` is 2 and this is 6, so
  // a phrase that looks like a subset carried THREE TIMES the count of the set it
  // appeared to sit inside -- arithmetic a reader cannot reconcile and should not have
  // to. The /campaign strip never had the problem because it keeps the clause that
  // does the work: "ended here, with no link asserted TO THE LIVE DOCKET".
  //
  // "carrying" is doing something specific: it makes this an ATTRIBUTE of a
  // jurisdiction rather than a status competing with the postures, which is what it
  // actually is. It also says nothing about whether that jurisdiction is itself live or
  // ended -- and that is deliberate, because the two sets are disjoint TODAY but not by
  // construction. `unlinked` is every unsuperseded row that is not the cell's own
  // docket, and `status` keys off that docket alone, so a jurisdiction whose every
  // unsuperseded docket is terminated lands in both. Measured overlap right now: none.
  // A wording like "ended, state still live" would be wrong the day that changes.
  unlinkedEndings: "carrying an unlinked ending",
};
