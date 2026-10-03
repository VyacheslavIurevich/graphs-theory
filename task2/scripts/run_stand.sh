#!/usr/bin/env bash
# One-shot D-Galois scaling run for the task1 stand (40 GiB, 8 threads).
#
# Usage (from anywhere):
#   bash task2/scripts/run_stand.sh
#
# Optional env:
#   TASK2_NODES=1,2,4,6        # default; P=6 needs --use-hwthread-cpus (in run.py)
#   TASK2_DATASETS=all         # or large / default / comma-separated names
#   TASK2_TIMEOUT=21600        # seconds per DistBench process
#   TASK2_OUTPUT=/path         # results directory
#   TASK2_RESUME=1             # skip ok points in TASK2_OUTPUT/report.json
#
# Copy the printed results directory back for analysis.

set -uo pipefail

TASK2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$TASK2/.." && pwd)"
cd "$TASK2" || exit

unset APPDIR APPIMAGE OWD ARGV0 || true

if [[ ! -f deps/Galois/CMakeLists.txt ]]; then
  echo "[run_stand] initializing Galois submodule"
  git -C "$REPO" submodule update --init task2/deps/Galois
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="${TASK2_OUTPUT:-$TASK2/results/stand-$STAMP}"
mkdir -p "$OUT"

NODES="${TASK2_NODES:-1,2,4,6}"
DATASETS="${TASK2_DATASETS:-all}"
TIMEOUT="${TASK2_TIMEOUT:-21600}"
RESUME_FLAG=()
if [[ "${TASK2_RESUME:-}" == "1" || "${TASK2_RESUME:-}" == "yes" ]]; then
  RESUME_FLAG=(--resume)
elif [[ -f "$OUT/report.json" && "${TASK2_RESUME:-}" != "0" ]]; then
  # Continuing into an existing stand dir: do not redo 1/2/4 by accident.
  RESUME_FLAG=(--resume)
fi

echo "[run_stand] task2=$TASK2"
echo "[run_stand] output=$OUT"
echo "[run_stand] datasets=$DATASETS nodes=$NODES timeout=$TIMEOUT resume=${RESUME_FLAG[*]:-no}"
echo "[run_stand] log=$OUT/console.log"

{
  echo "===== run_stand $STAMP ====="
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
  echo "[run_stand] BUILD FAILED rc=$BUILD_RC" | tee -a "$OUT/console.log"
  echo "[run_stand] logs: $OUT/console.log"
  exit "$BUILD_RC"
fi

python3 scripts/benchmark.py prepare --profile stand --dataset "$DATASETS" \
  2>&1 | tee -a "$OUT/console.log"
PREP_RC=${PIPESTATUS[0]}
if [[ "$PREP_RC" -ne 0 ]]; then
  echo "[run_stand] PREPARE FAILED rc=$PREP_RC" | tee -a "$OUT/console.log"
  echo "[run_stand] partial logs: $OUT/console.log"
  exit "$PREP_RC"
fi

python3 scripts/benchmark.py run \
  --profile stand \
  --dataset "$DATASETS" \
  --nodes "$NODES" \
  --timeout "$TIMEOUT" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  2>&1 | tee -a "$OUT/console.log"
RUN_RC=${PIPESTATUS[0]}

echo
echo "[run_stand] finished rc=$RUN_RC"
echo "[run_stand] Отдайте целиком каталог:"
echo "  $OUT"
echo "Внутри должны быть report.json, report.md, stand_info.txt,"
echo "console.log, WHAT_TO_SEND.txt и runs/."
exit "$RUN_RC"
