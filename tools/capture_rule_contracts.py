"""Print synthetic pure-rule fixtures from the committed pre-extraction source.

No server import, user data, graph submission or network access. The revision is
fixed deliberately: regenerating a golden file from changed code proves nothing.
"""
import ast
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "5ab6aae"
FUNCTIONS = ("parse_version", "compare_versions", "dims_for", "validate_style_tuning",
             "style_slug", "_style_prompt_text", "_style_slots", "fill_style_slots")


def capture():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:server.py"],
                                     cwd=ROOT).decode("utf-8")
    namespace = {"re": re, "math": math, "CANVAS_MULTIPLE": 16, "CANVAS_RATIO_WEIGHT": 6.0,
                 "TUNING_KEYS": ("steps", "cfg", "sampler_name", "scheduler", "eta", "shift"),
                 "_SLOT_TOKEN_RE": re.compile(r"\{([^{}]+)\}")}
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<baseline pure rules>", "exec"), namespace)
    cases = []
    for aspect in ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"):
        for mp in (0, 0.1, 1, 2, 4, 8):
            for grid in (16, 32):
                cases.append(("dims_for", [aspect, mp, grid]))
    cases += [("parse_version", [value]) for value in ("1.3.1b", "v1.3.1b", " 1.3.1B ", "bad", "1..2")]
    cases += [("compare_versions", list(pair)) for pair in
              (("1.3.1b", "1.3.1"), ("1.3", "1.3.0"), ("1.9", "1.10"), ("bad", "1"))]
    cases += [("validate_style_tuning", [value]) for value in
              (None, {}, {"steps": 12, "cfg": 1.2, "shift": 1.73, "eta": 0},
               {"steps": "14", "sampler_name": " linear/euler ", "scheduler": "simple"},
               {"steps": 0}, {"cfg": 31}, {"eta": "bad"}, {"unknown": True}, {"scheduler": ""})]
    cases += [("style_slug", ["A synthetic / style"]),
              ("_style_prompt_text", [" a\nshort  clause ", "prefix"]),
              ("_style_prompt_text", [13, "prefix"]),
              ("_style_slots", [None, "a {subject}; {outfit top}; {subject}"]),
              ("_style_slots", [{"subject": {"label": " Person ", "default": " someone "}}]),
              ("_style_slots", [{"bad{key": {}}]),
              ("fill_style_slots", ["portrait; wearing {outfit}; {place}", {}, {}]),
              ("fill_style_slots", ["a {subject}", {"subject": {"default": "person"}}, {}]),
              ("fill_style_slots", ["a {subject}", {"subject": {"default": "person"}}, {"subject": "bird"}])]
    output = []
    for function, args in cases:
        case = {"function": function, "args": args}
        try:
            case["result"] = namespace[function](*args)
        except (ValueError, TypeError) as exc:
            case["error"] = {"type": type(exc).__name__, "message": str(exc)}
        output.append(case)
    return {"source_commit": BASELINE, "cases": output}


if __name__ == "__main__":
    print(json.dumps(capture(), indent=2))
