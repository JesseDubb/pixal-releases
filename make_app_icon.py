r"""Pixal app icon - the P, cut to the ComfyUI icon's own geometry.

The brief was "make it look like that candy glass ComfyUI one", so the shape
language was measured off web/icons/comfy-512.png rather than eyeballed:

  puck    superellipse corners, R = 0.2637 x side, exponent 2.5. A circular
          radius is visibly rounder - at 1/8 down the edge the real icon is
          11px in where a circle would be 20.
  glyph   cap height 324/512 (y 97..421), monolinear stroke 106, sheared right
          by 0.29 px per px - both edges of the C's spine drift at that rate.
  ink     flat, two colours, no gloss. "Candy" is the palette, not a gradient.

Only the weight is ours: a P can't wear a 106 stroke on a 324 cap (arm +
counter + arm + leg doesn't fit), so the stem comes down to 92 and the arms to
74. Colours are Pixal's own - #1E32E0 and #D6F32F, not ComfyUI's blue/yellow.

Emits, all from the one parameter block:
  web/icons/block-tile.svg                 LIVE favicon + chrome --app= window
                                           icon: vector, so the taskbar gets a
                                           real rasterisation instead of a
                                           resampled PNG
  web/icons/block-mark.svg                 bare mark in currentColor
  web/icons/block-512.png, block-192.png   LIVE PWA icons, PNG favicon fallback
  web/icons/pixal-block.ico                LIVE desktop shortcut (16..256)
  web/icons/p-512.png, p-192.png   the retired leaning P, kept for reference
  web/icons/pixal-p.ico            "
  web/icons/p-tile.svg             puck + glyph, for favicons
  web/icons/p-mark.svg             bare glyph, for the site lockup (the site
                                   has no radii anywhere, so it gets no puck)

The block-* set is what web/index.html, web/manifest.webmanifest, web/sw.js and
install\pixal_install.py point at. The p-* set is dead art on disk - see "the
block mark" below for why the leaning P was retired.

NOT the three.js puck in the nav rail: that keeps ComfyUI's C, by Jesse's call
on 2026-08-15 - the C simply reads better as extruded glass. `outline_paths()`
below still exists because it is the hard part (walking the union into one
contour with a real hole, since a mesh has no winding rule to punch with), and
it is what to call if the puck ever changes its mind.

Filename rule: Chrome's favicon DB caches by URL and resurrects old art -
whenever the art changes, change the FILENAME here and in web/index.html,
web/manifest.webmanifest, and web/sw.js, then build with web\build.bat. The
same applies to the .ico: Windows caches shortcut icons by path, so a new
picture at the old filename shows up as the old picture until the icon cache
is cleared. Rename it and point install\pixal_install.py at the new name.

web/icons/comfy-512.png stays in the tree as the reference this was measured
against, not because anything loads it.

Run:  .venv\Scripts\python.exe make_app_icon.py
"""
import io
import math
import os
from PIL import Image, ImageDraw

BLUE = (30, 50, 224, 255)       # --blue   #1E32E0
CHART = (214, 243, 47, 255)     # --signal #D6F32F
S = 512                         # design units; master renders at S * Q
Q = 8                           # the puck is a filled polygon, so AA is all
                                # supersampling - 8x is where the edge stops
                                # showing facets after the downsample

PUCK_R, PUCK_N = 0.2637, 2.5    # measured off comfy-512.png
LEAN = 0.29                     # ditto
CAP, TOP = 324, 97              # glyph box, ditto

P = dict(stem=92,               # ours: the C's 106 leaves no room for a leg
         arm=74,                # bowl arms, a touch lighter than the stem
         bowl_h=224,
         width=256,             # = stem + counter + arm, so the bowl's right
                                # wall weighs exactly what the arms do
         counter_w=90,
         r=0.38,                # stem corner radius, x stem
         bowl_r=0.30,           # bowl end radius, x bowl_h
         counter_r=0.30)        # x counter height

# The correct lean throws the bowl right at the top and the leg left at the
# bottom, so a P spreads wider than a C of the same cap height. 0.96 hands back
# the difference and lands the glyph on the same margins the ComfyUI icon uses.
GLYPH_SCALE = 0.96

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icons")


# --------------------------------------------------------------- geometry --

def superellipse_corner(R, n=PUCK_N, k=9):
    """Top-left corner of the puck, from (0, R) to (R, 0).

    (1 - x/R)^n + (1 - y/R)^n = 1. At n=2 this is a circle; the real icon
    measures n=2.5, which is why it looks flatter than a rounded rectangle.
    """
    pts = []
    for i in range(k + 1):
        u = 1 - i / k
        pts.append((R * (1 - u), R * (1 - (1 - u ** n) ** (1 / n))))
    return pts


def puck_outline(side, k=9):
    """The whole puck as a point list, clockwise from the top-left corner's end.

    k=9 is plenty for the SVG (Catmull-Rom smooths between the samples); the
    raster fill gets a straight polygon, so it asks for many more.
    """
    R = side * PUCK_R
    tl = superellipse_corner(R, k=k)
    pts = list(tl)                                              # (0,R) -> (R,0)
    pts += [(side - x, y) for x, y in reversed(tl)]             # top-right
    pts += [(side - x, side - y) for x, y in tl]                # bottom-right
    pts += [(x, side - y) for x, y in reversed(tl)]             # bottom-left
    return pts


def glyph_parts():
    """Stem, bowl and counter as (x0, y0, x1, y1, corner-radii) in design units.

    The stem owns the top-left corner; the bowl starts where the stem's corner
    stops curving, with a square top-left, so the two share one flat top edge
    instead of fighting over the shoulder.
    """
    stem, arm = P["stem"], P["arm"]
    bowl_h, width, cw = P["bowl_h"], P["width"], P["counter_w"]
    ch = bowl_h - 2 * arm
    r = stem * P["r"]
    rb = bowl_h * P["bowl_r"]
    rc = ch * P["counter_r"]

    x0, y0 = X0, TOP
    parts = [
        # x0, y0, x1, y1, (tl, tr, br, bl)
        (x0, y0, x0 + stem, y0 + CAP, (r, r, r, r)),                    # stem
        (x0 + r, y0, x0 + width, y0 + bowl_h, (0, rb, rb, 0)),          # bowl
    ]
    # The counter starts exactly at the stem's right edge and never crosses it.
    # It has to: in the SVG the three slabs are one nonzero-wound path, so a
    # counter lying over both the stem and the bowl would score +2-1 and fill
    # back in. Raster and vector then agree by construction rather than by luck.
    counter = (x0 + stem, y0 + arm, x0 + stem + cw, y0 + arm + ch,
               (rc, rc, rc, rc))

    s, cy = GLYPH_SCALE, TOP + CAP / 2      # scale about the shear's own axis
    def sc(p):
        a, b, c, e, rr = p
        return (X0 + (a - X0) * s, cy + (b - cy) * s,
                X0 + (c - X0) * s, cy + (e - cy) * s, tuple(v * s for v in rr))
    return [sc(p) for p in parts], sc(counter)


X0 = 0.0        # set by _centre() below - the shear moves the optical centre


def _draw_glyph(side):
    """Render the glyph mask at `side` px, sheared, in one pass."""
    k = side / S
    m = Image.new("L", (side, side), 0)
    d = ImageDraw.Draw(m)
    parts, counter = glyph_parts()

    def slab(p, fill):
        x0, y0, x1, y1, rr = p
        # PIL takes one radius plus a corners mask, which is enough here: every
        # slab uses either one radius or one radius and square corners.
        rad = max(rr)
        corners = tuple(bool(c) for c in rr)
        rad = min(rad, (x1 - x0) / 2 - 0.5, (y1 - y0) / 2 - 0.5)
        d.rounded_rectangle((x0 * k, y0 * k, x1 * k, y1 * k),
                            radius=rad * k, corners=corners, fill=fill)

    for p in parts:
        slab(p, 255)
    slab(counter, 0)
    # PIL's AFFINE maps output back to input, so the signs are the inverse of
    # the SVG matrix that has to produce the same picture. Getting this
    # backwards mirrors the lean, which reads as a backslant next to the C.
    return m.transform(m.size, Image.AFFINE,
                       (1, LEAN, -LEAN * (TOP + CAP / 2) * k, 0, 1, 0),
                       resample=Image.BICUBIC)


def _centre():
    """Pick X0 so the sheared glyph sits centred.

    Solved by measuring, not algebra: the shear spreads the outline by
    LEAN*CAP but the corner radii eat some of it back, so the analytic answer
    is wrong by ~20px - enough to see.

    The probe starts at 150 rather than 0 because the shear pulls the shoulder
    left of the canvas from a zero origin, and a clipped probe measures a
    narrower glyph and centres it wrong.
    """
    global X0
    X0 = 150.0
    box = _draw_glyph(S).getbbox()
    X0 += (S - (box[2] - box[0])) / 2 - box[0]


def master():
    _centre()
    side = S * Q
    img = Image.new("RGBA", (side, side), BLUE)
    m = Image.new("L", (side, side), 0)
    ImageDraw.Draw(m).polygon(puck_outline(side, k=96), fill=255)
    img.putalpha(m)
    g = Image.new("RGBA", (side, side), CHART)
    g.putalpha(_draw_glyph(side))
    img.alpha_composite(g)
    return img


# -------------------------------------------------------------------- svg --

def fit_corner(R, n=PUCK_N):
    """One cubic per corner, fitted to the superellipse. Returns (offset, error).

    The corner runs (0,R) to (R,0) with a vertical tangent at one end and a
    horizontal one at the other, so the only free parameter is how far the two
    control points sit from the ends. Sweeping it beats guessing 0.5523 (the
    circle's number, which is visibly too round here).
    """
    def err(a):
        worst = 0.0
        for i in range(1, 40):
            t = i / 40
            u = 1 - t
            x = 3 * u * t * t * (R - a) + t ** 3 * R
            y = u ** 3 * R + 3 * u * u * t * (R - a)
            fx, fy = max(0.0, 1 - x / R), max(0.0, 1 - y / R)
            g = fx ** n + fy ** n - 1
            grad = (n / R) * ((fx ** (n - 1)) ** 2 + (fy ** (n - 1)) ** 2) ** 0.5
            worst = max(worst, abs(g) / max(grad, 1e-9))
        return worst

    best = min((err(R * k / 2000), R * k / 2000) for k in range(1, 2000))
    return best[1], best[0]


def puck_path(side, prec=2):
    """The puck outline: four straight edges and four fitted corners."""
    R = side * PUCK_R
    a, e = fit_corner(R)
    f = lambda v: f"{round(v, prec):g}"
    S_ = side
    d = [f"M{f(R)} 0"]                                       # top edge start
    for (ex, ey), (c1, c2), (px, py) in (
        ((S_ - R, 0), ((S_ - R + a, 0), (S_, R - a)), (S_, R)),          # TR
        ((S_, S_ - R), ((S_, S_ - R + a), (S_ - R + a, S_)), (S_ - R, S_)),  # BR
        ((R, S_), ((R - a, S_), (0, S_ - R + a)), (0, S_ - R)),          # BL
        ((0, R), ((0, R - a), (R - a, 0)), (R, 0)),                      # TL
    ):
        d.append(f"L{f(ex)} {f(ey)}")
        d.append(f"C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(px)} {f(py)}")
    return " ".join(d) + "Z", e


def _slab_path(p, cw=True, prec=2):
    """Rounded rect with per-corner radii, as one subpath.

    cw=False reverses the winding so a subpath punches a hole under
    fill-rule:nonzero - which is how the counter stays a counter while the
    stem and bowl still union instead of cancelling (evenodd would eat their
    overlap).
    """
    x0, y0, x1, y1, (tl, tr, br, bl) = p
    f = lambda v: f"{round(v, prec):g}"
    seg = []
    if cw:
        seg.append(f"M{f(x0 + tl)} {f(y0)}")
        seg.append(f"H{f(x1 - tr)}")
        if tr: seg.append(f"A{f(tr)} {f(tr)} 0 0 1 {f(x1)} {f(y0 + tr)}")
        seg.append(f"V{f(y1 - br)}")
        if br: seg.append(f"A{f(br)} {f(br)} 0 0 1 {f(x1 - br)} {f(y1)}")
        seg.append(f"H{f(x0 + bl)}")
        if bl: seg.append(f"A{f(bl)} {f(bl)} 0 0 1 {f(x0)} {f(y1 - bl)}")
        seg.append(f"V{f(y0 + tl)}")
        if tl: seg.append(f"A{f(tl)} {f(tl)} 0 0 1 {f(x0 + tl)} {f(y0)}")
    else:
        seg.append(f"M{f(x0 + tl)} {f(y0)}")
        if tl: seg.append(f"A{f(tl)} {f(tl)} 0 0 0 {f(x0)} {f(y0 + tl)}")
        seg.append(f"V{f(y1 - bl)}")
        if bl: seg.append(f"A{f(bl)} {f(bl)} 0 0 0 {f(x0 + bl)} {f(y1)}")
        seg.append(f"H{f(x1 - br)}")
        if br: seg.append(f"A{f(br)} {f(br)} 0 0 0 {f(x1)} {f(y1 - br)}")
        seg.append(f"V{f(y0 + tr)}")
        if tr: seg.append(f"A{f(tr)} {f(tr)} 0 0 0 {f(x1 - tr)} {f(y0)}")
    return " ".join(seg) + "Z"


def glyph_svg_path():
    parts, counter = glyph_parts()
    return " ".join([_slab_path(p) for p in parts] + [_slab_path(counter, cw=False)])


def svg_files():
    _centre()
    shear = f"matrix(1 0 {-LEAN} 1 {round(LEAN * (TOP + CAP / 2), 2):g} 0)"
    glyph = (f'<g transform="{shear}"><path fill="{{ink}}" '
             f'd="{glyph_svg_path()}"/></g>')

    def head(vb):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
                f'fill="none">')

    outline, fit_err = puck_path(S)
    tile = (head(f"0 0 {S} {S}") + f'<path fill="#1E32E0" d="{outline}"/>'
            + glyph.format(ink="#D6F32F") + "</svg>")

    # The bare mark gets a viewBox cropped to the glyph, measured off the same
    # mask the PNGs come from. Left in a 512 square it would sit at 60% of its
    # own box and render small next to whatever text it is set beside.
    a, b, c, e = _draw_glyph(S).getbbox()
    mark = (head(f"{a} {b} {c - a} {e - b}")
            + glyph.format(ink="currentColor") + "</svg>")
    return tile, mark, fit_err


# ---------------------------------------------------------------- three.js --

def _arc(cx, cy, r, a0, a1, steps=14):
    """Points along a corner arc, angles in degrees, screen space (y down)."""
    import math
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
            for i in range(steps + 1)]


def outline_paths():
    """The P as a flat outer contour plus its counter, for extrusion.

    The SVG gets away with three overlapping slabs and a winding rule; a mesh
    needs one real outline, so the union is walked by hand here. The only
    non-obvious vertex is where the bowl's underside meets the stem's right
    edge - a hard concave corner, kept sharp because that is what the raster
    has.
    """
    _centre()
    (stem, bowl), counter = glyph_parts()
    sx0, sy0, sx1, sy1 = stem[:4]
    r = stem[4][0]
    bx1, by1 = bowl[2], bowl[3]
    by0, rb = bowl[1], bowl[4][1]
    cx0, cy0, cx1, cy1 = counter[:4]
    rc = counter[4][0]

    outer = []
    outer += _arc(sx0 + r, sy0 + r, r, 180, 270)          # stem top-left
    outer += [(bx1 - rb, by0)]
    outer += _arc(bx1 - rb, by0 + rb, rb, 270, 360)       # bowl top-right
    outer += [(bx1, by1 - rb)]
    outer += _arc(bx1 - rb, by1 - rb, rb, 0, 90)          # bowl bottom-right
    outer += [(sx1, by1), (sx1, sy1 - r)]                 # underside, then down
    outer += _arc(sx1 - r, sy1 - r, r, 0, 90)             # stem bottom-right
    outer += [(sx0 + r, sy1)]
    outer += _arc(sx0 + r, sy1 - r, r, 90, 180)           # stem bottom-left
    outer += [(sx0, sy0 + r)]

    hole = []
    hole += _arc(cx0 + rc, cy0 + rc, rc, 180, 270)
    hole += [(cx1 - rc, cy0)]
    hole += _arc(cx1 - rc, cy0 + rc, rc, 270, 360)
    hole += [(cx1, cy1 - rc)]
    hole += _arc(cx1 - rc, cy1 - rc, rc, 0, 90)
    hole += [(cx0 + rc, cy1)]
    hole += _arc(cx0 + rc, cy1 - rc, rc, 90, 180)

    def place(pts):
        """Shear, then to tile units: origin at the tile's centre, y up, the
        whole 512 tile spanning 1.0. The puck can then scale by its own slab
        width and land the glyph at exactly the proportion the flat icon uses."""
        cy = TOP + CAP / 2
        out = []
        for x, y in pts:
            sx = x - LEAN * (y - cy)
            out.append((round((sx - S / 2) / S, 4), round(-(y - S / 2) / S, 4)))
        # drop consecutive duplicates left by an arc ending on a line's start
        return [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]

    def wind(pts, ccw):
        """Orient by measured signed area rather than by reasoning about it -
        the y flip reverses handedness and it is easy to talk yourself into
        the wrong answer."""
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                   - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts))) / 2
        return pts if (area > 0) == ccw else pts[::-1]

    return wind(place(outer), True), wind(place(hole), False)


# ------------------------------------------------------- the block mark ----
# The leaning P above was retired on 2026-08-16 ("I hate that P logo - maybe we
# should get away from trying to look like comfyui a little bit"), and borrowing
# ComfyUI's construction language is exactly what made it read as derivative.
# The approved mark is a solid block P whose counter is a speech bubble with a
# tail, a small square sitting inside it: chat in, images out.
#
# It is one contour, transcribed corner by corner from brand/pixal-block.svg so
# the two can never drift: seven convex corners carry a 5.5 radius and the three
# reflex corners stay sharp, which is what keeps the arm and the stem reading as
# slabs rather than as a blob. Union-of-rounded-rectangles was tried first and
# rounds the reflex corners too, which loses the P entirely.
INK = (17, 20, 1, 255)          # --sig-ink #111401
BLOCK_R = 5.5                   # outer corner radius, in the mark's 100 units
BLOCK_HULL = (((77.7, 0.0), BLOCK_R), ((77.7, 22.3), 0.0),
              ((100.0, 22.3), BLOCK_R), ((100.0, 77.7), BLOCK_R),
              ((77.7, 77.7), 0.0), ((77.7, 100.0), BLOCK_R),
              ((0.0, 100.0), BLOCK_R), ((0.0, 22.3), BLOCK_R),
              ((22.3, 22.3), 0.0), ((22.3, 0.0), BLOCK_R))
BLOCK_BUBBLE = ((22.3, 22.3), (77.7, 22.3), (77.7, 77.7),
                (41.0, 77.7), (22.3, 100.0))  # counter, knocked back out
BLOCK_CHIP = (36.4, 37.3, 63.6, 62.7)         # the picture inside the bubble
BLOCK_CHIP_R = 3.5


def block_hull(steps=16):
    """Flatten BLOCK_HULL's rounded corners into one polygon."""
    pts, n = [], len(BLOCK_HULL)
    for i, (corner, r) in enumerate(BLOCK_HULL):
        if r <= 0:
            pts.append(corner)
            continue
        cx, cy = corner
        out = []
        for other in (BLOCK_HULL[i - 1][0], BLOCK_HULL[(i + 1) % n][0]):
            dx, dy = other[0] - cx, other[1] - cy
            span = math.hypot(dx, dy)
            out.append((dx / span, dy / span))       # unit, corner -> neighbour
        (ax, ay), (bx, by) = out
        mid = (cx + r * (ax + bx), cy + r * (ay + by))   # arc centre
        a0 = math.atan2(cy + r * ay - mid[1], cx + r * ax - mid[0])
        a1 = math.atan2(cy + r * by - mid[1], cx + r * bx - mid[0])
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi   # the short way
        for s in range(steps + 1):
            a = a0 + sweep * s / steps
            pts.append((mid[0] + r * math.cos(a), mid[1] + r * math.sin(a)))
    return pts
TILE_R = 0.22                   # tile corner radius, as a fraction of the side
# 0.62 was measurably too timid in a browser tab - 19% padding a side leaves the
# counter mush at 16px. 0.72 is the ceiling before the arm crowds the tile edge
# and the whole thing stops reading as a tile (0.78 does exactly that). The two
# numbers must stay complementary: INSET = (1 - SCALE) / 2 keeps it centred, and
# the same treatment is mirrored in site/index.html's favicon data URI.
GLYPH_INSET, GLYPH_SCALE = 0.14, 0.72


def _contour(corners, sweep=1):
    """One closed SVG subpath from a ((x, y), radius) corner table.

    Same unit-vector maths as block_hull(), so the vector and the raster are
    generated from one table and cannot drift apart.
    """
    n, out = len(corners), []
    for i, (c, r) in enumerate(corners):
        cx, cy = c
        if r <= 0:
            out.append(f"L{cx:g} {cy:g}")
            continue
        u = []
        for other in (corners[i - 1][0], corners[(i + 1) % n][0]):
            dx, dy = other[0] - cx, other[1] - cy
            span = math.hypot(dx, dy)
            u.append((dx / span, dy / span))
        (ax, ay), (bx, by) = u
        out.append(f"L{cx + r * ax:g} {cy + r * ay:g}")
        out.append(f"A{r:g} {r:g} 0 0 {sweep} {cx + r * bx:g} {cy + r * by:g}")
    d = " ".join(out)
    return "M" + d[1:] + " Z"          # the first lineto is really the moveto


def block_path():
    """The whole mark as one evenodd path: hull, bubble hole, picture chip."""
    x0, y0, x1, y1 = BLOCK_CHIP
    r = BLOCK_CHIP_R
    chip = (((x1, y0), r), ((x1, y1), r), ((x0, y1), r), ((x0, y0), r))
    return " ".join((_contour(BLOCK_HULL),
                     _contour(tuple((p, 0.0) for p in BLOCK_BUBBLE)),
                     _contour(chip)))


def _hex(rgba):
    return "#%02X%02X%02X" % rgba[:3]


def block_svgs():
    """(tile, mark) - the favicon tile, and the bare mark in currentColor.

    The tile is what web/index.html points at: a browser rasterises it at
    whatever size the tab strip or the taskbar asks for, where a single PNG
    gets resampled to mush at 32px.
    """
    d = block_path()
    tile = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<rect width="100" height="100" rx="{TILE_R * 100:g}" '
            f'fill="{_hex(CHART)}"/>'
            f'<g transform="translate({GLYPH_INSET * 100:g} '
            f'{GLYPH_INSET * 100:g}) scale({GLYPH_SCALE:g})">'
            f'<path fill="{_hex(INK)}" fill-rule="evenodd" d="{d}"/></g></svg>\n')
    mark = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
            f'fill="none"><path fill="currentColor" fill-rule="evenodd" '
            f'd="{d}"/></svg>\n')
    return tile, mark


def block_snapped(side, tile=CHART, glyph=INK):
    """A small frame drawn ON the pixel grid rather than downsampled onto it.

    Downsampling the 1024px master to 16 lands every edge of the mark on a
    fraction of a pixel, and antialiasing turns the counter and the chip into
    grey mush. Here every coordinate is rounded to a whole pixel first, so the
    edges are hard: that is the whole difference between a crisp favicon and a
    smudge. The union of the three slabs equals the real contour whenever the
    corners are square, which they are at these sizes - a 0.9px radius only
    blurs a corner it cannot draw.
    """
    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(round(TILE_R * side))
    if r >= 2:
        d.rounded_rectangle((0, 0, side - 1, side - 1), radius=r, fill=tile)
    else:
        d.rectangle((0, 0, side - 1, side - 1), fill=tile)

    x0 = int(round(GLYPH_INSET * side))
    g = int(round(GLYPH_SCALE * side))
    p = lambda v: x0 + int(round(g * v / 100.0))   # mark units -> whole pixels

    for a, b, c, e in ((22.3, 0, 77.7, 100),       # stem
                       (0, 22.3, 100, 77.7),       # arm
                       (0, 22.3, 77.7, 100)):      # bowl + tail rail
        d.rectangle((p(a), p(b), p(c) - 1, p(e) - 1), fill=glyph)
    d.polygon([(p(22.3), p(22.3)), (p(77.7) - 1, p(22.3)),
               (p(77.7) - 1, p(77.7) - 1), (p(41), p(77.7) - 1),
               (p(22.3), p(100) - 1)], fill=tile)
    if p(63.6) - p(36.4) >= 3:            # below 3px the chip is just a smudge
        d.rectangle((p(36.4), p(37.3), p(63.6) - 1, p(62.7) - 1), fill=glyph)
    return img


def write_ico(path, frames):
    """An .ico of PNG-compressed frames, one per size.

    Hand-rolled because PIL's ICO writer only resamples a single image to every
    size, which is exactly the downsampling this is here to avoid.
    """
    import struct
    blobs = []
    for im in frames:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        blobs.append(buf.getvalue())
    out = [struct.pack("<HHH", 0, 1, len(blobs))]
    offset = 6 + 16 * len(blobs)
    for im, blob in zip(frames, blobs):
        w = 0 if im.width >= 256 else im.width
        h = 0 if im.height >= 256 else im.height
        out.append(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32,
                               len(blob), offset))
        offset += len(blob)
    out.extend(blobs)
    with open(path, "wb") as fh:
        fh.write(b"".join(out))


def block_master(side=1024, tile=CHART, glyph=INK):
    """The block P on a rounded tile.

    A tile rather than the bare mark because the counter closes up at 16px and
    a lone P goes to mush in a taskbar; the tile keeps a readable silhouette at
    every size. Drawn oversized and downsampled, since PIL has no antialiasing
    of its own.
    """
    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, side - 1, side - 1), radius=TILE_R * side, fill=tile)

    # mark space (0..100) -> tile pixels
    unit = side * GLYPH_SCALE / 100.0
    off = side * GLYPH_INSET
    at = lambda v: off + v * unit

    d.polygon([(at(x), at(y)) for x, y in block_hull()], fill=glyph)
    d.polygon([(at(x), at(y)) for x, y in BLOCK_BUBBLE], fill=tile)
    x0, y0, x1, y1 = BLOCK_CHIP
    d.rounded_rectangle((at(x0), at(y0), at(x1), at(y1)),
                        radius=BLOCK_CHIP_R * unit, fill=glyph)
    return img


# ------------------------------------------------------------------ write --

if __name__ == "__main__":
    # New filenames on purpose: Chrome caches favicons and PWA art by URL and
    # will happily resurrect the retired mark from an old path.
    block = block_master()
    for size in (512, 192):
        block.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT, f"block-{size}.png"))
    # Small frames are hinted onto the pixel grid; large ones downsample fine.
    write_ico(os.path.join(OUT, "pixal-block.ico"),
              [block_snapped(s) for s in (16, 20, 24, 32, 40, 48)] +
              [block.resize((s, s), Image.LANCZOS) for s in (64, 128, 256)])
    btile, bmark = block_svgs()
    open(os.path.join(OUT, "block-tile.svg"), "w", encoding="utf-8").write(btile)
    open(os.path.join(OUT, "block-mark.svg"), "w", encoding="utf-8").write(bmark)
    print("written: block-512.png, block-192.png, pixal-block.ico, "
          f"block-tile.svg ({len(btile)} bytes), block-mark.svg")

    img = master()
    for size in (512, 192):
        img.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, f"p-{size}.png"))

    ico = os.path.join(OUT, "pixal-p.ico")
    img.resize((256, 256), Image.LANCZOS).save(
        ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    tile, mark, fit_err = svg_files()
    open(os.path.join(OUT, "p-tile.svg"), "w", encoding="utf-8").write(tile)
    open(os.path.join(OUT, "p-mark.svg"), "w", encoding="utf-8").write(mark)


    print("written: p-512.png, p-192.png, pixal-p.ico, p-tile.svg, p-mark.svg")
    print(f"  glyph x0 = {X0:.1f}   svg tile {len(tile)} bytes"
          f"   corner fit off by {fit_err:.2f}px at 512")
