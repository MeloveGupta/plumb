"""Hand-computed fixtures for the rules module — PRD §5, LLD §6.

Every expected paise value here is computed on paper first, never derived
from RateBook/apply_bps themselves. Do not "fix" a failing assertion by
recomputing it from the code under test.
"""

from datetime import UTC, date, datetime

import pytest

from plumb.domain.money import apply_bps
from plumb.errors import NoApplicableRate
from plumb.rules.basis import Basis
from plumb.rules.ratebook import RateBook, RateKind, RateRule, default_ratebook

# Rs 100.00 gross order, Rs 15.00 commission, Rs 2.00 MDR.
GROSS_PAISE = 10_000


def test_net_settlement_reconciles_for_context():
    # Not a rules-module assertion on its own -- proving the Rs 83 figure
    # from the brief is consistent, so it isn't mistaken for a tax basis
    # figure in the two tests below.
    commission_paise = 1_500
    mdr_paise = 200
    net_settlement_paise = GROSS_PAISE - commission_paise - mdr_paise
    assert net_settlement_paise == 8_300  # Rs 83.00


def test_tds_on_gross_hand_computed():
    rule = default_ratebook().rate_for(RateKind.TDS, as_of=date(2026, 7, 15))
    assert rule.basis is Basis.GROSS
    # TDS basis is GROSS -- before commission, MDR, or fees (PRD §5.1). It
    # is NOT the Rs 83 net settlement figure; that substitution is exactly
    # the basis error D05 exists to catch.
    tds_paise = apply_bps(GROSS_PAISE, rule.rate_bps)
    assert tds_paise == 10  # 0.1% of Rs 100.00 = Rs 0.10 = 10 paise, exact.


def test_tcs_on_net_of_returns_hand_computed():
    rule = default_ratebook().rate_for(RateKind.TCS, as_of=date(2026, 7, 15))
    assert rule.basis is Basis.NET_OF_RETURNS
    # This "net" is a different net than the Rs 83 net-settlement figure
    # above -- PRD §5.2 defines it as gross taxable supply minus returns,
    # nothing to do with commission/MDR. Conflating the two is exactly the
    # D04 basis error.
    returns_paise = 2_000  # Rs 20.00 returned against the Rs 100.00 order
    net_of_returns_paise = GROSS_PAISE - returns_paise
    assert net_of_returns_paise == 8_000  # Rs 80.00
    tcs_paise = apply_bps(net_of_returns_paise, rule.rate_bps)
    assert tcs_paise == 40  # 0.5% of Rs 80.00 = Rs 0.40 = 40 paise, exact.


def test_rate_for_raises_rather_than_defaulting_before_the_documented_start_date():
    with pytest.raises(NoApplicableRate):
        default_ratebook().rate_for(RateKind.TDS, as_of=date(2020, 1, 1))


def test_rate_for_raises_for_a_kind_with_no_registered_rule():
    # GST_ON_FEES has no sourced effective_from in PRD §5.3 -- deliberately
    # unregistered rather than guessed. See P0.5 plan notes.
    with pytest.raises(NoApplicableRate):
        default_ratebook().rate_for(RateKind.GST_ON_FEES, as_of=date(2026, 7, 15))


def test_basis_is_keyword_only():
    with pytest.raises(TypeError):
        RateRule("X", 10, Basis.GROSS, date(2024, 1, 1), None, "prov", None, "src")


def test_as_of_lookup_picks_the_period_containing_the_transaction_date():
    # Synthetic fixture, deliberately unrelated to real TDS/TCS history --
    # this proves the lookup mechanism, not PRD's actual rates.
    old_rule = RateRule(
        "SYN_OLD",
        100,
        basis=Basis.GROSS,
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 9, 30),
        provision="synthetic old rule",
        legacy_provision=None,
        source_url="test fixture",
    )
    new_rule = RateRule(
        "SYN_NEW",
        10,
        basis=Basis.GROSS,
        effective_from=date(2024, 10, 1),
        effective_to=None,
        provision="synthetic new rule",
        legacy_provision=None,
        source_url="test fixture",
    )
    book = RateBook({RateKind.TDS: [old_rule, new_rule]})

    # A June 2024 transaction must get the OLD rule, even though the book
    # also contains the later (currently-open, effective_to=None) rule --
    # the easy bug is checking only effective_from and forgetting the
    # upper bound, or mishandling effective_to=None so it matches every
    # date instead of just "no upper bound yet."
    assert book.rate_for(RateKind.TDS, as_of=date(2024, 6, 15)) is old_rule

    # Boundary dates, inclusive on both ends.
    assert book.rate_for(RateKind.TDS, as_of=date(2024, 9, 30)) is old_rule
    assert book.rate_for(RateKind.TDS, as_of=date(2024, 10, 1)) is new_rule

    # A present-day transaction gets the open-ended new rule.
    assert book.rate_for(RateKind.TDS, as_of=date(2026, 7, 15)) is new_rule


def test_verified_on_is_within_thirty_days_of_today():
    # Deliberately a ticking check -- passes today, meant to start failing
    # in 30 days to force re-verification before submission (TRD §6.3).
    # Not a bug if this goes red later.
    #
    # Anchored to UTC, not date.today() (system-local time): this repo's
    # dev sandbox is IST (UTC+5:30) while GitHub Actions runs in UTC, so a
    # VERIFIED_ON set from IST "today" can read as tomorrow on a UTC clock
    # and make days_old go negative -- exactly what broke the first CI run
    # of this test.
    today_utc = datetime.now(UTC).date()
    days_old = (today_utc - RateBook.VERIFIED_ON).days
    assert 0 <= days_old <= 30
