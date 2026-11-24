"""Tune RAG_T_LOW / RAG_T_HIGH on the labelled queries with real embeddings.

Run from backend/:  uv run python ../evals/threshold_sweep.py
Writes evals/results/threshold_sweep.md. Needs OPENAI_API_KEY and an ingested database (python -m app.cli ingest).
"""

import asyncio
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app.config import Settings  # noqa: E402
from app.db import create_pool  # noqa: E402
from app.evals.sweep import LabelledScore, choose, sweep  # noqa: E402
from app.rag.embedder import OpenAIEmbedder  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402

GRID = [round(x / 100, 2) for x in range(15, 71)]


async def main() -> None:
    settings = Settings()
    queries = yaml.safe_load((HERE / "queries.yaml").read_text(encoding="utf-8"))
    pool = await create_pool(settings.database_url)
    embedder = OpenAIEmbedder(settings)
    scored = []
    try:
        for q in queries:
            top = await retrieve(pool, embedder, q["query"], q["tier"], 1)
            scored.append((q, top[0].score if top else 0.0, top[0].section_path if top else "-"))
    finally:
        await pool.close()

    data = [LabelledScore(score, q["expect"] == "escalate") for q, score, _ in scored]
    best = choose(sweep(data, GRID, GRID))
    current = next(r for r in sweep(data, [settings.rag_t_low], [settings.rag_t_high]))

    def band(s: float) -> str:
        return "low" if s < best.t_low else "high" if s >= best.t_high else "grey"

    lines = [
        "# Confidence threshold sweep",
        "",
        f"{len(queries)} labelled queries, `{settings.embedding_model}`, top-1 cosine similarity after tier filtering.",
        "",
        "| | t_low | t_high | escalate precision | escalate recall | out-of-scope answered unchecked | share needing source check |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in (("current", current), ("chosen", best)):
        lines.append(
            f"| {name} | {r.t_low:.2f} | {r.t_high:.2f} | {r.escalate_precision:.0%} | {r.escalate_recall:.0%} "
            f"| {r.high_band_leaks} | {r.grey_rate:.0%} |"
        )
    lines += ["", "## Per query (with the chosen thresholds)", "", "| score | band | expect | kind | query | top section |",
              "|---|---|---|---|---|---|"]
    for q, score, section in sorted(scored, key=lambda x: -x[1]):
        flag = " ⚠" if (q["expect"] == "escalate") != (band(score) == "low") and band(score) != "grey" else ""
        lines.append(f"| {score:.3f} | {band(score)}{flag} | {q['expect']} | {q['kind']} | {q['query']} | {section} |")
    out = HERE / "results" / "threshold_sweep.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"\nRAG_T_LOW={best.t_low:.2f}\nRAG_T_HIGH={best.t_high:.2f}\nwrote {out}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    asyncio.run(main())
