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

// Scores the TITLE only, deliberately not the summary. Many routine executive
// items are EAC (Election Assistance Commission) notices whose abstracts are full
// of "election"/"voting" -- scoring summary pulls ~16 Sunshine Act meeting notices
// into the relevant view and buries the signal. The title is the clean axis: it
// surfaces the EOs and genuinely-election-named notices, hides the procedural
// chaff. Tune TERMS as needed.
export function relevanceScore(title: string): number {
  const hay = title.toLowerCase();
  return TERMS.reduce((n, t) => (hay.includes(t) ? n + 1 : n), 0);
}
