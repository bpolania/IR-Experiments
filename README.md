# IR Experiments

IR Experiments is a repository for structured, repeatable intermediate-representation (IR) research workflows. It is organized to keep each experiment self-contained, with frozen inputs, clear phase boundaries, and dedicated documentation so results can be reproduced consistently.

## Raspberry Pi (ARM64) execution notes (Experiment 1)

This repo is designed to run deterministically against a frozen toolchain snapshot. On Raspberry Pi (ARM64), you must ensure the LLVM tool paths match the snapshot in:

- `irx/experiment1/env/tool_versions.json`

### Required tools (Pi, ARM64)

You need these executables available and executable at the exact absolute paths referenced in `tool_versions.json`:

- `llvm-as`
- `opt`
- `lli`
- (later phases) `llc`, `clang`

If your system installs LLVM under different paths, you must either:
- install LLVM so the binaries exist at the snapshot paths, or
- update `tool_versions.json` only if you are explicitly revising the toolchain snapshot (authority change).

### Quick preflight on Pi

From repo root:

```bash
python3 -m py_compile runner/phase2/phase2_runner.py
python3 -m py_compile irx/experiment1/harness/lli_abi_runner.py
python3 runner/phase2/phase2_runner.py --probe-harness
```

### Build the frozen lli shim (required for Phase 2 Step E)

The ABI harness expects a shim bitcode module (`shim.bc`) built from:
- `irx/experiment1/harness/lli_shim/shim.c`

Build on Pi using the frozen toolchain (paths must match `tool_versions.json`):

```bash
cd irx/experiment1/harness/lli_shim

# Use clang from the frozen snapshot path if available; otherwise use the system clang
# ONLY if it matches the intended snapshot (authority).
/usr/lib/llvm-19/bin/clang -O0 -S -emit-llvm shim.c -o shim.ll
/usr/lib/llvm-19/bin/llvm-as shim.ll -o shim.bc

ls -l shim.bc
```

Do not change the shim source or ABI without an authority revision.

### Running Phase 2 runner (current incremental gates)

Phase 2 runner emits artifacts under:
- `irx/experiment1/runs/<candidate_id>/<run_id>.json`
- `irx/experiment1/runs/<candidate_id>/<run_id>/work/`

Example:

```bash
python3 runner/phase2/phase2_runner.py --candidate /tmp/cand.ll
```

The runner is artifact-first: even when a gate fails (missing tool, parse/verify failure, etc.), it should still emit a schema-valid result JSON.

## Repository Structure

The repository groups experiment work under `irx/`, with each experiment in its own directory.

- `irx/experiment1/` — Experiment 1 workspace, including environment metadata, task definitions, harness artifacts, and experiment-specific documentation.
- `irx/experiment1/harness/id_rules.json` — Frozen authoritative candidate/run ID derivation rules for Experiment 1.
- `irx/experiment1/env/` — Target and toolchain capture artifacts.
- `irx/experiment1/tasks/` — Task specs and test vectors.
- `irx/experiment1/harness/` — Shared constants, schemas, and phase scripts.
- `irx/experiment1/candidates/` and `irx/experiment1/runs/` — Reserved for candidate inputs and run outputs.

## Experiments

- `irx/experiment1/` — Deterministic IR experiment pipeline with phased setup and validation artifacts.

## Getting Started

1. Read this root README to understand how the repository is organized.
2. Choose the experiment directory you want to work with.
3. Open that experiment’s `README.md` and follow its phase-specific instructions.
4. Use the experiment’s own docs as the source of truth for setup, validation, and expected outputs.

## Documentation

- Root overview: `README.md`
- Experiment 1 details: `irx/experiment1/README.md`

Each experiment directory is expected to document:
- scope and objectives,
- phase-by-phase workflow,
- required artifacts and validation steps.

## Navigation Guide

- Start at: `irx/`
- Then select: `irx/experiment1/`
- For implementation details, always defer to the experiment-level `README.md`.

## Contributing

When adding new work, place it in the appropriate experiment directory (or create a new `irx/experimentN/` folder) and include a clear experiment-level `README.md` describing goals, structure, and usage.
