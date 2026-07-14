# `main.pdf` 与最新 SkillQ 实现的差异及 §3 修改建议

> 适用范围:`main.pdf`(论文初稿,23 页,基于老版本 SkillQ,标"lqrl"路径) ↔ 当前 `skillq/` 仓 `main` 分支(截至 2026-07-09)。
> 阅读对象:作者本人(camera-ready 前的 §3 / §5.1 / Table 5 改稿)。
> 标注规则:**HIGH** = 不改会直接被审稿人打脸或让复现者失败;**MED** = 数学形状 / 默认值错位但仍可解释;**LOW** = 措辞 / cross-reference。

---

## 1. 现状速览

论文 §3 把 SkillQ 描述为**四层闭环 + 5-Enum + 标准 tabular Q-update + 强制调用** 的"标准"形态。但当前代码已经历 2026-06-22 → 2026-07-01 一系列内部重构,实际形态是:

- **Retrieval(L1)**:双公式并存(`additive` legacy + `multiplicative` 默认),带 BM25 融合,Hard Gate 默认 0.7。
- **Attribution(L3)**:仍是 5-enum,但已**删除** `SUCCESS_VIEWED_SKILL_BUT_NOT_USED`(2026-06-26)。
- **Edit**:原 near-miss gate 已**删除**(2026-06-22),无条件触发。
- **Q-update**:在 Eq. (1) 之上**加了 cosine-weighted delta**(Fix 3),且发生在 `step_q_update`(attribution 之前),与论文 Table 3 描述的 attribution 步骤更新 Q 不一致。
- **Create**:默认 `extract_every_n_trials=4`,但所有论文实验 config 实际设 **1**(2026-07-03 per-trial 分支生效)。
- **Library management**:代码里有 `b_max=1000` + lowest-Q eviction + `admission_exempt=True`,论文 §3.5 **完全没提**。
- **§5.1 末尾的 "paper-code alignment" 段落整段与现实相反**,论文声称"实现只有 2-enum / 没有 mandatory-call / 没有 threshold τ",代码里这三条全部已对齐。

---

## 2. §3 必须修改的具体条目

### 2.1 §3.1 Per-Skill Q-Learning — Eq. (1) 的措辞

**论文原文**:`Eq. (1) is the only Q-update rule used in the rest of the paper; it will be referenced rather than restated.`

**实际代码**(`skillq/runtime/steps.py:151-303`):在 Eq. (1) 之上多乘了 `max(cos(φ(q), φ(s)), 0)`,默认开启(`config.py:370` `q_update_cosine_weight=True`,Fix 3)。

**修改意见**(HIGH):把"only Q-update rule"改成
> "The paper uses the standard tabular Q-update of Eq. (1) as its base, optionally multiplied by a cosine-similarity weight (Fix 3, see §3.2 for the embedding pipeline). The full update reads `Q(s) ← Q(s) + α·[r_task − Q(s)]·max(cos(φ(q), φ(s)), 0)`. With `cosine_weight=False` it collapses to standard Eq. (1)."

并在 §4.2 Table 5 新增一行 `cosine-weighted delta: True`。

**附带清理**(LOW):`skillq/layers/l3_attribution/edit.py:74, 122` 残留"verifier's `r_learning` signal"引用,该信号在 2026-06-23 dead-code purge 后已不存在,纯文档残留。如读者对照仓里代码会困惑。

---

### 2.2 §3.2 Layer 1: Retrieval — 公式、默认值、BM25

| 论文原文 | 实际代码 | 修改 |
|---|---|---|
| Eq. (2) `score = sim·(1 + β·Q) + γ·UCB` 是唯一公式 | `score_skills`(`scoring.py:170`)双模式,默认 `multiplicative`;additive `(1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))` 仍存活 | **(HIGH)** §3.2 明确"Eq. (2) 是默认 multiplicative 模式,legacy additive(z-scored)作为 §4 ablation" |
| Hard Gate threshold τ 默认 0.5 | `sim_gate_min_score` 默认 0.7(`config.py:306`);`fromscratch.yaml:68` 设 0.5;`bm25_5tasks` 设 0.7 | **(HIGH)** §4.2 Table 5 把 τ 默认值改为 0.7;§3.2 文字描述"τ = 0.5 是 from-scratch 实验用值,仓默认 0.7" |
| γ 默认 0.3 | γ 默认 0.2(`config.py:279`,`fromscratch.yaml:73`) | **(MED)** Table 5 γ 改为 0.2 |
| Eq. (2) 用 raw cosine | 在 Hard Gate 前先做 `max(cosine, bm25)` 融合(`scoring.py:228-233` + `bm25.py`) | **(HIGH)** §3.2 必须新增 Eq. (2') 的 hybrid 版本:`sim' = max(cos(φ(q), φ(s)), BM25(q, body(s)))`,然后 `score = sim'·(1 + β·Q) + γ·UCB`。这是 BM25 ablation 跑得动的前提 |

---

### 2.3 §3.3 Layer 2: Run — 区分 retrieval_mode

**论文原文**:"the agent is required to call one of the top-k retrieved skills"

**实际代码**有两层强制实现,需要分清:

1. **Hook 模式**(`retrieval_mode="hook"`):PreToolUse hook `_handle_pretooluse_skill`(`runtime/hook.py:458`)对不在 top-k 的 Skill() 调用 **deny + 重定向**,附 top-k 列表与 MUST-call 文案。
2. **Pull 模式**(`retrieval_mode="pull"`,**默认** `config.py:516`):SessionStart / UserPromptSubmit 注入 `additionalContext`(`force_use_text.format_pull_context` `force_use_text.py:65`),MUST-call 文案见 `format_pull_context:103-105`。

**修改意见**(MED):
- §3.3 加一段区分两种 mode,并指出默认是 pull。
- "required to call" 改成"PreToolUse hook returns `deny` for skills outside the top-k; pull-mode injects MUST-call into `additionalContext`. Either way the agent is contractually required to call Skill() with one of the top-k candidates before other tools."

---

### 2.4 §3.4 Layer 3: Attribution — 5-Enum 改名史与 Q-update 时序

| 论文原文 | 实际代码 | 修改 |
|---|---|---|
| 5-Enum 名字 | 完全一致(`models.py:32-61`) | OK |
| `FAILURE_SKILL_USED` 触发 Eq. (1) | **错**:Eq. (1) 实际在 `step_q_update`(attribution 之前)根据 PreToolUse calls_log 跑,attribution 步骤只产出 enum,不动 Q | **(HIGH)** Table 3 "Q update"列与 Algorithm 1 行 8-9 改写为"Eq. (1) is applied on the called skill by `step_q_update` BEFORE attribution, using the per-trial PreToolUse calls_log; attribution only classifies the outcome" |
| `FAILURE_SKILL_USED` 触发 near-miss gate | **错**:near-miss gate 2026-06-22 删除(`edit.py:7-13`),改为无条件触发 | **(HIGH)** §3.5 写"Improve called skill"必须注明"unconditional (near-miss gate removed 2026-06-22 because `q_w_task=−0.5` made the gate unreachable; see Appendix 5.x for rationale)" |
| Enum 历史一致 | `SUCCESS_VIEWED_SKILL_BUT_NOT_USED` 2026-06-26 删除(`models.py:50-54`,`prompts.py:90-94`) | **(MED)** §3.4 加 footnote 说明此 enum 因 L1 force-use hook 让"viewed but not used"状态不可达而被删除;analyzer 在 r_task=1 时若检测到该状态会 coerce 到 `SUCCESS_SKILL_USED` |
| 鲁棒性 / Appendix 5.7 | 实装有 `[consistency-clamp]` safety net(`analyzer.py:189-243`) + calls_log 交叉验证(`steps.py:498-518, 669-697`) | **(MED)** §3.4 末尾加"Robustness"小段:analyzer 产出与 calls_log 互校,例如 LLM 说 `NO_SKILL_SEEN` 但 calls_log 显示有 approved lib skill → 跳过 L4 harvest |

---

### 2.5 §3.5 Layer 4: Evolution — batching、library mgmt、emb_cache 顺序

| 论文原文 | 实际代码 | 修改 |
|---|---|---|
| "Create new skill on SUCCESS_NO_SKILL_SEEN / FAILURE_SKILL_NOT_USED" | 一致(`steps.py:721-749`) | OK |
| "summarised into a new skill with three fields" | `SkillExtractor.extract_batch` → `_extract_single`(N=1)或 batch prompt;`body` 为 SKILL.md 全文 | **(LOW)** 补一句"name = kebab-case,1..4 words;body = 50..2000 tokens(SKILL.md 全文)" |
| `extract_every_n_trials` 未提 | 默认 4(`config.py:459`),但**所有论文实验 config 设 1**(`fromscratch.yaml:80`, `bm25_5tasks.yaml:82`, `hard6:9`, `tb2_skillq_e2e_*:10`) | **(HIGH)** §3.5 描述 batching 时明确"本论文实验采用 `extract_every_n_trials=1`,即 per-trial extract(2026-07-03 `_extract_single` 分支生效,`create.py:126-133`)"。Table 5 新增 `extract_every_n_trials=1` 行 |
| 不提 library 大小管理 | 有 `b_max=1000`(`config.py:151`) + `LibManager.maintain` lowest-Q eviction(`q_table.py:107-125`) + 新 skill `admission_exempt=True`(`steps.py:863`) | **(HIGH)** §3.5 必须新增 "Library management" 小节:`b_max` 强制上限 + lowest-Q eviction + 新建 skill admission exemption 三条机制。这是 §1 (b) "forgetting monotonicity" 的实现关键 |
| emb_cache 更新未提 | `step_refresh_emb_cache`(`steps.py:399-455`)在 trial end 批量写;pipeline invariant 强制该步骤在所有 lib-mutating 步骤之后(2026-07-01 修复后位置 7,见 `tests/test_pipeline_emb_cache_ordering.py`) | **(MED)** §3.5 / Algorithm 1 加一段"emb_cache 在 trial end 批量刷新;流水线位置 7 必须在 step_maintain_lib / step_incremental_edit / step_dispatch_evolve 之后,step_save_state 之前。原 2026-06-25 实现位置 5 导致 L4 Create 增量丢失,见 Appendix 5.x" |
| name collision 未提 | `__v2/__v3` 后缀改名(`steps.py:843-862`) | **(LOW)** §3.5 加一句"name-collision resolution:同名前缀 → 追加 `__v{n}`" |

---

### 2.6 Algorithm 1 控制流

**论文原文** 行 8-9:
```
Layer 3 (Attribution) ...
Apply Eq. (1) on the called skill (if applicable).
```

**实际控制流**(`runtime/steps.py`,2026-06-26 refactor 后):

```
step_classify_failure
step_q_update           ← Eq. (1) 在这里跑,attribution 之前
step_attribute          ← 仅产出 enum
step_maintain_lib       ← b_max eviction
step_incremental_edit   ← FAILURE_SKILL_USED 触发
step_dispatch_evolve    ← L4 create buffer
step_refresh_emb_cache  ← 批量 emb_cache 刷新(位置 7)
step_save_state         ← 落盘
```

**修改意见**(HIGH):Algorithm 1 整段重写或加 footnote 解释 8 步流水线顺序,关键是 **Eq. (1) 在 attribution 之前**,attribution 只分类不更新 Q。

---

## 3. §4.2 Table 5 必须修订

| Symbol | 论文 | 实际 config | 修改 |
|---|---|---|---|
| α | 0.3 | 0.3(`config.py:356`) | OK |
| β | 0.5 | 0.5(`config.py:269`;`fromscratch.yaml:73`) | OK |
| γ | 0.3 | **0.2**(`config.py:279`;`fromscratch.yaml:73`) | **改 0.2** |
| τ | 0.5 | **0.7**(`config.py:306`;bm25 0.7, fromscratch 0.5) | **改 0.7** |
| Qinit | 0.5 | 0.5(`config.py:478`) | OK |
| `extract_every_n_trials`(新增) | — | 4 default / **1 实验** | **新增行,实验值 1** |
| `cosine-weighted Q-delta`(新增) | — | True(`config.py:370`) | **新增行** |
| `sim_gate_floor`(新增) | — | 0(`config.py:318`) | **新增行** |
| `b_max`(新增) | — | 1000(`config.py:151`) | **新增行** |

---

## 4. §5.1 必须整段改写

**论文原文 §5.1 末段**:

> "the open-source implementation (code/lqrl/) currently uses a β-layered Q-update …, classifies outcomes into only two categories (success / failure) rather than the five Enums of Table 3, and does not implement the mandatory-call constraint or the similarity threshold τ."

**每一条都已被代码超越**:

- β-layered Q-update:2026-06-25 dead-code purge 删除,改为标准 Eq. (1) + 可选 cosine-weighted delta(`config.py:101-104`,`steps.py:241-256`)。
- 仅 2-enum:错。当前 5-enum 已稳定,`tests/test_enum_contract.py` pinning 字符串值。
- 没有 mandatory-call:错。L1 force-use hook `force_use_text.py:55, 103` 已上。
- 没有 similarity threshold τ:错。Hard Gate `scoring.py:114-164`,默认 0.7。
- `code/lqrl/` 路径:已挪,合并到 `skillq/layers/` 与 `skillq/runtime/`。

**建议改为**:

> "The open-source implementation lives under `skillq/`(committed at the Git SHA corresponding to this camera-ready). The five core design points—5-Enum attribution, multiplicative retrieval, similarity Hard Gate, mandatory-call PreToolUse/Pull hook, and standard tabular Q-update—match §3 exactly. Two extensions are present in the code but absent from the body for brevity: (i) BM25 keyword scoring fused with cosine via `max(cos, bm25)` before the Hard Gate (§3.2 Eq. (2')); (ii) cosine-weighted Q-delta Fix 3, multiplying the Eq. (1) update by `max(cos(φ(q), φ(s)), 0)`. The library is hard-bounded at `b_max=1000` with lowest-Q eviction; new skills are admission-exempt for one cycle. Headline numbers in Table 6 are reproduced from the paper-side spec; logged runs use these defaults and are auditable in the trial dirs."

---

## 5. §5.2 Future Work 校对

| Future work | 现状 |
|---|---|
| Adaptive τ schedule | 未实现 |
| Heterogeneous content roles | **`editor_model` 与 `attribution_model` 已可独立配**(`config.py:160-178`);`extractor_model` 默认与 `attribution_model` 对齐(`config.py:191-202` 强制约束)。可改写为"infrastructure in place; not yet ablated" |
| Multi-agent skill sharing | 未实现 |
| Non-binary rewards | `q_clip_floor / q_clip_ceiling` 支持任意实数 Q(`config.py:112-125`);Q-update 仍是 tabular,可承载连续 reward |

---

## 6. §4.1 Setup / Baselines 校对

| 论文原文 | 实际 | 修改 |
|---|---|---|
| 与 MemRL / Memento-Skills / SkillsVote 对比 | 仓内仅包装 `skillq skillsvote` 子命令调用上游 `skills_vote` 包(`skillq/skillsvote_mode/__init__.py`);MemRL / Memento-Skills 未实现 | **(MED)** §4.1 Baselines 一节明确"MemRL / Memento-Skills baselines exist only on the paper side;the open-source experiment runs No-Skill + SkillsVote(SkillsVote through `skillq skillsvote` wrapping the upstream `skills_vote` package)" |
| 用 DeepSeek-V4 / Claude Code | 实际 LLM 链:Claude Code agent(`SkillQClaudeCodeAgent`)跑在 anthropic/`deepseek-v4-flash`(env `ANTHROPIC_MODEL`);embedder 用 `openai/text-embedding-v4`(`fromscratch.yaml`);attribution / edit / extract 共用 deepseek-v4-flash | **(LOW)** §4.1 把 DeepSeek-V4 改成"Claude Code agent running anthropic/deepseek-v4-flash by default(Flash tier; Pro reserved for harder SWE-Bench Pro tasks); embedder is openai/text-embedding-v4" |

---

## 7. 修改优先级

| 优先级 | 章节 | 不改的后果 |
|---|---|---|
| **P0** | §3.2 Eq. (2) → 加入 BM25 融合;γ → 0.2;τ → 0.7;明确双 score_mode | 复现者按论文默认配置失败;additive 被默认跳过 |
| **P0** | §3.5 Algorithm 1 / Table 3 → Eq. (1) 在 attribution 之前,attribution 只分类 | 论文与代码控制流对不上 |
| **P0** | §3.5 新增 "Library management" + "emb_cache batched refresh" 段 | §1 (b) 实现细节缺失 |
| **P0** | §5.1 "paper-code alignment" 整段重写 | 与现实相反,审稿人秒打脸 |
| **P1** | §3.3 区分 hook vs pull retrieval_mode | §4 ablation 提到 "Method B" 无术语支撑 |
| **P1** | §3.4 注明 `SUCCESS_VIEWED_SKILL_BUT_NOT_USED` 已删除 + consistency-clamp + calls_log 互校 | enum 重命名史未交代 |
| **P1** | §3.5 注明 `extract_every_n_trials=1` 是实验值,默认 4 | §4 ablation 不可解释 |
| **P1** | Table 5 新增 `extract_every_n_trials=1` / `cos_w=True` / `sim_gate_floor=0` / `b_max=1000`;γ 改 0.2 | 复现找不到配置 |
| **P2** | docstring 残留的 `r_learning` 引用清理(`edit.py:74, 122`) | 误导读者 |
| **P2** | §4.1 Baselines 限定为 No-Skill + SkillsVote | 期望对照表无法兑现 |

---

## 8. 关键文件 + 行号速查

| 主题 | 位置 |
|---|---|
| Scoring 公式 + Hard Gate | `skillq/layers/l1_retrieval/scoring.py:170-290` |
| BM25 融合 | `skillq/layers/l1_retrieval/bm25.py` + `scoring.py:228-233` |
| 5-enum 表面 | `skillq/layers/l3_attribution/models.py:32-61` |
| `SUCCESS_VIEWED_SKILL_BUT_NOT_USED` 删除说明 | `skillq/layers/l3_attribution/models.py:50-54` + `prompts.py:90-94` |
| EditRefiner(near-miss gate 已删) | `skillq/layers/l3_attribution/edit.py:7-13, 61-86` |
| MUST-call 文案 | `skillq/layers/l1_retrieval/force_use_text.py:55-58, 103-105` |
| Q-update 流水线 | `skillq/runtime/steps.py:151-303` |
| cosine-weighted delta(Fix 3) | `skillq/runtime/steps.py:241-256` + `config.py:370` |
| 一致性安全网(consistency-clamp) | `skillq/layers/l3_attribution/analyzer.py:189-243` |
| calls_log 交叉验证 | `skillq/runtime/steps.py:498-518, 669-697` |
| 强制 MUST-call hook 入口 | `skillq/runtime/hook.py:458-595` |
| retrieval_mode 双模式 | `skillq/config.py:516-527` |
| admission_exempt + eviction | `skillq/shared/q_table.py:107-125` + `skillq/runtime/steps.py:863` |
| emb_cache 流水线位置 7 约束 | `skillq/runtime/steps.py:399-455` + `tests/test_pipeline_emb_cache_ordering.py` |
| extract batching 默认/实验差异 | `skillq/layers/l4_evolve/extract_buffer.py:41-74` + `skillq/runtime/steps.py:796-868` + `experiments/configs/tb2_skillq_fromscratch.yaml:80` |
| pre-trial settings.json transport(Bug #51/#52) | `skillq/runtime/agent.py:247-319` + `skillq/runtime/hook.py:141-179` |
| r_learning 文档残留 | `skillq/layers/l3_attribution/edit.py:74, 122` |
| SkillsVote baseline wrapper | `skillq/skillsvote_mode/__init__.py` |