"""Brief 9.75 - custom sampler settings survive a model switch within one
family.

Jesse (2026-08-27): "it resets my settings when I choose a new minimax h3
version". There was no explicit clear: quick tuning lives in
``opts.tuning[activeRecipeId]`` (store.js ``tuningOverrides``), and the H3
builds map to THREE recipe ids (h3_still / h3_still_2x / h3_ref_still), so a
model or quality switch changed the KEY and the card read the new id's
empty map. The old entry was orphaned, not deleted.

The fix carries the override map across the switch when the two recipes'
sampler seats are twins - same recipe family, same seat node class, same
sampler/scheduler choice lists - and drops per key anything the new seat
cannot take. Cross-family switches still reset (Krea 2 -> H3 has different
samplers; the family gate is load-bearing because Z-Image Turbo's v4 seat
and the H3 seats are all KSamplerSelect). The map MOVES: one live copy
follows the user, so switching back carries back whatever the card shows
then. A saved style's base is never written - the style file owns its
schedule.

What these tests pin:

  SeatSignature - ``seat_signature`` server-side: the H3 trio and the Krea 2
                  stills each share one signature (class, keys, choice
                  lists); a seatless recipe reports None; /api/options'
                  recipe rows carry the block and the route probes ComfyUI
                  so the lists are live.
  CarryRule     - static, in the test_h3_ref_still.py style: the named
                  export, the family/class/list gate, the per-key drop, the
                  move semantics, the saved-style guard, the wiring at both
                  re-route sites, and the composer's unchanged read path.
  Behavior      - the pure function's decision table plus an end-to-end
                  drive of the real store (loadOptions -> setTuning ->
                  setOpts), run in node when one is on PATH, skipped where
                  none is. This repo has no JS runner; the suite stays
                  green without one.

Same sanctioned simulation as every sibling file: stubbed catalog, no
generation, no ComfyUI, no GPU.
"""

import json
import re
import shutil
import subprocess
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_tuning_carry", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
STORE = (WEB / "store.js").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")

STOCK = server.H3_MODEL
REF2VA = server.H3_REF2V_MODEL


def h3_entries(root):
    """This box's H3 stack as catalog entries: both stock builds, the shared
    encoder and both VAEs."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    return [add("diffusion_models", STOCK),
            add("diffusion_models", REF2VA),
            add("vae", server.H3_VIDEO_VAE),
            add("vae", server.H3_AUDIO_VAE),
            add("text_encoders", server.H3_CLIP)]


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def options_payload(entries):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        with patch.object(server, "CDIR", root), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "model_roots", return_value=[]), \
             patch.object(server, "adjacent_metadata", return_value={}), \
             patch.object(server, "lm_enrich"), \
             patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
            return server.Hub().options()


class SeatSignatureTests(unittest.TestCase):
    """seat_signature + the /api/options recipe rows (9.75)."""

    def test_the_h3_stills_share_one_signature(self):
        # Four rows since 9.84 - each lane and its 2x twin. Every one seats
        # the FIRST pass, so all four signatures must be the same object's
        # worth of keys; a divergence would mean a tuning carry silently
        # dropped when the composer flipped Refined.
        ids = ("h3_still", "h3_still_2x", "h3_ref_still", "h3_ref_still_2x")
        sigs = [server.seat_signature(rid) for rid in ids]
        self.assertNotIn(None, sigs)
        for rid, sig in zip(ids[1:], sigs[1:]):
            self.assertEqual(sigs[0], sig, rid)
        self.assertEqual(sigs[0]["class"], "KSamplerSelect")
        self.assertEqual(sigs[0]["keys"], ["steps", "sampler_name", "scheduler"])

    def test_the_krea2_stills_share_one_signature(self):
        # realism_ii's seat is a different NODE ("265" vs "30:51") but the
        # same class, so its keys and choice lists are realism's own - the
        # carry rule's "same seat" test passes for the pair, as the brief's
        # choice-list rule states.
        one, two, ident = (server.seat_signature(rid) for rid in
                           ("realism", "realism_ii", "identity_edit"))
        self.assertEqual(one, two)
        self.assertEqual(two, ident)
        self.assertEqual(one["class"], "ClownsharKSampler_Beta")
        self.assertIn("eta", one["keys"])

    def test_cross_family_signatures_differ_by_class(self):
        self.assertNotEqual(server.seat_signature("h3_still")["class"],
                            server.seat_signature("realism")["class"])

    def test_probed_choice_lists_ride_the_signature(self):
        enums = {"KSamplerSelect": {"sampler_name": ["res_multistep"]},
                 "KSampler": {"sampler_name": ["euler"],
                              "scheduler": ["simple", "beta"]}}
        with patch.object(server, "_COMFY_NODES",
                          {"at": 0.0, "names": frozenset(), "modules": {},
                           "enums": enums}):
            sig = server.seat_signature("h3_still")
        # The seat's own names first, then the stock KSampler's extras - the
        # same merged list seat_choices hands the tuning card.
        self.assertEqual(sig["choices"]["sampler_name"],
                         ["res_multistep", "euler"])
        self.assertEqual(sig["choices"]["scheduler"], ["simple", "beta"])

    def test_a_seatless_recipe_reports_none(self):
        self.assertIsNone(server.seat_signature("klein_edit"))

    def test_the_recipe_rows_carry_the_block(self):
        options = options_payload(h3_entries(Path.cwd()))
        rows = {r["id"]: r for r in options["recipes"]}
        self.assertEqual(rows["h3_still"]["sampler"],
                         rows["h3_still_2x"]["sampler"])
        self.assertEqual(rows["h3_still_2x"]["sampler"],
                         rows["h3_ref_still"]["sampler"])
        self.assertEqual(rows["h3_still"]["family"], "minimax_h3")
        self.assertEqual(rows["h3_ref_still"]["family"], "minimax_h3")
        self.assertEqual(rows["realism"]["sampler"],
                         rows["realism_ii"]["sampler"])
        self.assertEqual(rows["realism"]["family"], "krea2")
        self.assertIsNone(rows["klein_edit"]["sampler"])

    def test_the_options_route_probes_comfy_first(self):
        handler = re.search(r"async def options\(_req\):([\s\S]{0,400}?)\n\n",
                            SERVER_SRC)
        self.assertIsNotNone(handler)
        self.assertIn("await refresh_comfy_nodes()", handler.group(1))


class CarryRuleStaticTests(unittest.TestCase):
    """Static, in the test_h3_ref_still.py style: the client contracts."""

    def body(self):
        match = re.search(
            r"export function carryTuning\(prev, next, options\) \{"
            r"([\s\S]{0,2200}?)\n\}", STORE)
        self.assertIsNotNone(match, "carryTuning(prev, next, options) "
                                    "is not a named export in store.js")
        return match.group(1)

    def test_the_rule_keys_off_the_active_recipe_ids(self):
        body = self.body()
        self.assertIn("activeRecipeId(prev, options)", body)
        self.assertIn("activeRecipeId(next, options)", body)

    def test_the_gate_is_family_class_and_identical_lists(self):
        body = self.body()
        self.assertIn("prevRecipe.family !== nextRecipe?.family", body)
        self.assertIn("from.class !== to.class", body)
        self.assertIn('["sampler_name", "scheduler"]', body)
        self.assertIn("JSON.stringify(from.choices?.[k] || [])", body)

    def test_the_drop_is_per_key(self):
        body = self.body()
        # A key the new seat does not have drops; a value outside the new
        # seat's (identical) lists - a stale pick from an older probe -
        # drops alone; everything else carries.
        self.assertIn("(to.keys || []).includes(k)", body)
        self.assertIn("!listed.includes(v)", body)

    def test_the_map_moves(self):
        body = self.body()
        self.assertIn("delete out[prevId]", body)
        self.assertIn("out[nextId] = carried", body)

    def test_a_saved_styles_base_is_never_written(self):
        self.assertIn("savedStyleFor(next, options)", self.body())

    def test_wired_at_both_reroute_sites(self):
        self.assertIn("next.tuning = carryTuning(state.opts, next, state.options);",
                      STORE)
        self.assertIn("healed.tuning = carryTuning(state.opts, healed, options);",
                      STORE)

    def test_the_card_reads_the_per_recipe_map_unchanged(self):
        # No Composer change: the carried map shows because the card reads
        # opts.tuning[activeRecipeId] exactly as before - and the subline
        # keeps naming the recipe's home as "recipe X" (homeMark).
        self.assertIn("const tuneOverrides = ((opts?.tuning || {}))[recipeId] || {};",
                      COMPOSER)
        self.assertIn("recipe {home[k]}", COMPOSER)


NODE_HARNESS = r"""
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync("web/src/store.js", "utf8")
  .replace(/^import[^\n]*\n/gm, "")
  .replace(/^export /gm, "");
const store = new Map();
const sandbox = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: () => {},
  console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(`
const useCallback = (f) => f, useEffect = () => {},
      useReducer = (r, i) => [i, () => {}], useSyncExternalStore = () => null;
const __fixture = { current: null };
const transport = new Proxy({}, { get: (t, k) =>
  k === "options" ? async () => __fixture.current : async () => ({ ok: false }) });
globalThis.__fixture = __fixture;
const prettyTemplate = (x) => x;
`, sandbox);
vm.runInContext(
  src + "\n;globalThis.__x = { carryTuning, activeRecipeId, tuningOverrides, api };",
  sandbox);
const { carryTuning, activeRecipeId, tuningOverrides, api } = sandbox.__x;

const H3_SEAT = {
  class: "KSamplerSelect", keys: ["steps", "sampler_name", "scheduler"],
  choices: { sampler_name: ["res_multistep", "seeds_2", "euler"],
             scheduler: ["simple", "ddim_uniform", "beta"] },
};
const CLOWN_SEAT = {
  class: "ClownsharKSampler_Beta",
  keys: ["steps", "cfg", "sampler_name", "scheduler", "eta"],
  choices: { sampler_name: ["res_2s", "linear/euler", "euler"],
             scheduler: ["beta", "bong_tangent", "simple"] },
};
const recipe = (id, family, sampler) => ({ id, family, sampler });
const options = {
  model_meta: {
    "MiniMax H3\\h3_fl2va.safetensors": { family: "minimax_h3", variant: "fl2va",
      supported: true, compatible_recipes: ["h3_still", "h3_still_2x"] },
    "MiniMax H3\\h3_ref2va.safetensors": { family: "minimax_h3", variant: "ref2va",
      supported: true, compatible_recipes: ["h3_ref_still"] },
    "Krea 2\\krea2.safetensors": { family: "krea2", variant: "turbo",
      supported: true, compatible_recipes: ["realism", "realism_ii"] },
  },
  recipes: [
    recipe("h3_still", "minimax_h3", H3_SEAT),
    recipe("h3_still_2x", "minimax_h3", H3_SEAT),
    recipe("h3_ref_still", "minimax_h3", H3_SEAT),
    recipe("realism", "krea2", CLOWN_SEAT),
    recipe("realism_ii", "krea2", CLOWN_SEAT),
    recipe("identity_edit", "krea2", CLOWN_SEAT),
    recipe("zimage", "zimage", { ...H3_SEAT }),   // v4 seat: H3's twin but family
    recipe("qwen_image", "qwen_image", { class: "KSampler",
      keys: ["steps", "cfg", "sampler_name", "scheduler"], choices: {} }),
  ],
  saved_styles: [],
};
const FL = "MiniMax H3\\h3_fl2va.safetensors";
const REF = "MiniMax H3\\h3_ref2va.safetensors";
const KREA = "Krea 2\\krea2.safetensors";
const TUNED = { sampler_name: "seeds_2", scheduler: "ddim_uniform", steps: 28 };

let failures = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures++;
  console.log((ok ? "PASS " : "FAIL ") + name,
    ok ? "" : `\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`);
};

check("fl2va -> ref2va carries the whole map and moves it",
  carryTuning({ model: FL, tuning: { h3_still: TUNED } },
              { model: REF, tuning: { h3_still: TUNED } }, options),
  { h3_ref_still: TUNED });
check("fl2va -> 2x via Refined carries",
  carryTuning({ model: FL, tuning: { h3_still: TUNED } },
              { model: FL, quality: "refined", tuning: { h3_still: TUNED } },
              options),
  { h3_still_2x: TUNED });
check("switching back carries the later edit back",
  carryTuning({ model: FL, quality: "refined",
                tuning: { h3_still_2x: { ...TUNED, steps: 32 } } },
              { model: FL, tuning: { h3_still_2x: { ...TUNED, steps: 32 } } },
              options),
  { h3_still: { ...TUNED, steps: 32 } });
check("cross-family (H3 -> Krea 2) leaves the map: the card resets as before",
  carryTuning({ model: REF, tuning: { h3_ref_still: TUNED } },
              { model: KREA, tuning: { h3_ref_still: TUNED } }, options),
  { h3_ref_still: TUNED });
check("realism -> realism_ii carries (same class, same lists)",
  carryTuning({ model: KREA, tuning: { realism: { steps: 12, eta: 0.5 } } },
              { model: KREA, quality: "refined",
                tuning: { realism: { steps: 12, eta: 0.5 } } }, options),
  { realism_ii: { steps: 12, eta: 0.5 } });
check("identical seats across families (zimage v4 -> h3) are blocked",
  carryTuning({ model: "z", style: "realism", engine: "zimage",
                tuning: { zimage: TUNED } },
              { model: REF, tuning: { zimage: TUNED } }, options),
  { zimage: TUNED });
const optionsNarrow = {
  ...options,
  recipes: options.recipes.map((r) =>
    r.family === "minimax_h3"
      ? { ...r, sampler: { ...H3_SEAT,
            choices: { ...H3_SEAT.choices, scheduler: ["simple", "beta"] } } }
      : r),
};
check("a value in neither list any more drops alone, the rest carries",
  carryTuning({ model: FL, tuning: { h3_still: TUNED } },
              { model: REF, tuning: { h3_still: TUNED } }, optionsNarrow),
  { h3_ref_still: { sampler_name: "seeds_2", steps: 28 } });
const optionsKeyless = {
  ...options,
  recipes: options.recipes.map((r) =>
    r.id === "h3_ref_still"
      ? { ...r, sampler: { ...H3_SEAT, keys: ["steps", "sampler_name"] } }
      : r),
};
check("a key the new seat lacks drops alone, the rest carries",
  carryTuning({ model: FL, tuning: { h3_still: TUNED } },
              { model: REF, tuning: { h3_still: TUNED } }, optionsKeyless),
  { h3_ref_still: { sampler_name: "seeds_2", steps: 28 } });
check("nothing under the old id: nothing happens",
  carryTuning({ model: FL, tuning: {} }, { model: REF, tuning: {} }, options),
  {});
const optionsStyled = {
  ...options,
  saved_styles: [{ id: "ultra", name: "Ultra", base: "h3_ref_still",
                   model: REF, available: true }],
};
check("a selected saved style's base is never written",
  carryTuning({ model: FL, tuning: { h3_still: TUNED } },
              { model: REF, saved_style: "ultra", tuning: { h3_still: TUNED } },
              optionsStyled),
  { h3_still: TUNED });
check("the carried map replaces a stale entry on the target id",
  carryTuning({ model: FL,
                tuning: { h3_still: TUNED, h3_ref_still: { steps: 1 } } },
              { model: REF,
                tuning: { h3_still: TUNED, h3_ref_still: { steps: 1 } } },
              options),
  { h3_ref_still: TUNED });

// End-to-end through the real api: loadOptions -> setTuning -> setOpts.
const OPTIONS = {
  models: [], loras: [], recipes: options.recipes.map((r) => ({
    ...r, available: true, lora_stages: [],
  })),
  model_meta: options.model_meta, saved_styles: [], characters: [],
  inputs: [], defaults: {},
};
sandbox.__fixture.current = OPTIONS;
await api.loadOptions();
api.setOpts({ model: FL });
api.setTuning("sampler_name", "seeds_2");
api.setTuning("scheduler", "ddim_uniform");
api.setTuning("steps", 28);
check("tuning lands on h3_still", api.opts.tuning, { h3_still: TUNED });
api.setOpts({ model: REF });
check("the model switch moves the tuning to h3_ref_still",
  api.opts.tuning, { h3_ref_still: TUNED });
check("the card read path sees it after the switch",
  tuningOverrides(api.opts, OPTIONS), TUNED);
api.setOpts({ model: FL });
check("switching back carries back", api.opts.tuning, { h3_still: TUNED });
api.setOpts({ quality: "refined" });
check("Refined carries to h3_still_2x",
  api.opts.tuning, { h3_still_2x: TUNED });
api.setOpts({ model: KREA, quality: "standard" });
check("crossing to Krea 2 leaves the H3 tuning where it was",
  api.opts.tuning, { h3_still_2x: TUNED });
check("the krea card shows no override",
  tuningOverrides(api.opts, OPTIONS), {});
api.setTuning("steps", 12);
check("krea tuning lands on realism",
  api.opts.tuning, { h3_still_2x: TUNED, realism: { steps: 12 } });
api.setOpts({ quality: "refined" });
check("Refined carries realism -> realism_ii",
  api.opts.tuning, { h3_still_2x: TUNED, realism_ii: { steps: 12 } });

console.log(failures ? `${failures} FAILURES` : "harness green");
process.exit(failures ? 1 : 0);
"""


@unittest.skipUnless(shutil.which("node"), "node is not on PATH")
class CarryTuningBehaviorTests(unittest.TestCase):
    """The pure function's decision table and the wired store, run for real.

    The repo has no JS runner, so this drives web/src/store.js itself in
    node with the react/transport imports stubbed - skipped where node is
    absent, and CI's static half above still pins the contract there."""

    def test_the_decision_table_and_the_end_to_end_switch(self):
        with TemporaryDirectory() as td:
            harness = Path(td) / "carry_harness.mjs"
            harness.write_text(NODE_HARNESS, encoding="utf-8")
            run = subprocess.run(["node", str(harness)], cwd=ROOT, timeout=60,
                                 capture_output=True, text=True)
        self.assertEqual(run.returncode, 0,
                         f"node harness failed:\n{run.stdout}\n{run.stderr}")
        self.assertIn("harness green", run.stdout)
        self.assertNotIn("FAIL", run.stdout)


if __name__ == "__main__":
    unittest.main()
