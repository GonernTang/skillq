---
name: _seed_stub
description: Placeholder skill so the seed library exists on this host. Not used by fix-git.
metadata:
  version: "0.0.0"
---

# Seed Stub

Replace with a real skill library to produce useful recommendations.
For the paper-mode smoke test this is enough: SkillsVote's
`step_recommend` copies it into `$CLAUDE_CONFIG_DIR/skills` so
`paper_retrieval` has at least one skill to rank (it will lose to
nothing on cosine, but the UCB breakdown header still gets written
and the bridge's Q-update path still runs).
