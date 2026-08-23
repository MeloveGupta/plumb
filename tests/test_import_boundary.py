"""TRD §3.1 — the full import-boundary table, not just the engine's side.

    plumb        -> may import: nothing from plumb_gen, plumb_eval
    plumb_gen    -> may import: plumb.domain only
    plumb_eval   -> may import: plumb.domain, plumb_gen

Only the first and second rows are checked here. plumb_eval stays
untested for now -- that package is still empty, and a test against an
empty target is exactly the vacuous-pass shape this project keeps running
into (P0.1's STRICT-schema stub, the layer-direction rule noted in P0.3).
It gets a real test the day plumb_eval has content to violate it with.

Static AST check only. It cannot see a dynamically constructed import
(importlib.import_module("plumb_gen"), __import__(...), anything built
from a string at runtime) — that gap is accepted, not hidden.
"""

import ast
from pathlib import Path

from _pyfiles import python_files

FORBIDDEN = ("plumb_gen", "plumb_eval")
PLUMB_ROOT = Path(__file__).parent.parent / "src" / "plumb"
PLUMB_GEN_ROOT = Path(__file__).parent.parent / "src" / "plumb_gen"
PLUMB_GEN_ALLOWED_PREFIXES = ("plumb.domain",)


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


def _is_allowed_plumb_import(dotted_name: str) -> bool:
    return any(dotted_name == p or dotted_name.startswith(p + ".") for p in PLUMB_GEN_ALLOWED_PREFIXES)


def _disallowed_plumb_imports(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name == "plumb" or alias.name.startswith("plumb.")) and not _is_allowed_plumb_import(
                    alias.name
                ):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and (node.module == "plumb" or node.module.startswith("plumb.")):
                if not _is_allowed_plumb_import(node.module):
                    hits.append(node.module)
    return hits


def test_plumb_gen_only_imports_plumb_domain():
    violations: list[str] = []
    for path in python_files(PLUMB_GEN_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        for hit in _disallowed_plumb_imports(tree):
            violations.append(f"{path}: imports {hit}")
    assert not violations, "\n".join(violations)
