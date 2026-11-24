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
    [vec] = await embedder.embed([query])
    qv = Vector(vec)
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT id, doc_id, section_path, tier, content, 1 - (embedding <=> %s) AS score
               FROM policy_chunks WHERE tier = ANY(%s)
               ORDER BY embedding <=> %s LIMIT %s""",
            (qv, allowed_tiers(tier), qv, k),
        )
        rows = await cur.fetchall()
    return [
        RetrievedChunk(
            chunk_id=r["id"],
            doc_id=r["doc_id"],
            section_path=r["section_path"],
            tier=r["tier"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]
