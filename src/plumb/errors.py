"""LLD §9 — error hierarchy. Only the exceptions with a real consumer today
are defined; the rest of LLD §9's tree gets added when each one's consumer
arrives.
"""


class PlumbError(Exception): ...


class NoApplicableRate(PlumbError):
    """Recoverable -- becomes a finding, not a crash. rate_for raises this
    instead of silently falling back to a current or default rate."""
