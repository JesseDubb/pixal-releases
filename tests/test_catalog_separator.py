"""_catalog_resolve must return the name ComfyUI actually LISTS.

The catalog stores `str(p.relative_to(base))`, which carries os.sep: a model in
a subfolder is `ZiT\\z_image...` on Windows and `ZiT/z_image...` on Linux. The
resolver compares separator-insensitively - recipes and saved styles are written
with backslashes and must match on either platform - but it used to return its
own normalised copy rather than the catalog's string.

On Windows the two coincide, so nothing showed. On Linux the returned name was
a backslash path ComfyUI does not list, and the loader rejected it at queue time
with "not in list" - the exact failure 724879c fixed for Z-Image's VAE, moved to
the other platform by that fix. It reaches every model in a subfolder, which is
all four shipped starter styles (ZiT\\ and Anima\\).
"""
import unittest
from unittest.mock import patch

import server


def catalog(kind, *rels):
    """Stub the scan with rels exactly as the platform would report them."""
    data = [{"kind": kind, "root": "/opt/comfy", "rel": r, "mtime": 0}
            for r in rels]
    return patch.dict(server._CATALOG, {"at": 9e18, "data": data})


class CatalogSeparator(unittest.TestCase):

    def test_linux_rel_survives_a_backslash_query(self):
        """A style written on Windows must resolve on Linux, AS LISTED."""
        listed = "ZiT/z_image_turbo_bf16.safetensors"
        with catalog("diffusion_models", listed):
            got = server._catalog_resolve(
                "diffusion_models", "ZiT\\z_image_turbo_bf16.safetensors")
        self.assertEqual(got, listed)

    def test_windows_rel_survives_a_forward_slash_query(self):
        """And the mirror: a forward-slash query on a Windows catalog."""
        listed = "ZiT\\z_image_turbo_bf16.safetensors"
        with catalog("diffusion_models", listed):
            got = server._catalog_resolve(
                "diffusion_models", "ZiT/z_image_turbo_bf16.safetensors")
        self.assertEqual(got, listed)

    def test_every_starter_style_model_resolves_as_listed(self):
        """The four shipped styles name two checkpoints, both in subfolders."""
        for sep in ("/", "\\"):
            listed = [f"ZiT{sep}z_image_turbo_bf16.safetensors",
                      f"Anima{sep}anima-base-v1.0.safetensors"]
            with self.subTest(sep=sep), catalog("diffusion_models", *listed):
                for want in ("ZiT\\z_image_turbo_bf16.safetensors",
                             "Anima\\anima-base-v1.0.safetensors"):
                    got = server._catalog_resolve("diffusion_models", want)
                    self.assertIn(got, listed)

    def test_unique_basename_returns_the_listed_path_not_the_basename(self):
        """724879c's own case: matching by basename must still hand back the
        real rel, or the loader is given a name it does not offer."""
        listed = "Flux/ae.safetensors"
        with catalog("vae", listed):
            got = server._catalog_resolve("vae", "ae.safetensors")
        self.assertEqual(got, listed)

    def test_an_ambiguous_basename_stays_unmatched(self):
        """The uniqueness guard is what keeps a half-match from poisoning the
        graph; normalising must not have widened it."""
        with catalog("vae", "Flux/ae.safetensors", "Other/ae.safetensors"):
            self.assertIsNone(server._catalog_resolve("vae", "ae.safetensors"))

    def test_exact_path_beats_a_basename_elsewhere(self):
        with catalog("vae", "Flux/ae.safetensors", "ZImage/ZiB_ae.safetensors"):
            self.assertEqual(
                server._catalog_resolve("vae", "ZImage\\ZiB_ae.safetensors"),
                "ZImage/ZiB_ae.safetensors")

    def test_case_insensitive_match_returns_the_catalog_casing(self):
        """The catalog has both text_encoders/Anima/ and /anima/ in the wild."""
        listed = "Anima/qwen_3_06b_base.safetensors"
        with catalog("text_encoders", listed):
            got = server._catalog_resolve(
                "text_encoders", "anima\\QWEN_3_06B_BASE.safetensors")
        self.assertEqual(got, listed)

    def test_a_miss_is_still_none(self):
        with catalog("diffusion_models", "ZiT/z_image_turbo_bf16.safetensors"):
            self.assertIsNone(
                server._catalog_resolve("diffusion_models", "nope.safetensors"))
            self.assertFalse(
                server._catalog_has("diffusion_models", "nope.safetensors"))


if __name__ == "__main__":
    unittest.main()
