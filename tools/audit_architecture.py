"""Read-only dependency inventory. Never imports or starts the application.

This is a conservative syntactic map, not a whole-program call graph: attribute
mutation, dynamic dispatch and nested scopes need human review. Output contains
source names/locations only, never configuration values or runtime user data.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def route_contract(source: str) -> list[dict[str, str]]:
    """Ordered HTTP registrations, including static prefixes but not handlers."""
    routes = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Attribute) or node.func.value.attr != "router":
            continue
        method = node.func.attr.removeprefix("add_")
        if method not in ("get", "post", "delete", "put", "patch", "static"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            routes.append((node.lineno, {"method": method.upper(), "path": node.args[0].value}))
    return [route for _, route in sorted(routes, key=lambda row: row[0])]


def inventory(source: str) -> dict:
    tree = ast.parse(source)
    globals_ = set()
    functions = []
    initializers = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            globals_.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            globals_.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)}
            globals_.update(names)
            if node.value is not None and any(isinstance(n, ast.Call) for n in ast.walk(node.value)):
                initializers.append({"line": node.lineno, "names": sorted(names)})
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        reads = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        writes = {name for n in ast.walk(node) if isinstance(n, ast.Global) for name in n.names}
        calls = {ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)}
        functions.append({"name": node.name, "line": node.lineno,
                          "lines": node.end_lineno - node.lineno + 1,
                          "module_name_references": sorted(reads & globals_),
                          "declared_globals": sorted(writes), "calls": sorted(calls)})
    return {"lines": len(source.splitlines()), "module_names": len(globals_),
            "definitions": functions, "call_initializers": initializers,
            "routes": route_contract(source)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / "server.py")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    report = inventory(args.path.read_text(encoding="utf-8"))
    if args.summary:
        report = {"lines": report["lines"], "module_names": report["module_names"],
                  "definitions": len(report["definitions"]), "routes": len(report["routes"]),
                  "call_initializers": len(report["call_initializers"]),
                  "largest": [{k: d[k] for k in ("name", "line", "lines")}
                              for d in sorted(report["definitions"], key=lambda d: -d["lines"])[:12]]}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
