#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXIT_CODE=0

JSON_FILES=(
  "$ROOT_DIR/env/target.json"
  "$ROOT_DIR/env/tool_versions.json"
  "$ROOT_DIR/harness/constants.json"
  "$ROOT_DIR/harness/result_schema.json"
  "$ROOT_DIR/tasks/sum_u32_le/spec.json"
  "$ROOT_DIR/tasks/sum_u32_le/tests.json"
  "$ROOT_DIR/tasks/hex_encode/spec.json"
  "$ROOT_DIR/tasks/hex_encode/tests.json"
  "$ROOT_DIR/tasks/parse_u32_decimal/spec.json"
  "$ROOT_DIR/tasks/parse_u32_decimal/tests.json"
)

for file in "${JSON_FILES[@]}"; do
  if python3 - "$file" <<'PY'
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    json.load(f)
PY
  then
    echo "$file OK"
  else
    echo "$file FAIL"
    EXIT_CODE=1
  fi
done

python3 "$ROOT_DIR/harness/discover_toolchain.py"
DISCOVER_EXIT=$?
if [ "$DISCOVER_EXIT" -ne 0 ]; then
  EXIT_CODE=$DISCOVER_EXIT
fi

python3 "$ROOT_DIR/harness/generate_run_config.py"
GEN_EXIT=$?
if [ "$GEN_EXIT" -ne 0 ]; then
  EXIT_CODE=$GEN_EXIT
fi

echo "$ROOT_DIR/env/tool_versions.json"
echo "$ROOT_DIR/env/run_config.default.json"
echo "$ROOT_DIR/env/target.json"

exit "$EXIT_CODE"
