#!/bin/bash
# Run every offline check. Exit 0 only when all four pass.
#   bash tests/run_all.sh            (PYTHON=/path/to/python3 to choose the interpreter; it needs `requests`)
cd "$(dirname "$0")/.." || exit 2
PY="${PYTHON:-python3}"
fail=0
for t in test_settings test_gates test_census test_weekly; do
  out=$("$PY" "tests/$t.py" 2>&1); rc=$?
  n=$(printf '%s\n' "$out" | grep -c '^ok ')
  bad=$(printf '%s\n' "$out" | grep -c '^FAIL ')
  if [ "$rc" -eq 0 ] && [ "$bad" -eq 0 ]; then
    echo "PASS  $t ($n checks)"
  else
    echo "FAIL  $t (exit $rc, $bad failed of $((n + bad)))"
    printf '%s\n' "$out" | grep -v '^ok ' | tail -15
    fail=1
  fi
done
[ "$fail" -eq 0 ] && echo "RESULT: all four pass" || echo "RESULT: FAILED"
exit "$fail"
