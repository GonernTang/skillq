"""Unit tests for ``skillq.layers.l1_retrieval.bm25.bm25_similarity``.

Covers six behaviors of the BM25 keyword scorer:
  a. Tokenization strips punctuation and lowercases.
  b. Exact keyword match outranks an unrelated body.
  c. Zero term overlap yields all-zero scores.
  d. IDF weighting: a rare term contributes more than a ubiquitous one.
  e. L2 normalization keeps every score in [0, 1] and the vector
     norm ≈ 1.0.
  f. Fusion: ``max(cossim, bm25)`` picks the BM25 signal when it
     exceeds the cosine gate.

All bodies are inline string literals — no skill files are read from
disk. No external packages (numpy/scipy) are used.
"""

from __future__ import annotations

import math

from skillq.layers.l1_retrieval.bm25 import bm25_similarity


def test_tokenize():
    """Punctuation is stripped and casing is ignored during tokenization.

    ``"Hello, World!"`` tokenizes to ``["hello", "world"]``, so the
    body ``"hello world"`` matches while ``"goodbye"`` does not.
    """
    scores = bm25_similarity("Hello, World!", ["hello world", "goodbye"])
    assert scores[0] > scores[1]
    assert scores[1] == 0.0


def test_exact_match():
    """A body containing the query's keywords outranks an unrelated one.

    Query ``"crack 7z hashcat"`` against a body about 7z/hashcat
    cracking vs. a body about SPARQL. The first body shares the
    terms ``7z`` and ``hashcat``; the second shares none.
    """
    b1 = "How to crack a 7z archive password using hashcat"
    b2 = "Querying RDF data with SPARQL endpoints and ontologies"
    scores = bm25_similarity("crack 7z hashcat", [b1, b2])
    assert scores[0] > scores[1]
    assert scores[1] == 0.0


def test_zero_match():
    """No shared terms between query and bodies → all scores are 0.0."""
    scores = bm25_similarity("xyz unknown", ["hello world"])
    assert len(scores) == 1
    assert scores[0] == 0.0


def test_idf_rare_terms():
    """A rare term (``hashcat``, df=1) outweighs a ubiquitous one
    (``the``, df=2) because IDF rewards rarity.

    Both documents contain ``the``; only the first contains
    ``hashcat``. Querying ``"the hashcat"`` must therefore rank the
    first document higher.
    """
    doc_with_rare = "the hashcat tool cracks passwords"
    doc_common_only = "the quick brown fox jumps"
    scores = bm25_similarity("the hashcat", [doc_with_rare, doc_common_only])
    assert scores[0] > scores[1]


def test_l2_normalized_range():
    """Every returned score lies in [0, 1] and the L2 norm of the
    score vector is ≈ 1.0 (within 1e-6).

    Uses three bodies so at least one matches the query and the
    normalization denominator is non-trivial.
    """
    bodies = [
        "python unit test with pytest",
        "python integration testing",
        "java maven build",
    ]
    scores = bm25_similarity("python test", bodies)
    assert len(scores) == len(bodies)
    for s in scores:
        assert 0.0 <= s <= 1.0
    sum_of_squares = sum(s * s for s in scores)
    assert abs(sum_of_squares - 1.0) < 1e-6


def test_fusion_effect():
    """``max(cossim, bm25)`` fusion selects the BM25 signal when it
    exceeds the cosine gate.

    Scenario: cosine similarity is 0.4 (below a typical 0.5 gate)
    while BM25 strongly matches the query (above the gate). The
    fused score must equal the BM25 score, not the cosine score.
    """
    bodies = [
        "hashcat cracks password hashes quickly",
        "sparql rdf graph query",
        "docker compose up containers",
    ]
    scores = bm25_similarity("hashcat crack", bodies)
    bm25_top = scores[0]
    # BM25 strongly matches body 0; the other two bodies do not
    # share any query term, so the normalized top score is high.
    assert bm25_top > 0.0

    cossim = 0.4  # cosine below the gate
    fused = max(cossim, bm25_top)
    assert fused == bm25_top
    assert fused > cossim
