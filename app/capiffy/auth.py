"""Capiffy token manager — auto-refresh access token before expiry."""

from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_APP_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(os.getenv("ALPHAABED_DATA_DIR", str(_APP_ROOT / "data")))
TOKENS_FILE = _DATA_DIR / "capiffy_tokens.json"
ENV_FILE = _APP_ROOT / ".env"


def _ssl_context() -> ssl.SSLContext:
    insecure = os.environ.get("CAPIFFY_SSL_VERIFY", "true").lower() in ("0", "false", "no")
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def capiffy_urlopen(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def _load_dotenv() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        return json.loads(_b64url_decode(parts[1]))
    except Exception:
        return {}


def jwt_exp_unix(token: str) -> Optional[int]:
    exp = decode_jwt_payload(token).get("exp")
    return int(exp) if exp else None


@dataclass
class CapiffyTokens:
    access_token: str
    refresh_token: str
    device_cid: str = ""
    account_id: str = ""

    def access_expires_in(self) -> Optional[int]:
        exp = jwt_exp_unix(self.access_token)
        if exp is None:
            return None
        return max(0, exp - int(time.time()))

    def refresh_expires_in(self) -> Optional[int]:
        exp = jwt_exp_unix(self.refresh_token)
        if exp is None:
            return None
        return max(0, exp - int(time.time()))

    def access_needs_refresh(self, skew_sec: int = 120) -> bool:
        left = self.access_expires_in()
        if left is None:
            return True
        return left <= skew_sec

    def refresh_is_dead(self) -> bool:
        left = self.refresh_expires_in()
        return left is not None and left <= 0

    @classmethod
    def from_env(cls) -> CapiffyTokens:
        return cls(
            access_token=os.environ.get("CAPIFFY_ACCESS_TOKEN", "").strip(),
            refresh_token=os.environ.get("CAPIFFY_REFRESH_TOKEN", "").strip(),
            device_cid=os.environ.get("CAPIFFY_DEVICE_CID", "").strip(),
            account_id=os.environ.get("CAPIFFY_ACCOUNT_ID", "").strip(),
        )

    @classmethod
    def load(cls) -> CapiffyTokens:
        _load_dotenv()
        if TOKENS_FILE.is_file():
            try:
                data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
                return cls(
                    access_token=str(data.get("access_token", "")),
                    refresh_token=str(data.get("refresh_token", "")),
                    device_cid=str(data.get("device_cid", "")),
                    account_id=str(data.get("account_id", "")),
                )
            except Exception:
                pass
        return cls.from_env()

    def save(self) -> None:
        TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKENS_FILE.write_text(
            json.dumps(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "device_cid": self.device_cid,
                    "account_id": self.account_id,
                    "saved_at": int(time.time()),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _cookie_value(set_cookies: list[str], name: str) -> str:
    prefix = f"{name}="
    for raw in set_cookies:
        for part in raw.split(","):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :].split(";", 1)[0].strip()
    return ""


def _extract_tokens_from_response(
    body: dict[str, Any],
    set_cookies: list[str],
) -> tuple[str, str]:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    access = (
        body.get("accessToken")
        or body.get("access_token")
        or body.get("token")
        or data.get("accessToken")
        or data.get("access_token")
        or ""
    )
    refresh = (
        body.get("refreshToken")
        or body.get("refresh_token")
        or data.get("refreshToken")
        or data.get("refresh_token")
        or _cookie_value(set_cookies, "refreshToken")
        or ""
    )
    if not access:
        access = _cookie_value(set_cookies, "accessToken")
    return str(access), str(refresh)


def refresh_tokens(tokens: CapiffyTokens) -> CapiffyTokens:
    url = os.environ.get(
        "CAPIFFY_REFRESH_URL", "https://api.capiffy.com/api/auth/refresh"
    ).strip()
    if not tokens.refresh_token:
        raise RuntimeError("No refresh_token — paste CAPIFFY_REFRESH_TOKEN into .env")

    method = os.environ.get("CAPIFFY_REFRESH_METHOD", "POST").upper()
    body_mode = os.environ.get("CAPIFFY_REFRESH_BODY", "empty").lower()

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://capiffy.com",
        "referer": "https://capiffy.com/",
        "Cookie": f"refreshToken={tokens.refresh_token}",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    if tokens.device_cid:
        headers["x-device-cid"] = tokens.device_cid

    data: Optional[bytes] = b"{}"
    if body_mode == "json":
        data = json.dumps({"refreshToken": tokens.refresh_token}).encode("utf-8")
    elif body_mode == "none":
        data = None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with capiffy_urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            set_cookies = []
            if hasattr(resp.headers, "get_all"):
                set_cookies = resp.headers.get_all("Set-Cookie") or []
            elif resp.headers.get("Set-Cookie"):
                set_cookies = [resp.headers.get("Set-Cookie", "")]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Refresh HTTP {exc.code}: {detail}") from exc

    new_access, new_refresh = "", tokens.refresh_token
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                new_access, new_refresh_parsed = _extract_tokens_from_response(parsed, set_cookies)
                if new_refresh_parsed:
                    new_refresh = new_refresh_parsed
        except json.JSONDecodeError:
            pass

    if not new_refresh or new_refresh == tokens.refresh_token:
        from_cookie = _cookie_value(set_cookies, "refreshToken")
        if from_cookie:
            new_refresh = from_cookie

    if not new_access:
        raise RuntimeError(
            f"Refresh succeeded but no access token in response. Body: {raw[:300]}."
        )

    out = CapiffyTokens(
        access_token=new_access,
        refresh_token=new_refresh,
        device_cid=tokens.device_cid,
        account_id=tokens.account_id,
    )
    out.save()
    return out


def get_valid_tokens(force_refresh: bool = False) -> CapiffyTokens:
    tokens = CapiffyTokens.load()
    if not tokens.access_token and not tokens.refresh_token:
        raise RuntimeError(
            "No Capiffy tokens in .env or data/capiffy_tokens.json. "
            "Set CAPIFFY_ACCESS_TOKEN and CAPIFFY_REFRESH_TOKEN in .env."
        )

    if tokens.refresh_is_dead():
        raise RuntimeError("Capiffy refresh token expired — log in again on capiffy.com")

    if force_refresh or tokens.access_needs_refresh():
        tokens = refresh_tokens(tokens)
    return tokens
