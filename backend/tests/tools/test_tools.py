import asyncio
from pathlib import Path

import pytest

from app.rag.embedder import HashEmbedder
from app.rag.ingest import ingest
from app.store.customers import refunded_total_cents
from app.store.sessions import create_session, get_session, set_customer
from app.store.tickets import list_tickets
from app.tools.base import ToolEnv
from app.tools.registry import build_registry, tool_schemas
from app.tools.runner import ToolRunner
from tests.fakes import make_ctx

CORPUS = Path(__file__).resolve().parents[3] / "data" / "policies"


def runner() -> ToolRunner:
    return ToolRunner(build_registry(), slow_seconds=0.01)


async def env_for(
    pool,
    customer_id: str | None = None,
    chaos: dict | None = None,
    said: list[str] | None = None,
    assistant_said: str = "",
) -> ToolEnv:
    async with pool.connection() as c:
        s = await create_session(c)
        if customer_id:
            await set_customer(c, s.id, customer_id)
    env = await ToolEnv.load(make_ctx(pool=pool, session_id=s.id, chaos=chaos), HashEmbedder())
    env.customer_said = said or []
    env.last_assistant = assistant_said
    return env


async def run(pool, customer_id, name, args, said: list[str] | None = None):
    env = await env_for(pool, customer_id, said=said)
    return await runner().run(env, name, args, "call-1")


@pytest.fixture
async def ingested(pool):
    async with pool.connection() as c:
        await c.execute("TRUNCATE policy_chunks RESTART IDENTITY")
    await ingest(pool, HashEmbedder(), CORPUS)
    return pool


# ------------------------------------------------------------------ identity


async def test_verify_customer_sets_session_customer(pool):
    env = await env_for(pool)
    out = await runner().run(env, "verify_customer", {"account_id": "C-1001", "pin": "4321"}, "c")
    assert out.ok and out.data == {
        "customer_id": "C-1001",
        "name": "Dana Lee",
        "tier": "pro",
        "contract_status": "active",
    }
    assert env.customer and env.customer.id == "C-1001"
    async with pool.connection() as c:
        assert (await get_session(c, env.ctx.session_id)).customer_id == "C-1001"


async def test_unknown_account_looks_like_wrong_pin(pool):
    out = await run(pool, None, "verify_customer", {"account_id": "C-9999", "pin": "1111"})
    assert out.error.code == "INVALID_CREDENTIALS"


async def test_verification_locks_after_three_failures(pool):
    env = await env_for(pool)
    codes = []
    for _ in range(3):
        codes.append(
            (await runner().run(env, "verify_customer", {"account_id": "C-1001", "pin": "0000"}, "c")).error.code
        )
    out = await runner().run(env, "verify_customer", {"account_id": "C-1001", "pin": "4321"}, "c")
    assert codes == ["INVALID_CREDENTIALS", "INVALID_CREDENTIALS", "VERIFICATION_LOCKED"]
    assert out.error.code == "VERIFICATION_LOCKED" and env.customer is None


# ------------------------------------------------------------------ policies


async def test_tier_comes_from_verified_customer_not_args(ingested):
    out = await run(ingested, "C-1003", "search_policies", {"query": "refund", "tier": "enterprise"})
    assert out.ok and out.data["chunks"] and all(c["tier"] in ("all", "free") for c in out.data["chunks"])
    assert out.data["tier_filter"] == "free"


async def test_unverified_search_sees_only_public_docs(ingested):
    out = await run(ingested, None, "search_policies", {"query": "enterprise support hours"})
    assert all(c["tier"] == "all" for c in out.data["chunks"]) and out.data["top_score"] is not None


# ------------------------------------------------------------------ billing


async def test_list_invoices_requires_verification(pool):
    assert (await run(pool, None, "list_invoices", {})).error.code == "NOT_VERIFIED"
    out = await run(pool, "C-1001", "list_invoices", {})
    assert {i["invoice_id"] for i in out.data["invoices"]} == {"INV-2207", "INV-2150", "INV-2099"}


async def test_refund_requires_verification(pool):
    out = await run(pool, None, "issue_refund", {"invoice_id": "INV-2207", "amount_usd": 49, "reason": "x"})
    assert not out.ok and out.error.code == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "cust,inv,amt,code",
    [
        ("C-1001", "INV-2207", 0, "INVALID_AMOUNT"),
        ("C-1001", "INV-2207", -5, "INVALID_AMOUNT"),
        ("C-1001", "INV-2207", 60, "INVALID_AMOUNT"),  # > invoice $49
        ("C-1001", "INV-2150", 49, "OUTSIDE_REFUND_WINDOW"),  # 40 days, pro window 30
        ("C-1001", "INV-2099", 490, "AMOUNT_EXCEEDS_LIMIT"),  # pro max $200
        ("C-1001", "INV-3101", 10, "INVOICE_NOT_FOUND"),  # someone else's invoice
        ("C-1004", "INV-2301", 49, "CONTRACT_NOT_ACTIVE"),
        ("C-1003", "INV-1202", 5, "REFUND_NOT_ELIGIBLE"),  # free tier, $10 add-on invoice
    ],
)
async def test_refund_rejections(pool, cust, inv, amt, code):
    out = await run(pool, cust, "issue_refund", {"invoice_id": inv, "amount_usd": amt, "reason": "x"})
    assert not out.ok and out.error.code == code


async def test_refund_happy_path(pool):
    out = await run(pool, "C-1001", "issue_refund", {"invoice_id": "INV-2207", "amount_usd": 49, "reason": "unused"})
    assert out.ok and out.data["amount_usd"] == 49 and not out.data["already_processed"]


async def test_enterprise_partial_refund_within_limit(pool):
    out = await run(
        pool,
        "C-1002",
        "issue_refund",
        {"invoice_id": "INV-3101", "amount_usd": 1000, "reason": "x"},
        said=["Please refund $1,000 of INV-3101"],
    )
    assert out.ok


async def test_refund_idempotent_within_session(pool):
    env = await env_for(pool, "C-1001")
    args = {"invoice_id": "INV-2207", "amount_usd": 49, "reason": "x"}
    a = await runner().run(env, "issue_refund", args, "c1")
    b = await runner().run(env, "issue_refund", args, "c2")
    assert a.ok and b.ok and b.data["already_processed"] and a.data["refund_id"] == b.data["refund_id"]
    async with pool.connection() as c:
        assert await refunded_total_cents(c, "INV-2207") == 4900


async def test_refund_cumulative_cap_across_sessions(pool):
    args = {"invoice_id": "INV-2207", "amount_usd": 30, "reason": "x"}
    said = ["refund $30 please"]
    assert (await run(pool, "C-1001", "issue_refund", args, said=said)).ok
    out = await run(pool, "C-1001", "issue_refund", args, said=said)  # new session, new idempotency key
    assert out.error.code == "INVALID_AMOUNT"


async def test_concurrent_refunds_never_exceed_invoice(pool):
    envs = [await env_for(pool, "C-1001", said=["refund 30 dollars"]) for _ in range(4)]
    args = {"invoice_id": "INV-2207", "amount_usd": 30, "reason": "x"}
    outs = await asyncio.gather(*(runner().run(e, "issue_refund", args, "c") for e in envs))
    assert sum(o.ok for o in outs) == 1
    async with pool.connection() as c:
        assert await refunded_total_cents(c, "INV-2207") == 3000


# ------------------------------------------------------------------ account


async def test_update_field_allow_list(pool):
    out = await run(pool, "C-1001", "update_account_field", {"field": "tier", "value": "enterprise"})
    assert out.error.code == "INVALID_VALUE"


@pytest.mark.parametrize(
    "field,value,ok",
    [
        ("email", "dana@new.example", True),
        ("email", "not-an-email", False),
        ("phone", "+1 415 555 0199", True),
        ("phone", "call me", False),
        ("billing_contact", "Accounts Payable", True),
        ("billing_contact", "", False),
    ],
)
async def test_update_field_validation(pool, field, value, ok):
    out = await run(pool, "C-1001", "update_account_field", {"field": field, "value": value})
    assert out.ok is ok and (ok or out.error.code == "INVALID_VALUE")


async def test_update_field_requires_verification(pool):
    out = await run(pool, None, "update_account_field", {"field": "email", "value": "a@b.co"})
    assert out.error.code == "NOT_VERIFIED"


# ------------------------------------------------------------------ tickets


async def test_escalation_ticket_created_then_appended(pool):
    env = await env_for(pool, "C-1001")
    args = {"summary": "Customer asks about router support", "category": "other", "priority": "normal"}
    a = await runner().run(env, "create_escalation_ticket", args, "c1")
    b = await runner().run(env, "create_escalation_ticket", {**args, "summary": "Follow-up"}, "c2")
    assert a.ok and a.data["ticket_id"].startswith("T-") and not a.data["appended"]
    assert b.data == {"ticket_id": a.data["ticket_id"], "appended": True}
    async with pool.connection() as c:
        tickets = await list_tickets(c, env.ctx.session_id)
        assert len(tickets) == 1 and tickets[0].customer_id == "C-1001"
        assert (await get_session(c, env.ctx.session_id)).escalation.ticket_id == a.data["ticket_id"]


def test_tool_schemas_are_openai_functions():
    schemas = {s["function"]["name"]: s for s in tool_schemas(build_registry())}
    assert set(schemas) == {
        "verify_customer",
        "search_policies",
        "list_invoices",
        "issue_refund",
        "update_account_field",
        "create_escalation_ticket",
    }
    assert "tier" not in schemas["search_policies"]["function"]["parameters"]["properties"]
    assert schemas["issue_refund"]["function"]["parameters"]["required"] == ["invoice_id", "amount_usd", "reason"]


@pytest.mark.parametrize(
    "account_id,pin",
    [
        ("C1001", "4321"),
        ("c 1001", "4321"),
        ("C-1001", "4 3 2 1"),
        ("c–1001", "4321."),
        ("C.1001", "four three two one"),
    ],
)
async def test_verify_accepts_how_speech_to_text_writes_ids(pool, account_id, pin):
    out = await run(pool, None, "verify_customer", {"account_id": account_id, "pin": pin})
    assert out.ok, (account_id, pin, out.error and out.error.message)


# ------------------------------------------------------------------ refund amount must be the customer's


async def test_agent_cannot_pick_a_refund_amount_the_customer_never_asked_for(pool):
    out = await run(
        pool,
        "C-1001",
        "issue_refund",
        {"invoice_id": "INV-2099", "amount_usd": 200, "reason": "capped"},
        said=["I'm C-1001, PIN 4321. Refund the full $490 on invoice INV-2099."],
    )
    assert out.error.code == "AMOUNT_NOT_CONFIRMED"


async def test_stated_partial_amount_is_allowed(pool):
    out = await run(
        pool,
        "C-1001",
        "issue_refund",
        {"invoice_id": "INV-2099", "amount_usd": 200, "reason": "x"},
        said=["Refund $200 on INV-2099 please"],
    )
    assert out.ok


async def test_full_invoice_needs_no_stated_amount(pool):
    out = await run(
        pool,
        "C-1001",
        "issue_refund",
        {"invoice_id": "INV-2207", "amount_usd": 49, "reason": "x"},
        said=["refund INV-2207"],
    )
    assert out.ok


async def test_yes_to_an_offered_amount_confirms_it(pool):
    env = await env_for(
        pool,
        "C-1001",
        said=["Refund the full $490 on INV-2099", "Yes please, go ahead"],
        assistant_said="The Pro plan allows up to $200. Would you like a $200 refund instead?",
    )
    out = await runner().run(env, "issue_refund", {"invoice_id": "INV-2099", "amount_usd": 200, "reason": "x"}, "c")
    assert out.ok


async def test_plain_yes_without_an_offer_confirms_nothing(pool):
    env = await env_for(pool, "C-1001", said=["Refund INV-2099", "yes"], assistant_said="Anything else?")
    out = await runner().run(env, "issue_refund", {"invoice_id": "INV-2099", "amount_usd": 150, "reason": "x"}, "c")
    assert out.error.code == "AMOUNT_NOT_CONFIRMED"
