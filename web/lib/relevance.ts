// View-layer election-relevance lens over the broad executive channel. The
// collector pulls broadly (FR full-text on loose terms); this surfaces the
// voting-rights signal and sinks routine rulemaking. Tunable: edit TERMS.
// Phrase-aware -- "voter registration" matches as a phrase, NOT bare
// "registration" (which would wrongly catch alien-registration notices).
const TERMS = [
  "election",
  "voting",
  "voter",
  "ballot",
  "voter registration",
  "voter roll",
  "proof of citizenship",
  "citizenship verification",
  "mail ballot",
  "absentee",
  "redistricting",
  "voting rights",
  "national voter registration act",
  "help america vote act",
  "election assistance commission",
];

// A LEADING WORD BOUNDARY, not a bare substring test. `String.includes` matched a
// term anywhere inside a word, so "election" fired on "Weighted SELECTion Process
// for Registrants and Petitioners Seeking To File Cap-Subject H-1B Petitions" --
// an immigration notice, sitting in the relevant view because of six letters in
// the middle of "Selection".
//
// This is the same class of error the phrase note above defends against, from the
// other side. That one keeps "registration" from catching alien-registration
// notices by requiring the phrase "voter registration"; this keeps a term from
// matching inside an unrelated word at all.
//
// LEADING ONLY -- no trailing \b. Plurals and inflections must keep matching:
// "election" has to hit "elections", "voter" has to hit "voters". Measured over
// data/executive.json (118 rows, 2026-08-16): includes 13, leading boundary 12.
// The single row dropped is the H-1B title, and nothing new is added.
const PATTERNS = TERMS.map(
  (t) => new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`),
);

// Scores the TITLE only, deliberately not the summary. Many routine executive
// items are EAC (Election Assistance Commission) notices whose abstracts are full
// of "election"/"voting" -- scoring summary pulls ~16 Sunshine Act meeting notices
// into the relevant view and buries the signal. The title is the clean axis: it
// surfaces the EOs and genuinely-election-named notices, hides the procedural
// chaff. Tune TERMS as needed.
export function relevanceScore(title: string): number {
  const hay = title.toLowerCase();
  return PATTERNS.reduce((n, p) => (p.test(hay) ? n + 1 : n), 0);
}
