"""TRD §3.1 — dynamic-import companion to test_import_boundary.py.

test_import_boundary.py only sees ast.Import/ast.ImportFrom nodes, so it
cannot see importlib.import_module("plumb_gen") or __import__("plumb_gen") —
those are just ast.Call nodes with a string argument. This test is scoped to
actual dynamic-import call sites, not a blanket grep, so it doesn't
false-positive on the package names appearing in prose (this docstring
included).

A module name built at runtime from a variable, f-string, or concatenation
is still invisible here — the argument has to be a literal string constant.
"""

import ast
from pathlib import Path

from _pyfiles import python_files

FORBIDDEN = ("plumb_gen", "plumb_eval")
PLUMB_ROOT = Path(__file__).parent.parent / "src" / "plumb"
DYNAMIC_IMPORT_NAMES = {"__import__", "import_module"}


def _root_module(dotted_name: str) -> str:
    return dotted_name.split(".")[0]


def _is_dynamic_import_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in DYNAMIC_IMPORT_NAMES
    if isinstance(func, ast.Attribute):
        return func.attr == "import_module"
    return False


def _dynamic_import_targets(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_dynamic_import_call(node.func):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if _root_module(first.value) in FORBIDDEN:
                hits.append(first.value)
    return hits


def test_engine_does_not_dynamically_import_ground_truth_packages():
    violations: list[str] = []
    for path in python_files(PLUMB_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        for hit in _dynamic_import_targets(tree):
            violations.append(f"{path}: dynamically imports {hit!r}")
    assert not violations, "\n".join(violations)
