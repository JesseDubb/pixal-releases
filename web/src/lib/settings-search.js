import { Children, Fragment, isValidElement } from "react";
import { settingId } from "./settings-layout.js";

export const textOf = (node) => {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(" ");
  return isValidElement(node) ? textOf(node.props.children) : "";
};

export const flatten = (children) => Children.toArray(children).flatMap((node) =>
  isValidElement(node) && node.type === Fragment ? flatten(node.props.children) : [node]);

// Build the index from the same React elements that render the settings. Labels,
// conditional controls and installed models cannot drift from a second catalog.
// Input values are deliberately excluded: they can contain provider credentials.
export const indexPages = (pages) => pages.flatMap((page) => {
  const entries = [];
  const visit = (children, parentPath = [], reveal) => {
    let path = parentPath;
    for (const node of flatten(children)) {
      if (!isValidElement(node)) continue;
      const kind = node.type?.settingsKind;
      const props = node.props;
      if (kind === "group") { path = [...parentPath, textOf(props.children)]; continue; }
      if (kind === "section" && props.title) {
        entries.push({ tab: page.id, label: textOf(props.title),
          id: `section-${settingId(textOf(props.title))}`,
          path: [page.label, ...path.filter(Boolean)].join(" / "),
          reveal: props.onSearchReveal || reveal });
      }
      if (kind === "field" || kind === "model" || kind === "navigation") {
        const label = kind === "model" ? props.name
          : kind === "navigation" ? props.ariaLabel : textOf(props.label);
        const optionText = (children) => flatten(children).map((child) => {
          if (!isValidElement(child)) return "";
          const options = child.props.options || [];
          return [options.map((option) => textOf(option.label)).join(" "),
            optionText(child.props.children)].join(" ");
        }).join(" ");
        entries.push({ tab: page.id, label,
          id: kind === "model" ? `model-${settingId(props.rel)}` : settingId(label),
          path: [page.label, ...path.filter(Boolean)].join(" / "),
          keywords: kind === "model" ? props.rel : kind === "navigation"
            ? props.tabs.map((item) => item.label).join(" ") : optionText(props.children), reveal });
      } else {
        visit(props.children, kind === "section" && props.title
          ? [...path, textOf(props.title)] : path, props.onSearchReveal || reveal);
      }
    }
  };
  visit(page.content);
  return entries;
});
