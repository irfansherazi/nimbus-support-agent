"""Mock CRM access: customers, invoices, refund limits and refunds."""

from typing import Literal

from app.db import Conn, one
from app.models import Customer, Invoice, PolicyLimit, RefundRow, Tier

EditableField = Literal["email", "phone", "billing_contact"]
_CUSTOMER_COLS = "id, name, tier, contract_status, email, phone, billing_contact, chaos_flags"


async def get_customer(conn: Conn, customer_id: str) -> Customer | None:
    cur = await conn.execute(f"SELECT {_CUSTOMER_COLS} FROM customers WHERE id = %s", (customer_id,))
    row = await cur.fetchone()
    return Customer(**row) if row else None


async def check_pin(conn: Conn, customer_id: str, pin: str) -> bool:
    cur = await conn.execute("SELECT pin FROM customers WHERE id = %s", (customer_id,))
    row = await cur.fetchone()
    return row is not None and row["pin"] == pin


async def list_invoices(conn: Conn, customer_id: str) -> list[Invoice]:
    cur = await conn.execute("SELECT * FROM invoices WHERE customer_id = %s ORDER BY issued_at DESC", (customer_id,))
    return [Invoice(**r) for r in await cur.fetchall()]


async def get_invoice(conn: Conn, invoice_id: str) -> Invoice | None:
    cur = await conn.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
    row = await cur.fetchone()
    return Invoice(**row) if row else None


async def get_policy_limit(conn: Conn, tier: Tier) -> PolicyLimit:
    cur = await conn.execute("SELECT * FROM policy_limits WHERE tier = %s", (tier,))
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f"no policy limit for tier {tier}")
    return PolicyLimit(**row)


async def all_policy_limits(conn: Conn) -> dict[str, PolicyLimit]:
    cur = await conn.execute("SELECT * FROM policy_limits")
    return {r["tier"]: PolicyLimit(**r) for r in await cur.fetchall()}


async def refunded_total_cents(conn: Conn, invoice_id: str) -> int:
    cur = await conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM refunds WHERE invoice_id = %s", (invoice_id,)
    )
    return int((await one(cur))["total"])


async def find_refund(conn: Conn, idempotency_key: str) -> RefundRow | None:
    cur = await conn.execute("SELECT * FROM refunds WHERE idempotency_key = %s", (idempotency_key,))
    row = await cur.fetchone()
    return RefundRow(**row) if row else None


async def record_refund(
    conn: Conn,
    *,
    invoice_id: str,
    customer_id: str,
    amount_cents: int,
    reason: str,
    idempotency_key: str,
) -> tuple[RefundRow, bool]:
    """Insert a refund once per idempotency key. Returns (row, created_now)."""
    cur = await conn.execute(
        """INSERT INTO refunds (invoice_id, customer_id, amount_cents, reason, idempotency_key)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING *""",
        (invoice_id, customer_id, amount_cents, reason, idempotency_key),
    )
    row = await cur.fetchone()
    if row is not None:
        return RefundRow(**row), True
    existing = await find_refund(conn, idempotency_key)
    assert existing is not None
    return existing, False


async def update_customer_field(conn: Conn, customer_id: str, field: EditableField, value: str) -> None:
    if field not in ("email", "phone", "billing_contact"):
        raise ValueError(f"field not editable: {field}")
    await conn.execute(f"UPDATE customers SET {field} = %s WHERE id = %s", (value, customer_id))  # noqa: S608
