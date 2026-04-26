from __future__ import annotations

import base64, hashlib, hmac, os
from dataclasses import dataclass


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode((data + "=" * (-len(data) % 4)).encode("ascii"))


@dataclass(frozen=True)
class ScryptParams:
    n: int = 2 ** 14
    r: int = 8
    p: int = 1
    dklen: int = 64
    salt_bytes: int = 32
    maxmem: int = 64 * 1024 * 1024


def hash_password(plain: str | bytes, *, params: ScryptParams = ScryptParams()) -> str:
    if isinstance(plain, str):
        plain = plain.encode("utf-8")
    salt = os.urandom(params.salt_bytes)
    digest = hashlib.scrypt(plain, salt=salt, n=params.n, r=params.r, p=params.p,
                            dklen=params.dklen, maxmem=params.maxmem)
    return f"$scrypt$n={params.n},r={params.r},p={params.p},dklen={params.dklen}${_b64e(salt)}${_b64e(digest)}"


def verify_password(plain: str | bytes, hashed: str) -> bool:
    if isinstance(plain, str):
        plain = plain.encode("utf-8")
    try:
        _, scheme, param_text, salt_b64, digest_b64 = hashed.split("$", 4)
        if scheme != "scrypt":
            return False
        params = dict(part.split("=", 1) for part in param_text.split(","))
        n, r, p, dklen = (int(params["n"]), int(params["r"]), int(params["p"]), int(params["dklen"]))
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
        actual = hashlib.scrypt(plain, salt=salt, n=n, r=r, p=p, dklen=dklen,
                                maxmem=max(64 * 1024 * 1024, n * r * p * 256))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def needs_rehash(hashed: str, *, params: ScryptParams = ScryptParams()) -> bool:
    try:
        _, scheme, param_text, _, _ = hashed.split("$", 4)
        if scheme != "scrypt":
            return True
        parsed = dict(part.split("=", 1) for part in param_text.split(","))
        return any(int(parsed[k]) != v for k, v in {"n": params.n, "r": params.r, "p": params.p, "dklen": params.dklen}.items())
    except Exception:
        return True
