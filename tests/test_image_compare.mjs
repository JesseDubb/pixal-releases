import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { originalImage, imageFinishInfo, wipePosition, clampView, zoomAt } from "../web/src/lib/image-compare.js";
import { finishChips } from "../web/src/lib/names.js";

test("only real per-image pairs offer post-processing comparison", () => {
  const original = { filename: "raw.png", subfolder: "pixal_dm" };
  assert.equal(originalImage({ filename: "new.png", original }), original);
  for (const image of [{ filename: "legacy.png" }, { ...original, original },
    { filename: "video.mp4", media: "video", original }]) assert.equal(originalImage(image), null);
});

test("per-image finish is authoritative even when empty; legacy jobs keep their summary", () => {
  const info = { finish: "dlss5@natural", model: "test" };
  assert.deepEqual(finishChips(imageFinishInfo({ finish: "" }, info)), []);
  assert.deepEqual(finishChips(imageFinishInfo({}, info)), ["DLSS 5"]);
  assert.deepEqual(finishChips({ finish: "dlss5@default+deshine@.8+grain@1.6" }, { details: true }),
    ["DLSS 5 (Default)", "Matte skin", "Film grain"]);
});

test("hover wipe masks the exact pointer position and clamps both edges", () => {
  assert.equal(wipePosition(300, 100, 400), 50);
  assert.equal(wipePosition(50, 100, 400), 0);
  assert.equal(wipePosition(900, 100, 400), 100);
  assert.equal(wipePosition(100, 100, 0), 50);
});

test("zoom preserves the pixel under the pointer and pan cannot strand either image", () => {
  assert.deepEqual(zoomAt({ s: 1, x: 0, y: 0 }, 2, 40, -20, 400, 300), { s: 2, x: -40, y: 20 });
  assert.deepEqual(clampView(400, 300, 2, 999, -999), { s: 2, x: 200, y: -150 });
  assert.deepEqual(clampView(400, 300, 1, 99, 99), { s: 1, x: 0, y: 0 });
  assert.equal(clampView(400, 300, 100, 0, 0).s, 6);
});

test("live SSE preserves provenance and viewer integration does not invent old originals", () => {
  const store = readFileSync(new URL("../web/src/store.js", import.meta.url), "utf8");
  const chat = readFileSync(new URL("../web/src/components/Chat.jsx", import.meta.url), "utf8");
  const component = readFileSync(new URL("../web/src/components/PostProcessCompare.jsx", import.meta.url), "utf8");
  assert.ok(store.includes("original: d.original"));
  assert.ok(store.includes("finish: d.finish"));
  assert.ok(chat.includes("<PostProcessCompare"));
  assert.ok(component.includes('aria-label="Save original"'));
  assert.ok(component.includes('aria-label="Save processed"'));
  assert.ok(component.includes('type="range"'));
  assert.ok(component.includes('clipPath: "inset('));
  assert.ok(!component.includes("transition:"), "direct manipulation must not lag");
});
