# Plumb — the commands CLAUDE.md lists. `make reproduce` is the one a
# panelist runs on a fresh clone: no API key, committed seeds, prints
# every headline number.

SEED    ?= 42
CONFIG  ?= configs/config_b.yaml
BATCH   ?= data/batch_main_200
LABEL   ?= HELD_OUT

.PHONY: reproduce test determinism gen clean

reproduce: ## fresh clone, no API key -> both ablation arms scored, metrics printed
	uv sync --locked
	uv run plumb-gen --seed $(SEED) --config $(CONFIG) --out $(BATCH) --tier T2
	uv run plumb run --data $(BATCH) --ablation rules_only --model-mode replay \
	  --sample-label $(LABEL) --seed $(SEED) --generator-config $(CONFIG)
	@RID=$$(ls -t reports | head -1); \
	  uv run plumb-eval --run reports/$$RID --truth $(BATCH)/truth --allow-provisional; \
	  echo; echo "=== rules_only ==="; cat reports/$$RID/metrics.md
	@if [ -n "$$(ls fixtures/llm/*.json 2>/dev/null)" ]; then \
	  uv run plumb run --data $(BATCH) --ablation hybrid --model-mode replay \
	    --sample-label $(LABEL) --seed $(SEED) --generator-config $(CONFIG); \
	  RID=$$(ls -t reports | head -1); \
	  uv run plumb-eval --run reports/$$RID --truth $(BATCH)/truth --allow-provisional; \
	  echo; echo "=== hybrid (replayed from fixtures/llm/) ==="; cat reports/$$RID/metrics.md; \
	else \
	  echo; echo "=== hybrid: skipped -- no cassettes under fixtures/llm/. See docs/RUN_HYBRID.md ==="; \
	fi

test: ## the full suite (offline, no key)
	uv run pytest

determinism: ## L1 determinism harness -- 5 runs, hash comparison, asserts 1.000
	uv run pytest tests/plumb/match/test_determinism_harness.py -q

gen: ## generate the held-out batch
	uv run plumb-gen --seed $(SEED) --config $(CONFIG) --out $(BATCH) --tier T2

clean:
	rm -rf data reports
