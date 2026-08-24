"""BACKEND_SCHEMA.md §2 -- the three source writers must genuinely
diverge, and the narration cascade must actually get exercised end to
end, not just look varied by eye.
"""

import csv
import json
import re

import pytest

from plumb_gen.config import GeneratorConfig
from plumb_gen.io import write_sources
from plumb_gen.world import build_world

SEEDS = [1, 2, 3, 7, 42]

# LLD §3.2, transcribed here since narration.py's extraction side doesn't
# exist until P1.2 -- this is the real cascade the generator's narrations
# have to survive, not a stand-in.
UTR_PATTERNS = [
    ("utr_labelled", re.compile(r"\bUTR[:\s-]*([A-Z0-9]{12,22})\b")),
    ("neft_ref", re.compile(r"\bNEFT[/\s-]*([A-Z]{4}[A-Z0-9]{8,18})\b")),
    ("rtgs_ref", re.compile(r"\bRTGS[/\s-]*([A-Z0-9]{16,22})\b")),
    ("imps_ref", re.compile(r"\bIMPS[/\s-]*(\d{12})\b")),
    ("bare_token", re.compile(r"\b([A-Z]{4}[A-Z0-9]{12,18})\b")),
]


def _classify(narration: str) -> str:
    for name, pattern in UTR_PATTERNS:
        if pattern.search(narration):
            return name
    return "unparseable"


def _read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_all_three_files_exist(tmp_path):
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")
    assert (tmp_path / "dataset" / "intent.csv").exists()
    assert (tmp_path / "dataset" / "razorpay.json").exists()
    assert (tmp_path / "dataset" / "bank.csv").exists()


def test_intent_csv_uses_seller_name_not_seller_id(tmp_path):
    from plumb_gen.fixtures import SELLER_NAMES

    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")
    rows = _read_csv(tmp_path / "dataset" / "intent.csv")
    assert "seller_id" not in rows[0]
    assert "seller_name" in rows[0]
    assert all(row["seller_name"] in SELLER_NAMES for row in rows)


def test_bank_csv_has_no_utr_column(tmp_path):
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")
    rows = _read_csv(tmp_path / "dataset" / "bank.csv")
    assert "utr" not in rows[0]
    assert "narration" in rows[0]


def test_same_order_same_amount_across_formats_different_shape(tmp_path):
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")

    intent_rows = {r["order_id"]: r for r in _read_csv(tmp_path / "dataset" / "intent.csv")}
    razorpay = json.loads((tmp_path / "dataset" / "razorpay.json").read_text())
    payments_by_order = {p["order_id"]: p for p in razorpay["payments"]}

    order = world.orders[0]
    intent_row = intent_rows[order.order_id]
    payment = payments_by_order[order.order_id]

    # Same underlying amount, genuinely different representation: a comma
    # -grouped rupee string on one side, a raw paise int on the other.
    rupees, paise = intent_row["gross_amount"].split(".")
    reconstructed_paise = int(rupees.replace(",", "")) * 100 + int(paise)
    assert reconstructed_paise == payment["amount"] == order.gross_paise
    assert isinstance(payment["amount"], int)


@pytest.mark.parametrize("seed", SEEDS)
def test_all_five_narration_patterns_appear_in_a_full_batch(tmp_path, seed):
    world = build_world(GeneratorConfig(seed=seed, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")
    rows = _read_csv(tmp_path / "dataset" / "bank.csv")

    seen = {_classify(row["narration"]) for row in rows}
    expected = {name for name, _ in UTR_PATTERNS} | {"unparseable"}
    missing = expected - seen
    assert not missing, f"patterns never exercised in this batch: {missing}"


def test_unparseable_rate_zero_produces_zero_unparseable_narrations(tmp_path):
    # The T4 case: config sets this to 0, and it must be exact, not just
    # low -- T4's gate depends on this being genuinely zero.
    config = GeneratorConfig(seed=1, batch_id="batch_test", unparseable_narration_rate_bps=0)
    world = build_world(config)
    write_sources(world, tmp_path / "dataset")
    rows = _read_csv(tmp_path / "dataset" / "bank.csv")

    unparseable = [row["narration"] for row in rows if _classify(row["narration"]) == "unparseable"]
    assert unparseable == []


def test_default_unparseable_rate_produces_some_but_not_all_unparseable(tmp_path):
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path / "dataset")
    rows = _read_csv(tmp_path / "dataset" / "bank.csv")

    total = len(rows)
    unparseable_count = sum(1 for row in rows if _classify(row["narration"]) == "unparseable")
    # Loose bound -- it's a random draw around 5%, not an exact count.
    assert 0 < unparseable_count < total * 0.2


def test_bank_credit_utr_null_iff_narration_unparseable(tmp_path):
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    for bank_credit in world.bank_credits:
        is_unparseable = _classify(bank_credit.narration) == "unparseable"
        assert (bank_credit.utr is None) == is_unparseable


def test_settlement_recon_utr_always_present_even_when_bank_side_is_not(tmp_path):
    # Razorpay always knows its own reference, independent of whether the
    # bank statement's free text happens to reveal it.
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    assert all(sr.utr for sr in world.settlement_recons)


def test_razorpay_json_settlements_carry_utr(tmp_path):
    # world.settlement_recons always has utr set (the test above), but the
    # JSON *writer* had its own, separate gap: the settlements array never
    # actually serialized it, so a real consumer of dataset/razorpay.json
    # (P1.1's ingest adapter) could never have recovered it. Caught by
    # trying to parse the real file, not by reading sources.py.
    world = build_world(GeneratorConfig(seed=1, batch_id="batch_test"))
    write_sources(world, tmp_path)
    payload = json.loads((tmp_path / "razorpay.json").read_text())
    assert payload["settlements"]
    assert all(s["utr"] for s in payload["settlements"])
    assert {s["utr"] for s in payload["settlements"]} == {sr.utr for sr in world.settlement_recons}
