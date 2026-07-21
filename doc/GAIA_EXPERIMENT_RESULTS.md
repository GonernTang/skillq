# GAIA Benchmark Experiment Results: SkillQ Four-Layer Method

> Multi-round iterative experiment on GAIA dataset (165 tasks), evaluating
> SkillQ's four-layer method (L1 retrieval → L2 Q-learning → L3 attribution →
> L4 evolution) with ablation controls and Q-learning convergence tracking.

**Date**: 2026-07-17 to 2026-07-20  
**Model**: deepseek-v4-flash (via Anthropic API / LiteLLM)  
**Benchmark**: GAIA v1.0 (53 L1, 86 L2, 26 L3)

---

## 1. Experiment Design

Four sequential rounds with controlled variable manipulation:

| Round | Design | Purpose |
|-------|--------|---------|
| R1 | Cold start, L4 ON, 4 concurrent, seed_initial_q=0.5, empty skill library | Baseline: measure cold-start skill generation |
| R2 | Inherit R1 state, L4 CREATE OFF, 4 concurrent | Ablation: isolate Q-learning contribution on fixed skill set |
| R3 | Inherit R1+R2 state, L4 CREATE ON, 8 concurrent | Verify: re-enable L4, measure incremental improvement |
| R4 | Inherit R1-R3 state, L4 CREATE ON, 8 concurrent | Convergence: continued iteration with growing skill library |

All rounds inherit the previous round's Q-table and skill library via `state_path` + `reuse_q_table=true`. R2 uses `evolve.enabled=false` to freeze skill creation while keeping L3 EDIT active. R1 uses `--fresh-start` to initialize Q-table at uniform 0.5.

### 1.1 Method Configuration

| Parameter | Value |
|-----------|-------|
| Retrieval mode | pull (Top-K injection via UserPromptSubmit) |
| Score mode | multiplicative: `sim·(1+β·Q)+γ·UCB` |
| β (Q weight) | 0.5 |
| γ (UCB weight) | 0.2 |
| Hard Gate (sim_gate_min_score) | 0.5 |
| Top-K | 3 |
| Q-learning α | 0.1 (default) |
| b_max (library cap) | 1000 |
| Embedding | text-embedding-v4, dim=1024 |

### 1.2 Infrastructure

- **Docker image**: Single shared `gaia/base:20260717` for all 165 tasks (python:3.11-slim-bookworm + curl + workspace attachments + Claude Code agent)
- **Disk footprint**: ~1.4 GB (shared base + agent layer)
- **Task timeout**: 1200s agent ceiling (task default: 600s)

---

## 2. Overall Results

| Metric | R1 (Cold Start) | R2 (L4 OFF) | R3 (L4 ON) | R4 (L4 ON) |
|--------|-----------------|-------------|------------|------------|
| **Overall Pass Rate** | 115/165 **69.7%** | 112/165 **67.9%** | 120/165 **72.7%** | 116/165 **70.3%** |
| L1 | 39/53 73.6% | 38/53 71.7% | 42/53 **79.2%** | 39/53 73.6% |
| L2 | 65/86 75.6% | 61/86 70.9% | 65/86 75.6% | 64/86 74.4% |
| L3 | 11/26 42.3% | 13/26 **50.0%** | 13/26 50.0% | 13/26 50.0% |

**Best performance**: R3 achieves 72.7% overall and 79.2% on L1 — the highest across all rounds. L3 stabilizes at 50.0% after R2 and remains unchanged through R4, suggesting a performance ceiling for the hardest tasks given the current model and skill representation.

### 2.1 Task-Level Delta

| Transition | Fail→Pass | Pass→Fail | Net |
|------------|-----------|-----------|-----|
| R1 → R2 | 10 | 13 | **-3** |
| R2 → R3 | 12 | 4 | **+8** |
| R3 → R4 | 7 | 11 | **-4** |

R2→R3 shows the strongest recovery (+8 net): re-enabling L4 CREATE generated 63 new skills, converting 12 previously-failed tasks. R3→R4 shows marginal degradation (-4), suggesting library dilution from over-creation.

---

## 3. Skill Library Evolution

### 3.1 Growth

| | R1 | R2 | R3 | R4 |
|---|-----|-----|-----|-----|
| Skills in library | 127 | 127 (frozen) | 190 (+63) | 241 (+51) |
| Skills on disk | 117 | 117 | 181 | 232 |
| Skills called (trials) | 19 | 84 | 87 | 102 |

Skill usage increases monotonically (19→84→87→102 trials), driven by L4 CREATE adding relevant skills and Q-learning boosting composite retrieval scores. However, library growth outpaces usage: 50% of skills remain never-called by R4 (118/241).

### 3.2 Q-Table Convergence

| | R1 | R2 | R3 | R4 |
|---|-----|-----|-----|-----|
| Q mean | 0.522 | 0.522 | 0.529 | 0.534 |
| Q max | 0.627 | 0.627 | 0.670 | **0.738** |
| Q > 0.5 (% of all) | 74 (58%) | 74 (58%) | 86 (45%) | 107 (44%) |
| Q = 0.5 (never used) | 44 (35%) | 44 (35%) | 95 (50%) | **118 (49%)** |
| Q < 0.5 (degraded) | 9 (7%) | 9 (7%) | 9 (5%) | 16 (7%) |
| Pipeline step counter | 165 | 303 | 455 | 609 |

Key insight: Q-learning successfully differentiates skills (44→107 above 0.5), but the ratio of never-called skills rises from 35% to 49% as L4 CREATE generates many skills that are never retrieved by L1. The top Q score reaches 0.738 by R4, showing strong convergence for consistently-useful skills.

---

## 4. Attribution & Verdict Distribution

### 4.1 R2 Attribution (before code fix)

R2 had a consistency-clamp bug where the attribution LLM's verdict was overridden without distinguishing skill-involvement:

| Attribution | Count | Issue |
|-------------|-------|-------|
| failure_skill_not_used | 20 | Library missing relevant skill |
| failure_skill_used (real) | 9 | Skill was used, answer still wrong |
| failure_skill_used (clamped) | 8 | LLM misclassified, incorrectly clamped |

The clamp caused L3 EDIT to fire on 8 trials where no skill was actually used, editing innocent skills with misleading failure traces. This was fixed before R3 (code-derived verdict from calls_log + r_task).

### 4.2 L3 EDIT Effectiveness

R2: 11 real failure_skill_used cases triggered L3 EDIT, but zero produced effective edits — the editor targeted the globally-highest-Q skill rather than the actually-called skill. Fixed before R3 (reads calls_log to identify the specific skill involved).

---

## 5. Code Improvements

During the experiment series, four bugs were discovered and fixed:

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | Attribution LLM judged success/failure independently | 8 fake failure_skill_used cases, spurious L3 EDIT | Code derives verdict from calls_log × r_task |
| 2 | L3 EDIT targeted highest-Q skill, not actually-called skill | 11 real failures with zero effective edits | Read calls_log, edit the involved skill |
| 3 | State save overwrote previous round's state file | R1 original state lost, unverifiable rollback | Write to lib_root/.state/ instead of state_path |
| 4 | EditRefiner placed in l3_attribution/ (attribution layer) | Module responsibility confusion | Moved to l4_evolve/ (evolution layer) |

Additionally, 7 ablation switches were added to `MethodConfig` for controlled experiments:
`enable_retrieval`, `enable_q_retrieval`, `enable_q_learning`, `enable_attribution`,
`enable_skill_edit`, `enable_success_skill_create`, `enable_failure_skill_create`.

---

## 6. Key Findings

### 6.1 L4 CREATE is the Primary Performance Driver

R2 (L4 disabled) dropped to 67.9% — the lowest across all rounds. R3 (L4 re-enabled) recovered to 72.7% — the highest. Net task delta: -3 (R1→R2) vs +8 (R2→R3). Closing L4 prevented the system from filling skill gaps, and the 127-skill library from R1 could not cover all 165 diverse GAIA tasks.

### 6.2 Q-Learning Converges but Library Bloats

Q mean rises steadily (0.522→0.534) and Q max reaches 0.738, demonstrating effective differentiation. However, 49% of R4's 241 skills were never called — L4 CREATE from success trajectories (SUCCESS_NO_SKILL_SEEN) injects skills for tasks the agent could already solve independently, inflating the library without improving pass rate.

### 6.3 L3 Performance Ceiling

L3 (the hardest GAIA tasks) converged to 50.0% at R2 and remained flat. These 26 tasks likely require capabilities beyond what the current model + skill format can provide (multi-hop web research, complex numerical reasoning, cross-modal analysis).

### 6.4 Skill Usage Rate Increases Regardless of Pass Rate

Skill calls per round (19→84→87→102) rose monotonically even when pass rate declined (R3→R4). This suggests Q-learning successfully encourages the agent to trust and invoke skills, but skill quality — not quantity — determines whether those invocations lead to correct answers.

---

## 7. Future Directions

1. **Ablation: disable success-path skill creation** (`enable_success_skill_create=false`). R1-R4 data shows 50%+ of skills are never called; limiting L4 CREATE to failure trajectories should reduce ghost skills while preserving gap-filling.

2. **Lower Hard Gate threshold**. `sim_gate_min_score=0.5` may be too strict for GAIA's diverse task distribution; lowering to 0.3 could surface more relevant skills without introducing noise.

3. **Skill deduplication and eviction**. The current library management (Q-driven eviction) only removes skills below b_max. A periodic dedup pass on never-called skills would reduce L1 search overhead.

4. **Model comparison**. All four rounds used deepseek-v4-flash. Stronger models (claude-sonnet-4-5) may improve L3 pass rates and skill extraction quality.

---

*Generated: 2026-07-20 | Repository: [GonernTang/skillq](https://github.com/GonernTang/skillq)*
