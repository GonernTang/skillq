#!/bin/bash
# Build ONE shared Claude Code image for all 165 GAIA tasks.
#
# All 165 tasks share the same base environment (python:3.11-slim-bookworm
# + curl). 38 tasks have workspace attachments (xlsx/png/pdf/mp3) that
# are all copied into the shared image — paths are UUID-prefixed so no
# conflicts. Result: one ~1.4 GB image, all tasks point to it.
#
# Usage:
#   bash scripts/build_gaia_image.sh [tag]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAG="${1:-$(date +%Y%m%d)}"
GAIA_TASKS_DIR="$REPO_ROOT/input/gaia/gaia"
DOCKERFILE_CLAUDE="$REPO_ROOT/docker/Dockerfile.claude"
IMAGE="gaia/base:${TAG}"

echo "=== GAIA Shared Image Builder ==="
echo "Tag:   $TAG"
echo "Image: $IMAGE"
echo ""

# ── Step 1: Collect all workspace files ──
echo "=== Step 1: Collect workspace files ==="
rm -rf /tmp/gaia-build
mkdir -p /tmp/gaia-build/workspace
COUNT=0
for d in "$GAIA_TASKS_DIR"/*/environment/workspace/; do
    if [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
        cp "$d"/* /tmp/gaia-build/workspace/ 2>/dev/null || true
        COUNT=$((COUNT + 1))
    fi
done
echo "  Collected $COUNT workspace file sets"
echo ""

# ── Step 2: Build base image (python + curl + all workspace files) ──
echo "=== Step 2: Build base image ==="
cat > /tmp/Dockerfile.gaia-base << 'DOCKERFILE'
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends curl
COPY workspace/ /app/files/
DOCKERFILE

DOCKER_BUILDKIT=1 docker build \
    -f /tmp/Dockerfile.gaia-base \
    -t gaia-base:${TAG} \
    /tmp/gaia-build/
echo ""

# ── Step 3: Build Claude Code on top ──
echo "=== Step 3: Build Claude Code (~6 min) ==="
DOCKER_BUILDKIT=1 docker build \
    -f "$DOCKERFILE_CLAUDE" \
    --build-arg "BASE_IMAGE=gaia-base:${TAG}" \
    --build-arg NVM_VERSION=v0.40.4 \
    --build-arg NODE_VERSION=22 \
    --build-arg CLAUDE_VERSION=latest \
    -t "$IMAGE" \
    "$REPO_ROOT/docker/"
echo ""

# ── Step 4: Update all task.toml files ──
echo "=== Step 4: Update task.toml ==="
for TASK_TOML in "$GAIA_TASKS_DIR"/*/task.toml; do
    uv run python -c "
import tomlkit
p = '$TASK_TOML'
doc = tomlkit.parse(open(p).read())
doc['environment']['docker_image'] = '$IMAGE'
open(p, 'w').write(tomlkit.dumps(doc))
" 2>/dev/null
done
echo "  Updated $(ls "$GAIA_TASKS_DIR"/*/task.toml | wc -l) tasks → $IMAGE"
echo ""

echo "=== Done ==="
echo "  Image: $IMAGE"
docker images "$IMAGE" --format '  Size: {{.Size}}'
echo ""
echo "  Run: uv run python experiments/run/run_benchmark.py --benchmark gaia --variant full"
