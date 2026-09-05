"""Non-destructive delivery of still finishers, independent of the app runtime.

Finishers receive disposable copies, never the engine's original output. Only
validated successes become the next stage; publication is one atomic rename.
The original/finish pair lives on each image, not on a batch-wide job label.
"""
import logging
import os
import shutil
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


def artifact_paths(output_root: Path, entry: dict) -> set[Path]:
    """Resolve only this entry's delivered files and their direct originals.

    Used by explicit history deletion; never follows arbitrary nested metadata
    or returns a path outside the engine output root.
    """
    root = Path(output_root).resolve()
    paths = set()
    for image in entry.get("images") or []:
        if not isinstance(image, dict):
            continue
        for descriptor in (image, image.get("original")):
            if not isinstance(descriptor, dict) or not isinstance(descriptor.get("filename"), str):
                continue
            try:
                path = (root / (descriptor.get("subfolder") or "") / descriptor["filename"]).resolve()
                if path != root and path.is_relative_to(root):
                    paths.add(path)
            except (OSError, ValueError, TypeError, RuntimeError):
                continue
    return paths


def finish_image(output_root: Path, image: dict, passes) -> dict:
    """Return the delivered descriptor; failures always leave the original safe.

    ``passes`` contains (ledger_tag, callable(path) -> bool) pairs in pixel
    order. No work or extra file is created with no enabled passes. Intermediate
    files stay private to this call and are never exposed to history or SSE.
    """
    if not passes or image.get("media") == "video" or image.get("original"):
        return image
    delivered = {**image, "finish": ""}
    temporary = []
    try:
        root = Path(output_root).resolve()
        name = image["filename"]
        if Path(name).name != name:
            raise ValueError("invalid output filename")
        source = (root / (image.get("subfolder") or "") / name).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError("original is missing or outside the output directory")
        from PIL import Image

        with Image.open(source) as original:
            size, fmt = original.size, original.format
        token = uuid.uuid4().hex
        working = source.with_name(f".{source.stem}.{token}.working{source.suffix}")
        candidate = source.with_name(f".{source.stem}.{token}.stage{source.suffix}")
        temporary.extend((working, candidate))
        current, applied = source, []
        for tag, apply in passes:
            try:
                shutil.copy2(current, candidate)
                if not apply(candidate):
                    continue
                with Image.open(candidate) as result:
                    if result.size != size or result.format != fmt:
                        raise ValueError("finisher changed the canvas or image format")
                    result.load()  # Reject truncated/invalid pixels before publishing.
                os.replace(candidate, working)
                current = working
                applied.append(tag)
            except Exception as exc:
                # A bad stage cannot contaminate an earlier successful one.
                log.warning("Post processing %s skipped for %s: %s", tag, name, exc)
        if not applied:
            return delivered
        final = source.with_name(f"{source.stem}__finished_{token}{source.suffix}")
        os.replace(working, final)
        return {
            **delivered, "filename": final.name, "finish": "+".join(applied),
            "original": {"filename": name, "subfolder": image.get("subfolder") or "",
                         "type": "output", "media": "image"},
        }
    except Exception as exc:
        log.warning("Post processing skipped; keeping original %s: %s",
                    image.get("filename"), exc)
        return delivered
    finally:
        for path in temporary:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove post-processing temporary file %s", path.name)
