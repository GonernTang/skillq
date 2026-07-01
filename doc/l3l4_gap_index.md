# L3/L4 gaps — small10 batch 复盘索引

**Date**: 2026-07-01
**Source run**: `output/tb2_skillq_small10__2026-07-01__11-27-17`
**Model**: deepseek-v4-flash (config `experiments/configs/tb2_skillq_small10.yaml`)

## 摘要

small10 batch 跑完后 0 个新 skill 入库, 0 个 skill 被 L3 edit。但 pipeline
**确实**进入了 L3/L4 路径 — `/tmp/claude-1000/claude-1000/` 下有 4 个
`skillq-extract-*` 沙盒目录说明 L4 CREATE 触发了 4 次 `claude --print`
子进程, 4 次全部被拒收。

本目录的 5 份文档分解了导致 L3/L4 完全无产出的根因:

| # | 文档 | 触因 | 影响 |
|---|---|---|---|
| 1 | [l3l4_gap_1_extract_batch_name_collision.md](l3l4_gap_1_extract_batch_name_collision.md) | `_flush_buffer` 撞名时整批丢弃 | 3 trial L4 CREATE 失败 |
| 2 | [l3l4_gap_2_knowledge_to_extract_empty.md](l3l4_gap_2_knowledge_to_extract_empty.md) | `if knowledge:` 守门 + LLM 输出空 knowledge | 2 trial L4 CREATE 跳过 |
| 3 | [l3l4_gap_3_fail_env_issue_misroute.md](l3l4_gap_3_fail_env_issue_misroute.md) | verifier 失败被 LLM 标 `fail_env_issue` (routing 黑洞) | 1 trial L3 edit 错过 |
| 4 | [l3l4_gap_4_extract_every_n_trials_1.md](l3l4_gap_4_extract_every_n_trials_1.md) | `extract_every_n_trials=1` 让单次失败 = 单 trial 永久丢失 | 放大 Gap 1 / Gap 5 影响 |
| 5 | [l3l4_gap_5_skill_extractor_model_missing.md](l3l4_gap_5_skill_extractor_model_missing.md) | `SkillExtractor(model="")` 不传 `--model` 给 claude CLI | extract 行为漂移, 难复现 |

## Gap 之间的相互作用

```
                    ┌─ Gap 1: 撞名整批丢 ──┐
                    │                      │
attribution ─Gap 2─►├─ Gap 4: threshold=1 ─┼─► extract_batch 4 次全失败
  enum 路由 ─Gap 3─►│                      │
                    └─ Gap 5: model="" ────┘
```

- **Gap 4 是放大器**: threshold=4 时单次 extract 失败只影响 1/4 的 trial,
  但 threshold=1 让 4 次失败 = 4 trial 永久丢失。
- **Gap 1 是主吞并者**: 即使 LLM 输出 valid SKILL.md, 撞名就 batch discard。
- **Gap 5 是隐性 noise**: extract LLM 行为漂移让 sandbox 输出不稳定,
  增加 Gap 1 / Gap 2 的失败概率。
- **Gap 2 / Gap 3 是 attribution 端的 misclassification**:
  enum 路由本身没错, 但 LLM 把 verdict 分类错了, 导致本该 harvest 的
  trial 被跳到 no-op 路径。

## 修复优先级

| 优先级 | Gap | 推荐 Fix | 预期效果 |
|---|---|---|---|
| P0 | Gap 1 | Fix A (撞名版本化) | 立即让 small10 后续 run 多产出 ~3 个 L4 skill |
| P0 | Gap 4 | Fix A (config ge=2) + Fix B (pending queue retry) | 防止 trial 永久丢失 |
| P1 | Gap 3 | Fix A (收紧 prompt) + Fix B (sanity check) | 让失败 trial 的 L3 edit 真正触发 |
| P1 | Gap 5 | Fix A (bridge.py 传 model) | 立刻让 extract 行为可控 |
| P2 | Gap 2 | Fix A (prompt 强制 knowledge 非空) + Fix C (warning log) | 提高 attribution 端一致性 |

## 关联

- Memory: `bridge-inverted-early-return.md`, `attribution-enum-surface.md`,
  `emb-cache-ordering-bug.md` (2026-07-01 修复的同源问题)
- CHANGELOG.md: 待补充本批 5 gap 的修复记录
- Tests: 5 份文档都建议了对应的 regression test, 写完后归入
  `tests/test_l3l4_*.py`

## 数据快照

```python
# .skillq_library/.state/method_state.json
{
  "step": 6,                        # 6 trial 走过 pipeline (4 PASS + 2 timeout)
  "q_table_size": 69,               # 仍是 69 个种子 skill
  "library.skills_count": 69,       # 0 新 skill
  "lib_changes": []                 # 空
}
```

```bash
# /tmp/claude-1000/claude-1000/-tmp-claude-1000-skillq-extract-31298-*
$ ls | wc -l
4                                      # 4 次 extract subprocess 调用
$ ls -la
drwxr-xr-x ... 11:29 ... 6ebf01cd-...  # trial 1
drwxr-xr-x ... 11:32 ... b6f6ea2f-...  # trial 2
drwxr-xr-x ... 11:33 ... f8fc40bd-...  # trial 3
drwxr-xr-x ... 11:42 ... 2d3e476b-...  # final force flush
```

```python
# trial.log 无 L3/L4 输出, 因为 skillq runtime logger 只写到 host log
$ grep -i "l3\|l4\|attribution\|incremental_edit" */trial.log
(空)
```