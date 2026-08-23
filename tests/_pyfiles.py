from pathlib import Path


def python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))
