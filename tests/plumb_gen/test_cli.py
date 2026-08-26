"""P0.9 -- end-to-end CLI wiring: dataset/ and truth/ both land under
--out, from a real YAML config file, via the actual console-script
entrypoint (typer's app object), not by calling build_world directly.
"""

import sqlite3

from typer.testing import CliRunner

from plumb_gen.cli import app

runner = CliRunner()


def test_cli_writes_dataset_and_truth(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
        batch_size: 20
        defects:
          D01: {count: 2}
          D06: {count: 1}
        """
    )
    out_dir = tmp_path / "batch_main_20"

    result = runner.invoke(
        app,
        [
            "--seed", "42",
            "--config", str(config_path),
            "--out", str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output

    dataset_dir = out_dir / "dataset"
    assert (dataset_dir / "intent.csv").exists()
    assert (dataset_dir / "razorpay.json").exists()
    assert (dataset_dir / "bank.csv").exists()

    truth_path = out_dir / "truth" / "truth.sqlite"
    assert truth_path.exists()

    conn = sqlite3.connect(truth_path)
    truth_count = conn.execute("SELECT COUNT(*) FROM truth_record").fetchone()[0]
    defect_count = conn.execute("SELECT COUNT(*) FROM injected_defect").fetchone()[0]
    conn.close()

    assert truth_count == 20
    assert defect_count == 3  # 2 (D01) + 1 (D06), hand-counted from the config above


def test_cli_accepts_a_tier_flag(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("batch_size: 10\n")
    out_dir = tmp_path / "batch_t4"

    result = runner.invoke(
        app,
        ["--seed", "42", "--config", str(config_path), "--out", str(out_dir), "--tier", "T4"],
    )

    assert result.exit_code == 0, result.output
    assert (out_dir / "truth" / "truth.sqlite").exists()


def test_cli_rejects_an_unknown_tier(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("batch_size: 10\n")
    out_dir = tmp_path / "batch_bad_tier"

    result = runner.invoke(
        app,
        ["--seed", "42", "--config", str(config_path), "--out", str(out_dir), "--tier", "T9"],
    )

    assert result.exit_code != 0
