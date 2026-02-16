#!/usr/bin/env bash
# Step H evidence check — reproduces and summarises the full A-H run.
# Usage: bash irx/experiment1/verification/evidence/step_h_check.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
CANDIDATE="$REPO_ROOT/irx/experiment1/verification/step_f/sum_u32_le_good.ll"
RUNNER="$REPO_ROOT/runner/phase2/phase2_runner.py"

echo "=== Step H Evidence Check ==="
echo "repo: $REPO_ROOT"

# Clean previous runs
rm -rf "$REPO_ROOT/irx/experiment1/runs/"*

# Syntax check
python3 -m py_compile "$RUNNER"
echo "py_compile: OK"

# Run pipeline
python3 "$RUNNER" --candidate "$CANDIDATE" --task sum_u32_le \
  1>/tmp/exp1_steph_out.txt 2>/tmp/exp1_steph_err.txt
echo "runner exit: $?"

# Tool env lines
grep -E "^\[(llvm-as|opt|lli|llc|clang|native_harness)\]" /tmp/exp1_steph_err.txt || true

# Locate result JSON
RESULT_PATH=$(python3 -c "
import sys, json
text = open('/tmp/exp1_steph_out.txt').read()
idx = text.index('{')
last = text.rindex('}')
s = json.loads(text[idx:last+1])
print(s['result_json'])
")

echo ""
echo "--- Summary ---"
python3 - "$RESULT_PATH" <<'PYEOF'
import json, sys, os
with open(sys.argv[1]) as f:
    r = json.load(f)
print(f"candidate_id: {r['candidate_id']}")
print(f"run_id:       {r['run_id']}")
print()
for run in r['runs']:
    ec = run.get('exit_code')
    ec_s = f"exit={ec}" if ec is not None else "not_run"
    print(f"  {run['stage']:20s} ok={str(run['ok']):5s}  {ec_s}")
print()
m = r['metrics']
print(f"lli tests:    {m['tests_passed']}/{m['tests_total']} passed, {m['tests_failed']} failed")
print(f"native tests: {m['native_tests_passed']}/{m['native_tests_total']} passed, {m['native_tests_failed']} failed")
print()
work = os.path.join(os.path.dirname(sys.argv[1]), r['run_id'], 'work')
obj = os.path.join(work, 'candidate.o')
exe = os.path.join(work, 'candidate.exe')
if os.path.isfile(obj):
    print(f"candidate.o:   EXISTS ({os.path.getsize(obj)} bytes)")
else:
    print("candidate.o:   NOT_PRESENT")
if os.path.isfile(exe):
    print(f"candidate.exe: EXISTS ({os.path.getsize(exe)} bytes)")
else:
    print("candidate.exe: NOT_PRESENT")
print()

# Verify lli and native results match
lli = r.get('test_results', [])
native = r.get('native_test_results', [])
if len(lli) == len(native) and len(lli) > 0:
    all_match = all(
        lli[i]['outcome'] == native[i]['outcome']
        and lli[i]['actual_ret'] == native[i]['actual_ret']
        and lli[i]['actual_out_hex'] == native[i]['actual_out_hex']
        for i in range(len(lli))
    )
    if all_match:
        print(f"lli/native match: ALL {len(lli)} tests agree")
    else:
        print("lli/native match: MISMATCH DETECTED")
else:
    print(f"lli/native match: SKIPPED (lli={len(lli)}, native={len(native)})")
PYEOF

echo ""
echo "=== Done ==="
