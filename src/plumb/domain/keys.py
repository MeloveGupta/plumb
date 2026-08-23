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
