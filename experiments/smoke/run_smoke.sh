#!/usr/bin/env bash
# Smoke test: N TB 2.0 tasks, paper mode, end-to-end.
#
# Mirrors lqrl's scripts/smoke_test_cobol.sh but adapted for paper
# mode and reuses the prebuilt images / dataset cache from the lqrl
# tree (no re-download, no re-prebuild).
#
# Steps
#   0. preflight (uv, docker, .env, project deps)
#   1. verify all 5 tasks exist in lqrl's input/terminal-bench
#   2. verify all 5 skills_vote/<task>:20260604 prebuilt images
#   3. ensure skills/ has the seed stub
#   4. run `uv run paper paper run -c .../fix-git_skillq_smoke.yaml`
#   5. for each task, parse result.json -> reward
#   6. verify .skillq_library/method_state.json: step = number of trials
#   7. print trajectory / verifier paths
#
# Cleanup
#   rm -rf output/smoke_5tasks_paper
#   rm -rf skills            (if you want a clean slate)

set -euo pipefail
# Make pipeline exit codes propagate (so a failing `paper paper run`
# is not masked by a `| tail`).
set -o pipefail

# -------- config --------
TASKS=(
  gcode-to-text
)
IMAGE_TAG="20260604"
CONFIG="experiments/smoke/fix-git_skillq_smoke.yaml"
JOB_DIR="output/smoke_wiring_v2"
SEED_SKILLS="skills"
METHOD_CONFIG="experiments/smoke/method.yaml"
SkillQ_INPUT="${SkillQ_INPUT:-./input}"
N_TASKS=${#TASKS[@]}

# -------- helpers --------
log()  { printf "\033[1;36m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
fail() { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }
ok()   { printf "\033[1;32m[ OK]\033[0m %s\n" "$*"; }

# -------- 0. preflight --------
log "=== paper smoke test: $N_TASKS TB 2.0 tasks (paper mode) ==="
log "Working dir: $(pwd)"
log "Tasks: ${TASKS[*]}"

command -v uv >/dev/null 2>&1 || fail "uv not found; install via https://docs.astral.sh/uv/"
ok "uv: $(uv --version)"

docker info >/dev/null 2>&1 || fail "docker daemon not reachable"
ok "docker: $(docker --version)"

[ -f .env ] || fail ".env not found at $(pwd)/.env; copy .env.example to .env and fill ANTHROPIC_* keys"
ok ".env found"

uv sync --quiet 2>&1 | tail -3 || fail "uv sync failed"
ok "project deps synced"

[ -f "$CONFIG" ] || fail "$CONFIG not found"
ok "smoke config: $CONFIG"

# -------- 1. verify tasks exist --------
for t in "${TASKS[@]}"; do
    [ -d "$SkillQ_INPUT/$t" ] || fail "lqrl input task not found at $SkillQ_INPUT/$t"
    [ -f "$SkillQ_INPUT/$t/task.toml" ] || fail "$SkillQ_INPUT/$t/task.toml missing"
done
ok "all $N_TASKS task defs present in $SkillQ_INPUT/"

# -------- 2. verify prebuilt images --------
for t in "${TASKS[@]}"; do
    img="skills_vote/${t}:${IMAGE_TAG}"
    if ! docker image inspect "$img" >/dev/null 2>&1; then
        fail "prebuilt image missing: $img (run uv run paper prebuild run --benchmark tb2 --agent claude_code --image-tag $IMAGE_TAG)"
    fi
done
ok "all $N_TASKS prebuilt images present (skills_vote/<task>:$IMAGE_TAG)"

# -------- 3. seed skills --------
if [ -d "$SEED_SKILLS" ] && [ -n "$(ls -A "$SEED_SKILLS" 2>/dev/null)" ]; then
    ok "seed skills dir already populated at $SEED_SKILLS"
else
    mkdir -p "$SEED_SKILLS/_seed_stub"
    cat > "$SEED_SKILLS/_seed_stub/SKILL.md" <<'STUB'
---
name: _seed_stub
description: Placeholder skill so the seed library exists on this host.
metadata:
  version: "0.0.0"
---

# Seed Stub

This is the minimum-viable seed library needed so SkillsVote's
step_recommend has at least one skill to copy into
$CLAUDE_CONFIG_DIR/skills. The paper-method smoke does not need real
skills to validate the Q-table / on_trial_ended pipeline.
STUB
    ok "wrote $SEED_SKILLS/_seed_stub/SKILL.md"
fi

# -------- 4. run the trials --------
log "--- Running `paper paper run` ($N_TASKS trials, ~1-2 min each) ---"
log "  config:     $CONFIG"
log "  agent:      $(grep model_name $CONFIG | awk '{print $2}')"
log "  job dir:    $JOB_DIR"

# Load .env so env-var resolution sees the keys.
set -a
. ./.env
set +a

# Clean any prior run so the smoke is reproducible.
rm -rf "$JOB_DIR"

uv run paper paper run -c "$CONFIG" --method-config "$METHOD_CONFIG" 2>&1 | tee /tmp/paper_run.log | tail -40

# -------- 5. parse per-trial results --------
[ -d "$JOB_DIR" ] || fail "no job dir at $JOB_DIR"
ok "job dir: $JOB_DIR"

log ""
log "=== per-trial rewards ==="
log "task                  reward     exception"
log "-----                 -----      ---------"
n_solved=0
n_failed=0
declare -A TRIAL_DIRS
for t in "${TASKS[@]}"; do
    trial_dir=$(ls -d "$JOB_DIR/${t}"__*/ 2>/dev/null | head -1 || true)
    if [ -z "$trial_dir" ]; then
        printf "%-22s %-10s %s\n" "$t" "<no trial dir>" ""
        n_failed=$((n_failed + 1))
        continue
    fi
    TRIAL_DIRS[$t]="$trial_dir"
    if [ ! -f "$trial_dir/result.json" ]; then
        printf "%-22s %-10s %s\n" "$t" "<no result.json>" ""
        n_failed=$((n_failed + 1))
        continue
    fi
    read -r reward exc <<<"$(python3 -c "
import json
d = json.load(open('$trial_dir/result.json'))
reward = d.get('verifier_result', {}).get('rewards', {}).get('reward') if d.get('verifier_result') else None
exc = d.get('exception_info', {}).get('exception_type', '') if d.get('exception_info') else ''
print(reward if reward is not None else '<none>', exc or '')
")"
    printf "%-22s %-10s %s\n" "$t" "$reward" "$exc"
    if [ "$reward" = "1.0" ] || [ "$reward" = "1" ]; then
        n_solved=$((n_solved + 1))
    else
        n_failed=$((n_failed + 1))
    fi
done
log ""
log "  solved: $n_solved / $N_TASKS"

# -------- 6. paper-mode artifacts --------
[ -d "$JOB_DIR/.skillq_library" ] || fail ".skillq_library not present in $JOB_DIR"
ok "paper method wrote $JOB_DIR/.skillq_library/"

[ -f "$JOB_DIR/.skillq_library/.state/method_state.json" ] \
    || fail "method_state.json missing (bridge did not save state)"
ok "method_state.json present"

log ""
log "=== method_state.json ==="
python3 <<EOF
import json
d = json.load(open("$JOB_DIR/.skillq_library/.state/method_state.json"))
print(f"  step:           {d.get('step')}")
print(f"  q_table:        {len(d.get('q_table', []))} entries")
print(f"  library.skills: {len(d.get('library', {}).get('skills', {}))} skills")
EOF

# -------- 7. trajectory / verifier (first trial as a sample) --------
FIRST_TRIAL="${TRIAL_DIRS[${TASKS[0]}]}"
if [ -n "$FIRST_TRIAL" ] && [ -d "$FIRST_TRIAL" ]; then
    log ""
    log "=== sample trajectory / verifier (${TASKS[0]}) ==="
    AGENT_DIR="$FIRST_TRIAL/agent"
    if [ -d "$AGENT_DIR" ]; then
        ok "agent dir: $AGENT_DIR"
        log "  session JSONLs: $(find $AGENT_DIR -name '*.jsonl' | head -3 | tr '\n' ' ')"
    fi
    VERIFIER_DIR="$FIRST_TRIAL/verifier"
    if [ -d "$VERIFIER_DIR" ]; then
        ok "verifier dir: $VERIFIER_DIR"
        log "  artifacts: $(ls $VERIFIER_DIR | tr '\n' ' ')"
    fi
fi

# -------- done --------
log ""
log "============================================================"
log "  ✓ SMOKE TEST PASSED: $N_TASKS trials, $n_solved solved"
log "============================================================"
log ""
log "  job dir:       $JOB_DIR"
log "  skillq_library:    $JOB_DIR/.skillq_library/"
log "  state:         $JOB_DIR/.skillq_library/.state/method_state.json"
log "  cleanup:       rm -rf $JOB_DIR"
log ""
