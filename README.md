# IR Experiments

IR Experiments is a repository for structured, repeatable intermediate-representation (IR) research workflows. It is organized to keep each experiment self-contained, with frozen inputs, clear phase boundaries, and dedicated documentation so results can be reproduced consistently.

## Repository Structure

The repository groups experiment work under `irx/`, with each experiment in its own directory.

- `irx/experiment1/` — Experiment 1 workspace, including environment metadata, task definitions, harness artifacts, and experiment-specific documentation.
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
