"""TRD §8.1: `plumb-gen --seed 42 --config configs/config_b.yaml --out
data/batch_main_200`. batch_id is derived from --out's own directory
name rather than taken as a separate flag, matching that exact
invocation -- there's no --batch-id to keep in sync with --out.
"""

from datetime import date
from pathlib import Path

import typer

from plumb_gen.config_loader import load_generator_config
from plumb_gen.io import write_sources
from plumb_gen.truth_db import write_truth
from plumb_gen.world import build_world

app = typer.Typer()


@app.command()
def main(
    seed: int = typer.Option(..., help="RNG seed; same seed + config -> byte-identical output"),
    config: Path = typer.Option(
        ..., exists=True, readable=True, help="Generator config YAML, e.g. configs/config_b.yaml"
    ),
    out: Path = typer.Option(
        ..., help="Output directory; dataset/ and truth/ are written under it, e.g. data/batch_main_200"
    ),
    batch_as_of: str = typer.Option("2026-08-20", help="ISO date the batch is generated as of"),
) -> None:
    batch_id = out.name
    generator_config = load_generator_config(
        config,
        seed=seed,
        batch_id=batch_id,
        batch_as_of=date.fromisoformat(batch_as_of),
    )
    world = build_world(generator_config)
    write_sources(world, out / "dataset")

    truth_path = out / "truth" / "truth.sqlite"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    write_truth(world, truth_path)


if __name__ == "__main__":
    app()
