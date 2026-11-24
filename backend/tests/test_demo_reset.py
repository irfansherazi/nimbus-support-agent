from app.demo import reset_demo_data
from app.store.customers import get_customer, record_refund, refunded_total_cents, update_customer_field


async def test_reset_restores_the_demo_crm(pool):
    # Review I1: on the shared public demo, refunds and edits must not stick forever.
    async with pool.connection() as c:
        await record_refund(
            c, invoice_id="INV-2207", customer_id="C-1001", amount_cents=4900, reason="x", idempotency_key="s:INV-2207"
        )
        await update_customer_field(c, "C-1001", "email", "someone@else.example")
    await reset_demo_data(pool)
    async with pool.connection() as c:
        assert await refunded_total_cents(c, "INV-2207") == 0
        assert (await get_customer(c, "C-1001")).email == "dana@example.com"
