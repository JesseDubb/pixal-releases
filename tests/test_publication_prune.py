"""What leaves this machine, and what must not.

Pixal publishes itself three ways: the installer anyone can unzip, the source
zip attached to a GitHub release, and the browsable tree on pixal-releases. All
three are cut from `git archive HEAD`, so a tracked file is a published file
unless something prunes it.

There used to be two prune lists - one in `release.py` for the two public
source artifacts, one in `install/build_installer.py` for the installer - and
they drifted. release.py's grew `RELEASING.md`, `release.py` itself and the
agent-skill folders; the installer's never did. The result was that every 1.1.x
installer carried Pixal's own release runbook and the Netlify site id, while
the public source tree looked perfectly clean. Nothing appeared wrong, which is
why it survived seven releases (found 2026-09-02, cutting 1.2.0b).

So these tests hold two things: the two lists are ONE list, and the things that
have ever been sensitive stay out of the tree entirely.
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tracked():
    """Every path `git archive HEAD` would lay down."""
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT,
                         capture_output=True, text=True, check=True)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


class OnePruneListTests(unittest.TestCase):

    def setUp(self):
        if str(_ROOT / "install") not in sys.path:
            sys.path.insert(0, str(_ROOT / "install"))
        self.installer = _load("pixal_build_installer",
                               _ROOT / "install" / "build_installer.py")
        self.release = _load("pixal_release", _ROOT / "release.py")

    def test_the_installer_and_the_public_tree_prune_the_same_things(self):
        """Two lists is how the runbook shipped inside the exe."""
        self.assertEqual(list(self.installer.INTERNAL), list(self.release.INTERNAL))

    def test_release_py_does_not_keep_its_own_copy(self):
        """It must IMPORT the list. A literal here is the bug returning - and it
        would pass the equality test above for exactly as long as somebody kept
        both edited."""
        src = (_ROOT / "release.py").read_text(encoding="utf-8")
        self.assertIn("from build_installer import INTERNAL", src)
        self.assertNotIn('INTERNAL = ["briefs"', src)

    def test_the_list_lives_where_a_stranger_still_has_it(self):
        """build_installer.py ships inside the published source; release.py is
        pruned out of it. Reverse the import and a clone of the public repo can
        no longer build an installer."""
        self.assertIn("release.py", self.installer.INTERNAL)
        self.assertNotIn("install", self.installer.INTERNAL)
        self.assertNotIn("install/build_installer.py", self.installer.INTERNAL)

    def test_the_internal_notes_that_leaked_are_named(self):
        """The specific files found inside the 1.1.9b installer."""
        for name in ("RELEASING.md", "release.py", "MORNING.md", "DESIGN.md",
                     "PORTING.md", ".claude", ".agents", "skills-lock.json",
                     # Not a leak - superseded landing pages nothing serves -
                     # but they shipped in both publications advertising a
                     # 1.0.0b download link until 1.2.0b.
                     "site-archive"):
            with self.subTest(path=name):
                self.assertIn(name, self.installer.INTERNAL)

    def test_applying_the_list_leaves_no_internal_file_behind(self):
        """Membership is not protection: a typo'd entry sits on the list and
        prunes nothing, which reads exactly like it is working.

        So apply the list the way both publications do - against `git ls-files`,
        which is what `git archive HEAD` lays down - and check the survivors. It
        has to be the tracked set and not the working directory: half these
        entries (`briefs`, `docs`, `SOL_PLAN.md`, `scratch_prompt.txt`) are
        gitignored working notes that exist on one machine and in no checkout,
        so asserting they are present passes here and fails in CI, which is
        precisely how this test failed the first time it ran on a runner."""
        survivors = [f for f in tracked()
                     if not any(f == i or f.startswith(i + "/")
                                for i in self.installer.INTERNAL)]
        for name in ("RELEASING.md", "release.py", "MORNING.md", "DESIGN.md",
                     "PORTING.md", "PACKAGING.md", "skills-lock.json"):
            with self.subTest(path=name):
                self.assertNotIn(name, survivors)
        for prefix in (".claude/", ".agents/", "site/", "brand/",
                       "site-archive/", ".github/"):
            with self.subTest(prefix=prefix):
                self.assertEqual([f for f in survivors if f.startswith(prefix)], [])

    def test_a_pruned_path_is_either_tracked_or_a_local_working_note(self):
        """The inert entries are deliberate belt-and-braces, not typos - but a
        NEW one that matches nothing anywhere is worth catching, so the list
        names the ones that are allowed to match no tracked file."""
        inert = {"briefs", "docs", "SOL_PLAN.md", "PRODUCT_NOTES.md",
                 "pixal-dm-ssot.md", "scratch_prompt.txt"}
        files = tracked()
        for name in self.installer.INTERNAL:
            with self.subTest(path=name):
                matches = any(f == name or f.startswith(name + "/") for f in files)
                self.assertTrue(matches or name in inert,
                                f"{name} prunes nothing and is not a known "
                                f"working note - typo, or a stale entry?")


class NothingSensitiveIsTrackedTests(unittest.TestCase):
    """Pruning is the second line. The first is never committing it."""

    def setUp(self):
        self.files = tracked()

    def test_no_runtime_state_or_credentials_are_tracked(self):
        """config.json carries a live API key and the remote access key;
        history.jsonl is every render ever made on this box."""
        never = {"config.json", "history.jsonl", "_lora_titles.json",
                 "_civitai_models.json", "sampler_combos.json", "lane.json",
                 ".env", "input_ref_types.json"}
        hit = [f for f in self.files if Path(f).name in never]
        self.assertEqual(hit, [])

    def test_no_chat_logs_characters_or_saved_styles_are_tracked(self):
        """Those folders SHIP - empty. Their contents are the user's own."""
        for folder in ("chats", "characters", "recipes"):
            with self.subTest(folder=folder):
                self.assertEqual([f for f in self.files if f.startswith(f"{folder}/")],
                                 [f"{folder}/.gitkeep"])

    def test_no_log_files_are_tracked(self):
        self.assertEqual([f for f in self.files if f.endswith(".log")], [])

    def test_the_example_config_ships_empty_credentials(self):
        """It is the file a new install copies from."""
        import json
        cfg = json.loads((_ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["llm"]["api_key"], "")
        self.assertEqual(cfg["access_key"], "")


if __name__ == "__main__":
    unittest.main()
