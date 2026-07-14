# SkillQ 全量实验最终总结（论文 Camera-Ready 用）

**日期**: 2026-07-01 至 2026-07-12
**基准**: Terminal-Bench 2.0 (89 任务)
**Agent 模型**: deepseek-v4-flash (全轮) / deepseek-v4-pro (hard6)
**Embedding 模型**: text-embedding-v4 (dashscope)
**检索模式**: Pull (UserPromptSubmit + PreToolUse hook)
**并发**: R1 = 4, R2-R5 = 8
**超时**: 3600s/trial (R1-R3), 7200s/trial (R4-R5)

---

## 1. 实验设计

SkillQ 是一种四层运行时强化学习架构，用于在 Terminal-Bench 2.0 基准上渐进学习可复用的 Agent 技能：

| Layer | 名称 | 机制 |
|:---:|---|---|
| L1 | Retrieval | 两阶段检索：cosine + BM25 杂交 → Hard Gate 过滤 → multiplicative/additive UCB 评分 |
| L2 | Agent Run | Pull-mode 强制注入 Top-K 技能，agent 必须调用 Skill() 后才能使用其他工具 |
| L3 | Attribution | LLM 分析 trial 轨迹，输出 5-Enum 归因（`SUCCESS_SKILL_USED`, `SUCCESS_NO_SKILL_SEEN`, `FAILURE_SKILL_USED`, `FAILURE_SKILL_NOT_USED`, `FAIL_ENV_ISSUE`） |
| L4 | Evolve | 基于归因分流：`FAILURE_SKILL_USED` → L3 Edit（增量修改现有技能）；`SUCCESS_NO_SKILL_SEEN` / `FAILURE_SKILL_NOT_USED` → L4 Create（从成功/失败轨迹提取新技能） |

### 两轮实验系列

为验证 SkillQ 的从零自举能力和 Q-learning 增量效果，先后进行了两轮独立实验系列：

**系列 A: From-Scratch（从零自举，R1-R4）**
- R1: 0 种子技能 + 空 Q-table，4 并发冷启动
- R2-R4: 继承上一轮 Q-table + 技能库，8 并发增量学习

**系列 B: Zero-Start（独立从零，R1-R5）**
- 每轮均从 0 种子技能 + 空 Q-table 开始（`reuse_q_table=false`）
- R4-R5: 排除 4 个硬任务（caffe-cifar-10, extract-moves-from-video, make-mips-interpreter, video-processing，全部计为 reward=0），任务数从 89 降为 85
- R4-R5: 超时从 1h 延长至 2h

---

## 2. 系列 A: From-Scratch 结果

| Round | 通过率 | Mean | Skills | Q entries | 非默认 Q | Q 范围 | 耗时 | 关键变更 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| R1 | 48/89 (53.9%) | 0.539 | 67 | 67 | 4 (6.0%) | 0.44–0.57 | ~15h | 零样本冷启动, 4 并发, 含 sleep 中断 |
| R2 | 44/89 (49.4%) | 0.494 | 94 | 90 | 57 (63.3%) | 0.31–0.70 | ~3h | Pull-mode MUST-call 修复, 8 并发 |
| R3 v1 | 51/87 (58.6%) | 0.573 | 92 | 92 | 73 (79.3%) | 0.25–0.74 | ~3.5h | Per-trial extract prompt (LLM 格式 bug 导致 10 次 error) |
| R3 v2 | 43/85 (50.6%) | 0.483 | 97 | 97 | 77 (79.4%) | 0.19–0.77 | ~3.5h | Per-trial extract prompt (JSON 转义修复) |
| **R4** | **49/88 (55.7%)** | **0.551** | **102** | **102** | **82 (80.4%)** | **0.15–0.81** | **3.6h** | **BM25 杂交检索** |

### 2.1 Q-Learning 收敛 (系列 A)

```
R1:  67 Q entries,   6% non-default, Q ∈ [0.44, 0.57]
R2:  90 Q entries,  63% non-default, Q ∈ [0.31, 0.70]   (+57pp)
R3:  97 Q entries,  79% non-default, Q ∈ [0.19, 0.77]   (+16pp)
R4: 102 Q entries,  80% non-default, Q ∈ [0.15, 0.81]   (+ 1pp)
```

Q-table 从初始全默认（94% 在 seed Q=0.5）收敛到 80% 分化，Q 值范围从 0.13 扩宽到 0.66。Q-learning 单调提升了 Q 值的区分度。

### 2.2 Q 值与任务成功率的相关性 (R2 数据)

| Q 范围 | Trials | Pass | Pass Rate |
|---|:---:|:---:|:---:|
| Q ≤ 0.35 | 10 | 0 | 0% |
| Q = 0.40 | 15 | 0 | 0% |
| Q = 0.45 | 8 | 0 | 0% |
| Q = 0.50 (默认) | 15 | 7 | 47% |
| Q = 0.55 | 14 | 13 | 93% |
| Q = 0.60 | 20 | 18 | 90% |
| Q ≥ 0.65 | 7 | 7 | 100% |

**Q ≥ 0.55 对应 90%+ 通过率；Q ≤ 0.45 对应 0% 通过率。** 单调相关性强。

### 2.3 跨轮稳定性 (R1→R4, 84 共同 scored tasks)

| 模式 | 数量 | 解读 |
|---|---|---|
| 稳定通过 | 41 (49%) | 确定性成功 |
| 稳定失败 | 31 (37%) | 超出 agent 能力 |
| 改善 (0→1) | 6 (7%) | 技能转移有效 |
| 退化 (1→0) | 6 (7%) | 噪声或低 Q 技能误导 |
| **稳定性** | **72/84 = 86%** | 任务难度是支配性因素 |

### 2.4 BM25 杂交效果 (R4)

在 L1 检索中插入 BM25 关键词评分（`max(cosine, BM25_L2_norm)` 融合），不改 Gate/UBC/Q-table 逻辑：

| 任务 | R3 v2 (纯 cosine) | R4 (BM25 hybrid) |
|---|---|---|
| crack-7z-hash | FAIL | PASS |
| build-pmars | FAIL | PASS |
| build-cython-ext | FAIL | PASS |

R4 整体通过率 55.7%（+5.1pp vs R3 v2），error 率 4 轮最低。BM25 在术语匹配场景（"7z", "debian", "cython"）显著改善了检索精度。

---

## 3. 系列 B: Zero-Start 结果

R1 从零冷启动（空技能库 + 空 Q-table, `reuse_q_table=false`），R2-R5 **继承上一轮的技能库和 Q-table**（`reuse_q_table=true`），与系列 A 的继承策略一致。共 5 轮完整实验（对应 zerostart 输出目录的 ZS R2-R6；ZS R1 使用不同的 sim_gate=0.7 配置，不计入本系列）。

| Round | 通过率 | Skills | Q entries | 非默认 Q | 耗时 | 配置 |
|:---:|:---:|:---:|:---:|:---:|:---:|---|
| R1 | 49/89 (55.1%) | 62 | 62 | 10% | ~254min | 冷启动, 1h timeout, 89 tasks |
| R2 | 48/89 (53.9%) | 82 | 82 | 60% | ~233min | 继承 R1 技能+Q, 1h timeout |
| R3 | 47/89 (52.8%) | 93 | 93 | 68% | ~227min | 继承 R2 技能+Q, 1h timeout |
| R4 | 49/85 (57.6%) | 104 | 104 | 66% | ~304min | 继承 R3 技能+Q, 2h timeout, 85 tasks |
| R5 | 42/85 (49.4%) | 112 | 112 | 69% | ~422min | 继承 R4 技能+Q, 2h timeout, 85 tasks |

> 注：R1-R3 为 89 任务全量；R4-R5 排除 4 个硬任务（caffe-cifar-10, extract-moves-from-video, make-mips-interpreter, video-processing），分母 85。Skills = 轮末技能库大小，Q entries = 轮末 Q-table 条目数。

### 3.1 Q-Learning 收敛 (系列 B)

```
R1:  62 Q entries,  10% non-default  (冷启动)
R2:  82 Q entries,  60% non-default  (+50pp, 技能库扩大 + Q 继承)
R3:  93 Q entries,  68% non-default  (+ 8pp)
R4: 104 Q entries,  66% non-default  (− 2pp, 新技能稀释)
R5: 112 Q entries,  69% non-default  (+ 3pp)
```

Q-table 跨轮继承使 Q 值从几乎全默认（R1 冷启动, 90% 在 seed Q=0.5）逐步收敛到 69% 分化。R4 的非默认比例小幅下降（68%→66%），原因是延长超时到 2h 后 L4 创建了更多新技能（Q=0.5），稀释了已有技能的 Q 分化比例。

### 3.2 R5 最终状态

```
技能库: 112 SKILL.md
Q-table: 112 entries, 69% non-default (77/112)
Q range: [0.201, 0.759]
Pipeline step: 371 (累计处理 371 个 trial)
```

**Top-10 高分技能 (Q ≥ 0.70):**

| 技能 | Q 值 |
|---|---|
| cobol-python-port | 0.759 |
| extract-elf-memory | 0.757 |
| tune-mjcf | 0.754 |
| multi-source-merge | 0.743 |
| async-task-shutdown | 0.743 |
| git-leak-recovery | 0.737 |
| compile-compcert | 0.734 |
| fix-overfull-hbox | 0.731 |
| nginx-custom-logging | 0.724 |
| crack-7z-hash | 0.722 |

### 3.3 通过率分析

系列 B 的 R1-R4 通过率平坦在 53-58%，R5 下降至 49%（净 -7 pass vs R4）。Q-learning 成功区分了技能质量（10% → 69% 非默认 Q），但未能转化为通过率提升。可能的根因：

1. **新技能冷启动问题**：L4 创建的新技能 Q=0.5 启动，UBC bonus（c_ucb=0.0）不足以使其在同轮内被检索到；技能价值需跨轮体现
2. **检索覆盖率天花板**：即便加入 BM25 杂交，仍有约 25% trial 无任何技能匹配（embedding 语义鸿沟 + Hard Gate 门槛）
3. **硬任务集群**：4 个硬任务在 R1-R5 中从未通过（去除后 R4 57.6% 是系列 B 最优）
4. **R5 回归**：R5 运行时间异常长（422min），13 个 Pass→Fail 回归，可能与 Q 值衰减机制的引入有关

### 3.4 R4→R5 回归分析

R5 相对于 R4 出现 13 个 Pass→Fail 回归和 6 个 Fail→Pass 改善，净 -7 pass。回归的可能原因：
- L4 edit 行为不确定：R5 的 `attribution_result.json` 持久化代码在编辑时被意外删除后恢复，R5 实际运行时 L4 edit 可能未正确触发
- Q 值衰减机制（`new_Q = old_Q × edit_dist + 0.5 × (1 − edit_dist)`）在 R5 首次引入，可能导致之前高分技能被过度惩罚

---

## 4. 硬任务专项 (Hard6)

在标准 R1-R5 之外，使用 **deepseek-v4-pro** + **2h timeout** 对 6 个硬任务进行了 3 轮专项测试：

| 任务 | 最佳结果 | 说明 |
|---|---|---|
| write-compressor | PASS (1/3) | LZ77 压缩器实现，唯一通过的任务 |
| caffe-cifar-10 | FAIL (0/3) | Caffe CIFAR-10 训练，超时 |
| extract-moves-from-video | FAIL (0/3) | 视频动作提取，超时 |
| make-mips-interpreter | FAIL (0/3) | MIPS 解释器实现，agent 能力不足 |
| video-processing | FAIL (0/3) | 视频处理流水线，超时 |
| train-fasttext | FAIL (0/3) | FastText 训练，agent 能力不足 |

> 最优成绩 1/6，model 从 v4-flash 升级到 v4-pro 仅解锁 1 个硬任务。说明剩余 5 个任务的瓶颈不在模型能力，而在任务本身的时间需求（超时）或问题复杂度（agent 策略空间过大）。

---

## 5. 两轮系列对比

两轮系列采用相同的设计原则：R1 冷启动（`reuse_q_table=false`），后续轮次继承技能库和 Q-table（`reuse_q_table=true`）。主要差异在于并发数、超时和 Hard Gate 阈值。

| 指标 | 系列 A (From-Scratch) | 系列 B (Zero-Start) |
|---|---|---|
| 轮数 | 4 (R1-R4) + R3 复跑 | 5 (R1-R5) |
| R1 冷启动 | 是 (`reuse_q_table=false`) | 是 (`reuse_q_table=false`) |
| R2+ 继承 | 技能 + Q-table (`reuse_q_table=true`) | 技能 + Q-table (`reuse_q_table=true`) |
| 并发 | R1=4, R2-R4=8 | R1-R5=8 |
| 超时 | 3600s | R1-R3=3600s, R4-R5=7200s |
| sim_gate | R1-R3=0.5, R4=0.7 | 0.5 (统一) |
| 最优通过率 | R4: 55.7% (BM25, 1h) | R4: 57.6% (2h timeout, 85 tasks) |
| Q 收敛峰值 | 80% non-default (R4) | 69% non-default (R5) |
| 技能库增长 | 67 → 102 (+52%, 4 轮) | 62 → 112 (+81%, 5 轮) |
| 关键发现 | BM25 +5.1pp; Q≥0.55→90%+ pass | R5 回归 42/85; 2h timeout 未显著改善 |

### 5.1 分析

1. **通过率天花板**：两轮系列的最优通过率均在 55-58%，未突破 60%。任务难度（约 37% 任务从未通过）是支配性因素，与 Q-table 继承策略无关。

2. **系列 B R5 回归严重**：R5 的 42/85 (49.4%) 是两轮系列的最差成绩，净 -7 pass vs R4。运行时间异常长（422min vs R4 的 304min），表明部分任务陷入长时间运行但未通过。可能原因：(a) Q 值衰减机制在 R5 首次引入导致高分技能被过度惩罚，(b) L4 edit 的 `attribution_result.json` 持久化代码在编辑时被意外删除后恢复，R5 实际运行时 L4 edit 未正确触发。

3. **2h timeout 效果有限**：系列 B R4-R5 使用 7200s 超时但通过率未超越系列 A R4 的 3600s。仅排除了 4 个永远超时的硬任务（分母变小导致通过率略升），但未解锁新的通过任务。

4. **并发影响**：系列 A R1 使用 4 并发（~15h，含 sleep 中断），系列 B R1 使用 8 并发（~4h）。并发翻倍将 wall-clock 时间缩短了约 4 倍，对通过率无显著影响。

---

## 6. 仍存在的问题与限制

1. **通过率平坦**：两轮系列的最优通过率均未突破 58%，Q-learning 的分化能力（10%→69%/80% non-default Q）未转化为通过率增益。可能原因：(a) 单轮噪声大（±5pp 方差），(b) 技能冷启动延迟——新技能 Q=0.5 需跨轮才能被检索到，(c) 任务难度是支配性因素——约 37% 任务从未通过

2. **检索覆盖率天花板**：BM25 杂交后仍有 ~25% trial 无技能匹配。Hard Gate=0.7 + text-embedding-v4 的 problem↔solution 语义鸿沟是主要瓶颈

3. **新技能冷启动**：L4 创建的新技能 Q=0.5 启动，UBC bonus（c_ucb=0.0）不足以在同轮内被检索到。技能价值需跨轮体现——这在两轮系列中均有体现（技能库持续增长但同轮利用率低）

4. **L4 Edit 质量不确定**：Q 值衰减机制（基于 embedding edit distance）的理论依据薄弱，可能过度惩罚高分技能。R5 回归（42/85）与此机制的引入时间吻合

5. **硬任务瓶颈**：6 个硬任务中 5 个在 5+ 轮实验中从未通过，非模型/model 可解

---

## 7. 关键数据快照

### 系列 A — R4 最终状态（2026-07-08）

```
技能库: 102 SKILL.md (93 种子 + 9 L4 新增)
Q-table: 102 entries, 80% non-default
Q range: [0.150, 0.808]
Top-5: git-webserver-deploy(0.81), qemu-alpine-ssh(0.79),
        openssl-selfsigned-cert(0.79), crack-7z-archive(0.79),
        rstan-hierarchical-mcmc(0.78)
稳定通过: 41 tasks (49%)
改善 (R1→R4): 6 tasks (7%)
```

### 系列 B — R5 最终状态（2026-07-12）

```
技能库: 112 SKILL.md
Q-table: 112 entries, 69% non-default
Q range: [0.201, 0.759]
Top-5: cobol-python-port(0.759), extract-elf-memory(0.757),
        tune-mjcf(0.754), multi-source-merge(0.743),
        async-task-shutdown(0.743)
Pipeline steps: 371 trials processed
```

### Hard6（deepseek-v4-pro, 3 runs）

```
最佳: 1/6 (write-compressor)
5 任务 0/3: caffe-cifar-10, extract-moves-from-video,
            make-mips-interpreter, video-processing, train-fasttext
```

---

## 8. 实验配置速查

| 参数 | 系列 A (R1-R4) | 系列 B (R1-R5) |
|---|---|---|
| 配置文件 | `tb2_skillq_fromscratch*.yaml` | `tb2_skillq_zerostart*.yaml` |
| `reuse_q_table` | R1=false, R2-R4=true | 全部 false |
| `c_ucb` | 0.0 | 0.0 |
| `sim_gate_min_score` | 0.5 (R1-R3), 0.7 (R4) | 0.7 |
| `retrieval_mode` | pull | pull |
| `n_concurrent_trials` | R1=4, R2-R4=8 | R1-R5=8 |
| `extract_every_n_trials` | 1 | 1 |
| `q_alpha` | 0.3 | 0.3 |
| `q_update_cosine_weight` | true | true |
| `embedder_model` | text-embedding-v4 | text-embedding-v4 |
