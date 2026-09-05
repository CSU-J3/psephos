/**
 * Counts DOUBLE CASTS -- `x as unknown as T` -- per file, from the AST.
 *
 *   node scripts/assert-casts.mjs            # sweep + assert the pinned floors
 *   node scripts/assert-casts.mjs --report   # sweep + print counts, never fail
 *   node scripts/assert-casts.mjs <file>...  # count only these files
 *
 * Exit code is the alarm: 0 every swept file is at or under its pinned count, 1
 * otherwise. A file with no pin is pinned at zero, so a new double cast fails
 * anywhere in the sweep without requiring old ones to be fixed first.
 *
 * WHY AN AST AND NOT A GREP. A double cast is a construct, and a grep matches text.
 * The false positive is not hypothetical and it is not rare -- it is simply what a
 * comment about a defect looks like to a text matcher -- and it was already true of
 * this repo on both sides of the fix, measured rather than imagined:
 *
 *   at 0dd5e8f,     19 casts in lib/db.ts   grep -c reads 21   (2 matches are comments)
 *   at this commit,  0 casts in lib/db.ts   grep -c reads  3   (3 matches are comments)
 *
 * The first is pinned to a sha and the second deliberately is NOT. This unit is
 * unpushed as it is written, and a cron data commit landing before the push rebases
 * it and rewrites its hashes -- which has orphaned citations in this repo twice, and
 * a hash inside a commit message cannot be corrected afterwards without rewriting the
 * history again. "This commit" survives the rebase; a local sha does not.
 *
 * The grep gets WORSE as the prose explaining the construct gets better, which is the
 * wrong direction for an instrument -- and this file is the extreme case, since a
 * header about double casts is mostly the phrase. Its own text-match count is not
 * written down here for that reason: editing this sentence would change it. An AST
 * cannot make the mistake at all -- a comment is not an expression, and a string
 * literal is not one either -- so its count of this file is 0 however the header is
 * worded.
 *
 * WHAT COUNTS. Exactly the chain `expr as unknown as T` -- a TypeScript AsExpression
 * whose own expression is an AsExpression asserting `unknown`. That is the shape this
 * repo used to gag the compiler on a return type its rows never had. `as any as T` is
 * the same move in a different word and counts too; it appears zero times today, and
 * it is covered so the class cannot regrow under a synonym. A single cast (`row as
 * Bill`) does NOT count: it is a claim the compiler still checks for overlap, not a
 * claim it was told to stop checking.
 *
 * WHY A COUNT IS ENOUGH HERE, when this repo's other two scripts are joins and their
 * headers say a count can only be wrong about how many, never about which. That
 * warning is about counting a PROXY -- a legend-count assertion cannot notice a
 * second component with no legend. This counts the thing itself: every instance of
 * one syntactic construct, enumerated from the AST of every source file in the app,
 * with the alarm at zero. There is no sampled subject for it to be pointed past, and
 * at a floor of zero the count and the join say the same thing.
 *
 * NO DEPENDENCY BEYOND `typescript`, which is already a devDependency here -- unlike
 * assert-layout.mjs and assert-encodings.mjs, this one needs no browser and no server,
 * so it can run in CI beside `tsc --noEmit`.
 */
import ts from "typescript";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");

// The sweep: every directory in web/ that holds hand-written source. Not `.next`
// (generated), not `node_modules`. `scripts` is swept as JS -- it cannot hold a cast
// at all, and it is in the list so that the sweep's scope is the app's source rather
// than the app's typed source.
const ROOTS = ["lib", "components", "app", "scripts"];
const EXTS = [".ts", ".tsx", ".mts", ".mjs", ".js", ".jsx"];

// PINNED PER-FILE FLOORS, and this table is EMPTY ON PURPOSE rather than unwritten.
// The mechanism exists so a file carrying old casts can be pinned at its measured
// count -- a new one then fails anywhere in the sweep without that file's backlog
// having to be cleared first. It holds nothing because the sweep measured nothing to
// pin: 62 files under lib, components, app and scripts, 19 double casts in
// `lib/db.ts` and ZERO in the other 61, all 19 removed in the commit before this one.
// So every file is pinned at the default, which is 0.
//
// A file added here is a debt being recorded, not a rule being relaxed: write the
// count this script measured, and the sha it was measured at, beside it.
export const FLOORS = {};

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (EXTS.some((e) => name.endsWith(e))) out.push(p);
  }
  return out;
}

/** Every `x as unknown as T` / `x as any as T` in one file, as {line, text}. */
export function findDoubleCasts(path) {
  const src = readFileSync(path, "utf8");
  const kind = /\.(mjs|js|jsx)$/.test(path) ? ts.ScriptKind.JSX : ts.ScriptKind.TSX;
  const sf = ts.createSourceFile(path, src, ts.ScriptTarget.ESNext, true, kind);
  const hits = [];

  const widened = (t) =>
    t.kind === ts.SyntaxKind.UnknownKeyword || t.kind === ts.SyntaxKind.AnyKeyword;

  const visit = (node) => {
    if (ts.isAsExpression(node)) {
      // Peel parentheses: `(x as unknown) as T` is the same construct written wide.
      let inner = node.expression;
      while (ts.isParenthesizedExpression(inner)) inner = inner.expression;
      if (ts.isAsExpression(inner) && widened(inner.type)) {
        const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
        hits.push({ line: line + 1, text: node.getText(sf).replace(/\s+/g, " ").slice(0, 90) });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

const args = process.argv.slice(2);
const reportOnly = args.includes("--report");
const explicit = args.filter((a) => !a.startsWith("--"));

const files = explicit.length
  ? explicit
  : ROOTS.flatMap((r) => walk(join(WEB, r))).sort();

let fail = 0;
const counted = [];
for (const f of files) {
  const hits = findDoubleCasts(f);
  const key = relative(WEB, f).split(sep).join("/");
  const floor = FLOORS[key] ?? 0;
  if (hits.length) counted.push([key, hits]);
  if (!explicit.length && !reportOnly && hits.length > floor) {
    fail++;
    console.log(`FAIL ${key}: ${hits.length} double casts, pinned at ${floor}`);
    for (const h of hits) console.log(`       ${key}:${h.line}  ${h.text}`);
  }
}

const scope = explicit.length ? "the named files" : ROOTS.join(", ");
console.log(`\nassert-casts swept ${files.length} file(s) under ${scope}`);
if (counted.length) {
  for (const [key, hits] of counted) {
    console.log(`  ${String(hits.length).padStart(3)}  ${key}`);
    if (explicit.length || reportOnly) for (const h of hits) console.log(`       :${h.line}  ${h.text}`);
  }
} else {
  console.log("  zero double casts");
}
if (!explicit.length && !reportOnly) {
  console.log(fail ? `\n${fail} file(s) over their pin` : "\nall files at or under their pin");
  process.exit(fail ? 1 : 0);
}
