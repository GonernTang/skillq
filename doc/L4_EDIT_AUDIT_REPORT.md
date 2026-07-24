# L4 Skill Edit Pipeline — 深度审计报告

**日期**: 2026-07-24
**数据来源**: GAIA R5 实验 (`gaia_skillq__2026-07-22__15-36-41`)  
**审计范围**: 5 个 `FAILURE_SKILL_USED` 归因的失败 trial  
**目的**: 验证 L4 编辑步骤是否能为失败任务生成有效的技能修复

---

## 1. 审计方法

### L4 Edit 流水线回顾

```
trial 失败 (r_task=0)
    ↓
L3 attribution LLM 分析轨迹
    → knowledge_to_extract: 从失败中学到的教训
    → library_gap_skill_description: 库中缺少什么样的技能
    ↓
L4 step_incremental_edit 触发 (attribution=FAILURE_SKILL_USED)
    → 从 calls_log 找出 agent 实际调用的技能
    → 选取 Q 值最低的调用技能（最可能的故障点）
    → 构造 diagnosis = knowledge_to_extract + gap_description
    → 取 session 最后 3 条 assistant 消息
    → 调用 EditRefiner.propose_edit(task, diagnosis, tail, old_skill)
        → EDIT_PROMPT: “这是失败的技能，请最小化修改以预防此失败”
    → 替换库中技能 (Qlib.replace)
```

### 分析维度

对每个 case 从 5 个维度评估：

| 维度 | 评估问题 |
|------|---------|
| **归因准确性** | L3 LLM 诊断的 failure root cause 是否正确？ |
| **技能质量** | 原始技能本身是否有缺陷导致失败？ |
| **Agent 行为** | Agent 是否正确遵循了技能指导？ |
| **编辑效果** | 假设 LLM 照 EDIT_PROMPT 生成修改，新技能是否能阻止此失败？ |
| **泛化风险** | 修改是否可能破坏该技能在其他任务上的正确行为？ |

---

## 2. 逐 Case 分析

### Case 1: bottle-deposit-refund

**任务**: 计算 2023 年 5 月从 LA 到 Maine 自驾途中，每 100 英里消耗 5 瓶水的瓶装水押金退款总额。

**Agent 行为** (来自 session trace):
- 使用 OSRM 路由引擎获取各州行驶距离
- 查询 Wikipedia 获取各州容器押金法规
- 识别 CA、NY、ME 为押金州
- 最终答案: $2.00

**归因 LLM 诊断**:
> "the agent's interpretation of the rounding rule (per-segment rounding vs. total-distance rounding) was incorrect, or the distance data from OSRM deviated from ground truth"

**技能内容** (bottle-deposit-refund/SKILL.md):
该技能指导 agent 执行多步骤退款计算，但未明确说明**取整规则应在总距离还是每段距离上应用**。

**分析**:

| 维度 | 评估 |
|------|------|
| 归因准确性 | ✅ 准确 — 归因正确指出取整歧义是根本原因 |
| 技能质量 | ⚠️ 技能缺少对取整歧义的处理逻辑 |
| Agent 行为 | ✅ Agent 正确执行了技能步骤 |
| 编辑效果 | ✅ 可行的编辑：在技能中添加 “总是在总距离上应用取整，而非逐段取整” |
| 泛化风险 | 🟢 低 — 取整规则是这类任务的通用要求 |

**结论**: 这是 L4 编辑的**理想 case** — 归因准确，技能有明确可修复的 gap，编辑不会破坏技能的通用性。

---

### Case 2: verify-ranked-list-overlap

**任务**: Box Office Mojo 2020 年全球 Top-10 与本土 Top-10 有多少重叠？（答案应为整数）

**Agent 行为**:
- 抓取 BOM 的 worldwide 和 domestic 榜单
- 计算交集：Bad Boys for Life, Sonic, Dolittle → 3
- 答案: 3

**归因 LLM 诊断**:
> "The failure may stem from an incorrect assumption about which lists constitute 'top 10 highest-grossing domestic movies' (e.g., the year or market definition), or from a mismatch between the fetched data and the verifier's ground truth."

**技能内容** (verify-ranked-list-overlap/SKILL.md):
防护性技能，强调“验证榜单定义、时间窗口”等 checklist，但**未提供正确的 URL 模板**。

**分析**:

| 维度 | 评估 |
|------|------|
| 归因准确性 | ⚠️ 部分准确 — 指出可能有 URL/定义问题，但未具体化 |
| 技能质量 | ❌ 技能是 guard-rail checklist，排查项太多，不够 actionable |
| Agent 行为 | ⚠️ Agent 计算看起来正确，失败可能是 verifier 数据源差异 |
| 编辑效果 | ❓ 不确定 — 技能缺少具体 URL，但 LLM 编辑也无法凭空补上正确 URL |
| 泛化风险 | 🟡 中 — 如果 agent 答案确实是错的（数据源不对），添加 URL 可修复；如果是 verifier 不一致，编辑无用 |

**结论**: **边界 case**。归因只描述了可能性，未给出具体修复建议。如果失败根因是 verifier 期望的答案不同（而非 agent 逻辑错误），L4 编辑无法修复这种问题。这暴露了归因 LLM 无法区分“agent 错”和“verifier 不一致”的局限。

---

### Case 3: earliest-publication-lookup

**任务**: 找出 "Pie Menus or Linear Menus, Which Is Better?" (2015) 的作者中，之前发过论文的那个人的**第一篇论文标题**。

**Agent 行为**:
- 找到论文作者：Pietro Murano 和 Iram N. Khan
- 发现 Murano 在 2001 年有论文，Khan 没有 2015 年前论文
- 在 Murano 的个人主页找到 "Mapping Human-Oriented Information to Software Agents for Online Systems Usage" (2001)
- 答案: 该标题

**归因 LLM 诊断**:
> "The agent never used the relevant skill 'earliest-publication-lookup' that was offered by the system. Instead it relied on fragile web searches and a personal homepage, leading to an incorrect or incomplete final answer."

**技能内容** (earliest-publication-lookup/SKILL.md):
系统性地查询多个学术数据库（OpenAlex, Crossref, DBLP），按年份排序，核实作者身份。

**分析**:

| 维度 | 评估 |
|------|------|
| 归因准确性 | ✅ 准确 — 指出了 agent 绕过了可用技能 |
| 技能质量 | ✅ 技能本身是好的 — 它指导了正确的多数据库查询方法 |
| Agent 行为 | ❌ Agent 读了技能但决定用 web search 替代，这是 agent 的自主决策问题 |
| 编辑效果 | ❌ 编辑无法修复 — 技能本身没问题，问题是 agent 没有使用它 |
| 泛化风险 | 🟢 低 — 不需要改技能 |

**结论**: **Agent 拒绝使用技能** — 即使技能被注入，agent 选择了自己的方法。这种失败的归因标签应该是 `FAILURE_SKILL_NOT_USED`（技能存在但 agent 没用），而非 `FAILURE_SKILL_USED`（技能被用了但不好）。这说明 **calls_log 的 skill 调用不等于 agent 实际遵循了技能指导**。L4 编辑在这种情况下会对一个好技能进行不必要的修改。

---

### Case 4: xlsx-parity-counter

**任务**: 从 Excel 电子表格中，统计房屋号码为偶数的客户数量（偶数=朝西=sunset awning）。

**Agent 行为**:
- 用 Python stdlib openpyxl 或 pandas 读取 xlsx
- 解析地址列，提取门牌号
- 统计偶数：8602, 6232, 2024, 2024 → 4
- 答案: 4

**归因 LLM 诊断**:
> "The agent parsed the xlsx file, applied parity logic, and counted 4 clients... Despite the computation appearing correct, the verifier indicated the task was not solved."

**技能内容** (xlsx-parity-counter/SKILL.md):
详细的指南：使用 stdlib 读取 xlsx，用正则提取门牌号，检查 parity。

**分析**:

| 维度 | 评估 |
|------|------|
| 归因准确性 | ⚠️ 不确定 — LLM 无法确定哪里错了 |
| 技能质量 | ✅ 技能是好的 — 步骤完整且正确 |
| Agent 行为 | ✅ 遵循了技能 |
| 编辑效果 | ❌ 无法针对性编辑 — 归因没有提供具体修复建议 |
| 泛化风险 | 🔴 高 — 如果答案是 4 但期望值是 3（比如方向定义不同），修改技能可能引入错误 |

**结论**: **归因天花板** — L3 LLM 无法确定失败原因（答案看起来是正确的）。可能的根因：(a) verifier 有 bug，(b) 答案格式不匹配，(c) agent 少处理了某条记录。这种情况 L4 编辑无法生成有用的修改。归因 LLM 应该在这种情况下**不生成 knowledge_to_extract**（或明确说“无法诊断”），以避免无意义的编辑。

---

### Case 5: grid-text-decoding

**任务**: 从 5×7 字母网格中提取隐藏句子。

**Agent 行为**:
- 逐行从左到右读取：`THESEAGULLGLIDEDPEACEFULLYTOMYCHAIR`
- 分割成句子："THE SEAGULL GLIDED PEACEFULLY TO MY CHAIR"
- 答案: 该句子

**归因 LLM 诊断**:
> "The agent misinterpreted the grid dimensions (7x5 vs the stated 5x7) or the output format (raw concatenation vs segmented sentence)"

**技能内容** (grid-text-decoding/SKILL.md):
指导多种网格读取策略（行、列、蛇形、螺旋等），但**未强调验证维度方向**的步骤。

**分析**:

| 维度 | 评估 |
|------|------|
| 归因准确性 | ⚠️ 部分准确 — 指出了维度歧义的可能性 |
| 技能质量 | ⚠️ 技能覆盖了太多模式，缺少“先确认维度”的第一步 |
| Agent 行为 | ✅ Agent 按技能步骤操作 |
| 编辑效果 | ✅ 可行的编辑：在技能开头添加“先验证输入是否符合声明的维度，不符合则尝试转置” |
| 泛化风险 | 🟢 低 — 维度验证是通用操作 |

**结论**: 另一个 L4 编辑的**好 case**。归因准确指出了可能的问题（维度方向），编辑可以添加一个简单的前置检查步骤。但同样存在不确定性——如果 verifier 期望的是无空格的原始答案（`THESEAGULL...`）而非分割后的句子，编辑也无法修复。

---

## 3. 综合评估

### 3.1 各维度总结

| Case | 归因准确性 | 技能质量 | Agent 行为 | 编辑效果 | 泛化风险 | 结论 |
|------|:---:|:---:|:---:|:---:|:---:|---|
| bottle-deposit-refund | ✅ | ⚠️ | ✅ | ✅ | 🟢 | **理想 case** |
| verify-ranked-list-overlap | ⚠️ | ❌ | ⚠️ | ❓ | 🟡 | 边界 case |
| earliest-publication-lookup | ✅ | ✅ | ❌ | ❌ | 🟢 | Agent 未使用技能 |
| xlsx-parity-counter | ⚠️ | ✅ | ✅ | ❌ | 🔴 | 无法诊断 |
| grid-text-decoding | ⚠️ | ⚠️ | ✅ | ✅ | 🟢 | 好 case |

### 3.2 优良编辑 vs 无效编辑

| 类型 | Count | 特征 |
|------|:---:|------|
| **能产出有效编辑** | 2/5 | 归因明确指出了技能缺陷，编辑可针对性添加规则 |
| **无法产出有效编辑** | 2/5 | 归因无法确定根因，或 agent 未遵循技能 |
| **边界/不确定** | 1/5 | 归因有线索但不足，编辑可能有用也可能无用 |

### 3.3 发现的系统性问题

#### 问题 1: 归因 LLM 无法区分“agent 错”和“verifier 不一致”

Case 2 和 Case 4 中，agent 的计算逻辑看起来正确，但 verifier 判了失败。归因 LLM 给出了模糊的诊断，无法确定是 agent 错误还是 verifier 数据差异。**L4 编辑在这种情况下会产生无意义的修改。**

**建议**: 在 EDIT_PROMPT 中添加一个 gate：如果归因的诊断中包含“可能”“不确定”等表达，要求 LLM 在修改前先评估“此修改是否可能有害”，如果无法确定则返回原技能。

#### 问题 2: FAILURE_SKILL_USED 的误标

Case 3 中，agent 调用了 Skill()（calls_log 记录了调用），因此代码判为 `FAILURE_SKILL_USED`。但实际上 agent **没有遵循技能指导**——它读了技能然后决定用自己的方法。正确的标签应该是 `FAILURE_SKILL_NOT_USED`（技能存在但未被有效使用）。

**建议**: L3 归因后不应仅靠 calls_log 的“是否调用”来决定标签。应该检查 agent 的轨迹是否**实际遵循了技能的关键步骤**。这需要归因 LLM 或一段规则代码做深度分析。

#### 问题 3: 编辑质量取决于归因质量，但归因质量不稳定

5 个 case 中，归因 LLM 的输出质量波动很大：
- Case 1: 精确指出取整规则问题 ✅
- Case 4: “计算看起来正确，但失败了” — 无信息 ❌

**建议**: 在 `step_incremental_edit` 中增加一个 quality gate — 如果 diagnosis 长度 < 50 字符或包含“不确定”关键词，跳过编辑，避免对好技能进行无效修改（可能造成 Q 值衰减）。

#### 问题 4: 当前 EDIT_PROMPT 的设计缺陷

```
EDIT_PROMPT 要求:
- Keep the skill's name unchanged ✅
- Do not introduce new dependencies ✅
- Preserve all currently-correct content ✅
- Return the FULL post-edit skill ✅
```

Prompt 的设计是保守的——它要求 LLM 做最小修改。这降低了 risk，但也意味着：
- LLM 无法从根本上重组一个设计不良的技能（如 Case 2 的纯 checklist 式技能）
- 如果技能的结构性设计是失败原因（而非缺少步骤），编辑不会修复

**建议**: 当技能连续 N 次在同一类任务上失败时，考虑触发“技能重写”而非“增量编辑”（目前没有这个机制）。

---

## 4. 改进建议优先级

| 优先级 | 建议 | 影响 |
|:---:|---|------|
| **P0** | 在 `step_incremental_edit` 加 quality gate — diagnosis 为空/不确定时跳过编辑 | 防止对好技能进行无效修改 |
| **P1** | 修复 FAILURE_SKILL_USED 误标 — 增加 agent 是否实际遵循技能的检查 | 防止对未被使用的技能进行编辑 |
| **P2** | 提升归因 LLM 的诊断质量 — 优化 ATTRIBUTION_PROMPT | 提升编辑输入质量 |
| **P3** | 增加连续失败后的技能重写机制 | 处理结构性错误的技能 |

---

## 5. 结论

L4 编辑流水线在**理想条件下**可以有效生成有用的技能修复（Case 1, Case 5）。但其成功率严重依赖上游归因的质量。在 5 个 case 中：

- **40%** (2/5) 能产出有效编辑
- **40%** (2/5) 因归因模糊或 agent 行为无法编辑
- **20%** (1/5) 不确定

系统当前的主要瓶颈不在编辑提示词的设计，而在**归因 LLM 无法精确诊断失败根因**。改进方向应优先放在：
1. 增强归因诊断质量（更具体的 root cause 识别）
2. 增加 quality gate 防止基于模糊诊断的错误编辑
3. 区分“技能被调用”和“技能被遵循”
