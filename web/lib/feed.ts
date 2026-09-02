// Merged cross-channel activity feed -- move 2 of the dashboard redesign. Pure
// functions only (no database client, no next/cache) so the ordering, the cap and
// the cross-link resolution test without standing either up. Same split as
// lib/activity.ts, for the same reason.

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

// A cap, and the count it hides, always rendered together. The standing rule is
// that a workflow bounding its coverage says what it dropped -- a silent top-N
// reads as "this is everything" when it is not.
//
// IT COUNTS CARDS, NOT ENTRIES, and that change is the whole point of grouping.
// Measured 2026-08-16: four dockets were seeded and walked in one run, so the 24h
// window held 192 entries of which 174 were four dockets' back-history. At 50
// ENTRIES the cap cut inside the litigation block and hid 7 news items collected in
// the same window -- the cap was deciding what a reader could reach, on an axis
// (row count) that had nothing to do with what mattered. The same window is 22
// cards, so the cap stops binding at all and the seed day renders whole.
export const FEED_LIMIT = 50;

// Older than the strip's own week AT THE MOMENT IT WAS FETCHED. Tied to
// WINDOW_DAYS.week deliberately rather than given its own number: "older than the
// 7d cell directly above this feed" is a definition a reader can check against the
// page, and it is not a threshold pulled from the air.
export const HISTORY_AFTER_DAYS = WINDOW_DAYS.week;

// Ordering, stated once. `fetched_at DESC, id DESC`.
//
// THE WINDOW AND THE ORDER SHARE A COLUMN DELIBERATELY. Order on anything else --
// occurred_at being the obvious candidate -- and an item enters the list in the
// middle as it ages into the window, because RSS routinely carries publication
// dates days behind collection. A reader watching the top of the feed would never
// see it arrive. Keying both on fetched_at means new entries always appear at the
// top and leave from the bottom, which is the only behaviour a feed can be read
// as having. Each entry still DISPLAYS its own occurred_at, so a backdated story
// is legible as backdated rather than silently re-dated.
//
// `id DESC` is the tiebreak, and it is load-bearing rather than cosmetic: a
// collector run writes many rows inside the same second, so fetched_at alone
// leaves within-batch order to whatever the engine returns. Same reason
// export.snapshots sorts on the (occurred_at, id) pair rather than on the
// timestamp alone.
export function compareEntries(a: FeedEntry, b: FeedEntry): number {
  if (a.fetched_at !== b.fetched_at) return a.fetched_at < b.fetched_at ? 1 : -1;
  return b.id - a.id;
}

export type AnchorKind = "case" | "bill" | "state";

// One card: either a single unanchored entry, or every entry in the window that
// shares an anchor. A docket walk arrives as one card saying how many entries and
// over what dates, instead of 55 rows each repeating the same caption.
export type FeedCard = {
  key: string; // `case:<id>` | `bill:<id>` | `state:<id>` | `item:<id>`
  anchor: AnchorKind | null;
  entries: FeedEntry[]; // >= 1, in compareEntries order
  newest_fetched_at: string; // the ordering key, from entries[0]
  newest_id: number; // the tiebreak, from entries[0]
  first_occurred_at: string | null;
  last_occurred_at: string | null;
  history: boolean;
  grades: string[]; // distinct `${source}${info}`, in first-seen order
};

export type Feed = {
  cards: FeedCard[];
  total_cards: number;
  total_entries: number;
  truncated: boolean;
};

// The anchor an entry groups on, checked in the SAME order entryLink uses so a card
// can never group on one anchor and link to another. At most one is returned.
function anchorOf(e: FeedEntry): { kind: AnchorKind; id: string } | null {
  if (e.bill_id) return { kind: "bill", id: e.bill_id };
  if (e.case_id) return { kind: "case", id: e.case_id };
  if (e.state_bill_id) return { kind: "state", id: e.state_bill_id };
  return null;
}

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

// Group into cards, sort, and cap. `total_entries` is the pre-cap ENTRY count and
// `total_cards` the pre-cap CARD count; the page renders both, because after
// grouping neither one alone says what the window held.
//
// Only entries INSIDE the window group, since the window is what the query returns.
// A docket with one entry in the window is therefore a card of one, and reads as
// that one entry -- which is correct: nothing else about it moved today.
export function buildFeed(rows: FeedEntry[], limit: number = FEED_LIMIT): Feed {
  const sorted = [...rows].sort(compareEntries);

  // Insertion order over `sorted` is already card order: a card's newest entry is
  // the first one seen for that key, so the Map preserves the ordering the
  // comparator gives. It is still sorted explicitly below -- see there.
  const groups = new Map<string, { anchor: AnchorKind | null; entries: FeedEntry[] }>();
  for (const e of sorted) {
    const a = anchorOf(e);
    const key = a ? `${a.kind}:${a.id}` : `item:${e.id}`;
    const g = groups.get(key);
    if (g) g.entries.push(e);
    else groups.set(key, { anchor: a?.kind ?? null, entries: [e] });
  }

  const cards: FeedCard[] = [...groups].map(([key, g]) => {
    const dates = g.entries
      .map((e) => e.occurred_at)
      .filter((d): d is string => !!d)
      .sort();
    const grades: string[] = [];
    for (const e of g.entries) {
      const grade = `${e.admiralty_source}${e.admiralty_info}`;
      if (!grades.includes(grade)) grades.push(grade);
    }
    return {
      key,
      anchor: g.anchor,
      entries: g.entries,
      newest_fetched_at: g.entries[0].fetched_at,
      newest_id: g.entries[0].id,
      first_occurred_at: dates[0] ?? null,
      last_occurred_at: dates[dates.length - 1] ?? null,
      // A card is history only when EVERY entry is. A docket that was walked and
      // then moved today is not history, and its date range shows the mix.
      history: g.entries.every(isHistoryEntry),
      grades,
    };
  });

  // Cards order by their NEWEST entry, which keeps the contract stated above one
  // level up: a card arrives at the top and leaves from the bottom, because it is
  // keyed on the same column as the window. A card whose oldest entry is the oldest
  // thing in the window still sorts by when it was last collected.
  cards.sort((a, b) => {
    if (a.newest_fetched_at !== b.newest_fetched_at) {
      return a.newest_fetched_at < b.newest_fetched_at ? 1 : -1;
    }
    return b.newest_id - a.newest_id;
  });

  return {
    cards: cards.slice(0, limit),
    total_cards: cards.length,
    total_entries: sorted.length,
    truncated: cards.length > limit,
  };
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

// A group card links to its anchor by the same function applied to its first entry,
// so the card header and a singleton row can never resolve to different places.
export function cardLink(card: FeedCard): { href: string; label: string } | null {
  return entryLink(card.entries[0]);
}

// The dimension row for a card's header. Read off the first entry for the same
// reason cardLink is: every entry on a card shares the anchor it grouped on, so
// they all carry the same joined row and the first is as good as any.
export function cardAnchor(card: FeedCard): FeedAnchor | null {
  return card.entries[0].anchor ?? null;
}
