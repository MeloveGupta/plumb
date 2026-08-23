"""TRD §2.5 — no `float` in any type annotation under src/, except report/.

Covers three annotation sites, which is really two AST node kinds:
function parameters and return type (live on FunctionDef/AsyncFunctionDef),
and everything else — module, class-body (Pydantic/dataclass fields), and
local variable annotations — which are all the same ast.AnnAssign node.
Python's grammar doesn't distinguish a dataclass field from any other
annotated assignment.

Gap: a quoted forward ref (`x: "float"`) is an ast.Constant string, not an
ast.Name, and this check won't see it.
"""

import ast
from pathlib import Path

from _pyfiles import python_files

SRC_ROOT = Path(__file__).parent.parent / "src"
EXEMPT = SRC_ROOT / "plumb" / "report"


def _annotation_uses_float(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(
        isinstance(node, ast.Name) and node.id == "float"
        for node in ast.walk(annotation)
    )


def _float_annotations(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            params = [
                *args.posonlyargs,
                *args.args,
                *args.kwonlyargs,
                *([args.vararg] if args.vararg else []),
                *([args.kwarg] if args.kwarg else []),
            ]
            for param in params:
                if _annotation_uses_float(param.annotation):
                    hits.append(f"{node.name}({param.arg}: float)")
            if _annotation_uses_float(node.returns):
                hits.append(f"{node.name}(...) -> float")
        elif isinstance(node, ast.AnnAssign):
            if _annotation_uses_float(node.annotation):
                target = ast.unparse(node.target)
                hits.append(f"{target}: float")
    return hits


def test_no_float_in_type_annotations_outside_report_layer():
    violations: list[str] = []
    for path in python_files(SRC_ROOT):
        if EXEMPT in path.parents:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for hit in _float_annotations(tree):
            violations.append(f"{path}: {hit}")
    assert not violations, "\n".join(violations)
