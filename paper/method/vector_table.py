"""Vector table — persistent description embeddings for the skill library.

**Lifecycle (per user design 2026-06-11)**: ``emb_cache.json`` is
**updated only when the skill library changes** (skill added, removed,
or its description / body changed). It is NOT re-dumped at every
trial start — that would be wasteful. The bridge is responsible for
calling the ``update_*`` methods when ``LibManager.add`` /
``.remove`` / ``near_miss.replace`` actually fire.

The cache is stored next to ``method_state.json`` at
``<library_root>/.state/emb_cache.json`` and is shipped (read-only)
to the agent container at trial start, so the container-side
``PreToolUse`` hook can do cosine sim against precomputed
description embeddings without re-embedding the whole lib per call.

The host-side :class:`paper.method.embedding_service.EmbeddingService`
HTTP server is what the container's hook calls for the **sub-task**
embedding on each invocation (the only "live" embedding per hook
call).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("paper.method.vector_table")


def _description_of(skill_body: str) -> str:
    """Extract the YAML frontmatter ``description:`` line from a SKILL.md body.

    The hook and the bridge's retrieval both embed the *description*
    (one-line skill summary), not the full body. SKILL.md is
    conventionally::

        ---
        name: ...
        description: One-sentence description
        metadata:
          ...
        ---

        # Body content / instructions

    We pull the first ``description:`` line we find in the frontmatter.
    If the file is not frontmatter-delimited, we fall back to the
    first non-empty line, then to the full body.
    """
    if not skill_body:
        return ""
    # Find the first frontmatter block
    text = skill_body.lstrip()
    if not text.startswith("---"):
        # No frontmatter — first non-empty line
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return text[:200]

    # Find closing ---
    lines = text.splitlines()
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        end = len(lines)

    # Look for ``description: ...`` in lines[1:end]
    for line in lines[1:end]:
        s = line.strip()
        if s.startswith("description:"):
            return s[len("description:"):].strip().strip('"').strip("'")
    # Fallback: first non-empty line
    for line in lines[1:end]:
        if line.strip():
            return line.strip()
    return text[:200]


@dataclass
class VectorTable:
    """Persistent ``{skill_id: description_embedding}`` cache.

    The cache is held as a ``Dict[str, np.ndarray]`` in memory and
    serialised to / from a single JSON file. Embeddings are encoded
    as a list of floats for JSON portability; the on-disk format is
    the same regardless of dimension.

    Lifecycle:
        - :meth:`load` — read emb_cache.json into memory (call once
          at the start of ``bridge.on_ended`` / container setup).
        - :meth:`save` — write memory back to disk (call only when
          :meth:`upsert` / :meth:`remove` mutates state).
        - :meth:`upsert` / :meth:`remove` — called from
          ``LibManager.add`` / ``.remove`` / near-miss ``replace``;
          does NOT call :meth:`save` automatically. The bridge is
          responsible for batching saves (e.g., once per on_ended
          call) to avoid disk thrash.
    """

    cache_path: Path
    embeddings: Dict[str, np.ndarray] = field(default_factory=dict)
    # Set by the most recent save() — guards against the call-after-no-
    # mutation case.
    _dirty: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------
    def load(self) -> bool:
        """Load emb_cache.json. Returns True if loaded, False if missing."""
        if not self.cache_path.exists():
            return False
        data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        emb = data.get("embeddings", {})
        self.embeddings = {
            str(sid): np.asarray(vec, dtype=np.float32)
            for sid, vec in emb.items()
        }
        self._dirty = False
        return True

    def save(self) -> None:
        """Persist current state to emb_cache.json. No-op if not dirty."""
        if not self._dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embeddings": {
                sid: vec.tolist() for sid, vec in self.embeddings.items()
            }
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._dirty = False

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def upsert(self, skill_id: str, embedding: np.ndarray) -> None:
        """Insert or update a skill's description embedding."""
        self.embeddings[skill_id] = np.asarray(embedding, dtype=np.float32)
        self._dirty = True

    def remove(self, skill_id: str) -> None:
        """Drop a skill's embedding (no-op if absent)."""
        if skill_id in self.embeddings:
            del self.embeddings[skill_id]
            self._dirty = True

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def get(self, skill_id: str) -> Optional[np.ndarray]:
        return self.embeddings.get(skill_id)

    def __contains__(self, skill_id: str) -> bool:
        return skill_id in self.embeddings

    def __len__(self) -> int:
        return len(self.embeddings)


# ---------------------------------------------------------------------------
# LibManager hook helpers — called by the bridge when lib mutates
# ---------------------------------------------------------------------------
def sync_lib_to_vector_table(
    *,
    added: Sequence[tuple[str, str]] | None = None,
    removed: Sequence[str] | None = None,
    replaced: Sequence[tuple[str, str, str]] | None = None,
    vector_table: VectorTable,
    embedder: Callable[[Sequence[str]], np.ndarray],
) -> None:
    """Update emb_cache in response to lib changes.

    Parameters
    ----------
    added : list of (skill_id, skill_body)
        New skills to embed. Each ``skill_id`` is added to the cache
        with the embedding of its description (extracted by
        :func:`_description_of`).
    removed : list of skill_id
        Skills evicted from the lib.
    replaced : list of (skill_id, old_body, new_body)
        Skills whose body changed (e.g., near-miss refine). Both old
        and new descriptions are re-extracted; we re-embed and
        overwrite the cache entry.
    vector_table : VectorTable
        The cache to mutate.
    embedder : callable
        ``embedder(texts) -> np.ndarray`` — the same interface as
        :class:`paper.method.retrieval.LiteLLMEmbedder`. Batched for
        efficiency: all descriptions are embedded in a single call.
    """
    if removed:
        for sid in removed:
            vector_table.remove(sid)

    to_embed: list[str] = []
    to_embed_sids: list[str] = []
    if added:
        for sid, body in added:
            desc = _description_of(body)
            to_embed_sids.append(sid)
            to_embed.append(desc)
    if replaced:
        for sid, _old, new_body in replaced:
            desc = _description_of(new_body)
            to_embed_sids.append(sid)
            to_embed.append(desc)

    if to_embed:
        vectors = embedder(to_embed)
        for sid, vec in zip(to_embed_sids, vectors):
            vector_table.upsert(sid, vec)


def vector_table_to_json_payload(vector_table: VectorTable) -> dict[str, Any]:
    """Serialise a VectorTable to the JSON dict format the container hook reads.

    The container's :class:`paper.paper_mode.hook.PreToolUseHook` reads
    ``emb_cache.json`` and consumes this same shape. Keeping the
    serialiser here means the host's load + sync + write path and the
    container's read path share a single source of truth.
    """
    return {
        "embeddings": {
            sid: vec.tolist() for sid, vec in vector_table.embeddings.items()
        }
    }


def json_payload_to_vector_table(
    payload: dict[str, Any],
    cache_path: Path,
) -> VectorTable:
    """Inverse of :func:`vector_table_to_json_payload` (no disk I/O)."""
    emb = payload.get("embeddings", {})
    return VectorTable(
        cache_path=cache_path,
        embeddings={
            str(sid): np.asarray(vec, dtype=np.float32) for sid, vec in emb.items()
        },
    )


__all__ = [
    "VectorTable",
    "_description_of",
    "sync_lib_to_vector_table",
    "vector_table_to_json_payload",
    "json_payload_to_vector_table",
]
