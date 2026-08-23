"""PRD §5 -- independently cited, NOT imported from plumb.rules.

plumb_gen may only import plumb.domain (TRD §3.1); it cannot import
plumb.rules even though these are the same numbers ratebook.py uses. If
the generator computed truth by calling the engine's own rate lookup, a
drift bug in the engine's rates would be invisible to scoring -- the
"ground truth" and the "answer" would silently move together. The
duplication is deliberate, not an oversight.
"""

TDS_BPS = 10  # PRD §5.1 -- 0.1% of GROSS, effective 1 Oct 2024
TCS_BPS = 50  # PRD §5.2 -- 0.5% of NET_OF_RETURNS, effective 10 Jul 2024
GST_ON_FEES_BPS = 1800  # PRD §5.3 -- 18% on MDR and platform commission
