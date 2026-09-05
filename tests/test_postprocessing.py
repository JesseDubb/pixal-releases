"""Real-file failure cases for non-destructive post-processing delivery."""
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from pixal.postprocessing import artifact_paths, finish_image


@pytest.fixture
def source(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    path = output / "render.png"
    meta = PngInfo()
    meta.add_text("prompt", '{"seed": 42}')
    Image.new("RGB", (20, 30), "#b89574").save(path, pnginfo=meta)
    return output, path, {"filename": path.name, "subfolder": "", "type": "output", "media": "image"}


def tint(path, color="white"):
    with Image.open(path) as im:
        meta = PngInfo()
        for key, value in im.info.items():
            if isinstance(value, str):
                meta.add_text(key, value)
        size = im.size
    Image.new("RGB", size, color).save(path, pnginfo=meta)
    return True


def test_success_preserves_original_and_publishes_separate_valid_file(source):
    root, path, descriptor = source
    before = path.read_bytes()
    result = finish_image(root, descriptor, [("grain@1.6", tint)])
    assert path.read_bytes() == before
    assert result["original"] == descriptor
    assert result["filename"] != path.name
    assert result["finish"] == "grain@1.6"
    with Image.open(root / result["filename"]) as out:
        assert out.getpixel((0, 0)) == (255, 255, 255)
        assert out.info["prompt"] == '{"seed": 42}'
    assert set(root.iterdir()) == {path, root / result["filename"]}
    assert "original" not in descriptor  # no mutation of engine data


def test_no_passes_does_not_even_open_the_original(source):
    root, _, descriptor = source
    with patch("shutil.copy2", side_effect=AssertionError("no copies")):
        assert finish_image(root, descriptor, []) is descriptor
    assert len(list(root.iterdir())) == 1


@pytest.mark.parametrize("failure", ["false", "raise", "invalid", "size"])
def test_failed_stage_cannot_poison_next_stage_or_original(source, failure):
    root, path, descriptor = source
    before = path.read_bytes()

    def fail(candidate):
        if failure == "size":
            Image.new("RGB", (1, 1)).save(candidate)
            return True
        candidate.write_bytes(b"broken")
        if failure == "raise":
            raise RuntimeError("model failed")
        return failure == "invalid"

    def next_stage(candidate):
        with Image.open(candidate) as im:
            assert im.getpixel((0, 0)) == (255, 255, 255)
        return tint(candidate, "black")

    result = finish_image(root, descriptor,
                          [("dlss5@default", tint), ("deshine@.8", fail), ("grain@1.6", next_stage)])
    assert path.read_bytes() == before
    assert result["finish"] == "dlss5@default+grain@1.6"
    with Image.open(root / result["filename"]) as out:
        assert out.getpixel((0, 0)) == (0, 0, 0)
    assert len(list(root.iterdir())) == 2


def test_all_no_ops_keep_single_original_without_compare(source):
    root, path, descriptor = source
    before = path.read_bytes()
    result = finish_image(root, descriptor, [("deshine@.8", lambda p: False)])
    assert result["filename"] == path.name
    assert result["finish"] == ""
    assert "original" not in result
    assert path.read_bytes() == before
    assert list(root.iterdir()) == [path]


@pytest.mark.parametrize("operation", ["copy2", "replace"])
def test_disk_failure_falls_back_to_original(source, operation):
    root, path, descriptor = source
    before = path.read_bytes()
    target = "pixal.postprocessing." + ("shutil." if operation == "copy2" else "os.") + operation
    with patch(target, side_effect=OSError("disk full")):
        result = finish_image(root, descriptor, [("grain@1.6", tint)])
    assert "original" not in result
    assert path.read_bytes() == before
    assert list(root.iterdir()) == [path]


def test_final_publish_failure_does_not_claim_success(source):
    root, path, descriptor = source
    import os
    real = os.replace

    def replace(src, dest):
        if "__finished_" in str(dest):
            raise OSError("cannot publish")
        return real(src, dest)

    with patch("pixal.postprocessing.os.replace", side_effect=replace):
        result = finish_image(root, descriptor, [("grain@1.6", tint)])
    assert result["finish"] == ""
    assert list(root.iterdir()) == [path]


def test_video_and_already_finished_are_not_processed(source):
    root, _, descriptor = source
    for image in ({**descriptor, "media": "video"}, {**descriptor, "original": descriptor}):
        assert finish_image(root, image, [("bad", lambda p: pytest.fail("double apply"))]) is image


@pytest.mark.parametrize("change", [{"filename": "../render.png"}, {"subfolder": "../../"},
                                    {"filename": "missing.png"}])
def test_missing_and_escaping_paths_never_run(source, change):
    root, _, descriptor = source
    result = finish_image(root, {**descriptor, **change}, [("bad", lambda p: pytest.fail("unsafe path"))])
    assert "original" not in result


def test_nested_output_and_multiple_deliveries_have_distinct_pairs(source):
    root, path, descriptor = source
    folder = root / "pixal_dm"
    folder.mkdir()
    path.rename(folder / path.name)
    descriptor["subfolder"] = "pixal_dm"
    a = finish_image(root, descriptor, [("grain@1", tint)])
    b = finish_image(root, descriptor, [("grain@2", tint)])
    assert a["filename"] != b["filename"]
    assert a["original"] == b["original"] == descriptor
    assert (folder / a["filename"]).is_file()


def test_hub_provenance_reaches_events_and_history(source):
    # conftest isolates import-time Hub state from the live studio.
    import server
    root, path, descriptor = source
    hub = object.__new__(server.Hub)
    events = []
    hub.broadcast = lambda **event: events.append(event)
    job = {"id": "compare", "template": "realism", "seen": set(), "images": [], "info": {}, "seed": 42}
    with patch.object(server, "CDIR", root.parent), \
         patch.object(server, "load_config", return_value={"still": {"film_grain": True}}):
        hub.add_image(job, descriptor.copy())
        hub.add_image(job, descriptor.copy())  # replay must not create another file
    assert len(job["images"]) == 1
    image = job["images"][0]
    assert image["original"] == descriptor
    assert events[0]["original"] == descriptor
    assert events[0]["filename"] == image["filename"]
    assert events[0]["finish"] == image["finish"] == job["info"]["finish"]
    assert path.is_file()


def test_batch_no_op_does_not_inherit_other_images_finish(source):
    import server
    root, _, descriptor = source
    hub = object.__new__(server.Hub)
    hub.broadcast = lambda **event: None
    job = {"id": "batch", "template": "realism", "seen": set(), "images": [],
           "info": {"finish": "dlss5@default"}}
    with patch.object(server, "CDIR", root.parent), \
         patch.object(server, "load_config", return_value={"still": {"dlss5": True}}), \
         patch.object(server, "_dlss5_delivered", return_value=False):
        hub.add_image(job, descriptor.copy())
    assert job["images"][0]["finish"] == ""
    assert "original" not in job["images"][0]


@pytest.mark.parametrize("shared", [False, True])
def test_history_delete_handles_both_files_but_keeps_shared_original(source, shared):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import server
    root, path, descriptor = source
    image = finish_image(root, descriptor, [("grain@1", tint)])
    entry = {"id": "one", "images": [image]}
    others = [{"id": "two", "images": [descriptor]}] if shared else []
    hub = SimpleNamespace(ledger_delete=lambda _: entry, ledger_read=lambda: others, jobs={})
    with patch.object(server, "HUB", hub), patch.object(server, "CDIR", root.parent):
        response = asyncio.run(server.history_delete(SimpleNamespace(json=AsyncMock(return_value={"id": "one"}))))
    assert json.loads(response.text)["files_removed"] == (1 if shared else 2)
    assert not (root / image["filename"]).exists()
    assert path.exists() is shared


def test_artifact_paths_are_bounded_deduplicated_and_not_recursive(source):
    root, path, descriptor = source
    entry = {"images": [descriptor, {**descriptor, "original": descriptor},
                        {"filename": "../../outside.png"},
                        {"filename": "ok.png", "original": {"filename": "../outside.png"}},
                        {"filename": "other.png", "original": {"filename": "raw.png", "original": descriptor}}]}
    assert artifact_paths(root, entry) == {path, root / "ok.png", root / "other.png", root / "raw.png"}
