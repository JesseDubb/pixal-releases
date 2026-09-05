"""Read finisher values from a supplied configuration snapshot, without IO."""
import math
from collections.abc import Sequence


def finite_still_value(cfg: dict, key: str, *, default: float,
                       minimum: float, maximum: float) -> float:
    try:
        value = float(cfg["still"][key])
    except (KeyError, TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


def dlss5_style(cfg: dict, choices: Sequence[str]) -> str:
    try:
        style = str(cfg["still"]["dlss5_style"])
    except (KeyError, TypeError):
        return "default"
    return style if style in choices else "default"
