// richtext.js — renderRichText, ported verbatim from an earlier chat widget
// of mine. Inline markdown
// (bold/italic/code/links + hex swatches) and GFM tables → HTML string for
// dangerouslySetInnerHTML. Trust level: our own LLM's output.

const hexSwatch = (hex) =>
  `<span style="display:inline-flex;align-items:center;gap:5px;vertical-align:-1px">` +
  `<span style="display:inline-block;width:12px;height:12px;border-radius:4px;background:#${hex};border:1px solid var(--border)"></span>` +
  `<code style='background:var(--bg4);padding:1px 5px;border-radius:4px;font-size:12px'>#${hex}</code></span>`;

const renderInline = (s) => s
  .replace(/(?<![\w/])(?:`#([0-9a-fA-F]{6})`|#([0-9a-fA-F]{6})\b)/g, (m, tick, bare) => {
    const hex = tick || bare;
    return (/\d/.test(hex) || hex === hex.toUpperCase()) ? hexSwatch(hex) : m;
  })
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "<em>$1</em>")
  .replace(/`([^`]+?)`/g, "<code style='background:var(--bg4);padding:1px 5px;border-radius:4px;font-size:12px'>$1</code>")
  .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

const splitCells = (l) =>
  l.trim().replace(/^\||\|$/g, "").split("|").map((c) => renderInline(c.trim()));

const mdTable = (headerLine, bodyLines) => {
  const TH = "text-align:left;font-weight:600;color:var(--textTer);padding:0 12px 6px 0;" +
    "border-bottom:1px solid var(--border);white-space:nowrap;font-size:11px";
  const TD = "padding:7px 12px 7px 0;border-bottom:1px solid var(--border);color:var(--text);" +
    "vertical-align:top;font-size:12px;line-height:1.45;word-break:normal;overflow-wrap:break-word";
  const head = splitCells(headerLine).map((h) => `<th style="${TH}">${h}</th>`).join("");
  const rows = bodyLines
    .map((r) => `<tr>${splitCells(r).map((c) => `<td style="${TD}">${c}</td>`).join("")}</tr>`)
    .join("");
  return `<table style="width:100%;border-collapse:collapse;margin:8px 0">` +
    `${head ? `<thead><tr>${head}</tr></thead>` : ""}<tbody>${rows}</tbody></table>`;
};

export const renderRichText = (text) => {
  const lines = (text || "").split("\n");
  const parts = [];
  let buf = [];
  const flush = () => { if (buf.length) { parts.push(buf.join("<br>")); buf = []; } };
  const isRow = (l) => l.trim().startsWith("|") && l.includes("|");
  const isSep = (l) => /-/.test(l) && /^[\s|:-]+$/.test(l.trim());
  const isHr = (l) => /^(-{3,}|\*{3,}|_{3,})$/.test(l.trim());
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (isRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      flush();
      const body = [];
      let j = i + 2;
      while (j < lines.length && isRow(lines[j])) { body.push(lines[j]); j++; }
      parts.push(mdTable(line, body));
      i = j;
      continue;
    }
    if (isHr(line)) {
      flush();
      parts.push('<hr style="border:none;border-top:1px solid var(--border);margin:10px 0">');
      i++;
      continue;
    }
    buf.push(renderInline(line));
    i++;
  }
  flush();
  return parts.join("");
};
