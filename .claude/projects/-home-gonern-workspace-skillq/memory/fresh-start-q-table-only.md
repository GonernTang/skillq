---
name: fresh-start-q-table-only
description: "--fresh-start in run_benchmark.py only flips reuse_q_table=False; emb_cache is left untouched (content-derived, invariant across runs)."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 867fbe5d-7c51-4933-85a3-c664c70646d8
---
When `experiments/run/run_benchmark.py --fresh-start` is set, it ONLY forces `reuse_q_table=False`. It does NOT touch `reuse_embedding_cache`.

**Why:** emb_cache entries are `VectorTable` rows keyed by `skill_id` and valued with `np.float32` embedding of the skill's body text (`skillq/shared/embeddings.py:130-175`). Since skill bodies are content-derived and don't change between runs, the cache is invariant across runs — invalidating it on fresh-start is wasteful. Only Q-table is run-history-dependent (it accumulates trial rewards + visit counts).

**How to apply:** When the user says "fresh-start" or "start clean", use `--fresh-start` flag. When reasoning about cache lifetime, remember that emb_cache persists across fresh-starts; you can safely `ls <lib_root>/.state/emb_cache.json` between runs without rebuilding it. To force a rebuild (e.g., after an embedder-model swap), pass `--method-override reuse_embedding_cache=false` instead.

**Did before:** As of 2026-06-21, `--fresh-start` flipped BOTH flags. User caught this on 2026-06-30 and called out that seed-skill embeddings are static — only Q-table should reset. Fix landed 2026-06-30 21:05.

See also [[full-run-fresh-start-permissions]] and [[extract-every-n-trials-default-1]].
