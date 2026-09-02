import Link from "next/link";
import { getCampaignRows, getTrackerNotes } from "@/lib/db";
import {
  buildCells,
  summarize,
  trackerStatus,
  contestsEnding,
  DORMANT_AFTER_DAYS,
} from "@/lib/campaign";
import type { Cell } from "@/lib/campaign";
// The key's own record, so this page cannot name a posture the map does not define.
import { POSTURE_LABEL } from "@/lib/board";
import { StateCell } from "@/components/StateCell";
import { Grade } from "@/components/Grade";
import { formatDate } from "@/lib/format";

// Live Turso per request, same as every other route. Two queries, ~40 and ~40 rows.
export const dynamic = "force-dynamic";

// Docket facts come from CourtListener and the tracker's framing comes from a
// maintained expert tracker; they are different claims from different sources and
// the page grades them separately rather than picking one grade per row.
const A1 = "A1";
const B2 = "B2";

function ProseRow({ children }: { children: React.ReactNode }) {
  return (
    <li className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">{children}</li>
  );
}

function DocketLine({ cell }: { cell: Cell }) {
  if (!cell.live) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-neutral-400">
      <span>{cell.live.court}</span>
      <span className="font-mono">{cell.live.docket_number}</span>
      <Grade grade={A1} />
    </div>
  );
}

export default async function CampaignPage() {
  const [rows, notes] = await Promise.all([getCampaignRows(), getTrackerNotes()]);
  const now = new Date();
  const cells = buildCells(rows, now);
  const s = summarize(cells);

  const chains = cells.filter((c) => c.chain !== null);
  // Endings the record holds with nothing asserted to connect them to what is live
  // in the same state. Neither existing section can hold these without lying:
  // `Continued elsewhere` asserts a link driven by superseded_by, which these have
  // by definition none of, and `Ended in this record` says the LIVE docket is
  // terminated, which in these states it is not.
  const unlinked = cells.filter((c) => c.unlinked.length > 0);
  // Michigan first: it is terminated at a CIRCUIT with no successor, the campaign's
  // furthest-progressed loss, and it would otherwise sort among the district
  // dismissals as though it were one.
  const ended = cells
    .filter((c) => c.status === "ended")
    .sort((a, b) => Number(b.live?.court?.includes("Circuit")) -
                    Number(a.live?.court?.includes("Circuit")));
  const dormant = cells
    .filter((c) => c.dormant)
    .sort((a, b) => (b.quietDays ?? 0) - (a.quietDays ?? 0));

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          The DOJ voter-data campaign
        </h1>
        <p className="mt-1 text-sm text-neutral-400">
          {s.sued} of {s.total} jurisdictions sued — {s.live} {POSTURE_LABEL.live},{" "}
          {s.ended} {POSTURE_LABEL.ended}, {s.chains} continued through an appeal or a
          refile.
        </p>
      </header>

      <section className="mt-8">
        <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6 lg:grid-cols-9">
          {cells.map((c) => (
            <StateCell key={c.code} cell={c} />
          ))}
        </div>
        <p className="mt-3 text-xs leading-relaxed text-neutral-500">
          ↑ continued as a circuit appeal · ↻ refiled in another district ·{" "}
          <span className="text-amber-400">●</span> no docket activity in over{" "}
          {DORMANT_AFTER_DAYS} days · † ended here, with no link asserted to the live
          docket. An unfilled cell means{" "}
          <strong className="font-medium text-neutral-400">no suit in this record</strong>{" "}
          — not that the state complied. DOJ demanded data from all 50 states and DC,
          but psephos holds no compliance data, so the {s.none} blanks say only that no
          docket for them has reached the tracker.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Continued elsewhere
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {chains.length}
          </span>
        </h2>
        <p className="mb-3 text-xs leading-relaxed text-neutral-500">
          An appeal and a refile are not the same event. An appeal means a district
          court ruled and the case went up; a refile means DOJ moved venue with no
          ruling on the merits. The grid marks them differently for that reason.
        </p>
        <ul className="space-y-3">
          {chains.map((c) => (
            <ProseRow key={c.code}>
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium">{c.name}</span>
                <span className="shrink-0 rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
                  {c.chain}
                </span>
              </div>
              {c.predecessors.map((p) => (
                <p key={p.case_id} className="mt-2 text-sm text-neutral-400">
                  <Link href={`/case/${p.case_id}`} className="hover:underline">
                    {p.court} <span className="font-mono">{p.docket_number}</span>
                  </Link>
                  <span className="text-neutral-600">
                    {" "}
                    terminated · {c.chain === "appeal" ? "appealed to" : "refiled in"}{" "}
                  </span>
                  <Link href={`/case/${c.live!.case_id}`} className="hover:underline">
                    {c.live!.court} <span className="font-mono">{c.live!.docket_number}</span>
                  </Link>
                </p>
              ))}
              <div className="mt-2">
                <Grade grade={A1} />
              </div>
            </ProseRow>
          ))}
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Ended, with no link asserted
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {unlinked.length}
          </span>
        </h2>
        <p className="mb-3 text-xs leading-relaxed text-neutral-500">
          A docket that ended while another docket in the same state is live, with{" "}
          <strong className="font-medium text-neutral-400">nothing in the record
          connecting them</strong>. That is a third thing from the two sections around
          it: a continuation psephos has not asserted, rather than one it has or one
          that does not exist. Until the link is asserted the two dockets are separate
          facts, and this section says so rather than guessing at the relationship.
        </p>
        {unlinked.length === 0 ? (
          <p className="text-sm text-neutral-500">
            Nothing unlinked — every ending in the record either points forward to a
            successor or is the state&apos;s last word.
          </p>
        ) : (
          <ul className="space-y-3">
            {unlinked.map((c) => (
              <ProseRow key={c.code}>
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium">{c.name}</span>
                  <span className="shrink-0 text-xs text-neutral-500">
                    live here: {c.live?.court}{" "}
                    <span className="font-mono">{c.live?.docket_number}</span>
                  </span>
                </div>
                {c.unlinked.map((r) => {
                  const status = trackerStatus(notes.get(r.case_id));
                  return (
                    <div key={r.case_id} className="mt-2">
                      <p className="text-sm text-neutral-400">
                        <Link href={`/case/${r.case_id}`} className="hover:underline">
                          {r.court} <span className="font-mono">{r.docket_number}</span>
                        </Link>
                        <span className="text-neutral-600">
                          {" "}
                          terminated {formatDate(r.latest_entry_at)}
                        </span>
                      </p>
                      {status && (
                        <p className="mt-1 flex flex-wrap items-baseline gap-2 text-sm text-neutral-300">
                          <span>{status}</span>
                          <Grade grade={B2} />
                        </p>
                      )}
                    </div>
                  );
                })}
                <div className="mt-2">
                  <Grade grade={A1} />
                </div>
              </ProseRow>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Ended in this record
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {ended.length}
          </span>
        </h2>
        <p className="mb-3 text-xs leading-relaxed text-neutral-500">
          The live docket is terminated and psephos holds nothing that continues it.
          Which court ended it is the whole content of the row: a circuit affirmance is
          a different outcome from a district dismissal, and Oklahoma is a settlement
          rather than either. <strong className="font-medium text-neutral-400">
          &quot;In this record&quot; is load-bearing</strong> — where the tracker&apos;s
          B2 line names an appeal the A1 record does not have, both are shown and the
          disagreement is flagged rather than resolved.
        </p>
        <ul className="space-y-3">
          {ended.map((c) => {
            const status = trackerStatus(notes.get(c.live!.case_id));
            return (
              <ProseRow key={c.code}>
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium">{c.name}</span>
                  <span className="shrink-0 text-xs text-neutral-500">
                    last entry {formatDate(c.live?.latest_entry_at)}
                  </span>
                </div>
                <DocketLine cell={c} />
                {status && (
                  <p className="mt-2 flex flex-wrap items-baseline gap-2 text-sm text-neutral-300">
                    <span>{status}</span>
                    <Grade grade={B2} />
                  </p>
                )}
                {contestsEnding(status) && (
                  <p className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-xs leading-relaxed text-amber-300/90">
                    Sources disagree. The docket record above is terminated with no
                    successor held; the tracker line names a further step. If that step
                    produced a new docket, psephos has not resolved it — a coverage gap
                    on the tracker side, not a closed case.
                  </p>
                )}
              </ProseRow>
            );
          })}
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Quiet
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {dormant.length}
          </span>
        </h2>
        <p className="mb-3 text-xs leading-relaxed text-neutral-500">
          Live dockets with no activity in over {DORMANT_AFTER_DAYS} days. Quiet is not
          dead: a docket can be stayed, or waiting on a ruling. The tracker&apos;s own
          status line is what distinguishes them, and it is graded B2 beside the A1
          docket record. The date beside each is when psephos last read the docket&apos;s
          status, so a long silence is the court&apos;s, not this tool&apos;s.
        </p>
        {dormant.length === 0 ? (
          <p className="text-sm text-neutral-500">
            Nothing over {DORMANT_AFTER_DAYS} days.
          </p>
        ) : (
          <ul className="space-y-3">
            {dormant.map((c) => (
              <ProseRow key={c.code}>
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium">{c.name}</span>
                  <span className="shrink-0 text-xs tabular-nums text-amber-400">
                    {c.quietDays} days quiet
                  </span>
                </div>
                <DocketLine cell={c} />
                {trackerStatus(notes.get(c.live!.case_id)) && (
                  <p className="mt-2 flex flex-wrap items-baseline gap-2 text-sm text-neutral-300">
                    <span>{trackerStatus(notes.get(c.live!.case_id))}</span>
                    <Grade grade={B2} />
                  </p>
                )}
                {/* status_checked_at, never entries_synced_at -- the latter is an
                    upstream high-water mark held on empty windows, so it would
                    report psephos asleep on a docket it had just polled. NULL on
                    rows terminated before the 08-10 refresh, hence the guard. */}
                {c.live?.status_checked_at && (
                  <p className="mt-1 text-xs text-neutral-600">
                    status last read {formatDate(c.live.status_checked_at)}
                  </p>
                )}
              </ProseRow>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
