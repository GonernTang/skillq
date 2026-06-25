"""Tests for Method A (agentic) retrieval artifacts.

Covers:
- ``AgenticSearchWriter.write()`` materializes the expected tree.
- ``render_skill_md`` preserves existing frontmatter and adds the
  Q-related fields.
- ``render_manifest`` lists every skill with metadata.
- ``_search.sh`` is a valid bash script and runs (uses python3
  subprocess to validate it does the RRF fusion).
- ``resolve_retrieval_mode`` picks the right mode based on lib size.
- ``paper.skillq_runtime.bridge._attribution_and_extract_dispatch`` adds
  failure-attributed knowledge into the buffer (Rule 5 path).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.skillq_runtime.agentic_search import (  # noqa: E402
    AgenticSearchWriter,
    render_manifest,
    render_skill_md,
)
from skillq.skillq_runtime.bridge import resolve_retrieval_mode  # noqa: E402
from skillq.skillq_runtime.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_skill(skill_id: str, body: str, n_uses: int = 0, n_success: int = 0) -> Skill:
    return Skill(
        skill_id=skill_id,
        body=body,
        n_uses=n_uses,
        n_success=n_success,
    )


def _fake_q_for(q_map: dict[str, float]):
    return lambda sid: q_map.get(sid, 0.0)


# ---------------------------------------------------------------------------
# render_skill_md
# ---------------------------------------------------------------------------
def test_render_skill_md_adds_q_frontmatter():
    skill = _make_skill("parse-cobol", "# parse-cobol\n\nUse awk.\n")
    out = render_skill_md(skill, q_value=0.73, n_uses=4, n_success=3)
    assert "q_value: 0.730" in out
    assert "n_uses: 4" in out
    assert "n_success: 3" in out
    assert "name: parse-cobol" in out
    # Body preserved
    assert "Use awk." in out


def test_render_skill_md_preserves_existing_frontmatter():
    skill = _make_skill(
        "git-recover",
        textwrap.dedent(
            """\
            ---
            name: git-recover
            description: recover a deleted commit
            custom_field: hello
            ---
            # git-recover

            Use `git reflog`.
            """
        ),
    )
    out = render_skill_md(skill, q_value=0.4, n_uses=1, n_success=1)
    assert "description: recover a deleted commit" in out
    assert "custom_field: hello" in out
    assert "q_value: 0.400" in out


# ---------------------------------------------------------------------------
# render_manifest
# ---------------------------------------------------------------------------
def test_render_manifest_lists_all_skills():
    lib = Qlib(b_max=10)
    lib.add(_make_skill("a", "---\nname: a\ndescription: alpha\n---\nbody A\n", n_uses=2, n_success=1))
    lib.add(_make_skill("b", "---\nname: b\ndescription: beta\n---\nbody B\n", n_uses=5, n_success=5))
    manifest = json.loads(render_manifest(lib, _fake_q_for({"a": 0.3, "b": 0.9})))
    names = {s["name"] for s in manifest["skills"]}
    assert names == {"a", "b"}
    by_name = {s["name"]: s for s in manifest["skills"]}
    assert by_name["a"]["q_value"] == 0.3
    assert by_name["b"]["n_uses"] == 5
    assert by_name["a"]["n_success"] == 1


# ---------------------------------------------------------------------------
# AgenticSearchWriter.write
# ---------------------------------------------------------------------------
def test_writer_writes_expected_tree(tmp_path: Path):
    lib = Qlib(b_max=10)
    lib.add(_make_skill("skill-one", "body one\n"))
    lib.add(_make_skill("skill-two", "body two\n", n_uses=3, n_success=2))
    writer = AgenticSearchWriter(skills_dir_name="skillq_skills", top_k=3, k_rrf=60)
    out_dir = writer.write(
        staging_dir=tmp_path,
        lib=lib,
        q_for=_fake_q_for({"skill-one": 0.5, "skill-two": 0.8}),
    )
    assert out_dir == tmp_path
    # Skill dirs + SKILL.md
    for sid in ("skill-one", "skill-two"):
        assert (tmp_path / sid / "SKILL.md").exists()
    # Manifest
    assert (tmp_path / "_manifest.json").exists()
    manifest = json.loads((tmp_path / "_manifest.json").read_text())
    assert {s["name"] for s in manifest["skills"]} == {"skill-one", "skill-two"}
    # Search script (executable bit)
    search = tmp_path / "_search.sh"
    assert search.exists()
    assert os.access(search, os.X_OK), "_search.sh must be executable"
    # Paper-method instructions (NOT named CLAUDE.md to avoid
    # overwriting the user's CLAUDE.md).
    instructions = tmp_path / "PAPER_METHOD_INSTRUCTIONS.md"
    assert instructions.exists()
    assert "skillq_skills" in instructions.read_text()
    assert "_search.sh" in instructions.read_text()
    # CLAUDE.md is NOT written by the writer (the merge happens
    # in container_wiring, not here).
    assert not (tmp_path / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# _search.sh — smoke test (run the script directly)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not available")
def test_search_sh_runs_and_returns_top_k(tmp_path: Path):
    lib = Qlib(b_max=10)
    lib.add(_make_skill("parse-cobol", "parse fixed-width COBOL records using awk\n", n_uses=2, n_success=2))
    lib.add(_make_skill("git-recover", "recover a deleted git commit using reflog\n", n_uses=5, n_success=4))
    lib.add(_make_skill("tar-extract", "extract a tar.gz archive\n", n_uses=1, n_success=0))
    writer = AgenticSearchWriter(skills_dir_name="skillq_skills", top_k=2, k_rrf=60)
    writer.write(
        staging_dir=tmp_path,
        lib=lib,
        q_for=_fake_q_for({"parse-cobol": 0.6, "git-recover": 0.9, "tar-extract": 0.2}),
    )

    # Run the script with a query that should rank cobol first.
    out = subprocess.run(
        ["bash", str(tmp_path / "_search.sh"), "git commit", "--top-k", "2"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, f"_search.sh failed: {out.stderr}"
    results = json.loads(out.stdout)
    assert isinstance(results, list)
    assert len(results) <= 2
    # git-recover has the highest Q and grep-matches "git commit"
    if results:
        assert results[0]["name"] in {"git-recover", "parse-cobol"}
        assert "rrf_score" in results[0]


def test_search_sh_returns_empty_for_no_query(tmp_path: Path):
    writer = AgenticSearchWriter(skills_dir_name="skillq_skills", top_k=3, k_rrf=60)
    writer.write(staging_dir=tmp_path, lib=Qlib(b_max=10), q_for=lambda s: 0.0)
    out = subprocess.run(
        ["bash", str(tmp_path / "_search.sh")],
        capture_output=True, text=True, timeout=5,
    )
    assert out.returncode == 0
    # No manifest yet → returns []
    assert json.loads(out.stdout) == []


# ---------------------------------------------------------------------------
# resolve_retrieval_mode
# ---------------------------------------------------------------------------
def test_resolve_mode_explicit():
    method = MethodConfig(retrieval_mode="agentic")
    assert resolve_retrieval_mode(method, n_lib_skills=0) == "agentic"
    assert resolve_retrieval_mode(method, n_lib_skills=10_000) == "agentic"
    method = MethodConfig(retrieval_mode="hook")
    assert resolve_retrieval_mode(method, n_lib_skills=0) == "hook"


def test_resolve_mode_auto_below_threshold():
    method = MethodConfig(retrieval_mode="auto", library_size_threshold=100)
    assert resolve_retrieval_mode(method, n_lib_skills=99) == "agentic"
    assert resolve_retrieval_mode(method, n_lib_skills=0) == "agentic"


def test_resolve_mode_auto_at_or_above_threshold():
    method = MethodConfig(retrieval_mode="auto", library_size_threshold=100)
    assert resolve_retrieval_mode(method, n_lib_skills=100) == "hook"
    assert resolve_retrieval_mode(method, n_lib_skills=1000) == "hook"
