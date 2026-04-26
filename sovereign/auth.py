from __future__ import annotations
import base64, hashlib, hmac, json, secrets, time
from typing import Callable, Mapping, Optional
from .errors import HTTPError
from .request import Request

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))

class JWTAuth:
    def __init__(self, secrets: str | Mapping[str, str], current_kid: Optional[str] = None,
                 issuer: Optional[str] = None, audience: Optional[str] = None,
                 expected_alg: str = "HS256", max_token_len: int = 8192,
                 blocklist: object | None = None) -> None:
        if isinstance(secrets, str):
            self.secrets = {"default": secrets}
            self.current_kid = current_kid or "default"
        else:
            if not secrets:
                raise ValueError("at least one JWT secret is required")
            self.secrets = dict(secrets)
            self.current_kid = current_kid or next(iter(self.secrets))
        self.issuer = issuer
        self.audience = audience
        self.expected_alg = expected_alg
        self.max_token_len = max_token_len
        self.blocklist = blocklist

    def create_token(self, payload: dict, exp_seconds: int = 3600, kid: Optional[str] = None) -> str:
        kid = kid or self.current_kid
        if kid not in self.secrets:
            raise ValueError("unknown kid")
        now = int(time.time())
        body = dict(payload)
        body.setdefault("iat", now)
        body.setdefault("jti", secrets.token_urlsafe(18))
        body["exp"] = now + exp_seconds
        if self.issuer:
            body.setdefault("iss", self.issuer)
        if self.audience:
            body.setdefault("aud", self.audience)
        header = {"alg": self.expected_alg, "typ": "JWT", "kid": kid}
        h = _b64e(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
        b = _b64e(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
        sig = hmac.new(self.secrets[kid].encode(), f"{h}.{b}".encode("ascii"), hashlib.sha256).digest()
        return f"{h}.{b}.{_b64e(sig)}"

    def verify_token(self, token: str) -> dict:
        if len(token) > self.max_token_len or token.count(".") != 2:
            raise HTTPError(401, "Invalid token structure")
        h, b, s = token.split(".")
        try:
            header = json.loads(_b64d(h).decode("utf-8"))
        except Exception as exc:
            raise HTTPError(401, "Invalid token header") from exc
        if header.get("alg") != self.expected_alg or header.get("typ") != "JWT":
            raise HTTPError(401, "Invalid token algorithm")
        kid = header.get("kid", self.current_kid)
        secret = self.secrets.get(kid)
        if not secret:
            raise HTTPError(401, "Unknown token key")
        expected = _b64e(hmac.new(secret.encode(), f"{h}.{b}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expected):
            raise HTTPError(401, "Invalid token signature")
        try:
            payload = json.loads(_b64d(b).decode("utf-8"))
        except Exception as exc:
            raise HTTPError(401, "Invalid token payload") from exc
        now = int(time.time())
        if int(payload.get("exp", 0)) < now:
            raise HTTPError(401, "Token expired")
        if self.issuer and payload.get("iss") != self.issuer:
            raise HTTPError(401, "Invalid issuer")
        if self.audience and payload.get("aud") != self.audience:
            raise HTTPError(401, "Invalid audience")
        jti = payload.get("jti")
        if self.blocklist is not None and jti and getattr(self.blocklist, "is_revoked")(str(jti)):
            raise HTTPError(401, "Token revoked")
        return payload

    def revoke_token(self, token: str, reason: str = "") -> None:
        if self.blocklist is None:
            raise RuntimeError("JWTAuth has no blocklist configured")
        payload = self.verify_token(token)
        jti = payload.get("jti")
        if not jti:
            raise HTTPError(400, "Token has no jti")
        getattr(self.blocklist, "revoke")(str(jti), int(payload.get("exp", 0)), reason)

def require_auth(jwt: JWTAuth):
    def mw(req: Request, call_next: Callable[[Request], object]) -> object:
        auth = req.header("authorization")
        if not auth.startswith("Bearer "):
            raise HTTPError(401, "Missing bearer token")
        req.user = jwt.verify_token(auth[7:].strip())
        return call_next(req)
    return mw
