# SkillQ 论文实验上下文快照(2026-06-25)

---

## 1. 论文创新方法、核心公式与整体架构

### 1.1 问题

让 LLM Agent 在 TB 2.0 (89 个 Docker 任务) 上自动积累"技能库",避免重复犯错。SkillsVote 是上游 baseline,但 per-intent-Q 表 + 概率性 admission/eviction 在小规模库下失效。

### 1.2 四层方法(SkillQ)

```
┌────────────────────────────────────────────────────────────────┐
│ L1 检索 (Retrieval)                                            │
│   embedding cosine + global Q + UCB                            │
│   score = (1-λ) · sim_z + λ · q_z + c_ucb · √(logN/(n+1))     │
│   λ=0.5, c_ucb=0.5                                             │
├────────────────────────────────────────────────────────────────┤
│ L2 反馈归因 (Attribution) — per-trial                          │
│   6-class enum + knowledge_to_extract + library_gap_…(2026-06-25)│
│   LLM-as-judge, model=deepseek-v4-flash via litellm            │
├────────────────────────────────────────────────────────────────┤
│ L3 编辑 (Edit) — near-miss                                     │
│   失败 + 用过相关 skill → EDIT_PROMPT 局部 patch                │
│   约束: ≤20% token, name 不变,无新依赖                          │
├────────────────────────────────────────────────────────────────┤
│ L4 创建 (Create) — Rule 2 + Rule 5                             │
│   Rule 2: N 次 success_viewed/no_skill_seen → batched extract  │
│   Rule 5: failure + knowledge_to_extract≠'' → batched extract  │
│   claude --print 子进程, sandbox + CACHEDIR.TAG                 │
└────────────────────────────────────────────────────────────────┘
```

### 1.3 核心公式

**Eq.4 (global-Q refactor, 无 intent dim)**

```
score(s) = (1-λ) · sim_z(s,task) + λ · q_z(s) + c_ucb · √(log N_total / (n_s+1))
```

**Q-update (LibManager.update_q)**

```
q_new = q_old + α · (r - q_old)              # α=0.3
```

**Bounded library**: `b_max=100`,超 LRU 淘汰。

---

## 2. 实验环境 / 数据集 / 固定超参 / 依赖

### 2.1 环境

- Python 3.12, uv-managed venv (`.venv/`)
- Harbor (vendored trial runner, `.venv/lib/.../harbor/trial/trial.py`)
- 容器: `skills_vote/<task>:20260604` 预构建
- uv 缓存预热路径:`/home/gonern/.skillq_cache/uv`(含 `.git`/`.gitignore`/`.lock`/`CACHEDIR.TAG` 标记,sdists-v9/),**RW bind mount** (2026-06-25 Bug #4 修复)

### 2.2 数据集

- **TB 2.0 full**: 89 task, `input/terminal-bench/` (`.gitignore`)
- `SkillQ_INPUT_ROOT` env var 覆盖
- 任务定义:本地 vendored,不走 registry 下载

### 2.3 固定超参(MethodConfig defaults)

| 字段 | 值 | 来源 |
|------|-----|------|
| `alpha` | 0.3 | Q-learning rate |
| `beta` | 0.5 | (历史参数,未在 main path 使用) |
| `k1` | 10 | top-k retrieval 第一档 |
| `k2` | 3 | top-k retrieval 第二档 |
| `b_max` | 100 | lib 容量上限 |
| `seed_initial_q` | 0.5 | optimistic prior |
| `lambda_` | 0.5 | Eq.4 sim/Q 混合 |
| `c_ucb` | 0.5 | Eq.4 UCB 系数 |
| `attribution_model` | `anthropic/${ANTHROPIC_MODEL}` | litellm provider prefix |
| `agent_timeout_multiplier` | **1.0** (2026-06-25 fix) | 见 §5 bug |
| `override_timeout_sec` | 3600.0 | absolute ceiling |
| `max_retries` | 0 (baseline) / 3 (tb2) | Harbor retry policy |
| `n_concurrent_trials` | 16 | full run 并发 |
| `sim_gate_min_score` | 0.7 | 检索相似度门槛 |

### 2.4 依赖

- `litellm` (provider routing)
- `requests` (hook → embed service)
- `claude` CLI (auto-extract 子进程)
- 嵌入服务:`skillq/method/embedding_service.py` uvicorn standalone
- 无 GPU,无训练

---

## 3. 核心代码片段(标注文件路径)

### 3.1 Eq.4 评分 + hook 重排

`skillq/paper_mode/hook.py:204-280`

```python
def _zscore(values): ...
def _cosine(a, b): ...

def rerank_with_ucb(query_emb, available_skills, q_table, n_total,
                    lambda_=0.5, c_ucb=0.5):
    sims = [_cosine(query_emb, s.emb) for s in available_skills]
    qs = [q_table.get(s.id, seed_initial_q) for s in available_skills]
    sim_z, q_z = _zscore(sims), _zscore(qs)
    scored = []
    for s, sz, qz in zip(available_skills, sim_z, q_z):
        n_s = s.n_uses
        ucb = c_ucb * math.sqrt(math.log(n_total + 1) / (n_s + 1))
        scored.append((s.id, (1-lambda_)*sz + lambda_*qz + ucb))
    return sorted(scored, key=lambda x: -x[1])
```

### 3.2 Seed-from-disk + Q-table 持久化

`skillq/method/state.py:167-249`

```python
@staticmethod
def scan_seed_dir(seed_dir, *, q_initial=0.5):
    """Walk seed_dir, build (skills, q_table) from <dir>/SKILL.md."""
    skills, q_table = {}, []
    for skill_dir in sorted(p for p in seed_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():        # 静默跳过无 SKILL.md 子目录
            continue
        skill_id = skill_dir.name        # dir 名 = primary id (与 Claude Code Skill tool 对齐)
        skills[skill_id] = {
            "body": skill_md.read_text(),
            "n_retrievals": 0, "n_uses": 0, "n_success": 0,
            "metadata": {"source": "seed_dir", "seed_dir": skill_id},
        }
        q_table.append([skill_id, q_initial])
    return skills, q_table
```

### 3.3 Bridge 入口:on_trial_started / on_ended

`skillq/paper_mode/bridge.py:640-700`

```python
async def on_trial_started(event):
    lib, mgr = Qlib(), LibManager()
    state = QlibState(state_path)
    state.ensure_seeded(lib, mgr, method.seed_skills_dir,
                        seed_initial_q=method.seed_initial_q)
    # ... 写 staging dir, 起 hook, 准备检索

async def on_trial_ended(event):
    r_task = event.result.verifier_result.reward  # 0 or 1
    trajectory = load_trajectory(trial_dir)
    attribution = await self.attribution_llm(ATTRIBUTION_PROMPT.format(...))
    # Rule 2 (success) / Rule 5 (failure) → batched extract
    await self._attribution_and_extract_dispatch(
        r_task, attribution, trajectory, ...)
```

### 3.4 Attribution LLM 输出

`skillq/method/attribution.py`

```python
class TrialAttribution(BaseModel):
    overall_attribution: Literal[
        "success_skill_used", "success_viewed_skill_but_not_used",
        "success_no_skill_seen",
        "fail_skill_issue", "fail_agent_issue", "fail_env_issue",
    ]
    overall_rationale: str
    subtasks: list[Subtask]
    knowledge_to_extract: str
    library_gap_skill_description: str = ""   # 2026-06-25 新增
```

### 3.5 失败路径 SKILL 合成(关键 prompt)

`skillq/method/prompts.py:351-393`

```
合成 SKILL.md 必须包含 2 个结构段:
(a) Diagnostic checklist — 2-4 条可测试检查
(b) Stop signal — 明确阈值 + reset 动作
(e.g. circuit-fibsqrt 7 versions / 115min case study)
Preferred seed = library_gap_skill_description (覆盖 knowledge_to_extract)
```

### 3.6 Hook Prompt (Method B agent-facing, 2026-06-25 rewrite)

`skillq/paper_mode/agentic_search.py:342-391`

```python
HOOK_INSTRUCTIONS_SNIPPET = """\
# Curated skills (Method B) — REQUIRED USAGE
1. ls $CLAUDE_CONFIG_DIR/skills/, 选 description 最匹配的
2. 仅当 description 明确匹配任务时调用 Skill("<name>")
3. 不匹配时输出 LIBRARY_GAP: <one-line gap description>
   (host 用来 auto-extract 新 skill)
4. 调用错误 skill 会污染 Q-table ranking
(原"calling the wrong skill is fine"已删除 — circuit-fibsqrt 合规剧场根因)
"""
```

### 3.7 Container wiring — uv cache RW bind

`skillq/paper_mode/container_wiring.py:650-700`

```python
# 2026-06-25 Bug #4 round 2: uv 0.9.5 truncate+rewrite marker files
# on every container startup. RO bind blocks truncate → verifier aborts.
# Fix: omit `read_only` from mount dict (ServiceVolumeConfig.default
# = RW for bind).
mounts.append({
    "type": "bind",
    "source": "/home/gonern/.skillq_cache/uv",
    "target": "/root/.cache/uv",
    # no read_only key → RW
})
```

### 3.8 Prime uv cache

`skillq/paper_mode/cli.py:140-220`

- 创建 `cache/`、`wheels/`、`environments/`、**`sdists-v9/`** 四个子目录
- 每个子目录写入 `.git`、`.gitignore`、`.lock`、`CACHEDIR.TAG`

---

## 4. 已跑完实验结果、现有指标

### 4.1 关键 smoke (2026-06-25)

| Smoke | 结果 | 备注 |
|-------|------|------|
| `tb2_skillq_smoke_bug45` (chess-best-move) | **reward = 1.0** ✓ | Bug #4 round 2 修复后,RW bind mount 生效 |
| `tb2_git_smoke_hook_v2` | pass | uv cache sdists-v9 修复 |

### 4.2 历史 full run (有问题的,作为 baseline 对照)

| Run | 日期 | 关键观察 |
|-----|------|---------|
| `tb2_skillq_full__2026-06-24` | 06-24 | circuit-fibsqrt 跑 115min / $56 / 7 versions gen.py — wall-clock ceiling **未生效**(根因见 §5) |
| `tb2_skillq_full__2026-06-22/23__pre_refactor` | 06-22/23 | 早期版本,b_max/eviction 未稳定 |

### 4.3 已上线的 prompt refinements (2026-06-25)

- ✅ Edit 1: HOOK_INSTRUCTIONS_SNIPPET 移除"wrong skill is fine",加 LIBRARY_GAP 指令
- ✅ Edit 2: ATTRIBUTION_PROMPT 加 `library_gap_skill_description` 字段
- ✅ Edit 3: BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT 强制 Diagnostic checklist + Stop signal + gap-seed preference
- ✅ 77 测试全过(`test_prompt_refinements.py` 13 个 + `test_bridge_extract.py` 扩展 + `test_container_wiring.py` 更新)

---

## 5. 现存代码 / 实验问题

### 5.1 ✅ 已修复(2026-06-25)

| Bug | 根因 | 修复 |
|-----|------|------|
| #4 (round 1) sdists-v9 缺失 | uv 找不到 sdists | `cli.py:prime_uv_cache` 加 `sdists-v9/` |
| #4 (round 2) uv cache RO 拒写 `.git` | uv 0.9.5 每次启动 truncate marker | `container_wiring.py` 改 RW bind mount |
| Compliance-theater prompt | "wrong skill is fine" 让 agent 乱调 skill 喂 Q | `agentic_search.py:HOOK_INSTRUCTIONS_SNIPPET` 重写 |
| Circuit-fibsqrt debug spiral | 合成 SKILL.md 无防呆结构 | `BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` 加 checklist + stop signal |
| Wall-clock ceiling 不生效 | **Harbor `_resolve_step_timeout` = `min(override, max) × multiplier`** —— multiplier 乘在 override 上,实际 ceiling = 3600 × 4.0 = **14400s** | `tb2_skillq_full.yaml` 把 `agent_timeout_multiplier: 4.0` → `1.0` |

### 5.2 ⚠️ Carry-over / 未修

| ID | 问题 | 阻塞? |
|----|------|-------|
| **#89** | 在 `SkillQClaudeCodeAgent.run()` 加 host-side 3600s 第二层 ceiling(防 Harbor 升级改语义) | 全量 run 后做 |
| **#87** | skill-call rate 仅 19/100 (TB2 full) — agent 不愿调 Skill 工具 | 调研中 |
| **#88** | `b_max=100` 满后 LRU 淘汰行为未文档化 | 低优 |
| #62/#90 | 4 个 root-owned output dir 待 sudo 清理 | 非阻塞 |
| Library gap description | 当前 `library_gap_skill_description` 全程 thread-through 已实现,但只有 failure-path 测试覆盖,success-path 暂未触发 | 全量 run 后回看 |

### 5.3 测试覆盖

- `test_prompt_refinements.py`: 13 个 (HOOK/ATTRIBUTION/EXTRACT prompt + TrialAttribution schema)
- `test_bridge_extract.py`: gap_description thread-through
- `test_container_wiring.py`: RO→RW 切换
- `test_classify_trial_failure.py`、`test_paper_hooks.py`: 既有用例

---

## 6. 接下来要做的实验 + 代码任务

### 6.1 全量 TB 2.0 run(用户授权后立即跑)

```bash
# jobs_dir=output, job_name=tb2_skillq_full__2026-06-25
# n_attempts=1, n_concurrent_trials=16
# override_timeout_sec=3600.0 + agent_timeout_multiplier=1.0  ← 真实 ceiling 3600s
# retry.max_retries=0 (一次性,失败直接走 Rule 5 attribution)
# enable_auto_extract=True (默认)
```

**期望产物**:

- 89 个 trial `result.json` + `trajectory.json` + `agent/sessions/`
- 每个 trial 触发最多一次 attribution LLM call (deepseek-v4-flash)
- 失败的 trial 累积到阈值后触发 batched extract (claude --print)
- 全程 wall-clock 估计:60-90 min agent step + 10-15% extract 开销

**跑完必读**:

1. trial 时长分布 —— 是否还有 ≥1h 的 case(若有,说明 skill 库的 avoidance guidance 不到位)
2. skill-call rate —— 是否还是 19/100
3. auto-extract 产出的新 skill 数量、描述命中率、是否触发 Diagnostic checklist/Stop signal 结构
4. attribution `library_gap_skill_description` 命中率(三个 gap enum 实际占比)
5. reward 分布:baseline 89-task 对照

### 6.2 代码 task 列表

| 优先级 | Task | 内容 | 何时做 |
|--------|------|------|--------|
| **P0** | #89 | 在 `SkillQClaudeCodeAgent.run()` 加 host-side 3600s `time.monotonic()` ceiling + `AgentTimeoutError` | 全量 run 后 |
| P1 | success-path gap description | 让 `success_no_skill_seen` 也触发 auto-extract(目前只 failure-path 走 Rule 5) | 全量 run 后看分布 |
| P1 | skill-call rate | 调研为何 19/100:hook 是否过严 / prompt 是否过弱 / CLAUDE.md 顺序 | 全量 run 后 |
| P2 | #88 | 文档化 b_max=100 LRU 淘汰 | 低优 |
| P2 | #62/#90 | sudo 清理 4 个 root-owned output dir | 方便起见 |
| P3 | cost-aware early stop | behavior counter (Edit 同一文件 >N 次 → kill) | 待数据驱动决策 |
| P3 | metadata-aware prior | 检索时把 skill 的 prior domain tag 加入 Eq.4 | 实验性 |

### 6.3 不做 (out of scope)

- 训练任何模型
- 改 Harbor 源码(只消费其行为)
- 跑 SkillsVote baseline 重对比(已确认原 baseline 不在 baseline.yaml)

---

## 7. 当前 git 状态关键点

```
M  experiments/configs/tb2_skillq_full.yaml   ← 今日改 multiplier
M  skillq/method/prompts.py                    ← 三层 prompt refinement
M  skillq/method/attribution.py                ← 新增 gap field
M  skillq/method/extractor.py                  ← gap thread-through
M  skillq/paper_mode/agentic_search.py         ← HOOK rewrite
M  skillq/paper_mode/bridge.py                 ← gap dispatch
M  skillq/paper_mode/container_wiring.py       ← uv RW bind
M  skillq/paper_mode/cli.py                    ← sdists-v9 prime
D  skills/                                     ← 清空,准备干净 baseline
D  skillq/method/sub_task_verifier.py          ← 旧 verifier 已删
+  tests/test_prompt_refinements.py            ← 新增 13 个 snapshot 测试
```

**最近 commit:**

```
5dd0129 fix(cli): prime-uv-cache pre-creates .gitignore + .lock in all cache subdirs
9050873 fix(cli): prime-uv-cache writes CACHEDIR.TAG so uvx accepts RO mount
62d495a fix(cli): prime-uv-cache uses system 'pip download', not 'uv pip install --target'
f5a2947 fix(paper): Bug #4+#5 — uv cache warm-bind + post-trial chown
1a6885b tune(gate): relax sim_gate_min_score 0.75 → 0.7
```

---

## 8. 启动命令速查

```bash
# 全量 run
python -m experiments.run.run_benchmark --benchmark tb2_skillq_full

# 单 task smoke (复现)
python -m experiments.run.run_benchmark --benchmark tb2_skillq_smoke_bug45

# 测试
.venv/bin/python -m pytest tests/test_prompt_refinements.py tests/test_bridge_extract.py tests/test_container_wiring.py -v
```

---

**快照生成时间**: 2026-06-25
**核心变更**: 三层 prompt refinement + uv cache RW bind + multiplier bug 修复 + 干净 skills/ baseline。
**下一步**: 用户授权后启动 TB 2.0 全量 89-task run。
