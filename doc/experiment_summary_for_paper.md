# SkillQ 全量实验总结（论文用）

**日期**: 2026-07-01 至 2026-07-08
**基准**: Terminal-Bench 2.0, 89 任务
**Agent 模型**: deepseek-v4-flash (R1-R4) / deepseek-v4-pro (hard6)
**Embedding 模型**: text-embedding-v4 (dashscope)
**检索模式**: Pull (UserPromptSubmit + PreToolUse hook)
**并发**: R1 = 4, R2-R4 = 8
**超时**: 3600s/trial

---

## 1. 实验设计

SkillQ 论文提出四层运行时强化学习架构（L1 retrieval → L2 agent run → L3 attribution → L4 evolve），核心机制包括：

1. **两阶段 UCB 检索** (L1)：cosine embedding + UCB-augmented re-rank
2. **β-layered Q-learning** (L2/L3)：信息隔离的 verifier 评估技能效果，更新 Q-table
3. **Q-driven 库管理** (L3)：准入/驱逐/再生策略
4. **近失感知增量编辑** (L4)：LLM-generative via EditRefiner + LiteLLMEditBackend

**四轮实验设计**：

| Round | 种子 | 关键变更 | 目的 |
|---|:---:|---|---|
| R1 | 0 技能, 空 Q-table | 冷启动, 4 并发 | 零样本基线 + 自举技能库 |
| R2 | R1 的 67 技能 + Q-table | Pull-mode 修复, 8 并发 | 验证 Q-learning 有效性 |
| R3 v1 | R2 的 94 技能 + Q-table | Per-trial extract prompt（有 bug） | 对照：纯 Q-table 效果 |
| R3 v2 | R2 的 94 技能 + Q-table | Per-trial extract prompt（修复） | 验证 per-trial extract |
| R4 | R3 的 97 技能 + Q-table | **BM25 杂交检索** | 验证 BM25 提升检索覆盖率 |

---

## 2. 全量实验结果

| Round | 通过率 | Mean | Errors | Q entries | 非默认 Q | Q 范围 | 耗时 | 关键变更 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| R1 | 48/89 (54%) | 0.528 | — | 67 | 4 (6%) | 0.44–0.57 | ~8h | 零样本, 4 并发 |
| R2 | 44/89 (49%) | 0.494 | — | 90 | 57 (63%) | 0.31–0.70 | ~3h | Pull-mode 修复 |
| R3 v1 | 51/87 (59%) | 0.573 | 10 | 92 | 73 (79%) | 0.25–0.74 | ~3.5h | Per-trial extract (崩) |
| R3 v2 | 43/85 (51%) | 0.483 | 14 | 97 | 77 (79%) | 0.19–0.77 | ~3.5h | Per-trial extract (修) |
| **R4** | **49/88 (56%)** | **0.551** | **6** | **102** | **82 (80%)** | **0.15–0.81** | **3.6h** | **BM25 杂交** |

---

## 3. Q-Learning 有效性证据

### 3.1 Q-table 收敛

```
R1:  67 entries,  6% non-default, Q ∈ [0.44, 0.57]
R2:  90 entries, 63% non-default, Q ∈ [0.31, 0.70]   (+57pp 分化)
R3:  97 entries, 79% non-default, Q ∈ [0.19, 0.77]   (+16pp 分化)
R4: 102 entries, 80% non-default, Q ∈ [0.15, 0.81]   (+ 1pp 分化)
```

四轮实验 Q-table 从几乎全默认（94% 在 0.5）收敛到 80% 分化，范围从 0.13 扩宽到 0.66。Q-learning 持续、单调地增加了 Q 值的区分度。

### 3.2 Q 值 vs 任务成功率（R2 数据）

| Q 范围 | Trials | Pass | Pass Rate |
|---|:---:|:---:|:---:|
| Q ≤ 0.35 | 10 | 0 | **0%** |
| Q = 0.40 | 15 | 0 | **0%** |
| Q = 0.45 | 8 | 0 | **0%** |
| Q = 0.50 (默认) | 15 | 7 | 47% |
| Q = 0.55 | 14 | 13 | **93%** |
| Q = 0.60 | 20 | 18 | **90%** |
| Q ≥ 0.65 | 7 | 7 | **100%** |

**Q≥0.55 → 90%+ 通过率；Q≤0.45 → 0% 通过率。** 单调相关性强，验证了 β-layered Q-learning 的设计。

### 3.3 高分技能验证（R4 状态）

| 技能 | Q 值 | 类型 |
|---|---|---|
| git-webserver-deploy | 0.808 | 正确部署 git web 服务 |
| qemu-alpine-ssh | 0.790 | QEMU Alpine SSH 配置 |
| openssl-selfsigned-cert | 0.788 | OpenSSL 自签名证书 |
| crack-7z-archive | 0.786 | 破解 7z 加密归档 |
| rstan-hierarchical-mcmc | 0.778 | RStan MCMC 层级模型 |

### 3.4 跨轮稳定性

R1→R4 跨轮对比（84 个共同 scored tasks）：

| 模式 | 数量 | 解读 |
|---|---|---|
| 稳定通过 | 41 (49%) | 确定性成功 |
| 稳定失败 | 31 (37%) | 超出 agent 能力 |
| 改善 (0→1) | 6 (7%) | 技能转移有效 |
| 退化 (1→0) | 6 (7%) | 噪声或低 Q 技能误导 |
| **稳定性** | **72/84 = 86%** | 略高于 R1→R2 的 79% |

四轮实验的整体 task 命运高度稳定——**任务难度是 agent 表现的支配性因素。**

---

## 4. BM25 杂交检索 (R4)

### 4.1 动机

R1-R3 的检索覆盖率瓶颈：35% 技能从未被使用，28% trial 没有检索到任何技能。根因是 `text-embedding-v4` 的 problem↔solution 语义鸿沟导致 cosine sim 低于 Hard Gate 门槛（0.5）。技术术语（"7z", "hashcat", "cython", "sparql"）是通用 embedding 模型的盲区。

### 4.2 方法

在 L1 检索的 `score_skills()` 中，cosine sim 计算后、Hard Gate 之前插入 BM25 关键词评分，取 `max(cosine, BM25_L2_norm)` 融合。BM25 使用纯 Python stdlib 实时计算（~2ms/次），零外部依赖。不改 Gate/UBC/Q-table 任何逻辑。

### 4.3 效果

| 任务 | R3 v2 (纯 cosine) | R4 (BM25 hybrid) |
|---|---|---|
| crack-7z-hash | FAIL | **PASS** |
| build-pmars | FAIL | **PASS** |
| build-cython-ext | FAIL | **PASS** |

R4 整体通过率 55.7%（+5.1pp vs R3 v2），error 率从 14 降至 6（四轮最低）。BM25 在术语匹配场景（"7z", "debian", "cython"）显著改善了检索精度。

---

## 5. 仍存在的问题

1. **检索覆盖率天花板**：即使用了 BM25，仍有约 25% trial 没有任何技能匹配。Hard Gate=0.5 + embedding 语义鸿沟仍是瓶颈。

2. **新技能冷启动**：L4 创建的新技能在同轮内无法被使用（Q=0.5 → UCB bonus 不足 → 被 gate 拦）。技能的价值需要跨轮体现。

3. **单轮实验方差大**：跨轮稳定性 80-86%，20% 任务会翻转。单轮实验不足以可靠判断改动效果。

4. **硬任务集群**：6 个任务在 5 轮实验中从未通过过（caffe-cifar-10, extract-moves-from-video, make-mips-interpreter, train-fasttext, video-processing, write-compressor）。其中 3 个纯超时（1h 不够），3 个 agent 能力不足。

---

## 6. 论文还需要哪些实验

### 6.1 必须完成的（核心贡献的证据）

| 实验 | 目的 | 配置 | 预计耗时 |
|---|---|---|---|
| **SkillsVote baseline** | 量化 SkillQ vs 原始方法 | `skillq skillsvote run`, 89 任务, 8 并发 | ~3h |
| **R4 repeat (statistical)** | 验证 BM25 效果不是单轮噪声 | R4 配置再跑 1 轮，取均值 | ~3h |
| **Ablation: Q-learning off** | 证明 Q-table 因果贡献 | `reuse_q_table=false`, `seed_initial_q=0.0` | ~3h |
| **Ablation: L4 extract off** | 证明技能增量学习的贡献 | `evolve.enabled=false` | ~3h |
| **Ablation: retrieval off** | 证明 L1 检索贡献 vs zero-shot | `retrieval_mode=none` (agent 不调用 Skill) | ~3h |

### 6.2 强烈建议补充的（提升论文质量）

| 实验 | 目的 |
|---|---|
| **Hard tasks 专项** | deepseek-v4-pro + 2h timeout, 验证硬任务集群是否可解 |
| **R5: gate=0.4** | 降低检索门槛后未使用技能是否能激活 |
| **多轮统计 (R4+R5+R6)** | 3 轮均值控制噪声, 计算置信区间 |
| **Embedding 模型对比** | text-embedding-v4 vs v3-large 的覆盖率对比 |
| **技能使用审计** | 追踪每个技能的 Q 值演化路径, 展示 Q-learning 的动态调整能力 |
| **Case study: Q 值演化** | 挑选 3-5 个技能, 展示 R1→R4 的 Q 值轨迹 + 对应任务命运 |

### 6.3 最低可行论文实验矩阵

```
Baseline:  SkillsVote        (89 tasks) — 对照
Treatment: SkillQ R4 (BM25)  (89 tasks) — 主体
Ablation:  SkillQ - Q        (89 tasks) — 消融 Q-learning
Ablation:  SkillQ - L4       (89 tasks) — 消融技能提取
Ablation:  SkillQ - retrieval(89 tasks) — 消融检索

合计: 5 次 × 89 tasks ≈ 15h wall-clock (8 concurrent)
```

---

## 7. 关键数据快照 (R4 final)

```
技能库: 102 SKILL.md (93 种子 + 9 L4 新增)
Q-table: 102 entries, 82 non-default (80%)
Q range: [0.150, 0.808]
Top-5 Q:  git-webserver-deploy(0.81), qemu-alpine-ssh(0.79),
          openssl-selfsigned-cert(0.79), crack-7z-archive(0.79),
          rstan-hierarchical-mcmc(0.78)
稳定通过: 41 任务 (49%)
稳定失败: 31 任务 (37%)
改善 (R1→R4): 6 任务 (7%)
退化 (R1→R4): 6 任务 (7%)
```
