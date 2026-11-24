from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.store.customers import (
    find_refund,
    get_policy_limit,
    list_invoices,
    record_refund,
    refunded_total_cents,
)
from app.tools.base import ToolEnv, ToolError


class ListInvoicesArgs(BaseModel):
    pass


class IssueRefundArgs(BaseModel):
    invoice_id: str = Field(description="Invoice ID, e.g. INV-2207")
    amount_usd: float = Field(description="Refund amount in US dollars")
    reason: str = Field(description="Short reason the customer gave")


def _usd(cents: int) -> float:
    return round(cents / 100, 2)


async def list_invoices_tool(env: ToolEnv, args: ListInvoicesArgs) -> dict[str, Any]:
    customer = env.require_customer()
    async with env.pool.connection() as conn:
        invoices = await list_invoices(conn, customer.id)
        refunded = {inv.id: await refunded_total_cents(conn, inv.id) for inv in invoices}
    return {
        "invoices": [
            {
                "invoice_id": inv.id,
                "amount_usd": _usd(inv.amount_cents),
                "issued_at": inv.issued_at.isoformat(),
                "description": inv.description,
                "refunded_usd": _usd(refunded[inv.id]),
            }
            for inv in invoices
        ]
    }


async def issue_refund(env: ToolEnv, args: IssueRefundArgs) -> dict[str, Any]:
    customer = env.require_customer()
    if customer.contract_status != "active":
        raise ToolError(
            "CONTRACT_NOT_ACTIVE", f"Contract is {customer.contract_status}; refunds need an active contract."
        )
    key = f"{env.session.id}:{args.invoice_id}"
    cents = round(args.amount_usd * 100)
    today = env.ctx.now().date()

    async with env.pool.connection() as conn, conn.transaction():
        # Lock the invoice row so concurrent refunds on it are serialised (the cumulative cap must hold).
        cur = await conn.execute("SELECT * FROM invoices WHERE id = %s FOR UPDATE", (args.invoice_id,))
        invoice = await cur.fetchone()
        if invoice is None or invoice["customer_id"] != customer.id:
            raise ToolError("INVOICE_NOT_FOUND", f"No invoice {args.invoice_id} on this account.")

        existing = await find_refund(conn, key)
        if existing is not None:
            return {
                "refund_id": existing.id,
                "invoice_id": existing.invoice_id,
                "amount_usd": _usd(existing.amount_cents),
                "already_processed": True,
            }

        remaining = invoice["amount_cents"] - await refunded_total_cents(conn, args.invoice_id)
        if cents <= 0 or cents > remaining:
            raise ToolError(
                "INVALID_AMOUNT", f"Amount must be more than $0 and at most ${_usd(remaining):.2f} for this invoice."
            )
        limit = await get_policy_limit(conn, customer.tier)
        if limit.max_refund_cents <= 0:
            raise ToolError(
                "REFUND_NOT_ELIGIBLE", f"{customer.tier.title()} plan charges are not eligible for refunds."
            )
        if invoice["issued_at"] < today - timedelta(days=limit.window_days):
            raise ToolError(
                "OUTSIDE_REFUND_WINDOW",
                f"Invoice is older than the {limit.window_days}-day refund window for the {customer.tier} plan.",
                hint="offer_escalation",
            )
        if cents > limit.max_refund_cents:
            raise ToolError(
                "AMOUNT_EXCEEDS_LIMIT",
                f"The {customer.tier} plan allows refunds up to ${_usd(limit.max_refund_cents):.2f}.",
                hint="offer a refund within the limit or escalation",
            )
        refund, _ = await record_refund(
            conn,
            invoice_id=args.invoice_id,
            customer_id=customer.id,
            amount_cents=cents,
            reason=args.reason,
            idempotency_key=key,
        )
    return {
        "refund_id": refund.id,
        "invoice_id": refund.invoice_id,
        "amount_usd": _usd(refund.amount_cents),
        "already_processed": False,
    }
