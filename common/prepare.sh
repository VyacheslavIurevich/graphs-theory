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
	# Disable interrupt balancing across cores
	systemctl stop irqbalance 2>/dev/null || true
	# Disable Intel thermal daemon to prevent frequency throttling
	systemctl stop thermald 2>/dev/null || true
	# Disable swap memory
	swapoff -a
	echo "   Services irqbalance and thermald stopped. Swap disabled."

	echo "=== 2. Tuning CPU via pyperf (Turbo Boost, C-states, ASLR, Governor) ==="
	"$UVX_BIN" pyperf system tune

	echo "=== 3. Configuring kernel perf event permissions ==="
	sysctl -w kernel.perf_event_paranoid=-1
	sysctl -w kernel.kptr_restrict=0
	sysctl -w kernel.nmi_watchdog=0

	echo "=== 4. Locking Intel Iris Xe GPU frequency ==="
	if [ -f "$GPU_PATH/gt_RP1_freq_mhz" ]; then
		TARGET_FREQ=$(cat $GPU_PATH/gt_RP1_freq_mhz)
		echo "   Locking GPU frequency at base ${TARGET_FREQ} MHz..."
		echo "$TARGET_FREQ" >$GPU_PATH/gt_min_freq_mhz
		echo "$TARGET_FREQ" >$GPU_PATH/gt_max_freq_mhz
		echo "$TARGET_FREQ" >$GPU_PATH/gt_boost_freq_mhz
	else
		echo "   [Warning] Path $GPU_PATH not found. Skipping GPU frequency configuration."
	fi

	echo "=== 5. Flushing all caches (OS, RAM, and CPU L1/L2/L3) ==="
	# 1. Flush OS disk cache (PageCache, dentries, inodes)
	sync
	echo 3 >/proc/sys/vm/drop_caches

	# 2. Compact RAM
	echo 1 >/proc/sys/vm/compact_memory 2>/dev/null || true

	# 3. Evict CPU L1/L2/L3 cache (overwrite 32 MB in RAM to flush 8 MB L3 cache of i5-1135G7)
	python3 -c 'b = bytearray(32 * 1024 * 1024); b[:] = b"\x00" * len(b)' 2>/dev/null || true
	echo "   OS disk cache flushed, RAM compacted, CPU cache evicted."

	echo ""
	echo "========================================================================="
	echo " Benchmarking testbed successfully prepared!"
	echo " Reminder: For best results, switch to TTY (Ctrl+Alt+F3)"
	echo " and stop GUI with: sudo systemctl isolate multi-user.target"
	echo "========================================================================="

elif [ "$ACTION" == "restore" ]; then
	echo "=== 1. Resetting CPU settings via pyperf ==="
	"$UVX_BIN" pyperf system reset

	echo "=== 2. Restoring perf security restrictions ==="
	sysctl -w kernel.perf_event_paranoid=2
	sysctl -w kernel.kptr_restrict=1
	sysctl -w kernel.nmi_watchdog=1

	echo "=== 3. Resetting Intel GPU frequency limits ==="
	if [ -f "$GPU_PATH/gt_RPn_freq_mhz" ] && [ -f "$GPU_PATH/gt_RP0_freq_mhz" ]; then
		MIN_FREQ=$(cat $GPU_PATH/gt_RPn_freq_mhz)
		MAX_FREQ=$(cat $GPU_PATH/gt_RP0_freq_mhz)
		echo "$MIN_FREQ" >$GPU_PATH/gt_min_freq_mhz
		echo "$MAX_FREQ" >$GPU_PATH/gt_boost_freq_mhz
		echo "$MAX_FREQ" >$GPU_PATH/gt_max_freq_mhz
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
