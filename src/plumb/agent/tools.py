"""PRD §10.3 / TRD §7.2 -- the seven read-only tools L3 investigates with.

Bounded, whitelisted, read-only. Fixed signatures: no free-form SQL, no
arbitrary paths, no query strings (TRD §7.2). Each tool returns a
Pydantic model, never a raw dict. A tool asked for a record that does
not exist raises `ToolError`; `invoke()` catches it and returns a
`ToolFailure` the model can see and adapt to -- one bad call never
aborts the batch (TRD §12, LLD §7.2 "degrade, never abort").

Every invocation is logged as an `AgentCall` with the columns
`agent_call` expects (BACKEND_SCHEMA §3.6): the args, a sha256 of the
canonicalised result, the row count, wall-clock latency, and -- filled
in by the loop, not here -- the token split of the model turn that
requested it. `called_at_utc` and `latency_ms` are genuine real-world
measurements, exactly like `stub_engine`'s `started_at_utc`; they make
`AgentCall` non-deterministic, which is fine -- L3 is not on the 1.000
determinism path (non-negotiable 8).

# PRD-DEVIATION: PRD §10.3 lists `search_intent_ledger(query)`. TRD §7.2
# forbids free-form queries ("Fixed signatures only"). Built here as a
# structured two-field filter, `search_intent_ledger(order_id,
# seller_id)`, at least one required.
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from pydantic import BaseModel, ConfigDict

from plumb.agent.evidence import EvidenceStore
from plumb.domain.keys import IdSequence
from plumb.domain.models import Dispute, Intent, Payment, Refund, SellerRateCard, SettlementRecon, Transfer
from plumb.errors import ToolError

TOOL_NAMES = (
    "fetch_payment",
    "fetch_transfer",
    "fetch_refunds_for_payment",
    "fetch_settlement_recon",
    "fetch_dispute",
    "fetch_rate_card",
    "search_intent_ledger",
)


# --- list-result wrappers (singular fetches return the domain model directly) ---


class RefundListView(BaseModel):
    model_config = ConfigDict(frozen=True)
    payment_id: str
    refunds: list[Refund]


class ReconListView(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    recon_rows: list[SettlementRecon]


class RateCardListView(BaseModel):
    model_config = ConfigDict(frozen=True)
    seller_id: str
    as_of: str
    rate_cards: list[SellerRateCard]


class IntentListView(BaseModel):
    model_config = ConfigDict(frozen=True)
    intents: list[Intent]


class ToolFailure(BaseModel):
    """The degraded result of a tool that could not answer. Appended to
    the transcript so the model adapts rather than the run aborting."""

    model_config = ConfigDict(frozen=True)
    tool: str
    error: str


ToolResult = Payment | Transfer | Dispute | RefundListView | ReconListView | RateCardListView | IntentListView | ToolFailure


@dataclass(frozen=True)
class AgentCall:
    call_id: str
    exception_id: str
    iteration: int
    tool: str
    args: dict
    result_sha256: str
    result_row_count: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    called_at_utc: str


def _row_count(result: BaseModel) -> int:
    if isinstance(result, ToolFailure):
        return 0
    for field in ("refunds", "recon_rows", "rate_cards", "intents"):
        value = getattr(result, field, None)
        if value is not None:
            return len(value)
    return 1


def _result_sha256(result: BaseModel) -> str:
    return hashlib.sha256(result.model_dump_json().encode()).hexdigest()


class Toolbox:
    """Binds the seven tools to one run's EvidenceStore. `self.tools` is
    the name -> callable dispatch table the loop indexes with a model's
    tool call."""

    def __init__(self, store: EvidenceStore, ids: IdSequence) -> None:
        self._store = store
        self._ids = ids
        self.tools: dict[str, Callable[..., BaseModel]] = {
            "fetch_payment": self.fetch_payment,
            "fetch_transfer": self.fetch_transfer,
            "fetch_refunds_for_payment": self.fetch_refunds_for_payment,
            "fetch_settlement_recon": self.fetch_settlement_recon,
            "fetch_dispute": self.fetch_dispute,
            "fetch_rate_card": self.fetch_rate_card,
            "search_intent_ledger": self.search_intent_ledger,
        }

    # --- the tools ---

    def fetch_payment(self, payment_id: str) -> Payment:
        payment = self._store.payment(payment_id)
        if payment is None:
            raise ToolError(f"no payment {payment_id!r}")
        return payment

    def fetch_transfer(self, transfer_id: str) -> Transfer:
        transfer = self._store.transfer(transfer_id)
        if transfer is None:
            raise ToolError(f"no transfer {transfer_id!r}")
        return transfer

    def fetch_dispute(self, dispute_id: str) -> Dispute:
        dispute = self._store.dispute(dispute_id)
        if dispute is None:
            raise ToolError(f"no dispute {dispute_id!r}")
        return dispute

    def fetch_refunds_for_payment(self, payment_id: str) -> RefundListView:
        if not self._store.has_payment(payment_id):
            raise ToolError(f"no payment {payment_id!r}")
        return RefundListView(payment_id=payment_id, refunds=self._store.refunds_for_payment(payment_id))

    def fetch_settlement_recon(self, date: str) -> ReconListView:
        return ReconListView(date=date, recon_rows=self._store.settlement_recon_on(date))

    def fetch_rate_card(self, seller_id: str, as_of: str) -> RateCardListView:
        if not self._store.has_seller(seller_id):
            raise ToolError(f"no seller {seller_id!r}")
        return RateCardListView(
            seller_id=seller_id, as_of=as_of, rate_cards=self._store.rate_cards_for(seller_id, as_of)
        )

    def search_intent_ledger(self, order_id: str | None = None, seller_id: str | None = None) -> IntentListView:
        if order_id is None and seller_id is None:
            raise ToolError("search_intent_ledger requires at least one of order_id, seller_id")
        return IntentListView(intents=self._store.intents(order_id=order_id, seller_id=seller_id))

    # --- dispatch + audit log ---

    def invoke(
        self,
        name: str,
        args: dict,
        *,
        exception_id: str,
        iteration: int,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> tuple[ToolResult, AgentCall]:
        """Run one tool call, always returning a (result, AgentCall)
        pair. An unknown tool, a bad argument, or a ToolError all
        degrade to a ToolFailure result -- never an exception out of
        here. `tokens_in`/`tokens_out` are the requesting model turn's
        usage, passed by the loop on the first call of a turn and 0 on
        the rest so a later SUM over agent_call matches true API usage."""
        started = time.monotonic()
        try:
            tool = self.tools.get(name)
            if tool is None:
                raise ToolError(f"unknown tool {name!r}")
            try:
                result: ToolResult = tool(**args)
            except TypeError as exc:  # bad/missing/extra kwargs for a real tool
                raise ToolError(f"{name}: bad arguments {args!r} ({exc})") from exc
        except ToolError as exc:
            result = ToolFailure(tool=name, error=str(exc))
        latency_ms = int((time.monotonic() - started) * 1000)

        call = AgentCall(
            call_id=self._ids.next("call"),
            exception_id=exception_id,
            iteration=iteration,
            tool=name,
            args=dict(args),
            result_sha256=_result_sha256(result),
            result_row_count=_row_count(result),
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            called_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        return result, call


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "fetch_payment",
        "description": "The payment record for a payment_id. Amount, method, fee, tax, capture time.",
        "input_schema": {
            "type": "object",
            "properties": {"payment_id": {"type": "string"}},
            "required": ["payment_id"],
        },
    },
    {
        "name": "fetch_transfer",
        "description": "The Route transfer record for a transfer_id. Amount, hold state, settlement time.",
        "input_schema": {
            "type": "object",
            "properties": {"transfer_id": {"type": "string"}},
            "required": ["transfer_id"],
        },
    },
    {
        "name": "fetch_refunds_for_payment",
        "description": "Every refund booked against a payment_id (possibly none).",
        "input_schema": {
            "type": "object",
            "properties": {"payment_id": {"type": "string"}},
            "required": ["payment_id"],
        },
    },
    {
        "name": "fetch_settlement_recon",
        "description": "Every settlement reconciliation row settled on an ISO date (YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    },
    {
        "name": "fetch_dispute",
        "description": "The dispute record for a dispute_id. Gross amount and amount deducted.",
        "input_schema": {
            "type": "object",
            "properties": {"dispute_id": {"type": "string"}},
            "required": ["dispute_id"],
        },
    },
    {
        "name": "fetch_rate_card",
        "description": "Seller rate cards in force on an ISO date, across all categories, for a seller_id.",
        "input_schema": {
            "type": "object",
            "properties": {"seller_id": {"type": "string"}, "as_of": {"type": "string"}},
            "required": ["seller_id", "as_of"],
        },
    },
    {
        "name": "search_intent_ledger",
        "description": "Intent-ledger rows filtered by order_id and/or seller_id. At least one is required.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "seller_id": {"type": "string"}},
        },
    },
]
