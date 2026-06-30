// NATO Admiralty grade badge, e.g. "A1" / "B2" / "C3". Source reliability (A-F)
// drives the accent colour: A primary records strongest, C aggregated weakest.
const ACCENT: Record<string, string> = {
  A: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  B: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  C: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

export function Grade({ grade }: { grade: string }) {
  const accent = ACCENT[grade[0]] ?? "border-neutral-700 bg-neutral-800 text-neutral-300";
  return (
    <span
      title={`Admiralty grade ${grade}`}
      className={`inline-block rounded border px-1.5 py-0.5 font-mono text-xs ${accent}`}
    >
      {grade}
    </span>
  );
}
