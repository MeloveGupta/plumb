"""LLD §1's dependency rule, the half never enforced until now:

    ingest → match → verify → agent → report        (strictly one direction)

"`match` may not import `verify`. `verify` may not import `agent`. A
backward edge means a layer boundary has leaked." Deferred since P0.2
because every layer under src/plumb/ was empty and this test would have
passed vacuously -- ingest/ has real content as of P1.1, so it stops
being vacuous now.

domain/, store/, rules/, errors.py, config.py are governed by a
different rule (domain <- everything, store <- all layers, rules <-
verify only) and are deliberately not checked here -- this test is
scoped to the five-layer chain only, same scoping discipline as
tests/test_import_boundary.py's own per-package checks.

Static AST check only, same accepted gap as test_import_boundary.py:
cannot see a dynamically constructed import.
"""

import ast
from pathlib import Path

from _pyfiles import python_files

PLUMB_ROOT = Path(__file__).parent.parent / "src" / "plumb"
LAYER_ORDER = ["ingest", "match", "verify", "agent", "report"]


def _root_module(dotted_name: str) -> str:
    return dotted_name.split(".")[0]


def _layer_submodule(dotted_name: str) -> str | None:
    """"plumb.ingest.normalise" -> "ingest"; "plumb.domain.keys" -> None."""
    parts = dotted_name.split(".")
    if len(parts) >= 2 and parts[0] == "plumb" and parts[1] in LAYER_ORDER:
        return parts[1]
    return None


def _imported_layers(tree: ast.Module) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                layer = _layer_submodule(alias.name)
                if layer:
                    hits.append(layer)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, resolved within the file's own
            # package -- e.g. "from . import X" inside ingest/ can only ever
            # reach ingest/'s own tree, never another layer. Skip rather than
            # false-flag; level == 0 with no module (a bare "from . import x")
            # is covered by the same reasoning.
            if node.level == 0 and node.module:
                layer = _layer_submodule(node.module)
                if layer:
                    hits.append(layer)
    return hits


def _file_layer(path: Path) -> str | None:
    rel = path.relative_to(PLUMB_ROOT)
    top = rel.parts[0]
    return top if top in LAYER_ORDER else None


def test_no_layer_imports_a_later_layer():
    violations: list[str] = []
    for path in python_files(PLUMB_ROOT):
        file_layer = _file_layer(path)
        if file_layer is None:
            continue  # domain/, store/, rules/, errors.py, config.py -- not this rule
        file_index = LAYER_ORDER.index(file_layer)

        tree = ast.parse(path.read_text(), filename=str(path))
        for imported_layer in _imported_layers(tree):
            imported_index = LAYER_ORDER.index(imported_layer)
            if imported_index > file_index:
                violations.append(f"{path} ({file_layer}) imports {imported_layer}")
    assert not violations, "\n".join(violations)
