"""PokeTokenBar 설치 프로그램 — build_exe.py 가 PokeTokenBar-Setup.exe 로 빌드한다.

앱 exe 를 안에 담고 있다가 %LOCALAPPDATA%\\Programs\\PokeTokenBar 에 설치하고, 시작 메뉴·바탕화면 바로가기와
'설치된 앱' 제거 항목을 만든다. 관리자 권한은 필요 없다.

--silent [--no-launch]: 창 없이 기본 옵션으로 설치
"""
import ctypes
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import ImageTk  # noqa: E402

from poketokenbar import setup_win  # noqa: E402
from poketokenbar.icon import pikachu_face  # noqa: E402

FONT = "Malgun Gothic"


def payload() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "payload" / setup_win.EXE_NAME
    return Path(__file__).resolve().parent / "dist" / setup_win.EXE_NAME


def main():
    if "--silent" in sys.argv:
        setup_win.install(payload(), desktop=True, autostart=True, launch="--no-launch" not in sys.argv)
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    root.title("PokeTokenBar 설치")
    root.configure(bg="#ffffff")
    root.resizable(False, False)
    sf = max(1.0, root.winfo_fpixels("1i") / 96)
    icon = ImageTk.PhotoImage(pikachu_face(64), master=root)
    root.iconphoto(True, icon)
    art = ImageTk.PhotoImage(pikachu_face(int(128 * sf)), master=root)

    frame = tk.Frame(root, bg="#ffffff", padx=int(28 * sf), pady=int(22 * sf))
    frame.pack()
    tk.Label(frame, image=art, bg="#ffffff").pack()
    tk.Label(frame, text="PokeTokenBar", font=(FONT, 18, "bold"), bg="#ffffff").pack(pady=(8, 0))
    tk.Label(frame, text=f"AI 코딩 토큰으로 포켓몬을 키워요 · v{setup_win.VERSION}", font=(FONT, 10),
             fg="#6e7781", bg="#ffffff").pack()
    tk.Label(frame, text=f"설치 위치: {setup_win.install_dir()}", font=(FONT, 8), fg="#868e96",
             bg="#ffffff", wraplength=int(340 * sf)).pack(pady=(10, 6))

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCheckbutton", background="#ffffff", font=(FONT, 10))
    style.configure("Go.TButton", font=(FONT, 11, "bold"), foreground="#ffffff", background="#e03131",
                    padding=(24, 8))
    style.map("Go.TButton", background=[("active", "#c92a2a"), ("disabled", "#adb5bd")])
    v_desk = tk.BooleanVar(value=True)
    v_auto = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="바탕화면에 바로가기 만들기", variable=v_desk).pack(anchor="w")
    ttk.Checkbutton(frame, text="Windows를 켤 때 자동으로 실행", variable=v_auto).pack(anchor="w")
    status = tk.Label(frame, text="", font=(FONT, 9), fg="#2f9e44", bg="#ffffff")
    status.pack(pady=(10, 0))
    btn = ttk.Button(frame, text="설치하기", style="Go.TButton")
    btn.pack(pady=(8, 0))

    def run():
        btn.state(["disabled"])
        status.configure(text="설치하는 중…", fg="#1971c2")

        def work():
            try:
                setup_win.install(payload(), desktop=v_desk.get(), autostart=v_auto.get(), launch=True)
                root.after(0, done, None)
            except Exception as e:  # noqa: BLE001
                root.after(0, done, e)
        threading.Thread(target=work, daemon=True).start()

    def done(err):
        if err:
            status.configure(text=f"설치하지 못했어요: {err}", fg="#e03131")
            btn.state(["!disabled"])
            return
        status.configure(text="설치 완료! 작업 표시줄 오른쪽에서 알을 찾아보세요", fg="#2f9e44")
        btn.configure(text="닫기", command=root.destroy)
        btn.state(["!disabled"])

    btn.configure(command=run)
    root.mainloop()


if __name__ == "__main__":
    main()
