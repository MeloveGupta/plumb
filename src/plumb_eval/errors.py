"""LLD §9 calls TruthJoinError "scorer only", but it can't live in
plumb/errors.py -- that module is top-level plumb, not plumb.domain, and
TRD §3.1 only allows plumb_eval to import plumb.domain and plumb_gen.
Owned here instead of subclassing plumb.errors.PlumbError for the same
reason.
"""


class TruthJoinError(Exception):
    """A record_key from run.sqlite resolves to no truth closure at all --
    TRD §8.3's fabrication case. Fatal: aborts the whole scoring run rather
    than being counted as a metric.
    """
