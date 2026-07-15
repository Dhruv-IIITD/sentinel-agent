"""Embeddings + vector retriever (offline, HashingEmbedder)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.rag.embeddings import HashingEmbedder, cosine
from app.rag.ingest import load_policy_dir
from app.rag.policy import PolicyEngine, default_policy_dir
from app.rag.retriever import KeywordRetriever, VectorRetriever, build_retriever


def _chunks():
    return load_policy_dir(default_policy_dir())


def test_hashing_embedder_deterministic_and_normalized():
    e = HashingEmbedder(dim=64)
    v1, v2 = e.embed("refund over fifty dollars"), e.embed("refund over fifty dollars")
    assert v1 == v2
    assert abs(cosine(v1, v1) - 1.0) < 1e-6


def test_related_text_scores_higher_than_unrelated():
    e = HashingEmbedder(dim=256)
    ref = e.embed("refund approval threshold amount")
    related = e.embed("refunds greater than fifty dollars require manager approval")
    unrelated = e.embed("track the shipment carrier delivery status")
    assert cosine(ref, related) > cosine(ref, unrelated)


def test_vector_retriever_finds_the_refund_clause():
    hits = VectorRetriever(_chunks(), HashingEmbedder(dim=256)).search(
        "refund greater than amount requires manager approval", k=5
    )
    assert hits
    assert any("refund" in (h.section or "").lower() for h in hits)


async def test_policy_routing_matches_with_vector_retriever():
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    engine = PolicyEngine(VectorRetriever(_chunks(), HashingEmbedder(dim=256)))
    assert engine.decide_refund(180.0, recent).needs_approval is True
    assert engine.decide_refund(30.0, recent).needs_approval is False


def test_build_retriever_selects_by_config():
    chunks = _chunks()
    assert isinstance(build_retriever(chunks, Settings(retriever="keyword")), KeywordRetriever)
    assert isinstance(
        build_retriever(chunks, Settings(retriever="vector", database_url="")), VectorRetriever
    )
