// Albers USA geometry for the records map, plus the label anchors and the one
// resolution function every consumer must go through.
//
// PROVENANCE, stated as what is known rather than as a command that would run.
// `us-states.json` arrived with handoff 87 (as docs/design/psephos-us-states-albers.json,
// md5 ebf495e85c6579150c5dfa8312ac7a77, copied here byte-identical). Per that handoff it
// was generated from us-atlas@3.0.1's `states-albers-10m.json`, simplified with
// topojson-simplify at weight 4, on a 975x610 canvas with integer coordinates, one
// {ab, name, d, cx, cy} per feature.
//
// THE GENERATING SCRIPT ITSELF WAS NOT PRESERVED. Those are the inputs and parameters,
// not a reproduction recipe, and the difference matters: rebuilding from them would
// likely produce a near-identical file, but "likely" is not the same as byte-stable, and
// the label anchors below were measured against THESE paths. Treat the committed file as
// the source of truth. If it ever must be regenerated, re-derive the anchors in the same
// pass and re-run the inside-the-polygon assertions -- do not carry the old numbers over.
//
// Committed as data rather than fetched, so the map has no runtime dependency and no
// map library. 51 features: 50 states plus DC. Do not hand-edit the `d` strings.

import geometry from "@/lib/us-states.json";

export type StateFeature = {
  /** Two-letter postal code. Unique across all 51 features. */
  ab: string;
  /** Full name as us-atlas spells it -- "District of Columbia", not "DC". */
  name: string;
  /** SVG path data in the 975x610 Albers canvas. */
  d: string;
  cx: number;
  cy: number;
};

export const US_STATES: StateFeature[] = geometry as StateFeature[];

/** The count is asserted, not assumed: a truncated import must fail here, not render
 *  a map that is quietly missing jurisdictions. See map.test.ts. */
export const FEATURE_COUNT = 51;

// Where a horizontal label fits INSIDE the polygon. These are NOT centroids: Michigan's
// centroid lands in Lake Michigan, and Florida's and Wisconsin's are little better.
// Derived by scanline over the same path data -- for each row the widest run inside the
// polygon, keeping only rows whose neighbours +/-10 units still contain that run with at
// least 42% half-width either side of the midpoint, after dropping rings under 30 units^2.
// That last step matters: the simplified paths carry degenerate zero-area slivers
// (MI 9, FL 9, WI 10, NC 2, OH 2) that corrupt even-odd parity and otherwise put
// Florida's label offshore.
//
// Only the nine bill-tracked states have one, because only they take a dot and a count.
export const LABEL_ANCHOR: Record<string, readonly [number, number]> = {
  AZ: [199.1, 408],
  FL: [784.8, 520],
  GA: [744.9, 443],
  MI: [687.6, 199],
  NC: [800, 345],
  OH: [724, 238],
  PA: [808.8, 229],
  TX: [423.3, 464],
  WI: [590.6, 154],
};

const BY_AB = new Map(US_STATES.map((f) => [f.ab, f]));
const BY_NAME = new Map(US_STATES.map((f) => [f.name, f]));

/**
 * Resolve a stored `cases.state` value to the feature the map draws.
 *
 * Two forms are live and both are load-bearing. `cases.state` holds the full name for
 * every state ("Maine", "West Virginia") but the bare code for the District of Columbia
 * ("DC"), whose feature is named "District of Columbia". So name is tried first, then
 * code.
 *
 * IT DOES NOT ACCEPT THE TRACKER'S SUFFIXED FORM, and that is deliberate.
 * `data/doj_cases.json` carries one row per docket and disambiguates two Georgia suits
 * inside the state field as "Georgia (1)" / "Georgia (2)", but
 * `collectors.litigation.normalize_state` strips that at the boundary where the artifact
 * enters the database. 32 artifact rows collapse to 31 stored values and `cases.state`
 * has never held a suffixed one. Accepting the suffix here would be tolerating input the
 * schema cannot produce, and a test asserting it resolves would pass while proving
 * nothing -- the same shape as a grep whose expected result is zero.
 *
 * Throws on an unmapped value. That is the point: a jurisdiction dropped from a 51-cell
 * map leaves no gap a reader can see, so silence is the worst available failure. Use
 * `tryResolveState` where a miss is legitimately expected.
 */
export function resolveState(value: string): StateFeature {
  const found = BY_NAME.get(value) ?? BY_AB.get(value);
  if (!found) {
    throw new Error(
      `map: no geometry for state ${JSON.stringify(value)}. ` +
        `Expected a full name ("Maine") or "DC". If this is the tracker's suffixed ` +
        `form ("Georgia (1)"), it reached the map unnormalized -- fix it at the ` +
        `collector boundary, not here.`,
    );
  }
  return found;
}

/** Resolution without the throw, for callers where absence is a real answer. */
export function tryResolveState(value: string): StateFeature | undefined {
  return BY_NAME.get(value) ?? BY_AB.get(value);
}

/**
 * Split all 51 features by whether a stored state value resolves to them.
 *
 * Every count the board renders is derived through this, never transcribed. The sued /
 * never-sued split was 31/20 on 2026-08-18 and 25/6 for the live/ended split a week
 * earlier; a literal pair goes stale exactly the way the figures this project keeps
 * correcting go stale. If a number is not derived at render, it does not ship.
 */
export function partitionByStates(values: readonly string[]): {
  sued: StateFeature[];
  neverSued: StateFeature[];
} {
  const hit = new Set<string>();
  for (const v of values) hit.add(resolveState(v).ab);
  return {
    sued: US_STATES.filter((f) => hit.has(f.ab)),
    neverSued: US_STATES.filter((f) => !hit.has(f.ab)),
  };
}
