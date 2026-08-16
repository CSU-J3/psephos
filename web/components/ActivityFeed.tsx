import Link from "next/link";
import { Grade } from "@/components/Grade";
import {
  buildFeed,
  cardAnchor,
  cardLink,
  entryLink,
  HISTORY_AFTER_DAYS,
  type FeedAnchor,
  type FeedCard,
  type FeedEntry,
} from "@/lib/feed";
import { formatDate } from "@/lib/format";
import { billLabel } from "@/lib/bill";
import { stateBillLabel } from "@/lib/statebill";

// Move 2: one reverse-chronological list across all five channels, each entry
// carrying its channel and its Admiralty grade. This is the redesign's answer to
// "what changed", where the strip above answers "how much".
//
// EVERY GRADE APPEARS HERE, including C3. That is what makes the badge worth
// rendering -- a feed filtered to one grade stamps an identical badge on every
// row, which is decoration rather than information. It also keeps this list
// consistent with the strip directly above it, which counts all grades: a
// B2-only feed would show 4 news entries under a strip reading 26.
//
// The channel tag is deliberately plain text rather than a second coloured
// badge. The grade already carries the only colour in the row, and two competing
// accents per line is the clutter the redesign block was written against.
const CHANNEL_LABEL: Record<string, string> = {
  legislation: "legislation",
  executive: "executive",
  litigation: "litigation",
  news: "news",
  state: "state",
};

const CARD = "rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 transition-colors hover:border-neutral-700";
const META = "mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500";

// ONE STRING, ON EVERY HISTORY TAG, GROUP OR SINGLETON. The tag is a claim about
// entries, and it means the same thing on a 55-entry docket walk as on one
// backdated news item, so it must not read as two different claims depending on
// which card it lands on. The threshold is interpolated rather than written as "7"
// so this cannot drift from the constant the classifier and the strip already share.
const HISTORY_TITLE =
  `Every entry here is dated more than ${HISTORY_AFTER_DAYS} days before psephos collected it.`;

// NEUTRAL, NO VALENCE -- the same rule the strip's deltas follow. This says which
// KIND of collection produced the card, not that anything is wrong. A docket loaded
// in one run, or a story published months before the aggregator surfaced it, is a
// correct reading of a real event; it is simply not news from today.
function HistoryTag() {
  return (
    <span
      title={HISTORY_TITLE}
      className="rounded border border-neutral-700 bg-neutral-800 px-1.5 py-0.5 text-neutral-400"
    >
      history
    </span>
  );
}

// A card's date span, or a single date when every entry shares one, or nothing at
// all when no entry carries a date. Litigation rows can have a NULL occurred_at.
function dateRange(card: FeedCard): string | null {
  if (!card.first_occurred_at || !card.last_occurred_at) return null;
  const first = formatDate(card.first_occurred_at);
  const last = formatDate(card.last_occurred_at);
  return first === last ? first : `${first} – ${last}`;
}

// "55 docket entries" reads as what a docket walk is; "55 items" does not. Every
// other channel gets the generic word. Groups are always >= 2, so no singular form.
function countLabel(card: FeedCard): string {
  const noun = card.entries[0].channel === "litigation" ? "docket entries" : "items";
  return `${card.entries.length} ${noun}`;
}

// The header for a group: the DIMENSION's own words, not the first entry's title.
// Unifies the caption spelling as a side effect -- litigation items carry the seed
// spelling ("United States of America v. State of Oregon, et al.") in every title,
// while cases.caption reads "United States v. State of Oregon". One header keyed on
// the case row means the page says it one way.
function AnchorHeader({ anchor }: { anchor: FeedAnchor }) {
  if (anchor.kind === "case") {
    return (
      <>
        <span className="font-medium text-neutral-100">{anchor.caption}</span>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-neutral-400">
          {anchor.court && <span>{anchor.court}</span>}
          {anchor.docket_number && (
            <span className="font-mono">{anchor.docket_number}</span>
          )}
          {anchor.status && <span className="text-neutral-500">{anchor.status}</span>}
        </div>
      </>
    );
  }
  if (anchor.kind === "bill") {
    return (
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="font-mono text-sm text-neutral-400">{billLabel(anchor)}</span>
          <span className="ml-2 font-medium text-neutral-100">
            {anchor.short_title ?? anchor.title ?? anchor.id}
          </span>
        </div>
        {/* Same markup as BillRow: the vehicle flag is the whole point of the
            project and must look identical wherever it appears. */}
        {anchor.is_vehicle === 1 && (
          <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-400">
            Vehicle
          </span>
        )}
      </div>
    );
  }
  return (
    <div className="min-w-0">
      <span className="font-mono text-sm text-neutral-400">{stateBillLabel(anchor)}</span>
      {anchor.title && (
        <span className="ml-2 font-medium text-neutral-100">{anchor.title}</span>
      )}
    </div>
  );
}

// The supersession link, in whichever direction the record holds it. Both can be
// present at once -- a circuit docket that was appealed from a district and then
// itself continued is a middle link -- so neither is an `else`. Same two sentences
// the case detail page renders, moved up to where the reader meets the docket.
function ChainLine({ anchor }: { anchor: FeedAnchor }) {
  if (anchor.kind !== "case") return null;
  const { successor, predecessor } = anchor;
  if (!successor && !predecessor) return null;
  return (
    <div className="mt-1.5 flex flex-col gap-0.5 text-xs">
      {successor && (
        <Link
          href={`/case/${successor.case_id}`}
          className="text-sky-400/90 hover:underline"
        >
          → continued as {successor.court} {successor.docket_number}
        </Link>
      )}
      {predecessor && (
        <Link
          href={`/case/${predecessor.case_id}`}
          className="text-sky-400/90 hover:underline"
        >
          ← continues {predecessor.court} {predecessor.docket_number}
        </Link>
      )}
    </div>
  );
}

// One unanchored entry, or one anchored entry that is the only thing its dimension
// did in the window.
//
// IT CARRIES THE HISTORY TAG TOO, and the reason is a number the reader could not
// otherwise check. `history` was always computed on every card, but only groups
// rendered it -- so on 2026-08-16 the strip read `news ... 11 history` while not one
// news row said which 11 it meant. A count the page cannot be reconciled against is
// exactly the number a reader stops on. The tag sits beside the entry's own date,
// which is the field it is a claim about.
function SingletonRow({ e, history }: { e: FeedEntry; history: boolean }) {
  const link = entryLink(e);
  return (
    <li className={CARD}>
      <a
        href={e.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm font-medium text-neutral-100 hover:underline"
      >
        {e.title}
      </a>
      <div className={META}>
        <span className="uppercase tracking-wide text-neutral-400">
          {CHANNEL_LABEL[e.channel] ?? e.channel}
        </span>
        {/* The entry's OWN occurred_at, not the fetched_at the list is
            ordered by. A backdated RSS item sorts to the top as newly
            collected and still reads as the older story it is. */}
        <span className="tabular-nums">{formatDate(e.occurred_at)}</span>
        {history && <HistoryTag />}
        <span>{e.source_id}</span>
        <Grade grade={`${e.admiralty_source}${e.admiralty_info}`} />
        {link && (
          <Link href={link.href} className="text-neutral-400 hover:underline">
            {link.label} →
          </Link>
        )}
      </div>
    </li>
  );
}

// Every entry in the window that shares an anchor, as ONE object.
//
// This is what the 2026-08-16 seed day needed and did not have: 174 of that
// window's 192 entries were four dockets being walked end to end, rendered as 174
// near-identical rows each repeating its caption, with the 50-row cap cutting
// through the middle of them. One card per docket says the same thing in four
// lines and leaves the rest of the window reachable.
function GroupCard({ card }: { card: FeedCard }) {
  const anchor = cardAnchor(card);
  const link = cardLink(card);
  const newest = card.entries[0];
  const range = dateRange(card);
  // The bare docket text. litigation.py stores the caption-prefixed string in
  // `title` and the plain entry text in `summary`, and the header above already
  // names the case -- so the prefix would be read twice on every card.
  const text = newest.channel === "litigation" ? (newest.summary ?? newest.title) : newest.title;

  return (
    <li className={CARD}>
      {anchor ? (
        <AnchorHeader anchor={anchor} />
      ) : (
        // An anchor id with no dimension row behind it. Not expected; the card still
        // renders rather than disappearing, and says what it is keyed on.
        <span className="font-medium text-neutral-100">{link?.label ?? card.key}</span>
      )}

      {anchor && <ChainLine anchor={anchor} />}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="font-medium tabular-nums text-neutral-300">
          {countLabel(card)}
        </span>
        {range && <span className="tabular-nums text-neutral-500">{range}</span>}
        {card.history && <HistoryTag />}
      </div>

      {card.history && (
        <p className="mt-1 text-xs text-neutral-600">
          Docket loaded; nothing dated in the last {HISTORY_AFTER_DAYS} days.
        </p>
      )}

      <a
        href={newest.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-2 block truncate text-sm text-neutral-300 hover:underline"
        title={text}
      >
        {text}
      </a>

      <div className={META}>
        <span className="uppercase tracking-wide text-neutral-400">
          {CHANNEL_LABEL[newest.channel] ?? newest.channel}
        </span>
        {/* Distinct grades, so a docket carrying A1 court records and the B2
            tracker line badges both -- and 55 A1 entries badge A1 once. */}
        {card.grades.map((g) => (
          <Grade key={g} grade={g} />
        ))}
        {link && (
          <Link href={link.href} className="text-neutral-400 hover:underline">
            {link.label} →
          </Link>
        )}
      </div>
    </li>
  );
}

export function ActivityFeed({ rows }: { rows: FeedEntry[] }) {
  const { cards, total_cards, total_entries, truncated } = buildFeed(rows);

  if (cards.length === 0) {
    // A quiet window is a reading, not an error. Three of five channels collected
    // nothing in 24h when this was built, so an empty feed is reachable and must
    // say which window it is empty for.
    return (
      <p className="text-sm text-neutral-500">
        Nothing collected in the last 24 hours.
      </p>
    );
  }

  return (
    <>
      <ul className="space-y-2">
        {cards.map((card) =>
          card.entries.length === 1 ? (
            <SingletonRow key={card.key} e={card.entries[0]} history={card.history} />
          ) : (
            <GroupCard key={card.key} card={card} />
          ),
        )}
      </ul>
      {/* BOTH NUMBERS, ALWAYS. After grouping, neither one alone describes the
          window: 22 cards hides that 192 things were collected, and 192 entries
          hides that they were 22 subjects. The standing rule that a bounded list
          says what it bounded now has two numbers to say, and the untruncated
          branch says them too -- which on the seed day is the branch that renders,
          since 22 cards no longer reach the cap that 192 entries did. */}
      <p className="mt-3 text-xs text-neutral-500">
        {truncated ? (
          <>
            Showing {cards.length} of {total_cards} cards ({total_entries} entries)
            collected in the last 24 hours.{" "}
            <Link href="/news" className="text-neutral-400 hover:underline">
              The full B2 news archive is at /news →
            </Link>
          </>
        ) : (
          <>
            {total_cards} cards, {total_entries} entries, last 24 hours.
          </>
        )}
      </p>
    </>
  );
}
