from app.budget import BudgetGuard
from app.chaos import ChaosState, MemoryChaosStore, PgChaosStore
from app.store.sessions import create_session
from tests.fakes import fast_settings


async def test_memory_store_consume_is_one_shot():
    s = MemoryChaosStore({"llm_timeout_next": True, "tool_fail_next": "issue_refund", "tool_slow": "search_policies"})
    assert await s.consume("llm_timeout_next") and not await s.consume("llm_timeout_next")
    assert not await s.consume_tool_fail("list_invoices")
    assert await s.consume_tool_fail("issue_refund") and not await s.consume_tool_fail("issue_refund")
    assert await s.tool_slow() == "search_policies" and await s.tool_slow() == "search_policies"  # sticky


async def test_pg_store_consume_is_atomic_one_shot(pool):
    async with pool.connection() as c:
        sid = (await create_session(c)).id
    store = PgChaosStore(pool, sid)
    await store.set(ChaosState(llm_429_next=True, tool_fail_next="list_invoices").model_dump())
    assert await store.consume("llm_429_next") and not await store.consume("llm_429_next")
    assert not await store.consume_tool_fail("issue_refund")
    assert await store.consume_tool_fail("list_invoices") and not await store.consume_tool_fail("list_invoices")
    assert ChaosState(**await store.get()).llm_429_next is False


async def test_budget_exceeded_after_cap(pool):
    guard = BudgetGuard(pool, fast_settings(daily_budget_usd=0.5))
    assert not await guard.exceeded()
    await guard.charge(0.3)
    assert not await guard.exceeded()
    await guard.charge(0.3)
    assert await guard.exceeded()
