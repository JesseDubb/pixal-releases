// block-mark.js — the block P as THREE.Shapes, from the same corner table as
// make_app_icon.py's BLOCK_HULL / BLOCK_BUBBLE / BLOCK_CHIP and
// brand/pixal-block.svg. One source of truth for the silhouette; if this and
// the icon ever disagree, one of them was hand-edited.
//
// Authored in the SVG's own space (0..100, y DOWN) so the numbers can be read
// straight off the path, then flipped to three.js' y-up on the way out.
//
// `steps` is the arc resolution and it is the whole cost knob. ExtrudeGeometry's
// own `curveSegments` is bypassed on purpose: the arcs are flattened here, so
// the triangle count is something we set rather than something we hope for. At
// 46px on screen a 5.5-unit radius is under two pixels, and steps=2 is
// indistinguishable from steps=14 while costing a seventh of the geometry.

const HULL = [
  [[77.7, 0.0], 5.5], [[77.7, 22.3], 0], [[100.0, 22.3], 5.5],
  [[100.0, 77.7], 5.5], [[77.7, 77.7], 0], [[77.7, 100.0], 5.5],
  [[0.0, 100.0], 5.5], [[0.0, 22.3], 5.5], [[22.3, 22.3], 0],
  [[22.3, 0.0], 5.5],
];
const BUBBLE = [[22.3, 22.3], [77.7, 22.3], [77.7, 77.7], [41.0, 77.7], [22.3, 100.0]];
const CHIP = [36.4, 37.3, 63.6, 62.7];
const CHIP_R = 3.5;

// Flatten a ((x, y), radius) corner table into a closed polyline.
const flatten = (corners, steps) => {
  const pts = [];
  const n = corners.length;
  for (let i = 0; i < n; i++) {
    const [[cx, cy], r] = corners[i];
    if (r <= 0) { pts.push([cx, cy]); continue; }
    const dirs = [corners[(i - 1 + n) % n][0], corners[(i + 1) % n][0]].map(([ox, oy]) => {
      const dx = ox - cx, dy = oy - cy, len = Math.hypot(dx, dy);
      return [dx / len, dy / len];
    });
    const [[ax, ay], [bx, by]] = dirs;
    const mx = cx + r * (ax + bx), my = cy + r * (ay + by);   // arc centre
    const a0 = Math.atan2(cy + r * ay - my, cx + r * ax - mx);
    const a1 = Math.atan2(cy + r * by - my, cx + r * bx - mx);
    // the short way round, so a corner never sweeps 270 degrees
    const sweep = ((a1 - a0 + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
    for (let s = 0; s <= steps; s++) {
      const a = a0 + sweep * (s / steps);
      pts.push([mx + r * Math.cos(a), my + r * Math.sin(a)]);
    }
  }
  return pts;
};

const rectCorners = ([x0, y0, x1, y1], r) =>
  [[[x1, y0], r], [[x1, y1], r], [[x0, y1], r], [[x0, y0], r]];

/**
 * @returns {{hull: THREE.Shape, chip: THREE.Shape, size: number}}
 *   `hull` carries the speech-bubble counter as a hole. `chip` is the little
 *   picture inside that counter and has to be its OWN shape: it is an island
 *   within a hole, which a single Shape cannot express.
 */
export const blockShapes = (THREE, { steps = 2, size = 2.4 } = {}) => {
  const k = size / 100;
  const to = ([x, y]) => new THREE.Vector2(x * k - size / 2, size / 2 - y * k);

  const hull = new THREE.Shape(flatten(HULL, steps).map(to));
  hull.holes.push(new THREE.Path(BUBBLE.map(to)));
  const chip = new THREE.Shape(flatten(rectCorners(CHIP, CHIP_R), steps).map(to));
  return { hull, chip, size };
};
