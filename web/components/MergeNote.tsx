// One dated note the R1 switch leaves where a figure moved (lib/merge-notes.ts). Renders
// nothing when there is no note, so a surface whose figure did not move shows nothing.
export function MergeNote({ text, className = "" }: { text: string | null; className?: string }) {
  if (!text) return null;
  return (
    <span data-merge-note="" className={`text-[0.7rem] leading-snug text-neutral-600 ${className}`}>
      {text}
    </span>
  );
}
