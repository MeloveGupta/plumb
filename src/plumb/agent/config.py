"""LLD §10 -- the agent's tuning knobs.

LLD §10 puts these on an umbrella `PlumbConfig` alongside `tolerance`
and `verify`; that umbrella doesn't exist yet (no orchestration layer),
so `AgentConfig` stands alone here and a future `PlumbConfig` composes
it. `frozen=True` + `extra="forbid"` for the same reasons LLD gives:
config cannot mutate mid-run (or `engine_config_sha256` in the manifest
describes a state that no longer applies), and a typo'd key fails at
load rather than being silently ignored.

The four thresholds below are placeholders in exactly the sense
`VerifyConfig`'s are -- no spec or config file gives numbers. They are
tuned against `config_a` only (never `config_b`, non-negotiable 11),
and every one of them is surfaced in the run report header and the
manifest (APP_FLOW §6) so a reader can see what autonomy was granted
under.

Starting values, and the reasoning for each:

- `auto_resolve_threshold_paise = 10_000` (Rs 100.00). Sits at
  `VerifyConfig.severity_medium_min_paise` -- an auto-resolve the model
  gets wrong below this is, by our own severity scale, not even a
  medium-severity miss. Autonomy is granted only where a mistake is
  immaterial.
- `confidence_threshold_bps = 9000` (0.90). A high bar: the model must
  be clearly sure, not merely more-likely-than-not, before code lets
  it act without a human.
- `token_budget = 60_000` per exception. Room for ~8 iterations of
  grounded evidence-gathering on one break with Sonnet, no batch-wide
  context dumps (TRD §7.4).
- `reserve_tokens = 4_000`. Held back so there is always enough budget
  to emit a proper ESCALATED_UNRESOLVED with its `what_would_resolve_it`
  -- an agent that runs out mid-thought and produces nothing is worse
  than one that stops early and says why (LLD §7.2).

# TRD-DEVIATION: TRD §7.3 / PRD §10.4 write confidence as a float 0..1.
# Represented here as integer basis points (0..10000), identical to how
# match/engine.py::MatchGroup.confidence_bps handles the same
# constraint -- the no-float lint (TRD §2.5) covers src/plumb/agent/
# (only report/ and plumb_eval/ are exempt), and a float field would
# trip it. Float appears once, at the resolution.confidence REAL write
# boundary, in the persistence-bridge task -- never on a comparison or
# a money path.

# LLD-DEVIATION: LLD §10 lists `temperature=0.0` as an AgentConfig
# field. It lives as agent/model.py::TEMPERATURE instead: it is never
# anything but 0.0 (non-negotiable 8's spirit -- L3 determinism is a
# finding, not a knob to turn), and a `temperature: float` field would
# trip the no-float lint. The manifest still records llm_temperature
# 0.0, read from that constant by the bridge task.
"""

import hashlib

from pydantic import BaseModel, ConfigDict


class AgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_iterations: int = 8
    token_budget: int = 60_000
    reserve_tokens: int = 4_000
    max_output_tokens: int = 4_096
    auto_resolve_threshold_paise: int = 10_000
    confidence_threshold_bps: int = 9_000
    # TRD-DEVIATION: TRD §7.1's default is `claude-sonnet-5`. L3 runs
    # against build.nvidia.com instead (see agent/model.py / ARCHITECTURE.md).
    model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    def sha256(self) -> str:
        """LLD §10's `PlumbConfig.sha256()` shape -- the manifest's
        `engine_config_sha256`. Field order is fixed by the model
        definition, so the digest is stable across runs."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
