"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CALLOUTS,
  CALLOUT_ABS,
  LABEL_ANCHOR,
  MAP_VIEWBOX,
  US_STATES,
  tryResolveState,
} from "@/lib/map";
import { visibleAt, type EoTick, type FilingStep, type Frame, type MonthCount, type Domain } from "@/lib/board";
import { RecordsBoard } from "@/components/RecordsBoard";

// The map, its scrubber and the detail panel. Receives rows as props from the server
// page: no client-side database access, no fetch on mount, no map library.
//
// ONE PROPERTY, ONE MEANING. Nothing here may take a second job:
//   fill       litigation posture -- suit live / suit ended / never sued
//   stroke     RESERVED for outcome. Unused this unit; the teal layer takes it when it
//              exists, and until then nothing else may.
//   violet dot state bills tracked, radius scaled by the running total
//   glow       selection
//   brightness hover
// Selection and hover therefore touch neither fill nor stroke -- if hover changed fill,
// a cursor crossing the map would read as posture changing under it.

export type Posture = "live" | "ended" | "none";

export type MapState = {
  ab: string;
  name: string;
  posture: Posture;
  /** State bills tracked, cumulative to the frame. */
  bills: number;
  dockets: {
    caseId: string;
    court: string | null;
    docket: string | null;
    filed: string | null;
    status: string | null;
    entries: number | null;
    supersededBy: string | null;
    /** Dockets this row CONTINUES. Plural: a successor may absorb more than one. */
    continues: string[];
  }[];
  /** getTrackerNotes() prose, rendered VERBATIM. Never parsed. */
  notes: string | null;
};

const FILL: Record<Posture, string> = {
  live: "var(--c-litigation)",
  ended: "color-mix(in oklch, var(--c-litigation) 42%, #171717)",
  none: "#1f1f1f",
};

/** Dot radius from a running total. Sub-linear so Texas does not swamp North Carolina. */
function dotRadius(n: number, max: number): number {
  if (n <= 0) return 0;
  return 3 + Math.sqrt(n / Math.max(max, 1)) * 8.7; // 3 .. 11.7
}

export function RecordsMap({
  domain,
  filings,
  stateBillMonths,
  legislation,
  eos,
  frames,
  states,
  billsByStateMonth,
}: {
  domain: Domain;
  filings: FilingStep[];
  stateBillMonths: MonthCount[];
  legislation: MonthCount[];
  eos: EoTick[];
  frames: Frame[];
  states: MapState[];
  /** ab -> [{month, n}], for the per-frame running dot totals. */
  billsByStateMonth: Record<string, MonthCount[]>;
}) {
  const [frameIndex, setFrameIndex] = useState(frames.length - 1);
  const [selected, setSelected] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frame = frames[frameIndex];

  // Repeated clicks must not stack timers: every scheduling path clears first.
  const clearTimer = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => {
    if (!playing) {
      clearTimer();
      return;
    }
    if (frameIndex >= frames.length - 1) {
      setPlaying(false);
      return;
    }
    // Dwell longer on frames where a jurisdiction was added: those are the frames the
    // replay exists to show, and an even cadence hides them among the quiet months.
    const next = frames[frameIndex + 1];
    const added = visibleAt(filings, next).length > visibleAt(filings, frame).length;
    clearTimer();
    timer.current = setTimeout(() => setFrameIndex((i) => i + 1), added ? 1500 : 550);
    return clearTimer;
  }, [playing, frameIndex, frames, filings, frame, clearTimer]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cumulativeBills = (ab: string): number => {
    const months = billsByStateMonth[ab];
    if (!months) return 0;
    let n = 0;
    for (const m of months) {
      if (Date.parse(`${m.month}-01T00:00:00Z`) <= frame.endsAt) n += m.n;
    }
    return n;
  };

  const maxBills = Math.max(
    1,
    ...Object.keys(billsByStateMonth).map((ab) => cumulativeBills(ab)),
  );

  const byAb = new Map(states.map((s) => [s.ab, s]));
  const chosen = selected ? byAb.get(selected) ?? null : null;

  // Only jurisdictions whose first filing has happened by this frame read as sued.
  const suedByFrame = new Set<string>();
  for (const step of visibleAt(filings, frame)) {
    for (const state of step.states) {
      const f = tryResolveState(state);
      if (f) suedByFrame.add(f.ab);
    }
  }

  const postureAt = (ab: string): Posture => {
    if (!suedByFrame.has(ab)) return "none";
    return byAb.get(ab)?.posture ?? "none";
  };

  const toggle = (ab: string) => setSelected((cur) => (cur === ab ? null : ab));

  return (
    <div>
      <RecordsBoard
        domain={domain}
        filings={filings}
        stateBills={stateBillMonths}
        legislation={legislation}
        eos={eos}
        frame={frame}
      />

      {/* --- scrubber ------------------------------------------------------------ */}
      <div className="mt-2 flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            clearTimer();
            setPlaying((p) => {
              if (!p && frameIndex >= frames.length - 1) setFrameIndex(0);
              return !p;
            });
          }}
          className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 transition-colors hover:border-neutral-500"
        >
          {playing ? "Stop" : "Replay"}
        </button>
        <input
          type="range"
          min={0}
          max={frames.length - 1}
          value={frameIndex}
          aria-label="Month"
          onChange={(e) => {
            // Dragging stops playback rather than fighting it.
            setPlaying(false);
            clearTimer();
            setFrameIndex(Number(e.target.value));
          }}
          className="h-1 flex-1 accent-neutral-400"
        />
        <span className="w-24 shrink-0 text-right text-xs tabular-nums text-neutral-400">
          {frame.toDate ? "(to date)" : frame.label}
        </span>
      </div>

      {/* --- map ----------------------------------------------------------------- */}
      <svg
        viewBox={`0 0 ${MAP_VIEWBOX.width} ${MAP_VIEWBOX.height}`}
        className="mt-3 w-full"
        role="img"
        aria-label={`DOJ voter-data suits and tracked state bills by jurisdiction, through ${frame.label}`}
        onClick={(e) => {
          // A click on empty SVG clears; a click that reached a state stopped there.
          if (e.target === e.currentTarget) setSelected(null);
        }}
      >
        <defs>
          <filter id="map-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="0" stdDeviation="3.2" floodColor="#fafafa" floodOpacity="0.55" />
          </filter>
        </defs>

        {US_STATES.filter((f) => !CALLOUT_ABS.has(f.ab)).map((f) => {
          const isSel = selected === f.ab;
          return (
            <path
              key={f.ab}
              data-ab={f.ab}
              d={f.d}
              fill={FILL[postureAt(f.ab)]}
              stroke="#0a0a0a"
              strokeWidth={0.6}
              filter={isSel ? "url(#map-glow)" : undefined}
              className="cursor-pointer transition-[filter] hover:brightness-150"
              tabIndex={0}
              role="button"
              aria-label={f.name}
              aria-pressed={isSel}
              onClick={() => toggle(f.ab)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle(f.ab);
                }
              }}
            >
              <title>{f.name}</title>
            </path>
          );
        })}

        {/* --- callout squares for the nine small jurisdictions ------------------- */}
        {CALLOUTS.map((c) => {
          const isSel = selected === c.ab;
          return (
            <g key={c.ab}>
              <line
                x1={c.cx}
                y1={c.cy}
                x2={c.x}
                y2={c.y + c.size / 2}
                stroke="#404040"
                strokeWidth={0.6}
                // Overlay marks must not swallow clicks meant for the state beneath.
                pointerEvents="none"
              />
              <rect
                data-ab={c.ab}
                x={c.x}
                y={c.y}
                width={c.size}
                height={c.size}
                rx={3}
                fill={FILL[postureAt(c.ab)]}
                stroke="#0a0a0a"
                strokeWidth={0.6}
                filter={isSel ? "url(#map-glow)" : undefined}
                className="cursor-pointer hover:brightness-150"
                tabIndex={0}
                role="button"
                aria-label={c.name}
                aria-pressed={isSel}
                onClick={() => toggle(c.ab)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggle(c.ab);
                  }
                }}
              >
                <title>{c.name}</title>
              </rect>
              <text
                x={c.x + c.size / 2}
                y={c.y + c.size / 2 + 4}
                textAnchor="middle"
                fontSize={12}
                fill="#e5e5e5"
                pointerEvents="none"
              >
                {c.ab}
              </text>
            </g>
          );
        })}

        {/* --- state-bill dots and their counts ----------------------------------- */}
        {/* The dot and its number are ONE OBJECT centred on the anchor, measured at
            render: both inputs vary (radius 3..11.7 with the count, label one to three
            digits), so a constant offset puts Texas's 198 inside its own marker. */}
        {Object.keys(LABEL_ANCHOR).map((ab) => {
          const n = cumulativeBills(ab);
          if (n <= 0) return null;
          return (
            <BillMarker
              key={ab}
              ab={ab}
              n={n}
              r={dotRadius(n, maxBills)}
              anchor={LABEL_ANCHOR[ab]}
            />
          );
        })}
      </svg>

      {/* --- panel ---------------------------------------------------------------- */}
      {/* Fixed min-height so selecting does not reflow the column. */}
      <div
        data-panel
        className="mt-3 min-h-[220px] rounded-lg border border-neutral-800 bg-neutral-900/40 p-4"
      >
        {!chosen ? (
          <p className="text-sm text-neutral-500">
            Select a jurisdiction to see its dockets and the tracker&rsquo;s note.
          </p>
        ) : (
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-base font-semibold text-neutral-100">{chosen.name}</h3>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-xs text-neutral-500 hover:text-neutral-300"
              >
                clear
              </button>
            </div>
            <p className="mt-1 text-xs text-neutral-400">
              <span className="rounded border border-neutral-700 px-1.5 py-0.5">
                {chosen.posture === "live"
                  ? "suit live"
                  : chosen.posture === "ended"
                    ? "suit ended"
                    : "never sued"}
              </span>{" "}
              · {cumulativeBills(chosen.ab)} tracked{" "}
              {cumulativeBills(chosen.ab) === 1 ? "bill" : "bills"}
            </p>

            {chosen.dockets.length > 0 && (
              <ul className="mt-3 space-y-2">
                {chosen.dockets.map((d) => (
                  <li key={d.caseId} className="text-xs text-neutral-400">
                    <span className="text-neutral-200">{d.court ?? "court unknown"}</span>{" "}
                    {d.docket} · filed {d.filed?.slice(0, 10) ?? "—"} · {d.status}
                    {d.entries !== null && <> · {d.entries} entries</>}
                    {d.supersededBy && <> · continued as {d.supersededBy}</>}
                    {d.continues.length > 0 && <> · continues {d.continues.join(", ")}</>}
                  </li>
                ))}
              </ul>
            )}

            {chosen.notes && (
              // VERBATIM, GRADED B2, NEVER PARSED. A regex over "dismissed" would score
              // Delaware's "state's motion to dismiss completed" -- briefing, not a
              // ruling -- the same as Colorado's "dismissed on the merits", which is a
              // classifier asserting outcomes the record does not structure.
              <div className="mt-3 border-t border-neutral-800 pt-3">
                <span className="mr-2 inline-block rounded border border-amber-900/60 bg-amber-950/40 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
                  B2
                </span>
                <span className="text-xs leading-relaxed text-neutral-300">{chosen.notes}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * A dot and its count as one centred object.
 *
 *   groupW = 2r + 6 + labelWidth      labelWidth MEASURED, via getComputedTextLength
 *   startX = anchor.x - groupW / 2
 *   dot.cx = startX + r               dot.cy = anchor.y
 *   label.x = startX + 2r + 6         label.y = anchor.y + 5
 *
 * The anchor's Y is applied as well as its X. Moving only X leaves the label on
 * whatever row the initial render baked in, which is the bug that looks like a
 * correct label in the wrong place.
 */
function BillMarker({
  ab,
  n,
  r,
  anchor,
}: {
  ab: string;
  n: number;
  r: number;
  anchor: readonly [number, number];
}) {
  const textRef = useRef<SVGTextElement>(null);
  const [labelW, setLabelW] = useState(0);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    setLabelW(el.getComputedTextLength());
  }, [n]);

  const [ax, ay] = anchor;
  const groupW = 2 * r + 6 + labelW;
  const startX = ax - groupW / 2;

  return (
    <g data-billdot={ab} pointerEvents="none">
      <circle cx={startX + r} cy={ay} r={r} fill="var(--c-legislation)" opacity={0.9} />
      <text
        ref={textRef}
        x={startX + 2 * r + 6}
        y={ay + 5}
        fontSize={12}
        fill="#f5f5f5"
        // paint-order keeps the count legible over both the red fill and black.
        style={{ paintOrder: "stroke", stroke: "#0a0a0a", strokeWidth: 3 }}
      >
        {n}
      </text>
    </g>
  );
}
