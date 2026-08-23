"""BACKEND_SCHEMA.md §8, item 9.

Cannot be written meaningfully yet: no code under src/plumb/ opens any file
at all, so there's nothing to assert against — the same vacuous-pass shape
the STRICT-schema stub had before P0.3. Fails loudly rather than being
skipped, and self-removes its marker (XPASS under strict=True fails the
build) the moment it's premature to keep this xfail.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="no plumb/ code opens sqlite files yet — lands with ingest/store, P1")
def test_truth_sqlite_never_opened_by_plumb_modules():
    pytest.fail("no file-opening code exists under src/plumb/ yet")
