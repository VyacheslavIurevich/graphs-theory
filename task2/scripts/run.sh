#!/usr/bin/env bash
# One-shot D-Galois scaling run (40 GiB, 8 threads).
#
# Usage (from anywhere):
#   bash task2/scripts/run.sh
#
# Optional env:
#   TASK2_NODES=1,2,4,8        # P=8 oversubscribes 16 threads onto 8 HW threads
#   TASK2_DATASETS=all         # or large / default / comma-separated names
#   TASK2_TIMEOUT=14400        # seconds per DistBench process (4 h)
#   TASK2_OUTPUT=/path         # results directory
#   TASK2_RESUME=1             # skip ok points in TASK2_OUTPUT/report.json
#
set -uo pipefail

TASK2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$TASK2/.." && pwd)"
cd "$TASK2" || exit

unset APPDIR APPIMAGE OWD ARGV0 || true

if [[ ! -f deps/Galois/CMakeLists.txt ]]; then
  echo "[task2] initializing Galois submodule"
  git -C "$REPO" submodule update --init task2/deps/Galois
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="${TASK2_OUTPUT:-$TASK2/results/$STAMP}"
mkdir -p "$OUT"

NODES="${TASK2_NODES:-1,2,4,8}"
DATASETS="${TASK2_DATASETS:-all}"
TIMEOUT="${TASK2_TIMEOUT:-14400}"
RESUME_FLAG=()
if [[ "${TASK2_RESUME:-}" == "1" || "${TASK2_RESUME:-}" == "yes" ]]; then
  RESUME_FLAG=(--resume)
elif [[ -f "$OUT/report.json" && "${TASK2_RESUME:-}" != "0" ]]; then
  # Continuing into an existing results dir: do not redo 1/2/4 by accident.
  RESUME_FLAG=(--resume)
fi

echo "[task2] task2=$TASK2"
echo "[task2] output=$OUT"
echo "[task2] datasets=$DATASETS nodes=$NODES timeout=$TIMEOUT resume=${RESUME_FLAG[*]:-no}"
echo "[task2] log=$OUT/console.log"

{
  echo "===== task2 $STAMP ====="
  echo "repo=$REPO"
  echo "task2=$TASK2"
  echo "nodes=$NODES resume=${RESUME_FLAG[*]:-no}"
  date -u
  nproc || true
  free -h || true
  echo "============================"
} >>"$OUT/console.log"

set +e
python3 scripts/benchmark.py build 2>&1 | tee -a "$OUT/console.log"
BUILD_RC=${PIPESTATUS[0]}
if [[ "$BUILD_RC" -ne 0 ]]; then
  echo "[task2] BUILD FAILED rc=$BUILD_RC" | tee -a "$OUT/console.log"
  echo "[task2] logs: $OUT/console.log"
  exit "$BUILD_RC"
fi

python3 scripts/benchmark.py prepare --profile full --dataset "$DATASETS" \
  2>&1 | tee -a "$OUT/console.log"
PREP_RC=${PIPESTATUS[0]}
if [[ "$PREP_RC" -ne 0 ]]; then
  echo "[task2] PREPARE FAILED rc=$PREP_RC" | tee -a "$OUT/console.log"
  echo "[task2] partial logs: $OUT/console.log"
  exit "$PREP_RC"
fi

python3 scripts/benchmark.py run \
  --profile full \
  --dataset "$DATASETS" \
  --nodes "$NODES" \
  --timeout "$TIMEOUT" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  2>&1 | tee -a "$OUT/console.log"
RUN_RC=${PIPESTATUS[0]}

echo
echo "[task2] finished rc=$RUN_RC"
echo "[task2] results: $OUT"
exit "$RUN_RC"
