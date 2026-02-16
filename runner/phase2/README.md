# Phase 2 Runner - Step A + Step B + Step C + Step D + Step E + Step F

This module provides the Phase 2 Step A..F skeleton for Experiment 1.

Step A/Step B/Step C/Step D/Step E/Step F behavior:
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
- Adds Step E `lli_tests` gate precedence:
  - runs only when `precheck`, `llvm_as_parse`, and `opt_verify` all pass and `work/candidate.bc` exists and is non-empty
  - frozen `lli` path from `env/tool_versions.json` (`detected.lli.path`, fallback `detected.llvm-lli.path`)
  - per-test limits loaded from `harness/constants.json` keys:
    - `limits.timeout_per_test_ms`
    - `limits.max_rss_mib`
  - if Stage 4 preconditions fail, `lli_tests` remains NOT_RUN
  - if `lli` path is missing/not executable and Stage 4 is eligible, `lli_tests` is recorded as failure with `POLICY_VIOLATION`
  - ABI invocation mechanism is not guessed; deterministic repo-wide discovery is used:
    - search order: `irx/experiment1/harness/` first, then `irx/experiment1/`
    - `irx/experiment1/runs/` is excluded from discovery
    - deterministic failure detail includes searched dirs/patterns and capped inspected-file sample
  - if schema lacks explicit per-test result container, Stage 4 fails deterministically with `ERR_INTERNAL(-3)` detail in artifact
- Adds Step F `llc_compile` gate precedence:
  - runs only when `precheck`, `llvm_as_parse`, `opt_verify`, and `lli_tests` all pass and `work/candidate.bc` exists and is non-empty
  - frozen `llc` path from `env/tool_versions.json` (`detected.llc.path`, fallback `detected.llvm-llc.path`)
  - output artifact in work dir: `candidate.o`
  - deterministic invocation: `llc -filetype=obj -mtriple=<target_triple> -O0 -o candidate.o candidate.bc`
  - deterministic environment and resource controls reuse shared LLVM runtime helpers (`LC_ALL/LANG/TZ`, derived `LD_LIBRARY_PATH` only, RSS-only preexec)
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

Step E precedence check (current host where `llvm-as` may be non-executable):

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/valid.ll
```

Step E harness discovery self-check (does not execute LLVM tools):

```bash
python3 runner/phase2/phase2_runner.py --probe-harness
```
