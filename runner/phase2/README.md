# Phase 2 Runner - Step A + Step B + Step C + Step D

This module provides the Phase 2 Step A skeleton for Experiment 1.

Step A/Step B/Step C/Step D behavior:
- Loads frozen artifacts (tool snapshot, limits, schema, and test vectors).
- Discovers candidate `.ll` deterministically using explicit `--candidate`.
- Recovers authoritative `candidate_id` / `run_id` rules using repo evidence precedence:
  - explicit Phase 0/1 derivation rules if present
  - otherwise `irx/experiment1/runs/*/*.json` + `work/candidate.ll` evidence
- If a rule cannot be recovered, requires authoritative fallback CLI values:
  - `--candidate-id` and/or `--run-id`
- Emits seven Phase 2 run stages in NOT_RUN form when IDs are available:
  - `precheck`, `llvm_as_parse`, `opt_verify`, `lli_tests`, `llc_compile`, `clang_link`, `native_tests`
- Enforces Step B precheck limits from frozen Phase 0 limits:
  - `max_ll_bytes`
  - `max_ll_lines`
  using deterministic line counting:
  - line_count = number of `\\n` bytes + 1 when non-empty and not newline-terminated
  - line_count = 0 when empty
- Copies the candidate byte-for-byte to `irx/experiment1/runs/<candidate_id>/<run_id>/work/candidate.ll`.
- Executes Step C `llvm-as` parse gate using frozen tool path and limits:
  - tool path: `env/tool_versions.json` → `detected.llvm-as.path`
  - limits: `harness/constants.json` → `limits.timeout_stage_ms`, `limits.max_rss_mib`
  - invocation in work dir: `llvm-as -o candidate.bc candidate.ll`
  - deterministic environment: `LC_ALL=C`, `LANG=C`, `TZ=UTC`
- Executes Step D `opt -verify` gate (only if precheck + parse succeeded and `candidate.bc` exists):
  - tool path: `env/tool_versions.json` → `detected.opt.path` (or `detected.llvm-opt.path` if present)
  - limits: `harness/constants.json` → `limits.timeout_stage_ms`, `limits.max_rss_mib`
  - invocation in work dir: `opt -verify -disable-output candidate.bc`
  - deterministic environment: `LC_ALL=C`, `LANG=C`, `TZ=UTC`
- Emits a schema-validated result to `irx/experiment1/runs/<candidate_id>/<run_id>.json`.

No LLVM tools are executed in Step A.

## Run Step A

Run from repository root:

```bash
python3 runner/phase2/phase2_runner.py --candidate /path/to/candidate.ll
```

Authoritative fallback (only if inference cannot recover a rule):

```bash
python3 runner/phase2/phase2_runner.py --candidate /path/to/candidate.ll --candidate-id <id> --run-id <id>
```

## Determinism Check

Run Step A twice on the same candidate.
- Outputs should match except `timestamps.started_at` and `timestamps.finished_at`.

## Precheck Test Cases

Run under-limit case:

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand_under.ll
```

Run over-bytes case (> `max_ll_bytes`):

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand_over_bytes.ll
```

Run over-lines case (> `max_ll_lines`):

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand_over_lines.ll
```

Run parse-fail case (invalid IR syntax):

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand_invalid.ll
```

Run verify-fail case (IR that parses but fails `opt -verify`):

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand_verify_fail.ll
```
