"""Public release-tag ordering; independent of the updater and its network IO."""
import re


def parse_version(text):
    """"1.0.4b" / "v1.0.4b" -> ((1, 0, 4), "b"); None on anything else."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)([a-zA-Z]*)", str(text).strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split(".")), m.group(2).lower()


def compare_versions(a, b):
    """-1/0/1 for a older/equal/newer than b. Numeric parts compare as numbers
    (1.0.10b > 1.0.9b, never string order), then the pre-release letter
    (1.0.4b > 1.0.4a), and the bare release outranks every letter
    (1.0.4 > 1.0.4b)."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        raise ValueError(f"unparseable version: {a!r} vs {b!r}")
    (na, sa), (nb, sb) = pa, pb
    width = max(len(na), len(nb))
    na += (0,) * (width - len(na))
    nb += (0,) * (width - len(nb))
    if na != nb:
        return -1 if na < nb else 1
    if sa == sb:
        return 0
    if not sa:
        return 1
    if not sb:
        return -1
    return -1 if sa < sb else 1
