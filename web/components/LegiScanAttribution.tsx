// THE CC BY 4.0 ATTRIBUTION FOR LEGISCAN DATA, and it is a licence term, not copy.
//
// LegiScan's API data is CC BY 4.0. From 2026-11-01 LegiScan audits keys against those
// terms, and a key in violation is permanently banned (LegiScan API Team email,
// 2026-09-23). That is the state channel gone, with no appeal. The licence wants three
// things wherever the data is shown: credit to the creator, a link to the licence,
// and a statement that the data was changed. psephos filters and reformats, so the
// third is not optional. The sentence is Corey's, verbatim (handoff 98, Part B), and
// matches data/NOTICE.md and the README.
//
// IT RENDERS IN THREE PLACES: /state-bills, each state-bill page, and the site-wide
// footer in app/layout.tsx. The footer is what covers every "LegiScan ·" citation on
// the home page (WhereThisStands) without editing each Fact.
//
// DO NOT REWORD IT HERE ALONE. web/scripts/assert-attribution.mjs, a scheduled
// dom-checks step, carries its own copy of the sentence and fails if this one stops
// matching, or if either link, its href or its text goes missing on /, /state-bills or
// a state-bill page. The copy is deliberate: a check that read the text back from this
// file would pass any edit made here.

export const LEGISCAN_API_URL = "https://legiscan.com/legiscan";
export const CC_BY_4_URL = "https://creativecommons.org/licenses/by/4.0/";

const LINK =
  "text-neutral-400 underline decoration-neutral-600 underline-offset-2 hover:text-neutral-200";

export function LegiScanAttribution({ className = "" }: { className?: string }) {
  return (
    <p
      data-attribution="legiscan"
      className={`text-[0.8rem] leading-relaxed text-neutral-500 ${className}`}
    >
      State legislation data from the{" "}
      <a href={LEGISCAN_API_URL} target="_blank" rel="noreferrer" className={LINK}>
        LegiScan API
      </a>{" "}
      by LegiScan LLC, licensed under{" "}
      <a href={CC_BY_4_URL} target="_blank" rel="license noreferrer" className={LINK}>
        CC BY 4.0
      </a>
      . Filtered to election-related bills and reformatted by psephos.
    </p>
  );
}
