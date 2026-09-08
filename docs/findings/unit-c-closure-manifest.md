# Unit C closure manifest — v4.3 (file form)

Assembled review-side 2026-09-07, from elements individually verified by both
sides in the 09-07 session. Supersedes chat blocks v3, delta-1, delta-2, v4,
v4.1, all of which truncated or are fragments. Intended path:
`docs/findings/unit-c-closure-manifest.md`, tracked. The closure touch reads
this file only. One commit, at the touch following the first-run observation.

**v4.3, 2026-09-08 — the touch executed; §8 and §9 amended after the fact.**
The closure touch landed at `8d828ba`, following the first-run observation of
that morning. Two items had gone stale and are corrected below rather than
rewritten away: §8's push gate, lifted by standing authorization, and §9's
board item, which had been closed for five sessions while this file went on
naming it as the thing that comes next. Item count is unchanged at 9. **A
governing document is not exempt from the staleness it exists to prevent** —
see the falsified entry that this amendment produced.

## 1. The observation

Read not predicted, at whatever hour the next session opens: the first
`17 5 * * *` audit run's outcome; the issue surface (0 open expected; if
"coverage_audit red" exists, the body separates genuine FIRES lines from the
no-output plumbing marker); landing time noted as one sample, no band claimed.
A null read stays null and dated; a red self-announces via the cc mention.

## 2. Falsified-list entries, three

**A. Review side.** Slot grid misexpanded from memory as 05/11/17/23:17Z for
`17 */6`, with the refuting data-commit timestamps (13:08Z, 05:00Z, 20:37Z) in
the same session's own output. Instrument: expand the cron against its spec,
or check any one data-commit time against the claimed grid.

**B. Code.** 2h08–4h42 derived from four same-day runs and written as an
operating envelope into three files; ten runs across three days break it
(2h05m below the floor; the 12:36:16Z run 0h19m or 6h19m, outside under either
assignment). Sampling, not arithmetic. Instrument: the full run_started_at
table across days before writing any range. Near-miss coda: the census built
to bound the blast radius would itself have widened it if piped into an edit —
"band is" alone reaches four unrelated senses in this tree, two of them inside
v37:830 and v42:884, the mock files the next unit is built from. A pattern
replace would have edited the approved spec while fixing a cron comment.
Census feeds a map; only the map feeds edits.

**C. status.md:549 intra-commit drift.** "Four still open" and the
canonicalization gate sentence contradict recon §7 ("All seven are approved
2026-09-06") and `7ac866e`, all born together in `72eeecf`. Instrument:
cross-read files staged in one commit against each other; re-read gate
sentences against the log before carrying them.

## 3. Strike/keep map at `5cf0eeb`

Six sites, grain-invariant across all censuses run 2026-09-07. Numeric tokens
reach all six; phrase tokens reach the prose sites; the family is the union.

- `audit.yml:20` — strike (the figure). `audit.yml:21` — strike (the
  "closes around 05:00" derivative). Lines 22–24 — keep; line 24 already
  disclaims the precision, say so in the commit message.
- `collect.yml:18` — restate as observed spread with n and dates. Second
  correction to the same lines; recorded as such.
- `findings:185` — keep (arithmetic record). `findings:187–194` — keep
  (measured table). `findings:196–197` — strike whole (band, derived window,
  ~02:2x vindication). Third correction layer to the same claim; recorded as
  a third layer.
- The 12:36:16Z run is filed separately as unassignable between slots. No
  envelope is claimed anywhere. 2h05 / 6h19 / 0h19 verified absent from the
  tree at `5cf0eeb`; the new figures enter fresh.

## 4. False-positive ledger

Tokens named, full paths, excluded from all edits:

- `docs/status.md:1027` ← "closes around" (cert window, 2026-11-12)
- `docs/status.md:1197` ← 05:00 (FLP window; restated per item 5)
- `docs/findings/reconciliation-alarm-2026-09-06.md:245` ← 05:00Z
  (commit-time row, 49 lines below a strike site)
- `web/components/DayTimeline.tsx:180` ← "band is" (timeline band)
- `web/scripts/assert-layout.mjs:84` ← "band is" (layout band)
- `docs/design/psephos-home-mock-v37.html:830` and
  `docs/design/psephos-home-mock-v42.html:884` ← "band is" (hatched band)
- `docs/findings/22-throttle-scope-vs-magnitude.md:153` ← "same lag"
  (EDU expiry)
- `data/*.json` and `tests/fixtures` ← timestamps

## 5. status.md:1197 restated

No 06:00Z run exists. Candidates are the 00:17Z Friday run (in-window at lag
≥ 3h43m) and the 06:17Z Friday run (in-window at ≤ 42m under PDT, ≤ 1h42m
under PST). "Falls inside under both" becomes "can overlap under either."
Durable core kept: FLP maintains weekly on a boundary that walks with DST,
and psephos accounts for it nowhere.

## 6. status.md:549 rewritten once, both stalenesses

Four-open → the four are decisions recorded inside the findings doc (§2, §4,
§5 ×2), approved 2026-09-06; the remainder is the verbatim-vs-canonical
display sub-question. Gate sentence → cleared at `7ac866e`; 22 identified as
the pre-canonicalCourt reading; 23 enters qualified as-of 2026-09-07 or
deferred to recon §2. No bare figure enters status.md.

## 7. Line-11 header

Cleared in the same touch; the Unit C closure line replaces
"AWAITING / waits on Corey."

## 8. Constraints

Edits by named site only, never pattern replace. Diff before commit.
`sha_sweep` on a fresh full clone post-push.

~~Push is a separate approval.~~ **SUPERSEDED 2026-09-08 by Corey's standing
authorization.** The old text is struck rather than deleted so the change reads
as a decision with a date on it; only the push gate is lifted, and every other
constraint in this section stands unchanged.

**`sha_sweep`'s discriminator, added 2026-09-08 after it misfired twice in one
run.** A candidate must carry **at least one non-decimal hex character**, or be
validated with `git cat-file -e <sha>^{commit}` rather than by pattern. The
reason is measured, not theoretical: CourtListener docket ids (`72347022`) and
GitHub Actions run ids (`31423505973`) are all-decimal and therefore match
`[0-9a-f]`, so a bare hex pattern reported **65 dead shas** where **one** token
was sha-shaped and unresolved. **Count the exclusions, never drop them** — the
63 ids ruled out are printed with their count, because a filter that silently
discards is indistinguishable from one that silently misses. The complementary
failure is in the same family: a quoting slip in the same run returned *0 shas
found* against a file holding 152, and only the absurdity of the number caught
it. Red-proof the extractor and the resolver before reading either's output.

## 9. Then

~~The board holds one item: section mock v1, review side, on Corey's go —
content from v37, frame from v42, gates.yaml schema per recon §6, live
figures at draw time. Code idle until the mock is approved.~~

**STALE AS OF 2026-09-07, corrected 2026-09-08.** The text above was already
false when this file was assembled, and it is kept because what it shows is
worth more than a clean paragraph: the item it names had been **done for
hours**. Section mock v1 was drawn, approved and committed at `9a02d6e`
(2026-09-07 18:27), and the section it specified shipped the same evening at
`077103f` (19:16) — twelve gated claims, no literal on the page. Nothing was
waiting on Corey's go, and nothing was idle.

**Actual board state, 2026-09-08: this manifest holds no open item.** What
remains is not a board item but an observation owed — the first SCHEDULED
`audit.yml` run going green on the mapped read-only token, which is the only
proof of `e4831c0` and the only thing that closes issue #1. It cannot be
scheduled, only waited for.

END v4.3 — 9 items. If this line is missing, the copy is truncated.
