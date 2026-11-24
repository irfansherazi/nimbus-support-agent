async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_cors_allows_only_frontend_origin(client):
    r = await client.options(
        "/healthz", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in r.headers


async def test_cors_allows_frontend_origin(client):
    r = await client.options(
        "/healthz", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_serves_the_built_frontend_without_shadowing_the_api(tmp_path):
    # One-service deploy: the backend serves the static Next.js export from "/".
    import httpx

    from app.main import create_app
    from tests.conftest import make_settings

    (tmp_path / "index.html").write_text("<html>Nimbus Support</html>", encoding="utf-8")
    (tmp_path / "_next").mkdir()
    (tmp_path / "_next" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(make_settings(static_dir=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert "Nimbus Support" in (await c.get("/")).text
        assert (await c.get("/_next/app.js")).status_code == 200
        assert (await c.get("/healthz")).json() == {"status": "ok"}
        assert (await c.get("/openapi.json")).status_code == 200


async def test_no_static_dir_means_api_only(client):
    assert (await client.get("/")).status_code == 404
