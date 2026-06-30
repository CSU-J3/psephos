"use client";

import { useState } from "react";
import type { ExecItem } from "@/lib/db";
import { ExecutiveList } from "./ExecutiveList";

// The one stateful piece in the app. Defaults to the election-relevant subset
// (scored server-side in the page); a toggle reveals the full broad channel so
// the routine rulemaking is one click away, never hidden. Scoring stays on the
// server; this only flips which array renders.
export function ExecutiveSection({
  relevant,
  all,
}: {
  relevant: ExecItem[];
  all: ExecItem[];
}) {
  const [showAll, setShowAll] = useState(false);
  const items = showAll ? all : relevant;

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Executive
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {showAll ? `all ${all.length}` : `${relevant.length} relevant`}
          </span>
        </h2>
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="shrink-0 rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:border-neutral-500"
        >
          {showAll ? "Show relevant" : `Show all ${all.length}`}
        </button>
      </div>
      <ExecutiveList items={items} />
    </div>
  );
}
