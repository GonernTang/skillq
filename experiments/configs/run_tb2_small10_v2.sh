#!/usr/bin/env bash
# run_tb2_small10_v2.sh — TB 2.0 small10-v2 10-task 验证实验启动脚本
#
# 配置: experiments/configs/tb2_skillq_small10_v2.yaml
#   Agent:     deepseek-v4-flash (来自 .env ANTHROPIC_MODEL)
#   Embedding: text-embedding-v4  (来自 .env EMBEDDING_MODEL)
#
#   L1: multiplicative, β=0.5, γ=0.2, sim_gate=0.5, floor=0, top_k=3
#   L3: attribution + editor = deepseek-v4-flash
#   L4: extract_every_n_trials=1, enforce_failure_structure=true
#   Q:  fresh-start (清 Q-table), b_max=1000, seed_q=0.5
#
#   10 tasks × 1 attempt, 4 并发, 1h/trial, delete=false
#   预计时长 45-75 min
#   产物 output/tb2_skillq_small10_v2__<timestamp>/
#
# 用法:
#   # 前台 (Ctrl+C 终止)
#   bash experiments/configs/run_tb2_small10_v2.sh
#
#   # 后台 nohup (ssh 断连不中断)
#   nohup bash experiments/configs/run_tb2_small10_v2.sh > /tmp/small10_v2.log 2>&1 &
#   tail -f /tmp/small10_v2.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ------------------------------------------------------------------
# pre-flight
# ------------------------------------------------------------------
echo "[$(date '+%H:%M:%S')] === small10-v2 pre-flight ==="

# docker daemon
if ! docker info >/dev/null 2>&1; then
    echo "[$(date '+%H:%M:%S')] FATAL: Docker daemon not running."
    exit 1
fi
echo "[$(date '+%H:%M:%S')] Docker: UP"

# .env
if [ ! -f .env ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: .env not found."
    exit 1
fi
source .env
for key in ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL EMBEDDING_API_KEY EMBEDDING_BASE_URL EMBEDDING_MODEL; do
    if [ -z "${!key:-}" ]; then
        echo "[$(date '+%H:%M:%S')] FATAL: .env ${key} is empty."
        exit 1
    fi
done
echo "[$(date '+%H:%M:%S')] .env: OK (model=${ANTHROPIC_MODEL})"

# docker images for the 10 tasks
MISSING=0
for task in chess-best-move circuit-fibsqrt crack-7z-hash git-leak-recovery \
            hf-model-inference path-tracing qemu-alpine-ssh regex-chess \
            sqlite-db-truncate build-pmars; do
    if ! docker images --format '{{.Repository}}' 2>/dev/null | grep -q "skills_vote/$task"; then
        echo "[$(date '+%H:%M:%S')] MISSING image: skills_vote/$task"
        MISSING=$((MISSING + 1))
    fi
done
if [ "$MISSING" -gt 0 ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: ${MISSING} skills_vote images missing."
    exit 1
fi
echo "[$(date '+%H:%M:%S')] Images: all 10 skills_vote images present"

# dry-run
echo "[$(date '+%H:%M:%S')] Dry-run..."
if ! timeout 30 uv run python experiments/run/run_benchmark.py \
    --benchmark tb2 --variant small10_v2 --fresh-start --dry-run \
    >/tmp/small10_v2_dry.log 2>&1; then
    echo "[$(date '+%H:%M:%S')] FATAL: dry-run failed (see /tmp/small10_v2_dry.log)"
    exit 1
fi
rm -f experiments/configs/tb2_skillq_small10_v2__*.job.yaml \
      experiments/configs/tb2_skillq_small10_v2__*.method.yaml
echo "[$(date '+%H:%M:%S')] Dry-run: OK"

# ------------------------------------------------------------------
# launch
# ------------------------------------------------------------------
echo ""
echo "[$(date '+%H:%M:%S')] === launching small10-v2 ==="
echo "[$(date '+%H:%M:%S')] 10 tasks, 4 concurrent, fresh-start, extract_every_n_trials=1"
echo "[$(date '+%H:%M:%S')] model: ${ANTHROPIC_MODEL}"
echo ""

uv run python experiments/run/run_benchmark.py \
    --benchmark tb2 \
    --variant small10_v2 \
    --fresh-start

echo ""
echo "[$(date '+%H:%M:%S')] === small10-v2 finished ==="
