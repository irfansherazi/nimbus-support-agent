from pathlib import Path

import pytest

from app.rag.embedder import HashEmbedder
from app.rag.ingest import ingest
from app.rag.retriever import retrieve

CORPUS = Path(__file__).resolve().parents[3] / "data" / "policies"


@pytest.fixture
async def ingested(pool):
    async with pool.connection() as c:
        await c.execute("TRUNCATE policy_chunks RESTART IDENTITY")
    await ingest(pool, HashEmbedder(), CORPUS)
    return pool


async def test_retrieve_filters_by_tier(ingested):
    unverified = await retrieve(ingested, HashEmbedder(), "refund window", tier=None, k=5)
    pro = await retrieve(ingested, HashEmbedder(), "refund window pro plan", tier="pro", k=5)
    assert unverified and all(c.tier == "all" for c in unverified)
    assert {c.tier for c in pro} <= {"all", "pro"} and any(c.tier == "pro" for c in pro)
    assert [c.score for c in pro] == sorted([c.score for c in pro], reverse=True)


async def test_retrieve_returns_k_with_scores_in_range(ingested):
    got = await retrieve(ingested, HashEmbedder(), "how do I reset my password", tier="enterprise", k=3)
    assert len(got) == 3 and all(-1.0 <= c.score <= 1.0 for c in got)
    assert got[0].section_path and got[0].content and got[0].doc_id
