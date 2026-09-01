"""P3 step 4 -- the seven read-only tools, their dispatch, and the
AgentCall audit record.

Row counts and record keys are read off the hand-built fixtures, not
from the tools' own output. sha256 values are never hand-computed --
the tests assert the property that matters (same call -> same hash,
different call -> different hash), not a literal digest.
"""

from _agent_fixtures import (
    dispute,
    ingest_result,
    intent,
    order,
    payment,
    rate_card,
    recon,
    refund,
    seller,
    transfer,
)

import pytest

from plumb.agent.evidence import EvidenceStore
from plumb.agent.tools import TOOL_NAMES, TOOL_SCHEMAS, AgentCall, Toolbox, ToolFailure
from plumb.domain.keys import IdSequence
from plumb.domain.models import Payment
from plumb.errors import ToolError


def _toolbox() -> Toolbox:
    batch = ingest_result(
        intent_records=[order(1), intent(1, 1), order(2, seller_id="sel_00002"), intent(2, 2, seller_id="sel_00002")],
        razorpay_records=[
            payment(1, 1),
            transfer(1, 1),
            refund(1, 1, 5_000),
            refund(2, 1, 3_000),
            dispute(1, 1, 1_200),
            recon(1, 1, settled_at="2026-07-05T00:00:00Z"),
        ],
        sellers_records=[
            seller("sel_00001"),
            seller("sel_00002"),
            rate_card(1, seller_id="sel_00001", effective_from="2026-01-01"),
        ],
    )
    return Toolbox(EvidenceStore.from_ingest(batch), IdSequence())


def test_singular_tools_return_domain_models():
    tb = _toolbox()
    assert isinstance(tb.fetch_payment("pay_00001"), Payment)
    assert tb.fetch_transfer("txfr_00001").payment_id == "pay_00001"
    assert tb.fetch_dispute("disp_00001").deducted_amount_paise == 1_200


def test_singular_tool_miss_raises_tool_error():
    tb = _toolbox()
    with pytest.raises(ToolError, match="no payment"):
        tb.fetch_payment("pay_99999")


def test_list_tools_shapes():
    tb = _toolbox()
    refunds = tb.fetch_refunds_for_payment("pay_00001")
    assert [r.refund_id for r in refunds.refunds] == ["rfnd_00001", "rfnd_00002"]

    recon_view = tb.fetch_settlement_recon("2026-07-05")
    assert [r.settlement_recon_id for r in recon_view.recon_rows] == ["setl_00001"]

    cards = tb.fetch_rate_card("sel_00001", "2026-07-01")
    assert [c.rate_card_id for c in cards.rate_cards] == ["rate_00001"]

    intents = tb.search_intent_ledger(seller_id="sel_00002")
    assert [i.intent_id for i in intents.intents] == ["int_00002"]


def test_search_intent_ledger_requires_a_filter():
    tb = _toolbox()
    with pytest.raises(ToolError, match="at least one"):
        tb.search_intent_ledger()


def test_refunds_for_unknown_payment_raises():
    tb = _toolbox()
    with pytest.raises(ToolError, match="no payment"):
        tb.fetch_refunds_for_payment("pay_99999")


def test_rate_card_for_unknown_seller_raises():
    tb = _toolbox()
    with pytest.raises(ToolError, match="no seller"):
        tb.fetch_rate_card("sel_09999", "2026-07-01")


# --- invoke(): dispatch + degrade + audit ---


def test_invoke_logs_an_agent_call():
    tb = _toolbox()
    result, call = tb.invoke(
        "fetch_refunds_for_payment", {"payment_id": "pay_00001"},
        exception_id="exc_00001", iteration=2, tokens_in=1_200, tokens_out=80,
    )
    assert len(result.refunds) == 2
    assert isinstance(call, AgentCall)
    assert call.call_id == "call_00001"
    assert call.exception_id == "exc_00001"
    assert call.iteration == 2
    assert call.tool == "fetch_refunds_for_payment"
    assert call.args == {"payment_id": "pay_00001"}
    assert call.result_row_count == 2
    assert call.tokens_in == 1_200 and call.tokens_out == 80
    assert len(call.result_sha256) == 64


def test_invoke_result_hash_is_stable_and_discriminating():
    tb = _toolbox()
    _, a = tb.invoke("fetch_payment", {"payment_id": "pay_00001"}, exception_id="exc_00001", iteration=1)
    _, b = tb.invoke("fetch_payment", {"payment_id": "pay_00001"}, exception_id="exc_00001", iteration=2)
    _, c = tb.invoke("fetch_transfer", {"transfer_id": "txfr_00001"}, exception_id="exc_00001", iteration=3)
    assert a.result_sha256 == b.result_sha256  # same query -> same hash
    assert a.result_sha256 != c.result_sha256  # different record -> different hash
    assert a.call_id != b.call_id  # but each call is its own row


def test_invoke_degrades_an_unknown_tool_to_a_failure():
    tb = _toolbox()
    result, call = tb.invoke("run_sql", {"q": "SELECT *"}, exception_id="exc_00001", iteration=1)
    assert isinstance(result, ToolFailure)
    assert "unknown tool" in result.error
    assert call.result_row_count == 0
    assert call.tool == "run_sql"


def test_invoke_degrades_bad_arguments_to_a_failure():
    tb = _toolbox()
    result, _ = tb.invoke("fetch_payment", {"wrong_kwarg": "x"}, exception_id="exc_00001", iteration=1)
    assert isinstance(result, ToolFailure)
    assert "bad arguments" in result.error


def test_invoke_degrades_a_missing_record_to_a_failure():
    tb = _toolbox()
    result, call = tb.invoke("fetch_payment", {"payment_id": "pay_99999"}, exception_id="exc_00001", iteration=1)
    assert isinstance(result, ToolFailure)
    assert "no payment" in result.error
    assert call.result_row_count == 0


def test_tool_schemas_match_the_seven_tool_names():
    assert tuple(s["name"] for s in TOOL_SCHEMAS) == TOOL_NAMES
    assert len(TOOL_SCHEMAS) == 7
