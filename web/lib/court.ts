// Court-name canonicalization for the read layer.
//
// WHY THIS EXISTS
// ===============
// `cases.court` is written off the SEED, never off the docket -- `upsert_case` takes
// it from the tracker row -- so the column carries the UW tracker's vocabulary rather
// than the courts' own names. On two rows those disagree: UW types 'Eighth District'
// for the Eighth Circuit and 'DC Circuit' for the D.C. Circuit. That mismatch is what
// left both rows unresolved for seventeen days (docs/findings/reconciliation-alarm-
// 2026-09-06.md), and `collectors/tracker_uw.py` now aliases both spellings onto the
// right CourtListener id.
//
// That fix is upstream and does not help the reader. The stored string is untouched by
// it -- deliberately -- so the page still renders 'Eighth District', and worse,
// `isCircuit` still reads FALSE on it: /\bcircuit\b/ does not match 'Eighth District'.
// A Minnesota cell whose successor is a circuit appeal would therefore draw the refile
// glyph, which is a different event with a different meaning.
//
// WHY IT CANONICALIZES AT READ AND NOT IN THE DATA
// ================================================
// The stored value is a JOIN KEY in three places on the Python side: `collect_case`'s
// reuse lookup, `coverage_audit`'s (docket_number, court) seed join, and the
// byte-identical overwrite between a tracker row and a config seed. Rewriting the
// column breaks all three. So the verbatim string stays in the database and every
// READER passes it through here first -- the same shape as the news channel's outlet
// promotion, where the grade is derived at read time and nothing rewrites what the
// pipe said.
//
// This is a display bridge over a known vocabulary gap, not a general normalizer.
// It maps the two spellings observed in the artifact and leaves everything else
// exactly as it found it; an unrecognized court is returned unchanged rather than
// guessed at. The alarm for a THIRD such spelling is upstream (Unit C), not here --
// silently canonicalizing an unknown string is how the first two went unnoticed.
//
// The key set is pinned against `COURT_IDS`'s aliases by a test that fails in either
// direction; see tests/test_court_alias_agreement.py for why that test lives on the
// Python side.

/** UW's spelling -> the court's name. Keys MUST agree with the alias block in
 *  `collectors/tracker_uw.py` COURT_ALIASES, in both directions. */
export const COURT_ALIASES: Record<string, string> = {
  "Eighth District": "Eighth Circuit",
  "DC Circuit": "D.C. Circuit",
};

/** The court's name for a stored `cases.court` value. Null and unrecognized values
 *  pass through unchanged -- this widens no claim the record does not already make. */
export function canonicalCourt(court: string | null): string | null {
  if (court === null) return null;
  return COURT_ALIASES[court] ?? court;
}
