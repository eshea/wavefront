#!/usr/bin/env bash
# loop/harness.sh — run all loop tests, report pass/fail summary.
#
# Tests live in loop/tests/*.sh. Each test is a standalone script that
# exits 0 on pass, non-zero on fail. The harness runs them in
# alphabetical order, captures output, and prints a summary.
#
# Usage:
#   ./loop/harness.sh              # run everything
#   ./loop/harness.sh score_smoke  # run just one test by basename
set -u
cd "$(dirname "$0")/.."

if [ "$#" -gt 0 ]; then
  tests=$(printf '%s\n' "$@" | sed 's|^|loop/tests/|; s|$|.sh|')
else
  tests=$(ls loop/tests/*.sh 2>/dev/null | sort)
fi

if [ -z "$tests" ]; then
  echo "no tests found in loop/tests/"
  exit 0
fi

ok=0; fail=0; failed_names=""
for t in $tests; do
  name=$(basename "$t" .sh)
  printf '\n══ %-30s ' "$name"
  printf '═%.0s' $(seq 1 40)
  printf '\n'
  if bash "$t"; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
    failed_names="$failed_names $name"
  fi
done

printf '\n══════════════════════════════════════════════════════════════════\n'
printf ' HARNESS SUMMARY · passed=%d failed=%d\n' "$ok" "$fail"
if [ "$fail" -gt 0 ]; then
  printf ' failed:%s\n' "$failed_names"
fi
printf '══════════════════════════════════════════════════════════════════\n'

exit "$fail"
