"""claude.ai 세션 키로 Claude 플랜 사용률(5시간/주간)을 실시간 조회한다.

채팅·Claude 데스크톱 앱·Cowork 사용량은 토큰 수가 PC에 남지 않으므로, 서버의 공식 사용률을 받아와
그 증가분을 성장에 반영한다 (원본 macOS PokeTokenBar 의 session key 경로와 같은 엔드포인트).

세션 키는 Windows DPAPI 로 암호화해 이 PC 사용자만 복호화할 수 있게 저장하고, claude.ai 에만 보낸다.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = "https://claude.ai/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")


class LiveError(Exception):
    def __init__(self, msg: str, auth: bool = False):
        super().__init__(msg)
        self.auth = auth


def _get(path: str, key: str):
    req = urllib.request.Request(f"{BASE}/{path}", headers={
        "Cookie": f"sessionKey={key}", "Accept": "application/json", "User-Agent": UA,
        "Origin": "https://claude.ai", "Referer": "https://claude.ai/"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LiveError("세션 키가 만료됐거나 올바르지 않아요", auth=True) from None
        if e.code == 429:
            raise LiveError("요청이 너무 많아요 — 잠시 후 다시 시도해요") from None
        raise LiveError(f"claude.ai 응답 오류 ({e.code})") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LiveError("claude.ai 에 연결할 수 없어요 (인터넷 확인)") from None


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_usage(key: str, org: str | None = None) -> dict:
    if not org:
        orgs = _get("organizations", key)
        if not orgs:
            raise LiveError("이 계정에서 조직을 찾지 못했어요")
        chat = [o for o in orgs if "chat" in (o.get("capabilities") or [])]
        org = (chat or orgs)[0]["uuid"]
    u = _get(f"organizations/{org}/usage", key)
    fh, sd = u.get("five_hour") or {}, u.get("seven_day") or {}
    if fh.get("utilization") is None and sd.get("utilization") is None:
        raise LiveError("사용률 정보가 없어요")
    return {"org": org, "t": time.time(),
            "fh": float(fh.get("utilization") or 0), "fh_reset": _ts(fh.get("resets_at")),
            "sd": float(sd.get("utilization") or 0), "sd_reset": _ts(sd.get("resets_at"))}


# ---------------------------------------------------------------- DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(data: bytes, protect: bool) -> bytes:
    src = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    dst = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):  # UI_FORBIDDEN
        raise OSError("DPAPI 실패")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def protect(text: str) -> str:
    return base64.b64encode(_crypt(text.encode("utf-8"), True)).decode("ascii")


def unprotect(blob: str) -> str | None:
    try:
        return _crypt(base64.b64decode(blob), False).decode("utf-8")
    except (OSError, ValueError):
        return None
