"""Idempotent corpus ingest: chunk, check refund limits against policy_limits, embed only new chunks."""

from dataclasses import dataclass
from pathlib import Path

from pgvector import Vector

from app.db import Pool
from app.rag.chunker import Chunk, chunk_markdown, extract_refund_limits
from app.rag.embedder import Embedder
from app.store.customers import all_policy_limits


class LimitsMismatchError(RuntimeError):
    """The corpus states refund limits that disagree with the policy_limits table (the enforced source)."""


@dataclass(frozen=True)
class IngestReport:
    inserted: int
    skipped: int
    deleted: int


def load_corpus(docs_dir: Path) -> list[Chunk]:
    return [c for p in sorted(docs_dir.glob("*.md")) for c in chunk_markdown(p.stem, p.read_text(encoding="utf-8"))]


async def ingest(pool: Pool, embedder: Embedder, docs_dir: Path) -> IngestReport:
    chunks = load_corpus(docs_dir)

    async with pool.connection() as conn:
        limits = await all_policy_limits(conn)
        enforced = {tier: (lim.max_refund_cents, lim.window_days) for tier, lim in limits.items()}
        stated = extract_refund_limits(chunks)
        if stated != enforced:
            raise LimitsMismatchError(f"corpus states {stated}, policy_limits enforces {enforced}")

        cur = await conn.execute("SELECT content_hash FROM policy_chunks")
        existing = {r["content_hash"] for r in await cur.fetchall()}

    wanted = {c.content_hash: c for c in chunks}
    new = [c for h, c in wanted.items() if h not in existing]
    stale = [h for h in existing if h not in wanted]

    vectors = await embedder.embed([c.embed_text for c in new]) if new else []
    async with pool.connection() as conn, conn.transaction():
        if stale:
            await conn.execute("DELETE FROM policy_chunks WHERE content_hash = ANY(%s)", (stale,))
        for c, v in zip(new, vectors, strict=True):
            await conn.execute(
                """INSERT INTO policy_chunks
                   (doc_id, section_path, tier, doc_type, content, embed_text, content_hash, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (c.doc_id, c.section_path, c.tier, c.doc_type, c.content, c.embed_text, c.content_hash, Vector(v)),
            )
    return IngestReport(inserted=len(new), skipped=len(wanted) - len(new), deleted=len(stale))
