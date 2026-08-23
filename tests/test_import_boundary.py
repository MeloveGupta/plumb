"""TRD §3.1 — the engine may not import plumb_gen or plumb_eval.

Static AST check only. It cannot see a dynamically constructed import
(importlib.import_module("plumb_gen"), __import__(...), anything built
from a string at runtime) — that gap is accepted, not hidden.
"""

import ast
from pathlib import Path

from _pyfiles import python_files

FORBIDDEN = ("plumb_gen", "plumb_eval")
PLUMB_ROOT = Path(__file__).parent.parent / "src" / "plumb"


def _root_module(dotted_name: str) -> str:
    return dotted_name.split(".")[0]


def _forbidden_imports(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root_module(alias.name) in FORBIDDEN:
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import (from . import x, from .. import y).
            # It cannot resolve outside src/plumb/'s own package tree, so it
            # cannot reach plumb_gen or plumb_eval — skip rather than false-flag.
            if node.level == 0 and node.module and _root_module(node.module) in FORBIDDEN:
                hits.append(node.module)
    return hits


def test_engine_does_not_import_ground_truth_packages():
    violations: list[str] = []
    for path in python_files(PLUMB_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        for hit in _forbidden_imports(tree):
            violations.append(f"{path}: imports {hit}")
    assert not violations, "\n".join(violations)
