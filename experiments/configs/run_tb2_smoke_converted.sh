#!/usr/bin/env bash
# run_tb2_smoke_converted.sh — single-task smoke for the recovered
# configure-git-webserver task (vs. the dead-symlink it used to be).
set -euo pipefail

ts() { date '+%H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

cd /home/gonern/workspace/skillq

log "=== pre-flight ==="
docker ps >/dev/null && log "Docker: UP" || { log "Docker: DOWN"; exit 1; }

if [ ! -f .env ]; then
    log ".env missing"
    exit 1
fi
set -a; source .env; set +a
for k in ANTHROPIC_BASE_URL ANTHROPIC_MODEL EMBEDDING_BASE_URL EMBEDDING_MODEL; do
    if [ -z "${!k:-}" ]; then
        log "FATAL: .env $k is empty"
        exit 1
    fi
done
log ".env: OK (model=${ANTHROPIC_MODEL})"

if ! docker image inspect "skills_vote/configure-git-webserver:20260604" >/dev/null 2>&1; then
    log "FATAL: skills_vote/configure-git-webserver:20260604 missing"
    exit 1
fi

log "Dry-run..."
if ! timeout 30 uv run python experiments/run/run_benchmark.py \
    --benchmark tb2 --variant smoke_converted --dry-run >/tmp/smoke_dry.log 2>&1; then
    log "FATAL: dry-run failed"
    tail -30 /tmp/smoke_dry.log
    exit 1
fi
log "Dry-run: OK"

log "=== launching 1-task smoke (configure-git-webserver) ==="
exec uv run python experiments/run/run_benchmark.py \
    --benchmark tb2 --variant smoke_converted
