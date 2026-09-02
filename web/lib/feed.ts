// The feed module: the entry and anchor types the whole read layer passes around, the
// window and history thresholds, and the cross-link resolution. Pure functions only
// (no database client, no next/cache), same split as lib/activity.ts.
//
// IT USED TO CARRY A CARD LAYER AND NO LONGER DOES. buildFeed, the cap, the anchor
// grouping and their types existed for ActivityFeed -- move 2's homepage feed -- which
// was replaced by the day-grouped timeline in 4703298, left mounted by nothing for
// months, and deleted. The live path is getFeed -> buildTimeline -> DayTimeline, and it
// imports none of what was removed.
//
// The contracts were re-homed rather than dropped: lib/timeline.ts owns the ordering
// and the grouping the page actually uses, and timeline.test.ts pins them -- including
// the grade-before-recency fold that keeps C3 items reachable, which is move 2's own
// decision and was the one thing the deleted tests carried that was not mechanical.

import { WINDOW_DAYS } from "@/lib/activity";
import { daysBetween } from "@/lib/format";
import { billLabel } from "@/lib/bill";
import { stateBillLabel } from "@/lib/statebill";

// A docket this case continues into, or continues from. Court + docket only --
// enough to render the chain line, and deliberately no timeline, which is the same
// split lib/db.ts:CaseRef already makes for the case detail page.
export type ChainRef = {
  case_id: string;
  court: string | null;
  docket_number: string | null;
};

// The dimension row an entry hangs off, carried so a card can put a real header on
// a group instead of repeating one entry's title. Discriminated on `kind`, which is
// the same three-way distinction entryLink and anchorOf make.
export type FeedAnchor =
  | {
      kind: "case";
      id: string;
      caption: string;
      court: string | null;
      docket_number: string | null;
      status: string | null;
      successor: ChainRef | null;
      predecessor: ChainRef | null;
    }
  | {
      kind: "bill";
      id: string;
      bill_type: string;
      number: number;
      short_title: string | null;
      title: string | null;
      is_vehicle: number;
    }
  | {
      kind: "state";
      id: string;
      state: string;
      bill_number: string;
      title: string | null;
    };

export type FeedEntry = {
  id: number;
  channel: string;
  title: string;
  // The bare docket text. collectors/litigation.py writes
  // `title = f"{caption}: {desc[:180]}"` and `summary = desc`, so a card that
  // already names the case in its header renders the summary and drops the
  // caption prefix without parsing anything back out of the title.
  summary: string | null;
  source_url: string;
  source_id: string;
  occurred_at: string | null;
  fetched_at: string;
  admiralty_source: string;
  admiralty_info: string;
  bill_id: string | null;
  case_id: string | null;
  state_bill_id: string | null;
  // OPTIONAL, because it is a joined row rather than a column of `items`: the pure
  // functions here group and order without it, and the tests construct entries that
  // have none. getFeed always sets it (null when the entry is unanchored).
  anchor?: FeedAnchor | null;
};

// The homepage shows one window. 24h, not 7d: measured 2026-08-14 the 7d window
// holds 260 entries against 24h's 29, and a 260-entry list below the fold is an
// archive, not an activity feed. /news remains the place to read the whole B2 set.
export const FEED_WINDOW: "day" | "week" = "day";

// Older than the strip's own week AT THE MOMENT IT WAS FETCHED. Tied to
// WINDOW_DAYS.week deliberately rather than given its own number: "older than the
// 7d cell directly above this feed" is a definition a reader can check against the
// page, and it is not a threshold pulled from the air.
export const HISTORY_AFTER_DAYS = WINDOW_DAYS.week;

// Was this entry already old when it was collected? The docket-walk signature: a
// bootstrap poll writes an entire docket's history in one run, so every row lands
// with a fetched_at of today and an occurred_at of months ago.
//
// A NULL occurred_at is NOT history. 41 litigation rows carry no date at all, and
// an unknown date is not evidence of an old one -- the same rule the SQL takes,
// where NULL arithmetic yields NULL and the SUM does not count it.
export function isHistoryEntry(e: FeedEntry): boolean {
  const lag = daysBetween(e.occurred_at, e.fetched_at);
  return lag !== null && lag > HISTORY_AFTER_DAYS;
}

// THE ONE PLACE AN ANCHOR IS TURNED INTO A NAME. Two callers, and they used to be
// two implementations: entryLink built a label inline while DayTimeline's docket
// header hardcoded `case ${caseId}` and never called entryLink at all. That second
// one is the copy a reader actually met on the homepage, and its own type docstring
// says the row is "the caption once, the entry text beneath" -- so the caption was
// always the intent and the id was what shipped. Extracting the function is what
// makes that divergence impossible rather than merely fixed twice.
//
// IT WAS AN ID ON ALL THREE ARMS, not just the reported one. Every arm returned the
// raw key: `s1383-119`, `case 71452580`, `1890243`. The anchor hanging off the entry
// already carried what each display helper needs, so this was reading past the answer
// rather than lacking it -- and `AnchorHeader` renders those same helpers on a group
// card, which left the page naming one case two ways depending on whether its window
// happened to hold one entry or several.
//
// THE CASE ARM GOT NOTICED AND THE OTHER TWO DID NOT, which is the part worth
// keeping. Two hand-seeded rows key on slugs, so the feed could print `case
// united-states-v-minnesota` -- visibly wrong. `1890243` is a bare LegiScan id and
// strictly less legible, and it drew no complaint because a number reads as though
// somebody chose it. Legibility of the symptom is not severity of the defect.
//
// Returns null rather than a fallback, so each caller states its OWN fallback where
// the reader can see it: the two are not the same string, and a shared default would
// have to pick one and be wrong at the other site.
export function anchorLabel(a: FeedAnchor | null | undefined): string | null {
  if (!a) return null;
  if (a.kind === "bill") return billLabel(a);
  if (a.kind === "case") return a.caption;
  return stateBillLabel(a);
}

// The cross-channel link, which is most of why the feed is worth building: an
// entry that belongs to a bill, a case or a state bill says so and goes there.
// Checked in that order and at most one is returned -- items carry at most one
// anchor today (measured 2026-08-13: zero items carry both a bill_id and a
// case_id), and if that ever stops being true the first match is still a link
// to somewhere real rather than a rendering decision made at random.
//
// FALLING BACK TO THE ID IS REAL, NOT DEFENSIVE. `anchor` is optional -- the pure
// tests construct entries without one -- and `getFeed` builds a case anchor only
// when the joined caption is non-null, so an entry can arrive carrying an id and
// no dimension row behind it. The id is then the only true thing left to print.
export function entryLink(e: FeedEntry): { href: string; label: string } | null {
  const named = anchorLabel(e.anchor);
  // Each arm takes the name only when the anchor is the MATCHING kind. An entry
  // carrying two ids would otherwise label a bill link with a case caption, which is
  // worse than the id it replaced -- a wrong name reads as authoritative.
  const a = e.anchor;
  if (e.bill_id) {
    return { href: `/bill/${e.bill_id}`, label: a?.kind === "bill" ? named! : e.bill_id };
  }
  if (e.case_id) {
    // No `case ` prefix once a caption is available: the caption already reads as a
    // case name. The prefix stays on the fallback, where the bare key would
    // otherwise be an unexplained number sitting beside a headline.
    const label = a?.kind === "case" ? named! : `case ${e.case_id}`;
    return { href: `/case/${e.case_id}`, label };
  }
  if (e.state_bill_id) {
    const label = a?.kind === "state" ? named! : e.state_bill_id;
    return { href: `/state-bill/${e.state_bill_id}`, label };
  }
  return null;
}
