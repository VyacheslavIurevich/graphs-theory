#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run with root privileges (sudo)!"
  exit 1
fi

ACTION=$1
GPU_PATH="/sys/class/drm/card1"

UVX_BIN=""
for cand in "$HOME/.local/bin/uvx" /home/*/.local/bin/uvx; do
  if [ -x "$cand" ]; then
    UVX_BIN="$cand"
    break
  fi
done
if [ -z "$UVX_BIN" ] && command -v uvx >/dev/null 2>&1; then
  UVX_BIN="uvx"
fi
if [ -z "$UVX_BIN" ]; then
  echo "Error: uvx not found. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [ "$ACTION" == "setup" ]; then
  echo "=== 1. Stopping background services and disabling Swap ==="
  # Stop irqbalance so the kernel does not keep moving IRQs between CPUs.
  systemctl stop irqbalance 2>/dev/null || true
  # Stop thermald so it does not apply extra thermal policy during the run.
  systemctl stop thermald 2>/dev/null || true
  # Disable swap to avoid paging latency during measurements.
  swapoff -a
  echo "   Services irqbalance and thermald stopped. Swap disabled."

  # pyperf system tune: performance governor, min freq = max freq,
  # disable Turbo Boost, keep full ASLR, stop irqbalance, cap perf
  # sample rate at 1 Hz. It does not disable C-states or ASLR.
  echo "=== 2. Tuning CPU via pyperf ==="
  "$UVX_BIN" pyperf system tune

  echo "=== 3. Relaxing perf restrictions and freeing the PMU ==="
  sysctl -w kernel.perf_event_paranoid=-1
  sysctl -w kernel.kptr_restrict=0
  # NMI watchdog uses PMU counters and contends with perf.
  sysctl -w kernel.nmi_watchdog=0

  echo "=== 4. Locking Intel Iris Xe GPU frequency ==="
  if [ -f "$GPU_PATH/gt_RP1_freq_mhz" ]; then
    TARGET_FREQ=$(cat "$GPU_PATH/gt_RP1_freq_mhz")
    echo "   Locking GPU frequency at base ${TARGET_FREQ} MHz..."
    echo "$TARGET_FREQ" >"$GPU_PATH/gt_min_freq_mhz"
    echo "$TARGET_FREQ" >"$GPU_PATH/gt_max_freq_mhz"
    echo "$TARGET_FREQ" >"$GPU_PATH/gt_boost_freq_mhz"
  else
    echo "   [Warning] Path $GPU_PATH not found. Skipping GPU frequency configuration."
  fi

  echo "=== 5. Dropping OS page cache and compacting memory ==="
  # Drop page cache, dentries, and inodes. This does not flush CPU caches.
  sync
  echo 3 >/proc/sys/vm/drop_caches

  echo 1 >/proc/sys/vm/compact_memory 2>/dev/null || true

  # Best-effort pollution of CPU caches by touching 32 MB; not a guaranteed
  # L1/L2/L3 flush.
  python3 -c 'b = bytearray(32 * 1024 * 1024); b[:] = b"\x00" * len(b)' 2>/dev/null || true
  echo "   Page cache dropped, memory compacted, CPU caches polluted best-effort."

  echo ""
  echo "========================================================================="
  echo " Benchmarking testbed successfully prepared!"
  echo " Reminder: For best results, switch to TTY (Ctrl+Alt+F3)"
  echo " and stop GUI with: sudo systemctl isolate multi-user.target"
  echo "========================================================================="

elif [ "$ACTION" == "restore" ]; then
  echo "=== 1. Resetting CPU settings via pyperf ==="
  "$UVX_BIN" pyperf system reset

  echo "=== 2. Restoring perf sysctl defaults ==="
  sysctl -w kernel.perf_event_paranoid=2
  sysctl -w kernel.kptr_restrict=1
  sysctl -w kernel.nmi_watchdog=1

  echo "=== 3. Resetting Intel GPU frequency limits ==="
  if [ -f "$GPU_PATH/gt_RPn_freq_mhz" ] && [ -f "$GPU_PATH/gt_RP0_freq_mhz" ]; then
    MIN_FREQ=$(cat "$GPU_PATH/gt_RPn_freq_mhz")
    MAX_FREQ=$(cat "$GPU_PATH/gt_RP0_freq_mhz")
    echo "$MIN_FREQ" >"$GPU_PATH/gt_min_freq_mhz"
    echo "$MAX_FREQ" >"$GPU_PATH/gt_boost_freq_mhz"
    echo "$MAX_FREQ" >"$GPU_PATH/gt_max_freq_mhz"
  fi

  echo "=== 4. Enabling services and Swap ==="
  swapon -a 2>/dev/null || true
  systemctl start irqbalance 2>/dev/null || true
  systemctl start thermald 2>/dev/null || true

  echo ""
  echo "=== System successfully restored to default state! ==="

else
  echo "Usage: sudo $0 [setup|restore]"
fi
