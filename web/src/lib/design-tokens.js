// Color story: Pixal — forked from an earlier token set of mine
// 2026-08-07, own identity. Neutral charcoal room, one electric chartreuse
// signal: the ComfyUI C in the glass puck IS the accent (user-picked against
// the Kimi K-chip reference). Charcoal stays hue-neutral so the chartreuse
// and the renders themselves carry all the color. Amber was the previous
// accent; here the lamp is chartreuse.
//
// Both themes are COMPLETE sets — every component styles through these
// via CSS vars (Chat.jsx applyThemeCss); no literal colors in components.
export const DARK = {
  bg0: "#0B0D0F", bg1: "#101316", bg2: "#15181C", bg3: "#1D2126", bg4: "#272C32",
  text: "#EAEDEF",
  textSec: "rgba(234,237,239,0.65)",
  textTer: "rgba(234,237,239,0.38)",
  textMut: "rgba(234,237,239,0.20)",
  textFaint: "rgba(234,237,239,0.30)",
  cream: "#F5F0E8",
  border: "rgba(234,237,239,0.06)",
  borderHov: "rgba(234,237,239,0.12)",
  borderStr: "rgba(234,237,239,0.18)",
  accent: "#D6F32F", accentHot: "#C1DD1E",
  accentMut: "rgba(214,243,47,0.09)", accentStr: "rgba(214,243,47,0.22)",
  accentInk: "#111401",              // text ON an accent-filled control
  surface: "rgba(16,19,22,0.72)",    // the floating content panel
  surfaceSolid: "rgba(16,19,22,0.93)", // history bento / opaque overlays
  photon: "238,241,235",             // background dot-field rgb triplet
  lamp: "214,243,47",                // top-glow rgb triplet
  success: "#7BB495", successHot: "#6BA585", successMut: "rgba(123,180,149,0.10)",
  warning: "#FBBF24", warningMut: "rgba(251,191,36,0.10)",
  // Destructive — oxblood (inherited from the earlier palette), never tailwind red.
  error: "#8A3040", errorMut: "rgba(138,48,64,0.22)",
  info: "#8AA5BD", infoMut: "rgba(138,165,189,0.10)",
};

export const LIGHT = {
  bg0: "#F4F6F1", bg1: "#FFFFFF", bg2: "#EFF2EB", bg3: "#E5E9DF", bg4: "#D9DED1",
  text: "#15171A", textSec: "rgba(21,23,26,0.66)", textTer: "rgba(21,23,26,0.42)",
  textMut: "rgba(21,23,26,0.24)", textFaint: "rgba(21,23,26,0.34)", cream: "#F5F0E8",
  border: "rgba(21,23,26,0.08)", borderHov: "rgba(21,23,26,0.16)", borderStr: "rgba(21,23,26,0.24)",
  // Chartreuse is too bright to BE ink on white — the light accent is its
  // olive-lime deep end; the electric shade returns on hover states.
  accent: "#6E8B00", accentHot: "#87A812",
  accentMut: "rgba(110,139,0,0.09)", accentStr: "rgba(110,139,0,0.20)",
  accentInk: "#FFFFFF",
  surface: "rgba(255,255,255,0.74)",
  surfaceSolid: "rgba(255,255,255,0.95)",
  photon: "44,52,38",
  lamp: "110,139,0",
  success: "#059669", successHot: "#047857", successMut: "rgba(5,150,105,0.07)",
  warning: "#D97706", warningMut: "rgba(217,119,6,0.07)",
  error: "#6B2935", errorMut: "rgba(107,41,53,0.10)",
  info: "#2563EB", infoMut: "rgba(37,99,235,0.07)",
};

export const FONT = "'Geist', -apple-system, BlinkMacSystemFont, sans-serif";
export const LOGO_FONT = "'Syne', -apple-system, BlinkMacSystemFont, sans-serif";

// Weight hierarchy — single source of truth
export const W = {
  heading: 600,   // page titles, section headings
  nav: 500,       // nav labels, brand names, buttons
  body: 400,      // body text, input values
  label: 300,     // field labels, slugs, hex codes, metadata, timestamps
  logo: 600,      // Syne wordmark — Syne 700 reads boxy, 500 too thin; 600 is the pocket
};

// ──────────────────────────────────────────────────────────────
// GEOMETRIC + MOTION TOKENS
// ──────────────────────────────────────────────────────────────
// Single source of truth for everything that isn't color or font.
// Edit a value here → every component that reads it updates.
//
// Audit baseline (2026-05-04): the codebase used 17 distinct
// radii, 31 font sizes, 42 heights. These scales collapse those
// into deliberate ladders.
//
// Convention: numeric scales use bracket access (`SPACE[12]`),
// component-size scales use semantic keys (`HEIGHT.md`).
// ──────────────────────────────────────────────────────────────

// Type scale — use these instead of bare numbers in fontSize.
// Drops half-pixel sizes (8.5/9.5/10.5/11.5/12.5/13.5/15.5)
// that crept into the codebase via incremental nudges.
export const TYPE = {
  micro: 10,      // SectionLabel, badges (uppercase, letter-spaced)
  label: 11,      // Field labels, kbd, hint text
  ui: 12,         // Buttons, status, inline UI text
  body: 13,       // Form values, table cells, body text
  h3: 14,         // Card titles, page sub-header
  h2: 16,         // Section heading
  h1: 20,         // Page title
  hero: 24,       // Empty-state title, modal title
};

// Pixel-keyed spacing scale — every key IS the pixel value.
// SPACE[12] is 12px. No multiplier math, no fractional keys, no
// surprise gaps. Migrated from a 4px-base multiplier scale on
// 2026-05-04 (single-pass atomic rename across ~1180 callsites).
export const SPACE = {
  2: 2, 4: 4, 6: 6, 8: 8, 10: 10, 12: 12,
  16: 16, 20: 20, 24: 24, 32: 32, 40: 40, 48: 48,
};

// Page chrome — the canonical max-width every top-level page wraps
// its content in, plus the horizontal padding outside the wrapper.
// Pages must `<div style={{maxWidth: PAGE.maxWidth, margin: "0 auto"}}>`
// to feel consistent. One source — change this and every page
// adjusts together.
export const PAGE = {
  maxWidth: 1200,
  padX: 48,        // desktop horizontal page padding
  padXMobile: 20,  // mobile horizontal page padding
  padTop: 40,
  padTopMobile: 24,
  padBottom: 48,
};

// Radius scale — five values, period. The audit found 17
// distinct radii in use; this collapses 6/7/8 → input (6) and
// 9/10/12 → card (8 or dialog 12) etc.
// ── THE CONCENTRIC RADIUS RULE (added 2026-07-12) ──────────────────────────
//
//     inner radius = outer radius − padding
//
// Nested curves must be CONCENTRIC. Get it wrong and the gap between the two
// curves varies around the corner — it reads subtly broken and nobody can name
// why. The design rule: "corner radius has to scale properly… different elements require
// different corner radius to show exact relation to the container it might be in."
//
// This only BITES at generous radii. At chip/input scale (4–8) the error is
// imperceptible, which is why the small end of this scale is not derived.
//
// The consequence that matters: generous padding AND a generous inner radius
// FORCE a big outer radius. They are coupled — you cannot just "round things
// more" without re-deriving the children.
//
//     surface 32  (pad 20)  ->  control 12  (pad 4)  ->  inner 8
//
export const RADIUS = {
  chip: 4,        // Badges, kbd, accent chips
  input: 6,       // Buttons, inputs, selects, toggles, nav rows
  card: 8,        // Cards, panels, dropdown menus
  dialog: 12,     // Modals, sheets
  // The generous "warm" scale — floating editor/canvas surfaces. DERIVED, not picked.
  surface: 32,    // Floating panels on a canvas surface. Children: inner = 32 − padding.
  control: 12,    // = surface(32) − 20 padding
  inner: 8,       // = control(12) − 4 padding  (e.g. a segmented button in its track)
  composer: 24,   // Chat composer shell. Pads 12 → corner children take control(12).
  pill: 999,      // Avatars, status dots, true pills, the primary CTA
};

// Component height ladder — interactive elements (buttons,
// inputs, selects) line up because they share this scale.
// Non-interactive heights (dividers, progress bars) stay as
// raw values; this ladder is for things you click.
export const HEIGHT = {
  xs: 24,         // Tag-style chips, dense table buttons
  sm: 28,         // Secondary buttons, compact selects
  md: 32,         // Default buttons, default inputs, default selects
  lg: 40,         // Primary CTAs, hero inputs
};

// Motion — three timings cover everything. All ease-out (no
// springs, no bounces — flat means no playful overshoot).
// Use as full transition fragments: `transition: \`background ${MOTION.hover}\``
export const MOTION = {
  hover:  "100ms cubic-bezier(0.22, 1, 0.36, 1)",  // bg/border/color tints
  state:  "150ms cubic-bezier(0.22, 1, 0.36, 1)",  // toggle slides, accordion
  layout: "200ms cubic-bezier(0.22, 1, 0.36, 1)",  // modals, drawers, position
  reveal: "360ms cubic-bezier(0.16, 1, 0.3, 1)",   // staggered entrances, image fade-in
  // TACTILITY (added 2026-07-12). A gentle overshoot that makes a control feel
  // like an OBJECT you pressed, not a div that changed colour. Spend it on the
  // few controls that exist: hover-lift (translateY -1/-2px), press (scale .92),
  // selection settling in, a chevron rotating. Never on a colour fade.
  // Design goal: "nice non-linear motion / animation in the small amount of controls."
  press:  "280ms cubic-bezier(0.34, 1.45, 0.64, 1)",
};

// Bare easing curves, decoupled from duration — compose a custom-duration
// transition on a canonical curve without re-typing the cubic-bezier. Named
// CURVE (not EASE) to avoid colliding with the file-local `const EASE`
// Material-curve consts being migrated out (see motion spec 2026-06-02).
//   CURVE.out    — state / position / hover (the canonical MOTION curve)
//   CURVE.reveal — entrance / reveal (softer easeOutExpo)
export const CURVE = {
  out:    "cubic-bezier(0.22, 1, 0.36, 1)",
  reveal: "cubic-bezier(0.16, 1, 0.3, 1)",
  spring: "cubic-bezier(0.34, 1.45, 0.64, 1)",  // gentle overshoot — tactility (see MOTION.press)
};

// Border opacities — calibrated so idle hints, hover firms up,
// and focus owns the field. The current system uses one value
// for all three states, which kills the responsive cue.
//
// Stored as raw rgba so they work both in dark + light themes
// when wrapped in a color-mix or used as alpha overlays. For
// theme-aware borders use var(--border) / var(--borderHov)
// from DARK/LIGHT instead.
export const BORDER = {
  idle:  "rgba(240,236,228,0.05)",   // dark: barely-there hint
  hover: "rgba(240,236,228,0.14)",   // dark: firms under cursor
  focus: "var(--accent)",            // owns the field on tab/click
};

// Focus ring — neutral 1px hairline, derived from text color (not
// amber). Reads as "the border firmed up slightly" rather than a
// spotlight. Drawn via box-shadow so layout never shifts.
export const FOCUS_RING = "0 0 0 1px rgba(234,239,236,0.22)";

// Elevation — five buckets cover every drop shadow in the app.
// Calibrated for the dark theme (rgba black, fairly punchy alphas)
// because the surfaces have so little luminance contrast that a
// thin shadow disappears. Pattern matches Radix UI / Vercel Geist.
//
// Usage: boxShadow: SHADOW.md
//
// Avoid composing two SHADOW values in one rule — pick the right
// bucket and own the elevation. The handful of legacy compound
// shadows stay raw because they imitate a third party's chrome,
// not our system.
export const SHADOW = {
  sm:   "0 1px 3px rgba(0,0,0,0.25)",    // toggle knobs, small inline depth
  md:   "0 8px 24px rgba(0,0,0,0.30)",   // dropdowns, popovers, tooltips
  lg:   "0 12px 40px rgba(0,0,0,0.45)",  // popover modals, action menus
  xl:   "0 24px 80px rgba(0,0,0,0.50)",  // modals, dialogs, lightboxes
  glow: "0 0 12px rgba(214,243,47,0.30)", // chartreuse-accent emphasis
};

// Dark-glass chip floated over MEDIA (thumbnails, previews, lane
// clips) — the ONE sanctioned dark-on-image exception to the flat-panel
// rule. One recipe so every chip (type badge, duration, mute, remove)
// matches instead of drifting (the pre-token chips were hand-rolled
// per surface and six variants deep).
// Spread it: style={{ ...GLASS, ... }}. Text/icons use a FIXED light ink
// because the wash is fixed near-black in BOTH themes — var(--text) would
// flip dark-on-dark in light mode.
export const GLASS = {
  background: "rgba(3,8,10,0.62)",
  backdropFilter: "blur(4px)",
  WebkitBackdropFilter: "blur(4px)",
  color: "#E8EDF0",
  borderRadius: RADIUS.chip,
};
export const GLASS_INK = "#E8EDF0";

// GLASS_SOLID — the SAME chip without backdrop-filter. backdrop-filter:blur
// forces an uncached offscreen blur pass PER element; spread across hundreds of
// opaque-backed chips (every media tile + clip) it tanks the framerate even at
// idle. Over opaque thumbnails there's nothing to blur, so a slightly more
// opaque solid fill reads identically for ~free. Use GLASS_SOLID for chips over
// thumbnails/clips; reserve GLASS (real blur) for the 1-2 chips over LIVE video.
export const GLASS_SOLID = {
  background: "rgba(3,8,10,0.82)",
  color: "#E8EDF0",
  borderRadius: RADIUS.chip,
};

// Stacking layers — six semantic levels. Use these instead of
// raw zIndex anywhere a stacking context is global (i.e. competing
// with chrome / modals / toasts). Local stacking inside a tightly-
// scoped layout (e.g. zIndex: 1 to sit above a sibling pseudo-
// element) doesn't need a token.
//
// Order is sticky < dropdown < popover < modal < toast < dialog.
// Anything beyond dialog is a hack — fix the parent stacking context.
//
// `dialog` lives above lightbox-tier overlays — a third-party lightbox
// once pinned itself at z-index 9999, ignoring our tokens, so this tier
// had to clear it. Use it for confirmations triggered from inside a
// lightbox or other top-stack overlay.
export const Z = {
  base:     0,      // explicit document flow
  raised:   1,      // local sibling layering
  sticky:   50,     // mobile header, bottom-tab bar, fixed sidebars
  dropdown: 100,    // popovers, menus, command palette
  popover:  200,    // mobile drawers, action menus (above dropdowns)
  modal:    1000,   // modals, drawers, settings, danger
  toast:    9999,   // toasts, info tooltips
  dialog:   11000,  // confirmation modals — above lightboxes (a third-party 9999 was the bar)
};

// Pixal's OWN fixed overlays sit in their own low band, ordered by what can
// open on top of what. They predate `Z` and do not use it: `Z.modal` is 1000
// and the boot screen is 90, so migrating them piecemeal would silently drop
// "Starting ComfyUI" behind every modal. The band is the honest record of the
// order the app actually has, and the place to add the next overlay.
//
// The rule the band exists to enforce: **a viewer is below the dialogs that
// open from it.** The still/clip lightbox sat at 40 while ModalShell defaulted
// to 36/37, so pressing "animate" on an open render mounted the whole Direct
// the clip dialog underneath the photo (Jesse, 2026-08-24: "you cant fix
// that?" — yes).
export const OVERLAY = {
  card:    30,   // a fixed history card lifted out of the grid
  viewer:  32,   // full-screen still / clip lightbox — BELOW every dialog
  panel:   34,   // Settings and its scrim
  scrim:   36,   // ModalShell's default scrim...
  modal:   37,   // ...and the box it carries (scrim + 1)
  form:    38,   // CharacterForm, which opens over another modal
  meter:   45,   // the render progress hairline — decorative, always visible
  setup:   60,   // first-run setup, which owns the whole window
  boot:    90,   // "Starting ComfyUI" — nothing outranks it
};

// Line-height scale — four values cover everything. Audit found
// 22 distinct values; most were within 0.05 of these.
export const LH = {
  heading: 1.2,   // h1 / h2 / h3
  ui:      1.4,   // buttons, table cells, dense UI
  body:    1.5,   // paragraphs, descriptions
  long:    1.6,   // long-form copy (rare in app shell)
};
