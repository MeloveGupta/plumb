"""BACKEND_SCHEMA.md §1.2 — record_key format: prefix + zero-padded-to-5.

One generic pattern, not a type per entity prefix (ord_, pay_, ...). This
catches a malformed key but not a pay_-prefixed value landing in an
order_id field — that gap is accepted; nine near-duplicate types wasn't
worth it for a mixup the matcher's claim-once assertions (P1.9) would
likely surface anyway.
"""

from typing import Annotated

from pydantic import StringConstraints

RecordKey = Annotated[str, StringConstraints(pattern=r"^[a-z]+_\d{5}$")]


class IdSequence:
    """Deterministic, zero-padded, one counter per prefix -- the engine's
    own equivalent of plumb_gen/ids.py's IdSequence. Kept separate rather
    than imported from plumb_gen: plumb (the engine) may never import
    plumb_gen (TRD §3.1), and L1/L2's determinism guarantee needs every
    id the engine itself assigns (raw_id, transform_id, ...) to be
    seed-order-derived, never uuid4() or time-based, same reasoning as
    the generator's own ids.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}_{n:05d}"
