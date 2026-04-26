from examples.app import router
from sovereign.testing import SovereignTestClient


def test_site_homepage_renders():
    client = SovereignTestClient(router, app_state={"started_at": 1})
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Jetzt unterstützt Sovereign auch moderne HTML5-Apps." in resp.text
    assert "/assets/app.css" in resp.text
    assert "/api/status" in resp.text


def test_site_status_endpoint():
    client = SovereignTestClient(router, app_state={"started_at": 1})
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["version"] == "10.5-html5"
    assert "uptime_seconds" in data


def test_site_contact_validation_success():
    client = SovereignTestClient(router)
    resp = client.post("/api/contact", json_body={"name": "Ada", "message": "Hallo Sovereign"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert data["received"]["name"] == "Ada"
    assert data["received"]["length"] == len("Hallo Sovereign")


def test_site_contact_validation_failure():
    client = SovereignTestClient(router)
    resp = client.post("/api/contact", json_body={"name": "Ada"})
    assert resp.status_code == 400
    assert "Validation failed" in resp.text
