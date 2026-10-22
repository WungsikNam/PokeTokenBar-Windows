"""Claude 로그인 창 (별도 프로세스로 실행: python -m poketokenbar.login).

Windows 내장 Edge WebView2 로 claude.ai 로그인 페이지를 띄우고, 사용자가 로그인하면
sessionKey 쿠키를 표준 출력(JSON 한 줄)으로 부모 앱에 넘긴 뒤 창을 닫는다.
비공개 모드라 로그인 정보가 이 창의 프로필에 남지 않는다.

--probe: 로그인 없이 페이지를 열어 쿠키 읽기가 동작하는지만 확인 (쿠키 이름만 출력).
"""
from __future__ import annotations

import json
import sys
import threading
import time

import webview

LOGIN_URL = "https://claude.ai/login"


def _cookie_items(win):
    for jar in win.get_cookies() or []:
        for name, morsel in jar.items():
            yield name, morsel.value


def main():
    probe = "--probe" in sys.argv
    win = webview.create_window("Claude 로그인 — PokeTokenBar", LOGIN_URL, width=480, height=760)
    done = threading.Event()

    def emit(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def watch():
        deadline = time.time() + (20 if probe else 15 * 60)
        while not done.is_set() and time.time() < deadline:
            time.sleep(1)
            try:
                items = list(_cookie_items(win))
            except Exception:  # noqa: BLE001 — 페이지 이동 중
                continue
            if probe and items:
                emit({"probe": sorted({n for n, _ in items})})
                break
            key = next((v for n, v in items if n == "sessionKey" and v), None)
            if key:
                emit({"sessionKey": key})
                break
        done.set()
        try:
            win.destroy()
        except Exception:  # noqa: BLE001
            pass

    win.events.closed += lambda: done.set()
    webview.start(watch, private_mode=True)


if __name__ == "__main__":
    main()
