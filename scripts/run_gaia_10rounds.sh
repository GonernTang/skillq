#!/bin/bash
# GAIA 10-round iterative experiment — each round inherits Q-table + skills
# from the previous round. Round 1 is cold start, rounds 2-10 carry forward.
#
# Usage:
#   bash scripts/run_gaia_10rounds.sh
#
# Output layout:
#   output/gaia_r1__<ts>/.skillq_library/.state/method_state.json
#   output/gaia_r2__<ts>/.skillq_library/.state/method_state.json
#   ...
#
# Each round writes its own state snapshot, so you can roll back to any round.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROUNDS="${1:-10}"
PREV_STATE=""
R1_OUTPUT=""

echo "========================================="
echo "  GAIA $ROUNDS-Round Iterative Experiment"
echo "========================================="
echo ""

for round in $(seq 1 "$ROUNDS"); do
    echo "=== Round $round / $ROUNDS ==="

    if [ "$round" -eq 1 ]; then
        # Round 1: cold start — empty skills/gaia/, fresh Q-table
        uv run python experiments/run/run_benchmark.py \
            --benchmark gaia --variant full \
            --fresh-start

        R1_OUTPUT="$(ls -dt "$REPO_ROOT/output/gaia_skillq__"* 2>/dev/null | head -1)"
        PREV_STATE="$R1_OUTPUT/.skillq_library/.state/method_state.json"
    else
        # Rounds 2-10: inherit Q-table, disable L4 CREATE (ablation design)
        # — seed_skills_dir already points to skills/gaia/ (R1's skills)
        # — evolve.enabled=false: no new skills, only L3 EDIT on failures
        # — Q-learning optimizes skill selection on the fixed skill library
        uv run python experiments/run/run_benchmark.py \
            --benchmark gaia --variant full \
            --method-override state_path="$PREV_STATE" \
            --method-override reuse_q_table=true \
            --method-override reuse_embedding_cache=true \
            --method-override evolve.enabled=false

        CURRENT="$(ls -dt "$REPO_ROOT/output/gaia_skillq__"* 2>/dev/null | head -1)"
        PREV_STATE="$CURRENT/.skillq_library/.state/method_state.json"
    fi

    if [ ! -f "$PREV_STATE" ]; then
        echo "ERROR: state file not found: $PREV_STATE" >&2
        exit 1
    fi

    echo "  state → $PREV_STATE"
    echo ""
done

echo "=== Done ==="
echo "  R1 output: $R1_OUTPUT"
echo "  Last state: $PREV_STATE"
echo ""
echo "  Rollback to round N: set state_path to output/gaia_rN__*/method_state.json"
