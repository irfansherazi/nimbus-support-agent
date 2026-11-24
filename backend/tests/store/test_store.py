from datetime import UTC, datetime, timedelta

from app.models import Escalation, PolicyLimit
from app.store.customers import (
    check_pin,
    get_customer,
    get_invoice,
    get_policy_limit,
    list_invoices,
    record_refund,
    refunded_total_cents,
    update_customer_field,
)
from app.store.sessions import (
    add_message,
    create_session,
    get_chaos,
    get_session,
    incr_verify_failures,
    recent_messages,
    set_chaos,
    set_customer,
    set_escalation,
)
from app.store.spend import add_spend, today_spend
from app.store.tickets import append_to_ticket, create_ticket, list_tickets
from app.store.traces import list_traces, save_trace


async def test_seed_loaded(pool):
    async with pool.connection() as c:
        assert (await get_customer(c, "C-1001")).tier == "pro"
        assert await check_pin(c, "C-1001", "4321") and not await check_pin(c, "C-1001", "0000")
        assert await get_policy_limit(c, "pro") == PolicyLimit(tier="pro", max_refund_cents=20000, window_days=30)
        assert await get_customer(c, "C-9999") is None


async def test_invoice_dates_are_relative_to_today(pool):
    async with pool.connection() as c:
        inv = await get_invoice(c, "INV-2150")
        assert inv.issued_at == datetime.now(UTC).date() - timedelta(days=40)  # the DB clock is UTC
        assert {i.id for i in await list_invoices(c, "C-1001")} == {"INV-2207", "INV-2150", "INV-2099"}


async def test_record_refund_idempotent(pool):
    async with pool.connection() as c:
        r1, created1 = await record_refund(
            c, invoice_id="INV-2207", customer_id="C-1001", amount_cents=4900, reason="x", idempotency_key="s1:INV-2207"
        )
        r2, created2 = await record_refund(
            c, invoice_id="INV-2207", customer_id="C-1001", amount_cents=4900, reason="x", idempotency_key="s1:INV-2207"
        )
        assert created1 and not created2 and r1.id == r2.id
        assert await refunded_total_cents(c, "INV-2207") == 4900


async def test_update_customer_field(pool):
    async with pool.connection() as c:
        await update_customer_field(c, "C-1001", "email", "dana@new.example")
        assert (await get_customer(c, "C-1001")).email == "dana@new.example"


async def test_session_lifecycle(pool):
    async with pool.connection() as c:
        s = await create_session(c)
        assert (await get_session(c, s.id)).customer_id is None
        await set_customer(c, s.id, "C-1001")
        assert await incr_verify_failures(c, s.id) == 1
        await set_escalation(c, s.id, Escalation(ticket_id="T-100", reason="low_confidence"))
        got = await get_session(c, s.id)
        assert got.customer_id == "C-1001" and got.verify_failures == 1 and got.escalation.ticket_id == "T-100"


async def test_chaos_roundtrip(pool):
    async with pool.connection() as c:
        s = await create_session(c)
        assert await get_chaos(c, s.id) == {}
        await set_chaos(c, s.id, {"llm_timeout_next": True})
        assert await get_chaos(c, s.id) == {"llm_timeout_next": True}


async def test_recent_messages_order_and_limit(pool):
    async with pool.connection() as c:
        s = await create_session(c)
        for i in range(12):
            await add_message(
                c, session_id=s.id, turn_id=f"t{i}", channel="chat", role="user", content=str(i), interrupted=False
            )
        msgs = await recent_messages(c, s.id, 10)
        assert [m.content for m in msgs] == [str(i) for i in range(2, 12)]


async def test_ticket_ids_sequential_and_append(pool):
    async with pool.connection() as c:
        s = await create_session(c)
        kw = dict(customer_id=None, category="policy", priority="normal", reason="low_confidence", turns=[])
        t1 = await create_ticket(c, session_id=s.id, summary="a", **kw)
        t2 = await create_ticket(c, session_id=s.id, summary="b", **kw)
        assert t1.id.startswith("T-") and int(t2.id[2:]) == int(t1.id[2:]) + 1
        await append_to_ticket(c, t1.id, "again", [{"role": "user", "content": "still?"}])
        tickets = await list_tickets(c, s.id)
        assert len(tickets) == 2 and "again" in tickets[0].summary


async def test_traces_and_spend(pool):
    async with pool.connection() as c:
        s = await create_session(c)
        await save_trace(c, "turn_1", s.id, "chat", "ok", [{"name": "agent"}], [{"model": "m"}], {"total_ms": 5})
        assert (await list_traces(c, s.id))[0]["turn_id"] == "turn_1"
        assert await add_spend(c, 0.25) == 0.25 and await add_spend(c, 0.5) == 0.75
        assert await today_spend(c) == 0.75


async def test_save_trace_twice_merges_spans_usage_and_latency(pool):
    from app.store.traces import append_trace

    async with pool.connection() as c:
        s = await create_session(c)
        await save_trace(c, "v_1", s.id, "voice", "ok", [{"span_id": "a"}], [{"cost_usd": 0.1}], {"total_ms": 5})
        await save_trace(c, "v_1", s.id, "voice", "escalated", [{"span_id": "b"}], [{"cost_usd": 0.2}], {"ttft_ms": 3})
        await append_trace(c, "v_1", s.id, "voice", spans=[{"span_id": "c"}], usage=[{"cost_usd": 0.3}])
        [t] = await list_traces(c, s.id)
    assert [x["span_id"] for x in t["spans"]] == ["a", "b", "c"]
    assert len(t["usage"]) == 3 and t["latency"] == {"total_ms": 5, "ttft_ms": 3} and t["status"] == "escalated"


async def test_merge_latency_creates_the_trace_row_if_missing(pool):
    from app.store.traces import merge_latency

    async with pool.connection() as c:
        s = await create_session(c)
        await merge_latency(c, "v_9", {"voice_e2e_ms": 640}, session_id=s.id, channel="voice")
        [t] = await list_traces(c, s.id)
    assert t["latency"] == {"voice_e2e_ms": 640} and t["channel"] == "voice"
