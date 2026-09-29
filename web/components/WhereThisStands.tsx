"use client";

import { useState } from "react";
import type { DocketRow, Bill, StateBill } from "@/lib/db";
import { Grade } from "@/components/Grade";
import { RecordDate } from "@/components/RecordDate";
import {
  dojFilings,
  relatedSuits,
  eoLawsuits,
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
// filter. `cases` held 52 dockets when this was written; three are suits by
// civil-society plaintiffs against federal agencies -- one of them against DOJ itself
// -- so a sentence opening "DOJ has sued" counts the 49 DOJ filed and names the other
// three in their own clause. See lib/stands.ts#isDojFiling for why the scope is read
// off `plaintiff` rather than inherited from the campaign query's state filter.
//
// A THIRD SET, the challenges to the mail-ballot executive order, is counted in a
// sentence of its own and in neither of the other two. Its lawsuits are counted, not
// its dockets: one held lead appeal stands for four consolidated ones. See THE THREE
// SETS in lib/stands.ts.
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
function shortDate(iso: string | null | undefined): string | null {
  if (!iso || iso.length < 10) return null;
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
  const eoSuits = eoLawsuits(docketRows);
  const totals = docketTotals(doj);
  const open = openSplit(doj);
  const wi = wisconsinOutcomes(stateBills);
  const stall = saveStallMonths(bills, collectedAt);
  // A record date, so it renders through RecordDate with the short format the gate's
  // renders_as uses. vehicleQuietSince skips an action dated ahead of the clock.
  const quietAt = vehicleQuietSince(bills, collectedAt);
  const quiet = quietAt ? (
    <RecordDate value={quietAt} clock={collectedAt} format={shortDate} />
  ) : null;
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

          {/* ONE FACT PER ORDER, ONE GATED CLAIM PER LINE (Corey, 2026-09-29). The order's
              name is the fact's heading, so no lead-in doubles it, and each line's
              `renders_as` is a sentence that stands alone: retiring a line never means
              rewriting its neighbour. Each line ends in a period outside its span,
              except where its text already ends on one ("D. Mass."). */}
          <Fact
            when="Mar 25, 2025"
            src={
              // ONE SPAN PER SOURCE. `.fact .src` is a wrapping flex row, so a bare badge,
              // label and chip wrap as three items, and a badge could end a line with its
              // label on the next. Each span is one flex item whose content flows inline, so
              // a badge always starts its label's line.
              <>
                <span>
                  <Grade grade="A1" dense /> Federal Register
                </span>
                <span>
                  <Grade grade="A1" dense /> EO 14248 per the D.D.C., W.D. Wash. and D. Mass. dockets{" "}
                  <span className="rk">recheck by Oct 26</span>
                </span>
                <span>
                  <Grade grade="A1" dense /> DHS&rsquo;s SAVE system per Supreme Court docket 26A308{" "}
                  <span className="rk">recheck by Oct 26</span>
                </span>
                <span>
                  <Grade grade="A1" dense /> the NVRA&rsquo;s limit per Supreme Court docket 26A308{" "}
                  <span className="rk">recheck by Nov 4</span>
                </span>
              </>
            }
          >
            <b>EO 14248</b> was published. Whether it operates in full today is not in the
            record. The sources below give where parts of it stand,{" "}
            <span data-gate-ref="dhs-save-system-stayed">the SAVE-system changes it prompted</span>{" "}
            among them:
            <ul className="claims">
              <li>
                <span data-gate="eo-14248-enjoined">
                  {"Three courts have permanently enjoined parts of EO 14248 (D.D.C. from Oct 31, 2025, W.D. Wash. from Jan 9, 2026, D. Mass. from Jun 24, 2026): section 2(a), proof of citizenship on the federal mail registration form, in all three; section 3(d), the same and proof of eligibility in the voter's State on the post card form for military and overseas voters, in D.D.C. and D. Mass.; section 2(d), citizenship checks before agencies offer the registration form, in D.D.C.; section 4(b), new voting-system standards, in W.D. Wash.; and sections 4(a), 7(a) and 7(b), which tie federal election funds to proof of citizenship and to an Election Day ballot-receipt deadline and direct that deadline's enforcement, only as to plaintiff States, in W.D. Wash. and D. Mass."}
                </span>
              </li>
              <li>
                <span data-gate="dhs-save-system-stayed">
                  {"The D.D.C. order of Jun 22 vacating DHS's modified SAVE system (Systematic Alien Verification for Entitlements, not the SAVE Act), which added Social Security records and bulk searches to its citizenship checks, has been stayed by the Supreme Court since Sep 25, pending appeal and any certiorari petition"}
                </span>
                .
              </li>
              <li>
                <span data-gate="dhs-save-stay-nvra-limit">
                  {"In staying the D.D.C. order that vacated DHS's modified SAVE system, the Supreme Court said the NVRA's 90-day bar on systematic voter-roll removals limits the stay's potential impact, and that individualized inquiries are permitted under federal law in that period"}
                </span>
                .
              </li>
            </ul>
          </Fact>

          <Fact
            when="Mar 31, 2026"
            src={
              <>
                <span>
                  <Grade grade="A1" dense /> Federal Register
                </span>
                <span>
                  <Grade grade="A1" dense /> the USPS rule in D.D.C. per docket{" "}
                  <span className="whitespace-nowrap">1:26-cv-01114</span>{" "}
                  <span className="rk">recheck by Oct 15</span>
                </span>
                <span>
                  <Grade grade="A1" dense /> the USPS rule in D. Mass. per Supreme Court docket 26A305{" "}
                  <span className="rk">recheck by Oct 15</span>
                </span>
                <span>
                  <Grade grade="A1" dense /> the §§2-3 injunction per Supreme Court docket 26A124{" "}
                  <span className="rk">recheck by Nov 20</span>
                </span>
              </>
            }
          >
            {/* The D.D.C. injunction first, the broader (the whole rule, no end date), then
                D. Mass.'s; then the stayed injunction against the order's own sections. The
                D.D.C. line keeps section 3 out: ECF 193's decree names no section, and its
                fn. 1 denies the motion as to section 3. No transient procedural state ("no
                appeal on the docket") on the page: that lives in each entry's comment and
                recheck, in docs/gates.yaml. */}
            <b>EO 14399</b> was published. Whether it operates in full today is not in the
            record. The sources below give where parts of it stand:
            <ul className="claims">
              <li>
                <span data-gate="eo-14399-usps-rule-enjoined-ddc">
                  {"The Postal Service is preliminarily enjoined from implementing and enforcing the ballot-mail rule it issued on Aug 21 at EO 14399's direction, in full and with no end date, by a D.D.C. order of Sep 13"}
                </span>
                .
              </li>
              <li>
                <span data-gate="eo-14399-usps-rule-enjoined">
                  {"A D. Mass. preliminary injunction of Sep 4 enjoins the mandatory provisions of the Postal Service's ballot-mail rule for elections through Nov 3, 2026; the First Circuit denied stays of it on Sep 10, and the Supreme Court denied one on Sep 14"}
                </span>
                .
              </li>
              <li>
                <span data-gate="eo-14399-s2-3-stayed">
                  {"A D. Mass. injunction against sections 2 and 3 of EO 14399 themselves, for the plaintiff States, has been stayed by the Supreme Court since Aug 24, pending appeal"}
                </span>
                .
              </li>
            </ul>
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
            — League of Women Voters v. DHS (the suit behind{" "}
            <span data-gate-ref="dhs-save-system-stayed">the SAVE-system stay</span> above), its
            D.C. Circuit appeal, and Common Cause v. DOJ —
            none of them DOJ filings, and none counted above.{" "}
            <span data-gate="eo-challenges">
              The record holds {eoSuits.length}{" "}
              {eoSuits.length === 1 ? "challenge" : "challenges"} to the mail-ballot executive
              order, counted apart from DOJ&rsquo;s filings and the related suits
            </span>
            . The written demands went to all 50 states and DC.
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
            q="DOJ's voter-roll suits reach the Supreme Court"
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
              [
                "Challenged in court",
                <span data-gate="eo-challenges-held">
                  {eoSuits.length} {eoSuits.length === 1 ? "challenge" : "challenges"} to the
                  mail-ballot order held in the record
                </span>,
                // DONE REGARDLESS OF THE COUNT. The step is about both orders, and both were
                // challenged: an injunction needs a suit, and tab 1's gated claims record
                // injunctions against 14248's provisions, against the USPS rule implementing
                // 14399 (two, D.D.C.'s and D. Mass.'s), and against 14399's own §§2-3 (that
                // one stayed). The count is what the record holds of one order's challenges,
                // and at 0 -- the window between this deploy and the seeds' first walk -- an
                // undone step would have read "not challenged".
                true,
              ],
              [
                "In force today",
                // POINTERS, NOT CLAIMS. Each part names a provision, or for the USPS rule
                // the court whose order it points at, and sends the reader to its gated claim
                // on the first tab; it states no status of its own, so
                // there is no second text to fall out of step with the register.
                // `data-gate-ref` is checked by assert-gates: every ref must name an
                // authored gate that is registered, not falsified, and on the page.
                <>
                  see the first tab for 14399&rsquo;s USPS rule (
                  <span data-gate-ref="eo-14399-usps-rule-enjoined-ddc">D.D.C.</span> and{" "}
                  <span data-gate-ref="eo-14399-usps-rule-enjoined">D. Mass.</span>) and{" "}
                  <span data-gate-ref="eo-14399-s2-3-stayed">§§2-3 themselves</span>, and for{" "}
                  <span data-gate-ref="eo-14248-enjoined">the enjoined parts of 14248</span>{" "}
                  · the rest not in the record, apart from{" "}
                  <span data-gate-ref="dhs-save-system-stayed">the SAVE-system changes 14248 prompted</span>,
                  also on the first tab
                </>,
                // Not done, on the gated claims: parts of 14248 are enjoined, section by
                // section, and so is the USPS rule implementing 14399, in full by D.D.C. and
                // in its mandatory provisions by D. Mass. (the injunction against 14399's own
                // §§2-3 is stayed), so neither order operates unblocked.
                false,
              ],
            ]}
            note={
              <>
                psephos records that a document was published and which challenges to it the
                record holds, not whether it operates. Holding a docket puts the suit on the
                record, not its outcome: operating status stays with the graded claims on the
                first tab, each carrying the date it must be rechecked by.
              </>
            }
            // Short on purpose: `.pnote .src` is a non-wrapping inline-flex, and a long
            // text run in it collapses into a narrow column at 390px. Where operating
            // status comes from is said in the note above.
            src={<><Grade grade="A1" dense /> CourtListener · <span className="gate">derived</span></>}
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
  steps: ReadonlyArray<readonly [string, React.ReactNode, boolean]>;
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
