import shutil
from pathlib import Path

import pytest

from app.rag.embedder import HashEmbedder
from app.rag.ingest import LimitsMismatchError, ingest

CORPUS = Path(__file__).resolve().parents[3] / "data" / "policies"


def copy_corpus(dest: Path) -> None:
    for p in CORPUS.glob("*.md"):
        shutil.copy(p, dest / p.name)


@pytest.fixture
async def empty_chunks(pool):
    async with pool.connection() as c:
        await c.execute("TRUNCATE policy_chunks RESTART IDENTITY")
    return pool


async def test_ingest_idempotent(empty_chunks, tmp_path):
    copy_corpus(tmp_path)
    r1 = await ingest(empty_chunks, HashEmbedder(), tmp_path)
    r2 = await ingest(empty_chunks, HashEmbedder(), tmp_path)
    assert r1.inserted > 0 and r2.inserted == 0 and r2.skipped == r1.inserted and r2.deleted == 0


async def test_ingest_removes_chunks_no_longer_in_corpus(empty_chunks, tmp_path):
    copy_corpus(tmp_path)
    r1 = await ingest(empty_chunks, HashEmbedder(), tmp_path)
    (tmp_path / "troubleshooting-login.md").unlink()
    r2 = await ingest(empty_chunks, HashEmbedder(), tmp_path)
    assert r2.deleted > 0 and r2.skipped == r1.inserted - r2.deleted


async def test_ingest_rejects_limit_mismatch(empty_chunks, tmp_path):
    copy_corpus(tmp_path)
    refunds = tmp_path / "refunds.md"
    refunds.write_text(refunds.read_text(encoding="utf-8").replace("$200", "$300"), encoding="utf-8")
    with pytest.raises(LimitsMismatchError):
        await ingest(empty_chunks, HashEmbedder(), tmp_path)


def test_hash_embedder_is_deterministic_and_normalised():
    import math

    e = HashEmbedder(dim=64)
    a = e.embed_sync(["refund window for pro"])[0]
    assert a == e.embed_sync(["refund window for pro"])[0]
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6) and len(a) == 64


async def test_switching_embedding_model_re_embeds_everything(empty_chunks, tmp_path):
    class OtherEmbedder(HashEmbedder):
        model_name = "other-embedder"

    copy_corpus(tmp_path)
    first = await ingest(empty_chunks, HashEmbedder(), tmp_path)
    switched = await ingest(empty_chunks, OtherEmbedder(), tmp_path)
    assert switched.inserted == first.inserted and switched.deleted == first.inserted
    async with empty_chunks.connection() as c:
        rows = await (await c.execute("SELECT DISTINCT embedding_model FROM policy_chunks")).fetchall()
    assert [r["embedding_model"] for r in rows] == ["other-embedder"]
