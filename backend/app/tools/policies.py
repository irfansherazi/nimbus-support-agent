from typing import Any

from pydantic import BaseModel, Field

from app.rag.retriever import retrieve
from app.tools.base import ToolEnv


class SearchPoliciesArgs(BaseModel):
    """Deliberately has no tier argument: the tier filter comes from the verified customer only."""

    query: str = Field(description="What to look up in the Nimbus help centre, in plain words")


async def search_policies(env: ToolEnv, args: SearchPoliciesArgs) -> dict[str, Any]:
    tier = env.customer.tier if env.customer else None
    chunks = await retrieve(env.pool, env.embedder, args.query, tier, env.ctx.settings.rag_top_k)
    result = {
        "query": args.query,
        "tier_filter": tier or "all",
        "top_score": round(chunks[0].score, 4) if chunks else None,
        "chunks": [
            {
                "doc_id": c.doc_id,
                "section_path": c.section_path,
                "tier": c.tier,
                "score": round(c.score, 4),
                "content": c.content,
            }
            for c in chunks
        ],
    }
    env.last_retrieval = result
    return result
