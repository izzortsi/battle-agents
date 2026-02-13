"""Retrieval — three-factor memory scoring (recency + importance + relevance).

Implements the Park et al. retrieval function:
    score = α_rec · recency + α_imp · importance + α_rel · relevance

All three components are min-max normalized to [0, 1] before combining.
Relevance uses keyword overlap as a fallback when embeddings are unavailable.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from cognition.memory_stream import MemoryNode, MemoryStream

# -- Default hyperparameters (from spec) ------------------------------------

DEFAULT_DECAY: float = 0.85  # γ — recency decay factor
DEFAULT_TOP_K: int = 7
DEFAULT_ALPHA_REC: float = 1.0
DEFAULT_ALPHA_IMP: float = 1.0
DEFAULT_ALPHA_REL: float = 1.0

# -- Tokenisation for keyword overlap --------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "at",
        "to",
        "in",
        "on",
        "of",
        "for",
        "and",
        "or",
        "but",
        "not",
        "with",
        "this",
        "that",
        "it",
        "by",
        "from",
        "as",
        "be",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "i",
        "you",
        "he",
        "she",
        "they",
        "we",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
    }
)


def _tokenize(text: str) -> set[str]:
    """Lowercase tokenize, strip stop words."""
    words = set(_WORD_RE.findall(text.lower()))
    return words - _STOP_WORDS


# -- Component scores -------------------------------------------------------


def _recency_score(node: MemoryNode, current_turn: int, gamma: float) -> float:
    """Exponential decay: γ^Δt where Δt = turns since creation."""
    dt = max(0, current_turn - node.turn_created)
    return gamma**dt


def _importance_score(node: MemoryNode) -> float:
    """Normalized poignancy: poignancy / 10."""
    return node.poignancy / 10.0


def _relevance_keyword(node: MemoryNode, query_tokens: set[str]) -> float:
    """Keyword overlap relevance (fallback when no embeddings).

    Jaccard-ish: |intersection| / max(|query|, 1) — biased toward recall.
    """
    if not query_tokens:
        return 0.0
    node_tokens = _tokenize(node.description)
    if node.subject:
        node_tokens |= _tokenize(node.subject)
    if node.predicate:
        node_tokens |= _tokenize(node.predicate)
    if node.object:
        node_tokens |= _tokenize(node.object)

    overlap = len(query_tokens & node_tokens)
    return overlap / max(len(query_tokens), 1)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _relevance_embedding(node: MemoryNode, query_embedding: list[float]) -> float:
    """Embedding-based relevance (cosine similarity)."""
    if node.embedding is None:
        return 0.0
    return _cosine_similarity(node.embedding, query_embedding)


# -- Min-max normalisation ---------------------------------------------------


def _min_max_normalize(values: list[float]) -> list[float]:
    """Normalize values to [0, 1] range.  If all equal, return 1.0 for each."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# -- Main retrieval function ------------------------------------------------


def retrieve(
    memory: MemoryStream,
    query: str,
    current_turn: int,
    top_k: int = DEFAULT_TOP_K,
    gamma: float = DEFAULT_DECAY,
    alpha_rec: float = DEFAULT_ALPHA_REC,
    alpha_imp: float = DEFAULT_ALPHA_IMP,
    alpha_rel: float = DEFAULT_ALPHA_REL,
    query_embedding: Optional[list[float]] = None,
) -> list[MemoryNode]:
    """Retrieve the top-K most relevant memories for a given query.

    Uses three-factor scoring from Park et al.:
        score = α_rec · recency + α_imp · importance + α_rel · relevance

    All three components are min-max normalized to [0, 1].

    Args:
        memory: the agent's memory stream
        query: natural-language query (e.g. current situation description)
        current_turn: current simulation turn number
        top_k: how many memories to return
        gamma: recency decay factor (0 < γ < 1)
        alpha_rec/imp/rel: weighting coefficients
        query_embedding: optional pre-computed embedding of the query
            (if provided and nodes have embeddings, uses cosine similarity
             instead of keyword overlap for relevance)

    Returns:
        top-K MemoryNodes sorted by descending combined score.
    """
    nodes = memory.all()
    if not nodes:
        return []

    # Compute raw component scores
    raw_rec = [_recency_score(n, current_turn, gamma) for n in nodes]
    raw_imp = [_importance_score(n) for n in nodes]

    # Relevance: prefer embeddings if available, else keyword overlap
    query_tokens = _tokenize(query)
    use_embeddings = query_embedding is not None and any(
        n.embedding is not None for n in nodes
    )

    if use_embeddings:
        raw_rel = [_relevance_embedding(n, query_embedding) for n in nodes]  # type: ignore[arg-type]
    else:
        raw_rel = [_relevance_keyword(n, query_tokens) for n in nodes]

    # Normalize each component to [0, 1]
    norm_rec = _min_max_normalize(raw_rec)
    norm_imp = _min_max_normalize(raw_imp)
    norm_rel = _min_max_normalize(raw_rel)

    # Combined score
    scored: list[tuple[float, MemoryNode]] = []
    for i, node in enumerate(nodes):
        score = (
            alpha_rec * norm_rec[i] + alpha_imp * norm_imp[i] + alpha_rel * norm_rel[i]
        )
        scored.append((score, node))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Touch retrieved nodes (updates last_accessed for future recency)
    result = []
    for _, node in scored[:top_k]:
        node.touch(current_turn)
        result.append(node)

    return result
