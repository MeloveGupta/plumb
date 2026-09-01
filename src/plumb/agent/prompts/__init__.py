"""TRD §7.4 -- prompts live in versioned files here and are hashed into
the manifest. "A prompt change is a spec change": the hash lets a
reader of a run tell whether the wording the model was grounded in was
the committed wording.

# TRD-DEVIATION: TRD §7.4 / IMPLEMENTATION_PLAN P3.2 say the prompt hash
# goes "into the manifest" but name no field. `load_prompts().sha256`
# is exposed here; wiring it into manifest.json as `prompt_sha256`
# belongs to the L3 persistence-bridge task, which owns manifest
# writing (no manifest writer exists in the engine yet -- only
# stub_engine's stand-in).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompts:
    system_text: str
    sha256: str


def _hash_dir(directory: Path) -> str:
    """sha256 over every .md file in `directory`, sorted by name, each
    contribution being name + NUL + bytes + NUL -- so a rename, an edit,
    or a new file all change the digest."""
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.md")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_prompts() -> Prompts:
    """The system prompt, plus a hash over every prompt file here -- so
    adding a second prompt file later changes the hash without changing
    this code."""
    return Prompts(
        system_text=(_PROMPTS_DIR / "system.md").read_text(),
        sha256=_hash_dir(_PROMPTS_DIR),
    )
