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

// One SVG, mirrored around a shared day-resolution axis.
//
//   above   cumulative jurisdictions sued, stepping on real filing dates, scaled 0-51
//   axis    quarterly ticks; amber marks for election EOs
//   below   monthly counts hanging down, scaled to the window's own maximum:
//           violet bars for state bills first seen, a pale violet line for federal
//           legislative actions
//
// A CLIP RECT WRAPS EVERY DATA LAYER AND NOTHING ELSE. Axis, ticks and the 51-line stay
// outside it, because they are the frame rather than the data -- a replay whose axis
// grows is a zoom, not a replay. And nothing may be drawn past the scrubber: a replay
// that shows its endpoint is not a replay.
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
    const y = (total: number) => AXIS_Y - (total / JURISDICTIONS) * (H_TOP - 12);
    let d = `M ${x(domain.start)} ${AXIS_Y}`;
    let prev = 0;
    for (const s of filings) {
      d += ` L ${x(s.t)} ${y(prev)} L ${x(s.t)} ${y(s.total)}`;
      prev = s.total;
    }
    d += ` L ${x(domain.end)} ${y(prev)}`;
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

  return (
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
        y1={AXIS_Y - (H_TOP - 12)}
        x2={W - PAD_R}
        y2={AXIS_Y - (H_TOP - 12)}
        stroke="#262626"
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      <text x={PAD_L - 6} y={AXIS_Y - (H_TOP - 12) + 4} textAnchor="end" fontSize={10} fill="#737373">
        {JURISDICTIONS}
      </text>
      <text x={PAD_L - 6} y={AXIS_Y + 4} textAnchor="end" fontSize={10} fill="#737373">
        0
      </text>

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
              cy={AXIS_Y - (s.total / JURISDICTIONS) * (H_TOP - 12)}
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

      {/* --- the two below-axis series, named in place ------------------------- */}
      {/* OUTSIDE THE CLIP, with the axis and the ticks, because a label is frame and
          not data: a label that wipes in behind the scrubber reads as a series that
          did not exist until that month. Both series are the same violet and differ
          only in mark, which the key states and these two say again at the mark
          itself -- the key is on a rule below, and a reader tracing a shape should
          not have to leave the chart to find out what it is. The aria-label above is
          unchanged; it already describes the whole figure to a reader who gets no
          marks at all. */}
      <text x={PAD_L + 4} y={AXIS_Y + H_BOT - 14} fontSize={10} fill="#8b7bb8">
        state bills first seen
      </text>
      <text x={PAD_L + 4} y={AXIS_Y + H_BOT - 3} fontSize={10} fill="#6f6a86">
        federal legislative actions
      </text>

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

      {/* --- quarterly ticks: outside the clip, no end labels ------------------- */}
      {ticks.map((q) => (
        <g key={q.t}>
          <line x1={x(q.t)} y1={AXIS_Y + H_BOT + 4} x2={x(q.t)} y2={AXIS_Y + H_BOT + 9} stroke="#404040" />
          <text
            x={x(q.t)}
            y={AXIS_Y + H_BOT + 22}
            textAnchor="middle"
            fontSize={10}
            fill={q.label.length === 4 ? "#a3a3a3" : "#525252"}
          >
            {q.label}
          </text>
        </g>
      ))}

      {/* The frame's leading edge, and the running total beside it. */}
      <line
        x1={PAD_L + clipW}
        y1={8}
        x2={PAD_L + clipW}
        y2={AXIS_Y + H_BOT}
        stroke="#525252"
        strokeWidth={1}
        strokeDasharray="2 3"
      />
      <text x={PAD_L + clipW - 5} y={18} textAnchor="end" fontSize={11} fill="#d4d4d4">
        {lastVisible?.total ?? 0} of {JURISDICTIONS}
      </text>
    </svg>
  );
}
