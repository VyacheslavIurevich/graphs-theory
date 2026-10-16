#!/usr/bin/env bash
# One-shot reproduction of the task1 LAGraph/CPU vs spla/GPU runs.
#
# Usage (from anywhere):
#   bash task1/run_all_benchmarks.sh
#
# Optional env:
#   TASK1_OUTPUT=/path     # results directory (default: task1/results/run-<UTC stamp>)
#   OMP_NUM_THREADS=8      # OpenMP threads for LAGraph; default 8
#
# Prepare the stand before measuring:
#   sudo bash common/prepare.sh setup
#
# Implementations are the two backends of the experiment, each in its own
# spla-bench process so profiling is not shared:
#   spla     host flamegraph; GPU times come from the spla binary
#   lagraph  perf hardware counters and a flamegraph

set -euo pipefail

TASK1="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$TASK1/results"
REPO="$(cd "$TASK1/.." && pwd)"
BENCH="$TASK1/spla-bench"
BENCHMARK="$BENCH/scripts/benchmark.py"

if [[ ! -f "$BENCHMARK" ]]; then
  echo "[run_all] initializing spla-bench submodule"
  git -C "$REPO" submodule update --init -- task1/spla-bench
fi

if [[ ! -f "$BENCHMARK" ]]; then
  echo "[run_all] missing $BENCHMARK" >&2
  exit 1
fi

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="${TASK1_OUTPUT:-$RESULTS_DIR/run-$STAMP}"
mkdir -p "$OUT"

if [[ "$OUT" == "$RESULTS_DIR"/* ]]; then
  ln -sfn "${OUT#"$RESULTS_DIR"/}" "$RESULTS_DIR/recent"
fi

echo "[run_all] output=$OUT"
echo "[run_all] benchmark=$BENCHMARK"
echo "[run_all] OMP_NUM_THREADS=$OMP_NUM_THREADS"

run_case() {
  local tool="$1"
  local algo="$2"
  shift 2
  local dest="$OUT/${algo}-${tool}"
  mkdir -p "$dest"
  echo "[run_all] tool=$tool algo=$algo -> $dest"
  python3 "$BENCHMARK" \
    --tool "$tool" \
    --algo "$algo" \
    --output "$dest" \
    --printer all \
    --format txt \
    "$@" \
    2>&1 | tee "$dest/log.log"
}

algos=(bfs sssp tc pr)
for algo in "${algos[@]}"; do
  run_case spla "$algo" --flamegraph
  run_case lagraph "$algo" --cpu-profile --flamegraph
done

echo "[run_all] done: $OUT"
