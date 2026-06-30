import Link from "next/link";
import { notFound } from "next/navigation";
import { getCase, getCaseTimeline } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { Timeline } from "@/components/Timeline";

// Live Turso per request, no build-time dependency -- same as home.
export const dynamic = "force-dynamic";

export default async function CasePage({
  params,
}: {
  params: Promise<{ case_id: string }>; // Next 15: params is a Promise
}) {
  const { case_id } = await params;
  const c = await getCase(case_id);
  if (!c) notFound();
  const items = await getCaseTimeline(case_id);

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <div className="flex items-start justify-between gap-3">
          <h1 className="min-w-0 text-2xl font-semibold tracking-tight">{c.caption}</h1>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {c.category && (
              <span className="rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
                {c.category}
              </span>
            )}
            {c.status && (
              <span className="rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
                {c.status}
              </span>
            )}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
          {c.court && <span>{c.court}</span>}
          {c.docket_number && <span className="font-mono">{c.docket_number}</span>}
          {c.plaintiff && c.defendant && (
            <span>
              {c.plaintiff} v. {c.defendant}
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-neutral-500">
          Filed {formatDate(c.filed_at)} · Updated {formatDate(c.latest_entry_at)}
        </div>
        {c.source_url && (
          <a
            href={c.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-sm text-sky-400 hover:underline"
          >
            View docket ↗
          </a>
        )}
      </header>

      <section className="mt-8">
        <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          Timeline
          <span className="text-sm font-normal tabular-nums text-neutral-500">
            {items.length}
          </span>
        </h2>
        <Timeline items={items} />
      </section>
    </main>
  );
}
