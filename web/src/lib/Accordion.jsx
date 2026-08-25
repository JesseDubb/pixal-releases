// Accordion.jsx — the transitions.dev "accordion expand" (skill 21) on
// Pixal's motion tokens: the panel grows and shrinks through
// grid-template-rows 0fr <-> 1fr (no height measuring, any content), the
// inner box clips and fades, and the chevron flips vertically through a
// flat line at the midpoint so a "v" becomes a "^" in every browser.
//
// Render-quiet on purpose: grid-rows + opacity + a transform, nothing that
// forces a blur or a paint storm, and a one-shot on click - nothing animates
// while a job samples unless the user is opening a drawer.
import { CaretDown } from "@phosphor-icons/react";
import { MOTION } from "./design-tokens.js";

export const AccordionPanel = ({ open, children }) => (
  <div style={{ display: "grid",
                gridTemplateRows: open ? "1fr" : "0fr",
                transition: `grid-template-rows ${MOTION.layout}` }}>
    <div style={{ overflow: "hidden", minHeight: 0,
                  opacity: open ? 1 : 0,
                  transition: `opacity ${MOTION.layout}` }}>
      {children}
    </div>
  </div>
);

export const AccordionChevron = ({ open, size = 11 }) => (
  <span aria-hidden="true"
        style={{ display: "inline-flex", lineHeight: 0,
                 transform: open ? "scaleY(-1)" : "scaleY(1)",
                 transition: `transform ${MOTION.state}` }}>
    <CaretDown size={size} weight="bold" />
  </span>
);
