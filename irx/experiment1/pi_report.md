# IR Experiments - Experiment 1 - Raspberry Pi Validation Report

**Date**: 2026-02-15
**Platform**: Raspberry Pi 5
**OS**: Raspberry Pi OS 64-bit (Debian-based)
**Kernel**: Linux 6.12.47+rpt-rpi-2712
**Architecture**: aarch64 (ARM64)

---

## Executive Summary

This report documents the successful completion of Phase 1 toolchain discovery and environment capture for IR Experiments - Experiment 1 on a Raspberry Pi 5 running 64-bit Raspberry Pi OS. All required LLVM toolchain components were verified, environment artifacts were generated, and the system is validated for proceeding to Phase 2 execution.

---

## 1. Environment Overview

### 1.1 Hardware Platform

The target system is a Raspberry Pi 5 with the following characteristics:

- **CPU**: ARM Cortex-A76 (quad-core)
- **Architecture**: AArch64 (64-bit ARM)
- **Instruction Set**: ARMv8-A

### 1.2 Operating System

- **Distribution**: Raspberry Pi OS (Debian-based)
- **Kernel Version**: 6.12.47+rpt-rpi-2712
- **Target Triple**: `aarch64-unknown-linux-gnu`

### 1.3 Purpose

This environment serves as the authoritative target platform for IR Experiments. The Raspberry Pi was selected for its:

1. Deterministic hardware behavior
2. Native ARM64 architecture support
3. Full LLVM toolchain availability
4. Reproducible environment characteristics

---

## 2. Toolchain Discovery Results

### 2.1 Required Binaries

Phase 1 requires the following LLVM toolchain components:

| Binary | Purpose |
|--------|---------|
| `llvm-as` | LLVM assembler - converts .ll to .bc |
| `opt` | LLVM optimizer - runs optimization passes |
| `lli` | LLVM interpreter - executes bitcode directly |
| `llc` | LLVM static compiler - generates native code |
| `clang` | C/C++ frontend - generates LLVM IR |

### 2.2 Detection Results

All required binaries were successfully detected:

#### llvm-as
- **Status**: OK
- **Path**: `/usr/lib/llvm-19/bin/llvm-as`
- **Version**: Debian LLVM version 19.1.7 (Optimized build)

#### opt
- **Status**: OK
- **Path**: `/usr/lib/llvm-19/bin/opt`
- **Version**: Debian LLVM version 19.1.7 (Optimized build)
- **Default Target**: aarch64-unknown-linux-gnu
- **Host CPU**: cortex-a76

#### lli
- **Status**: OK
- **Path**: `/usr/lib/llvm-19/bin/lli`
- **Version**: Debian LLVM version 19.1.7 (Optimized build)

#### llc
- **Status**: OK
- **Path**: `/usr/lib/llvm-19/bin/llc`
- **Version**: Debian LLVM version 19.1.7 (Optimized build)
- **Default Target**: aarch64-unknown-linux-gnu
- **Host CPU**: cortex-a76
- **Registered Targets**: 47 architectures including aarch64, arm64, x86, x86-64, riscv32, riscv64, wasm32, wasm64

#### clang
- **Status**: OK
- **Path**: `/usr/lib/llvm-19/bin/clang`
- **Version**: Debian clang version 19.1.7 (3+b1)
- **Target**: aarch64-unknown-linux-gnu
- **Thread Model**: posix
- **Installed Directory**: /usr/lib/llvm-19/bin

### 2.3 LLVM Version Summary

All toolchain components are from **LLVM 19.1.7** (Debian package), ensuring version consistency across the entire toolchain. This is critical for deterministic IR generation and execution.

---

## 3. Configuration Artifacts

### 3.1 Generated Files

Phase 1 generated the following configuration artifacts:

| File | Purpose |
|------|---------|
| `env/tool_versions.json` | Captured toolchain paths and versions |
| `env/run_config.default.json` | Default execution configuration |
| `env/target.json` | Target platform metadata |

### 3.2 Run Configuration

The generated `run_config.default.json` specifies:

```json
{
  "experiment": "1",
  "target_triple": "aarch64-unknown-linux-gnu",
  "limits": {
    "max_ll_bytes": 65536,
    "max_ll_lines": 2000,
    "max_basic_blocks": 200,
    "max_instructions": 20000,
    "max_alloca_bytes_total": 4096,
    "timeout_stage_ms": 1000,
    "timeout_per_test_ms": 50,
    "max_rss_mib": 64,
    "max_input_bytes": 65536,
    "max_output_bytes": 65536
  },
  "modes": {
    "lli_enabled": true,
    "native_enabled": true,
    "sanitizer_enabled": false,
    "fuzz_enabled": false
  },
  "determinism": {
    "clear_env": true,
    "cwd_mode": "run_dir",
    "seed_source": "candidate_id"
  },
  "logging": {
    "capture_stdout": true,
    "capture_stderr": true
  }
}
```

### 3.3 Execution Modes

| Mode | Status | Description |
|------|--------|-------------|
| lli_enabled | Enabled | LLVM interpreter execution |
| native_enabled | Enabled | Native code compilation and execution |
| sanitizer_enabled | Disabled | Address/memory sanitizers |
| fuzz_enabled | Disabled | Fuzzing mode |

---

## 4. Validation Checks

### 4.1 Phase 1 Check Script

The `phase1_check.sh` script was executed to validate the environment:

```bash
bash irx/experiment1/phase1_check.sh
```

### 4.2 Validation Results

All validation checks passed:

| Check | Status |
|-------|--------|
| env/target.json | OK |
| env/tool_versions.json | OK |
| harness/constants.json | OK |
| harness/result_schema.json | OK |
| tasks/sum_u32_le/spec.json | OK |
| tasks/sum_u32_le/tests.json | OK |
| tasks/hex_encode/spec.json | OK |
| tasks/hex_encode/tests.json | OK |
| tasks/parse_u32_decimal/spec.json | OK |
| tasks/parse_u32_decimal/tests.json | OK |

**Exit Code**: 0 (Success)

---

## 5. Task Specifications

### 5.1 Available Tasks

Three tasks are defined for Experiment 1:

| Task | Description |
|------|-------------|
| `sum_u32_le` | Sum unsigned 32-bit integers (little endian) |
| `hex_encode` | Encode binary data as hexadecimal |
| `parse_u32_decimal` | Parse decimal string to unsigned 32-bit integer |

### 5.2 Task Structure

Each task contains:
- `spec.json` - Function signature, ABI, and constraints
- `tests.json` - Test vectors for validation

---

## 6. Resource Limits

The harness enforces the following limits for deterministic execution:

| Limit | Value | Unit |
|-------|-------|------|
| Max LL file size | 65,536 | bytes |
| Max LL lines | 2,000 | lines |
| Max basic blocks | 200 | blocks |
| Max instructions | 20,000 | instructions |
| Max alloca total | 4,096 | bytes |
| Stage timeout | 1,000 | ms |
| Per-test timeout | 50 | ms |
| Max RSS | 64 | MiB |
| Max input size | 65,536 | bytes |
| Max output size | 65,536 | bytes |

---

## 7. Installation Notes

### 7.1 LLVM Package

The LLVM 19 toolchain was installed via Debian packages. The binaries are located in `/usr/lib/llvm-19/bin/`.

### 7.2 PATH Configuration

Symlinks were created in `/usr/local/bin/` to make the LLVM tools accessible system-wide:

```bash
sudo ln -s /usr/lib/llvm-19/bin/{llvm-as,opt,lli,llc} /usr/local/bin/
```

This ensures consistent tool resolution across all execution contexts.

---

## 8. Conclusions

### 8.1 Phase 1 Status

**PASSED** - All Phase 1 requirements have been satisfied:

1. All required LLVM binaries are present and functional
2. Toolchain versions are consistent (LLVM 19.1.7)
3. Target triple matches expected value (aarch64-unknown-linux-gnu)
4. Environment artifacts have been generated
5. All frozen assets validate successfully

### 8.2 Readiness for Phase 2

The Raspberry Pi environment is fully validated and ready for Phase 2 execution. The following preconditions are met:

- Deterministic toolchain state captured
- Run configuration generated with appropriate limits
- Task specifications and test vectors in place
- Harness constants and result schema frozen

### 8.3 Recommendations

1. **Proceed to Phase 2** - The environment is validated for candidate execution
2. **Preserve tool_versions.json** - This artifact documents the exact toolchain state
3. **Monitor resource usage** - The 64 MiB RSS limit is appropriate for Pi constraints
4. **Use lli mode first** - Interpreter mode provides faster iteration than native compilation

---

## Appendix A: File Manifest

```
irx/experiment1/
├── README.md
├── pi_report.md (this file)
├── phase1_check.sh
├── env/
│   ├── target.json
│   ├── tool_versions.json
│   └── run_config.default.json
├── harness/
│   ├── constants.json
│   ├── result_schema.json
│   ├── discover_toolchain.py
│   └── generate_run_config.py
├── tasks/
│   ├── sum_u32_le/
│   │   ├── spec.json
│   │   └── tests.json
│   ├── hex_encode/
│   │   ├── spec.json
│   │   └── tests.json
│   └── parse_u32_decimal/
│       ├── spec.json
│       └── tests.json
├── candidates/ (empty, reserved)
└── runs/ (empty, reserved)
```

---

## Appendix B: Verification Commands

To re-verify the environment at any time:

```bash
# Run Phase 1 check
bash irx/experiment1/phase1_check.sh
echo $?  # Should print 0

# Verify tool versions
cat irx/experiment1/env/tool_versions.json

# Verify run configuration
cat irx/experiment1/env/run_config.default.json

# Test LLVM tools directly
llvm-as --version
opt --version
lli --version
llc --version
clang --version
```

---

*Report generated on Raspberry Pi 5 running Raspberry Pi OS 64-bit*
