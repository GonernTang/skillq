# Step 9B circuit-fibsqrt timeout — 根因分析 (2026-06-29)

## Summary

`tb2_skillq_e2e__2026-06-29__18-09-50/` (3 task e2e):
- extract-elf: ✅ reward 1.0
- chess-best-move: ❌ reward 0.0 (失败但完成)
- **circuit-fibsqrt: ⏱️ AgentTimeoutError @ 1800s**

## Trial 时序

| Trial | Started (UTC) | Finished (UTC) | Duration | Result |
|---|---|---|---|---|
| extract-elf | 10:13:19 | 10:14:00 | ~1 min | reward 1.0 |
| chess-best-move | 10:13:19 | 10:27:05 | ~14 min | reward 0.0 |
| circuit-fibsqrt | 10:27:27 | **11:00:32** | **33 min** | **timeout** |

circuit-fibsqrt 跟 chess-best-move 是 concurrent（10:27:05 vs 10:27:27 间隔 22 秒）。

## 根因：debug spiral + 缺 skill 介入

### 任务内容 (instruction.md 260 字)

> The file /app/sim.c is a logic-gate simulator: each line of the file /app/gates.txt should contain a line of the form
>   outX = outY | outZ | etc.
> Create a /app/gates.txt file with <32,000 lines that, when you call /app/sim N, outputs fib(isqrt(N))%(2^32)
> where isqrt is the integer valued square root (rounded down) and fib(i) is the ith Fibonacci number, fib(0)=0 and fib(1)=1.
> As an example, running /app/sim 208 should output 377 because isqrt(208)=14 and fib(14) = 377,
> and running /app/sim 20000 should give 1407432322.

### Agent 走的路径

1. agent 读 /app/sim.c（reference C simulator）
2. 写 `gen.py` Python generator（emit gates.txt + C simulator）
3. 跑 `python3 gen.py && gcc && ./sim 208` → 错（错的输出）
4. agent **加 print debug 看 signal 编号** → 发现 signal index 漂移（因为 c16 + c0 之间的 intermediate sigs 把 iq 推到 266 而不是 203）
5. 改 `gen.py` 重新算 → 跑 → 还是错
6. 写更复杂的 trace program → 还错
7. **thinking_tokens 一直涨**（2969 → 3092）但没有实际进展
8. 30 min timeout 触发

### 关键事实

- **agent 0 Skill invocation**：`grep '"name":"Skill"' | wc -l` = 0
- **65 Bash 调用**全是 gcc/python3/grep 调试
- **`_calls_log` 是空目录**（hook 根本没触发，因为没 Skill tool call）
- agent 不知道 `domain-extractor-guardrail` 这个 L4-extracted skill 存在

### L4 已经提取了正确的 skill！

`skills/domain-extractor-guardrail/SKILL.md` 描述：

> The three recurring failures — manual ELF parsing, hand-rolled chess-board
> recognition, and **gate-by-gate circuit synthesis** — share one anti-pattern:
> building a complex domain-specific system from primitives instead of standing
> on a high-level library, and validating only at the end.

精确 cover circuit-fibsqrt 这种情况：
- "assemble gates by hand" ← circuit-fibsqrt 任务
- "debug spirals" ← agent 30 min 没出来
- diagnostic checklist 第一条就是 "library / skill search"

### 为什么 agent 没看到这个 skill

`domain-extractor-guardrail` 是 L4 SkillExtractor 在 e2e 跑完后从 **chess-best-move 失败 trial + extract-elf 成功 trial** 抽取出来 mirror 到 `skills/` 目录的。

circuit-fibsqrt trial 跑的时刻（10:27:27 UTC），agent 还**没看到这个 skill**——因为 skill 还没被抽取。即使 L1 retrieval 在 trial start 时 seed 进了 lib，skill 也不存在。

## 不是 framework bug

按 Task #74 SKIP_ALL 早退 fix，timeout 会被 classify 为 `AgentTimeoutError` → `_INFRA_EXCEPTIONS` → SKIP_ALL → 干净跳过所有 step。**pipeline 处理正确**。

根因是 **meta-level**：paper method 需要在 agent 真的去 hard-code 电路 generator 之前，主动 surface 这个 skill。L1 retrieval 不会主动 surface skill（只在 `Skill(skill_name="...")` 调用时响应），需要其他机制。

## 缓解方向（待用户决策）

1. **Bigger library bootstrap**：把 `domain-extractor-guardrail` 等 5 个明显 cover 已知 anti-pattern 的 skill 直接 seed 到 `seed_skills_dir` (不是等 trial 失败后 L4 抽)，让 trial 1 就能看到。这是个 fake-it-till-you-make-it 策略，但能让 1/3 → 2/3。

2. **Bigger L1 top_k**：现在 `top_k=3`，circuit-fibsqrt 这种 task 一开始 lib 已经有 40+ seed skill，可能 relevant skill 排第 7-10 没被 surface。top_k=10 会让更长的 tail 进入候选。但这增加 compute。

3. **Compaction trigger**：如果 agent 进入 debug spiral (n thinking tokens > threshold)，L3 attribution 主动 flag FAILURE_SKILL_NOT_USED，触发 L4 extract。这本来就是 L3 attribution 的语义但需要新增一个 "stall detector"。

4. **Accept 1/3 baseline**：circuit-fibsqrt 这个具体 task 是 adversarial hard case（32K gates、fib + isqrt、mod 2^32）。pass rate 1/3 可能就是这个 task 的天花板。full 89 task 上 pass@1 才更有意义。

## 验证

- agent.log last entry: thinking_tokens=3092 (永远 stop_reason=null)
- exception.txt: `harbor.trial.trial.AgentTimeoutError: Agent execution timed out after 1800.0 seconds`
- result.json: `"exception_stats": {"AgentTimeoutError": ["circuit-fibsqrt__76AKS38"]}`

## 下一步候选

1. **Step 9C full 89-task**：得到真实 pass@1 baseline，circuit-fibsqrt 这种 hard case 在统计上会被稀释
2. **Mitigation 1（seed bootstrap）**：把 3 个 L4-extracted skill 加到 `seed_skills_dir/`，下次 e2e 立即生效
3. **Mitigation 3（stall detector）**：新增 L3 attribution 一个 "thinking tokens growth" 信号