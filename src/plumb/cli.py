"""`plumb run` -- the L0->L4 CLI. Same one-@app.command() Typer shape as
plumb-gen and plumb-eval. The batch must already be generated
(`plumb-gen --out <data_dir>`); this reads <data_dir>/dataset/.
"""

from datetime import date
from pathlib import Path

import typer

from plumb.pipeline import execute_run, run_repeated

app = typer.Typer(add_completion=False)


@app.callback()
def _root() -> None:
    """Plumb -- settlement assurance engine. The batch must already exist
    (`plumb-gen --out <data_dir>`)."""


@app.command()
def run(
    data: Path = typer.Option(..., exists=True, help="Batch directory holding dataset/ (from plumb-gen --out)"),
    ablation: str = typer.Option("hybrid", help="rules_only | hybrid"),
    sample_label: str = typer.Option(..., help="IN_SAMPLE | HELD_OUT (this run's config provenance)"),
    seed: int = typer.Option(..., help="The generator seed the batch was made with (manifest provenance)"),
    generator_config: Path = typer.Option(
        ..., exists=True, help="The generator config the batch was made with (for generator_config_sha256)"
    ),
    out: Path = typer.Option(Path("reports"), help="Reports directory; reports/<run_id>/ is written under it"),
    as_of: str = typer.Option("2026-08-26", help="As-of date for the verify layer's rate lookups (ISO)"),
    model_mode: str = typer.Option("replay", help="replay | record | live (ignored for rules_only)"),
    batch_token_budget: int = typer.Option(None, help="Optional whole-batch L3 token cap"),
    repeat: int = typer.Option(1, help="Run N times and score L3 determinism (PRD §7.9); needs N>=2"),
) -> None:
    if ablation not in ("rules_only", "hybrid"):
        raise typer.BadParameter("ablation must be rules_only or hybrid")
    if sample_label not in ("IN_SAMPLE", "HELD_OUT"):
        raise typer.BadParameter("sample_label must be IN_SAMPLE or HELD_OUT")

    common = dict(
        data_dir=data,
        out_dir=out,
        ablation=ablation,
        sample_label=sample_label,
        generator_seed=seed,
        generator_config=generator_config,
        as_of=date.fromisoformat(as_of),
        model_mode=model_mode,
        batch_token_budget=batch_token_budget,
    )

    if repeat > 1:
        result = run_repeated(repeat=repeat, **common)
        typer.echo(f"determinism runs  {result['runs']}  ({', '.join(result['run_ids'])})")
        typer.echo(f"exceptions        {result['exceptions_total']}")
        typer.echo(f"identical         {result['exceptions_identical_across_all_runs']}")
        score = result["determinism_score"]
        typer.echo(f"determinism_score {score:.3f}" if score is not None else "determinism_score NOT_MEASURED")
        typer.echo(f"written           {out}/{result['run_ids'][0]}/determinism.json")
        return

    outcome = execute_run(**common)

    typer.echo(f"run_id            {outcome.run_id}")
    typer.echo(f"ablation          {outcome.ablation}")
    typer.echo(f"exceptions        {outcome.exception_count}")
    for label in ("AUTO_RESOLVED", "PROPOSED", "ESCALATED_UNRESOLVED"):
        typer.echo(f"  {label:<20} {outcome.resolution_outcomes.get(label, 0)}")
    typer.echo(f"written           {outcome.run_dir}/")
    typer.echo(f"score it          plumb-eval --run {outcome.run_dir} --truth {data}/truth")


if __name__ == "__main__":
    app()
