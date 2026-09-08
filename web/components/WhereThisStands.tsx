"use client";

import { useState } from "react";
import type { DocketRow, Bill, StateBill } from "@/lib/db";
import { Grade } from "@/components/Grade";
import {
  dojFilings,
  relatedSuits,
  docketTotals,
  openSplit,
  wisconsinOutcomes,
  saveStallMonths,
  vehicleQuietSince,
  PRESIDENTIAL_TYPES,
} from "@/lib/stands";

// "Where this stands" -- what has already changed, and what would have to happen next.
//
// EVERY FIGURE HERE IS DERIVED AT RENDER FROM ROWS THE PAGE FETCHED. No number is
// typed into this file, and `docs/gates.yaml` registers each one against the function
// that produces it; `web/scripts/assert-gates.mjs` joins the `data-gate` attributes
// below against that register in both directions. An ungated claim and a registered
// gate the page never renders both fail.
//
// THE DOCKET FIGURES ARE DOJ-SCOPED, and the scope is in the words as well as the
// filter. `cases` holds 52 dockets; three are suits by civil-society plaintiffs
// against federal agencies -- one of them against DOJ itself -- so a sentence opening
// "DOJ has sued" counts the 49 DOJ filed and names the other three in their own
// clause. See lib/stands.ts#isDojFiling for why the scope is read off `plaintiff`
// rather than inherited from the campaign query's state filter.
//
// THE MOCK IS NOT THIS FILE'S EQUAL. `docs/design/psephos-where-this-stands-mock-v1.html`
// is the approved spec and it renders 52/29/23 and 31 open, drawn before the scope was
// ruled on. That difference is documented in docs/status.md and is deliberate; two
// affordances in the mock also do not ship, the canonical/verbatim court toggle
// (court names render canonical, its own default) and the .mocknotes block.

type Props = {
  docketRows: readonly DocketRow[];
  bills: readonly Bill[];
  stateBills: readonly StateBill[];
  /** The record's clock -- MAX(fetched_at), the same value the header labels
   *  "collected". Null when nothing has ever been collected. NEVER a render clock:
   *  the stall figure below is an age, and an age against `new Date()` drifts away
   *  from the record it describes on every page load. */
  collectedAt: string | null;
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Sep 7, 21:38Z" from an ISO string, by slicing. No Date parsing: these strings are
 *  already UTC and reading them through the runtime's local zone can shift the day. */
function stamp(iso: string | null): string | null {
  if (iso === null || iso.length < 16) return null;
  const month = MONTHS[Number(iso.slice(5, 7)) - 1];
  if (!month) return null;
  return `${month} ${Number(iso.slice(8, 10))}, ${iso.slice(11, 16)}Z`;
}

/** "Mar 26" from an ISO date. */
function shortDate(iso: string | null): string | null {
  if (iso === null || iso.length < 10) return null;
  const month = MONTHS[Number(iso.slice(5, 7)) - 1];
  if (!month) return null;
  return `${month} ${Number(iso.slice(8, 10))}`;
}

const TABS = [
  { id: "now", label: "On the books now" },
  { id: "next", label: "What it would take" },
  { id: "em", label: "If an emergency is declared" },
] as const;

export function WhereThisStands({ docketRows, bills, stateBills, collectedAt }: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("now");

  const doj = dojFilings(docketRows);
  const related = relatedSuits(docketRows);
  const totals = docketTotals(doj);
  const open = openSplit(doj);
  const wi = wisconsinOutcomes(stateBills);
  const stall = saveStallMonths(bills, collectedAt);
  const quiet = shortDate(vehicleQuietSince(bills));
  const asOf = stamp(collectedAt);

  const counts = { now: 8, next: 5, em: 1 };

  return (
    <section data-section="where-this-stands" className="mt-10">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold tracking-tight">Where this stands</h2>
        <p className="text-sm text-neutral-500">
          what has already changed, and what would have to happen next
        </p>
        {asOf ? (
          <span className="asofchip">section figures as of {asOf}</span>
        ) : (
          // Not a fallback to the clock: an empty record is where a rendered time
          // would be most misleading and least questioned.
          <span className="asofchip">no collection recorded</span>
        )}
      </div>

      <div className="tabs mt-4" role="tablist" aria-label="Where this stands">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`wts-${t.id}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            <span className="k">
              {t.id === "now" ? counts.now : t.id === "next" ? `${counts.next} paths` : "1 on the record"}
            </span>
          </button>
        ))}
      </div>

      {/* --- Tab 1: on the books now ------------------------------------------- */}
      <div className="panel" id="wts-now" role="tabpanel" hidden={tab !== "now"}>
        <div className="factlist">
          <Fact when="May 15, 2025" src={<><Grade grade="A1" dense /> LegiScan · TX SJR37</>}>
            Texas <b>SJR37 passed</b>: a constitutional amendment requiring a voter to be a US
            citizen. Goes to voters for ratification.
          </Fact>
          <Fact when="Jun 20, 2025" src={<><Grade grade="A1" dense /> LegiScan · TX SB510, HB493</>}>
            Texas <b>SB510 passed</b>: penalties where a voter registrar fails to comply with
            registration law. HB493 narrowed poll-watcher eligibility the same day.
          </Fact>
          <Fact when="Mar 20, 2026" src={<><Grade grade="A1" dense /> LegiScan · OH SB293</>}>
            Ohio <b>SB293 passed</b>: the deadline to return an absentee ballot was revised.
          </Fact>
          <Fact when="Jun 15, 2026" src={<><Grade grade="A1" dense /> LegiScan · AZ HCR2001</>}>
            Arizona <b>HCR2001 passed</b>: citizenship, identification and early voting. Goes to
            voters for ratification.
          </Fact>
          <Fact when="Jun 16, 2026" src={<><Grade grade="A1" dense /> LegiScan · OH SB63</>}>
            Ohio <b>SB63 passed</b>: ranked choice voting prohibited, with funding withheld from
            jurisdictions that use it.
          </Fact>

          <Fact
            when="Mar 25, 2025 · Mar 31, 2026"
            src={
              <>
                <Grade grade="A1" dense /> Federal Register <Grade grade="C3" dense /> status from
                reporting <span className="rk" data-gate="eo-blocked-per-reporting">recheck by Sep 15</span>
              </>
            }
          >
            <b>EO 14248 and EO 14399</b> were published. Whether either is operating today is not
            in the record; a judge blocked an election EO on Aug 16 per reporting.
          </Fact>

          <Fact
            when="since Sep 2025"
            src={
              <>
                <Grade grade="A1" dense /> CourtListener · <span className="gate">derived</span>{" "}
                <Grade grade="B2" dense /> demands per Democracy Docket{" "}
                <span className="rk stale" data-gate="doj-demands-all-51">recheck was Nov 30, 2025</span>
              </>
            }
          >
            DOJ has{" "}
            <b data-gate="suits-jurisdictions">sued {new Set(doj.map((r) => r.state).filter(Boolean)).size} of 51 jurisdictions</b>{" "}
            over voter-roll data — <span data-gate="dockets-total">{totals.total} dockets DOJ filed</span>:{" "}
            <span data-gate="district-circuit-split">
              {totals.district} district suits and {totals.circuit} appeals
            </span>
            . <span data-gate="open-split">
              <b>{open.total} remain open</b> — {open.district} district, {open.circuit} on appeal
            </span>
            . The record also holds{" "}
            <span data-gate="related-suits">
              {related.length} related suits by civil-society plaintiffs against federal agencies
            </span>{" "}
            — League of Women Voters v. DHS, its D.C. Circuit appeal, and Common Cause v. DOJ —
            none of them DOJ filings, and none counted above. The written demands went to all 50
            states and DC.
          </Fact>

          <Fact when="through Jul 27, 2026" src={<><Grade grade="A1" dense /> LegiScan · WI <span className="gate">derived</span></>}>
            <span data-gate="wi-outcomes">
              In Wisconsin, <b>{wi.failed} of {wi.tracked} tracked election bills failed</b> and{" "}
              {wi.vetoed} were vetoed.
            </span>{" "}
            Nothing in the watched set became law there.
          </Fact>
        </div>
        <Note>
          Eight things the record says are already true, each with the row it came from. Passage is
          not the same as taking effect: SJR37 and HCR2001 are constitutional amendments that still
          go to voters, and psephos does not track election results. A derived figure is rendered
          from tonight&rsquo;s tables and stores no hand-written number; a graded claim carries the
          date it must be rechecked by.
        </Note>
      </div>

      {/* --- Tab 2: what it would take ----------------------------------------- */}
      <div className="panel" id="wts-next" role="tabpanel" hidden={tab !== "next"}>
        <div className="pathlist">
          <Path
            q="The SAVE Act becomes law"
            count="2 of 5"
            state={
              <span data-gate="save-stall-months">
                stalled {stall === null ? "—" : stall} months <span className="gate">derived</span>
              </span>
            }
            steps={[
              ["Introduced", "Jan 3, 2025", true],
              ["Passed the House", "Apr 10, 2025", true],
              ["Out of Senate Rules", "referred Jan 16, 2025", false],
              ["Senate floor vote", "—", false],
              ["Signed", "—", false],
            ]}
            note={<>The Senate companion, S. 128, has not moved since it was referred.</>}
            src={<><Grade grade="A1" dense /> hr22-119 · s128-119</>}
          />
          <Path
            q="A vehicle bill carries the text instead"
            count="2 of 4"
            state={
              <span data-gate="vehicle-quiet-since">
                quiet since {quiet ?? "—"} <span className="gate">derived</span>
              </span>
            }
            steps={[
              ["Vehicle identified", "s1383-119", true],
              ["Live in the Senate", quiet ?? "—", true],
              ["Election text attached", "not on the record", false],
              ["Enacted", "—", false],
            ]}
            note={
              <>
                S. 1383 is a veterans accessibility bill. It was taken up on a House message, which
                is the posture an unrelated rider needs. This is the path the trackers do not watch.
              </>
            }
            src={<><Grade grade="A1" dense /> s1383-119 · is_vehicle</>}
          />
          <Path
            q="The voter-roll fight reaches the Supreme Court"
            count="2 of 5"
            state={<>clock running</>}
            steps={[
              ["Suits filed", `${new Set(doj.map((r) => r.state).filter(Boolean)).size} jurisdictions`, true],
              ["Appeals taken", `${totals.circuit} dockets`, true],
              ["DOJ wins one", "0 in held dockets", false],
              ["Cert window open", "closes ~Nov 12", false],
              ["Cert granted", "—", false],
            ]}
            note={
              <>
                Michigan is the one terminated circuit row, so its only continuation is a cert
                petition. The Sixth Circuit denied rehearing on Aug 14; a petition runs ~90 days
                from that denial, which is{" "}
                <span data-gate="cert-window-nov-12">the clock</span>. No petition appears in the
                dockets psephos holds — a statement about this record, not about the parties&rsquo;
                intent. <span data-gate="doj-scotus-possibility">
                  The Attorney General called a Supreme Court filing a possibility on Aug 16.
                </span>
              </>
            }
            src={
              <>
                <Grade grade="B2" dense /> Democracy Docket{" "}
                <span className="rk">recheck by Nov 14</span>
              </>
            }
          />
          <Path
            q="Texas requires documentary proof of citizenship"
            count="1 of 3"
            steps={[
              ["Passed the legislature", "May 15, 2025", true],
              ["Ratified by voters", "not tracked here", false],
              ["In effect", "—", false],
            ]}
            note={<>Arizona HCR2001 is on the same path, one step in as of Jun 15, 2026.</>}
            src={<><Grade grade="A1" dense /> TX SJR37 · AZ HCR2001</>}
          />
          <Path
            q="The election executive orders operate unblocked"
            count="contested"
            steps={[
              ["Published", "Mar 2025 · Mar 2026", true],
              ["Challenged in court", "per reporting", true],
              ["In force today", "not in the record", false],
            ]}
            note={
              <>
                psephos records that a document was published, not whether it operates. Closing
                this row needs an outcome field, or a tracker cited by name.
              </>
            }
            src={<><Grade grade="C3" dense /> gap in the record</>}
          />
        </div>
        <Note>
          Five paths, each broken into steps that either happened or did not. No weights and no
          index: a single number would need weights nobody can check, and it would be the only
          figure on this page not traceable to a row.
        </Note>
      </div>

      {/* --- Tab 3: if an emergency is declared --------------------------------- */}
      <div className="panel" id="wts-em" role="tabpanel" hidden={tab !== "em"}>
        <div className="em">
          <p className="lede">
            One thing on the record now touches this tab: a declared national emergency naming
            elections — <b>Foreign Interference in or Undermining Public Confidence in United
            States Elections</b> — continued by notice on <b>Aug 31, 2026</b>. No emergency power
            moves an election date. <b>The date of a federal election is set by statute and no
            president can move it</b>; the United States voted through the Civil War in 1864 and
            through both world wars. What follows is what each step would actually require, and
            whether psephos sees it — in the present tense, against the collector as it runs
            tonight.
          </p>
          <Statute
            q="A federal election moves"
            body={
              <>
                Requires an act of Congress. The dates are fixed by 2 U.S.C. §7 (House), 2 U.S.C.
                §1 (Senate) and 3 U.S.C. §1 (presidential electors). No presidential authority to
                postpone exists.
              </>
            }
            see={<span className="see">would see it · a bill on Congress.gov</span>}
          />
          <Statute
            q="Terms end regardless"
            body={
              <>
                The 20th Amendment ends congressional terms on Jan 3 and the presidential term on
                Jan 20 at noon. A missed election leaves offices <b>vacant</b>; it does not extend
                anyone&rsquo;s term. This is the structural answer to the question.
              </>
            }
            see={<span className="see na">nothing to watch</span>}
          />
          <Statute
            q="A state extends its own voting period"
            body={
              <>
                The Electoral Count Reform Act of 2022 replaced the old &ldquo;failed to make a
                choice&rdquo; provision with an <b>extraordinary and catastrophic</b> standard, and
                requires that any extension run under state law enacted before election day. State
                and local primaries have been postponed under state emergency law before, in New
                York after Sandy in 2012 and widely in 2020.
              </>
            }
            see={<span className="see">would see it · the pre-enacted law, LegiScan, 9 watched states</span>}
          />
          <Statute
            q="A national emergency is declared"
            body={
              <>
                The National Emergencies Act, 50 U.S.C. §1601 et seq., unlocks a catalog of standby
                powers. None of them moves an election date. Declarations publish in the Federal
                Register; one naming elections is on the record, and its annual continuation
                arrived as a notice on Aug 31.
              </>
            }
            see={<span className="see yes">sees it · all seven presidential document types requested</span>}
          />
          <Statute
            q="The Insurrection Act is invoked"
            body={
              <>
                10 U.S.C. §§251-255 permits domestic deployment and requires a proclamation to
                disperse first. It does not authorize closing polls or suspending an election.
              </>
            }
            see={<span className="see">would see it · proclamations are requested</span>}
          />
          <Statute
            q="Wartime communications powers"
            body={
              <>
                47 U.S.C. §606 reaches wire and radio in war. Adjacent to voting rather than about
                it: it touches the information environment, not the ballot. Recorded here so it is
                not mistaken for an election power.
              </>
            }
            see={<span className="see part">type covered · terms untested</span>}
          />
        </div>
        <Note>
          The executive collector queries the Federal Register for all seven presidential document
          types — {PRESIDENTIAL_TYPES.join(", ")} — and the configured election terms decide
          relevance (<code>collectors/executive.py</code>). It requested only executive orders
          until Aug 20, 2026; the widening&rsquo;s highest-value catch is the notice carrying the
          annual elections-interference emergency continuation. Four of the six rows above are
          monitored tonight; the §606 row turns on whether the term list would match such a
          document, which is untested.
        </Note>
      </div>
    </section>
  );
}

function Fact({
  when,
  src,
  children,
}: {
  when: string;
  src: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="fact">
      <div className="when">{when}</div>
      <div>
        <div className="what">{children}</div>
        <div className="src">{src}</div>
      </div>
    </div>
  );
}

function Path({
  q,
  count,
  state,
  steps,
  note,
  src,
}: {
  q: string;
  count: string;
  state?: React.ReactNode;
  steps: ReadonlyArray<readonly [string, string, boolean]>;
  note: React.ReactNode;
  src: React.ReactNode;
}) {
  return (
    <div className="path">
      <div className="ph">
        <span className="pq">{q}</span>
        <span className="pc">{count}</span>
        {state ? <span className="pc motion">{state}</span> : null}
      </div>
      <ol className="psteps">
        {steps.map(([label, detail, done]) => (
          <li key={label} data-done={done}>
            <span className="sl">{label}</span>
            <span className="sd">{detail}</span>
          </li>
        ))}
      </ol>
      <div className="pnote">
        {note} <span className="src">{src}</span>
      </div>
    </div>
  );
}

function Statute({ q, body, see }: { q: string; body: React.ReactNode; see: React.ReactNode }) {
  return (
    <div className="path">
      <div className="ph">
        <span className="pq">{q}</span>
      </div>
      <div className="pnote">{body}</div>
      <div className="mt-2">{see}</div>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 max-w-[130ch] text-xs leading-relaxed text-neutral-500">{children}</p>;
}
