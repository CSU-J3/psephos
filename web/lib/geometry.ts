// Point-in-polygon over the committed Albers path data.
//
// This exists so the map's label placement can be ASSERTED rather than eyeballed. The
// handoff requires that all four edge midpoints of each label box fall inside their
// state; that is a geometric claim and it needs a geometric test, not a screenshot.
//
// THE PATHS ONLY USE M, L AND Z. The generator emitted integer coordinates with no
// curves, so the parser handles exactly those three commands and throws on anything
// else rather than silently mis-parsing a shape it does not understand.

export type Point = { x: number; y: number };
export type Ring = Point[];

/**
 * Rings under this area are dropped before any parity test.
 *
 * NOT AN OPTIMISATION -- a correctness fix. The simplified paths carry degenerate
 * near-zero-area slivers (MI 9, FL 9, WI 10, NC 2, OH 2 by the handoff's count), and an
 * even-odd test counts a crossing through one of them like any other. Left in, they
 * flip parity along whole scanlines and put Florida's label offshore.
 */
export const MIN_RING_AREA = 30;

/** Parse an SVG path of M/L/Z commands into closed rings. */
export function parseRings(d: string): Ring[] {
  const rings: Ring[] = [];
  let current: Ring = [];
  // Tokens look like "M648,492", "L689,380", "Z". Matched on ANY command letter, not
  // just the three supported ones -- with a narrower class an unsupported command is
  // swallowed as coordinates and the guard below can never fire, which is how a
  // mis-parse becomes a wrong shape instead of an error.
  const tokens = d.match(/[A-Za-z][^A-Za-z]*/g);
  if (!tokens) return rings;
  for (const tok of tokens) {
    const cmd = tok[0].toUpperCase();
    if (cmd === "Z") {
      if (current.length) rings.push(current);
      current = [];
      continue;
    }
    if (cmd !== "M" && cmd !== "L") {
      throw new Error(`geometry: unsupported path command ${cmd} in ${tok.slice(0, 20)}`);
    }
    const nums = tok
      .slice(1)
      .split(/[\s,]+/)
      .filter(Boolean)
      .map(Number);
    if (nums.length % 2 !== 0 || nums.some(Number.isNaN)) {
      throw new Error(`geometry: bad coordinates in ${tok.slice(0, 24)}`);
    }
    if (cmd === "M" && current.length) {
      rings.push(current);
      current = [];
    }
    for (let i = 0; i < nums.length; i += 2) current.push({ x: nums[i], y: nums[i + 1] });
  }
  if (current.length) rings.push(current);
  return rings;
}

/** Absolute shoelace area. */
export function ringArea(ring: Ring): number {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    a += ring[j].x * ring[i].y - ring[i].x * ring[j].y;
  }
  return Math.abs(a / 2);
}

/** Rings worth testing against: the slivers removed. */
export function significantRings(d: string, minArea = MIN_RING_AREA): Ring[] {
  return parseRings(d).filter((r) => r.length >= 3 && ringArea(r) >= minArea);
}

/** Even-odd point-in-polygon across a set of rings. */
export function pointInRings(p: Point, rings: readonly Ring[]): boolean {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i];
      const b = ring[j];
      const straddles = a.y > p.y !== b.y > p.y;
      if (!straddles) continue;
      const xAt = ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x;
      if (p.x < xAt) inside = !inside;
    }
  }
  return inside;
}

/** Convenience: is this point inside the state whose path this is? */
export function pointInPath(p: Point, d: string): boolean {
  return pointInRings(p, significantRings(d));
}

export type Box = { x: number; y: number; width: number; height: number };

/**
 * The four EDGE MIDPOINTS of a box -- not its corners.
 *
 * Corners are the wrong probe for a label sitting in a state: a box centred well inside
 * a narrow state can still poke a corner over a border while reading perfectly, and a
 * corner test would reject it. Edge midpoints test that the box is centred in real
 * interior on every side, which is the property that actually matters.
 */
export function edgeMidpoints(b: Box): Point[] {
  return [
    { x: b.x + b.width / 2, y: b.y }, // top
    { x: b.x + b.width / 2, y: b.y + b.height }, // bottom
    { x: b.x, y: b.y + b.height / 2 }, // left
    { x: b.x + b.width, y: b.y + b.height / 2 }, // right
  ];
}

/** Axis-aligned overlap, touching edges permitted. */
export function boxesOverlap(a: Box, b: Box): boolean {
  return (
    a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
  );
}

/** Bounding box of every significant ring in a path. */
export function pathBounds(d: string): Box {
  const rings = significantRings(d);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const r of rings) {
    for (const p of r) {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    }
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}
