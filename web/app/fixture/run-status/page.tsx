import { RunStatus } from "@/components/RunStatus";
import { HEARTBEAT_FAR_MS, type Heartbeat } from "@/lib/staleness";

/**
 * A VISUAL CHECKPOINT FOR AN ELEMENT WHOSE INTERESTING STATES DO NOT EXIST YET.
 *
 * `RunStatus` has four states and the live page can only ever show one of them today:
 * collection is current. The state that matters — a named missing slot — requires a
 * scheduled run to actually go missing, which has happened once in the record's life
 * (the 09-14 18:17Z slot). Shipping an element and looking only at its empty branch is
 * how a red branch reaches production unseen, so every branch is rendered here at a
 * FIXED instant, off fabricated heartbeats, and screenshotted before the commit.
 *
 * THE INSTANT IS A CONSTANT, not a clock read: `clock.test.ts` bans a bare wall-clock
 * read in this layer and grants exactly one exemption, to `lib/staleness.ts`. A fixture
 * that reached for the clock would spend the layer's only exemption on a screenshot.
 *
 * DEV-ONLY, AND ENFORCED RATHER THAN NAMED. The first draft lived under
 * `app/_fixture/`, on the assumption that a leading underscore keeps a route out of the
 * way. It does more than that: a private folder is excluded from ROUTING ENTIRELY, so
 * the fixture 404ed and could never be looked at -- which is a strange property for a
 * file whose whole purpose is to be looked at. It is a real route now, behind a
 * `notFound()` on production, so it renders under `pnpm dev` and does not exist on the
 * deployed site. `tests/test_heartbeat.py` asserts the guard.
 */
import { notFound } from "next/navigation";

export const dynamic = "force-static";

const SLOT = Date.parse("2026-09-17T06:17:00Z");
const NOW = SLOT + HEARTBEAT_FAR_MS + 3_600_000; // an hour past the edge

const hb = (finishedAtMs: number, itemsWritten: number, conclusion = "success"): Heartbeat => ({
  slot: "17 0 * * *",
  finishedAt: new Date(finishedAtMs).toISOString(),
  itemsWritten,
  conclusion,
});

const CASES: { name: string; heartbeats: Heartbeat[] }[] = [
  {
    name: "current — the only state the live page can show today",
    heartbeats: [hb(SLOT + 5 * 3_600_000, 47)],
  },
  {
    name: "quiet — ran, nothing new (2 of 34 runs since the anchor went live)",
    heartbeats: [hb(SLOT + 5 * 3_600_000, 0)],
  },
  {
    name: "one slot missing — the 09-14 shape, the only real instance so far",
    heartbeats: [hb(SLOT - 6 * 3_600_000 + 5 * 3_600_000, 12)],
  },
  {
    name: "several slots missing, and the last run failed",
    heartbeats: [hb(SLOT - 30 * 3_600_000, 3, "failure")],
  },
  { name: "no heartbeat at all — the table before its first run", heartbeats: [] },
];

export default function Fixture() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">RunStatus — every state</h1>
      <p className="mt-2 text-sm text-neutral-400">
        Rendered at a fixed instant, {new Date(NOW).toISOString()}, off fabricated
        heartbeats. Not a route anyone links to.
      </p>
      <div className="mt-8 space-y-8">
        {CASES.map((c) => (
          <section key={c.name} className="border-t border-neutral-800 pt-4">
            <h2 className="text-xs uppercase tracking-wide text-neutral-500">{c.name}</h2>
            <RunStatus heartbeats={c.heartbeats} nowMs={NOW} />
          </section>
        ))}
      </div>
    </main>
  );
}
