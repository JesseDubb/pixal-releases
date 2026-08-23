import { useMemo } from "react";

// AspectShape — a tiny outlined rectangle standing in for a ratio, so a grid
// of "1:1 / 2:3 / 16:9" can be read as shapes instead of parsed as arithmetic.
//
// Jesse asked for it in these words: "can you show little squares that
// represent the aspect ratios? rectangles for the tall and wides that all kind
// of match a subtle very subtle corner radius on them and match the stroke of
// the other icons."
//
// Ported from Lumen's AspectPicker.jsx, which already had exactly this as an
// inner helper — the same 1.5px stroke and 3px radius he described. The rest of
// that component is a five-option social dropdown behind a PickerPill and is
// the wrong control for Pixal's eight-ratio canvas grid, so this is the half
// that travels. Improvements over the original, to be raised back against
// Lumen rather than left forked here:
//
//   - `size` is a prop. Lumen hardcodes a 32px box with a 22px cap, which is
//     right beside a dropdown row and too heavy inside a 32px-tall chip.
//   - the box is square at `size` regardless of ratio, so a row of these keeps
//     one baseline and one left edge no matter what shapes are in it.
//   - `currentColor` rather than a fixed token, so the shape inherits the
//     selected/unselected colour of whatever control holds it instead of
//     staying one grey while its label changes.
//
// "auto" reads as a dashed square: no ratio chosen yet, not a 1:1 choice.
export const AspectShape = ({ ratio, size = 16 }) => {
  const dims = useMemo(() => {
    const max = Math.round(size * 0.82);
    if (!ratio || ratio === "auto") return { w: max, h: max, dashed: true };
    const m = String(ratio).match(/(\d+)\s*:\s*(\d+)/);
    if (!m) return { w: max, h: max };
    const w = Number(m[1]);
    const h = Number(m[2]);
    if (!w || !h) return { w: max, h: max };
    // Scale to fill one axis: the wider side is the one that maxes out, so a
    // 21:9 and a 9:16 are the same "size" and differ only in shape.
    return w >= h
      ? { w: max, h: Math.max(3, Math.round((h / w) * max)) }
      : { w: Math.max(3, Math.round((w / h) * max)), h: max };
  }, [ratio, size]);
  return (
    <span aria-hidden="true" style={{
      width: size, height: size, flexShrink: 0,
      display: "inline-flex", alignItems: "center", justifyContent: "center",
    }}>
      <span style={{
        width: dims.w, height: dims.h,
        border: `1.5px ${dims.dashed ? "dashed" : "solid"} currentColor`,
        borderRadius: 3, opacity: 0.75,
      }} />
    </span>
  );
};
