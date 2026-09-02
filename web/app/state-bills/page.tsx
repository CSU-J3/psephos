import Link from "next/link";
import { getStateBills } from "@/lib/db";
import { StateBillRow } from "@/components/StateBillRow";
import { StateMatrix } from "@/components/StateMatrix";
import {
  buildMatrix,
  filterStateBills,
  groupByState,
  latestMovement,
  listTitle,
  parseStateBillParams,
  sortByRecent,
} from "@/lib/statebill";

// Live Turso per request, no build-time dependency -- same as home. force-dynamic is
// also what makes the search params below free: every view of this page is already a
// fresh render, so a filter costs nothing beyond the filter.
export const dynamic = "force-dynamic";

// THE SUMMARY IS THE DEFAULT, AND THE LIST IS OPT-IN. This page used to render all
// 484 bills as nine stacks of cards -- a screen you scroll and learn nothing from,
// because a list of 484 answers no question a reader arrives with. The matrix answers
// "which states are moving and how far", "latest movement" answers "what moved", and
// the list appears only once a count has been clicked and the reader has asked for it.
//
// ALL OF IT IS SERVER-RENDERED LINKS. The mock drives this with client JS and hidden
// sections; here the filters live in the URL, so there is no client component, no
// hydration, and every filtered view is a real address that can be linked and shared.
export default async function StateBillsPage({
  searchParams,
}: {
  // A Promise on Next 15 -- the page is async anyway, so it just gets awaited.
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const bills = await getStateBills();
  const { state, status, sort, listing } = parseStateBillParams(await searchParams);

  const matrix = buildMatrix(bills);
  const movement = latestMovement(bills);
  const rows = listing ? filterStateBills(bills, { state, status }) : [];

  // Grouping by state INSIDE one state is meaningless, so a state filter forces the
  // flat list and hides the toggle. The mock leaves the toggle up there and then
  // ignores it, which is a mock bug rather than a specification.
  const grouped = sort === "state" && !state;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        ← psephos
      </Link>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">State legislation</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {matrix.total} election bills across {matrix.rows.length} states,
          subject-filtered via LegiScan. Every count below opens its list.
        </p>
      </header>

      <h2 className="mt-9 mb-2 text-[0.8rem] font-semibold tracking-[0.08em] text-neutral-500 uppercase">
        By state and stage
      </h2>
      <StateMatrix matrix={matrix} />

      <h2 className="mt-9 mb-2 text-[0.8rem] font-semibold tracking-[0.08em] text-neutral-500 uppercase">
        Latest movement
        <span className="ml-2 text-[0.8rem] font-normal tracking-normal text-neutral-600 normal-case">
          ten most recent actions, any state
        </span>
      </h2>
      <ul>
        {movement.map((b) => (
          <StateBillRow key={b.state_bill_id} bill={b} />
        ))}
      </ul>

      <p className="mt-3">
        <Link
          href="/state-bills?all=1#list"
          className="text-[0.8rem] text-neutral-400 hover:text-neutral-100"
        >
          Browse all {matrix.total} →
        </Link>
      </p>

      {listing && (
        <section id="list" className="mt-10 scroll-mt-6">
          <div className="mb-1 flex items-baseline gap-3">
            <h3 className="text-base font-semibold">{listTitle({ state, status })}</h3>
            <span className="text-[0.8rem] tabular-nums text-neutral-500">
              {rows.length === 1 ? "1 bill" : `${rows.length} bills`}
            </span>
            <Link href="/state-bills" className="text-xs text-neutral-500 hover:text-neutral-100">
              × close
            </Link>
            {!state && (
              <span className="ml-auto inline-flex overflow-hidden rounded-md border border-neutral-800">
                <SortLink label="Recent" target="recent" active={!grouped} {...{ state, status }} />
                <SortLink label="By state" target="state" active={grouped} {...{ state, status }} />
              </span>
            )}
          </div>

          {rows.length === 0 ? (
            <p className="border-t border-[#1c1c1c] py-4 text-sm text-neutral-500">
              No bills match that filter.
            </p>
          ) : grouped ? (
            groupByState(rows).map((group) => (
              <div key={group.state}>
                <h4 className="sticky top-0 z-5 mt-4 border-b border-neutral-800 bg-neutral-950 pt-1.5 pb-1.5 text-[0.95rem] font-semibold">
                  {group.state}{" "}
                  <span className="text-[0.78rem] font-normal tabular-nums text-neutral-500">
                    {group.bills.length}
                  </span>
                </h4>
                <ul>
                  {group.bills.map((b) => (
                    <StateBillRow key={b.state_bill_id} bill={b} />
                  ))}
                </ul>
              </div>
            ))
          ) : (
            <ul>
              {sortByRecent(rows).map((b) => (
                <StateBillRow key={b.state_bill_id} bill={b} />
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}

// The mock's segmented control, as two links. `all=1` is carried explicitly because a
// sort with no filter would otherwise close the list it is sorting.
function SortLink({
  label,
  target,
  active,
  state,
  status,
}: {
  label: string;
  target: "recent" | "state";
  active: boolean;
  state: string | null;
  status: string | null;
}) {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (status) params.set("status", status);
  if (!state && !status) params.set("all", "1");
  params.set("sort", target);

  return (
    <Link
      href={`/state-bills?${params.toString()}#list`}
      aria-current={active ? "true" : undefined}
      className={`px-2 py-1 text-[0.72rem] ${
        active ? "bg-neutral-900 text-neutral-100" : "text-neutral-500 hover:text-neutral-300"
      }`}
    >
      {label}
    </Link>
  );
}
