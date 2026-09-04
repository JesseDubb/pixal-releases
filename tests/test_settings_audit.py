"""Unit-test the geometry judge without launching a browser or contacting Pixal."""

from copy import deepcopy

from tools.audit_rows import judge


def sample():
    return {"tab": "General", "frame": 876, "rows": [{"label": "Address", "h": 50}],
            "rails": [{"label": "Address", "tag": "INPUT", "role": "", "h": 34,
                       "w": 260, "above": 0, "below": 0}],
            "gaps": [{"kind": "group", "value": 28}, {"kind": "card", "value": 12},
                     {"kind": "heading", "value": 12}, {"kind": "row", "value": 0}],
            "overflow": []}


def test_wrapped_rows_and_role_sized_inputs_are_accepted():
    tab = sample()
    assert judge([tab])[0] == []
    tab["rows"][0]["h"] = 76
    assert judge([tab])[0] == []


def test_short_rows_and_off_ladder_controls_fail():
    tab = sample()
    tab["rows"][0]["h"] = 32
    tab["rails"][0]["h"] = 40
    assert len(judge([tab])[0]) == 2


def test_overlap_and_wrong_spacing_fail():
    tab = sample()
    tab["overflow"].append("Address: label overlaps control")
    tab["gaps"][0]["value"] = 8
    tab["rails"][0]["below"] = 6
    assert len(judge([tab])[0]) == 3


def test_tabs_must_not_resize_the_frame():
    first = sample()
    second = deepcopy(first)
    second["tab"], second["frame"] = "Video", 800
    assert "changes height" in judge([first, second])[0][0]


def test_the_pixal_switch_is_a_deliberate_rail_exception():
    tab = sample()
    tab["rails"][0].update(tag="BUTTON", role="switch", h=16, w=42)
    assert judge([tab])[0] == []
