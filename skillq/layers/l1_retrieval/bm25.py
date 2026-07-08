"""L1 retrieval: BM25 keyword scoring (pure function, stdlib-only).

A lexical complement to the cosine embedding similarity in
:mod:`skillq.layers.l1_retrieval.scoring`. Where cosine captures
semantic closeness, BM25 captures exact-term overlap with term
saturation and document-length normalization. The two are fused
in a later task (``scoring.score_skills`` will mix cosine + BM25).

No external dependencies (no numpy, no rank-bm25). Uses only
:mod:`re`, :mod:`math`, and :mod:`collections` from the stdlib.
The function is stateless: no token cache, no persistent index,
no class — every call recomputes IDF from the supplied corpus.

Formula (Robertson & Zaragoza, "The Probabilistic Relevance
Framework: BM25 and Beyond", 2009; IDF variant with +1 smoothing
so IDF is never negative)::

    score(q, d) = Σ_{t ∈ q ∩ d}  IDF(t) · TF(t,d) · (k1 + 1)
                                 ─────────────────────────────
                                 TF(t,d) + k1·(1 − b + b·|d|/avgdl)

    IDF(t) = log( (N − df(t) + 0.5) / (df(t) + 0.5) + 1.0 )

where:

- ``N``      — total number of documents (``len(bodies)``)
- ``df(t)``  — number of documents containing term *t*
- ``TF(t,d)``— raw term frequency of *t* in document *d*
- ``|d|``    — token length of document *d*
- ``avgdl``  — mean document length across the corpus
- ``k1 = 1.5``— TF saturation point (controls how quickly term
               frequency stops increasing the score)
- ``b = 0.75``— document-length normalization strength (0 = none,
               1 = full)

The ``+1.0`` inside the log guarantees ``IDF ≥ 0`` even when a term
appears in every document (``df = N``), preventing rare negative-IDF
contributions that would let ubiquitous terms *decrease* a score.

Scores are L2-normalized so the result vector has unit Euclidean
norm (each element lands in ``[0, 1]`` because every raw score is
non-negative). A ``+1e-9`` floor on the norm avoids division by zero
when no query term matches any document — in that case every element
is ``0.0``.
"""

from __future__ import annotations

import math
import re
from collections import Counter

__all__ = ["bm25_similarity"]


def bm25_similarity(query: str, bodies: list[str]) -> list[float]:
    """Return L2-normalized BM25 scores of ``bodies`` against ``query``.

    Tokenizes with ``re.findall(r'[a-zA-Z0-9_]+', text.lower())``,
    computes IDF across the full corpus, scores each body with BM25
    TF saturation (``k1=1.5``, ``b=0.75``), then L2-normalizes the
    score vector so every element is in ``[0, 1]``.

    Parameters
    ----------
    query : str
        The query text. An empty or whitespace-only query, or a query
        that yields no tokens after tokenization, returns
        ``[0.0] * len(bodies)``.
    bodies : list[str]
        The corpus documents to score. One score per body, in input
        order. An empty list returns ``[]``.

    Returns
    -------
    list[float]
        L2-normalized BM25 scores, one per body. ``normalized[i] =
        score[i] / sqrt(Σ score² + 1e-9)``. When no query term matches
        any body every element is ``0.0``.
    """
    n = len(bodies)
    # Empty/bad input: zero bodies or empty query → all-zeros.
    if n == 0 or not query or not query.strip():
        return [0.0] * n

    query_tokens = re.findall(r"[a-zA-Z0-9_]+", query.lower())
    if not query_tokens:
        return [0.0] * n

    doc_tokens = [re.findall(r"[a-zA-Z0-9_]+", body.lower()) for body in bodies]

    # Document frequency across the full corpus (all bodies).
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))

    # IDF (Robertson/Sparck Jones with +1 smoothing) for query terms.
    query_terms = set(query_tokens)
    idf: dict[str, float] = {}
    for term in query_terms:
        dfreq = df.get(term, 0)
        idf[term] = math.log((n - dfreq + 0.5) / (dfreq + 0.5) + 1.0)

    doc_lens = [len(tokens) for tokens in doc_tokens]
    avg_doc_len = sum(doc_lens) / n

    k1 = 1.5
    b = 0.75
    scores: list[float] = []
    for tokens, doc_len in zip(doc_tokens, doc_lens, strict=True):
        # Empty doc or all-empty corpus → no term can match.
        if not tokens or avg_doc_len == 0.0:
            scores.append(0.0)
            continue
        tf = Counter(tokens)
        norm_len = doc_len / avg_doc_len
        score = 0.0
        for term in query_terms:
            term_tf = tf.get(term, 0)
            if term_tf == 0:
                continue
            denom = term_tf + k1 * (1.0 - b + b * norm_len)
            score += idf[term] * term_tf * (k1 + 1.0) / denom
        scores.append(float(score))

    # L2 normalize: +1e-9 floor so the denominator is never zero.
    l2_norm = math.sqrt(sum(s * s for s in scores) + 1e-9)
    return [float(s / l2_norm) for s in scores]
