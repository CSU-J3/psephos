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
      className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-neutral-800 pt-3 text-xs text-neutral-500"
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
