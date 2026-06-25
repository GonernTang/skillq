"""Tests for MethodConfig.reuse_q_table / reuse_embedding_cache (2026-06-25).

Covers:
  1. Default values (both True for backward compat).
  2. Explicit override works.
  3. resolved_state_path / resolved_emb_cache_path behavior:
     - Legacy default: <library_root>/.state/
     - Explicit state_path wins; emb_cache lives next to it
     - seed_skills_dir alone does NOT auto-derive state_path to
       <seed_skills_dir>/.skillq_state/ — must be set explicitly
       (this is a deliberate backward-compat choice).
"""
from __future__ import annotations
from pathlib import Path


def test_default_reuse_flags():
    """reuse_q_table and reuse_embedding_cache default to True."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig()
    assert cfg.reuse_q_table is True
    assert cfg.reuse_embedding_cache is True


def test_explicit_reuse_flags():
    """Users can set either flag to False to force fresh start."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig(reuse_q_table=False, reuse_embedding_cache=False)
    assert cfg.reuse_q_table is False
    assert cfg.reuse_embedding_cache is False


def test_resolved_state_path_legacy_default(tmp_path):
    """No seed_skills_dir, no state_path → <library_root>/.state/."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig(library_root=tmp_path / "lib")
    assert cfg.resolved_state_path() == tmp_path / "lib" / ".state" / "method_state.json"
    assert cfg.resolved_emb_cache_path() == tmp_path / "lib" / ".state" / "emb_cache.json"


def test_resolved_state_path_explicit_wins(tmp_path):
    """Explicit state_path always wins; emb_cache sits next to it."""
    from skillq.skillq_runtime.config import MethodConfig

    seed = tmp_path / "skills"
    explicit = tmp_path / "explicit" / "method_state.json"
    cfg = MethodConfig(seed_skills_dir=seed, state_path=explicit)
    assert cfg.resolved_state_path() == explicit
    assert cfg.resolved_emb_cache_path() == explicit.parent / "emb_cache.json"


def test_resolved_state_path_no_auto_derive(tmp_path):
    """seed_skills_dir alone does NOT auto-derive state_path to
    <seed_skills_dir>/.skillq_state/. Users must set state_path
    explicitly to opt into co-location. This avoids silently
    abandoning existing state files when seed_skills_dir is added.
    """
    from skillq.skillq_runtime.config import MethodConfig

    seed = tmp_path / "skills"
    cfg = MethodConfig(seed_skills_dir=seed, library_root=tmp_path / "lib")
    # Falls back to library_root, NOT seed_skills_dir
    assert cfg.resolved_state_path() == tmp_path / "lib" / ".state" / "method_state.json"
    assert cfg.resolved_emb_cache_path() == tmp_path / "lib" / ".state" / "emb_cache.json"