"""LLD §6 — Basis is an explicit, unmissable parameter. Getting it wrong is
defects D04 and D05.
"""

from enum import StrEnum


class Basis(StrEnum):
    GROSS = "gross"
    NET_OF_RETURNS = "net_of_returns"
    TAXABLE_VALUE = "taxable_value"
