"""``mg/experiments/kappa_sweep.py`` — inter-rater agreement audit.

The paper's Sec. 4.7 reports κ agreement across three verifier
backends. This driver runs the same (50) skill-delta audits with
``gpt-4o``, ``claude-sonnet-4-5``, and a stub backend, then computes
Cohen's κ for each pair.

Note: requires the OpenAI / Anthropic APIs to be live; the stub
backend is a deterministic baseline.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.method.types import Skill, Verdict  # noqa: E402
from mg.method.verifier import (  # noqa: E402
    IndependentVerifier,
    LiteLLMVerifierBackend,
    StubVerifierBackend,
)


def cohen_kappa(rater_a: Sequence[bool], rater_b: Sequence[bool]) -> float:
    """Compute Cohen's κ for two sequences of boolean labels."""
    assert len(rater_a) == len(rater_b)
    n = len(rater_a)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    p_a = sum(rater_a) / n
    p_b = sum(rater_b) / n
    pe = p_a * p_b + (1 - p_a) * (1 - p_b)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def _sample_pairs(n: int) -> list[tuple[Skill, Skill, Verdict]]:
    """Generate a deterministic stub list of (old, new) pairs for the audit."""
    pairs: list[tuple[Skill, Skill, Verdict]] = []
    for i in range(n):
        old = Skill(skill_id=f"s{i}", body=f"old body {i}")
        new = Skill(skill_id=f"s{i}", body=f"new body {i}")
        verdict = Verdict(
            old_score=0.4,
            new_score=0.5 + (i % 3) * 0.1,
            improved=(i % 2 == 0),
            rationale=f"sample {i}",
        )
        pairs.append((old, new, verdict))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kappa_sweep")
    parser.add_argument("--n-pairs", type=int, default=50)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/kappa_sweep"),
    )
    parser.add_argument(
        "--backends",
        nargs="+",
        default=["stub", "gpt-4o", "claude-sonnet-4-5"],
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pairs = _sample_pairs(args.n_pairs)

    labels: dict[str, list[bool]] = {name: [] for name in args.backends}

    for name in args.backends:
        if name == "stub":
            backend: object = StubVerifierBackend(old_score=0.4, new_score=0.6)
        elif name == "gpt-4o":
            backend = LiteLLMVerifierBackend(model="openai/gpt-4o")
        elif name == "claude-sonnet-4-5":
            backend = LiteLLMVerifierBackend(model="anthropic/claude-sonnet-4-5")
        else:
            print(f"[kappa_sweep] unknown backend: {name}", file=sys.stderr)
            return 2

        verifier = IndependentVerifier(backend=backend, model=name)  # type: ignore[arg-type]
        for old, new, _expected in pairs:
            verdict = verifier.score("audit task", old, new)
            labels[name].append(verdict.improved)

    # Compute pairwise κ
    out: dict[str, dict[str, float]] = {}
    for a in args.backends:
        out[a] = {}
        for b in args.backends:
            if a == b:
                out[a][b] = 1.0
            else:
                out[a][b] = cohen_kappa(labels[a], labels[b])

    (args.output_dir / "kappa.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
