"""TRD §8.1: `plumb-gen --seed 42 --config configs/config_b.yaml --out
data/batch_main_200`. Config-file loading (YAML, configs/config_*.yaml) is
P0.13's job; today this exposes GeneratorConfig's knobs as flags directly
rather than reading a file that doesn't exist yet.
"""

from datetime import date
from pathlib import Path

import typer

from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_dataset
from plumb_gen.world import build_world

app = typer.Typer()


@app.command()
def main(
    seed: int = typer.Option(..., help="RNG seed; same seed + config -> byte-identical output"),
    batch_id: str = typer.Option(..., help="Identifies this batch, e.g. batch_main_200"),
    out: Path = typer.Option(..., help="Output directory; dataset/ is written under it"),
    batch_as_of: str = typer.Option("2026-08-20", help="ISO date the batch is generated as of"),
) -> None:
    config = GeneratorConfig(
        seed=seed,
        batch_id=batch_id,
        batch_as_of=date.fromisoformat(batch_as_of),
    )
    world = build_world(config)
    write_dataset(world, out / "dataset")


if __name__ == "__main__":
    app()
