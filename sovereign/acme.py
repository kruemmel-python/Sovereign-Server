from __future__ import annotations

import base64, json, os, subprocess, tempfile, threading, time, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .responses import Response
from .router import Router


LETS_ENCRYPT_PRODUCTION = "https://acme-v02.api.letsencrypt.org/directory"
LETS_ENCRYPT_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@dataclass
class HTTP01Challenge:
    token: str
    key_authorization: str


class HTTP01ChallengeStore:
    def __init__(self) -> None:
        self._items: dict[str, str] = {}
        self._lock = threading.RLock()

    def put(self, token: str, key_authorization: str) -> None:
        with self._lock:
            self._items[token] = key_authorization

    def remove(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)

    def get(self, token: str) -> str | None:
        with self._lock:
            return self._items.get(token)


class ACMERouteInstaller:
    def __init__(self, router: Router, store: HTTP01ChallengeStore | None = None) -> None:
        self.router = router
        self.store = store or HTTP01ChallengeStore()
        self.installed = False

    def install(self) -> None:
        if self.installed:
            return
        store = self.store

        @self.router.route("/.well-known/acme-challenge/{token}", methods=("GET",))
        def acme_challenge(req):
            value = store.get(req.route_params["token"])
            if value is None:
                return Response("not found", status=404, content_type="text/plain; charset=utf-8")
            return Response(value, content_type="text/plain; charset=utf-8")

        self.installed = True


class OpenSSL:
    @staticmethod
    def generate_account_key(path: str | Path, bits: int = 4096) -> None:
        subprocess.run(["openssl", "genrsa", "-out", str(path), str(bits)], check=True)

    @staticmethod
    def generate_private_key(path: str | Path, bits: int = 2048) -> None:
        subprocess.run(["openssl", "genrsa", "-out", str(path), str(bits)], check=True)

    @staticmethod
    def create_csr(key_path: str | Path, csr_path: str | Path, domains: list[str]) -> None:
        san = ",".join(f"DNS:{d}" for d in domains)
        subj = f"/CN={domains[0]}"
        with tempfile.NamedTemporaryFile("w", delete=False) as cfg:
            cfg.write("[req]\ndistinguished_name=req\n[ext]\nsubjectAltName=" + san + "\n")
            cfg_name = cfg.name
        try:
            subprocess.run([
                "openssl", "req", "-new", "-sha256", "-key", str(key_path), "-subj", subj,
                "-reqexts", "ext", "-config", cfg_name, "-out", str(csr_path)
            ], check=True)
        finally:
            try:
                os.unlink(cfg_name)
            except OSError:
                pass


class ACMEClient:
    """Minimal ACMEv2 scaffold using urllib and system OpenSSL.

    It intentionally exposes the low-level ACME operations instead of hiding
    protocol errors. That makes it usable for production hardening while still
    keeping Sovereign dependency-free.
    """

    def __init__(self, directory_url: str = LETS_ENCRYPT_STAGING) -> None:
        self.directory_url = directory_url
        self.directory: dict[str, Any] | None = None

    def fetch_directory(self) -> dict[str, Any]:
        with urllib.request.urlopen(self.directory_url, timeout=10) as resp:
            self.directory = json.loads(resp.read().decode("utf-8"))
        return self.directory

    def ready(self) -> bool:
        return bool(self.directory or self.fetch_directory())


class CertificateManager:
    """Operational helper for ACME HTTP-01 route wiring and cert storage.

    Full issuance depends on live CA access and a reachable public domain. The
    manager therefore provides deterministic local pieces (challenge serving,
    key/CSR generation, renewal scheduling hooks) and keeps network ACME calls
    explicit through ACMEClient.
    """

    def __init__(self, router: Router, *, domains: list[str], cert_dir: str | Path = "certs",
                 directory_url: str = LETS_ENCRYPT_STAGING) -> None:
        if not domains:
            raise ValueError("at least one domain is required")
        self.router = router
        self.domains = domains
        self.cert_dir = Path(cert_dir)
        self.cert_dir.mkdir(parents=True, exist_ok=True)
        self.store = HTTP01ChallengeStore()
        self.routes = ACMERouteInstaller(router, self.store)
        self.client = ACMEClient(directory_url)
        self.account_key = self.cert_dir / "account.key"
        self.private_key = self.cert_dir / f"{domains[0]}.key"
        self.csr = self.cert_dir / f"{domains[0]}.csr"
        self.cert = self.cert_dir / f"{domains[0]}.crt"

    def install_http01_route(self) -> None:
        self.routes.install()

    def prepare_keys(self) -> None:
        if not self.account_key.exists():
            OpenSSL.generate_account_key(self.account_key)
        if not self.private_key.exists():
            OpenSSL.generate_private_key(self.private_key)
        OpenSSL.create_csr(self.private_key, self.csr, self.domains)

    def add_challenge(self, token: str, key_authorization: str) -> None:
        self.store.put(token, key_authorization)

    def remove_challenge(self, token: str) -> None:
        self.store.remove(token)

    def should_renew(self, min_remaining_days: int = 30) -> bool:
        if not self.cert.exists():
            return True
        # Dependency-free, conservative fallback. Real deployments may replace
        # this with openssl x509 -checkend via subprocess.
        age = time.time() - self.cert.stat().st_mtime
        return age > max(1, 90 - min_remaining_days) * 86400

    def configure_router(self) -> "CertificateManager":
        self.install_http01_route()
        return self
