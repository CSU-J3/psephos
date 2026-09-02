import Link from "next/link";
import type { CampaignSummary } from "@/lib/campaign";
import { formatDate } from "@/lib/format";
import type {
  BillsRead,
  ExecutiveRead,
  LitigationRead,
  NewsRead,
  StateBillsRead,
} from "@/lib/read";

// The read: six sentences, one per channel, replacing the channel strip's numbers as
// the page's opening. The strip's counts survive as one muted line beneath.
//
// ALL FORMATTING LIVES HERE AND ALL DERIVATION LIVES IN lib/read.ts. This component
// receives computed values and turns them into prose; it does no arithmetic beyond
// pluralisation, so the tests can assert on numbers rather than on strings.
//
// Every line can say "nothing", and says it with a date. "No movement" tells a reader
// nothing about whether the system is quiet or broken; "none since Mar 26, 2026" tells
// them which.

function plural(n: number, one: string, many = `${one}s`) {
  return n === 1 ? one : many;
}

function Line({
  label,
  href,
  children,
}: {
  label: string;
  href?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-4">
      <div className="w-28 shrink-0 pt-px text-xs uppercase tracking-wide text-neutral-500">
        {href ? (
          <Link href={href} className="transition-colors hover:text-neutral-300">
            {label}
          </Link>
        ) : (
          label
        )}
      </div>
      <p className="max-w-[78ch] text-sm leading-relaxed text-neutral-300">{children}</p>
    </div>
  );
}

export function TheRead({
  news,
  litigation,
  campaign,
  bills,
  executive,
  stateBills,
}: {
  news: NewsRead;
  litigation: LitigationRead;
  campaign: CampaignSummary;
  bills: BillsRead;
  executive: ExecutiveRead;
  stateBills: StateBillsRead;
}) {
  return (
    <div className="grid gap-x-10 gap-y-5 mid:grid-cols-2 3xl:grid-cols-3">
      <Line label="Reporting" href="/news">
        {news.collectedLast24h === 0 ? (
          <>
            Nothing collected in the last 24 hours. The most recent story is dated{" "}
            {formatDate(news.mostRecent?.occurred_at)}.
          </>
        ) : news.lead ? (
          <>
            <span className="text-neutral-100">
              {news.datedInWindow} of {news.collectedLast24h}
            </span>{" "}
            {plural(news.collectedLast24h, "story", "stories")} collected today{" "}
            {plural(news.datedInWindow, "is", "are")} dated in the last{" "}
            {news.windowDays} days. The best-graded is{" "}
            <a
              href={news.lead.source_url}
              className="text-neutral-100 underline decoration-neutral-700 underline-offset-2 hover:decoration-neutral-400"
            >
              {news.lead.title}
            </a>{" "}
            <span className="text-neutral-500">
              ({news.lead.admiralty_source}
              {news.lead.admiralty_info}, {formatDate(news.lead.occurred_at)})
            </span>
            .
          </>
        ) : (
          <>
            {news.collectedLast24h}{" "}
            {plural(news.collectedLast24h, "story", "stories")} collected today, none
            dated in the last {news.windowDays} days — the newest is dated{" "}
            {formatDate(news.mostRecent?.occurred_at)}.
          </>
        )}
      </Line>

      <Line label="Litigation" href="/campaign">
        {litigation.latestFiling === null ? (
          <>No dockets in the record yet.</>
        ) : (
          <>
            The most recent filing is{" "}
            <span className="text-neutral-100">
              {formatDate(litigation.latestFiling)}
            </span>
            , {litigation.filedOnLatest.length}{" "}
            {plural(litigation.filedOnLatest.length, "case")} —{" "}
            {litigation.filedOnLatest
              .map((c) => c.state)
              .slice(0, 5)
              .join(", ")}
            .{" "}
            {litigation.movedSinceFiling
              ? "Dockets have moved since."
              : "Nothing has moved since."}
          </>
        )}
      </Line>

      <Line label="DOJ campaign" href="/campaign">
        <span className="text-neutral-100">
          {campaign.sued} of {campaign.total} jurisdictions sued
        </span>
        , {campaign.live} still live and {campaign.ended} ended.{" "}
        {campaign.chains > 0 && <>{campaign.chains} continued elsewhere. </>}
        {campaign.dormant > 0 && <>{campaign.dormant} quiet.</>}
      </Line>

      <Line label="Watched bills">
        {bills.total === 0 ? (
          <>No bills on the watchlist.</>
        ) : bills.movedInWindow.length === 0 ? (
          <>
            None of the {bills.total} watched {plural(bills.total, "bill")} has moved
            since{" "}
            <span className="text-neutral-100">
              {formatDate(bills.latestActionAt)}
            </span>
            {bills.latest?.short_title && <> ({bills.latest.short_title})</>}.
          </>
        ) : (
          <>
            <span className="text-neutral-100">
              {bills.movedInWindow.length} of {bills.total}
            </span>{" "}
            watched {plural(bills.total, "bill")} moved in the last 7 days. Latest:{" "}
            {bills.latest?.short_title ?? bills.latest?.bill_id} —{" "}
            {bills.latestAction} ({formatDate(bills.latestActionAt)}).
          </>
        )}
      </Line>

      <Line label="Executive">
        {executive.total === 0 ? (
          <>Nothing collected on the executive channel.</>
        ) : executive.latest === null ? (
          <>
            <span className="text-neutral-100">0 of {executive.total}</span> collected
            documents score as election-relevant.
          </>
        ) : (
          <>
            <span className="text-neutral-100">
              {executive.relevant} of {executive.total}
            </span>{" "}
            collected documents are election-relevant. The most recent is{" "}
            <a
              href={executive.latest.source_url}
              className="text-neutral-100 underline decoration-neutral-700 underline-offset-2 hover:decoration-neutral-400"
            >
              {executive.latest.title}
            </a>{" "}
            <span className="text-neutral-500">
              ({formatDate(executive.latest.occurred_at)})
            </span>
            .
          </>
        )}
      </Line>

      <Line label="State bills" href="/state-bills">
        {stateBills.bills === 0 ? (
          <>No state bills in the dimension yet.</>
        ) : (
          <>
            <span className="text-neutral-100">
              {stateBills.bills} {plural(stateBills.bills, "bill")}
            </span>{" "}
            across {stateBills.states} {plural(stateBills.states, "state")},{" "}
            {stateBills.actedInWindow.length === 0 ? (
              <>
                none dated in the last 7 days — the latest action is{" "}
                {formatDate(stateBills.latestActionAt)}.
              </>
            ) : (
              <>
                {stateBills.actedInWindow.length} dated in the last 7 days.
              </>
            )}
          </>
        )}
      </Line>
    </div>
  );
}
