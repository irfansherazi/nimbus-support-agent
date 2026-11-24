"""Operational commands: `python -m app.cli migrate|seed|ingest|release`."""

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.db import create_pool, migrate, run_sql_file

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


async def _migrate() -> None:
    pool = await create_pool(get_settings().database_url)
    try:
        applied = await migrate(pool, BACKEND_DIR / "migrations")
        print(f"migrate: applied {applied or 'nothing (up to date)'}")
    finally:
        await pool.close()


async def _seed() -> None:
    pool = await create_pool(get_settings().database_url)
    try:
        await run_sql_file(pool, BACKEND_DIR / "seed" / "seed.sql")
        print("seed: ok")
    finally:
        await pool.close()


async def _ingest(use_hash: bool = False) -> None:
    from app.rag.embedder import Embedder, HashEmbedder, OpenAIEmbedder
    from app.rag.ingest import ingest

    settings = get_settings()
    if not use_hash and not settings.openai_api_key:
        raise SystemExit("ingest: OPENAI_API_KEY is not set (use --hash for an offline, test-quality index)")
    embedder: Embedder = HashEmbedder() if use_hash else OpenAIEmbedder(settings)
    pool = await create_pool(settings.database_url)
    try:
        report = await ingest(pool, embedder, REPO_DIR / "data" / "policies")
        print(
            f"ingest ({embedder.model_name}): inserted={report.inserted} "
            f"skipped={report.skipped} deleted={report.deleted}"
        )
    finally:
        await pool.close()


async def _release() -> None:
    """Deploy-time step: migrate, re-seed (refreshes relative dates), ingest any changed policy docs."""
    await _migrate()
    await _seed()
    await _ingest()


def _openapi(out: str) -> None:
    """Write the OpenAPI schema (the source of the frontend's generated TypeScript types)."""
    import json

    from app.main import create_app

    Path(out).write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"openapi: wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["migrate", "seed", "ingest", "release", "openapi"])
    parser.add_argument("--hash", action="store_true", help="ingest with the offline hashing embedder")
    parser.add_argument("--out", default="openapi.json", help="output path for the openapi command")
    args = parser.parse_args()
    if args.command == "openapi":
        _openapi(args.out)
    elif args.command == "ingest":
        asyncio.run(_ingest(use_hash=args.hash))
    else:
        asyncio.run({"migrate": _migrate, "seed": _seed, "release": _release}[args.command]())


if __name__ == "__main__":
    main()
