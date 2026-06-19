#!/usr/bin/env bash
# Paper mode on terminal-bench 2.0 — single task (gcode-to-text) × 1 attempt.
#
# Mirror of lqrl/scripts/run_tb2_baseline_claude_code_sonnet.sh with
# two key differences:
#   1. The agent is SkillQClaudeCodeAgent (paper method), not
#      SkillsVoteClaudeCode (baseline).
#   2. The SkillQ bridge owns per-subtask hook wiring: bind-mounts
#      the state files into the container, starts the embedding
#      daemon, and updates the Q-table on trial end. This is the
#      whole point of the paper method vs the baseline.
#
# This script runs a SINGLE task as a smoke (gcode-to-text). For
# the full 89-task matrix, see experiments/run/run_benchmark.py
# (which generates per-task YAMLs in experiments/configs/).
#
# Outputs land in output/tb2_skillq_smoke__<timestamp>/
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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

CONFIG="experiments/configs/tb2_skillq_smoke.yaml"
RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date +%Y-%m-%d__%H-%M-%S)}"
JOB_NAME="tb2_skillq_smoke__${RUN_TIMESTAMP}"

# -------- preflight --------
command -v uv >/dev/null 2>&1 || { echo "uv not found; install via https://docs.astral.sh/uv/" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon not reachable" >&2; exit 1; }
[ -f .env ] || { echo ".env not found; copy .env.example to .env and set ANTHROPIC_API_KEY" >&2; exit 1; }

# Prebuilt image present?
docker image inspect skills_vote/gcode-to-text:20260604 >/dev/null 2>&1 || {
  echo "prebuilt image missing: skills_vote/gcode-to-text:20260604" >&2
  echo "If you need to prebuild, run:" >&2
  echo "  uv run skillq prebuild run --benchmark tb2 --agent claude_code --cfg-path <yaml>" >&2
  exit 1
}

# Task definition present?
TASK_DIR="${SkillQ_INPUT:-./input}/terminal-bench/gcode-to-text"
[ -f "${TASK_DIR}/task.toml" ] || {
  echo "task definition not found at ${TASK_DIR}/task.toml" >&2
  echo "copy from lqrl:" >&2
  echo "  mkdir -p ${SkillQ_INPUT:-./input}/terminal-bench && \\" >&2
  echo "    cp -r /home/gonern/workspace/lqrl/input/terminal-bench/gcode-to-text ${TASK_DIR}" >&2
  exit 1
}

# Seed skills stub present?
[ -f skills/_seed_stub/SKILL.md ] || {
  echo "seed_skills stub missing; expected skills/_seed_stub/SKILL.md" >&2
  exit 1
}

# Clean previous run (the YAML's job_name is fixed, so we
# pre-empt any stale output from a prior aborted run).
rm -rf "output/${JOB_NAME}"

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
echo "Running skillq paper mode on TB 2.0 (gcode-to-text): ${JOB_NAME}"
JOB_NAME="tb2_skillq_smoke"
env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_EFFORT \
    uv run skillq paper run -c "${CONFIG}"

# -------- quick aggregate --------
JOB_DIR="output/${JOB_NAME}"
echo ""
echo "=== Reward distribution ==="
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

# -------- Q-table state --------
STATE_FILE="${JOB_DIR}/.skillq_library/.state/method_state.json"
echo ""
echo "=== Q-table state ==="
if [ -f "${STATE_FILE}" ]; then
  python3 - <<PY
import json
data = json.load(open("${STATE_FILE}"))
print(f"  step:           {data.get('step', 0)}")
print(f"  Q-table size:   {len(data.get('q_table', []))}")
print(f"  probation:      {data.get('probation', {}).get('count', {})}")
print(f"  library skills: {len(data.get('library', {}).get('skills', {}))}")
for row in data.get('q_table', [])[:10]:
    print(f"    {row[0]:40s} q={row[1]:.4f}")
PY
else
  echo "  (no state file at ${STATE_FILE} — hook may not have fired)"
fi
