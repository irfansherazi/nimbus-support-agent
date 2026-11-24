from uuid import uuid4

from tests.api.conftest import small_talk_llm
from tests.api.test_sessions import new_session
from tests.voice.test_bridge import FakeTransport

OFFER = "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\n"


def fake_voice(client) -> list[FakeTransport]:
    transports: list[FakeTransport] = []

    async def create_call(settings, offer_sdp, session):
        assert offer_sdp == OFFER and session["tools"][0]["name"] == "consult_agent"
        return "v=0 answer", "rtc_test"

    def transport(settings, call_id):
        transports.append(FakeTransport(hold_open=True))
        return transports[-1]

    registry = client.services.extras["voice"]
    registry.call_factory, registry.transport_factory = create_call, transport
    return transports


async def post_offer(client, sid):
    return await client.post(
        f"/api/voice/calls?session_id={sid}", content=OFFER, headers={"Content-Type": "application/sdp"}
    )


async def test_start_and_end_call(api):
    client = await api(small_talk_llm())
    transports = fake_voice(client)
    sid = await new_session(client)
    r = await post_offer(client, sid)
    assert r.status_code == 201 and r.text == "v=0 answer" and r.headers["content-type"].startswith("application/sdp")
    assert (await post_offer(client, sid)).json()["detail"]["code"] == "VOICE_BUSY"
    assert (await client.delete(f"/api/voice/calls/{sid}")).status_code == 204
    assert transports[0].closed.is_set()


async def test_unknown_session_404(api):
    client = await api(small_talk_llm())
    fake_voice(client)
    assert (await post_offer(client, uuid4())).status_code == 404


async def test_voice_rate_limit(api):
    client = await api(small_talk_llm(), voice_calls_per_hour=1)
    fake_voice(client)
    a, b = await new_session(client), await new_session(client)
    assert (await post_offer(client, a)).status_code == 201
    r = await post_offer(client, b)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMITED"


async def test_budget_exceeded_blocks_voice(api, pool):
    from app.store.spend import add_spend

    client = await api(small_talk_llm(), daily_budget_usd=0.01)
    fake_voice(client)
    async with pool.connection() as c:
        await add_spend(c, 0.02)
    r = await post_offer(client, await new_session(client))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "BUDGET_EXCEEDED"
