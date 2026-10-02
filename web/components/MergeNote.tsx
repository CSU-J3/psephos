// One dated note the R1 switch leaves where a figure moved (lib/merge-notes.ts). Renders
// nothing when there is no note, so a surface whose figure did not move shows nothing.
//
// A NOTE CAN HOLD MORE THAN ONE MOVE, one line each: the merge of duplicate rows, then a
// tier-2 link with its own date (Corey, 2026-10-02). Each line is its own block inside the
// one span, so the caller's display class is never contested by this one (two display
// utilities on one element resolve by emission order, not by the order written). `inline`
// runs them together, for a note inside a line of text.
export function MergeNote({
  text,
  className = "",
  inline = false,
}: {
  text: string | null;
  className?: string;
  inline?: boolean;
}) {
  if (!text) return null;
  const lines = text.split("\n");
  return (
    <span data-merge-note="" className={`text-[0.7rem] leading-snug text-neutral-600 ${className}`}>
      {inline || lines.length === 1
        ? lines.join(" ")
        : lines.map((l, i) => (
            <span key={i} className="block">
              {l}
            </span>
          ))}
    </span>
  );
}
