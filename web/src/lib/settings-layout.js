// Settings owns a roomier reading rhythm than the compact controls inside it.
// The shared 26px rail remains unchanged throughout the rest of the studio.
export const SETTINGS = {
  defaultWidth: 600,
  minWidth: 480,
  maxWidth: 760,
  row: 44,
  inset: 24,
  groupGap: 28,
  cardGap: 12,
};

export const settingId = (label) => String(label || "")
  .normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export const matchSettings = (entries, query) => {
  const words = String(query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  return entries.filter((entry) => {
    const text = `${entry.label} ${entry.path} ${entry.keywords || ""}`.toLowerCase();
    return words.every((word) => text.includes(word));
  }).sort((a, b) => {
    const q = words.join(" ");
    const score = (entry) => entry.label.toLowerCase() === q ? 0
      : entry.label.toLowerCase().startsWith(q) ? 1 : 2;
    return score(a) - score(b);
  });
};

export const settingsWidth = (preferred, viewport) => Math.round(Math.min(
  Math.max(SETTINGS.minWidth, Number(preferred) || SETTINGS.defaultWidth),
  SETTINGS.maxWidth, Math.max(SETTINGS.minWidth, viewport - 660),
));
