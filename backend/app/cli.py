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


COMMANDS = {"migrate": _migrate, "seed": _seed}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()
    asyncio.run(COMMANDS[args.command]())


if __name__ == "__main__":
    main()
