"use client";

import { useMemo } from "react";
import {
  clipWidth,
  monthlyMax,
  quarterTicks,
  visibleAt,
  xOf,
  type Domain,
  type EoTick,
  type FilingStep,
  type Frame,
  type MonthCount,
} from "@/lib/board";

// One chart, built in TWO LAYERS over ONE coordinate system.
//
//   above   cumulative jurisdictions sued, stepping on real filing dates, scaled 0-51
//   axis    quarterly ticks; amber marks for election EOs
//   below   monthly counts hanging down, scaled to the window's own maximum:
//           violet bars for state bills first seen, a pale violet line for federal
//           legislative actions
//
// THE LETTERING IS NOT IN THE COORDINATE SYSTEM. The SVG carries geometry only; every
// glyph is HTML in `.board-labels`, positioned as a PERCENTAGE of the same viewBox by
// the same `x()` and `yOfTotal()` the geometry uses, and sized in CSS pixels.
//
// WHY, measured rather than preferred. An SVG `font-size` is in user units, so a 13u
// label renders at 13 * (rendered width / 900): on this page that was 8.44px where the
// chart shares the board row at 584px, and 12.37px where it is stacked at 857px. Two
// sizes, neither of them the specified one, both a function of layout rather than of
// typography -- and the fix is not a bigger number, because matching a legible 19px at
// the narrow width means 29-unit glyphs, ~11% of chart height, colliding with the plot.
// Lettering in CSS pixels is width-independent BY CONSTRUCTION: the chart can render at
// 520px or 1600px and the type never changes size, only density.
//
// The density rule is the one thing that does vary, and it is a container query rather
// than a viewport query for the same reason the board's own reflow is (globals.css):
// in the 1900+ arrangement the board column is ~880px on a 2560px viewport, so a
// viewport query would thin the labels of a chart that has plenty of room.
//
// A CLIP RECT WRAPS EVERY DATA LAYER AND NOTHING ELSE. Axis, ticks and the 51-line stay
// outside it, because they are the frame rather than the data -- a replay whose axis
// grows is a zoom, not a replay. And nothing may be drawn past the scrubber: a replay
// that shows its endpoint is not a replay. The label layer obeys the same rule in its
// own terms -- milestone markers and their captions are gated on the frame.
//
// Colour is one hue one meaning, from the shared CSS variables: red is DOJ in court,
// violet is legislation at both levels, amber is executive. Deliberately not the
// electoral convention -- the jurisdictions DOJ sued are largely the politically blue
// ones, so red-state/blue-marker reads backwards here.

const W = 900;
const H_TOP = 130;
const H_BOT = 96;
const AXIS_Y = H_TOP;
const H = H_TOP + H_BOT + 34;
const PAD_L = 34;
const PAD_R = 16;
const PLOT = W - PAD_L - PAD_R;

/** All 51 jurisdictions -- the ceiling the cumulative line is scaled against. */
const JURISDICTIONS = 51;

/**
 * Height of the cumulative line at a running total. Shared by the path and by the
 * labels that annotate it, so a marker cannot drift off the line it is marking.
 */
const yOfTotal = (total: number) => AXIS_Y - (total / JURISDICTIONS) * (H_TOP - 12);

/** viewBox units -> percentage of the plot box, which is what the HTML layer speaks. */
const pctX = (u: number) => `${((u / W) * 100).toFixed(3)}%`;
const pctY = (u: number) => `${((u / H) * 100).toFixed(3)}%`;

const day = (v: string) => Date.parse(`${v}T00:00:00Z`);

export type Milestone = {
  date: string;
  t: number;
  label: string;
  /** "line" pins the marker to the cumulative line at its date; "axis" to the axis. */
  anchor: "line" | "axis";
};

/**
 * THE FOUR CAMPAIGN MILESTONES. EDITORIAL, AND THE CONSTANT SAYS SO.
 *
 * These are curation, not derivation, and they are a constant precisely because the
 * record does not structure them. Two of the four ARE checkable against the rows this
 * chart draws and were checked rather than trusted; the other two are sourced to a
 * specific item and no further. Each comment says which, because "sourced" and
 * "derivable" are different claims, and a list that blurs them invites the next reader
 * to believe the whole set was computed.
 *
 * Auto-derivation is deliberately out of scope: no column means "first rejection", and
 * inventing one from headline text would be a classifier, not a lookup.
 */
export const MILESTONES: Milestone[] = [
  {
    // A1, from the legislation channel: `hr22-119: Received in the Senate.` dated
    // 2025-04-10, the same day as `On passage Passed by the Yeas and Nays: 220 - 208
    // (Roll no. 102)`. Anchored to the AXIS rather than to the line: this is a
    // legislative event and the line counts lawsuits, so pinning it to a suit total
    // would assert a relationship the record does not make.
    date: "2025-04-10",
    t: day("2025-04-10"),
    label: "Apr 10, 2025 — SAVE Act to the Senate",
    anchor: "axis",
  },
  {
    // DERIVED-AND-CHECKED. The earliest `filed_at` across the campaign rows is Oregon
    // 2025-09-16, which is this chart's own first step. Written out rather than
    // computed so the caption can name Oregon; re-checked against the snapshot when
    // this shipped. If the first filing ever moves earlier, the line visibly steps
    // before this marker, which is a symptom a reader can see.
    date: "2025-09-16",
    t: day("2025-09-16"),
    label: "Sep 16, 2025 — first suit, Oregon",
    anchor: "line",
  },
  {
    // A1, FROM THE DOCKET, not from a headline. `case_id` 71452580 -- United States v.
    // Shirley Weber, C.D. Cal. 2:25-cv-09149, now terminated and superseded by the
    // Ninth Circuit appeal 72356732 (26-1232) -- carries the entry:
    //
    //   2026-01-15  ORDER by Judge David O. Carter: Granting 37 Defendant's MOTION to
    //               Dismiss and Intervenors' Motions to Dismiss [62-1], 67...
    //
    // Two same-day news items corroborate it (AP News; League of Women Voters) and are
    // CORROBORATION RATHER THAN SOURCE -- the docket is the record and the headlines
    // agree with it to the day.
    //
    // THIS ENTRY REPLACES A FALSE ONE, and the replacement is the point. It read
    // "Apr 28, 2026 -- first record demand rejected", carried from the v37 sketch into
    // chart mock v1. A sweep of the news channel before that date returned 22 candidate
    // reports under two readings: jurisdictions refusing the demand from 2025-08-12
    // (Vermont) and 2025-09-23 (Washington), and courts rejecting it from this order
    // onward. The channel's own "0 for 4" and "0 for 5" scorekeeping puts Arizona sixth
    // rather than first. A "first" is assertable only where some table can be ordered
    // on it; `cases` orders this one and nothing orders the other.
    //
    // AXIS-ANCHORED for the same reason the SAVE Act entry is: the line counts suits
    // FILED, and a dismissal is not a filing. On the line it would read as a suit filed
    // that day.
    date: "2026-01-15",
    t: day("2026-01-15"),
    label: "Jan 15, 2026 — first court rejection on the record (California)",
    anchor: "axis",
  },
  {
    // DERIVED-AND-CHECKED, the mirror of the second: the latest first-filing across the
    // campaign rows is Maine 2026-06-15, this chart's last step. "Last new suit" is true
    // as of the snapshot and is exactly the kind of claim that goes stale the day DOJ
    // files again -- at which point the line steps past this marker, visibly.
    date: "2026-06-15",
    t: day("2026-06-15"),
    label: "Jun 15, 2026 — last new suit",
    anchor: "line",
  },
];

export function RecordsBoard({
  domain,
  filings,
  stateBills,
  legislation,
  eos,
  frame,
}: {
  domain: Domain;
  filings: FilingStep[];
  stateBills: MonthCount[];
  legislation: MonthCount[];
  eos: EoTick[];
  frame: Frame;
}) {
  const x = (t: number) => PAD_L + xOf(t, domain, PLOT);
  const clipW = clipWidth(frame, domain, PLOT);

  const max = useMemo(() => monthlyMax(stateBills, legislation), [stateBills, legislation]);

  // Month bars are positioned by their month START and sized to the month's span, so a
  // 28-day February is narrower than a 31-day March rather than every bar being equal
  // on a day-resolution axis.
  const monthGeom = (month: string) => {
    const [y, m] = month.split("-").map(Number);
    const t0 = Date.UTC(y, m - 1, 1);
    const t1 = Date.UTC(y, m, 1);
    return { x0: x(t0), x1: x(t1) };
  };

  const stepPath = useMemo(() => {
    if (!filings.length) return "";
    let d = `M ${x(domain.start)} ${AXIS_Y}`;
    let prev = 0;
    for (const s of filings) {
      d += ` L ${x(s.t)} ${yOfTotal(prev)} L ${x(s.t)} ${yOfTotal(s.total)}`;
      prev = s.total;
    }
    d += ` L ${x(domain.end)} ${yOfTotal(prev)}`;
    return d;
  }, [filings, domain]);

  const legPath = useMemo(() => {
    if (!legislation.length) return "";
    return legislation
      .map((m, i) => {
        const g = monthGeom(m.month);
        const cx = (g.x0 + g.x1) / 2;
        const yy = AXIS_Y + (m.n / max) * H_BOT;
        return `${i === 0 ? "M" : "L"} ${cx} ${yy}`;
      })
      .join(" ");
  }, [legislation, max, domain]);

  const ticks = useMemo(() => quarterTicks(domain), [domain]);
  const visibleFilings = visibleAt(filings, frame);
  const lastVisible = visibleFilings.at(-1);

  /** The running total on the date a milestone marks, so a marker sits ON the line. */
  const totalAt = (t: number) => {
    let total = 0;
    for (const s of filings) {
      if (s.t > t) break;
      total = s.total;
    }
    return total;
  };

  const reached = visibleAt(MILESTONES, frame);
  const reachedCount = reached.length;

  // The chip rides the frame's leading edge, hanging to its LEFT so it never covers
  // ground the replay has not revealed. In the first frames there is no left to hang
  // into, so it flips to the right of the edge rather than sliding off the plot --
  // 90 units is about one chip's width at the narrowest arrangement this board renders.
  const chipLeads = clipW < 90;

  // AND IT SITS OFF THE LINE, NOT ON IT. A chip centred on the line's end occluded the
  // last milestone marker at 1400px and not at 2560px, which is the one hazard this
  // design's own thesis creates: the chip is a FIXED CSS-PIXEL object over a plot that
  // scales, so it covers ~12% of a 584px chart against ~8% of an 857px one, and the
  // marker it hides is the one nearest the line's end -- exactly where the last
  // milestone tends to fall. Clearing it vertically costs nothing and does not move
  // with width. Near the ceiling there is no room above, so it goes below instead.
  const chipBelow = yOfTotal(lastVisible?.total ?? 0) < 44;

  return (
    <>
      <div className="board-plot">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={`Cumulative jurisdictions sued and monthly legislative activity, through ${frame.label}`}
        >
          <defs>
            {/* Width follows the frame. Every data layer is inside it; the axis is not. */}
            <clipPath id="board-frame">
              <rect x={PAD_L} y={0} width={Math.max(0, clipW)} height={H} />
            </clipPath>
          </defs>

          {/* --- frame: outside the clip ------------------------------------------- */}
          <line x1={PAD_L} y1={AXIS_Y} x2={W - PAD_R} y2={AXIS_Y} stroke="#404040" strokeWidth={1} />
          <line
            x1={PAD_L}
            y1={yOfTotal(JURISDICTIONS)}
            x2={W - PAD_R}
            y2={yOfTotal(JURISDICTIONS)}
            stroke="#262626"
            strokeWidth={1}
            strokeDasharray="3 3"
          />

          {/* --- above the axis: cumulative jurisdictions --------------------------- */}
          <g clipPath="url(#board-frame)">
            <path d={stepPath} fill="none" stroke="var(--c-litigation)" strokeWidth={1.75} />

            {/* One dot per distinct filing date, dim by default, lit in its own frame. */}
            {filings.map((s) => {
              const lit = s.t <= frame.endsAt && s.t > frame.endsAt - 31 * 86_400_000;
              return (
                <circle
                  key={s.date}
                  cx={x(s.t)}
                  cy={yOfTotal(s.total)}
                  r={lit ? 3.4 : 2}
                  fill="var(--c-litigation)"
                  opacity={lit ? 1 : 0.42}
                />
              );
            })}
          </g>

          {/* --- below the axis: monthly legislative counts ------------------------- */}
          <g clipPath="url(#board-frame)">
            {stateBills.map((m) => {
              const g = monthGeom(m.month);
              const w = Math.max(1.5, g.x1 - g.x0 - 1.5);
              return (
                <rect
                  key={m.month}
                  x={g.x0 + 0.75}
                  y={AXIS_Y}
                  width={w}
                  height={(m.n / max) * H_BOT}
                  fill="var(--c-legislation)"
                  opacity={0.78}
                />
              );
            })}
            <path d={legPath} fill="none" stroke="var(--c-legislation)" strokeWidth={1.25} opacity={0.5} />
          </g>

          {/* --- executive orders: A MARKER LAYER, NOT A SERIES --------------------- */}
          {/* They get no scale. An EO has no magnitude to plot, so plotting one would be
              inventing a quantity; the tick says only "one happened, here". */}
          <g clipPath="url(#board-frame)">
            {eos.map((e) => (
              <line
                key={`${e.date}-${e.title.slice(0, 12)}`}
                x1={x(e.t)}
                y1={AXIS_Y - 7}
                x2={x(e.t)}
                y2={AXIS_Y + 7}
                stroke="var(--c-executive)"
                strokeWidth={1.5}
              >
                <title>{`${e.date} — ${e.title}`}</title>
              </line>
            ))}
          </g>

          {/* --- quarterly ticks: THE RULES ONLY; their labels are HTML ------------- */}
          {ticks.map((q) => (
            <line
              key={q.t}
              x1={x(q.t)}
              y1={AXIS_Y + H_BOT + 4}
              x2={x(q.t)}
              y2={AXIS_Y + H_BOT + 9}
              stroke="#404040"
            />
          ))}

          {/* The frame's leading edge. Its numeral is a chip in the label layer. */}
          <line
            x1={PAD_L + clipW}
            y1={8}
            x2={PAD_L + clipW}
            y2={AXIS_Y + H_BOT}
            stroke="#525252"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        </svg>

        {/* --- the label layer ---------------------------------------------------- */}
        {/* Percent-positioned over the same box, sized in CSS pixels. Nothing here is
            measured at runtime and nothing here is an effect: it is pure from props and
            server-rendered, so the first paint already carries the lettering. */}
        <div className="board-labels">
          {/* The rail. THE TWO-LINE SERIES LABEL THAT USED TO SIT HERE IS DELETED: the
              board's key names both below-axis series, and assert-encodings joins that
              key against the paint in both directions -- a stronger guarantee than a
              caption inside the plot that nothing checks. */}
          <span
            className="board-lbl rail"
            style={{ left: pctX(PAD_L - 6), top: pctY(yOfTotal(JURISDICTIONS)) }}
          >
            {JURISDICTIONS}
          </span>
          <span className="board-lbl rail" style={{ left: pctX(PAD_L - 6), top: pctY(AXIS_Y) }}>
            0
          </span>

          {/* Quarterly labels. A four-character year is major; Q2/Q3/Q4 are minor, and
              the minors are what the container rule drops when the chart gets narrow. */}
          {ticks.map((q) => (
            <span
              key={q.t}
              className={`board-lbl axis${q.label.length === 4 ? "" : " minor"}`}
              style={{ left: pctX(x(q.t)), top: pctY(AXIS_Y + H_BOT + 22) }}
            >
              {q.label}
            </span>
          ))}

          {/* Milestone markers. GATED ON THE FRAME, exactly as the filing dots are: a
              marker for something that has not happened yet would show the replay its
              own endpoint. aria-hidden because the caption strip below carries the same
              text as real prose, and announcing both would read the list twice. */}
          {reached.map((m, i) => (
            <span
              key={m.date}
              data-encoding="milestone-marker"
              className="board-ms"
              style={{
                left: pctX(x(m.t)),
                top: pctY(m.anchor === "axis" ? AXIS_Y : yOfTotal(totalAt(m.t))),
              }}
              title={m.label}
              aria-hidden="true"
            >
              {i + 1}
            </span>
          ))}

          {/* The one load-bearing numeral, bound to the frame's own last step. */}
          <span
            className={`board-chip${chipLeads ? " leads" : ""}${chipBelow ? " below" : ""}`}
            style={{ left: pctX(PAD_L + clipW), top: pctY(yOfTotal(lastVisible?.total ?? 0)) }}
          >
            {lastVisible?.total ?? 0} of {JURISDICTIONS}
          </span>
        </div>
      </div>

      {/* --- the caption strip --------------------------------------------------- */}
      {/* ANNOTATION TEXT NEVER SITS INSIDE THE PLOT, which is what lets the markers be
          small: the prose lives here and the plot carries a numeral.
          EVERY ENTRY IS ALWAYS IN THE FLOW and unreached ones are merely invisible.
          That is two constraints meeting rather than a styling choice -- `visibility`
          keeps the strip's height identical on every frame, which assert-layout asserts
          across all 23 of them, while `display:none` would reflow the board as the
          scrubber moved; and hiding rather than omitting keeps the replay from naming a
          date it has not reached. */}
      <ol className="board-caps">
        {MILESTONES.map((m, i) => (
          <li key={m.date} data-reached={i < reachedCount ? "true" : "false"}>
            <span className="n" aria-hidden="true">
              {i + 1}
            </span>
            {m.label}
          </li>
        ))}
      </ol>
    </>
  );
}
