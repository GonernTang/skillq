# SkillExtractor 没传 model 参数: extract subprocess 行为不稳定 (Gap 5/5)

**Discovered**: 2026-07-01, small10 batch 复盘
**Severity**: Medium — extract LLM 行为漂移, 难复现难调试
**Status**: 未修复

## Summary

`bridge.py` 构造 `SkillExtractor` 时**没传 `model` 参数**, 默认 `model=""`。
这导致 `_extract_with_prompt` 调用 claude CLI 时**不传 `--model` 标志**,
extract subprocess 退化成 claude CLI 默认 model 的行为。

后果:
- extract LLM 实际跑的模型可能是 deepseek-v4-flash (通过 ANTHROPIC_BASE_URL),
  也可能是别的默认 — **取决于 host 上 claude CLI 的默认配置**, 不取决于
  MethodConfig 里设的 `attribution_model` / `editor_model`。
- 即便 LLM 输出 SKILL.md, 因为模型不一致, `_collect_skill` 校验通过率也漂移。
- 失败时无 visible signal — host log 没有"用了哪个 model"的记录。

## 现象 (证据)

### 代码位置

`skillq/runtime/bridge.py:222-229`:
```python
extractor: SkillExtractor | None = (
    SkillExtractor(
        claude_cli=method.extractor_claude_cli,
        timeout_sec=method.extract_timeout_sec,
        # ← model 没传! 默认值 model=""
    )
    if method.enable_auto_extract
    else None
)
```

`skillq/layers/l4_evolve/create.py:180-200`:
```python
cmd = [
    self.claude_cli,
    "--print",
    "--permission-mode=bypassPermissions",
    "--output-format",
    "json",
    *(["--model", self.model] if self.model else []),  # ← 空字符串 falsy, 不传 --model
    "--append-system-prompt",
    system_prompt,
    "-p",
    f"Task: {task}\n\n"
    f"Synthesize a reusable SKILL.md into "
    f"{sandbox}/create/<your-skill-name>/SKILL.md.",
]
```

### 验证

手工 host 上跑 `claude --print --output-format json --append-system-prompt "test" -p "hello"`,
返回的 `modelUsage` 字段是 `"MiniMax-M3"` 而不是 deepseek-v4-flash:

```json
{
  "modelUsage": {
    "MiniMax-M3": {
      "inputTokens": 14822,
      "outputTokens": 72,
      ...
    }
  }
}
```

虽然 ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic 把请求路由到 deepseek,
但 claude CLI 内部的 model 标识符不是 deepseek-v4-flash。

### 行为差异

| 配置 | claude CLI 实际用 model | extract 产出稳定性 |
|---|---|---|
| `--model anthropic/deepseek-v4-flash` | deepseek-v4-flash | ✓ (我手动测能产出 valid SKILL.md) |
| 不传 `--model` | 默认 model (host 配置决定) | ? (没在 production 环境实测过) |

## 根因

### 形成原因

1. `SkillExtractor` 在 2026-06-26 refactor 时被从 lqrl 移植过来, lqrl 的
   `SkillExtractor` 也是 model-less, 移植时没补这层。
2. `MethodConfig` 里有 `attribution_model` / `editor_model`, 但**没有
   `extractor_model` 字段** — 设计上就漏了这个配置点。
3. `bridge.py:218-221` 创建 attribution analyzer 时显式传了 `model=method.attribution_model`,
   但创建 SkillExtractor 时忘了对称处理。
4. 在单次测试场景下 (`extract_every_n_trials=4`), 4 次中 1 次失败被 retry
   或被下一个 batch 兜住, 影响不明显。但 small10 的 threshold=1 + 缺 retry
   (Gap 4), 暴露了这个问题。

## 后果

| 维度 | 影响 |
|---|---|
| Extract LLM 行为一致性 | 取决于 host claude CLI 默认, 不可控 |
| 调试可见性 | 失败时无 model 标识, 难以复现 |
| 配置一致性 | attribution_model / editor_model / (缺失) extractor_model 三个模型分离 |
| Gap 1 放大 | extract LLM 不一致 → sandbox 输出格式不稳定 → name collision / 校验失败概率上升 |
| 实验可复现性 | 在不同 host 上跑同样的 config, extract LLM 可能用不同 model |

## 修复方向

### Fix A: bridge.py 显式传 model (推荐, 改动小, 立刻生效)

`skillq/runtime/bridge.py:222-229`:
```python
extractor: SkillExtractor | None = (
    SkillExtractor(
        claude_cli=method.extractor_claude_cli,
        timeout_sec=method.extract_timeout_sec,
        model=method.attribution_model,  # ← 复用 attribution model, 默认对齐
    )
    if method.enable_auto_extract
    else None
)
```

**优点**: 改动 1 行, 立刻让 extract subprocess 用可控 model
**风险**: 复用 attribution_model 可能在某些场景下不够 (extractor 需要更长 context?)

### Fix B: MethodConfig 加 extractor_model 字段 (推荐同步做)

`skillq/config.py` 在 `attribution_model` 附近:
```python
attribution_model: str = "openai/gpt-4o"
editor_model: str = "openai/gpt-4o"
extractor_model: str = ""  # ← 新增, 空字符串 fallback 到 attribution_model

@model_validator(mode="after")
def _fill_extractor_model_default(self):
    if not self.extractor_model:
        self.extractor_model = self.attribution_model
    return self
```

然后 bridge.py:
```python
extractor = SkillExtractor(
    claude_cli=method.extractor_claude_cli,
    timeout_sec=method.extract_timeout_sec,
    model=method.extractor_model,  # ← 用新的字段
)
```

**优点**: 配置对称, 可独立 tune extract model (例如想要更便宜的 model)
**风险**: 需要 pydantic model 改动, 老 config 可能缺这个字段 (validator 兜底)

### Fix C: extract subprocess log 加 model 标识 (推荐同步做)

`skillq/layers/l4_evolve/create.py:203-211` (subprocess 调用前后):
```python
import json
proc_cmd_str = " ".join(cmd)
logger.info(
    "extract_batch invoking: claude_cli=%s model=%s timeout=%ss n_trials=%d",
    self.claude_cli,
    self.model or "(default)",  # ← 显式标记 "default" vs explicit
    self.timeout_sec,
    len(trials),
)
proc = await asyncio.to_thread(subprocess.run, cmd, ...)
if proc.returncode != 0:
    logger.warning(
        "extract_batch subprocess failed: rc=%s cmd=%s stderr=%s",
        proc.returncode,
        proc_cmd_str,
        proc.stderr[:500] if proc.stderr else "",
    )
```

**优点**: 失败时立刻看到 model 配置, 排查时间大幅缩短
**风险**: 无

### Fix D: 写 unit test pin 这个 model 字段 (推荐同步做)

`tests/test_bridge_extractor_uses_method_model.py`:
```python
def test_skill_extractor_uses_method_attribution_model(method_config):
    """Regression: SkillExtractor must inherit attribution_model.

    Fixed 2026-07-01: bridge.py created extractor without model=,
    so claude CLI fell back to its host default instead of using
    method-configured attribution_model.
    """
    services = build_services(method_config)
    assert services.extractor.model == method_config.attribution_model
```

**优点**: 防回归
**风险**: 无

## 验证

修复后跑 small10, 预期:
- 配置 Fix A/B: extract subprocess 日志显式标记 `model=anthropic/deepseek-v4-flash`
- 调试 Fix C: extract 失败时日志显示实际 cmd + model
- 测试 Fix D: 单元测试断言 extractor.model == method.attribution_model

## 相关文件

- `skillq/runtime/bridge.py:218-243` — `SkillExtractor` 构造 (Fix A 主战场)
- `skillq/layers/l4_evolve/create.py:77-91` — `SkillExtractor` dataclass + 默认 `model=""`
- `skillq/layers/l4_evolve/create.py:180-200` — `_extract_with_prompt` cmd 构造 (Fix C 主战场)
- `skillq/config.py:170-185` — `attribution_model` / `editor_model` 定义 (Fix B 参考)