"""TRD §8.3: `plumb-eval --run reports/{run_id} --truth data/{batch_id}/truth
[--allow-provisional]`.
"""

from pathlib import Path

import typer

from plumb_eval.errors import TruthJoinError
from plumb_eval.manifest import DirtyTreeError, ManifestMissingError
from plumb_eval.scorer import score_run

app = typer.Typer()


@app.command()
def main(
    run: Path = typer.Option(..., exists=True, help="Run directory, e.g. reports/{run_id}"),
    truth: Path = typer.Option(..., exists=True, help="Truth directory, e.g. data/{batch_id}/truth"),
    allow_provisional: bool = typer.Option(
        False,
        "--allow-provisional",
        help="Score a run with git_dirty=true anyway; stamps the output PROVISIONAL. "
        "Does not override a missing manifest.",
    ),
) -> None:
    try:
        result = score_run(run, truth, allow_provisional=allow_provisional)
    except (ManifestMissingError, DirtyTreeError) as exc:
        typer.echo(f"refusing to score: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except TruthJoinError as exc:
        typer.echo(f"fabrication -- aborting: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"scored {run} -> {run / 'eval.sqlite'}, {run / 'metrics.json'}, {run / 'metrics.md'}")
    if result["provisional"]:
        typer.echo("PROVISIONAL (dirty working tree)")


if __name__ == "__main__":
    app()
