"""Pure canvas sizing. Keep the browser mirror and fixture tests in step."""
import math

CANVAS_MULTIPLE = 16
CANVAS_RATIO_WEIGHT = 6.0


def dims_for(aspect, mp, multiple=CANVAS_MULTIPLE):
    """aspect string + megapixels -> (w, h), both multiples of `multiple`.

    The height is derived from the SNAPPED width, not the ideal one. Rounding
    each axis independently off the unsnapped ideal let them drift apart and
    put up to 0.7% of shape error into the ratio - 3:4 at 2 MP came out
    1232x1632, which is not 3:4. Candidates either side of the ideal are then
    scored, so a width one step over that lands the ratio exactly is preferred
    to one that merely lands the area.
    """
    aw, ah = (float(x) for x in aspect.split(" ")[0].split(":"))
    ratio = aw / ah
    target = max(0.0, float(mp)) * 1_000_000
    step = max(1, int(multiple))
    if target <= 0 or ratio <= 0:
        return step, step
    # Half-UP, not Python's bankers rounding: the composer mirrors this function
    # in JS, where Math.round is half-up, and 4:3 lands on an exact .5 often
    # enough that round() would hand the two a different canvas.
    snap = lambda v: math.floor(v + 0.5)
    centre = max(1, snap((target * ratio) ** 0.5 / step))
    best = None
    for offset in range(-3, 4):
        w = (centre + offset) * step
        if w < step:
            continue
        h = max(step, snap(w / ratio / step) * step)
        score = (abs(w * h - target) / target
                 + CANVAS_RATIO_WEIGHT * abs((w / h) - ratio) / ratio)
        key = (round(score, 12), -(w * h))    # ties go to the larger canvas
        if best is None or key < best[0]:
            best = (key, w, h)
    return int(best[1]), int(best[2])
