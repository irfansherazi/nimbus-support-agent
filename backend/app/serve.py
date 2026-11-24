"""Local dev server entry point: `python -m app.serve`.

psycopg's async driver can't run on Windows' default Proactor loop, and uvicorn.run() picks that loop itself on
Windows, so the server is driven here on a selector loop. Production (Linux) runs uvicorn directly.
"""

import asyncio
import os
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "app.main:create_app", factory=True, host="127.0.0.1", port=int(os.environ.get("PORT", "8000"))
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
