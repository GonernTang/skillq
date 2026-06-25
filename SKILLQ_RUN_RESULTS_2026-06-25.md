# SkillQ TB 2.0 全量 Run Results — 2026-06-25

## 1. Headline Numbers

| Metric | Old baseline (2026-06-24) | New run (2026-06-25) | Δ |
|--------|---------------------------|----------------------|---|
| n_trials | 89 | 89 | — |
| n_errors | 13 | 10 | -3 |
| **pass@1** | **0.494** (44/89) | **0.584** (52/89) | **+0.090 (+18% rel.)** |
| VerifierTimeoutError | 13 | 0 | -13 (multiplier fix) |
| AgentTimeoutError | 0 | 7 | +7 (intentional ceiling firings) |
| NonZeroAgentExitCodeError | 0 | 3 | +3 (transient agent errors) |
| Skill tool_use calls | 0 (no seed_skills_dir) | 6 (6.7% per trial) | seed fix works |
| Wall-clock | 4h 04m (2026-06-24) | 1h 49m (2026-06-25) | -55% |

**Net: +9 percentage points pass@1, with a working SkillQ retrieval layer.**

## 2. What worked

### 2.1 Wall-clock ceiling fix (Bug #5)
- All 7 AgentTimeoutError trials stopped at ~3700-4500s (1.0×3600 ceiling + ~3-7 min verifier/post-step overhead)
- No more runaway trials (vs 2026-06-24's 115min/4hr outliers)
- 13 VerifierTimeoutError → 0

### 2.2 circuit-fibsqrt prompt fix (Diagnostic checklist + Stop signal)
- 2026-06-24: 115 min / $56 / 7 versions / **reward=0** (compliance-theater spiral)
- 2026-06-25: 3883s = 64.7 min wall-clock but hit `AgentTimeoutError` → **reward=0**
- Net: still failing but with a clean error signal instead of an undetected spiral.
- (Note: this trial DID hit the ceiling this time. The 56-min solve from the mini-flight was under n_concurrent=5; under n_concurrent=16 the same task may have been slower due to embedding-service contention. Post-run hypothesis to verify.)

### 2.3 seed_skills_dir / Plan D (NEW, post mini-flight fix)
- Pre-mini-flight full run: `q_table.json = {}`, manifest `{"skills": []}`, 0 Skill calls (SkillQ pipeline silently bypassed)
- Post-fix full run: q_table populated with 42 seeded skills on every trial, 6 trials made Skill tool_use calls
- Verified by 1-task seed-verify smoke: Skill tool_use count went 0 → 1

### 2.4 Layer 3 (Edit) and Layer 4 (Create)
- Disabled during this run due to `editor_model: "openai/gpt-4o"` default (no OPENAI_API_KEY in env)
- Bridge swallowed the error → trial rewards still valid
- **P0 follow-up**: set `editor_model: anthropic/${ANTHROPIC_MODEL}` in method-config

## 3. Carry-over / 不修

| ID | Status | Note |
|----|--------|------|
| **#89** host-side ceiling | Unnecessary — Harbor ceiling is working at ~3700-4500s | Drop or simplify |
| **#87** skill-call rate | 6/89 = 6.7% (low; was 0% before fix). Need prompt tuning | Open |
| **#88** b_max LRU docs | Low pri, defer | — |
| **#62/#90** sudo cleanup | Non-blocking | — |
| **library_gap_skill_description** | Cannot evaluate (edit layer broken) | Blocked by #10 |
| Success-path gap description | Cannot evaluate (edit layer broken) | Blocked by #10 |

## 4. Per-trial Duration Distribution

| Bucket | Count | Notes |
|--------|-------|-------|
| <60s | 4 | log-summary-date-ranges, fix-git, modernize-scientific-stack, git-leak-recovery, openssl-selfsigned-cert, kv-store-grpc, vulnerable-secret — most passed |
| 60-300s | 36 | Median trial; most pass |
| 300-900s | 30 | Heavy domain work |
| 900-1800s | 12 | Image/audio/codegen tasks |
| 1800-3600s | 3 | Hard but completing |
| >3600s (ceiling) | 7 | write-compressor, make-mips-interpreter, train-fasttext, caffe-cifar-10, make-doom-for-mips, circuit-fibsqrt, path-tracing — 5 of 7 failed |

## 5. Top failures (suggesting where SkillQ could help next)

| Task | Duration | Why it failed | Skill call? |
|------|----------|---------------|-------------|
| write-compressor | 3876s | Ceiling kill — agent still working | 0 |
| train-fasttext | 4455s | Ceiling kill — 38 steps only | 0 |
| caffe-cifar-10 | 3984s | Ceiling kill — 80 steps | 0 |
| path-tracing | 3892s | Ceiling kill — image rendering | 0 |
| circuit-fibsqrt | 3883s | Ceiling kill — Fibonacci circuit | 0 |
| make-mips-interpreter | 3928s | Ceiling kill — 524 steps | 0 |
| make-doom-for-mips | 3909s | **PASS but** hit ceiling — 964 steps | 0 |
| gpt2-codegolf | 1249s | 6 steps → NonZeroExit | 0 |
| regex-chess | 1528s | 8 steps → NonZeroExit | 0 |
| schemelike-metacircular-eval | 1687s | 33 steps → NonZeroExit | 0 |
| chess-best-move | 1190s | 109 steps, vision misparse | 1 |

## 6. Skill-call positive cases (where Skill tool was actually used)

6 trials made Skill calls (out of 89):
- pytorch-model-recovery (1 call) → PASS
- chess-best-move (1 call) → FAIL
- gcode-to-text (1 call) → FAIL
- db-wal-recovery (1 call) → PASS
- mailman (1 call) → PASS
- nginx-request-logging (1 call) → PASS

**3 of 6 trials with Skill calls passed (50%) — same as overall pass rate. Not enough signal to claim skill calls help.**

This is consistent with #87's "skill-call rate still low" finding — even with skills available, the agent rarely calls them. The seed library is heavy on web/cloud/blockchain skills, mostly irrelevant to TB 2.0.

## 7. P0 Follow-ups (block paper claims)

### 7.1 Fix `editor_model` default (Task #10)
```yaml
# In experiments/configs/method_tb2_skillq_full.yaml, add:
editor_model: anthropic/${oc.env:ANTHROPIC_MODEL,deepseek-v4-flash}
```
- Unblocks: Rule 5 auto-extract, library_gap_skill_description path, Q-table real reward updates
- Cost: 1 line change + re-run

### 7.2 Investigate skill-call rate (Task #87)
- 6.7% is still too low — paper needs >20% to claim SkillQ layer contributes
- Hypothesis: seed library skills don't match TB 2.0 task descriptions (web/blockchain/cloud vs system/network/code tasks)
- Plan: examine agent reasoning when skills are available but not chosen; consider tighter prompt injection in HOOK_INSTRUCTIONS_SNIPPET

### 7.3 Add auto-extract trigger (success path)
- Current code only triggers extract on failure (Rule 5)
- Success-path extraction requires moving extract call out of the failure branch
- Lower priority — paper benefits are clearer from failure-path data

## 8. Artifacts

- `output/tb2_skillq_full__2026-06-25/` — full run output (89 trial dirs, q_table, manifest, trajectory per trial)
- `output/tb2_skillq_full__2026-06-24/` — old baseline preserved for comparison
- `output/tb2_skillq_miniflight_10__2026-06-25/` — pre-fix mini-flight (skill-call=0)
- `output/tb2_skillq_seedverify_1__2026-06-25/` — post-fix 1-task smoke (skill-call=1, q_table populated)
- `experiments/configs/tb2_skillq_full.yaml` — updated job_name to 2026-06-25
- `experiments/configs/method_tb2_skillq_full.yaml` — NEW, adds seed_skills_dir
- `experiments/configs/tb2_skillq_miniflight_10.yaml` — 10-task pre-flight config
- `experiments/configs/tb2_skillq_seedverify_1task.yaml` — 1-task seed-verify smoke
- `experiments/configs/method_tb2_skillq_miniflight.yaml` — miniflight method-config
- `experiments/configs/method_tb2_skillq_seedverify.yaml` — seed-verify method-config
- `output/miniflight_logs/analyze_full_89.py` — post-run analyzer

## 9. Recommended next-run config (after editor_model fix)

```yaml
# experiments/configs/method_tb2_skillq_full.yaml
editor_model: anthropic/${oc.env:ANTHROPIC_MODEL,deepseek-v4-flash}
# (everything else as-is)
```

This single change unblocks:
- Auto-extract on failure (Rule 5) → new skills created
- Q-table updates with real reward signal
- library_gap_skill_description path evaluation
- Success-path gap description experiment

Expected outcome: auto-extracted skills accumulate during the 89-task run, providing relevant TB 2.0 skills that the agent should call more frequently.