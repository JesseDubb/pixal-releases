"""Brief 9.24a — the update check: Pixal may KNOW a newer build exists and say
so in About, but it must never nag. Offline, GitHub down, rate-limited or fed
garbage, the answer collapses to a quiet "unknown" - the running version shows
and nothing else. The download itself is 9.24b; this half only knows and shows.
"""

import asyncio
import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import server

ROOT = Path(__file__).resolve().parent.parent
MENU_SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")

# The exact sentence the About panel owes the user, visible and not in a tip.
# Verified true against install/pixal.iss before it was written: recipes/,
# characters/ and chats/ ship only .gitkeep; config.json and history.jsonl are
# gitignored and SECRETS-excluded from the installer stage; [UninstallDelete]
# runs on uninstall only; an in-place upgrade touches none of them.
REASSURANCE = ("Updating replaces only Pixal's own modules — your recipes, "
               "characters, styles, settings and history stay untouched.")


def _clear_cache():
    server._update_check_cache["at"] = 0.0
    server._update_check_cache["result"] = None


class _Resp:
    """Smallest stand-in for the object urllib.request.urlopen returns."""

    def __init__(self, payload, status=200):
        self.status = status
        self._body = payload if isinstance(payload, bytes) \
            else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release(tag, sha="a" * 64, url=None):
    """The GitHub Releases API shape release.py actually publishes, notes and
    all - the sha256 line is lifted from step 13's own wording."""
    return {
        "tag_name": tag,
        "html_url": url or f"https://github.com/JesseDubb/pixal-releases/releases/tag/{tag}",
        "body": (f"Pixal {tag}.\n\n---\n\nGrab the installer below.\n\n"
                 f"If you want to check it: sha256 `{sha}`\n"),
    }


class VersionComparison(unittest.TestCase):
    # (a, b, sign of compare(a, b)) — 1 newer, 0 equal, -1 older.
    CASES = [
        ("1.0.5b", "1.0.4b", 1),    # plain newer
        ("1.0.4b", "1.0.5b", -1),   # plain older
        ("1.0.4b", "1.0.4b", 0),    # equal is not an update
        ("1.0.4b", "1.0.4a", 1),    # a newer pre-release suffix is newer
        ("1.0.4a", "1.0.4b", -1),   # an older suffix is older
        ("1.0.4a", "1.0.4a", 0),    # equal suffix
        ("1.0.10b", "1.0.9b", 1),   # numeric compare, not string compare
        ("1.1.0a", "1.0.9z", 1),    # the minor outranks any suffix
        ("2.0.0a", "1.9.9z", 1),    # the major outranks everything
        ("1.0.4", "1.0.4b", 1),     # the bare release outranks its pre-releases
        ("1.0.4b", "1.0.4", -1),
        ("v1.0.4b", "1.0.4b", 0),   # the tag's leading v is not the number
    ]

    def test_comparison_table(self):
        for a, b, want in self.CASES:
            with self.subTest(a=a, b=b):
                self.assertEqual(server.compare_versions(a, b), want)


class SilentFailures(unittest.TestCase):
    """Every failure shape yields the same quiet unknown - never an exception,
    never anything the UI could render as an error."""

    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def _check(self, **urlopen_kwargs):
        with mock.patch.object(server.urllib.request, "urlopen", **urlopen_kwargs):
            return server.update_check(now=1000.0)

    def _assert_unknown(self, result):
        self.assertFalse(result["ok"])
        self.assertIsNone(result["latest"])
        self.assertFalse(result["update"])
        self.assertIsNone(result["url"])
        self.assertIsNone(result["sha256"])
        self.assertEqual(result["running"], server.PIXAL_VERSION)

    def test_network_failure_is_unknown(self):
        self._assert_unknown(self._check(side_effect=urllib.error.URLError("offline")))

    def test_timeout_is_unknown(self):
        self._assert_unknown(self._check(side_effect=TimeoutError("timed out")))

    def test_rate_limited_403_is_unknown(self):
        err = urllib.error.HTTPError(server.RELEASES_API, 403, "rate limited", {}, None)
        self._assert_unknown(self._check(side_effect=err))

    def test_malformed_json_is_unknown(self):
        self._assert_unknown(self._check(return_value=_Resp(b"{not json")))


class CheckCache(unittest.TestCase):
    """A settings open must never hammer GitHub: inside the window there is
    no second network call - not after a hit, and not after a failure either
    (a nagging retry storm is the failure this brief forbids)."""

    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_second_call_inside_window_does_no_network(self):
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Resp(_release("v9.9.9z"))) as fetch:
            first = server.update_check(now=1000.0)
            second = server.update_check(now=1000.0 + 60)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first, second)
        self.assertTrue(second["ok"])

    def test_failure_is_cached_too(self):
        with mock.patch.object(server.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("offline")) as fetch:
            server.update_check(now=1000.0)
            server.update_check(now=1000.0 + 60)
        self.assertEqual(fetch.call_count, 1)

    def test_cache_expires_after_the_window(self):
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Resp(_release("v9.9.9z"))) as fetch:
            server.update_check(now=1000.0)
            server.update_check(now=1000.0 + server.UPDATE_CHECK_TTL + 1)
        self.assertEqual(fetch.call_count, 2)


class SuccessfulCheck(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_newer_release_reports_update_with_url_and_sha(self):
        sha = "b" * 64
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Resp(_release("v9.9.9z", sha=sha))):
            result = server.update_check(now=1000.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["running"], server.PIXAL_VERSION)
        self.assertEqual(result["latest"], "9.9.9z")   # the v is the tag's, not the version's
        self.assertTrue(result["update"])
        self.assertEqual(result["url"],
                         "https://github.com/JesseDubb/pixal-releases/releases/tag/v9.9.9z")
        self.assertEqual(result["sha256"], sha)        # parsed now so 9.24b's wire never changes


class Endpoint(unittest.TestCase):
    """The wire itself: an equal or older release is never an update."""

    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def _call(self, tag):
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_Resp(_release(tag))):
            resp = asyncio.run(server.update_check_get(None))
        return json.loads(resp.text)

    def test_older_release_is_not_an_update(self):
        body = self._call("v0.0.1a")
        self.assertTrue(body["ok"])
        self.assertFalse(body["update"])

    def test_equal_release_is_not_an_update(self):
        body = self._call("v" + server.PIXAL_VERSION)
        self.assertTrue(body["ok"])
        self.assertFalse(body["update"])

    def test_newer_release_is_an_update(self):
        body = self._call("v9.9.9z")
        self.assertTrue(body["ok"])
        self.assertTrue(body["update"])


class AboutPanel(unittest.TestCase):
    def test_reassurance_sentence_is_visible_not_a_tip(self):
        about = MENU_SRC[MENU_SRC.index('{tab === "about"'):]
        self.assertIn(REASSURANCE, about)
        # ...and it is genuinely visible: stripping every InfoTip must not
        # strip the sentence. (About currently carries no InfoTip; the regex
        # guards the day someone adds one and moves the line into it.)
        without_tips = re.sub(r"<InfoTip\b[^>]*/>", "", about)
        self.assertIn(REASSURANCE, without_tips)


if __name__ == "__main__":
    unittest.main()
