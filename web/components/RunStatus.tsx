import {
  HEARTBEAT_FAR_MS,
  durationLabel,
  missingSlots,
  slotLabel,
  stampLabel,
  type Heartbeat,
} from "@/lib/staleness";

/**
 * Is collection still running? — the one element on this page that asks about the
 * SCHEDULE rather than about the record.
 *
 * WHY IT CANNOT BE DERIVED FROM THE RECORD. Everything else here is anchored to
 * `MAX(fetched_at)`, and that anchor cannot answer this: `fetched_at` is written once on
 * first insert and never updated, so a run that collected nothing leaves it exactly
 * where a run that never fired would. Three of 51 scheduled runs since `58c6aca`
 * committed nothing at all. The `runs` table is written by the workflow's last step
 * under `if: always()`, so a row means the run happened whatever it collected, and an
 * absent row for a slot means it did not.
 *
 * THREE STATES, AND THE QUIET ONE IS NOT THE ALARMING ONE. A missing slot is named. A
 * run that finished having written nothing says so in those words, because "nothing
 * collected" is an ordinary day here and reading it as a fault is the mistake the
 * element exists to prevent. Everything current renders as a single line.
 *
 * `nowMs` IS PASSED IN, never read here. The one clock read in this layer lives in
 * `lib/staleness.ts`'s `clockNowMs`, which `clock.test.ts` asserts is the only one; this
 * component takes the number so it stays pure and so the states below can be rendered at
 * a fixed instant for a visual check.
 */
export function RunStatus({
  heartbeats,
  nowMs,
}: {
  heartbeats: Heartbeat[];
  nowMs: number;
}) {
  const latest = heartbeats[0] ?? null;
  const lastFinishedMs = latest ? Date.parse(latest.finishedAt) : NaN;
  const missing = missingSlots(
    heartbeats,
    nowMs,
    Number.isFinite(lastFinishedMs) ? lastFinishedMs : null,
  );

  // No heartbeat at all: the table before its first run. Saying "every slot is missing"
  // would be this element's own first defect, so it says what is true instead.
  if (!latest) {
    return (
      <p
        data-run-status="unknown"
        className="mt-[9px] text-[13px] leading-[18px] text-neutral-500"
      >
        No run has reported yet. Collection status is unknown until the next scheduled
        run writes its first heartbeat.
      </p>
    );
  }

  const stamp = stampLabel(latest.finishedAt);
  const quiet = missing.length === 0 && latest.itemsWritten === 0;

  return (
    <p
      data-run-status={missing.length ? "missing" : quiet ? "quiet" : "current"}
      className="mt-[9px] text-[13px] leading-[18px] text-neutral-400"
    >
      {missing.length > 0 ? (
        <>
          <span className="text-neutral-200">
            {missing.length === 1 ? "One scheduled run" : `${missing.length} scheduled runs`}
          </span>{" "}
          {missing.length === 1 ? "has" : "have"} not reported:{" "}
          <span className="tabular-nums">
            {missing.map(slotLabel).join(", ")}
          </span>
          . The last run finished {stamp ?? "at the record's edge"}
          {latest.conclusion !== "success" ? ` (${latest.conclusion})` : ""}.
        </>
      ) : quiet ? (
        <>
          Collection is current. The last run finished {stamp ?? "at the record's edge"}{" "}
          and <span className="text-neutral-200">collected nothing new</span> — an
          ordinary result, not a fault.
        </>
      ) : (
        <>
          Collection is current. The last run finished {stamp ?? "at the record's edge"}{" "}
          and wrote{" "}
          <span className="text-neutral-200 tabular-nums">
            {latest.itemsWritten.toLocaleString()}
          </span>{" "}
          {latest.itemsWritten === 1 ? "item" : "items"}
          {latest.conclusion !== "success" ? ` (${latest.conclusion})` : ""}.
        </>
      )}
      {/* The threshold, stated where it is applied. A slot is named only once this has
          passed, and the edge is a LOWER bound -- so the error runs toward naming a slot
          whose very late run could still land, never toward missing one. */}
      {missing.length > 0 ? (
        <span className="text-neutral-600">
          {" "}
          A slot is named {durationLabel(HEARTBEAT_FAR_MS)} after it fires.
        </span>
      ) : null}
    </p>
  );
}
