"""BACKEND_SCHEMA.md §1.2 -- record_key format: prefix + zero-padded-to-5.

One counter per prefix, sequential. "Derived from the seed" (TRD §8.1)
means the world built under a given seed always creates the same records
in the same order, not that individual id numbers are seed-hashed.
"""


class IdSequence:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}_{n:05d}"
