import { POSTURE_FILL, POSTURE_LABEL } from "@/lib/board";

// THE REGISTER, shared by both keys on this page rather than copied into each. A key
// that drifts from the other key is a second vocabulary, which is the problem a key
// exists to solve.
const REGISTER =
  "flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-neutral-500";

// The source-grade legend, on a rule under the nav.
//
// IT APPEARS EXACTLY ONCE, and the placement is the argument: it defines the
// vocabulary before the reader meets it, rather than explaining it after the fact at
// the foot of the page. v33 of the mock shipped it in both places while its source
// read as though it had been moved, which is why section 7 asserts the count in the
// RENDERED DOM and not by grepping this file. One <div data-legend> is the marker
// that assertion counts.
export function SourceLegend() {
  return (
    <div
      data-legend
      className={`mt-4 border-t border-neutral-800 pt-3 ${REGISTER}`}
    >
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block h-2 w-2 rounded-full bg-neutral-300"
        />
        collected in the last 24 hours
      </span>
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block h-2 w-2 rounded-full border border-dashed border-neutral-500"
        />
        added to the record, dated earlier
      </span>
      <span className="text-neutral-600">·</span>
      <span>
        <span className="font-medium text-neutral-300">A1</span> government and court
        records
      </span>
      <span>
        <span className="font-medium text-neutral-300">B2</span> maintained trackers
        and specialist outlets
      </span>
      <span>
        <span className="font-medium text-neutral-300">C3</span> aggregated news,
        until corroborated
      </span>
    </div>
  );
}

// --- the board's key ---------------------------------------------------------------
//
// WHAT IS NAMED HERE WAS ENUMERATED FROM THE EMITTED DOM, not from the component's
// header comment. That distinction is the whole reason this file changed: the board
// shipped with no key at all, past a verification pass that asserted a "legend count"
// -- and passed, because it counted <SourceLegend> above and never looked at the map
// below. A check can name the thing it is missing and still be pointed elsewhere.
//
// So the marker is `data-key`, NOT a second `data-legend`. Adding one would have made
// that assertion read 2 and go on proving nothing; a distinct marker makes the two
// countable apart. Each entry carries `data-encoding`, so a check can JOIN emitted
// encodings against named ones rather than counting boxes -- the count was never the
// question.
//
// RESERVED STROKE IS ABSENT ON PURPOSE. There is nothing to name until the teal layer
// exists, and a key entry for an unpainted encoding is the same lie in the other
// direction.
//
// Hover and selection are absent for a different reason and it is not an oversight:
// they are affordances rather than encodings of the record, they carry no datum, and
// neither is emitted by a page at rest.

function Entry({
  encoding,
  swatch,
  children,
}: {
  encoding: string;
  swatch: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span data-encoding={encoding} className="flex items-center gap-2">
      {swatch}
      {children}
    </span>
  );
}

/** A jurisdiction chip, drawn with the map's own fill AND the map's own hairline. */
function Chip({ posture }: { posture: keyof typeof POSTURE_FILL }) {
  return (
    <svg aria-hidden width="14" height="11" className="shrink-0">
      <rect
        x="0.3"
        y="0.3"
        width="13.4"
        height="10.4"
        rx="2"
        fill={POSTURE_FILL[posture]}
        stroke="#0a0a0a"
        strokeWidth={0.6}
      />
    </svg>
  );
}

export function BoardKey() {
  return (
    <div data-key="board" className="mt-3 space-y-2 border-t border-neutral-800 pt-3">
      <div className={REGISTER}>
        <span className="w-10 shrink-0 uppercase tracking-wide text-neutral-600">Map</span>
        <Entry encoding="posture-live" swatch={<Chip posture="live" />}>
          {POSTURE_LABEL.live}
        </Entry>
        <Entry encoding="posture-ended" swatch={<Chip posture="ended" />}>
          {POSTURE_LABEL.ended}
        </Entry>
        <Entry encoding="posture-none" swatch={<Chip posture="none" />}>
          {POSTURE_LABEL.none}
        </Entry>
        <Entry
          encoding="state-bill-dot"
          swatch={
            // TWO circles, because the radius is the encoding. One dot would name the
            // colour and say nothing about the thing that varies across nine states.
            <svg aria-hidden width="26" height="14" className="shrink-0">
              <circle cx="4" cy="7" r="3" fill="var(--c-legislation)" opacity={0.9} />
              <circle cx="16" cy="7" r="6" fill="var(--c-legislation)" opacity={0.9} />
            </svg>
          }
        >
          state bills tracked, sized by count
        </Entry>
      </div>

      <div className={REGISTER}>
        <span className="w-10 shrink-0 uppercase tracking-wide text-neutral-600">Chart</span>
        <Entry
          encoding="filings-cumulative"
          swatch={
            <svg aria-hidden width="20" height="11" className="shrink-0">
              <path
                d="M 0 9 L 7 9 L 7 5 L 13 5 L 13 2 L 20 2"
                fill="none"
                stroke="var(--c-litigation)"
                strokeWidth={1.75}
              />
            </svg>
          }
        >
          jurisdictions sued, cumulative to 51
        </Entry>
        <Entry
          encoding="filing-date-dot"
          swatch={
            <svg aria-hidden width="14" height="11" className="shrink-0">
              <circle cx="4" cy="5.5" r="2" fill="var(--c-litigation)" opacity={0.42} />
              <circle cx="11" cy="5.5" r="3.4" fill="var(--c-litigation)" />
            </svg>
          }
        >
          a filing date, lit in its own month
        </Entry>
        <Entry
          encoding="state-bills-monthly"
          swatch={
            <svg aria-hidden width="14" height="11" className="shrink-0">
              <rect x="1" y="1" width="4" height="9" fill="var(--c-legislation)" opacity={0.78} />
              <rect x="7" y="4" width="4" height="6" fill="var(--c-legislation)" opacity={0.78} />
            </svg>
          }
        >
          state bills first seen, monthly
        </Entry>
        <Entry
          encoding="legislation-monthly"
          swatch={
            <svg aria-hidden width="20" height="11" className="shrink-0">
              <path
                d="M 0 8 L 6 3 L 13 7 L 20 2"
                fill="none"
                stroke="var(--c-legislation)"
                strokeWidth={1.25}
                opacity={0.5}
              />
            </svg>
          }
        >
          federal legislative actions, monthly
        </Entry>
        <Entry
          encoding="executive-order-tick"
          swatch={
            <svg aria-hidden width="14" height="11" className="shrink-0">
              <line x1="7" y1="0" x2="7" y2="11" stroke="var(--c-executive)" strokeWidth={1.5} />
            </svg>
          }
        >
          election executive order
        </Entry>
      </div>
    </div>
  );
}
