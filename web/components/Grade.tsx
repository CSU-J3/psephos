// NATO Admiralty grade badge, e.g. "A1" / "B2" / "C3". Source reliability (A-F)
// drives the accent colour: A primary records strongest, C aggregated weakest.
const ACCENT: Record<string, string> = {
  A: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  B: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  C: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

// Two sizes, kept as WHOLE alternative strings rather than a base plus an override.
// Appending `text-[0.62rem]` to a string already holding `text-xs` does not reliably
// win -- conflicting utilities resolve on emission order, not on the order they appear
// in the attribute -- so the sizes never coexist in one class list.
const SIZE = {
  default: "px-1.5 py-0.5 text-xs",
  dense: "px-1 py-px text-[0.62rem] leading-normal",
};

export function Grade({ grade, dense = false }: { grade: string; dense?: boolean }) {
  const accent = ACCENT[grade[0]] ?? "border-neutral-700 bg-neutral-800 text-neutral-300";
  return (
    <span
      title={`Admiralty grade ${grade}`}
      className={`inline-block shrink-0 rounded border font-mono ${SIZE[dense ? "dense" : "default"]} ${accent}`}
    >
      {grade}
    </span>
  );
}
