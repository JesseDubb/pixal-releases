"""The combo shelf: pairs to audition, and the ones you kept.

The presets beside it are the three or four schedules somebody stands behind.
This is the other half - a shelf of sampler x scheduler pairs the card walks
with two arrows, seeded with the community report's graphic-quality ranking and
extended by a star (Jesse, 2026-09-02: "make it easy to save combos of sampler
scheduler you like right in the panel / sampler card ... I want these loaded up
and a little arrow left right to select the combo presets").

What these tests protect is not the ranking - it is noise above 4.5 and says so
- but the four properties that make a shelf safe to click through blind:

  * an arrow can never land on a name this seat would refuse,
  * a row never claims a measurement it does not have,
  * starring is idempotent and starring twice cannot mint a duplicate,
  * and the file lives beside config.json, not inside it, so a config that
    falls back to defaults cannot take the kept pairs with it.
"""
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


_ROOT = Path(__file__).resolve().parents[1]
_SPEC = spec_from_file_location("pixal_server_combos", _ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

H3_STILL = "h3_ref_still"
KREA = "realism"
H3_FAMILY = "minimax_h3"


class _Isolated(unittest.TestCase):
    """Never touch the real sampler_combos.json - it holds Jesse's own pairs."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.file = Path(self._dir.name) / "sampler_combos.json"
        patcher = patch.object(server, "SAMPLER_COMBOS", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)


class TableTests(unittest.TestCase):
    """The seeded rows."""

    def test_five_a_family_and_no_more(self):
        """Jesse, 2026-09-03: "drop the extra 10 presets from minimax h3, the
        bottom of that list had terrible combos" ... "shoot for 5 excellent
        combos per model type." Twelve of the old twenty were 5.00 scores
        standing on one or two votes - an ordering that is mostly noise, and it
        was being walked one blind arrow-press at a time."""
        for family, rows in server.COMMUNITY_COMBOS.items():
            with self.subTest(family=family):
                self.assertEqual(len(rows), 5)

    def test_no_pair_appears_twice(self):
        """A duplicate pair would be two shelf positions that do the same
        thing, and the second could never be reached by the star."""
        for family, rows in server.COMMUNITY_COMBOS.items():
            pairs = [(s, c) for s, c, _note in rows]
            with self.subTest(family=family):
                self.assertEqual(len(pairs), len(set(pairs)))

    def test_every_row_says_where_it_came_from(self):
        """A shelf mixing our own A/Bs with somebody's published pair with
        Jesse's saved styles cannot flatten the three into one claim - so the
        provenance rides on the row, not in a footnote nobody reads."""
        for family, rows in server.COMMUNITY_COMBOS.items():
            for sampler, scheduler, note in rows:
                with self.subTest(family=family, pair=(sampler, scheduler)):
                    self.assertTrue(note.strip())
                    self.assertRegex(
                        note,
                        r"Measured here|Jesse|Not measured here"
                        r"|not a measurement|lead to render|RES4LYF")

    def test_what_we_measured_ourselves_leads_the_h3_shelf(self):
        """Position is the only ranking left, so the rows with a real A/B
        behind them have to be the ones the arrows reach first."""
        for _s, _c, note in server.H3_COMMUNITY_COMBOS[:2]:
            self.assertIn("Measured here", note)

    def test_no_row_names_a_scheduler_h3_measured_as_dead(self):
        """karras, exponential and kl_optimal scored 1.1-1.2 stars over
        hundreds of community votes on H3. A 5.00-from-one-vote row naming one
        of them would be the shelf handing over its own worst case."""
        dead = {"karras", "exponential", "kl_optimal"}
        for _sampler, scheduler, _note in server.H3_COMMUNITY_COMBOS:
            self.assertNotIn(scheduler, dead)

    def test_no_zimage_row_names_something_that_family_rates_dead(self):
        """karras and exponential are red down the entire column of a
        992-image Z-Image grid, and so is the whole res_multistep family."""
        for sampler, scheduler, _note in server.ZIMAGE_COMBOS:
            self.assertNotIn(scheduler, {"karras", "exponential"})
            self.assertNotIn("res_multistep", sampler)

    def test_the_three_families_with_a_shelf_are_the_three_in_use(self):
        self.assertEqual(set(server.COMMUNITY_COMBOS),
                         {H3_FAMILY, "krea2", "zimage"})


class ShelfTests(_Isolated):
    """What the card's arrows are handed."""

    def test_the_table_rows_are_offered_on_h3(self):
        with patch.object(server, "seat_choices", return_value={}):
            got = server.sampler_combos(H3_STILL, "")
        self.assertEqual(len(got), 5)
        self.assertTrue(all(c["source"] == "community" for c in got))

    def test_a_row_says_its_position_and_its_provenance(self):
        with patch.object(server, "seat_choices", return_value={}):
            first = server.sampler_combos(H3_STILL, "")[0]
        self.assertIn("#1 of 5", first["note"])
        self.assertIn("Measured here", first["note"])

    def test_every_row_carries_both_copy_registers(self):
        """`note` stands alone under the bar; `detail` sits in the list under a
        group heading that has already named the source, so it must not repeat
        it. One string doing both jobs read wrong in one of the two places."""
        with patch.object(server, "seat_choices", return_value={}):
            rows = server.sampler_combos(H3_STILL, "")
        for c in rows:
            with self.subTest(pair=c["tuning"]):
                self.assertTrue(c["note"].strip())
                self.assertTrue(c["detail"].strip())
                self.assertNotIn("Community", c["detail"])

    def test_a_value_the_seat_does_not_offer_drops_the_pair(self):
        """The whole point of the arrows is that you can hold one down without
        reading. Nothing they land on may be a name the graph would refuse."""
        with patch.object(server, "seat_choices",
                          return_value={"sampler_name": ["res_multistep"],
                                        "scheduler": ["simple"]}):
            got = server.sampler_combos(H3_STILL, "")
        self.assertEqual([(c["tuning"]["sampler_name"], c["tuning"]["scheduler"])
                          for c in got],
                         [("res_multistep", "simple")])

    def test_an_unprobed_comfy_filters_nothing_rather_than_everything(self):
        """sampler_choices answers {} before ComfyUI has been probed. Reading
        that as "no valid values" would empty the shelf on a cold boot."""
        with patch.object(server, "sampler_choices", return_value={}):
            self.assertEqual(len(server.sampler_combos(H3_STILL, "")), 5)

    def test_a_seat_without_both_halves_gets_no_shelf(self):
        """A pair needs a sampler AND a scheduler to mean anything."""
        with patch.object(server, "seat_tuning_keys", return_value=("steps",)):
            self.assertEqual(server.sampler_combos(H3_STILL, ""), [])

    def test_an_unknown_recipe_yields_nothing_rather_than_raising(self):
        self.assertEqual(server.sampler_combos("no_such_recipe", ""), [])

    def test_krea_has_its_own_shelf_now(self):
        """It had no table, so the star was the only way anything got there.
        Jesse, 2026-09-03: the shipped Krea pairs were "a bit gritty" and he
        had already saved better ones - those are the shelf."""
        with patch.object(server, "seat_choices", return_value={}):
            got = server.sampler_combos(KREA, "")
        self.assertEqual(len(got), 5)
        self.assertIn("Jesse's", got[0]["note"])

    def test_a_krea_star_still_leads_its_own_shelf(self):
        with patch.object(server, "seat_choices", return_value={}):
            server.star_combo("krea2", "multistep/res_2m", "beta57")
            got = server.sampler_combos(KREA, "")
        self.assertEqual(got[0]["source"], "saved")
        self.assertEqual(len(got), 5)        # a table row, so no duplicate


class StarTests(_Isolated):
    """Keeping one, and dropping it again."""

    def test_a_starred_table_pair_keeps_its_position(self):
        """dpmpp_sde_gpu x ddim_uniform is #5 of 5. Keeping it must not cost it
        the standing that made it worth keeping."""
        with patch.object(server, "seat_choices", return_value={}):
            server.star_combo(H3_FAMILY, "dpmpp_sde_gpu", "ddim_uniform")
            row = server.sampler_combos(H3_STILL, "")[0]
        self.assertEqual(row["source"], "saved")
        self.assertIn("#5 of 5", row["note"])
        self.assertIn("#5 of 5", row["detail"])

    def test_a_starred_pair_the_table_never_rated_says_only_that(self):
        with patch.object(server, "seat_choices", return_value={}):
            server.star_combo(H3_FAMILY, "euler", "beta")
            row = server.sampler_combos(H3_STILL, "")[0]
        self.assertNotIn("#", row["note"])
        self.assertIn("Yours", row["note"])

    def test_a_starred_pair_leads_the_shelf(self):
        with patch.object(server, "seat_choices", return_value={}):
            server.star_combo(H3_FAMILY, "euler", "beta")
            got = server.sampler_combos(H3_STILL, "")
        self.assertEqual(got[0]["source"], "saved")
        self.assertEqual(got[0]["tuning"],
                         {"sampler_name": "euler", "scheduler": "beta"})
        self.assertEqual(len(got), 6)

    def test_starring_the_same_pair_twice_does_not_mint_a_duplicate(self):
        server.star_combo(H3_FAMILY, "euler", "beta")
        server.star_combo(H3_FAMILY, "euler", "beta")
        self.assertEqual(len(server.load_saved_combos()), 1)

    def test_a_starred_community_pair_appears_once_and_as_yours(self):
        """dpmpp_sde_gpu x beta is #1. Starring it must not put the same pair
        on the shelf twice - two positions that do the same thing, one of which
        the star could never reach."""
        with patch.object(server, "seat_choices", return_value={}):
            server.star_combo(H3_FAMILY, "dpmpp_sde_gpu", "beta")
            got = server.sampler_combos(H3_STILL, "")
        rows = [c for c in got
                if c["tuning"] == {"sampler_name": "dpmpp_sde_gpu",
                                   "scheduler": "beta"}]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "saved")
        self.assertEqual(len(got), 5)

    def test_the_newest_star_is_the_first_one_back(self):
        server.star_combo(H3_FAMILY, "euler", "beta")
        server.star_combo(H3_FAMILY, "ipndm", "sgm_uniform")
        self.assertEqual([r["sampler_name"] for r in server.load_saved_combos()],
                         ["ipndm", "euler"])

    def test_forgetting_removes_exactly_the_one_named(self):
        server.star_combo(H3_FAMILY, "euler", "beta")
        server.star_combo(H3_FAMILY, "euler", "simple")
        server.unstar_combo(H3_FAMILY, "euler", "beta")
        self.assertEqual([(r["sampler_name"], r["scheduler"])
                          for r in server.load_saved_combos()],
                         [("euler", "simple")])

    def test_forgetting_something_never_starred_is_not_an_error(self):
        server.star_combo(H3_FAMILY, "euler", "beta")
        server.unstar_combo(H3_FAMILY, "seeds_2", "ddim_uniform")
        self.assertEqual(len(server.load_saved_combos()), 1)

    def test_one_family_s_stars_do_not_show_on_another(self):
        """A RES4LYF name means nothing on H3's KSamplerSelect and the reverse.
        The seat filter would drop it anyway; the family keeps the shelf short
        and the note honest."""
        server.star_combo("krea2", "linear/euler", "simple")
        with patch.object(server, "seat_choices", return_value={}):
            got = server.sampler_combos(H3_STILL, "")
        self.assertTrue(all(c["source"] == "community" for c in got))

    def test_a_pair_this_seat_cannot_run_is_kept_but_not_offered(self):
        """Starred on one machine, opened on another that lacks the node: the
        row stays in the file (the model may come back) and simply does not
        appear on a seat that cannot name it."""
        server.star_combo(H3_FAMILY, "not_a_real_sampler", "simple")
        with patch.object(server, "seat_choices",
                          return_value={"sampler_name": ["euler"],
                                        "scheduler": ["simple"]}):
            got = server.sampler_combos(H3_STILL, "")
        self.assertTrue(all(c["source"] == "community" for c in got))
        self.assertEqual(len(server.load_saved_combos()), 1)


class FileTests(_Isolated):
    """Where the kept pairs live, and what happens when that file is wrong."""

    def test_they_do_not_live_in_config_json(self):
        """config.json's merge is a whitelist and an unreadable one falls back
        to defaults which then get saved over the real file - that has already
        happened on this box once. A starred combo is not worth losing to it."""
        server.star_combo(H3_FAMILY, "euler", "beta")
        self.assertTrue(self.file.exists())
        self.assertNotEqual(self.file.name, server.CONFIG.name)
        self.assertIn("combos", json.loads(self.file.read_text(encoding="utf-8")))

    def test_no_file_yet_is_an_empty_shelf_not_a_crash(self):
        self.assertFalse(self.file.exists())
        self.assertEqual(server.load_saved_combos(), [])

    def test_an_unreadable_file_is_reported_and_skipped(self):
        """One bad file must never take the card down."""
        self.file.write_text("{not json", encoding="utf-8")
        self.assertEqual(server.load_saved_combos(), [])

    def test_a_half_written_row_is_dropped_not_offered(self):
        self.file.write_text(json.dumps({"version": 1, "combos": [
            {"family": H3_FAMILY, "sampler_name": "euler"},          # no scheduler
            {"family": H3_FAMILY, "sampler_name": "euler", "scheduler": "beta"},
        ]}), encoding="utf-8")
        self.assertEqual([r["scheduler"] for r in server.load_saved_combos()], ["beta"])


class PayloadTests(unittest.TestCase):
    """The two ends the card actually talks to."""

    def test_the_seat_endpoint_publishes_the_shelf(self):
        src = (_ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('"combos": sampler_combos(base_id, model) if seat else []', src)

    def test_both_writes_are_routed(self):
        from pixal.http.routes import ROUTES, RouteSpec
        self.assertIn(RouteSpec("POST", "/api/sampler/combos/star", "sampler_combo_star"), ROUTES)
        self.assertIn(RouteSpec("POST", "/api/sampler/combos/forget", "sampler_combo_forget"), ROUTES)

    def test_the_write_routes_take_the_pair_never_an_id(self):
        """A RES4LYF sampler name carries a slash (multistep/res_2m), which does
        not survive a URL path - so neither route may grow one."""
        from pixal.http.routes import ROUTES
        self.assertFalse(any(spec.path.startswith("/api/sampler/combos/{") for spec in ROUTES))

    def test_the_card_steps_and_stars_them(self):
        jsx = (_ROOT / "web" / "src" / "components" / "Composer.jsx") \
            .read_text(encoding="utf-8")
        self.assertIn("const shelf = seat.combos || []", jsx)
        self.assertIn("const stepCombo = (dir) =>", jsx)
        self.assertIn("const toggleCombo = async () =>", jsx)
        self.assertIn("<ComboShelf", jsx)

    def test_the_shelf_lists_through_the_design_system_picker(self):
        """Twenty rows behind two arrows and nothing else would be a list you
        can only walk. The Picker is the app's dropdown - groups, descriptions,
        a filter past six, portalled out of the accordion's overflow - and
        DESIGN.md calls a hand-rolled equivalent a defect on sight."""
        jsx = (_ROOT / "web" / "src" / "components" / "Composer.jsx")             .read_text(encoding="utf-8")
        self.assertIn('<Picker label="combo"', jsx)
        self.assertIn("const comboOptions = [", jsx)

    def test_the_shelf_position_is_derived_never_stored(self):
        """One state. Whatever set the pair - an arrow, a preset pill, a Picker,
        the recipe itself - the bar says the same thing, so there is nothing to
        fall out of sync."""
        jsx = (_ROOT / "web" / "src" / "components" / "Composer.jsx") \
            .read_text(encoding="utf-8")
        self.assertIn("const comboIndex = shelf.findIndex((c) => samePair(c.tuning));", jsx)
        self.assertNotIn("setComboIndex", jsx)


if __name__ == "__main__":
    unittest.main()
