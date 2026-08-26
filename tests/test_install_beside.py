"""Brief 9.50 — the projector lands beside the brain, wherever the brain is.

server.py's _local_llm_mmproj discovers the vision projector by the chat
model's OWN folder (one glob), never by a fixed path. The catalog used to
say the opposite: the gguf counted as installed wherever it sat, while the
projector's dest was pinned to LLM/GGUF and counted as installed anywhere
too — so a model in text_encoders/Qwen with the projector in LLM/GGUF was
two green rows and a blind brain.

The fix is one catalog declaration, "beside": "<sibling dest>". These tests
pin its three states (stray-across-folders with a move, fresh-install dest,
beside-is-have), the download target when the projector is missing, the tidy
move on a full worker run, and the done-check that refuses to say "done"
while no mmproj sits beside the model.

Simulations only: temp-dir disk layouts, stubbed downloads/pip/shortcuts.
No network, no real ComfyUI, and the real config.json and install/_work are
never touched — pi.log is captured and pi.WORK/PIXAL point into the temp dir.
"""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True          # keep install/__pycache__ out of the repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "install"))
import pixal_install as pi

MODEL = "text_encoders/Qwen/qwen3-vl-4b-heretic-Q8_0.gguf"
MODEL_CAT = "LLM/GGUF/qwen3-vl-4b-heretic-Q8_0.gguf"
PROJ_CAT = "LLM/GGUF/qwen3-vl-4b-heretic.mmproj-f16.gguf"
PROJ_NAME = "qwen3-vl-4b-heretic.mmproj-f16.gguf"


def comfy_with(*rels):
    """A ComfyUI folder in a temp dir, with the given models on disk."""
    tmp = tempfile.TemporaryDirectory()
    cdir = Path(tmp.name) / "ComfyUI"
    (cdir / "models").mkdir(parents=True)
    (cdir / "main.py").write_text("# comfy", encoding="utf-8")
    for rel in rels:
        p = cdir / "models" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return tmp, cdir


def brain_files(cdir):
    found = pi.survey(str(cdir))
    return found, found["lanes"]["brain"]["files"]


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loglines = []
        self._saved = {k: getattr(pi, k, None) for k in
                       ("log", "WORK", "PIXAL", "TRANSFERS", "LAST_CLIENT",
                        "WORKER_THREAD")}
        self._state = copy.deepcopy(pi.STATE)
        pi.log = self.loglines.append
        pi.WORK = Path(self.tmp.name) / "_work"
        pi.TRANSFERS = 0
        pi.LAST_CLIENT = 0.0
        pi.WORKER_THREAD = None
        pi.CANCEL.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            setattr(pi, k, v)
        pi.STATE.clear()
        pi.STATE.update(copy.deepcopy(self._state))
        pi.CANCEL.clear()


class BesideSurveyTests(_Base):
    """The three states of the projector row, straight out of the brief."""

    def test_a_projector_in_the_wrong_folder_is_a_stray_with_a_move_beside_the_model(self):
        # Jesse's machine, 2026-08-25: the gguf satisfied in
        # text_encoders/Qwen, the projector sitting in LLM/GGUF.
        tmp, cdir = comfy_with(MODEL, PROJ_CAT)
        self.addCleanup(tmp.cleanup)
        found, files = brain_files(cdir)
        model, proj = files
        self.assertEqual(model["state"], "have")
        self.assertEqual(proj["state"], "stray")
        self.assertEqual(proj["at"], "llm/gguf/" + PROJ_NAME)
        # The row names where it must end up - the wizard's summary stays honest.
        self.assertEqual(proj["dest"],
                         "text_encoders/Qwen/" + PROJ_NAME)
        # "src" is the REAL path (the inventory key is lowercased, and a
        # case-sensitive filesystem - CI on Linux - cannot resolve it).
        self.assertEqual(found["moves"],
                         [{"from": "llm/gguf/" + PROJ_NAME,
                           "to": "text_encoders/Qwen/" + PROJ_NAME,
                           "src": str(cdir / "models" / "LLM" / "GGUF" / PROJ_NAME),
                           "name": PROJ_NAME}])

    def test_a_fresh_install_resolves_to_the_catalog_dest(self):
        tmp, cdir = comfy_with()
        self.addCleanup(tmp.cleanup)
        found, files = brain_files(cdir)
        model, proj = files
        self.assertEqual(model["state"], "missing")
        self.assertEqual(proj["state"], "missing")
        self.assertEqual(proj["dest"], PROJ_CAT)     # nothing changes there
        self.assertEqual(found["moves"], [])

    def test_a_projector_beside_the_model_is_have(self):
        tmp, cdir = comfy_with(MODEL, "text_encoders/Qwen/" + PROJ_NAME)
        self.addCleanup(tmp.cleanup)
        found, files = brain_files(cdir)
        proj = files[1]
        self.assertEqual(proj["state"], "have")
        self.assertEqual(proj["at"], "text_encoders/qwen/" + PROJ_NAME)
        self.assertTrue(proj["exact"])
        self.assertEqual(found["moves"], [])

    def test_a_projector_beside_a_catalog_folder_model_is_have(self):
        # The pre-beside happy path must not regress: both in LLM/GGUF.
        tmp, cdir = comfy_with(MODEL_CAT, PROJ_CAT)
        self.addCleanup(tmp.cleanup)
        found, files = brain_files(cdir)
        self.assertEqual(files[0]["state"], "have")
        self.assertEqual(files[1]["state"], "have")
        self.assertTrue(files[1]["exact"])
        self.assertEqual(found["moves"], [])

    def test_the_projector_is_not_have_just_for_existing_somewhere(self):
        # The old rule: any_path matched anywhere counted as installed.
        tmp, cdir = comfy_with(MODEL, "LLM/GGUF/mmproj-F16.gguf")
        self.addCleanup(tmp.cleanup)
        _, files = brain_files(cdir)
        self.assertEqual(files[1]["state"], "stray")


class BesidePlanTests(_Base):
    """The defect itself: a missing projector must be fetched to the model's
    folder, not to the catalog's fixed LLM/GGUF."""

    def _choices(self, cdir, tidy=False):
        return {"lanes": ["brain"], "tidy": tidy,
                "comfy": {"mode": "use", "path": str(cdir)},
                "home": str(Path(self.tmp.name) / "home")}

    def test_the_plan_downloads_the_projector_beside_the_model(self):
        tmp, cdir = comfy_with(MODEL)
        self.addCleanup(tmp.cleanup)
        lanes, _, have, found = pi.build_plan(self._choices(cdir))
        steps = {s["id"] for s in pi.STATE["steps"]}
        self.assertIn("dl:text_encoders/Qwen/" + PROJ_NAME, steps)
        self.assertNotIn("dl:" + PROJ_CAT, steps)
        self.assertIn(MODEL_CAT, have)               # the gguf is not re-fetched

        def fake_download(url, dest, *a, **k):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"x")

        with mock.patch.object(pi, "download", fake_download):
            planned, failed = pi.fetch_weights(
                lanes, have, cdir / "models", found)
        self.assertEqual(failed, [])
        self.assertTrue((cdir / "models" / "text_encoders" / "Qwen"
                         / PROJ_NAME).is_file())
        self.assertFalse((cdir / "models" / "LLM" / "GGUF" / PROJ_NAME).exists())

    def test_a_fresh_install_still_downloads_to_llm_gguf(self):
        # No survey (a fresh ComfyUI) -> catalog dests, i.e. LLM/GGUF.
        lanes = [l for l in pi.CATALOG["lanes"] if l["id"] == "brain"]
        dests = [d for _, d in pi.pending_files(lanes, set(), None)]
        self.assertEqual(dests, [MODEL_CAT, PROJ_CAT])


class _WorkerBase(_Base):
    """A full worker run over a temp ComfyUI with every side effect stubbed
    except the model files themselves and the tidy."""

    def _run(self, cdir, tidy, download):
        home = Path(self.tmp.name) / "pixal"
        home.mkdir()
        choices = {"lanes": ["brain"], "tidy": tidy,
                   "comfy": {"mode": "use", "path": str(cdir.parent)},
                   "home": str(home)}
        with mock.patch.object(pi, "disk_preflight", lambda *a, **k: None), \
             mock.patch.object(pi, "install_pack", lambda *a, **k: None), \
             mock.patch.object(pi, "install_pixal_to",
                               lambda *a, **k: (home, False)), \
             mock.patch.object(pi, "choose_python",
                               lambda *a, **k: (Path("py"), "venv")), \
             mock.patch.object(pi, "ensure_pip", lambda *a, **k: None), \
             mock.patch.object(pi, "pip", lambda *a, **k: None), \
             mock.patch.object(pi, "run_out", lambda *a, **k: (1, "")), \
             mock.patch.object(pi, "llama_wheel_url",
                               lambda *a, **k: (None, "")), \
             mock.patch.object(pi, "desktop_shortcut", lambda *a, **k: None), \
             mock.patch.object(pi, "download", download):
            pi.worker(choices)


class BesideWorkerTests(_WorkerBase):

    def test_the_tidy_lands_the_projector_beside_the_model(self):
        # Jesse's layout, tidy on: the move runs, the run says done, and the
        # projector physically sits in the model's folder afterwards.
        tmp, cdir = comfy_with(MODEL, PROJ_CAT)
        self.addCleanup(tmp.cleanup)

        def fake_download(*a, **k):
            raise AssertionError("nothing should download - it is all here")

        self._run(cdir, tidy=True, download=fake_download)
        self.assertEqual(pi.STATE["phase"], "done", pi.STATE["error"])
        landed = cdir / "models" / "text_encoders" / "Qwen" / PROJ_NAME
        self.assertTrue(landed.is_file())
        self.assertFalse((cdir / "models" / "LLM" / "GGUF" / PROJ_NAME).exists())
        tidy_step = next(s for s in pi.STATE["steps"] if s["id"] == "tidy")
        self.assertEqual(tidy_step["status"], "ok")

    def test_the_run_fails_loudly_when_no_projector_is_beside_the_model(self):
        # Everything else green - model on disk, runtime step done, config
        # written - but the projector never landed beside the gguf. That is
        # the blind-brain defect, and the run must not call itself "done".
        tmp, cdir = comfy_with(MODEL)
        self.addCleanup(tmp.cleanup)

        def silent_no_land(url, dest, *a, **k):
            pass                               # claims success, writes nothing

        self._run(cdir, tidy=False, download=silent_no_land)
        self.assertEqual(pi.STATE["phase"], "error")
        self.assertIn("projector not beside the model", pi.STATE["error"])
        self.assertIn("*mmproj*.gguf", pi.STATE["error"])
        self.assertIn("done_note", pi.STATE)
        self.assertIn("projector not beside the model", pi.STATE["done_note"])


if __name__ == "__main__":
    unittest.main()
