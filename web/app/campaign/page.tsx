import Link from "next/link";
import { getCampaignMovement, getCampaignRows, getTrackerNotes } from "@/lib/db";
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
import {
  latestMovement,
  membersOf,
  sectionByState,
  SECTION_ORDER,
  SECTION_TITLE,
  type SectionKey,
} from "@/lib/movement";
import { StateCell } from "@/components/StateCell";
import { Grade } from "@/components/Grade";
import { formatDate } from "@/lib/format";

// Live Turso per request, same as every other route. force-dynamic is also what makes
// the search params below free: every view is already a fresh render, so opening a
// section costs nothing beyond the section.
export const dynamic = "force-dynamic";

// Docket facts come from CourtListener and the tracker's framing comes from a
// maintained expert tracker; they are different claims from different sources and
// the page grades them separately rather than picking one grade per row.
const A1 = "A1";
const B2 = "B2";

// THE SECTIONS ARE OPT-IN NOW, AND THAT IS THE WHOLE CHANGE. This page used to render
// all four open on every visit -- the grid, then ~23 expanded rows nobody had asked
// for, 4,473px of page. The reader arrives with a question about one jurisdiction or
// one category; the grid and the section lines answer "which", and only then does a
// list open. Same inversion /state-bills took, and the same mechanism: server-rendered
// links over search params, no client component, no hydration.

/** Prose that belongs to a section and renders only when the section does. */
const SECTION_INTRO: Record<SectionKey, string> = {
  continued:
    "An appeal and a refile are not the same event. An appeal means a district court ruled and the case went up; a refile means DOJ moved venue with no ruling on the merits. The grid marks them differently for that reason.",
  unlinked:
    "A docket that ended while another docket in the same state is live, with nothing in the record connecting them. That is a third thing from the two sections around it: a continuation psephos has not asserted, rather than one it has or one that does not exist. Until the link is asserted the two dockets are separate facts, and this section says so rather than guessing at the relationship.",
  ended:
    "The live docket is terminated and psephos holds nothing that continues it. Which court ended it is the whole content of the row: a circuit affirmance is a different outcome from a district dismissal, and Oklahoma is a settlement rather than either. “In this record” is load-bearing — where the tracker’s B2 line names an appeal the A1 record does not have, both are shown and the disagreement is flagged rather than resolved.",
  quiet: `Live dockets with no activity in over ${DORMANT_AFTER_DAYS} days. Quiet is not dead: a docket can be stayed, or waiting on a ruling. The tracker’s own status line is what distinguishes them, and it is graded B2 beside the A1 docket record. The date beside each is when psephos last read the docket’s status, so a long silence is the court’s, not this tool’s.`,
};

function href(section: SectionKey, state?: string): string {
  const p = new URLSearchParams({ section });
  if (state) p.set("state", state);
  return `/campaign?${p.toString()}#section`;
}

const ROW = "border-b border-[#1c1c1c] px-2.5 py-2.5";
const HL = "rounded-md bg-[#0d1a1e] outline outline-1 outline-[#164e63]";
const L1 = "flex flex-wrap items-baseline gap-x-2.5 gap-y-1";
const NAME = "min-w-[7.5rem] text-[0.9rem] font-semibold";
// One line, always. The entry text is a court's own sentence and runs long; the row is
// a pointer to the docket, not a place to read it.
const L2 = "mt-1 line-clamp-1 text-[0.8rem] text-neutral-300";

/** A section row, highlighted when the URL names its state. */
function Row({ code, hl, children }: { code: string; hl: boolean; children: React.ReactNode }) {
  return (
    <li id={`st-${code}`} className={`${ROW} ${hl ? HL : ""}`}>
      {children}
    </li>
  );
}

export default async function CampaignPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [rows, notes, movementRows] = await Promise.all([
    getCampaignRows(),
    getTrackerNotes(),
    getCampaignMovement(),
  ]);
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || null;
  const raw = one(sp.section);
  const open = (SECTION_ORDER as readonly string[]).includes(raw ?? "")
    ? (raw as SectionKey)
    : null;
  const focus = one(sp.state)?.toUpperCase() ?? null;

  const now = new Date();
  const cells = buildCells(rows, now);
  const s = summarize(cells);
  const homes = sectionByState(cells);
  const movement = latestMovement(movementRows);
  const codeOf = new Map(cells.map((c) => [c.name, c.code]));

  // ORDERING INSIDE A SECTION IS THE SECTION'S OWN, and each has a reason. Michigan
  // first among endings: terminated at a CIRCUIT with no successor, the campaign's
  // furthest-progressed loss, which would otherwise sort among district dismissals as
  // though it were one. Quiet by length of silence, longest first.
  const members = (key: SectionKey): Cell[] => {
    const m = membersOf(cells, key);
    if (key === "ended") {
      return [...m].sort(
        (a, b) =>
          Number(b.live?.court?.includes("Circuit")) - Number(a.live?.court?.includes("Circuit")),
      );
    }
    if (key === "quiet") return [...m].sort((a, b) => (b.quietDays ?? 0) - (a.quietDays ?? 0));
    return m;
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-5">
        <h1 className="text-2xl font-semibold tracking-tight">
          The DOJ voter-data campaign
        </h1>
        <p className="mt-1 text-sm text-neutral-400">
          {s.sued} of {s.total} jurisdictions sued — {s.live} {POSTURE_LABEL.live},{" "}
          {s.ended} {POSTURE_LABEL.ended}, {s.chains} continued through an appeal or a
          refile.
        </p>
      </header>

      <div className="mt-6 grid grid-cols-6 gap-1.5 lg:grid-cols-9">
        {cells.map((c) => (
          <StateCell key={c.code} cell={c} section={homes.get(c.code) ?? null} />
        ))}
      </div>

      {/* THE LEGEND'S VOCABULARY IS UNCHANGED: four marks, the same four glyphs, the
          same four meanings. The mock draws dormancy as a small bullet; this keeps the
          filled circle, because swapping a glyph IS changing an encoding even when the
          meaning survives. One SENTENCE is new, and it names an affordance rather than
          a mark -- the cells became links, and a link nobody knows is a link is not
          one. */}
      <p className="mt-3 text-xs leading-relaxed text-neutral-500">
        ↑ continued as a circuit appeal · ↻ refiled in another district ·{" "}
        <span className="text-amber-400">●</span> no docket activity in over{" "}
        {DORMANT_AFTER_DAYS} days · † ended here, with no link asserted to the live
        docket. An unfilled cell means{" "}
        <strong className="font-medium text-neutral-400">no suit in this record</strong>{" "}
        — not that the state complied. DOJ demanded data from all 50 states and DC,
        but psephos holds no compliance data, so the {s.none} blanks say only that no
        docket for them has reached the tracker.{" "}
        <strong className="font-medium text-neutral-400">
          Every populated cell is a link — to its row below, or to the docket itself
          where a state belongs to no section; section lines open their lists.
        </strong>
      </p>

      {/* WHAT MOVED, which the grid cannot say: a cell carries a posture, and a
          posture has no date. Ordered and cut in lib/movement.ts so the ordering that
          ships is the ordering under test. */}
      <h2 className="mt-8 mb-1 flex items-baseline gap-2 text-[0.8rem] font-semibold tracking-[0.08em] text-neutral-500 uppercase">
        Latest movement
        <span className="text-[0.72rem] font-normal tracking-normal text-neutral-600 normal-case">
          eight most recent docket entries, any state
        </span>
      </h2>
      <ul>
        {movement.map((m) => {
          // A movement row's state may belong to no section -- nine sued jurisdictions
          // are simply live. Those rows keep the name and drop the affordance rather
          // than linking somewhere invented.
          const code = codeOf.get(m.state);
          const key = code ? homes.get(code) : undefined;
          return (
            <li
              key={m.id}
              className="flex items-baseline gap-2.5 border-b border-[#161616] px-1 py-1.5"
            >
              <span className="min-w-[6.2rem] font-mono text-[0.72rem] text-neutral-600">
                {formatDate(m.occurred_at)}
              </span>
              <span className="min-w-[6.4rem] text-[0.85rem] font-semibold">{m.state}</span>
              <span className="min-w-0 flex-1 truncate text-[0.82rem] text-neutral-300">
                {m.text}
              </span>
              <Grade grade={m.grade} />
              {key && code && (
                <Link
                  href={href(key, code)}
                  className="shrink-0 text-[0.68rem] whitespace-nowrap text-neutral-600 hover:text-neutral-300"
                >
                  {SECTION_TITLE[key].toLowerCase()} ›
                </Link>
              )}
            </li>
          );
        })}
      </ul>

      {/* The four sections as one line each: title, count, and the roster of who is in
          it. The roster is read from membersOf -- the same function that builds the
          rows below -- so the summary and the list cannot disagree about membership. */}
      <div className="mt-7 border-t border-neutral-800">
        {SECTION_ORDER.map((key) => {
          const m = members(key);
          return (
            <Link
              key={key}
              href={href(key)}
              className="flex items-baseline gap-2.5 border-b border-[#1c1c1c] px-1 py-2.5 hover:bg-neutral-900"
            >
              <span className="text-[0.95rem] font-semibold">{SECTION_TITLE[key]}</span>
              <span className="text-[0.8rem] tabular-nums text-neutral-500">{m.length}</span>
              <span className="ml-auto font-mono text-[0.68rem] tracking-wide text-neutral-600">
                {m.map((c) => c.code).join(" ")}
              </span>
              <span className="text-neutral-600">›</span>
            </Link>
          );
        })}
      </div>

      {open && (
        <section id="section" className="mt-6 scroll-mt-6">
          <h2 className="mb-1 flex items-baseline gap-2.5 text-[1.05rem] font-semibold">
            {SECTION_TITLE[open]}
            <span className="text-[0.8rem] font-normal tabular-nums text-neutral-500">
              {members(open).length}
            </span>
            <Link
              href="/campaign"
              className="ml-auto text-[0.72rem] font-normal text-neutral-500 hover:text-neutral-100"
            >
              × close
            </Link>
          </h2>
          <p className="mb-2 max-w-4xl text-[0.78rem] leading-relaxed text-neutral-500">
            {SECTION_INTRO[open]}
          </p>
          <ul>
            {members(open).map((c) => {
              const hl = c.code === focus;
              const status = trackerStatus(notes.get(c.live?.case_id ?? ""));

              if (open === "continued") {
                return (
                  <Row key={c.code} code={c.code} hl={hl}>
                    <div className={L1}>
                      <span className={NAME}>{c.name}</span>
                      {c.predecessors.map((p) => (
                        <Link
                          key={p.case_id}
                          href={`/case/${p.case_id}`}
                          className="font-mono text-[0.78rem] text-neutral-500 hover:underline"
                        >
                          {p.court} {p.docket_number}
                        </Link>
                      ))}
                      <span className="text-neutral-600">→</span>
                      <Link
                        href={`/case/${c.live!.case_id}`}
                        className="font-mono text-[0.78rem] hover:underline"
                      >
                        {c.live!.court} {c.live!.docket_number}
                      </Link>
                      <span className="rounded border border-neutral-700 px-1.5 text-[0.62rem] text-neutral-400">
                        {c.chain}
                      </span>
                      <Grade grade={A1} />
                    </div>
                  </Row>
                );
              }

              if (open === "unlinked") {
                return (
                  <Row key={c.code} code={c.code} hl={hl}>
                    {c.unlinked.map((r) => (
                      <div key={r.case_id}>
                        <div className={L1}>
                          <span className={NAME}>{c.name}</span>
                          <Link
                            href={`/case/${r.case_id}`}
                            className="font-mono text-[0.78rem] text-neutral-500 hover:underline"
                          >
                            {r.docket_number}
                          </Link>
                          <span className="text-[0.78rem] text-neutral-500">
                            terminated {formatDate(r.latest_entry_at)}
                          </span>
                          <span className="ml-auto text-[0.78rem] text-neutral-500">
                            live here:{" "}
                            <span className="font-mono">
                              {c.live?.court} {c.live?.docket_number}
                            </span>
                          </span>
                        </div>
                        {trackerStatus(notes.get(r.case_id)) && (
                          <div className={L2}>
                            {trackerStatus(notes.get(r.case_id))} <Grade grade={B2} />
                          </div>
                        )}
                      </div>
                    ))}
                  </Row>
                );
              }

              if (open === "ended") {
                return (
                  <Row key={c.code} code={c.code} hl={hl}>
                    <div className={L1}>
                      <span className={NAME}>{c.name}</span>
                      <span className="text-[0.78rem] text-neutral-500">{c.live?.court}</span>
                      <span className="font-mono text-[0.78rem] text-neutral-500">
                        {c.live?.docket_number}
                      </span>
                      <Grade grade={A1} />
                      <span className="ml-auto text-[0.78rem] text-neutral-500">
                        last entry {formatDate(c.live?.latest_entry_at)}
                      </span>
                    </div>
                    {status && (
                      <div className={L2}>
                        {status} <Grade grade={B2} />
                      </div>
                    )}
                    {/* NEVER CLAMPED, unlike the status line above it. This is the
                        page saying its own record and its tracker disagree, and a
                        contradiction truncated mid-sentence is worse than one not
                        shown -- the reader would see half a warning and no way to
                        tell there was more. */}
                    {contestsEnding(status) && (
                      <p className="mt-1.5 rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[0.75rem] leading-relaxed text-amber-300/90">
                        Sources disagree. The docket record above is terminated with no
                        successor held; the tracker line names a further step. If that
                        step produced a new docket, psephos has not resolved it — a
                        coverage gap on the tracker side, not a closed case.
                      </p>
                    )}
                  </Row>
                );
              }

              return (
                <Row key={c.code} code={c.code} hl={hl}>
                  <div className={L1}>
                    <span className={NAME}>{c.name}</span>
                    <span className="text-[0.78rem] text-neutral-500">{c.live?.court}</span>
                    <span className="font-mono text-[0.78rem] text-neutral-500">
                      {c.live?.docket_number}
                    </span>
                    <Grade grade={A1} />
                    <span className="ml-auto text-[0.75rem] tabular-nums text-amber-400/90">
                      {c.quietDays} days quiet
                    </span>
                  </div>
                  {status && (
                    <div className={L2}>
                      {status} <Grade grade={B2} />
                    </div>
                  )}
                  {/* status_checked_at, never entries_synced_at -- the latter is an
                      upstream high-water mark held on empty windows, so it would
                      report psephos asleep on a docket it had just polled. NULL on
                      rows terminated before the 08-10 refresh, hence the guard. */}
                  {c.live?.status_checked_at && (
                    <p className="mt-0.5 text-[0.68rem] text-neutral-600">
                      status last read {formatDate(c.live.status_checked_at)}
                    </p>
                  )}
                </Row>
              );
            })}
          </ul>
        </section>
      )}
    </main>
  );
}
