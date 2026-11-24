from typing import Any

from pydantic import BaseModel, Field

from app.rag.retriever import retrieve_any
from app.tools.base import ToolEnv


class SearchPoliciesArgs(BaseModel):
    """Deliberately has no tier argument: the tier filter comes from the verified customer only."""

    query: str = Field(description="What to look up in the Nimbus help centre, in plain words")


async def search_policies(env: ToolEnv, args: SearchPoliciesArgs) -> dict[str, Any]:
    tier = env.customer.tier if env.customer else None
    # The model often shortens the question ("plans offered"), which scores far lower than the customer's own words
    # and would escalate a question the help centre answers. Search with both; the best match per chunk counts.
    own = env.customer_said[-1].strip() if env.customer_said else ""
    queries = [args.query] + ([own] if own and own.lower() != args.query.strip().lower() else [])
    chunks = await retrieve_any(env.pool, env.embedder, queries, tier, env.ctx.settings.rag_top_k)
    result = {
        "query": args.query,
        "customer_query": own or None,
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
