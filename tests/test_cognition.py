"""Tests for the cognition layer: MemoryStream, retrieval, reflection, embeddings."""

from __future__ import annotations

import math

import pytest

from cognition.memory_stream import MemoryNode, MemoryStream, MemoryType
from cognition.retrieval import (
    _cosine_similarity,
    _importance_score,
    _min_max_normalize,
    _recency_score,
    _relevance_embedding,
    _relevance_keyword,
    _tokenize,
    retrieve,
)
from cognition.embeddings import EmbeddingCache, EmbeddingProvider
from tests.conftest import MockLLM, populate_memory


# ---------------------------------------------------------------------------
# MemoryStream
# ---------------------------------------------------------------------------


class TestMemoryStream:
    def test_add_and_get(self):
        ms = MemoryStream()
        node = ms.add(
            turn=1,
            memory_type=MemoryType.OBSERVATION,
            description="Kael attacked Lyra",
            poignancy=7,
        )
        assert node.node_id == 0
        assert node.turn_created == 1
        assert node.last_accessed == 1
        assert ms.get(0) is node

    def test_sequential_ids(self):
        ms = MemoryStream()
        n0 = ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=3)
        n1 = ms.add(turn=2, memory_type=MemoryType.OBSERVATION, description="b", poignancy=5)
        assert n0.node_id == 0
        assert n1.node_id == 1

    def test_get_missing(self):
        ms = MemoryStream()
        assert ms.get(99) is None
        assert ms.get(-1) is None

    def test_all(self):
        ms = MemoryStream()
        populate_memory(ms, 5)
        all_nodes = ms.all()
        assert len(all_nodes) == 5
        # Returns a copy
        all_nodes.append(None)
        assert len(ms.all()) == 5

    def test_get_by_type(self):
        ms = MemoryStream()
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="obs", poignancy=3)
        ms.add(turn=2, memory_type=MemoryType.REFLECTION, description="ref", poignancy=8)
        ms.add(turn=3, memory_type=MemoryType.PLAN, description="plan", poignancy=7)
        assert len(ms.get_by_type(MemoryType.OBSERVATION)) == 1
        assert len(ms.get_by_type(MemoryType.REFLECTION)) == 1
        assert len(ms.get_by_type(MemoryType.PLAN)) == 1

    def test_get_recent(self):
        ms = MemoryStream()
        populate_memory(ms, 10)
        recent = ms.get_recent(3)
        assert len(recent) == 3
        assert recent[0].node_id == 7
        assert recent[-1].node_id == 9

    def test_get_recent_more_than_available(self):
        ms = MemoryStream()
        populate_memory(ms, 3)
        recent = ms.get_recent(10)
        assert len(recent) == 3

    def test_get_since(self):
        ms = MemoryStream()
        populate_memory(ms, 10)
        since = ms.get_since(7)
        assert len(since) == 3
        assert all(n.turn_created >= 7 for n in since)

    def test_importance_accumulator(self):
        ms = MemoryStream()
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=5)
        ms.add(turn=2, memory_type=MemoryType.OBSERVATION, description="b", poignancy=8)
        assert ms.importance_accumulator == 13.0

    def test_reset_importance(self):
        ms = MemoryStream()
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=5)
        old_val = ms.reset_importance()
        assert old_val == 5.0
        assert ms.importance_accumulator == 0.0

    def test_len(self):
        ms = MemoryStream()
        assert len(ms) == 0
        populate_memory(ms, 5)
        assert len(ms) == 5

    def test_bool(self):
        ms = MemoryStream()
        assert not ms
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=1)
        assert ms

    def test_touch(self):
        ms = MemoryStream()
        node = ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=1)
        assert node.last_accessed == 1
        node.touch(5)
        assert node.last_accessed == 5

    def test_spo_triple(self):
        ms = MemoryStream()
        node = ms.add(
            turn=1,
            memory_type=MemoryType.OBSERVATION,
            description="Kael attacked Lyra",
            poignancy=7,
            subject="Kael",
            predicate="attacked",
            object_="Lyra",
        )
        assert node.subject == "Kael"
        assert node.predicate == "attacked"
        assert node.object == "Lyra"

    def test_evidence_ids(self):
        ms = MemoryStream()
        node = ms.add(
            turn=1,
            memory_type=MemoryType.REFLECTION,
            description="insight",
            poignancy=8,
            evidence_ids=[0, 1, 2],
        )
        assert node.evidence_ids == [0, 1, 2]

    def test_embedding_stored(self):
        ms = MemoryStream()
        vec = [0.1, 0.2, 0.3]
        node = ms.add(
            turn=1,
            memory_type=MemoryType.OBSERVATION,
            description="test",
            poignancy=3,
            embedding=vec,
        )
        assert node.embedding == vec


# ---------------------------------------------------------------------------
# Retrieval: component scores
# ---------------------------------------------------------------------------


class TestRetrievalComponents:
    def test_tokenize(self):
        tokens = _tokenize("The quick brown fox is running")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "the" not in tokens  # stop word
        assert "is" not in tokens  # stop word

    def test_tokenize_empty(self):
        assert _tokenize("") == set()

    def test_recency_score_same_turn(self):
        node = MemoryNode(
            node_id=0, turn_created=5, last_accessed=5,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=5,
        )
        assert _recency_score(node, current_turn=5, gamma=0.85) == pytest.approx(1.0)

    def test_recency_score_decays(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=5,
        )
        score_near = _recency_score(node, current_turn=1, gamma=0.85)
        score_far = _recency_score(node, current_turn=10, gamma=0.85)
        assert score_near > score_far

    def test_importance_score(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=7,
        )
        assert _importance_score(node) == pytest.approx(0.7)

    def test_relevance_keyword(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION,
            description="Kael attacked Lyra with sword",
            poignancy=5,
            subject="Kael",
            predicate="attacked",
        )
        tokens = _tokenize("Kael attacked")
        score = _relevance_keyword(node, tokens)
        assert score > 0

    def test_relevance_keyword_no_overlap(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION,
            description="weather is sunny",
            poignancy=1,
        )
        tokens = _tokenize("Kael attacked")
        score = _relevance_keyword(node, tokens)
        assert score == 0.0

    def test_relevance_keyword_empty_query(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=1,
        )
        assert _relevance_keyword(node, set()) == 0.0

    def test_cosine_similarity_identical(self):
        a = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, a) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_relevance_embedding(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=5,
            embedding=[1.0, 0.0, 0.0],
        )
        score = _relevance_embedding(node, [1.0, 0.0, 0.0])
        assert score == pytest.approx(1.0)

    def test_relevance_embedding_no_embedding(self):
        node = MemoryNode(
            node_id=0, turn_created=0, last_accessed=0,
            memory_type=MemoryType.OBSERVATION, description="test", poignancy=5,
        )
        assert _relevance_embedding(node, [1.0, 0.0]) == 0.0

    def test_min_max_normalize(self):
        assert _min_max_normalize([1, 2, 3]) == [0.0, 0.5, 1.0]

    def test_min_max_normalize_all_equal(self):
        assert _min_max_normalize([5, 5, 5]) == [1.0, 1.0, 1.0]

    def test_min_max_normalize_empty(self):
        assert _min_max_normalize([]) == []

    def test_min_max_normalize_single(self):
        assert _min_max_normalize([7]) == [1.0]


# ---------------------------------------------------------------------------
# Retrieval: main function
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_empty_memory(self):
        ms = MemoryStream()
        assert retrieve(ms, "test query", current_turn=1) == []

    def test_returns_top_k(self):
        ms = MemoryStream()
        populate_memory(ms, 20)
        result = retrieve(ms, "event", current_turn=20, top_k=5)
        assert len(result) == 5

    def test_retrieval_touches_nodes(self):
        ms = MemoryStream()
        populate_memory(ms, 5)
        result = retrieve(ms, "event_0", current_turn=10, top_k=3)
        for node in result:
            assert node.last_accessed == 10

    def test_keyword_fallback(self):
        ms = MemoryStream()
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="Kael attacked Lyra", poignancy=7, subject="Kael")
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="weather is sunny today", poignancy=3)
        result = retrieve(ms, "Kael attacked", current_turn=2, top_k=1)
        assert result[0].description == "Kael attacked Lyra"

    def test_embedding_retrieval(self):
        ms = MemoryStream()
        ms.add(
            turn=1, memory_type=MemoryType.OBSERVATION,
            description="relevant", poignancy=5,
            embedding=[1.0, 0.0, 0.0],
        )
        ms.add(
            turn=1, memory_type=MemoryType.OBSERVATION,
            description="irrelevant", poignancy=5,
            embedding=[0.0, 1.0, 0.0],
        )
        result = retrieve(
            ms, "query", current_turn=2, top_k=1,
            query_embedding=[1.0, 0.0, 0.0],
        )
        assert result[0].description == "relevant"

    def test_top_k_larger_than_memory(self):
        ms = MemoryStream()
        populate_memory(ms, 3)
        result = retrieve(ms, "event", current_turn=5, top_k=10)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class MockEmbeddingProvider(EmbeddingProvider):
    """A deterministic mock embedding provider for testing."""

    def __init__(self, dim: int = 3):
        self._dim = dim
        self.call_count = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [[float(hash(t) % 100) / 100.0] * self._dim for t in texts]

    @property
    def name(self) -> str:
        return "mock"

    @property
    def dimension(self) -> int:
        return self._dim


class TestEmbeddingCache:
    def test_embed_one(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        vec = cache.embed_one("hello")
        assert len(vec) == 3
        assert provider.call_count == 1

    def test_embed_one_cached(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        v1 = cache.embed_one("hello")
        v2 = cache.embed_one("hello")
        assert v1 == v2
        assert provider.call_count == 1  # second call was cached

    def test_embed_batch(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        vecs = cache.embed_batch(["hello", "world"])
        assert len(vecs) == 2
        assert provider.call_count == 1

    def test_embed_batch_partial_cache(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        cache.embed_one("hello")  # cache "hello"
        assert provider.call_count == 1
        vecs = cache.embed_batch(["hello", "world"])  # "hello" cached, "world" miss
        assert len(vecs) == 2
        assert provider.call_count == 2  # one more call for "world"

    def test_len(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        assert len(cache) == 0
        cache.embed_one("hello")
        assert len(cache) == 1

    def test_lru_eviction(self):
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=2)
        cache.embed_one("a")
        cache.embed_one("b")
        cache.embed_one("c")  # should evict "a"
        assert len(cache) == 2

    def test_is_none_check_not_truthiness(self):
        """EmbeddingCache has __len__, so empty cache is falsy.
        Code must use `is None` checks, not truthiness."""
        provider = MockEmbeddingProvider()
        cache = EmbeddingCache(provider, max_size=10)
        # Empty cache: len==0, bool==False
        assert len(cache) == 0
        assert not cache  # falsy!
        # But it's a valid object — `is None` correctly distinguishes
        assert cache is not None


# ---------------------------------------------------------------------------
# Reflection (with mock LLM)
# ---------------------------------------------------------------------------


class TestReflection:
    def test_below_threshold_returns_empty(self):
        from cognition.reflection import reflect

        ms = MemoryStream()
        populate_memory(ms, 3)
        # Accumulator will be sum of poignancies (1+2+3+...+3 depending on pattern)
        # Reset to ensure below threshold
        ms.importance_accumulator = 10.0  # well below 50
        result = reflect("kael", "warrior", ms, MockLLM(), current_turn=5)
        assert result == []

    def test_too_few_memories(self):
        from cognition.reflection import reflect

        ms = MemoryStream()
        ms.add(turn=1, memory_type=MemoryType.OBSERVATION, description="a", poignancy=30)
        ms.add(turn=2, memory_type=MemoryType.OBSERVATION, description="b", poignancy=30)
        # importance_accumulator = 60 >= 50, but only 2 memories (need >= 3)
        result = reflect("kael", "warrior", ms, MockLLM(), current_turn=5)
        assert result == []

    def test_reflection_with_valid_llm_response(self):
        from cognition.reflection import reflect

        ms = MemoryStream()
        populate_memory(ms, 10)
        ms.importance_accumulator = 60.0  # above threshold

        llm = MockLLM([
            # questions response
            '{"questions": ["What is happening?", "Who is winning?", "What should I do?"]}',
            # insight responses (one per question)
            '{"insight": "The battle is intense", "evidence": [1, 2]}',
            '{"insight": "Kael is leading", "evidence": [3]}',
            '{"insight": "Need to be careful", "evidence": [1]}',
        ])

        result = reflect("kael", "warrior", ms, llm, current_turn=15)
        assert len(result) == 3  # 3 insights
        assert ms.importance_accumulator == 0.0  # reset

    def test_reflection_resets_importance(self):
        from cognition.reflection import reflect

        ms = MemoryStream()
        populate_memory(ms, 10)
        ms.importance_accumulator = 60.0

        llm = MockLLM([
            '{"questions": ["q1", "q2", "q3"]}',
            '{"insight": "i1", "evidence": []}',
            '{"insight": "i2", "evidence": []}',
            '{"insight": "i3", "evidence": []}',
        ])

        reflect("kael", "warrior", ms, llm, current_turn=15)
        assert ms.importance_accumulator == 0.0
