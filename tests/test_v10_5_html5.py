from __future__ import annotations

from pathlib import Path

from examples.app import router
from sovereign import AssetManifest, HTML5App, Router, SovereignTestClient


ROOT = Path(__file__).resolve().parents[1]


def test_html5_spa_fallback_and_security_headers():
    client = SovereignTestClient(router)
    resp = client.get("/dashboard/settings", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text
    assert "Sovereign HTML5 Runtime" in resp.text
    assert "Content-Security-Policy" in resp.headers
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]


def test_html5_assets_mime_etag_and_manifest():
    client = SovereignTestClient(router)
    css = client.get("/assets/app.css")
    assert css.status_code == 200
    assert css.response.content_type.startswith("text/css")
    assert "ETag" in css.headers
    manifest = client.get("/__assets.json").json()
    assert "/assets/app.css" in manifest
    assert manifest["/assets/app.css"]["integrity"].startswith("sha256-")


def test_html5_range_requests_for_assets():
    client = SovereignTestClient(router)
    resp = client.get("/assets/app.js", headers={"range": "bytes=0-10"})
    assert resp.status_code == 206
    assert resp.headers["Content-Range"].startswith("bytes 0-10/")
    assert len(resp.content) == 11


def test_router_supports_path_converter_for_deep_links(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    r = Router()
    HTML5App(root=site).mount(r)
    client = SovereignTestClient(r)
    assert client.get("/a/b/c", headers={"accept": "text/html"}).status_code == 200


def test_docker_copies_html5_web_directory():
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "compose.yaml").read_text()
    assert "COPY --chown=sovereign:sovereign web /app/web" in dockerfile
    assert "SOVEREIGN_WEB_DIR" in compose
    assert "sovereign-server:v10.5" in compose
