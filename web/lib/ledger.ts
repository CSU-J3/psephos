// The ledger rules: what text a detail-page row shows, and what leaves the ledger.
//
// These are derivations over stored columns, which is why they live here rather than in
// the component -- `vitest.config.ts` draws that line and it holds. `Timeline.tsx` is
// then thin enough that its correctness is visible on the page.

import type { TimelineItem } from "@/lib/db";

/** The Admiralty grade as one comparable string, e.g. "A1". */
export function gradeOf(it: Pick<TimelineItem, "admiralty_source" | "admiralty_info">): string {
  return `${it.admiralty_source}${it.admiralty_info}`;
}

/**
 * The best grade present on the page, or null when the page is empty.
 *
 * Lexicographic order IS the Admiralty order: source reliability runs A-F and
 * credibility 1-6, so "A1" < "B2" < "C3" as strings without a lookup table.
 */
export function bestGrade(items: readonly TimelineItem[]): string | null {
  let best: string | null = null;
  for (const it of items) {
    const g = gradeOf(it);
    if (best === null || g < best) best = g;
  }
  return best;
}

/**
 * The caption every entry on this page repeats, or null when there isn't one.
 *
 * MECHANICAL, NEVER A PARSE. It does not know what a case caption or a bill id looks
 * like: it takes the longest common prefix of the cohort's titles and truncates that at
 * its last ": ". Nothing here can be wrong about a name because nothing here reads one.
 *
 * THE COHORT IS THE BEST-GRADED ENTRIES, NOT A HARDCODED A1. The rule was written as
 * "leads every A1 entry", which is exactly right on a case page and on a bill page, and
 * silently wrong on a state-bill page: all 3,882 state items are B2 and no state page
 * holds a single A1 row, so a literal reading finds no cohort, computes null, keeps
 * "TX SB2753: " on every collapsed line, and leaves each expansion showing LESS than the
 * line above it. Reading the cohort off the page's own best grade is the same rule where
 * the literal one worked and the intended one where it did not. On /bill/s1383-119 this
 * also does the right thing for free: the cohort is that page's 44 legislation A1 rows,
 * and its 96 interleaved news titles -- which share no prefix at all -- cannot veto it.
 *
 * SMALL-COHORT OVERSTRIP, accepted and pinned rather than mitigated (ruled 2026-09-02).
 * With one entry in the cohort the "common prefix" is that entry's entire title, so a
 * second ": " inside the text is taken for part of the caption and the collapsed line
 * loses a real piece of itself. It is contained by construction: the strip touches the
 * COLLAPSED LINE ONLY, every branch of `entryText` puts a verbatim stored column in the
 * body, and the reader is one click from the whole string. See ledger.test.ts.
 */
export function pagePrefix(items: readonly TimelineItem[]): string | null {
  const best = bestGrade(items);
  if (best === null) return null;

  const cohort = items.filter((it) => gradeOf(it) === best).map((it) => it.title ?? "");
  if (cohort.length === 0) return null;

  let lcp = cohort[0];
  for (const title of cohort.slice(1)) {
    let i = 0;
    while (i < lcp.length && i < title.length && lcp[i] === title[i]) i++;
    lcp = lcp.slice(0, i);
    if (lcp === "") return null;
  }

  const cut = lcp.lastIndexOf(": ");
  if (cut <= 0) return null; // no separator, or a title that opens with one
  const prefix = lcp.slice(0, cut + 2);

  // True by construction; asserted because a prefix that does not actually lead every
  // cohort title would strip text off rows it does not belong to.
  return cohort.every((t) => t.startsWith(prefix)) ? prefix : null;
}

/**
 * What one row renders: a collapsed line, and a body when the body adds something.
 *
 * `body === null` means the line already carries the whole text and the <details> only
 * has to stop clipping it -- the de-dupe, not a deletion.
 */
export type EntryText = {
  line: string;
  body: string | null;
};

/**
 * The one-text rule. STRIP FIRST, THEN COMPARE, and the order is the whole rule.
 *
 * The collector writes `title = "<caption>: " + desc[:180]` and `summary = desc`, so the
 * summary extends the title only once the caption is off the front of it. Compared raw,
 * `summary.startsWith(title)` is true for 0 of 10,538 production items and the summary
 * branch is dead code; compared after the strip it fires on 6,102 -- every litigation,
 * legislation and state row, and correctly none of the 4,318 news and executive rows,
 * where a lede is a different text from a headline rather than a longer one.
 *
 * IT DE-DUPES, IT DOES NOT DELETE (ruled 2026-09-02). Three branches, and in all three
 * the body is a stored column verbatim:
 *
 *   summary extends the stripped title -> the summary alone; it contains the title
 *   summary exists but is distinct     -> title on the line, summary in the body
 *   no summary                          -> the title, stripped on the line, whole in body
 */
export function entryText(it: TimelineItem, prefix: string | null): EntryText {
  const title = it.title ?? "";
  const stripped = prefix && title.startsWith(prefix) ? title.slice(prefix.length) : title;
  const summary = it.summary?.trim() ? it.summary : null;

  if (summary && stripped.trim() !== "") {
    if (summary.trim().startsWith(stripped.trim())) {
      return { line: summary, body: null };
    }
    if (fold(summary) !== "" && fold(summary) === fold(stripped)) {
      return { line: stripped, body: null };
    }
  }
  if (summary) {
    return { line: stripped, body: summary };
  }
  return { line: stripped, body: stripped === title ? null : title };
}

/**
 * The comparison key for "these are the same words": entities out, case and every
 * non-alphanumeric discarded. Used ONLY to decide whether two texts say the same thing;
 * nothing rendered is ever folded.
 *
 * It exists for the aggregator restatement, which is the most common item on the news
 * channel -- 3,174 of 4,189 -- and fits neither shape the rule was written for. Google
 * News delivers `title` as "<headline> - <publisher>" and `summary` as "<headline>
 * &nbsp;&nbsp; <publisher>": not an extension, so the summary branch misses it, and not
 * a distinct text either, so the two-text branch printed one sentence twice.
 *
 * EQUALITY ONLY, NEVER PREFIX. Folding away punctuation makes strings compare equal much
 * too easily, and 8 news items prove the danger: their summaries open by quoting the
 * headline and then say something else entirely. Under a folded PREFIX test those lose
 * their real text; under folded EQUALITY they keep both halves, which is the right
 * answer when the rule is unsure.
 */
function fold(s: string): string {
  return s
    .toLowerCase()
    .replace(/&[a-z]+;|&#\d+;/g, " ")
    .replace(/[^a-z0-9]+/g, "");
}

/** Rows shown before the fold. */
export const SLICE_HEAD = 10;

export type Slice = {
  /** The latest `head` entries, newest first. */
  head: TimelineItem[];
  /** Everything older, still newest first. Empty when nothing is folded. */
  rest: TimelineItem[];
};

/**
 * Newest first, then split at `head`.
 *
 * NEWEST FIRST, RULED 2026-09-02. A docket reads oldest-first in PACER because a docket
 * is a filing record; this is a monitor, and the question it exists to answer is what
 * moved last. The full chronological reading stays available -- expanding the fold puts
 * the whole record on the page -- so nothing is lost, and there is NO second sort inside
 * the fold: the order is uniform, or the page would run 43, 42 ... 34, then 1, 2, 3.
 *
 * THE SORT KEY IS THE `occurred_at` STRING, NOT A PARSED DATE, and that is a
 * correctness requirement rather than a shortcut. `occurred_at` is naive on litigation
 * rows (`2025-12-11T00:00:00`) and `+00:00`-suffixed on news, and `Date.parse` reads the
 * naive form in the runtime's local zone -- the reason `lib/format.ts` carries `utcDay`
 * at all. Comparing the raw strings is exactly what SQLite's TEXT collation did in the
 * three `ORDER BY occurred_at, id` queries feeding this, so the result here is provably
 * the reverse of the query rather than an independent guess at chronology.
 *
 * It sorts rather than reversing, so the tests can hand it shuffled input. A test built
 * on pre-sorted rows would pass against a function that only called `.reverse()`, and
 * would go on passing if a query ever lost its ORDER BY.
 *
 * COPIES BEFORE SORTING. `Array.prototype.sort` is in-place, and every caller hands the
 * same array to `pagePrefix` and to the channel-label check BEFORE slicing it. Sorting
 * the caller's array would not throw; it would quietly change what those two computed.
 */
export function sliceLedger(
  items: readonly TimelineItem[],
  head: number = SLICE_HEAD,
): Slice {
  const ordered = [...items].sort(
    (a, b) =>
      (b.occurred_at ?? "").localeCompare(a.occurred_at ?? "") || b.id - a.id,
  );
  return { head: ordered.slice(0, head), rest: ordered.slice(head) };
}

export type Promotion = {
  /** The tracker's current reading of the case, lifted out of the ledger. */
  status: TimelineItem | null;
  /** Everything that stays on the timeline. */
  ledger: TimelineItem[];
};

/**
 * Lift the B2 tracker status row out of a case's ledger and into its header.
 *
 * THE DISCRIMINATOR IS CLEAN, WHICH IS WHY THE WHOLE KIND LEAVES rather than just the
 * one promoted row. Measured over all 2,265 case-anchored items: 118 are B2 and 2,147
 * are A1, and the split is structural rather than lucky -- `litigation.py` has two
 * writers, one emitting `"<caption> — <category>"` at B2 for tracker metadata and one
 * emitting `"<caption>: <desc>"` at A1 for court records. The em-dash shape corroborates
 * the grade independently: 118 of 118 B2 titles carry " — ", 0 of 2,147 A1 titles do.
 *
 * NOTHING LEAVES THAT IS NOT A RE-READ OF WHAT WAS PROMOTED. 29 of the 52 cases holding
 * a status row hold more than one, up to five. Across all 29 the title and the
 * source_url are identical within the case and only the summary moves, so they are
 * repeated readings of one fact rather than distinct events; 26 of 29 differ only in the
 * text after "| Status:", and in the other 3 the tracker revised its own claims list.
 *
 * THE HIGHEST id, NOT THE LAST ROW. `id` is insertion order, so it is the freshest read.
 * The page's own `ORDER BY occurred_at, id` cannot be reused: most status rows carry a
 * NULL `occurred_at` and sort ahead of the few dated ones, so timeline-last is often the
 * OLDEST reading -- the two disagreed on all 8 multi-status cases sampled.
 */
export function promoteStatus(items: readonly TimelineItem[]): Promotion {
  const isStatus = (it: TimelineItem) =>
    it.channel === "litigation" && it.admiralty_source === "B";

  let status: TimelineItem | null = null;
  const ledger: TimelineItem[] = [];
  for (const it of items) {
    if (!isStatus(it)) {
      ledger.push(it);
      continue;
    }
    if (status === null || it.id > status.id) status = it;
  }
  return { status, ledger };
}
