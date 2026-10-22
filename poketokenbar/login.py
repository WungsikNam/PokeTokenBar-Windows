"""Claude 로그인 창 (별도 프로세스로 실행: python -m poketokenbar.login).

Windows 내장 Edge WebView2 로 claude.ai 로그인 페이지를 띄우고, 사용자가 로그인하면
sessionKey 쿠키를 (--out 파일 또는 표준 출력으로) 부모 앱에 넘긴 뒤 창을 닫는다.
비공개 모드라 로그인 정보가 이 창의 프로필에 남지 않는다.

진단용으로 %APPDATA%\\PokeTokenBarWin\\login.log 에 페이지 주소(쿼리 제외)와 쿠키 '이름'만 남긴다 (값은 남기지 않음).

--probe: 로그인 없이 페이지를 열어 쿠키 읽기가 동작하는지만 확인 (쿠키 이름만 출력).
--out <파일>: 결과를 표준 출력 대신 이 파일에 쓴다 (exe 로 묶으면 창 모드라 stdout 이 없다).
  세션 키는 DPAPI 로 암호화한 값만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import webview

try:
    # pywebview 는 팝업(window.open, "Google 로 계속하기" 등)을 기본 브라우저로 넘긴다 → 로그인이 Chrome 에서
    # 끝나 이 창은 끝내 로그인되지 않는다. 처리하지 않고 두면 WebView2 가 같은 세션의 자체 팝업 창으로 연다.
    from webview.platforms import edgechromium

    edgechromium.EdgeChrome.on_new_window_request = lambda self, sender, args: None
except Exception:  # noqa: BLE001 — 다른 백엔드/버전이면 기본 동작 유지
    pass

LOGIN_URL = "https://claude.ai/login"
LOG = Path(os.environ.get("APPDATA") or Path.home()) / "PokeTokenBarWin" / "login.log"
TITLE = "Claude 로그인 — 이메일 로그인은 메일의 '인증 코드'를 이 창에 입력하세요 (링크 클릭 X)"


def log(msg: str):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def _cookie_items(win):
    for jar in win.get_cookies() or []:
        for name, morsel in jar.items():
            yield name, morsel.value


def _is_session_cookie(name: str) -> bool:
    return name == "sessionKey" or name.startswith("sessionKey")


def main():
    probe = "--probe" in sys.argv
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    win = webview.create_window(TITLE, LOGIN_URL, width=520, height=780)
    done = threading.Event()
    log("login window opened")

    def emit(obj):
        if out:
            if "sessionKey" in obj:
                from .claude_live import protect
                obj = {"sessionKeyEnc": protect(obj["sessionKey"])}
            tmp = out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f)
            os.replace(tmp, out)
        elif sys.stdout:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    def watch():
        deadline = time.time() + (20 if probe else 30 * 60)
        last_state = None
        while not done.is_set() and time.time() < deadline:
            time.sleep(1)
            try:
                url = win.get_current_url() or ""
                items = list(_cookie_items(win))
            except Exception as e:  # noqa: BLE001 — 페이지 이동 중
                state = f"cookie read failed: {type(e).__name__}"
                if state != last_state:
                    log(state)
                    last_state = state
                continue
            names = sorted({n for n, _ in items})
            u = urlsplit(url)
            state = f"page={u.netloc}{u.path} cookies={names}"
            if state != last_state:  # 바뀔 때만 기록
                log(state)
                last_state = state
            if probe and items:
                emit({"probe": names})
                break
            key = next((v for n, v in items if _is_session_cookie(n) and v), None)
            if key:
                log("session cookie found → 앱에 전달")
                emit({"sessionKey": key})
                break
        done.set()
        try:
            win.destroy()
        except Exception:  # noqa: BLE001
            pass

    win.events.closed += lambda: (log("login window closed"), done.set())
    webview.start(watch, private_mode=True)


if __name__ == "__main__":
    main()
