# IR Experiments - Experiment 1 - Phase 0

This directory contains only the deterministic Phase 0 scaffold for Experiment 1.
Execution logic is intentionally not implemented yet.

## Layout

- `env/`: frozen target metadata and tool version placeholder files.
- `tasks/`: task specifications and fixed test vectors.
  - `tasks/sum_u32_le/`: `spec.json`, `tests.json`
  - `tasks/hex_encode/`: `spec.json`, `tests.json`
  - `tasks/parse_u32_decimal/`: `spec.json`, `tests.json`
- `harness/`: frozen shared constants and result schema.
- `candidates/`: empty directory reserved for submitted candidates.
- `runs/`: empty directory reserved for run artifacts.

## Frozen Assets

- ABI and limits: `harness/constants.json`
- Task specs and vectors: `tasks/*/spec.json`, `tasks/*/tests.json`
- Result shape contract: `harness/result_schema.json`
