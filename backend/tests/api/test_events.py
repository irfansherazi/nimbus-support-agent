from tests.api.conftest import collect_sse, small_talk_llm
from tests.api.test_sessions import new_session


async def test_sse_resume_from_last_event_id(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    first = await collect_sse(client, sid)
    resumed = await collect_sse(client, sid, last_event_id=first[2]["seq"])
    assert [e["seq"] for e in resumed] == [e["seq"] for e in first[3:]]


async def test_sse_query_param_resume_for_first_connect(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    await collect_sse(client, sid)
    # EventSource can't send headers on its first connect, so the page passes the seq it hydrated at.
    async with client.stream("GET", f"/api/sessions/{sid}/events?last_event_id=0") as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                assert '"turn_started"' in line
                break


async def test_sse_headers_disable_buffering(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    async with client.stream("GET", f"/api/sessions/{sid}/events") as r:
        assert r.headers["x-accel-buffering"] == "no"
        assert "no-transform" in r.headers["cache-control"]
