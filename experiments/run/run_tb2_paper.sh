#!/usr/bin/env bash
# Thin wrapper for the TB 2.0 smoke run (Step 8, 2026-06-27).
#
# Replaces the old 138-line run_tb2_paper.sh that hardcoded a single
# task (gcode-to-text) and pinned job_name to a fixed date. The new
# shape delegates everything to the single-driver in
# experiments/run/run_benchmark.py with --benchmark tb2 --variant smoke.
#
# Per-trial reward lives in <trial_name>/result.json
#   → verifier_result.rewards.reward  (0.0 or 1.0)
# Q-table updates land in
#   <job_dir>/.skillq_library/.state/method_state.json
# Per-skill call log (from the PreToolUse hook) lives in
#   <trial_dir>/mg_skill_calls.jsonl
#
# Required .env:
#   ANTHROPIC_API_KEY=...
#   ANTHROPIC_BASE_URL=...   # optional, leave empty to hit api.anthropic.com
#   ANTHROPIC_MODEL=claude-sonnet-4-5
#   SkillQ_INPUT=./input     # default; only override if your task
#                            # definitions live elsewhere
#
# Hardware: 4 CPU, 8 GB RAM is enough for a single-task smoke.
# Wall-time: 5-30 min per task (mostly LLM roundtrips + verifier run).
#
# Pass any single-driver flags through:
#   ./experiments/run/run_tb2_paper.sh --dry-run
#   ./experiments/run/run_tb2_paper.sh --method-override retrieval.score_mode=additive
#   ./experiments/run/run_tb2_paper.sh --fresh-start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# -------- preflight --------
command -v uv >/dev/null 2>&1 || { echo "uv not found; install via https://docs.astral.sh/uv/" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon not reachable" >&2; exit 1; }
[ -f .env ] || { echo ".env not found; copy .env.example to .env and set ANTHROPIC_API_KEY" >&2; exit 1; }

# Prebuilt image present? (smoke task is chess-best-move.)
docker image inspect skills_vote/chess-best-move:20260604 >/dev/null 2>&1 || {
  echo "prebuilt image missing: skills_vote/chess-best-move:20260604" >&2
  echo "If you need to prebuild, run:" >&2
  echo "  uv run skillq prebuild run --benchmark tb2 --agent claude_code --cfg-path <yaml>" >&2
  exit 1
}

# Task definition present?
TASK_DIR="${SkillQ_INPUT:-./input}/terminal-bench/chess-best-move"
[ -f "${TASK_DIR}/task.toml" ] || {
  echo "task definition not found at ${TASK_DIR}/task.toml" >&2
  echo "copy from lqrl:" >&2
  echo "  mkdir -p ${SkillQ_INPUT:-./input}/terminal-bench && \\" >&2
  echo "    cp -r /home/gonern/workspace/lqrl/input/terminal-bench/chess-best-move ${TASK_DIR}" >&2
  exit 1
}

# Seed skills stub present?
[ -f skills/_seed_stub/SKILL.md ] || {
  echo "seed_skills stub missing; expected skills/_seed_stub/SKILL.md" >&2
  exit 1
}

# -------- run --------
set -a
. ./.env
set +a

# Harbor's ClaudeCode agent reads CLAUDE_CODE_EFFORT_LEVEL via
# env_fallback, but its enum validator only accepts low/medium/high.
# Claude Code (the CLI client) often sets CLAUDE_CODE_EFFORT_LEVEL=max
# in our shell environment; if inherited by the trial subprocess it
# crashes Trial.create with 'Invalid value for reasoning_effort'.
# Strip it before launching. Use `env -u` so even if `unset` in the
# current shell fails (e.g. read-only), uv run still sees a clean env.
echo "Running skillq paper mode on TB 2.0 (smoke: chess-best-move)..."
env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_EFFORT \
    uv run python "${SCRIPT_DIR}/run_benchmark.py" \
        --benchmark tb2 \
        --variant smoke \
        "$@"

# -------- quick aggregate --------
# The driver prints job_name + the path to <job_name>.job.yaml. Find the
# newest <job_name>.job.yaml in experiments/configs/ as a fallback.
JOB_YAML="$(ls -1t "${SCRIPT_DIR}/../configs/"*.job.yaml 2>/dev/null | head -n1 || true)"
JOB_NAME="$(basename "${JOB_YAML}" .job.yaml 2>/dev/null || true)"
JOB_DIR="${REPO_ROOT}/output/${JOB_NAME}"

echo ""
echo "=== Reward distribution (job_name=${JOB_NAME}) ==="
if [ -d "${JOB_DIR}" ]; then
  python3 - <<PY
import json, glob
rewards = []
for r in glob.glob(f"${JOB_DIR}/*/result.json"):
    try:
        d = json.load(open(r))
        rv = d.get("verifier_result", {}).get("rewards", {}).get("reward")
        if rv is not None:
            rewards.append(float(rv))
    except Exception:
        pass
if not rewards:
    print("  (no reward results yet — trial may not have completed)")
else:
    n = len(rewards)
    ones = sum(1 for r in rewards if r >= 1.0)
    print(f"  trials with reward.json: {n}")
    print(f"  pass@1:                 {ones / n:.3f}  ({ones}/{n})")
PY
else
  echo "  (job dir ${JOB_DIR} not found — trial may not have started)"
fi

# -------- Q-table state --------
STATE_FILE="${JOB_DIR}/.skillq_library/.state/method_state.json"
echo ""
echo "=== Q-table state ==="
if [ -f "${STATE_FILE}" ]; then
  python3 - <<PY
import json
data = json.load(open("${STATE_FILE}"))
print(f"  step:           {data.get('step', 0)}")
q_table = data.get("q_table", [])
print(f"  Q-table size:   {len(q_table)}")
lib_skills = data.get("library", {}).get("skills", {})
print(f"  library skills: {len(lib_skills)}")
for row in q_table[:10]:
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        print(f"    {row[0]:40s} q={float(row[1]):.4f}")
PY
else
  echo "  (no state file at ${STATE_FILE} — hook may not have fired)"
fi
