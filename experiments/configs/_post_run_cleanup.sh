#!/usr/bin/env bash
# _post_run_cleanup.sh — post-experiment container cleanup.
#
# Why this exists: SkillQ paper-mode runs set `delete: false` in the
# YAML so Harbor's `docker compose down --rmi all` doesn't nuke the
# skills_vote/<task>:20260604 base images (verified 2026-07-01 that
# `delete: true` deletes images at trial-end — see
# harbor/environments/docker/docker.py:579-585).
#
# This script runs AFTER the experiment finishes and reclaims the
# disk/mem that `delete: false` left behind. It ONLY touches
# containers + networks; it NEVER prunes images, so skills_vote
# base images survive.
#
# Usage:
#   # Manual (after a run finishes):
#   bash experiments/configs/_post_run_cleanup.sh
#
#   # From run_tb2_small10.sh: appended automatically when --delete is
#   # not requested; safe to run multiple times.

set -euo pipefail

echo "[$(date '+%H:%M:%S')] === post-run container cleanup ==="

# 1. Stop any skillq-orchestrated compose stacks that might be left.
#    (If delete=true was used in the YAML, this is a no-op.)
STACKS=$(docker ps -a --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u | grep -v '^$' || true)
if [ -n "$STACKS" ]; then
  echo "[$(date '+%H:%M:%S')] stopping ${STACKS//$'\n'/ } compose stacks"
  for s in $STACKS; do
    docker compose -p "$s" stop 2>/dev/null || true
  done
fi

# 2. Remove stopped skillq containers (NOT images).
BEFORE=$(docker ps -aq | wc -l | tr -d ' ')
docker container prune -f >/dev/null 2>&1 || true
AFTER=$(docker ps -aq | wc -l | tr -d ' ')
echo "[$(date '+%H:%M:%S')] containers: $BEFORE -> $AFTER"

# 3. Remove orphan networks (NOT images).
docker network prune -f >/dev/null 2>&1 || true

# 4. Sanity check: image count must be unchanged.
echo "[$(date '+%H:%M:%S')] images preserved:"
docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
  | grep -c '^skills_vote/' || true
echo "[$(date '+%H:%M:%S')] === cleanup done (images preserved) ==="