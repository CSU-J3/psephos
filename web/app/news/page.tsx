import Link from "next/link";
import { getNewsFeed, getNewsExcludedCount, type NewsItem } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { groupByMonth, sourceRoster, UNDATED } from "@/lib/news";
import { Grade } from "@/components/Grade";

// Live Turso per request, no build-time dependency -- same as every other route.
// Deliberately NOT reading data/news.json: no route in this app reads a snapshot,
// and a page that did would go stale between crons while its neighbours stayed live.
export const dynamic = "force-dynamic";

export default async function NewsPage({
  searchParams,
}: {
  searchParams: Promise<{ source?: string }>; // Next 15: searchParams is a Promise
}) {
  const [{ source }, all, excluded] = await Promise.all([
    searchParams,
    getNewsFeed(),
    getNewsExcludedCount(),
  ]);

  // THE ROSTER IS BUILT FROM `all`, THE MONTHS FROM `items`. A roster computed over the
  // filtered rows would list only the source already chosen, leaving the reader inside a
  // filter with nothing to click back out of -- and on a view where the filter matched
  // nothing it would render empty and strand them completely.
  const roster = sourceRoster(all);
  const items = source ? all.filter((it) => it.source_id === source) : all;
  const groups = groupByMonth(items);
  const [open, ...folded] = groups;

  // ONE ROW FUNCTION FOR BOTH SIDES OF EVERY FOLD. Two copies would be two things to
  // keep in step, and the promise that a folded row is treated exactly like an open one
  // is then a claim about review rather than a property of the code.
  const row = (it: NewsItem) => {
    const grade = `${it.admiralty_source}${it.admiralty_info}`;
    return (
      <li
        key={it.id}
        className="flex items-baseline gap-2.5 border-b border-neutral-900 py-2 pl-0.5 pr-1 hover:bg-neutral-900/60"
      >
        <span className="w-[6.2rem] shrink-0 font-mono text-[0.72rem] text-neutral-600">
          {formatDate(it.occurred_at)}
        </span>
        {/* The exception chip, and the rule it is an exception to is stated in the
            subtitle. It is NOT unreachable: the feed filters on the SOURCE's grade and
            renders the ITEM's, and collectors/news.py classify() demotes an item to C3
            when it attaches to the vehicle bill by inference -- 6 rows today, which are
            exactly the 6 carrying a bill_id. Absence of a chip means B2. */}
        {grade !== "B2" && <Grade grade={grade} dense />}
        <a
          href={it.source_url}
          target="_blank"
          rel="noopener noreferrer"
          title={it.title}
          className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-sm text-neutral-300 hover:text-neutral-100 hover:underline"
        >
          {it.title}
        </a>
        {it.bill_id && (
          <Link
            href={`/bill/${it.bill_id}`}
            className="shrink-0 text-[0.68rem] text-neutral-500 hover:text-neutral-200"
          >
            {it.bill_id} →
          </Link>
        )}
        {/* `shrink-0` at a pinned 8.5rem overflowed the viewport at 375px -- 136px of
            source beside 99px of date leaves less than the headline needs, and the row
            pushed 10px past the page. Narrowed below `sm` rather than hidden: the
            publisher is the second thing a reader checks on a reporting archive, and
            `truncate` degrades it rather than dropping it. */}
        <span className="w-[8.5rem] shrink-0 truncate text-right text-[0.68rem] text-neutral-600 max-sm:w-16">
          {it.source_id}
        </span>
      </li>
    );
  };

  const monthLabel = (month: string) => (month === UNDATED ? "Undated" : month);
  const plural = (n: number) => (n === 1 ? "entry" : "entries");

  // The aggregator's two halves. `excluded` counts the whole channel's exclusions, and
  // every one of them is google-news -- measured, not assumed -- so promoted + excluded
  // is the entire aggregator population and the subtitle's arithmetic closes.
  const promoted = roster.find((r) => r.source_id === "google-news")?.count ?? 0;
  const aggregatorTotal = promoted + excluded;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">Reporting</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {items.length.toLocaleString()} items from the maintained trackers, newest
          first{source ? ` — ${source} only` : ""}. A grade shows only where it is not
          B2.
        </p>
        {/* THE TWO GOOGLE NEWS FIGURES ARE HALVES OF ONE NUMBER, and the sentence says so
            rather than leaving them adjacent and apparently contradictory: the roster
            below lists `google-news` among the included sources while this line says
            Google News items are excluded. Both are true -- 124 + 3,514 = 3,638, the
            whole aggregator population -- and a reader can check the arithmetic. */}
        <p className="mt-2 text-xs leading-relaxed text-neutral-500">
          B2 sources only, plus outlet promotion: of {aggregatorTotal.toLocaleString()}{" "}
          aggregated Google News items, {promoted.toLocaleString()} are here because
          their publisher is an outlet this config grades B2, and the other{" "}
          {excluded.toLocaleString()} are excluded — graded C3 until corroborated, and an
          uncorroborated aggregate should not drive the record.
        </p>

        {/* The roster doubles as the filter control and as the way out of it. */}
        <p className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
          <Link
            href="/news"
            className={
              source
                ? "text-neutral-500 hover:text-neutral-200"
                : "font-medium text-neutral-200"
            }
          >
            all <span className="tabular-nums">{all.length.toLocaleString()}</span>
          </Link>
          {roster.map((r) => (
            <Link
              key={r.source_id}
              href={`/news?source=${encodeURIComponent(r.source_id)}`}
              className={
                source === r.source_id
                  ? "font-medium text-neutral-200"
                  : "text-neutral-500 hover:text-neutral-200"
              }
            >
              {r.source_id} <span className="tabular-nums">{r.count}</span>
            </Link>
          ))}
        </p>
      </header>

      {groups.length === 0 ? (
        <p className="mt-10 text-sm text-neutral-500">
          No reporting yet{source ? ` from ${source}` : ""}.
        </p>
      ) : (
        <section className="mt-8">
          <h2 className="mb-1 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
            {monthLabel(open.month)}
            <span className="text-sm font-normal text-neutral-500">
              <span className="tabular-nums">{open.items.length}</span>{" "}
              {plural(open.items.length)}
            </span>
          </h2>
          <ul className="border-t border-neutral-900">{open.items.map(row)}</ul>

          {folded.map((g) => (
            // NO `group` CLASS HERE, the same hazard the ledger's fold documents:
            // Tailwind compiles `group-open:` to a DESCENDANT selector, so a wrapper
            // carrying `group` would reach every row nested inside it. No row on this
            // page uses `group-open:` today, and the class is still withheld so that
            // adding one later cannot quietly break across the fold.
            <details key={g.month}>
              <summary className="flex cursor-pointer list-none items-baseline gap-2 border-b border-neutral-900 py-2 pl-0.5 text-[0.72rem] text-neutral-500 hover:bg-neutral-900/60 hover:text-neutral-300 [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="font-mono">
                  ▸
                </span>
                <span className="font-mono">{monthLabel(g.month)}</span>
                <span>
                  · <span className="tabular-nums">{g.items.length}</span>{" "}
                  {plural(g.items.length)}
                </span>
              </summary>
              <ul>{g.items.map(row)}</ul>
            </details>
          ))}
        </section>
      )}
    </main>
  );
}
