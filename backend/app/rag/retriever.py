"""Tier-filtered cosine retrieval over pgvector."""

from dataclasses import dataclass

from pgvector import Vector

from app.db import Pool
from app.models import ChunkTier, Tier
from app.rag.embedder import Embedder


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    doc_id: str
    section_path: str
    tier: ChunkTier
    content: str
    score: float  # cosine similarity, 1 - cosine distance


def allowed_tiers(tier: Tier | None) -> list[str]:
    """Unverified callers see only public ('all') policy; verified customers also see their own tier."""
    return ["all"] if tier is None else ["all", tier]


async def retrieve(pool: Pool, embedder: Embedder, query: str, tier: Tier | None, k: int) -> list[RetrievedChunk]:
    return await retrieve_any(pool, embedder, [query], tier, k)


async def retrieve_any(
    pool: Pool, embedder: Embedder, queries: list[str], tier: Tier | None, k: int
) -> list[RetrievedChunk]:
    """Top k chunks for any of several phrasings of one question; each chunk keeps its best score."""
    vectors = await embedder.embed(queries)
    best: dict[int, RetrievedChunk] = {}
    async with pool.connection() as conn:
        for vec in vectors:
            qv = Vector(vec)
            cur = await conn.execute(
                """SELECT id, doc_id, section_path, tier, content, 1 - (embedding <=> %s) AS score
                   FROM policy_chunks WHERE tier = ANY(%s)
                   ORDER BY embedding <=> %s LIMIT %s""",
                (qv, allowed_tiers(tier), qv, k),
            )
            for r in await cur.fetchall():
                chunk = RetrievedChunk(
                    chunk_id=r["id"],
                    doc_id=r["doc_id"],
                    section_path=r["section_path"],
                    tier=r["tier"],
                    content=r["content"],
                    score=float(r["score"]),
                )
                if chunk.chunk_id not in best or chunk.score > best[chunk.chunk_id].score:
                    best[chunk.chunk_id] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:k]
