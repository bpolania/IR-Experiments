# Frozen LLI Shim Contract

This directory defines the authoritative ABI bridge for Experiment 1 under `lli`.

## Frozen ABI

Candidate must export exactly:

`i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)`

Equivalent C declaration used by the shim:

`int64_t f(uint8_t* in_ptr, int32_t in_len, uint8_t* out_ptr, int32_t out_cap);`

## Deterministic Build Inputs/Outputs

Input source:
- `irx/experiment1/harness/lli_shim/shim.c`

Output artifact expected by `lli_abi_runner.py`:
- `irx/experiment1/harness/lli_shim/shim.bc`

Deterministic build command (run in repo root, not auto-run in this revision):

`clang -O0 -emit-llvm -c irx/experiment1/harness/lli_shim/shim.c -o irx/experiment1/harness/lli_shim/shim.bc`

The Phase 0/1 authority revision defines this contract and location only. It does not auto-build the shim.
