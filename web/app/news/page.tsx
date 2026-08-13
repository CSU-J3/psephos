import Link from "next/link";
import { getNewsFeed, getNewsExcludedCount } from "@/lib/db";
import { formatDate } from "@/lib/format";

// Live Turso per request, no build-time dependency -- same as every other route.
// Deliberately NOT reading data/news.json: no route in this app reads a snapshot,
// and a page that did would go stale between crons while its neighbours stayed live.
export const dynamic = "force-dynamic";

export default async function NewsPage() {
  const [items, excluded] = await Promise.all([
    getNewsFeed(),
    getNewsExcludedCount(),
  ]);

  // Group by month in one linear pass -- rows arrive newest-first, so the groups
  // come out in order without a re-sort (same shape as /state-bills).
  const byMonth = new Map<string, typeof items>();
  for (const it of items) {
    const key = it.occurred_at ? it.occurred_at.slice(0, 7) : "undated";
    const group = byMonth.get(key);
    if (group) group.push(it);
    else byMonth.set(key, [it]);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">Reporting</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {items.length} items from the maintained trackers, newest first.
        </p>
        {/* The excluded count travels with the included one, always. Without it this
            page reads as "the news channel", which it is not. */}
        <p className="mt-2 text-xs leading-relaxed text-neutral-500">
          B2 sources only. {excluded.toLocaleString()} aggregated Google News items are
          excluded: they are graded C3 until corroborated, and an uncorroborated
          aggregate should not drive the record.
        </p>
      </header>

      {items.length === 0 ? (
        <p className="mt-10 text-sm text-neutral-500">No reporting yet.</p>
      ) : (
        [...byMonth.entries()].map(([month, group]) => (
          <section key={month} className="mt-10">
            <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
              {month === "undated" ? "Undated" : month}
              <span className="text-sm font-normal tabular-nums text-neutral-500">
                {group.length}
              </span>
            </h2>
            <ul className="space-y-3">
              {group.map((it) => (
                <li
                  key={it.id}
                  className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-700"
                >
                  <a
                    href={it.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-neutral-100 hover:underline"
                  >
                    {it.title}
                  </a>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
                    <span className="tabular-nums">{formatDate(it.occurred_at)}</span>
                    <span>{it.source_id}</span>
                    <span className="rounded border border-neutral-700 px-1.5 py-0.5 font-mono tabular-nums">
                      {it.admiralty_source}
                      {it.admiralty_info}
                    </span>
                    {it.bill_id && (
                      <Link
                        href={`/bill/${it.bill_id}`}
                        className="text-neutral-400 hover:underline"
                      >
                        also on {it.bill_id} →
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </main>
  );
}
