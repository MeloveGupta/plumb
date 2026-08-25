"""LLD §4.1/§4.2, TRD §5.2, P1.9 -- property-based tests over a
randomised mix of matcher scenarios.

`plumb_gen` cannot exercise P2 or P3 (confirmed by reading
plumb_gen/world.py directly, not by inference): every settled order
gets exactly one dedicated BankCredit -- there is no code path that
batches multiple orders' money into one physical bank credit, so P2's
n:1/1:n grouping has no real data to ever fire on. And bank_credit and
settlement_recon stay numerically identical to each other in every
scenario including D02 (D02's shortfall lives on the intent-expected
vs. actual-settled axis, which is verify's job, not the matcher's
bank-vs-recon axis) -- so P3's tolerance band never has anything to
absorb either. These strategies build RecordSets directly instead,
same shape as _match_fixtures.py's hand-built fixtures, randomised and
composed into one batch per example.

Properties asserted are universal invariants that must hold regardless
of the specific random mix drawn -- not "this chain must resolve via
pass X", since two independently-drawn chains could coincidentally
collide (same target, same date) and legitimately turn each other
ambiguous. Predicting exact per-chain outcomes would make the test
flaky on an accidental collision; asserting invariants over whatever
the actual result is does not.
"""

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from plumb.domain.tolerance import DEFAULT_V1
from plumb.match.engine import MatchConfig, MatchEngine

from _match_fixtures import _bank_credit, _intent, _order, _payment, _record_set, _recon, _transfer

_BASE_DATE = date(2026, 7, 5)
_AMOUNT = st.integers(min_value=10_000, max_value=500_000)


def _chain_records(n, target_paise, settlement_id=None):
    settlement_id = settlement_id or f"stlbatch_{n}"
    return [
        _order(n), _intent(n, n), _payment(n, n), _transfer(n, n),
        _recon(n, n, settlement_id, f"UTR{n:012d}", credit_paise=target_paise,
               settled_at=f"{_BASE_DATE.isoformat()}T00:00:00Z"),
    ], settlement_id


@st.composite
def _clean(draw, n):
    target = draw(_AMOUNT)
    records, _ = _chain_records(n, target)
    records.append(_bank_credit(n, target, credited_on=_BASE_DATE.isoformat(), utr=f"UTR{n:012d}"))
    return records, n + 1


@st.composite
def _p1_exact(draw, n):
    target = draw(_AMOUNT)
    records, _ = _chain_records(n, target)
    records.append(_bank_credit(n, target, credited_on=_BASE_DATE.isoformat(), utr=None))
    return records, n + 1


@st.composite
def _p3_within_band(draw, n):
    target = draw(_AMOUNT)
    band = DEFAULT_V1.band_paise(target)
    shortfall = draw(st.integers(min_value=1, max_value=max(1, band)))
    day_offset = draw(st.integers(min_value=0, max_value=DEFAULT_V1.date_window_days))
    records, _ = _chain_records(n, target)
    credited_on = (_BASE_DATE + timedelta(days=day_offset)).isoformat()
    records.append(_bank_credit(n, target - shortfall, credited_on=credited_on, utr=None))
    return records, n + 1


@st.composite
def _outside_band(draw, n):
    target = draw(_AMOUNT)
    band = DEFAULT_V1.band_paise(target)
    shortfall = band + draw(st.integers(min_value=1, max_value=1_000))
    records, _ = _chain_records(n, target)
    records.append(_bank_credit(n, target - shortfall, credited_on=_BASE_DATE.isoformat(), utr=None))
    return records, n + 1


@st.composite
def _p2_group(draw, n):
    count = draw(st.integers(min_value=2, max_value=3))
    settlement_id = f"stlbatch_grp_{n}"
    records = []
    total = 0
    for i in range(count):
        target = draw(_AMOUNT)
        total += target
        chain, _ = _chain_records(n + i, target, settlement_id=settlement_id)
        records.extend(chain)  # no individual bank credit -- money arrives combined
    records.append(_bank_credit(n, total, credited_on=_BASE_DATE.isoformat(), utr=None))
    return records, n + count


@st.composite
def _ambiguous_pair(draw, n):
    target = draw(_AMOUNT)
    records = []
    for i in range(2):
        chain, _ = _chain_records(n + i, target)  # distinct settlement_ids -- not a P2 group
        records.extend(chain)
    records.append(_bank_credit(n, target, credited_on=_BASE_DATE.isoformat(), utr=None))
    return records, n + 2


def _intent_only(n):
    return st.just(([_order(n), _intent(n, n)], n + 1))


_SHAPE_BUILDERS = (_clean, _p1_exact, _p3_within_band, _outside_band, _p2_group, _ambiguous_pair, _intent_only)


@st.composite
def _batch(draw):
    shapes = draw(st.lists(st.sampled_from(_SHAPE_BUILDERS), min_size=3, max_size=10))
    all_records = []
    n = 1
    for build in shapes:
        records, n = draw(build(n))
        all_records.extend(records)
    return _record_set(*all_records)


@given(records=_batch())
@settings(max_examples=100)
def test_no_record_is_ever_claimed_twice(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    claimed = [key for group in result.groups for key, _ in group.members]
    assert len(claimed) == len(set(claimed))
    assert set(claimed).isdisjoint(result.unmatched)


@given(records=_batch())
@settings(max_examples=100)
def test_every_record_is_accounted_for_exactly_once(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    claimed = {key for group in result.groups for key, _ in group.members}
    accounted = claimed | set(result.unmatched)
    assert accounted == set(records.all_keys())


@given(records=_batch())
@settings(max_examples=100)
def test_every_group_has_complete_evidence(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    expected_confidence = {"P0": 10_000, "P1": 9_500, "P2": 9_000, "P3": 7_000}
    for group in result.groups:
        assert group.rule_id
        assert group.pass_ in expected_confidence
        assert group.confidence_bps == expected_confidence[group.pass_]
        assert len(group.members) >= 1


@given(records=_batch())
@settings(max_examples=100)
def test_p2_groups_sum_exactly_between_bank_and_settlement_sides(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    for group in result.groups:
        if group.pass_ != "P2":
            continue
        bank_total = sum(
            records.get(key).amount_paise for key, side in group.members if side == "bank"
        )
        recon_total = sum(
            records.get(key).credit_paise - records.get(key).debit_paise
            for key, side in group.members
            if side == "razorpay" and hasattr(records.get(key), "credit_paise")
        )
        assert bank_total == recon_total


@given(records=_batch())
@settings(max_examples=100)
def test_p3_groups_are_within_the_tolerance_band(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    result = engine.run(records)

    for group in result.groups:
        if group.pass_ != "P3":
            continue
        bank_amounts = [records.get(key).amount_paise for key, side in group.members if side == "bank"]
        recon_targets = [
            records.get(key).credit_paise - records.get(key).debit_paise
            for key, side in group.members
            if side == "razorpay" and hasattr(records.get(key), "credit_paise")
        ]
        assert len(bank_amounts) == 1 and len(recon_targets) == 1
        assert DEFAULT_V1.within(recon_targets[0], bank_amounts[0])


@given(records=_batch())
@settings(max_examples=50)
def test_engine_run_is_deterministic(records):
    engine = MatchEngine(tolerance=DEFAULT_V1, cfg=MatchConfig())
    assert engine.run(records) == engine.run(records)
