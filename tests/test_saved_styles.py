import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\analogMadnessKrea2Turbo_v20.safetensors", "krea2")
ZTURBO = model("ZiT\\z_image_turbo_bf16.safetensors", "zimage", "turbo")
ZBASE = model("ZiB\\z_image_bf16.safetensors", "zimage", "base")


@contextmanager
def catalog(entry):
    """Pretend `entry` is the only installed model, and every LoRA resolves."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry",
                                         return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora",
                                         side_effect=lambda name: name))
        yield


def style(**over):
    base = {"schema_version": 1, "name": "Grainy Portrait", "base": "realism",
            "model": KREA["rel"]}
    base.update(over)
    return base


class SavedStyleSchemaTests(unittest.TestCase):
    def test_every_rejection_names_what_is_wrong(self):
        """A stranger's file must never arrive as a traceback, and a hand-edited
        one has to say which field to fix. Each case asserts on the REASON, not
        merely that it raised."""
        cases = [
            ({"schema_version": 99, "name": "x", "base": "realism",
              "model": "m.safetensors"}, "schema_version"),
            (style(name="  "), "needs a name"),
            (style(name="x" * 65), "longer than 64"),
            (style(base="nope"), "unknown base recipe"),
            (style(model=""), "name the model"),
            (style(aspect="17:4 (Nope)"), "unknown canvas"),
            (style(mp="wide"), "megapixels must be a number"),
            (style(mp=99), "between 0.1 and 8"),
            (style(tuning={"steps": 0}), "between 1 and 200"),
            (style(tuning={"steps": "many"}), "whole number"),
            (style(tuning={"cfg": 999}), "between 0 and 30"),
            (style(tuning={"eta": "lots"}), "eta must be a number"),
            (style(tuning={"eta": 900}), "between -100 and 100"),
            (style(tuning={"guidance": 3}), "unknown tuning setting"),
            (style(tuning={"sampler_name": ""}), "cannot be empty"),
            (style(provenance="me"), "provenance must be an object"),
        ]
        for raw, fragment in cases:
            with self.subTest(reason=fragment):
                with self.assertRaises(ValueError) as caught:
                    server.validate_saved_style(raw)
                self.assertIn(fragment, str(caught.exception))

    def test_source_only_recipes_cannot_be_styles(self):
        """The style picker offers creative direction. A recipe that needs a
        finished frame has no look of its own to bottle, so it stays out."""
        self.assertNotIn("qwen_edit", server.STYLE_BASE_IDS)
        self.assertNotIn("klein_inpaint", server.STYLE_BASE_IDS)
        self.assertNotIn("face_mint", server.STYLE_BASE_IDS)
        for rid in ("realism", "realism_ii", "fantasy", "anime", "zimage",
                    "qwen_image", "anima", "identity_edit"):
            self.assertIn(rid, server.STYLE_BASE_IDS)
        with self.assertRaisesRegex(ValueError, "cannot be a style"):
            server.validate_saved_style(style(base="qwen_edit"))

    def test_an_identity_edit_style_records_its_anchor_requirement(self):
        """Bottling an Identity Edit look is the point of "save this style"
        (Jesse, 2026-08-22): the base is allowed, and the saved record carries
        the anchor requirement so selecting it later asks for a character
        instead of failing at render time. The flag is derived from the base,
        never taken from the file."""
        record = server.validate_saved_style(style(base="identity_edit"))
        self.assertIs(record["needs_character"], True)
        # A style on an ordinary base must not acquire the requirement, even
        # if a hand-edited file claims it.
        plain = server.validate_saved_style(style(needs_character=True))
        self.assertNotIn("needs_character", plain)
        with catalog(KREA):
            self.assertIs(server.check_style_runnable(record), record)

    def test_id_is_slugged_and_cannot_shadow_a_builtin(self):
        """The ID is slugged because it addresses a file. The NAME is the
        user's, and keeps its punctuation - only runs of whitespace collapse."""
        record = server.validate_saved_style(style(name="Grainy  Portrait!"))
        self.assertEqual(record["id"], "grainy_portrait")
        self.assertEqual(record["name"], "Grainy Portrait!")
        with self.assertRaisesRegex(ValueError, "built-in recipe id"):
            server.validate_saved_style(style(id="realism"))

    def test_id_alphabet_cannot_escape_the_recipes_directory(self):
        """The id addresses a file. Traversal has to die in validation, not at
        the filesystem."""
        for hostile in ("../../etc/passwd", "..\\..\\config", "/abs/path"):
            with self.subTest(id=hostile):
                record = server.validate_saved_style(style(id=hostile, name="Safe"))
                self.assertRegex(record["id"], r"\A[a-z0-9_]+\Z")
                self.assertNotIn("..", record["id"])
                self.assertNotIn("/", record["id"])
                self.assertNotIn("\\", record["id"])

    def test_a_style_keeps_only_what_it_was_given(self):
        """Absent optional fields stay absent, so the file a user shares says
        exactly what they chose and nothing they did not."""
        record = server.validate_saved_style(style())
        self.assertNotIn("aspect", record)
        self.assertNotIn("mp", record)
        self.assertNotIn("lora_plan", record)
        self.assertEqual(record["tuning"], {})


class SamplerSeatTests(unittest.TestCase):
    def test_the_seat_belongs_to_the_pairing_not_the_recipe(self):
        """Z-Image Turbo's Amazing v4 profile DELETES the KSampler and builds a
        two-pass sigma schedule instead (see _build_zimage). Base keeps its
        KSampler; Turbo gets the v4 seat, whose keys MAP to the nodes that
        carry them (Jesse, 2026-08-26: tuning in every recipe) - the sampler on
        the KSamplerSelect, steps on the Karras schedule, cfg on both passes,
        and no scheduler box, since the schedule IS the graph."""
        with catalog(ZBASE):
            self.assertEqual(server.sampler_seat("zimage", ZBASE["rel"])["node"], "8")
        with catalog(ZTURBO):
            seat = server.sampler_seat("zimage", ZTURBO["rel"])
            self.assertIs(seat, server.ZIMAGE_V4_SEAT)
            self.assertEqual(server.seat_tuning_keys(seat), ("steps", "cfg", "sampler_name"))
            self.assertNotIn("scheduler", server.sampler_defaults("zimage", ZTURBO["rel"]))

    def test_realism_ii_tunes_its_first_pass_only(self):
        """The first pass is the sample; the 2-step refine at denoise 0.2 (node
        274) is what "refined" means and stays authored."""
        template = server.TEMPLATES["realism_ii"]
        seat = server.SAMPLER_SEATS["realism_ii"]
        self.assertEqual(seat["node"], "265")
        self.assertEqual(template["265"]["inputs"]["denoise"], 1.0)
        with catalog(KREA):
            got = server.tuning_overrides("realism_ii", KREA["rel"], {"steps": 12})
        self.assertEqual(got, [{"node": "265", "input": "steps", "value": 12}])

    def test_seats_point_at_nodes_that_exist_in_their_template(self):
        """A seat naming a node the template does not have would raise KeyError
        inside the builder's override loop, at queue time, on the user."""
        for base_id, seat in server.SAMPLER_SEATS.items():
            with self.subTest(recipe=base_id):
                template = server.TEMPLATES[
                    "zimage" if server.RECIPE_SPECS[base_id]["family"] == "zimage"
                    else base_id]
                self.assertIn(seat["node"], template)
                self.assertEqual(template[seat["node"]]["class_type"], seat["class"])

    def test_tuning_becomes_overrides_only_where_there_is_a_seat(self):
        tuning = {"steps": 12, "cfg": 2.5, "sampler_name": "euler",
                  "scheduler": "beta"}
        with catalog(ZBASE):
            got = server.tuning_overrides("zimage", ZBASE["rel"], tuning)
        self.assertEqual(got, [
            {"node": "8", "input": "steps", "value": 12},
            {"node": "8", "input": "cfg", "value": 2.5},
            {"node": "8", "input": "sampler_name", "value": "euler"},
            {"node": "8", "input": "scheduler", "value": "beta"},
        ])
        # On a Turbo build the same tuning lands on the v4 graph's own nodes:
        # steps on the schedule, cfg on both passes, the sampler on the
        # selector - and the scheduler key, which has no node, is dropped.
        with catalog(ZTURBO):
            self.assertEqual(
                server.tuning_overrides("zimage", ZTURBO["rel"], tuning), [
                    {"node": "z:v4:sigmas", "input": "steps", "value": 12},
                    {"node": "z:v4:high", "input": "cfg", "value": 2.5},
                    {"node": "z:v4:low", "input": "cfg", "value": 2.5},
                    {"node": "z:v4:sampler", "input": "sampler_name", "value": "euler"},
                ])

    def test_eta_belongs_to_the_seat_that_has_it(self):
        """eta is RES4LYF's stochasticity dial and only ClownsharKSampler_Beta
        has the input. A stock KSampler does not, so an eta written into its
        inputs is a ComfyUI error at queue time - on the user, after the wait.
        The editor is told which keys exist, and a save is refused by name."""
        self.assertEqual(
            server.seat_tuning_keys(server.SAMPLER_SEATS["realism"]),
            ("steps", "cfg", "sampler_name", "scheduler", "eta"))
        self.assertEqual(
            server.seat_tuning_keys(server.SAMPLER_SEATS["zimage"]),
            ("steps", "cfg", "sampler_name", "scheduler"))
        self.assertEqual(server.seat_tuning_keys(None), ())

        tuning = {"steps": 5, "eta": 0.75}
        with catalog(KREA):
            self.assertEqual(server.tuning_overrides("realism", KREA["rel"], tuning), [
                {"node": "30:51", "input": "steps", "value": 5},
                {"node": "30:51", "input": "eta", "value": 0.75},
            ])
            self.assertEqual(
                server.sampler_defaults("realism", KREA["rel"])["eta"],
                server.TEMPLATES["realism"]["30:51"]["inputs"]["eta"])
        # A KSampler seat drops it rather than writing an input that is not
        # there, and says so at save time instead of at queue time.
        with catalog(ZBASE):
            self.assertEqual(
                server.tuning_overrides("zimage", ZBASE["rel"], tuning),
                [{"node": "8", "input": "steps", "value": 5}])
            self.assertNotIn("eta", server.sampler_defaults("zimage", ZBASE["rel"]))
            record = server.validate_saved_style(
                style(base="zimage", model=ZBASE["rel"], tuning={"eta": 0.75}))
            with self.assertRaisesRegex(ValueError, "KSampler has no eta setting"):
                server.check_style_runnable(record)

    def test_probed_enums_are_read_from_the_live_install(self):
        """RES4LYF's sampler names are compound ("linear/euler") and a stock
        KSampler would reject them, so the list cannot be hardcoded."""
        probe = {"ClownsharKSampler_Beta": {
            "sampler_name": ["linear/euler", "multistep/deis_3m"],
            "scheduler": ["simple", "bong_tangent"]}}
        with patch.dict(server._COMFY_NODES, {"enums": probe}):
            got = server.sampler_choices("ClownsharKSampler_Beta")
            self.assertIn("linear/euler", got["sampler_name"])
            self.assertIn("bong_tangent", got["scheduler"])
            record = server.validate_saved_style(
                style(tuning={"sampler_name": "not_a_sampler"}))
            with catalog(KREA):
                with self.assertRaisesRegex(ValueError, "no sampler_name called"):
                    server.check_style_runnable(record)

    def test_object_info_combos_parse_in_both_comfy_dialects(self):
        """This ComfyUI serves BOTH spellings at once - the stock KSampler still
        uses the legacy nested list, RES4LYF's Clownshar node uses the v3
        ["COMBO", {"options": [...]}] form. Handling only one yields an empty
        dropdown that looks exactly like "ComfyUI is not running"."""
        legacy = [["euler", "heun", "dpmpp_2m"], {"default": "euler"}]
        v3 = ["COMBO", {"default": "multistep/res_2m",
                        "options": ["none", "linear/euler", "multistep/res_2m"]}]
        self.assertEqual(server._combo_choices(legacy), ["euler", "heun", "dpmpp_2m"])
        self.assertEqual(server._combo_choices(v3),
                         ["none", "linear/euler", "multistep/res_2m"])
        for junk in (None, [], {}, "euler", ["COMBO"], ["COMBO", {}]):
            with self.subTest(spec=junk):
                self.assertEqual(server._combo_choices(junk), [])

    def test_an_unprobed_comfy_does_not_refuse_every_style(self):
        """Empty enums mean "not asked yet", never "no valid values"."""
        record = server.validate_saved_style(style(tuning={"sampler_name": "euler"}))
        with patch.dict(server._COMFY_NODES, {"enums": {}}), catalog(KREA):
            self.assertIs(server.check_style_runnable(record), record)


class SavedStyleRoutingTests(unittest.TestCase):
    def test_a_saved_style_selects_its_own_graph(self):
        record = server.validate_saved_style(style(base="anima",
                                                   model="Anima\\anima-base-v1.0.safetensors"))
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}):
            self.assertEqual(
                server.effective_recipe({"saved_style": record["id"],
                                         "style": "realism", "quality": "refined"}),
                "anima")

    def test_identity_still_outranks_a_saved_style(self):
        """A character IS the style - selecting one has to win, or picking an
        anchor would silently render someone else."""
        record = server.validate_saved_style(style())
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}):
            self.assertEqual(
                server.effective_recipe({"saved_style": record["id"],
                                         "character": "hero"}), "identity_edit")

    def test_a_deleted_style_does_not_take_the_render_down(self):
        """Deleted in another tab, still selected in this one. It must fall
        back to ordinary style routing, not raise."""
        self.assertEqual(
            server.effective_recipe({"saved_style": "gone_forever",
                                     "style": "anime"}), "anime")

    def test_the_file_beats_the_composers_mirror(self):
        """The browser mirrors a style's model and plan so the pills read true.
        A mirror goes stale between two tabs, so the render reads the FILE."""
        record = server.validate_saved_style(style(
            model=KREA["rel"], aspect="1:1 (Square)", mp=1.0,
            tuning={"steps": 14, "cfg": 2.0}))
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            recipe = server._apply_opts(args, {
                "saved_style": record["id"],
                "model": "ZiT\\something-else.safetensors",
            })
        self.assertEqual(recipe, "realism")
        self.assertEqual(args["model"], KREA["rel"])
        self.assertEqual(args["aspect"], "1:1 (Square)")
        self.assertEqual(args["overrides"], [
            {"node": "30:51", "input": "steps", "value": 14},
            {"node": "30:51", "input": "cfg", "value": 2.0},
        ])

    def test_the_render_records_which_style_produced_it(self):
        """Everything a style does is folded into ordinary args, so without a
        tag the job receipt can only ever name the base recipe - and a card
        reading "Realism" for an Ultra Realism picture identifies nothing."""
        record = server.validate_saved_style(style())
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"]})
        self.assertEqual(args["_style"],
                         {"id": record["id"], "name": record["name"],
                          "base": record["base"]})

    def test_no_style_leaves_no_tag(self):
        """A free-mode render must not carry an empty style badge."""
        args = {}
        with catalog(KREA):
            server._apply_opts(args, {"style": "realism"})
        self.assertNotIn("_style", args)

    def test_a_direction_on_the_photo_graph_names_itself(self):
        """Krea 2 has no anime graph, so picking Anime runs the realism recipe
        with the craft register spliced in - and the card said "Realism" over
        a cel-shaded picture. The direction is a choice too, so it tags."""
        args = {}
        with catalog(KREA):
            server._apply_opts(args, {"style": "anime", "model": KREA["rel"]})
        self.assertEqual(args["_style"], {"id": "", "name": "Anime",
                                          "base": "realism", "direction": True})

    def test_a_graph_that_draws_the_style_itself_keeps_its_own_name(self):
        """On a recipe style_directive does not fire for, the recipe name IS
        the true one - a second tag would only ever restate it."""
        args = {}
        with catalog(KREA):
            server._apply_opts(args, {"style": "anime"})
        self.assertEqual(server.effective_recipe({"style": "anime"}), "anime")
        self.assertNotIn("_style", args)

    def test_a_saved_style_still_outranks_a_direction(self):
        """The preset is the more specific name for what ran."""
        record = server.validate_saved_style(style())
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"],
                                      "style": "anime", "model": KREA["rel"]})
        self.assertEqual(args["_style"]["name"], record["name"])

    def test_the_style_tag_never_reaches_a_builder_signature(self):
        """It rides in args only as far as submit(), which pops it the way it
        pops seed. If it ever matched a builder parameter it would be passed
        as a real graph input instead."""
        for template, params in server.SIGS.items():
            self.assertNotIn("_style", params, f"{template} would swallow the tag")

    def test_an_explicit_canvas_pick_still_wins(self):
        """The style's canvas is a saved default; the size pill is a live
        choice the user just made."""
        record = server.validate_saved_style(style(aspect="1:1 (Square)"))
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"],
                                      "aspect": "16:9 (Widescreen)"})
        self.assertEqual(args["aspect"], "16:9 (Widescreen)")

    def test_a_planless_style_runs_recipe_defaults(self):
        """With no stack on either side, the base recipe's own defaults run."""
        record = server.validate_saved_style(style())
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"]})
        self.assertNotIn("lora_plan", args)
        self.assertNotIn("loras", args)

    def test_a_lora_added_by_hand_beats_the_styles_own_stack(self):
        """A preset is a base to work from: you keep it selected and try LoRAs
        against it. The file stays authoritative for model, canvas and sampler
        - things a mirror can go stale about - but a stack the user just edited
        is the stack that has to render."""
        record = server.validate_saved_style(style(lora_plan={
            "version": 1, "recipe": "realism", "recipe_revision":
                server.RECIPE_SPECS["realism"]["lora_stack_revision"],
            "mode": "replace_editable",
            "entries": [{"name": "Krea 2\\LARP_v0-5.safetensors", "strength": 1.5}]}))
        edited = {"version": 1, "recipe": "realism", "recipe_revision":
                  server.RECIPE_SPECS["realism"]["lora_stack_revision"],
                  "mode": "replace_editable",
                  "entries": [{"name": "Krea 2\\LARP_v0-5.safetensors", "strength": 1.5},
                              {"name": "Krea 2\\added_by_hand.safetensors", "strength": 0.8}]}
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"],
                                      "lora_plan": edited})
        self.assertEqual(args["lora_plan"], edited)

    def test_editing_the_stack_keeps_the_styles_sampler(self):
        """The regression this pairs with: tuning lives only in the style file
        and only applies while the style is selected, so anything that dropped
        the selection silently took Ultra Realism's 5 steps back to Realism's
        8 with every visible pill unchanged."""
        record = server.validate_saved_style(style(tuning={"steps": 5, "cfg": 1.0}))
        edited = {"version": 1, "recipe": "realism", "recipe_revision":
                  server.RECIPE_SPECS["realism"]["lora_stack_revision"],
                  "mode": "replace_editable",
                  "entries": [{"name": "Krea 2\\added_by_hand.safetensors", "strength": 0.8}]}
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"],
                                      "lora_plan": edited})
        steps = [o for o in args["overrides"] if o["input"] == "steps"]
        self.assertEqual([o["value"] for o in steps], [5])

    def test_overrides_reach_the_graph_the_builder_actually_builds(self):
        """The end of the chain: a tuned style has to change the sampler node in
        the BUILT graph, not merely produce a plausible-looking args dict."""
        record = server.validate_saved_style(style(
            tuning={"steps": 14, "cfg": 2.0, "scheduler": "beta"}))
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), catalog(KREA):
            server._apply_opts(args, {"saved_style": record["id"]})
            # submit() strips the receipt tag before the builder ever sees the
            # args; do the same here rather than teaching builders to ignore it.
            args.pop("_style", None)
            graph, _cap, _info = server.build_realism("a portrait", 5, **args)
        sampler = graph["30:51"]["inputs"]
        self.assertEqual((sampler["steps"], sampler["cfg"], sampler["scheduler"]),
                         (14, 2.0, "beta"))


class SavedStyleStorageTests(unittest.TestCase):
    def test_one_bad_file_never_takes_the_others_down(self):
        """A folder is a shared namespace: a hand-edited or half-downloaded file
        must cost only itself, and say why."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "good.json").write_text(
                '{"schema_version": 1, "name": "Good", "base": "realism",'
                ' "model": "Krea 2\\\\m.safetensors"}', encoding="utf-8")
            (root / "broken.json").write_text("{not json", encoding="utf-8")
            (root / "wrong.json").write_text(
                '{"schema_version": 1, "name": "No Base"}', encoding="utf-8")
            with patch.object(server, "RECIPE_DIR", root):
                styles, problems = server.load_saved_styles()
        self.assertEqual(list(styles), ["good"])
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("broken.json" in p and "JSON" in p for p in problems))
        self.assertTrue(any("wrong.json" in p and "base recipe" in p for p in problems))

    def test_a_stale_lora_revision_is_restamped_not_refused(self):
        """A style FILE outlives recipe revisions. Realism went to revision 2 on
        2026-08-13; a plan written before that must not be dead forever."""
        current = server.RECIPE_SPECS["realism"]["lora_stack_revision"]
        record = server.validate_saved_style(style(lora_plan={
            "version": 1, "recipe": "realism", "recipe_revision": current - 1,
            "mode": "replace_editable",
            "entries": [{"slot": "realistic_snapshot", "strength": 0.6}]}))
        self.assertEqual(record["lora_plan"]["recipe_revision"], current)
        self.assertEqual(record["lora_plan"]["entries"][0]["strength"], 0.6)

    def test_a_genuinely_broken_plan_keeps_its_own_reason(self):
        """Only the revision gate is healed. A plan naming a slot that is not
        editable is a real error and has to stay one."""
        with self.assertRaisesRegex(ValueError, "not editable"):
            server.validate_saved_style(style(lora_plan={
                "version": 1, "recipe": "realism",
                "recipe_revision": server.RECIPE_SPECS["realism"]["lora_stack_revision"],
                "mode": "replace_editable",
                "entries": [{"slot": "vector_bypass", "strength": 0.0}]}))

    def test_saving_writes_one_file_named_for_its_id(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            record = server.validate_saved_style(style(name="Night Market"))
            with patch.object(server, "RECIPE_DIR", root), \
                 patch.dict(server.SAVED_STYLES, {}, clear=True):
                path = server.write_saved_style(record)
                self.assertEqual(path.name, "night_market.json")
                with patch.object(server, "RECIPE_DIR", root):
                    styles, problems = server.load_saved_styles()
        self.assertEqual(problems, [])
        self.assertEqual(styles["night_market"]["name"], "Night Market")

    def test_a_missing_model_greys_the_style_rather_than_hiding_it(self):
        """Load-time validation deliberately does not touch the catalog: a style
        whose model is temporarily gone must still SHOW, with a reason."""
        record = server.validate_saved_style(style())
        with patch.object(server, "resolve_model_entry", return_value=None):
            missing = server.style_missing(record)
        self.assertTrue(any("not installed" in m for m in missing))

    def test_a_cross_family_pairing_is_refused_at_save_time(self):
        record = server.validate_saved_style(style(base="realism",
                                                   model=ZTURBO["rel"]))
        with catalog(ZTURBO):
            with self.assertRaisesRegex(ValueError, "but Realism needs krea2"):
                server.check_style_runnable(record)


if __name__ == "__main__":
    unittest.main()


class QuickTuningTests(unittest.TestCase):
    """The composer's per-render tuning card (2026-08-26): a sparse override
    that rides /api/chat as opts.tuning, on whatever seat the running graph
    has, over a selected style's own tuning."""

    ENUMS = {"ClownsharKSampler_Beta": {
        "sampler_name": ["linear/euler", "res_2s", "re_sde"],
        "scheduler": ["simple", "beta"]}}

    def test_cfg_is_locked_where_the_seat_is_authored_at_one(self):
        # Distilled builds sample at cfg 1 by authoring; the composer greys
        # the box instead of letting a 4 double the time and burn the image.
        with catalog(KREA):
            self.assertTrue(server.cfg_locked("realism", KREA["rel"]))
        with catalog(ZBASE):
            self.assertFalse(server.cfg_locked("zimage", ZBASE["rel"]))

    def test_the_model_page_recommendation_becomes_a_tuning_block(self):
        page = {"modelDescription": "<p>intro</p><p>推荐设置: re_sde + simple, "
                                    "8-16 steps, 1 cfg</p>"}
        with catalog(KREA), patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}), \
                patch.object(server, "adjacent_metadata", return_value=page):
            got = server.model_recommended_tuning("realism", KREA["rel"])
        self.assertEqual(got["sampler_name"], "re_sde")
        self.assertEqual(got["scheduler"], "simple")
        self.assertEqual(got["steps"], 8)
        self.assertEqual(got["cfg"], 1.0)
        with catalog(KREA), patch.object(server, "adjacent_metadata",
                                         return_value={"modelDescription": "no advice"}):
            self.assertIsNone(server.model_recommended_tuning("realism", KREA["rel"]))

    def test_the_override_rides_the_seat_and_is_recorded(self):
        opts = {"model": KREA["rel"], "style": "realism",
                "tuning": {"steps": 12, "sampler_name": "res_2s",
                           "scheduler": "not_offered"}}
        args = {}
        with catalog(KREA), patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}):
            self.assertEqual(server._apply_opts(args, opts), "realism")
        overrides = {(o["input"], o["value"]) for o in args["overrides"]}
        self.assertIn(("steps", 12), overrides)
        self.assertIn(("sampler_name", "res_2s"), overrides)
        # A value the seat does not offer is dropped, never queued to fail.
        self.assertNotIn(("scheduler", "not_offered"), overrides)
        self.assertEqual(args["_tuning"]["steps"], 12)
        self.assertEqual(args["_tuning"]["scheduler"], "simple")   # the recipe's own
        self.assertIn("_tuning", server._REROLL_COMPOSER_OWNED)

    def test_an_untouched_card_changes_nothing(self):
        args = {}
        with catalog(KREA):
            server._apply_opts(args, {"model": KREA["rel"], "style": "realism", "tuning": {}})
        self.assertNotIn("overrides", args)
        self.assertNotIn("_tuning", args)

    def test_a_bad_value_is_refused_by_name(self):
        with catalog(KREA):
            with self.assertRaisesRegex(ValueError, "tuning: steps"):
                server._apply_opts({}, {"model": KREA["rel"], "style": "realism",
                                        "tuning": {"steps": "lots"}})


class StockSamplerSwapTests(unittest.TestCase):
    """A stock KSampler name on a Clownshark seat (Jesse, 2026-08-26:
    "re_sde ... make those available") swaps the node at build time."""

    ENUMS = {"ClownsharKSampler_Beta": {"sampler_name": ["linear/euler", "res_2s"],
                                        "scheduler": ["simple", "bong_tangent"]},
             "KSampler": {"sampler_name": ["euler", "re_sde", "er_sde"],
                          "scheduler": ["simple", "karras"]}}

    def test_the_seat_offers_both_families_split_by_node(self):
        seat = server.SAMPLER_SEATS["realism"]
        with patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}):
            self.assertEqual(server.seat_choices(seat)["sampler_name"],
                             ["linear/euler", "res_2s", "euler", "re_sde", "er_sde"])
            groups = server.seat_choice_groups(seat)["sampler_name"]
            self.assertEqual([g["label"] for g in groups], ["RES4LYF", "ComfyUI KSampler"])
            self.assertIn("re_sde", groups[1]["ids"])
            self.assertEqual(server.seat_choice_groups(server.SAMPLER_SEATS["anima"]), {})

    def test_a_stock_name_swaps_the_node_and_keeps_the_links(self):
        seat = server.SAMPLER_SEATS["realism"]
        tuning = {"sampler_name": "re_sde", "scheduler": "bong_tangent", "steps": 12, "eta": 0.5}
        with patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}), catalog(KREA):
            swap = server.sampler_swap(seat, tuning)
            self.assertEqual(swap, {"node": "30:51", "sampler_name": "re_sde",
                                    "scheduler": "simple"})   # not a KSampler scheduler -> simple
            overrides = server.tuning_overrides("realism", KREA["rel"], tuning)
        self.assertEqual(overrides, [{"node": "30:51", "input": "steps", "value": 12}])
        g = {"30:51": {"class_type": "ClownsharKSampler_Beta", "inputs": {
            "model": ["m", 0], "positive": ["p", 0], "negative": ["n", 0],
            "latent_image": ["l", 0], "seed": 7, "steps": 12, "cfg": 1.0,
            "eta": 0.5, "bongmath": True, "denoise": 1.0}}}
        server.swap_sampler_node(g, swap)
        node = g["30:51"]
        self.assertEqual(node["class_type"], "KSampler")
        self.assertEqual(node["inputs"]["model"], ["m", 0])
        self.assertEqual(node["inputs"]["latent_image"], ["l", 0])
        self.assertEqual(node["inputs"]["steps"], 12)
        self.assertEqual(node["inputs"]["sampler_name"], "re_sde")
        self.assertNotIn("eta", node["inputs"])

    def test_a_clownshark_name_never_swaps(self):
        with patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}):
            self.assertIsNone(server.sampler_swap(server.SAMPLER_SEATS["realism"],
                                                  {"sampler_name": "res_2s"}))

    def test_the_composer_override_rides_the_swap_to_submit(self):
        opts = {"model": KREA["rel"], "style": "realism",
                "tuning": {"sampler_name": "er_sde", "scheduler": "karras"}}
        args = {}
        with patch.dict(server._COMFY_NODES, {"enums": self.ENUMS}), catalog(KREA):
            server._apply_opts(args, opts)
        self.assertEqual(args["_sampler_swap"],
                         {"node": "30:51", "sampler_name": "er_sde", "scheduler": "karras"})
        self.assertIn("_sampler_swap", server._REROLL_COMPOSER_OWNED)
