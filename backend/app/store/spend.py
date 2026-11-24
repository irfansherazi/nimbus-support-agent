"""Daily estimated API spend, used by the budget kill switch."""

from app.db import Conn, one


async def add_spend(conn: Conn, usd: float) -> float:
    cur = await conn.execute(
        """INSERT INTO spend (day, usd) VALUES (CURRENT_DATE, %s)
           ON CONFLICT (day) DO UPDATE SET usd = spend.usd + EXCLUDED.usd RETURNING usd""",
        (usd,),
    )
    return float((await one(cur))["usd"])


async def today_spend(conn: Conn) -> float:
    cur = await conn.execute("SELECT usd FROM spend WHERE day = CURRENT_DATE")
    row = await cur.fetchone()
    return float(row["usd"]) if row else 0.0
