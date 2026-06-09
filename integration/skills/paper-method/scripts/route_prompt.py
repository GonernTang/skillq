"""``route_prompt.py`` — agent-side wrapper for the LQRL paper method.

This is the standalone script that the agent invokes when it reads
``SKILL.md``. It mirrors :func:`paper.paper_mode.retrieval_step.rerank_with_ucb`
but in a self-contained, ``uv run``-able form. By design it uses the
:mod:`paper.method.retrieval.StubEmbedder` so it does not require an
``OPENAI_API_KEY`` to produce a meaningful (deterministic) ranking.

For a real production run, set ``MG_PAPER_EMBEDDER=live`` to switch to
the LiteLLM-backed :class:`paper.method.retrieval.LiteLLMEmbedder`. (The
``live`` mode requires an actual API key; this script does not enforce
that — the LiteLLM call will fail with a clear error from litellm if
the key is missing.)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running this script directly via ``uv run scripts/route_prompt.py``
# without installing the parent package. We add the project root to
# sys.path so ``import paper.method.retrieval`` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper.method.hash import qhash  # noqa: E402
from paper.method.retrieval import (  # noqa: E402
    LiteLLMEmbedder,
    StubEmbedder,
    TwoStageRanker,
)
from paper.method.types import Skill  # noqa: E402


def _list_skills(skills_root: Path) -> list[Skill]:
    if not skills_root.exists():
        return []
    out: list[Skill] = []
    for child in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        body_path = child / "SKILL.md"
        if not body_path.is_file():
            continue
        out.append(
            Skill(
                skill_id=child.name,
                body=body_path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="route_prompt.py")
    parser.add_argument(
        "--role",
        choices=["main", "subagent", "explain"],
        default="main",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=Path(os.environ.get("MG_SKILLS_ROOT", "/skills")),
        help="Directory of skill folders (each with SKILL.md).",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=os.environ.get("MG_QUERY", ""),
        help="The current task description (overrides env).",
    )
    parser.add_argument("--k1", type=int, default=10)
    parser.add_argument("--k2", type=int, default=3)
    parser.add_argument("--lambda_", type=float, default=0.5)
    parser.add_argument("--c_ucb", type=float, default=0.5)
    parser.add_argument(
        "--embedder",
        choices=["stub", "live"],
        default=os.environ.get("MG_PAPER_EMBEDDER", "stub"),
    )
    args = parser.parse_args(argv)

    if args.role == "explain":
        # Audit-only mode: the agent asks for the rationale of a
        # previously printed verdict. We do not have persistent state
        # in this script, so we just print a placeholder.
        print("[route_prompt] explain mode is a no-op in this standalone script.")
        print("Run `paper paper run` to get persistent Q-table state.")
        return 0

    if not args.query:
        print("[route_prompt] no query provided; pass --query '...'", file=sys.stderr)
        return 2

    skills = _list_skills(args.skills_root)
    if not skills:
        print(f"[route_prompt] no skills found under {args.skills_root}", file=sys.stderr)
        return 0

    embedder = LiteLLMEmbedder() if args.embedder == "live" else StubEmbedder()
    ranker = TwoStageRanker(
        embedder=embedder,
        k1=min(args.k1, len(skills)),
        k2=min(args.k2, len(skills)),
        lambda_=args.lambda_,
        c_ucb=args.c_ucb,
    )

    retrieved = ranker.rank(
        query=args.query,
        skills=skills,
        q_value_lookup=lambda _: 0.0,
        total_retrievals=sum(s.n_retrievals for s in skills) + 1,
    )

    print(f"# LQRL paper retrieval — intent_hash={qhash(args.query)}")
    print(f"# phase_a_pool_size={min(args.k1, len(skills))} phase_b_top_k={len(retrieved)}")
    for r in retrieved:
        print(
            f"{r.skill.skill_id}\t"
            f"score={r.score:+.3f}\t"
            f"phase_a={r.phase_a_rank}\tphase_b={r.phase_b_rank}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
