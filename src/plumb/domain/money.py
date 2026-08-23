"""LLD §2 — Paise/Bps are documentation, not enforcement.

The four money functions (apply_bps, sum_paise, format_inr,
parse_rupee_string) are deliberately not here yet. Their first real
consumer is the rules module (P0.5); writing them now, unused, would be
building ahead of the task that needs them.
"""

Paise = int
Bps = int
