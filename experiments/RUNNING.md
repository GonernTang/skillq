# 跑 TB 2.0 / TB Pro / SWE-Bench Pro 实验 — 完整指南

`paper` 通过两条互斥的 entrypoint 暴露这两个 benchmark:

- **`paper skillsvote run -c X`** —— 包装 `skills_vote.harbor.cli.run_job`,完全走 SkillsVote 上游的 recommend → feedback → evolve 生命周期(SkillsVote 是 **LQRL 论文对比的 baseline**)。
- **`paper paper run -c Y`** —— 在 SkillsVote agent 之上多套一层 UCB rerank,跑 **LQRL 论文的** β-Q + 库管理 + near-miss 编辑。

三个 benchmark 共用同一份 JobConfig 结构,只是 `datasets:` 字段不同。

---

## 0. 前置条件(一次性)

```bash
cd /home/gonern/workspace/mg
uv sync                                         # 装 paper + skills_vote + harbor + litellm

# 拷贝 lqrl 的 .env 到 paper/ 下(键名完全一致,可直接 cp)
cp /home/gonern/workspace/lqrl/.env.example .env
# 编辑 .env 填入 OPENAI_API_KEY / ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ...
```

### `.env` 格式(跟 lqrl 完全一样)

`paper/.env.example` 已经写好,字段名跟 `lqrl/.env.example` 一致(可直接
`cp lqrl/.env paper/.env`):

```bash
# Codex / OpenAI 路径
OPENAI_BASE_URL=
OPENAI_API_KEY=
CODEX_FORCE_API_KEY=1

# Claude / Anthropic 路径(支持自定义 endpoint,如 deepseek)
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_MODEL=
```

`paper paper run` / `paper prebuild run` / `paper skillsvote run` **都会**自动加载
`.env`(默认 `./.env`,可用 `--env-file` 覆盖)。`paper.env.load_env_file`
在语义上跟 SkillsVote 的 `skills_vote.harbor.cli.load_env_file` 一致:
`override=True` 意味着 .env 里的值会覆盖已有的 shell export。

也可以直接用 shell 环境变量,完全等效:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run paper paper run -c experiments/configs/tb2_paper.yaml
```

---

## 0.5. 预构建 Docker 镜像(强烈建议,第一次跑之前做)

**paper 的实验流和 lqrl 一样需要先 prebuild Docker 镜像**。原因:每个 trial 跑在
一个全新容器里;如果不预构建,每次 trial 都要 apt-get / pip 装 agent
+ 依赖,5-10 分钟一次。预构建把 agent 装一次,打 tag 成
`local/<task_name>:<tag>`,后续 trial 直接复用这个 image。

paper 提供 `paper prebuild` 子命令,内部转调 lqrl 的
`scripts/prebuild_images.py`(避免重复实现):

```bash
# TB 2.0 + Claude Code(默认 4 个并行 worker,tag = 今天日期)
uv run paper prebuild run --benchmark tb2 --agent claude_code

# TB Pro + Codex
uv run paper prebuild run --benchmark tb_pro --agent codex

# SWE-Bench Pro + Claude Code
uv run paper prebuild run --benchmark swebenchpro --agent claude_code

# 自定义 tag(确保多个 run 之间 image 复用)
uv run paper prebuild run --benchmark tb2 --agent claude_code --image-tag 20260605

# 调整并行度(默认 4)
uv run paper prebuild run --benchmark tb2 --agent claude_code --max-workers 8

# 只下载 task 定义,不构建 image(快速验证 task 集合)
uv run paper prebuild run --benchmark tb2 --download-only

# 用自定义 prebuild YAML(指向你 fork 的版本)
uv run paper prebuild run --benchmark tb2 \
    --cfg-path /path/to/my_prebuild.yaml
```

`paper prebuild` 默认按 `(benchmark, agent)` 选 lqrl 的
`scripts/configs/prebuild_images*.yaml`(Claude 用 `.claude.yaml`,Codex
用 `.yaml`)。`--cfg-path` 可以覆盖。镜像打好后会带 `local/<task>:<tag>`
tag,Harbor 在 `Trial.create` 时会优先复用这个 image。

> **时间预估**:
> - TB 2.0 全 89 task × Claude Code:~1-2 小时
> - TB Pro 48 task × Claude Code:~1 小时
> - SWE-Bench Pro 700+ task × Claude Code:~6-12 小时(每个 instance
>   的 repo clone 都要花时间;只跑子集就快得多)

跑过一次后,`docker images | grep local/` 能看到打好的镜像。下次跑
`paper paper run` 直接复用,**不会**重头构建。

**paper 的 prebuild 跟 lqrl 一样吗?** —— 完全一样,只是入口命令不同。lqrl 用
`uv run python lqrl/scripts/prebuild_images.py --cfg-path ...`,paper 用
`uv run paper prebuild run --benchmark ...`。两个最终调的是**同一段
prebuild 逻辑**(paper 的 prebuild_cli.py 内部 `subprocess.run` 调 lqrl 的
`prebuild_images.py`),所以镜像 tag、registry、build args 全部一致。

---

## 1. 直接用现成 config 跑(最快)

`paper/experiments/configs/` 下已经准备好三份 paper-mode YAML:

```bash
# Terminal-Bench 2.0(89 tasks,默认全跑)
uv run paper paper run -c paper/experiments/configs/tb2_paper.yaml

# Terminal-Bench Pro(48 tasks,默认 1 个 task 做冒烟)
uv run paper paper run -c paper/experiments/configs/tb_pro_paper.yaml

# SWE-Bench Pro(700+ tasks,默认 2 个 instance 做冒烟)
uv run paper paper run -c paper/experiments/configs/swebenchpro_paper.yaml
```

**SkillsVote 模式**只是入口不同,配置类似:

```bash
# 1) 把 configs/tb2_paper.yaml 复制一份,把 agents[0].import_path 改成
#    skills_vote.harbor.claude_code:SkillsVoteClaudeCode(去掉 paper_retrieval)
# 2) 跑:
uv run paper skillsvote run -c configs/tb2_skillsvote.yaml
```

`jobs_dir: output` 字段告诉 Harbor 把 trial 结果写到哪里(默认是
`output/<job_name>/<trial_name>/result.json`)。每个 trial end 后
`paper paper` 的 hook 会写 `<job_dir>/.mg_library/.state/method_state.json`。

---

## 2. 用 `run_benchmark.py` 生成 config(推荐,带默认值)

```bash
# TB 2.0, paper 模式, Sonnet 4.5
uv run python -m paper.experiments.run_benchmark \
    --benchmark tb2 \
    --mode paper \
    --agent-model anthropic/claude-sonnet-4-5

# TB Pro, SkillsVote 模式, Codex GPT-5.5
uv run python -m paper.experiments.run_benchmark \
    --benchmark tb_pro \
    --mode skillsvote \
    --agent-import-path skills_vote.harbor.agents:SkillsVoteCodex \
    --agent-model openai/gpt-5.5

# SWE-Bench Pro, paper 模式, Opus 4.1
uv run python -m paper.experiments.run_benchmark \
    --benchmark swebenchpro \
    --mode paper \
    --agent-model anthropic/claude-opus-4-1

# 加 --dry-run 只写 YAML 不跑
uv run python -m paper.experiments.run_benchmark \
    --benchmark tb_pro --mode paper --dry-run

# 自定义并发度 / 重试次数 / 子集
uv run python -m paper.experiments.run_benchmark \
    --benchmark tb2 --mode paper \
    --n-concurrent 4 --n-attempts 1 \
    --task-subset tb2-001 tb2-002
```

`run_benchmark.py` 会:

1. 把 benchmark 默认配置(dataset name/version + 合理并发度)合并进
   JobConfig;
2. 根据 `--mode` 注入正确的 agent `import_path` 和 `kwargs`;
3. 写 YAML 到 `paper/experiments/configs/<benchmark>_<mode>.yaml`;
4. 调用 `uv run paper <mode> run -c <yaml>` 启动。

---

## 3. 手工写 YAML(最高自由度)

参考 `paper/experiments/configs/tb2_paper.yaml` 的结构:

```yaml
jobs_dir: output
job_name: my_run__${now:%Y-%m-%d__%H-%M-%S}
n_attempts: 5
n_concurrent_trials: 8
agent_timeout_multiplier: 4.0
retry:
  max_retries: 3
  exclude_exceptions: [VerifierTimeoutError, ...]
environment:
  type: docker
  force_build: false
  delete: false
agents:
  - import_path: paper.paper_mode.agent:PaperClaudeCodeAgent   # paper mode
    # - import_path: skills_vote.harbor.claude_code:SkillsVoteClaudeCode  # lqrl mode
    model_name: anthropic/claude-sonnet-4-5
    kwargs:
      recommend: {skills_dir: ${abspath:.mg_library/seed}, prompt_path: ...}
      paper_retrieval: {enabled: true, k1: 10, k2: 3}
datasets:
  - name: terminal-bench        # or terminal-bench-pro / swebenchpro
    version: "2.0"              # or "1.0"
    download_dir: input/tb2     # or input/tb-pro / input/swebenchpro
    task_names:                 # 可选:子集
      - some-task-id
```

OmegaConf 的 `${now:%Y-%m-%d__%H-%M-%S}` / `${abspath:...}` 解析 lqrl 自己也用,
(paper) 自动支持。

---

## 4. 看结果

跑完后 Harbor 把每个 trial 写到 `output/<job_name>/<trial_name>/`:

```bash
ls output/tb2_paper__2026-06-05__14-30-00/trial-001/
# result.json         # Harbor TrialResult(verifier_result.rewards 含 reward)
# config.json         # 该 trial 的配置
# agent/              # agent 的 stdout / 日志
# verifier/           # ctrf.json / test-stdout.txt / reward.json
```

`paper paper` 模式额外写:
- `output/<job_name>/.mg_library/.state/method_state.json` — Q-table 持久化
- `output/<job_name>/.mg_library/<skill_name>/` — 被 near-miss 改写的 skill

`paper skillsvote` 模式额外写(由 SkillsVote 自己写,paper 不参与):
- `output/<job_name>/feedback.json`(每 trial)
- `output/<job_name>/skills_vote_evolve_state.json`
- `output/<job_name>/working_skills/`

汇总结果:
```bash
uv run harbor view output/      # Harbor 自带 viewer
```

---

## 5. 跑多 seed / 跑 β sweep / 跑 ablation

`paper/experiments/` 下还有三个 driver:

```bash
# β sweep: 7 个 β 值 × 同一份 job config
uv run python -m paper.experiments.beta_sweep \
    --job-config paper/experiments/configs/tb2_paper.yaml

# Ablation: 6 个 cell(with/without UCB, with/without verifier, with/without near-miss)
uv run python -m paper.experiments.ablation \
    --job-config paper/experiments/configs/tb2_paper.yaml

# Inter-rater κ: 用三个 verifier 后端跑同样的 (old, new) 对
uv run python -m paper.experiments.kappa_sweep \
    --n-pairs 50 --backends stub gpt-4o claude-sonnet-4-5
```

`run_benchmark.py` 不带 seed 参数(每个 trial 内部 `n_attempts` 决定
跑几次;`n_concurrent_trials` 决定并行度)。要做 5-seed 完整跑,
shell 循环调 `run_benchmark.py` 5 次即可,每次改 `--agent-model`
后面挂个 seed 后缀,或者改 `job_name`:

```bash
for seed in 0 1 2 3 4; do
    uv run python -m paper.experiments.run_benchmark \
        --benchmark tb2 --mode paper \
        --job-name tb2_paper_seed${seed}__$(date +%H%M%S)
done
```

---

## 6. 故障排查

| 现象 | 原因 / 修复 |
|------|------------|
| `ModuleNotFoundError: skills_vote` | `uv sync` 跑过吗?或者 `pyproject.toml` 里 `tool.uv.sources.skills_vote` 路径对吗? |
| `ModuleNotFoundError: harbor` | `harbor==0.5.0` 在 deps 里,跑 `uv sync` 重装 |
| trial 跑到一半挂 `Docker daemon not running` | 本地 docker 没起;或者改用 `--env e2b` / `--env daytona` |
| `litellm.AuthenticationError` | 缺 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`,`export` 一下 |
| 第一次 `paper paper run` 跑得很慢 | Docker image 在拉(`terminal-bench` image ≈ 1-2 GB);用 lqrl 的 `prebuild_images.py` 预热 |
| paper 模式写不进 `state.json` | 检查 `output/<job_name>/.mg_library/.state/` 目录权限,bridge 不会自己 `chmod` |
| `qhash()` 跑出大整数 | 正常;`int(hashlib.sha1(text).hexdigest()[:16], 16)` 是设计上的 64-bit key |

---

## 7. 推荐 workflow(论文实验)

1. **冷启动**:在 TB 2.0 选 5 个 task,paper 模式跑 1 个 seed,看 Q-table
   是不是真的在演化(看 `method_state.json` 的 `q_table` 长度)。
2. **基线对比**:同一份 task 列表,paper 模式 + skillsvote 模式 + 无方法(bare
   `harbor run`)各跑一遍,统计 `verifier_result.rewards["reward"]`。
3. **β sweep**:在第 1 步的 5 个 task 上跑 `beta_sweep.py`,挑甜区。
4. **主实验**:TB 2.0 全 89 task × 5 seed,paper 模式 24-48 小时。
5. **Ablation**:同 4 的 task 集,跑 `ablation.py` 的 6 个 cell,验证 UCB
   bonus / verifier / near-miss 各自的贡献。
6. **TB Pro / SWE-Bench Pro**:在 TB 2.0 收敛后,把同一份 agent + 同样的
   `MethodConfig` 平移到这两个 benchmark。**`MethodConfig` 不需要重调**,
   因为它跟 benchmark 解耦,只跟 skill 库的统计性质有关。

---

## 8. 论文 method 的"创建新 skill"路径(`enable_auto_extract`)

**论文原始骨架没有 create 步骤,本框架**加了一个**lqrl 风格**的 extract
路径,默认**关闭**,通过 `MethodConfig.enable_auto_extract=True` 启用。

### 触发条件

每 trial 跑完后,bridge 会先调一次 attribution LLM(读 session jsonl +
available skills 列表,模仿 lqrl 的 `step_feedback`)。在 `r_task=1.0` 且
attribution 落在以下两类的 trial 上,会**进一步**起一个 `claude --print`
subprocess 写新 skill:

| Attribution | 含义 | Q 副作用 |
|-------------|------|---------|
| `SUCCESS_NO_SKILL_SEEN` | 没看到相关 skill,基于自己的探索成功 | 单纯 extract |
| `SUCCESS_VIEWED_SKILL_BUT_NOT_USED` | 看了但没用,基于自己的探索成功 | 看过的那批 skill Q += 0.05(防漂) |

附加守卫:**任何** retrieved skill 的 Q 超过 `theta_consider_used`(默认 0.3)就
跳过 extract,认为"已经被现有 skill 救过,不需要新 skill"。

### 流程(单 trial)

```
on_ended:
  1) 读 trial_dir/agent/sessions/projects/*.jsonl
  2) AttributionAnalyzer.analyze(task, trial_dir, skills_root)
     → TrialAttribution{ overall_attribution, knowledge_to_extract, ... }
     (1 LLM call, LiteLLM, temperature 0)
  3) r_task > 0.5 && attribution ∈ {VIEWED_BUT_NOT_USED, NO_SKILL_SEEN}?
     ├── NO  → 跳过 extract
     └── YES →
            SkillExtractor.extract(task, knowledge, intent_hash)
              → 起 `claude --print` subprocess 写 SKILL.md 到 sandbox
              → 校验 name 长度(1-4 词)+ body token 数(50-2000)
              → 返回 Skill 或 None
            └── 成功 → lib.add(new_skill)
                        mgr.probation_count 置空,走 admission probation
            └── 失败 → logger.warning,跳过
  4) 走 β-Q update + LibManager.maintain(同原来)
  5) 失败 trial 走 NearMissRefiner(同原来)
```

### 怎么开

```yaml
# experiments/configs/tb2_paper_with_extract.yaml 的 method section
method:
  enable_auto_extract: true
  extract_max_new_per_trial: 1     # 一次 trial 至多 1 个新 skill
  extract_timeout_sec: 600         # claude subprocess 超时
  theta_consider_used: 0.30        # 已有 skill 救得了就跳过
  attribution_model: openai/gpt-4o
  extractor_claude_cli: claude     # 走系统的 Claude Code CLI
```

### 跟 lqrl create_skill 的差异

| 维度 | lqrl `step_evolve` | mg `SkillExtractor` |
|------|---------------------|----------------------|
| 触发 | 调度层,每 N 个 trial 一次,无差别 | 条件性:成功 + attribution 命中 + θ 守卫 |
| 调度 | 批量(`aggregate_feedback_payloads`) | 单 trial 内联 |
| 落盘 | Claude 物理写文件(同 mg) | Claude 物理写文件(同 lqrl) |
| 准入 | 直接进 working_skills_dir,无检验 | **走 paper 的 admission probation**——Q=0,过 8 次 retrieval 再说 |
| 频率 | 高(每 N 个 trial 一批) | 低(估 10-20% successful trials) |

### 性能成本

- attribution:1 LLM call/trial,temperature 0,gpt-4o ≈ $0.005
- extractor:仅在 attribution 命中后,1 subprocess call ≈ $0.012
- 100 trial 估算:
  - attribution:100 × $0.005 = $0.50
  - extractor:10-20 × $0.012 = $0.12-$0.24
  - 跟 verifier / editor 同一量级,不影响总成本

### 测试覆盖

- `test_attribution.py` — stub backend, prose-wrapped JSON 解析, session jsonl 加载
- `test_extractor.py` — happy path, 各种 reject(under/over token, bad name, subprocess fail, timeout, missing CLI)
- `test_bridge_extract.py` — 5 个集成测试:成功+NO_SKILL_SEEN 触发;失败不触发;SKILL_USED 不触发;`enable_auto_extract=False` 不构造 extractor;VIEWED_BUT_NOT_USED 触发 Q-bump

45 tests pass(`uv run pytest tests/`)。

### 风险与护栏

- **质量风险**:LLM 从一次成功任务里抽取"可复用知识"是难任务,生成的 skill 经常有任务特异性。**护栏**:`body_min_tokens=50`(防止凑字数)+ `body_max_tokens=2000`(防止灌水)+ `name_max_words=4`(强制精炼)+ probation 8 次 retrieval 自然淘汰低 Q 抽取产物。
- **预算风险**:`B_max=50` 容量小,自动抽取容易撑爆。**护栏**:`extract_max_new_per_trial=1`(单 trial 至多 1 个)+ 失败的 trial 不触发(不浪费配额)+ admission probation 兜底。
- **安全风险**:LLM 物理写文件需要 `bypassPermissions`,必须把 cwd 限制在 sandbox 内。**护栏**:`_collect_skill` 校验文件路径必须是 `<sandbox>/create/<name>/SKILL.md` 的直接子,`name` 必须 1-4 词,`body` 50-2000 token,任一不满足 reject。

### 调试

```bash
# 查看哪些 trial 触发了 extract
grep "Extracted new skill" output/<job_name>/trial-*/agent.log
grep "Extracted new skill" output/<job_name>/logs.txt

# 失败的 extract 原因
grep "extractor" output/<job_name>/logs.txt

# admission 8 次 retrieval 后,新 skill 还在不在?
cat output/<job_name>/.mg_library/.state/method_state.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for sid, skill in data['library']['skills'].items():
    if skill.get('metadata', {}).get('source') == 'mg_paper_extract':
        print(sid, 'still in library')
"
```
