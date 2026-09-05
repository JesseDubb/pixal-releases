// Per-image provenance wins over batch summaries; old history stays readable.
export function originalImage(image) {
  const original = image?.original;
  if (!original?.filename || image.media === "video" || original.media === "video") return null;
  if (original.filename === image.filename &&
      (original.subfolder || "") === (image.subfolder || "")) return null;
  return original;
}

export function imageFinishInfo(image, info) {
  return { ...info, ...(typeof image?.finish === "string" ? { finish: image.finish } : {}) };
}

export function wipePosition(clientX, left, width) {
  return width > 0 ? Math.min(100, Math.max(0, (clientX - left) / width * 100)) : 50;
}

export function clampView(width, height, s, x, y) {
  const scale = Math.min(6, Math.max(1, s));
  const mx = width * (scale - 1) / 2, my = height * (scale - 1) / 2;
  return { s: scale, x: Math.max(-mx, Math.min(mx, x)), y: Math.max(-my, Math.min(my, y)) };
}

export function zoomAt(view, nextScale, dx, dy, width, height) {
  const s = Math.min(6, Math.max(1, nextScale));
  const k = s / view.s;
  return clampView(width, height, s, dx - (dx - view.x) * k, dy - (dy - view.y) * k);
}
