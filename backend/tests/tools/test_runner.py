from tests.tools.test_tools import env_for, run, runner


async def test_runner_emits_steps_and_never_raises(pool):
    env = await env_for(pool)
    out = await runner().run(env, "issue_refund", {"invoice_id": "X", "amount_usd": 1, "reason": "x"}, "call-9")
    emitted = env.ctx.emitted
    assert not out.ok
    assert [e.type for e in emitted] == ["step_started", "step_failed"]
    assert (
        emitted[0].label == "Issuing refund…" and emitted[0].step_id == "call-9" and emitted[1].error == "NOT_VERIFIED"
    )


async def test_runner_records_tool_span(pool):
    env = await env_for(pool, "C-1001")
    await runner().run(env, "list_invoices", {}, "c")
    span = env.ctx.trace.spans[-1]
    assert span.kind == "tool" and span.name == "list_invoices" and span.attrs["ok"] is True


async def test_unknown_tool_and_bad_args_are_structured_errors(pool):
    env = await env_for(pool, "C-1001")
    assert (await runner().run(env, "drop_tables", {}, "c")).error.code == "INVALID_VALUE"
    assert (await runner().run(env, "issue_refund", {"invoice_id": "INV-2207"}, "c")).error.code == "INVALID_VALUE"


async def test_chaos_tool_fail_next_is_one_shot_and_retryable(pool):
    env = await env_for(pool, "C-1001", chaos={"tool_fail_next": "list_invoices"})
    a = await runner().run(env, "list_invoices", {}, "c1")
    b = await runner().run(env, "list_invoices", {}, "c2")
    assert a.error.code == "TOOL_FAILED" and a.error.retryable and b.ok


async def test_chaos_customer_always_fail_second_failure_hints_escalation(pool):
    env = await env_for(pool, "C-1006")  # list_invoices always_fail
    r = runner()
    a = await r.run(env, "list_invoices", {}, "c1")
    b = await r.run(env, "list_invoices", {}, "c2")
    assert a.error.retryable and a.error.hint is None
    assert not b.error.retryable and b.error.hint == "offer_escalation"


async def test_tool_slow_adds_delay(pool):
    env = await env_for(pool, "C-1001", chaos={"tool_slow": "list_invoices"})
    await runner().run(env, "list_invoices", {}, "c")
    assert env.ctx.emitted[-1].duration_ms >= 10


async def test_unexpected_exception_becomes_tool_failed(pool, monkeypatch):
    import app.tools.billing as billing

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(billing, "list_invoices", boom)
    out = await run(pool, "C-1001", "list_invoices", {})
    assert out.error.code == "TOOL_FAILED" and "db down" not in out.error.message
