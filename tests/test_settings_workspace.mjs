import test from "node:test";
import assert from "node:assert/strict";
import { createElement as h, Fragment } from "react";
import { SETTINGS, matchSettings, settingId, settingsWidth } from "../web/src/lib/settings-layout.js";
import { flatten, indexPages, textOf } from "../web/src/lib/settings-search.js";

const component = (kind) => Object.assign(() => null, { settingsKind: kind });
const Field = component("field"), Section = component("section"), Group = component("group");
const Model = component("model"), Navigation = component("navigation");
const Tip = () => null, Choice = () => null;
const page = (id, children) => ({ id, label: id, content: h(Fragment, null, ...children) });

test("label text excludes tooltip prose, attributes and credentials", () => {
  assert.equal(textOf(h(Fragment, null, "API key", h(Tip, { text: "private explanation" }))).trim(), "API key");
  assert.equal(textOf(h("input", { value: "secret", placeholder: "private" })), "");
  assert.equal(textOf(["H3", 2, false, null]).trim(), "H3 2");
});

test("fragments flatten without rendering inactive branches", () => {
  const nodes = flatten(h(Fragment, null, h("span", null, "A"), false,
    h(Fragment, null, h("span", null, "B"))));
  assert.deepEqual(nodes.map(textOf), ["A", "B"]);
});

test("all pages, sections, labels and option labels are searchable", () => {
  const entries = indexPages([
    page("General", [h(Group, null, "This machine"),
      h(Section, { title: "Memory" }, h(Field, { label: "Brain idles after" },
        h(Choice, { options: [{ label: "Never" }, { label: h("span", null, "10 min") }] })))]),
    page("Video", [h(Group, null, "Defaults"), h(Field, { label: "H3 upscale" })]),
  ]);
  assert.equal(matchSettings(entries, "  GENERAL never ")[0].label, "Brain idles after");
  assert.equal(matchSettings(entries, "10 min")[0].path, "General / This machine / Memory");
  assert.equal(matchSettings(entries, "video upscale")[0].label, "H3 upscale");
  assert.equal(matchSettings(entries, "memory")[0].id, "section-memory");
  assert.deepEqual(matchSettings(entries, ""), []);
  assert.deepEqual(matchSettings(entries, "no-such-setting"), []);
});

test("search never indexes input values or tooltip contents", () => {
  const entries = indexPages([page("Chat", [h(Field, {
    label: h(Fragment, null, "API key", h(Tip, { text: "hidden-tip" })),
  }, h("input", { value: "sk-private-token", type: "password" }))])]);
  assert.equal(matchSettings(entries, "api key").length, 1);
  assert.deepEqual(matchSettings(entries, "private-token"), []);
  assert.deepEqual(matchSettings(entries, "hidden-tip"), []);
  assert.ok(!JSON.stringify(entries).includes("sk-private-token"));
});

test("model results carry the family reveal callback and raw filename keywords", () => {
  let reveals = 0;
  const reveal = () => reveals++;
  const entries = indexPages([page("Models", [h(Group, null, "Model families"),
    h(Section, { title: "MiniMax H3", onSearchReveal: reveal },
      h(Model, { name: "H3 reference", rel: "models/H3_ref_fp8.safetensors" }))])]);
  const [result] = matchSettings(entries, "fp8");
  assert.equal(result.path, "Models / Model families / MiniMax H3");
  assert.equal(result.id, `model-${settingId("models/H3_ref_fp8.safetensors")}`);
  result.reveal();
  assert.equal(reveals, 1);
  assert.equal(matchSettings(entries, "MiniMax H3")[0].reveal, reveal);
});

test("brain-source navigation is found without switching or saving its mode", () => {
  let changes = 0;
  const entries = indexPages([page("Chat", [h(Navigation, {
    ariaLabel: "Chat brain source", tabs: [{ id: "api", label: "API" }, { id: "local", label: "Local" }],
    onChange: () => changes++,
  })])]);
  assert.equal(matchSettings(entries, "local")[0].id, "chat-brain-source");
  assert.equal(changes, 0);
});

test("exact and prefix label matches rank before matches in breadcrumbs", () => {
  const entries = [
    { label: "Video memory", path: "General / Memory" },
    { label: "Memory policy", path: "Chat" },
    { label: "Memory", path: "General" },
  ];
  assert.deepEqual(matchSettings(entries, "memory").map((entry) => entry.label),
    ["Memory", "Memory policy", "Video memory"]);
});

test("dock width is bounded and leaves room for the studio", () => {
  assert.equal(settingsWidth(null, 1920), SETTINGS.defaultWidth);
  assert.equal(settingsWidth("bad", 1920), SETTINGS.defaultWidth);
  assert.equal(settingsWidth(200, 1920), SETTINGS.minWidth);
  assert.equal(settingsWidth(2000, 1920), SETTINGS.maxWidth);
  assert.equal(settingsWidth(740, 1200), 540);
  assert.equal(settingsWidth(740, 1000), SETTINGS.minWidth);
  assert.equal(settingsWidth(600.7, 1920), 601);
});

test("setting identifiers are stable across punctuation and whitespace", () => {
  assert.equal(settingId("  H3 2× upscale "), "h3-2-upscale");
  assert.equal(settingId("Brain idles after"), "brain-idles-after");
  assert.equal(settingId(null), "");
});
