from examples.app import router, jwt
from sovereign.testing import SovereignTestClient

def test_testclient_and_di_auth():
    c = SovereignTestClient(router)
    token = jwt.create_token({"sub": "tester"})
    r = c.get("/users", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["users"] == ["Ada", "Grace"]

def test_async_handler():
    c = SovereignTestClient(router)
    assert c.get("/async").json()["async"] is True

def test_cors_preflight():
    c = SovereignTestClient(router)
    r = c.request("OPTIONS", "/users", headers={"origin": "https://example.test"})
    assert r.status_code == 204
    assert "Access-Control-Allow-Origin" in r.headers
