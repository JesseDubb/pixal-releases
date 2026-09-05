"""Pure saved-style validation and slot expansion; no catalogs or file access."""
import math
import re

TUNING_KEYS = ("steps", "cfg", "sampler_name", "scheduler", "eta", "shift")
_SLOT_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


def validate_style_tuning(tuning):
    """Shape-check a tuning block: keys, types, ranges. No catalog access.

    Deliberately does NOT check the seat or the enum values - that needs the
    model catalog, which is not warm at boot, and a load-time check against it
    would reject perfectly good styles on the way up. Those checks live in
    check_style_runnable(), which runs when the user SAVES and is present.
    """
    if tuning in (None, {}):
        return {}
    if not isinstance(tuning, dict):
        raise ValueError("tuning must be an object")
    unknown = [k for k in tuning if k not in TUNING_KEYS]
    if unknown:
        raise ValueError(f"unknown tuning setting: {', '.join(sorted(unknown))}")
    out = {}
    if "steps" in tuning:
        try:
            steps = int(tuning["steps"])
        except (TypeError, ValueError):
            raise ValueError(f"steps must be a whole number, got {tuning['steps']!r}") from None
        if not 1 <= steps <= 200:
            raise ValueError(f"steps must be between 1 and 200, got {steps}")
        out["steps"] = steps
    if "cfg" in tuning:
        try:
            cfg = float(tuning["cfg"])
        except (TypeError, ValueError):
            raise ValueError(f"cfg must be a number, got {tuning['cfg']!r}") from None
        if not math.isfinite(cfg) or not 0.0 <= cfg <= 30.0:
            raise ValueError(f"cfg must be between 0 and 30, got {cfg:g}")
        out["cfg"] = cfg
    if "shift" in tuning:
        # ModelSamplingAuraFlow declares shift as a float in [0, 100] (default
        # 1.73). Anything useful on Z-Image lives in 0.5-8; the node's range is
        # kept rather than narrowed, because which seats even HAVE a shift is
        # check_style_runnable's job and this stays catalog-free.
        try:
            shift = float(tuning["shift"])
        except (TypeError, ValueError):
            raise ValueError(
                f"shift must be a number, got {tuning['shift']!r}") from None
        if not math.isfinite(shift) or not 0.0 <= shift <= 100.0:
            raise ValueError(f"shift must be between 0 and 100, got {shift:g}")
        out["shift"] = shift
    if "eta" in tuning:
        # Bounds are the node's own declared range, not a guess: RES4LYF
        # declares eta as a float in [-100, 100] (default 0.5). Which seats
        # even HAVE it is check_style_runnable's job - this stays catalog-free.
        try:
            eta = float(tuning["eta"])
        except (TypeError, ValueError):
            raise ValueError(f"eta must be a number, got {tuning['eta']!r}") from None
        if not math.isfinite(eta) or not -100.0 <= eta <= 100.0:
            raise ValueError(f"eta must be between -100 and 100, got {eta:g}")
        out["eta"] = eta
    for key in ("sampler_name", "scheduler"):
        if key not in tuning:
            continue
        value = str(tuning[key] or "").strip()
        if not value:
            raise ValueError(f"{key} cannot be empty")
        if len(value) > 64:
            raise ValueError(f"{key} is longer than 64 characters")
        out[key] = value
    return out


def style_slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:64]


def _style_prompt_text(value, field):
    """An optional free-text clause on a style (negative, prompt_prefix,
    prompt_tail).

    Whitespace-collapsed and capped: these ride inside shared files and end up
    as single clauses in a caption, so a paste with newlines must not explode
    into one. Empty means absent - the key simply leaves the record.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = " ".join(value.split())
    if len(text) > 600:
        raise ValueError(f"{field} is longer than 600 characters")
    return text or None


def _style_slots(raw, *clauses):
    """A style's slot declarations -> {name: {"label", "default"}}.

    The formula is the product; the slots are the per-shoot input (9.77).
    Declared explicitly as a map, or inferred from the {name} tokens in the
    prompt frame when the map is absent - an inferred slot's default is "",
    so an unfilled field collapses its clause rather than inventing words.
    """
    if raw is None:
        names = []
        for clause in clauses:
            for token in _SLOT_TOKEN_RE.findall(clause or ""):
                name = " ".join(token.split())
                if name and name not in names:
                    names.append(name)
        return {name: {"label": "", "default": ""} for name in names}
    if not isinstance(raw, dict):
        raise ValueError("slots must be an object of name -> {label, default}")
    if len(raw) > 32:
        raise ValueError("a style can declare at most 32 slots")
    out = {}
    for key, spec in raw.items():
        name = " ".join(str(key).split())
        if not name or len(name) > 64 or "{" in name or "}" in name:
            raise ValueError(f"slot name {key!r} is not a usable {{token}}")
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise ValueError(f"slot {name!r} must be an object of label/default")
        label, default = spec.get("label"), spec.get("default")
        if label is not None and not isinstance(label, str):
            raise ValueError(f"slot {name!r}: label must be a string")
        if default is not None and not isinstance(default, str):
            raise ValueError(f"slot {name!r}: default must be a string")
        label = " ".join((label or "").split())
        default = " ".join((default or "").split())
        if len(label) > 64:
            raise ValueError(f"slot {name!r}: label is longer than 64 characters")
        if len(default) > 600:
            raise ValueError(f"slot {name!r}: default is longer than 600 characters")
        out[name] = {"label": label, "default": default}
    return out


def fill_style_slots(text, slots, fills):
    """Render a style clause's {slot} tokens (9.77).

    A fill from the composer wins; an unfilled slot renders as its declared
    default. When the effective value is empty the slot's whole clause - the
    ;-separated segment it sits in - collapses, so "wearing {outfit top}"
    with nothing to wear never leaves a dangling "wearing" in the caption,
    and an undeclared token never leaks literal braces either.
    """
    if not text or "{" not in text:
        return text
    slots = slots or {}
    fills = fills if isinstance(fills, dict) else {}
    out = []
    for clause in text.split(";"):
        drop = False

        def repl(match):
            nonlocal drop
            name = " ".join(match.group(1).split())
            value = fills.get(name)
            if not isinstance(value, str) or not value.strip():
                value = (slots.get(name) or {}).get("default") or ""
            value = " ".join(value.split())
            if not value:
                drop = True
            return value

        rendered = _SLOT_TOKEN_RE.sub(repl, clause)
        if drop:
            continue
        rendered = " ".join(rendered.split())
        if rendered:
            out.append(rendered)
    return "; ".join(out)
