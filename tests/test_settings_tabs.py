"""Brief 9.17a — Settings splits by medium (structure only).

Asserts the information architecture of web/src/components/SettingsMenu.jsx
without a JS runtime: the five-tab set, which setting keys each tab's block
reaches (no control dropped in the move), the unknown-saved-tab fallback to
"general", the frozen /api/settings write surface (the wire must not change
in this brief), the navigation-vs-setting control split in the brain panel,
the whole-row bound on the brain model list, and that HELP.md section 6
describes the same tabs the UI now ships.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")
HELP = (ROOT / "HELP.md").read_text(encoding="utf-8")

EXPECTED_TABS = [("general", "General"), ("image", "Image"), ("video", "Video"),
                 ("brain", "Brain"), ("about", "About")]


def _tab_blocks(src):
    """Map tab id -> JSX of every `{tab === "<id>" &&` block, so a control's
    reachability can be asserted per tab. Component-top code (state, helpers)
    precedes the first mark and belongs to no block."""
    marks = list(re.finditer(r'\{tab === "(\w+)" &&', src))
    blocks = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(src)
        blocks[m.group(1)] = blocks.get(m.group(1), "") + src[m.start():end]
    return blocks


BLOCKS = _tab_blocks(SRC)

# Every pre-split control, by the config key its auto-save posts (or the
# route/store it calls), under the tab the split moved it to. A key missing
# from its block means the move dropped it; the set equality in
# test_settings_wire_is_frozen means nothing new was added either.
TAB_KEYS = {
    "general": ["setTheme", "comfy_url", "comfy_editor", "comfy_console",
                "vram_profile", "explicit", "extra_model_roots",
                "/api/comfy/free", "/api/comfy/restart", "/api/llm/free",
                "/api/settings/rescan"],
    "image": ["zimage", "edit: { model", "image_mode", "image_model",
              "identity_finish"],
    "video": ["default_engine", "default_model", "video_mode"],
    "brain": ["base_url", "local_model", "local_keep", "local_gpu_layers",
              "api_key", "critic: { model", "onClick={test}"],
    "about": [],
}


def test_tabs_are_the_five_media_rooms():
    m = re.search(r"const TABS = \[(.*?)\];", SRC, re.S)
    ids = re.findall(r'\{ id: "(\w+)", label: "(\w+)" \}', m.group(1))
    assert ids == EXPECTED_TABS


def test_no_models_tab_remains():
    assert '{tab === "models"' not in SRC
    assert set(BLOCKS) == {t for t, _ in EXPECTED_TABS}


def test_every_setting_reachable_after_the_move():
    for tab, keys in TAB_KEYS.items():
        assert tab in BLOCKS, f"tab block missing: {tab}"
        for key in keys:
            assert key in BLOCKS[tab], f"{key} not reachable under {tab}"


def test_no_setting_duplicated_across_tabs():
    # a move, not a copy: each control lives under exactly one tab
    for tab, keys in TAB_KEYS.items():
        for key in keys:
            homes = [t for t, body in BLOCKS.items() if key in body]
            assert homes == [tab], f"{key} found in {homes}, expected only {tab}"


def test_unknown_saved_tab_falls_back_to_general():
    # the restore guard: a saved id that is not a current tab cannot restore,
    # so a stale "models" (or any retired id) lands on "general"
    assert 'TABS.some((t) => t.id === saved) ? saved : "general"' in SRC
    m = re.search(r"const TABS = \[(.*?)\];", SRC, re.S)
    ids = {i for i, _ in re.findall(r'\{ id: "(\w+)", label: "(\w+)" \}', m.group(1))}
    assert "general" in ids
    assert "models" not in ids


def test_settings_wire_is_frozen():
    # top-level keys of every apply({...}) payload = the /api/settings write
    # surface; this brief forbids changing it
    found = set(re.findall(r"\bapply\(\{\s*(\w+)", SRC))
    assert found == {
        "comfy_url", "comfy_editor", "comfy_console", "explicit",
        "vram_profile", "video", "critic", "vae", "edit", "upscale",
        "pid", "llm", "extra_model_roots",
    }


def test_mode_switch_is_navigation_not_pills():
    # the pill shape is retired: selection is SegRadio/TabStrip, action is Btn
    assert "<Pill" not in SRC
    brain = BLOCKS["brain"]
    assert "<TabStrip" in brain
    assert '{ id: "api", label: "API" }' in brain
    assert '{ id: "local", label: "Local" }' in brain


def test_at_most_two_segradio_rows_per_section():
    for tab, body in BLOCKS.items():
        for chunk in body.split("<Section "):
            n = chunk.count("<SegRadio")
            assert n <= 2, f"{tab} has a section stacking {n} SegRadio rows"


def test_brain_model_list_clips_on_whole_rows():
    # rows are 36px with 6px gaps; a fractional maxHeight sliced a row
    # mid-height at the top edge and read as a rendering fault, not a scroll
    m = re.search(r'maxHeight: (\d+), overflowY: "auto"', BLOCKS["brain"])
    assert m, "brain model list has no bounded scroll height"
    assert (int(m.group(1)) + 6) % 42 == 0


def test_help_settings_section_matches_the_new_tabs():
    s6 = HELP.split("## 6. Settings reference")[1].split("## 7.")[0]
    for heading in ["### General", "### Image", "### Video", "### Brain", "### About"]:
        assert heading in s6, f"HELP.md §6 missing {heading}"
    flat = re.sub(r"\s+", " ", HELP)
    assert "Settings → Models" not in flat
    assert "### Models" not in HELP
