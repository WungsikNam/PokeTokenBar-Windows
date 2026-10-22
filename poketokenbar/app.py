"""PokeTokenBar for Windows — 트레이 아이콘 + 메인 창 + 데스크톱 펫."""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageTk

from .companion import (COMMON_GRAD_TOKENS, DEX_MAX, GENERATIONS, ITEM_SPRITES, RARITY_MULT, MEGA_SPECIES, PIKACHU_BASE, RARITY_COLOR, RARITY_KO, SHOP_ITEMS, Companion,
                        dex_no, display_name, enrich_line, exp_at, find_node, roll_hatch, tree_depth)
from .pokedata import PokeData, egg_image, load_frames
from .usage import UsageScanner, fmt_tokens
from . import weather as wx

APP_NAME = "PokeTokenBarWin"
APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
FONT = "Malgun Gothic"
C = {"bg": "#f4f5f7", "card": "#ffffff", "text": "#1f2328", "sub": "#6e7781", "line": "#e3e5e8",
     "accent": "#e03131", "bar": "#4dabf7", "bar_today": "#e03131", "track": "#e9ecef", "egg": "#f59f00"}
CALIBRATE_DAYS = 7  # 사용량 맞추기: 일반 포켓몬이 이만큼(사용한 날 기준)에 졸업
PRESETS = [("원본 (100%)", 1.0), ("보통 (25%)", 0.25), ("쉬움 (10%)", 0.1), ("아주 쉬움 (2%)", 0.02),
           ("초고속 (0.5%)", 0.005)]


# ---------------------------------------------------------------- helpers
SF = 1.0  # DPI 배율 (App 초기화 때 설정)


def W(n: float) -> int:
    """96dpi 기준 픽셀 값을 현재 화면 배율로 환산."""
    return int(round(n * SF))


def josa(word: str, pair: str) -> str:
    """한국어 조사: pair = '이/가', '을/를', '으로/로', '은/는'."""
    a, b = pair.split("/")
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        if pair == "으로/로":
            return word + (b if jong in (0, 8) else a)
        return word + (a if jong else b)
    return word + a if pair != "으로/로" else word + b


def log_error(msg: str):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(APP_DIR / "error.log", "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def window_label(minutes: int | None) -> str:
    return {300: "5시간", 10080: "주간", 43200: "30일"}.get(minutes or 0, f"{(minutes or 0) // 60}시간")


class Anim:
    """Label 에 PhotoImage 프레임을 순환 표시."""

    def __init__(self, label: tk.Label):
        self.label, self.frames, self.durs, self.i, self.job = label, [], [], 0, None

    def set(self, photos, durs):
        if self.job:
            self.label.after_cancel(self.job)
            self.job = None
        self.frames, self.durs, self.i = photos, durs, 0
        self._tick()

    def _tick(self):
        if not self.frames:
            return
        try:
            self.label.configure(image=self.frames[self.i])
        except tk.TclError:
            return
        if len(self.frames) > 1:
            d = self.durs[self.i]
            self.i = (self.i + 1) % len(self.frames)
            self.job = self.label.after(d, self._tick)


class Scrollable(tk.Frame):
    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()


def bar(canvas: tk.Canvas, frac: float, color: str):
    canvas.delete("all")
    canvas.update_idletasks()
    w = canvas.winfo_width() if canvas.winfo_width() > 1 else int(canvas["width"])
    h = int(canvas["height"])
    canvas.create_rectangle(0, 0, w, h, fill=C["track"], outline="")
    canvas.create_rectangle(0, 0, max(0, min(1, frac)) * w, h, fill=color, outline="")


def card(parent, **kw) -> tk.Frame:
    f = tk.Frame(parent, bg=C["card"], highlightbackground=C["line"], highlightthickness=1, padx=14, pady=12)
    f.pack(fill="x", padx=12, pady=(0, 10), **kw)
    return f


def lbl(parent, text="", size=10, bold=False, color=None, bg=None, **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                    fg=color or C["text"], bg=bg or parent["bg"], **kw)


# ---------------------------------------------------------------- tray
class Tray:
    def __init__(self, app: "App"):
        self.app = app
        a = app
        menu = pystray.Menu(
            pystray.MenuItem("열기", lambda: a.post(a.show_main), default=True),
            pystray.MenuItem("작업 표시줄 위젯",
                             lambda: a.post(a.set_taskbar, not a.comp.settings.get("taskbar_visible", True)),
                             checked=lambda item: a.comp.settings.get("taskbar_visible", True)),
            pystray.MenuItem("데스크톱 펫", lambda: a.post(a.toggle_pet),
                             checked=lambda item: a.comp.settings["pet_visible"]),
            pystray.MenuItem("지금 새로고침", lambda: a.refresh_now()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", lambda: a.post(a.quit)),
        )
        self.icon = pystray.Icon(APP_NAME, egg_image(64, pikachu=app.pikachu_mode), app.app_title(), menu)
        self.icon.run_detached()

    def update(self, image: Image.Image, title: str):
        try:
            self.icon.icon = image
            self.icon.title = title[:127]
        except Exception as e:  # noqa: BLE001
            log_error(f"tray update: {e}")

    def notify(self, title: str, msg: str):
        try:
            self.icon.notify(msg, title)
        except Exception as e:  # noqa: BLE001
            log_error(f"notify: {e}")

    def stop(self):
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- desktop pet
class PetWindow:
    KEY = "#fe01fe"
    KEY_RGB = (0xFE, 0x01, 0xFE)

    def __init__(self, app: "App"):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("PokeTokenBar Pet")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self.KEY)
        self.win.configure(bg=self.KEY)
        self.label = tk.Label(self.win, bg=self.KEY, bd=0, highlightthickness=0, cursor="hand2")
        self.label.pack()
        self.anim = Anim(self.label)
        self.key = None
        self.tip = None
        self.tip_job = None
        self.bubble = None
        self._drag = None
        self.label.bind("<ButtonPress-1>", self._press)
        self.label.bind("<B1-Motion>", self._motion)
        self.label.bind("<ButtonRelease-1>", self._release)
        self.label.bind("<Button-3>", self._menu)
        self.label.bind("<Enter>", self._enter)
        self.label.bind("<Leave>", self._leave)
        # 마우스를 올리면 스프라이트 오른쪽 위에 ✕ 버튼 — 누르면 펫을 숨긴다
        self.close_btn = tk.Label(self.win, text="✕", font=(FONT, 8, "bold"), bg="#e03131", fg="#ffffff",
                                  padx=W(4), pady=0, cursor="hand2")
        self.close_btn.bind("<Button-1>", lambda e: self._close())
        self.close_btn.bind("<Enter>", lambda e: self._cancel_hide_close())
        self.close_btn.bind("<Leave>", lambda e: self._schedule_hide_close())
        self.close_job = None
        self.sprite_box = None
        self.place()
        if not app.comp.settings["pet_visible"]:
            self.win.withdraw()

    def place(self):
        st = self.app.comp.settings
        size = st["pet_size"]
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = st["pet_x"] if st["pet_x"] is not None else sw - size - 60
        y = st["pet_y"] if st["pet_y"] is not None else sh - size - 90
        x = max(0, min(sw - 40, x))
        y = max(0, min(sh - 40, y))
        self.win.geometry(f"{size}x{size}+{x}+{y}")

    def set_sprite(self, key, frames, durs):
        if key == self.key:
            return
        self.key = key
        photos = []
        for f in frames:
            bg = Image.new("RGBA", f.size, self.KEY_RGB + (255,))
            # 반투명 픽셀이 있으면 키 색과 섞여 테두리가 생기므로 알파를 이진화
            a = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
            bg.paste(f.convert("RGB"), (0, 0), a)
            photos.append(ImageTk.PhotoImage(bg.convert("RGB"), master=self.win))
        self.sprite_box = frames[0].getbbox() if frames else None
        self.anim.set(photos, durs)

    def show(self, visible: bool):
        if visible:
            self.win.deiconify()
            self.win.attributes("-topmost", True)
        else:
            self.win.withdraw()
            self._hide_tip()
            self._hide_close()

    # --- ✕ 버튼
    def _show_close(self):
        self._cancel_hide_close()
        size = self.app.comp.settings["pet_size"]
        l, t, r, b = self.sprite_box or (0, 0, size, size)
        self.close_btn.place(x=min(size, r + W(2)), y=max(0, t - W(2)), anchor="ne")
        self.close_btn.lift()

    def _schedule_hide_close(self):
        self._cancel_hide_close()
        self.close_job = self.win.after(700, self._hide_close)

    def _cancel_hide_close(self):
        if self.close_job:
            self.win.after_cancel(self.close_job)
            self.close_job = None

    def _hide_close(self):
        self._cancel_hide_close()
        self.close_btn.place_forget()

    def _close(self):
        self._hide_close()
        if self.app.comp.settings["pet_visible"]:
            self.app.toggle_pet()
        self.app.tray.notify("데스크톱 펫을 숨겼어요",
                             "트레이 아이콘 메뉴나 설정 → 데스크톱 펫에서 다시 켤 수 있어요.")

    # --- 드래그 / 클릭
    def _press(self, e):
        self._drag = (e.x_root, e.y_root, self.win.winfo_x(), self.win.winfo_y(), False)
        self._hide_tip()

    def _motion(self, e):
        if not self._drag:
            return
        sx, sy, wx, wy, moved = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if moved or abs(dx) + abs(dy) > 4:
            self._drag = (sx, sy, wx, wy, True)
            self.win.geometry(f"+{wx + dx}+{wy + dy}")
            if self.bubble:
                self._place_bubble()

    def _release(self, e):
        if self._drag and self._drag[4]:
            st = self.app.comp.settings
            st["pet_x"], st["pet_y"] = self.win.winfo_x(), self.win.winfo_y()
            self.app.comp.save()
        else:
            self.app.show_main()
        self._drag = None

    def _menu(self, e):
        m = tk.Menu(self.win, tearoff=0, font=(FONT, 9))
        m.add_command(label="열기", command=self.app.show_main)
        m.add_command(label="지금 새로고침", command=self.app.refresh_now)
        sm = tk.Menu(m, tearoff=0, font=(FONT, 9))
        for s in (64, 96, 128, 192, 256, 384):
            sm.add_command(label=f"{s}px", command=lambda s=s: self.app.set_pet_size(s))
        m.add_cascade(label="크기", menu=sm)
        m.add_command(label="위치 초기화", command=self._reset_pos)
        m.add_separator()
        m.add_command(label="펫 숨기기", command=self.app.toggle_pet)
        m.add_command(label="종료", command=self.app.quit)
        m.tk_popup(e.x_root, e.y_root)

    def _reset_pos(self):
        st = self.app.comp.settings
        st["pet_x"] = st["pet_y"] = None
        self.app.comp.save()
        self.place()

    # --- 호버 툴팁
    def _enter(self, e):
        self._show_close()
        if self.tip_job:
            self.win.after_cancel(self.tip_job)
        self.tip_job = self.win.after(350, self._show_tip)

    def _leave(self, e):
        self._hide_tip()
        self._schedule_hide_close()

    def _show_tip(self):
        self._hide_tip()
        text = self.app.status_text()
        self.tip = tk.Toplevel(self.win)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(self.tip, text=text, justify="left", font=(FONT, 9), bg="#222831", fg="#ffffff",
                 padx=10, pady=6).pack()
        self.tip.update_idletasks()
        w, h = self.tip.winfo_width(), self.tip.winfo_height()
        x = self.win.winfo_x() + self.win.winfo_width() // 2 - w // 2
        y = self.win.winfo_y() - h - 6
        if y < 0:
            y = self.win.winfo_y() + self.win.winfo_height() + 6
        self.tip.geometry(f"+{max(0, min(self.win.winfo_screenwidth() - w, x))}+{y}")

    def _hide_tip(self):
        if self.tip_job:
            self.win.after_cancel(self.tip_job)
            self.tip_job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None

    # --- 말풍선 (이벤트 알림)
    def say(self, text: str, ms=7000):
        if not self.app.comp.settings["pet_visible"]:
            return
        if self.bubble:
            self.bubble.destroy()
        self.bubble = tk.Toplevel(self.win)
        self.bubble.overrideredirect(True)
        self.bubble.attributes("-topmost", True)
        tk.Label(self.bubble, text=text, font=(FONT, 10, "bold"), bg="#fff9db", fg=C["text"],
                 padx=12, pady=8, wraplength=W(260), justify="left",
                 highlightbackground="#f08c00", highlightthickness=2).pack()
        self._place_bubble()
        b = self.bubble

        def close():
            if b.winfo_exists():
                b.destroy()
            if self.bubble is b:
                self.bubble = None
        self.win.after(ms, close)

    def _place_bubble(self):
        b = self.bubble
        b.update_idletasks()
        w, h = b.winfo_width(), b.winfo_height()
        sw = self.win.winfo_screenwidth()
        x = self.win.winfo_x() + self.win.winfo_width() // 2 - w // 2
        y = self.win.winfo_y() - h - 4
        if y < 0:
            y = self.win.winfo_y() + self.win.winfo_height() + 4
        b.geometry(f"+{max(0, min(sw - w, x))}+{y}")


# ---------------------------------------------------------------- taskbar widget
def _taskbar_light() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def _weather_widget_near_tray() -> bool:
    """Win11 작업 표시줄이 왼쪽 정렬이고 위젯(날씨)이 켜져 있으면 날씨가 트레이 바로 왼쪽에 붙는다."""
    import winreg
    vals = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced") as k:
            for name in ("TaskbarAl", "TaskbarDa"):
                try:
                    vals[name] = winreg.QueryValueEx(k, name)[0]
                except OSError:
                    pass
    except OSError:
        return False
    return vals.get("TaskbarAl", 1) == 0 and vals.get("TaskbarDa", 1) != 0


def _force_foreground(hwnd: int):
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    fg = u.GetForegroundWindow()
    fg_tid = u.GetWindowThreadProcessId(ctypes.c_void_p(fg), None) if fg else 0
    my_tid = k.GetCurrentThreadId()
    attached = bool(fg_tid and fg_tid != my_tid and u.AttachThreadInput(fg_tid, my_tid, True))
    try:
        u.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        u.BringWindowToTop(ctypes.c_void_p(hwnd))
        u.SetForegroundWindow(ctypes.c_void_p(hwnd))
    finally:
        if attached:
            u.AttachThreadInput(fg_tid, my_tid, False)


def _main_is_foreground(app) -> bool:
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    try:
        return app.root.state() == "normal" and u.GetForegroundWindow() == int(app.root.wm_frame(), 16)
    except Exception:  # noqa: BLE001
        return False


def _win_rect(hwnd):
    import ctypes.wintypes as wt
    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


class TaskbarWidget:
    """작업 표시줄 위(트레이 바로 왼쪽)에 얹는 미니 위젯 — macOS 메뉴바의 '스프라이트 + 오늘 토큰' 표시.

    Windows 트레이 아이콘엔 글자를 붙일 수 없어서, 항상-위 창을 작업 표시줄 위에 겹쳐 띄운다.
    투명 키 색을 쓰면 글자 사이 빈 곳의 클릭이 뒤로 빠지므로, 대신 작업 표시줄 색을 화면에서 샘플링해
    불투명 배경으로 칠한다 (주기적으로 다시 샘플링해 테마/배경 변화에 맞춘다).
    """

    def __init__(self, app: "App"):
        self.app = app
        light = _taskbar_light()
        self.KEY_RGB = (0xEE, 0xEE, 0xEE) if light else (0x1F, 0x1F, 0x1F)
        self.KEY = "#%02x%02x%02x" % self.KEY_RGB
        fg = "#1b1b1b" if light else "#ffffff"
        self.win = tk.Toplevel(app.root)
        self.win.title("PokeTokenBar Taskbar")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.KEY)
        self._frames, self._durs = [], []
        self._ticks = 0
        self.sprite = tk.Label(self.win, bg=self.KEY, bd=0, highlightthickness=0, cursor="hand2")
        self.sprite.pack(side="left")
        self.text = tk.Label(self.win, bg=self.KEY, fg=fg, font=(FONT, 10, "bold"), bd=0, justify="left",
                             cursor="hand2")
        self.text.pack(side="left", padx=(W(2), W(4)))
        self.anim = Anim(self.sprite)
        self.key = None
        self.tip = None
        self.hwnd = None
        self.visible = app.comp.settings.get("taskbar_visible", True)
        self._drag = None
        for w in (self.win, self.sprite, self.text):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>", self._motion)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Button-3>", self._menu)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", lambda e: self._hide_tip())
        if not self.visible:
            self.win.withdraw()
        self.win.after(300, self._tick)

    def offset(self) -> int:
        """트레이 왼쪽 끝에서 위젯 오른쪽 끝까지의 간격(px). 드래그로 바꿀 수 있다."""
        off = self.app.comp.settings.get("taskbar_offset")
        if off is None:
            off = W(6) + (W(72) if _weather_widget_near_tray() else 0)
        return int(off)

    # --- 드래그로 좌우 위치 조정 / 클릭으로 창 열기
    def _press(self, e):
        self._hide_tip()
        self._drag = (e.x_root, self.offset(), False)
        self.app._fg_before_click = getattr(self, "_main_fg_snapshot", False)

    def _motion(self, e):
        if not self._drag:
            return
        sx, off0, moved = self._drag
        dx = e.x_root - sx
        if moved or abs(dx) > 4:
            self._drag = (sx, off0, True)
            self.app.comp.settings["taskbar_offset"] = max(0, off0 - dx)
            self._reposition()

    def _release(self, e):
        if self._drag and self._drag[2]:
            self.app.comp.save()
        else:
            self.app.toggle_main()
        self._drag = None

    @staticmethod
    def _tray_hwnd():
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        return u.FindWindowW("Shell_TrayWnd", None)

    def _taskbar(self):
        t = self._tray_hwnd()
        return _win_rect(t) if t else None

    def sprite_size(self) -> int:
        tb = self._taskbar()
        th = (tb[3] - tb[1]) if tb else W(48)
        return max(W(24), int(th * 0.9))

    def _anchor_x(self, tb):
        u = ctypes.windll.user32
        u.FindWindowExW.restype = ctypes.c_void_p
        n = u.FindWindowExW(ctypes.c_void_p(self._tray_hwnd()), None, "TrayNotifyWnd", None)
        if n:
            return _win_rect(n)[0]
        return tb[2] - W(300)

    def _fullscreen_app(self) -> bool:
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = ctypes.c_void_p
        fg = u.GetForegroundWindow()
        if not fg:
            return False
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(ctypes.c_void_p(fg), cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        l, t, r, b = _win_rect(fg)
        return l <= 0 and t <= 0 and r >= u.GetSystemMetrics(0) and b >= u.GetSystemMetrics(1)

    def _tick(self):
        # 클릭 순간엔 위젯이 포그라운드를 가져가므로, 클릭 직전 상태를 틱마다 기억해 둔다
        self._main_fg_snapshot = _main_is_foreground(self.app)
        self._ticks += 1
        try:
            self._reposition()
            if self._ticks % 10 == 1:
                self._sample_bg()
        except Exception:  # noqa: BLE001
            log_error(traceback.format_exc())
        if self.app.running:
            self.win.after(800, self._tick)

    def _reposition(self):
        if not self.visible:
            return
        tb = self._taskbar()
        horizontal = tb and (tb[2] - tb[0]) > (tb[3] - tb[1])
        if not tb or not horizontal or self._fullscreen_app():
            if self.win.state() != "withdrawn":
                self.win.withdraw()
                self._hide_tip()
            return
        if self.win.state() == "withdrawn":
            self.win.deiconify()
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = max(tb[0], self._anchor_x(tb) - w - self.offset())
        y = tb[1] + (tb[3] - tb[1] - h) // 2
        if (self.win.winfo_x(), self.win.winfo_y()) != (x, y):
            self.win.geometry(f"+{x}+{y}")
        # 작업 표시줄을 클릭하면 그쪽이 위로 올라오므로 주기적으로 다시 맨 위로 (포커스는 뺏지 않음)
        if self.hwnd is None:
            self.hwnd = int(self.win.wm_frame(), 16)
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(self.hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                          0x0001 | 0x0002 | 0x0010)

    def _sample_bg(self):
        """위젯 바로 왼쪽 작업 표시줄 띠에서 가장 흔한 색을 배경색으로 쓴다."""
        if not self.visible or self.win.state() == "withdrawn":
            return
        from PIL import ImageGrab
        tb = self._taskbar()
        if not tb:
            return
        x = self.win.winfo_x()
        img = ImageGrab.grab(bbox=(max(tb[0], x - W(10)), tb[1] + W(4), max(tb[0] + 1, x - W(2)), tb[3] - W(4)))
        colors = img.convert("RGB").getcolors(4096)
        if not colors:
            return
        rgb = max(colors)[1]
        if max(abs(a - b) for a, b in zip(rgb, self.KEY_RGB)) <= 2:
            return
        self.KEY_RGB = rgb
        self.KEY = "#%02x%02x%02x" % rgb
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        for w in (self.win, self.sprite, self.text):
            w.configure(bg=self.KEY)
        self.text.configure(fg="#1b1b1b" if lum > 128 else "#ffffff")
        key, self.key = self.key, None
        if self._frames:
            self.update(key, self._frames, self._durs, self.text["text"])

    def update(self, key, frames, durs, text):
        if key != self.key:
            self.key = key
            self._frames, self._durs = frames, durs
            photos = []
            for f in frames:
                bg = Image.new("RGBA", f.size, self.KEY_RGB + (255,))
                a = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
                bg.paste(f.convert("RGB"), (0, 0), a)
                photos.append(ImageTk.PhotoImage(bg.convert("RGB"), master=self.win))
            self.anim.set(photos, durs)
        if self.text["text"] != text:
            self.text.configure(text=text)

    def show(self, visible: bool):
        self.visible = visible
        if visible:
            self.win.deiconify()
            self._reposition()
        else:
            self.win.withdraw()
            self._hide_tip()

    def _menu(self, e):
        self._hide_tip()
        m = tk.Menu(self.win, tearoff=0, font=(FONT, 9))
        m.add_command(label="열기", command=self.app.show_main)
        m.add_command(label="지금 새로고침", command=self.app.refresh_now)
        cost = tk.BooleanVar(master=self.win, value=self.app.comp.settings.get("taskbar_cost", False))
        m.add_checkbutton(label="오늘 비용($)도 표시", variable=cost,
                          command=lambda: self.app.set_setting("taskbar_cost", cost.get()))
        m.add_command(label="데스크톱 펫 켜기/끄기", command=self.app.toggle_pet)
        m.add_command(label="위치 초기화", command=self._reset_pos)
        m.add_separator()
        m.add_command(label="작업 표시줄에서 숨기기", command=lambda: self.app.set_taskbar(False))
        m.add_command(label="종료", command=self.app.quit)
        m.tk_popup(e.x_root, e.y_root)

    def _reset_pos(self):
        self.app.comp.settings["taskbar_offset"] = None
        self.app.comp.save()
        self._reposition()

    def _enter(self, e):
        if self.tip or self._drag:
            return
        self.tip = tk.Toplevel(self.win)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(self.tip, text=self.app.status_text(), justify="left", font=(FONT, 9), bg="#222831",
                 fg="#ffffff", padx=10, pady=6).pack()
        self.tip.update_idletasks()
        w, h = self.tip.winfo_width(), self.tip.winfo_height()
        x = self.win.winfo_x() + self.win.winfo_width() // 2 - w // 2
        y = self.win.winfo_y() - h - W(10)
        self.tip.geometry(f"+{max(0, min(self.win.winfo_screenwidth() - w, x))}+{max(0, y)}")

    def _hide_tip(self):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------- main app
class App:
    def __init__(self, start_hidden=False):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        try:  # 알림/작업 표시줄에 "Python" 대신 앱 이름이 보이도록
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PokeTokenBar")
        except Exception:  # noqa: BLE001
            pass
        global SF
        self.root = tk.Tk()
        SF = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self.root.title("PokeTokenBar")
        self.root.configure(bg=C["bg"])
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ww, wh = W(470), min(W(760), sh - W(150))
        self.root.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{W(30)}")
        self.root.minsize(W(430), W(520))
        self._set_window_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_main)
        self.root.report_callback_exception = lambda *a: log_error("".join(traceback.format_exception(*a)))
        self.q: queue.Queue = queue.Queue()
        self.pd = PokeData(APP_DIR / "cache")
        self.scanner = UsageScanner(APP_DIR / "usage_cache.json")
        self.comp = Companion(APP_DIR / "state.json")
        self.summary = None
        self.hatching = False
        self.hatch_error = None
        self.frame_cache: dict = {}
        self.fetching: set = set()
        self.photos: dict = {}
        self.running = True
        self.wake = threading.Event()
        self.dex_dirty = True
        self.dex_page = 0
        self.weather = self.comp.s.get("weather")
        self.dex_filter = tk.StringVar(master=self.root, value="all")

        self._style()
        self._build()
        self._set_window_icon()
        self.root.title(self.app_title())
        self.pet = PetWindow(self)
        self.taskbar = TaskbarWidget(self)
        self.tray = Tray(self)
        self.refresh_all()
        threading.Thread(target=self._scan_loop, daemon=True).start()
        self.wx_wake = threading.Event()
        threading.Thread(target=self._weather_loop, daemon=True).start()
        a = self.comp.active
        if a and "growth_rate" not in a:
            def enrich(a=dict(a)):
                try:
                    self.post(self._on_enriched, enrich_line(self.pd, a))
                except Exception:  # noqa: BLE001
                    log_error("enrich: " + traceback.format_exc())
            threading.Thread(target=enrich, daemon=True).start()
        self.root.after(100, self._pump)
        if start_hidden or self.comp.settings.get("start_hidden"):
            self.root.withdraw()

    @property
    def pikachu_mode(self) -> bool:
        return self.comp.settings.get("fixed_base") == PIKACHU_BASE

    def app_title(self) -> str:
        return "피카츄 키우기" if self.pikachu_mode else "PokeTokenBar"

    def _set_window_icon(self):
        img = egg_image(64, pikachu=hasattr(self, "comp") and self.pikachu_mode)
        self._icon_photo = ImageTk.PhotoImage(img, master=self.root)
        self.root.iconphoto(True, self._icon_photo)

    # ---------- 스레드 간 통신
    def post(self, fn, *args):
        self.q.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except Exception:  # noqa: BLE001
                    log_error(traceback.format_exc())
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._pump)

    def _scan_loop(self):
        while self.running:
            try:
                s = self.scanner.scan()
                self.post(self.on_summary, s)
            except Exception:  # noqa: BLE001
                log_error(traceback.format_exc())
            self.wake.wait(timeout=max(1, self.comp.settings["refresh_min"]) * 60)
            self.wake.clear()

    def _weather_loop(self):
        while self.running:
            if self.comp.settings.get("weather_boost", True):
                try:
                    w = wx.fetch(self.comp.settings.get("city", "서울"))
                    self.post(self._on_weather, w)
                except Exception:  # noqa: BLE001
                    log_error("weather: " + traceback.format_exc())
            self.wx_wake.wait(timeout=30 * 60)
            self.wx_wake.clear()

    def _on_weather(self, w):
        self.weather = w
        self.comp.s["weather"] = w
        self.comp.save()
        self.refresh_all()

    def current_boost(self) -> list[str]:
        if not self.comp.settings.get("weather_boost", True) or self.pikachu_mode:
            return []
        return wx.boost_types(self.weather)

    def refresh_now(self):
        self.wake.set()

    # ---------- 데이터 흐름
    def on_summary(self, s):
        self.summary = s
        if not self.comp.s.get("calibrated"):
            self.calibrate(silent=True)
        events = self.comp.ingest_total(s.all_time_total)
        self.comp.save()
        self.handle_events(events)
        self.maybe_hatch()
        self._update_estimate()
        self.refresh_all()

    def _on_enriched(self, r):
        events = self.comp.apply_enrich(r)
        self.comp.save()
        self.handle_events(events)
        self.refresh_all()

    def maybe_hatch(self):
        if not self.comp.egg_ready() or self.hatching:
            return
        self.hatching = True
        collected = set(self.comp.s["graduated_lines"])
        tier = self.comp.egg.get("tier")
        charm = self.comp.s["shiny_charm"]
        fixed = self.comp.settings.get("fixed_base")
        boost = self.current_boost()
        w = self.weather if boost else None

        def work():
            try:
                r = roll_hatch(self.pd, collected, tier, charm, fixed, boost)
                if w:
                    r["born_weather"] = w["kind"]
                self.post(self.on_hatched, r)
            except Exception as e:  # noqa: BLE001
                log_error("hatch: " + traceback.format_exc())
                self.post(self.on_hatch_failed, str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_hatched(self, r):
        self.hatching = False
        self.hatch_error = None
        if not self.comp.egg_ready():  # 그 사이 상점에서 알을 바꾼 경우 등
            return
        events = self.comp.apply_hatch(r)
        self.comp.save()
        self.handle_events(events)
        self.maybe_hatch()
        self.refresh_all()

    def on_hatch_failed(self, err):
        self.hatching = False
        self.hatch_error = err
        self.refresh_all()
        self.root.after(60_000, self.maybe_hatch)

    def handle_events(self, events):
        for ev in events:
            kind = ev[0]
            if kind == "hatch":
                _, name, rarity, shiny = ev
                title = "✨ 색이 다른 포켓몬이 태어났어요!" if shiny else "알이 부화했어요!"
                msg = f"{josa(name, '이/가')} 태어났어요! ({RARITY_KO[rarity]})"
                bw = (self.comp.active or {}).get("born_weather")
                if bw:
                    msg = f"{wx.WEATHERS[bw][0]} 오는 날, " + msg if bw in ("rain", "snow") else \
                        f"{wx.WEATHERS[bw][0]} 날씨에 " + msg
            elif kind == "evolve":
                a, b = ev[1], ev[2]
                if len(ev) > 3 and ev[3] in MEGA_SPECIES:
                    title, msg = "메가진화!", f"{josa(a, '은/는')} {josa(b, '으로/로')} 메가진화했어요!"
                else:
                    title, msg = "진화!", f"축하해요! {josa(a, '은/는')} {josa(b, '으로/로')} 진화했어요!"
            elif kind == "graduate":
                _, name, rarity = ev
                title, msg = "졸업!", f"{josa(name, '이/가')} 도감에 등록됐어요. 새 알이 도착했어요."
            elif kind == "mint":
                _, old, new = ev
                title, msg = "민트 사용", f"성격이 {old} → {new}(으)로 바뀌었어요."
            else:
                continue
            self.dex_dirty = True
            self.pet.say(f"{title}\n{msg}")
            if self.comp.settings["notify"] and kind != "mint":
                self.tray.notify(title, msg)

    # ---------- 스프라이트
    def frames_for(self, key, size):
        ck = (key, size)
        if ck in self.frame_cache:
            return self.frame_cache[ck]
        if key == "egg":
            wob = [0, 0, 0, 0, -7, 0, 7, 0, 0, 0]
            res = ([egg_image(size, w, self.pikachu_mode) for w in wob], [180] * len(wob))
        else:
            sid, shiny = key
            p = self.pd.sprite_path(sid, shiny)
            if not p.exists():
                self._fetch_sprite(sid, shiny)
                return self.frames_for("egg", size)
            try:
                res = load_frames(p, size)
            except Exception:  # noqa: BLE001
                log_error(traceback.format_exc())
                return self.frames_for("egg", size)
        self.frame_cache[ck] = res
        return res

    def _fetch_sprite(self, sid, shiny):
        if (sid, shiny) in self.fetching:
            return
        self.fetching.add((sid, shiny))

        def work():
            self.pd.ensure_sprite(sid, shiny)
            self.post(self._sprite_ready)
        threading.Thread(target=work, daemon=True).start()

    def _sprite_ready(self):
        self.dex_dirty = True
        self.refresh_all()

    def photo(self, key, size, frame=0, master=None):
        frames, _ = self.frames_for(key, size)
        ck = (key, size, frame)
        if ck in self.photos:
            return self.photos[ck]
        ph = ImageTk.PhotoImage(frames[min(frame, len(frames) - 1)], master=master or self.root)
        if key == "egg" or (key, size) in self.frame_cache:  # 다운로드 전 임시 알 이미지는 캐시하지 않음
            self.photos[ck] = ph
        else:
            self._tmp_photos = getattr(self, "_tmp_photos", [])[-200:] + [ph]
        return ph

    def item_icon(self, kind: str):
        """상점/가방 아이콘 (PokéAPI 아이템 스프라이트, 알은 직접 그림)."""
        ck = ("item", kind)
        if ck in self.photos:
            return self.photos[ck]
        size = W(40)
        if kind.startswith("egg"):
            img = egg_image(size, pikachu=self.pikachu_mode)
        else:
            path = self.pd.sprite_dir / f"item_{ITEM_SPRITES[kind]}.png"
            if not path.exists():
                if ck not in self.fetching:
                    self.fetching.add(ck)

                    def work():
                        if self.pd.ensure_item_sprite(ITEM_SPRITES[kind]):
                            self.post(self.refresh_all)
                    threading.Thread(target=work, daemon=True).start()
                return None
            img = Image.open(path).convert("RGBA")
            bb = img.getbbox()
            if bb:
                img = img.crop(bb)
            sc = min(size / img.width, size / img.height)
            img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.NEAREST)
        self.photos[ck] = ImageTk.PhotoImage(img, master=self.root)
        return self.photos[ck]

    def current_key(self):
        a = self.comp.active
        return (a["current_id"], a["shiny"]) if a else "egg"

    # ---------- 텍스트
    def status_text(self) -> str:
        a = self.comp.active
        if a:
            head = (self.comp.name_of(a["current_id"]) + (" ✨" if a["shiny"] else "")
                    + f"  Lv.{self.comp.level()}")
        else:
            thr = self.comp.egg_threshold()
            head = f"알 ({min(1, self.comp.egg['progress'] / thr):.0%})"
        s = self.summary
        if s:
            return f"{head}\n오늘 {fmt_tokens(s.today_total)} 토큰 · ${s.today_cost:,.2f}"
        return head + "\n사용량 읽는 중…"

    # ---------- 화면 갱신
    def refresh_all(self):
        self._refresh_home()
        key = self.current_key()
        frames, durs = self.frames_for(key, self.comp.settings["pet_size"])
        self.pet.set_sprite((key, self.comp.settings["pet_size"]), frames, durs)
        tsz = self.taskbar.sprite_size()
        tframes, tdurs = self.frames_for(key, tsz)
        s = self.summary
        ttext = fmt_tokens(s.today_total) if s else "…"
        if s and self.comp.settings.get("taskbar_cost"):
            ttext += f"\n${s.today_cost:,.2f}"
        self.taskbar.update((key, tsz), tframes, tdurs, ttext)
        tray_img = self.frames_for(key, 64)[0][0]
        self.tray.update(tray_img, self.app_title() + "\n" + self.status_text())
        if self.dex_dirty and self.nb.index("current") == 1:
            self._refresh_dex()
        if self.nb.index("current") == 2:
            self._refresh_shop()

    # ---------- 창
    def show_main(self):
        r = self.root
        r.deiconify()
        if r.state() == "iconic":
            r.state("normal")
        r.lift()
        # Windows 는 백그라운드 앱의 창 활성화를 막으므로, 잠깐 최상위로 올리고 포그라운드를 강제한다
        r.attributes("-topmost", True)
        try:
            _force_foreground(int(r.wm_frame(), 16))
        except Exception:  # noqa: BLE001
            log_error(traceback.format_exc())
        r.focus_force()
        r.after(300, lambda: r.attributes("-topmost", False))

    def hide_main(self):
        self.root.withdraw()

    def set_pikachu(self, on: bool):
        self.comp.settings["fixed_base"] = PIKACHU_BASE if on else None
        self.comp.save()
        # 알 그림/제목이 바뀌므로 캐시 초기화
        self.frame_cache = {k: v for k, v in self.frame_cache.items() if k[0] != "egg"}
        self.photos = {k: v for k, v in self.photos.items() if k[0] != "egg" and not str(k[1]).startswith("egg")}
        self.h_sprite_key = self.pet.key = self.taskbar.key = None
        self._set_window_icon()
        self.root.title(self.app_title())
        self.l_title.configure(text=self.app_title())
        self.dex_dirty = True
        a = self.comp.active
        if on and a and a["base_id"] != PIKACHU_BASE:
            messagebox.showinfo("피카츄 키우기", f"지금 키우는 {josa(self.comp.name_of(a['current_id']), '이/가')} "
                                "졸업하면 다음 알부터 피츄가 태어나요.\n바로 바꾸려면 상점에서 새 알을 사세요.",
                                parent=self.root)
        self.refresh_all()

    def toggle_main(self):
        # 위젯 클릭 직전에 메인 창이 맨 앞에 있었으면 숨기고, 아니면(숨김/다른 창 뒤) 앞으로 가져온다
        if self.root.state() == "normal" and getattr(self, "_fg_before_click", False):
            self.hide_main()
        else:
            self.show_main()

    def set_setting(self, key, value):
        self.comp.settings[key] = value
        self.comp.save()
        if key == "taskbar_cost" and hasattr(self, "v_tcost"):
            self.v_tcost.set(value)
        self.refresh_all()

    def set_taskbar(self, on: bool):
        self.comp.settings["taskbar_visible"] = on
        self.comp.save()
        self.taskbar.show(on)
        self.v_taskbar.set(on)
        self.tray.icon.update_menu()

    def toggle_pet(self):
        st = self.comp.settings
        st["pet_visible"] = not st["pet_visible"]
        self.comp.save()
        self.pet.show(st["pet_visible"])
        self.v_pet.set(st["pet_visible"])
        self.tray.icon.update_menu()

    def set_pet_size(self, s):
        self.comp.settings["pet_size"] = int(s)
        self.comp.save()
        self.pet.place()
        self.pet.key = None
        self.refresh_all()
        self.v_pet_size.set(int(s))

    def quit(self):
        self.running = False
        self.wake.set()
        try:
            self.comp.save()
        except OSError:
            pass
        self.tray.stop()
        self.root.destroy()

    # ================================================================ UI 구성
    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("TNotebook", background=C["bg"], borderwidth=0)
        st.configure("TNotebook.Tab", font=(FONT, 10), padding=(14, 6), background="#e9ecef")
        st.map("TNotebook.Tab", background=[("selected", C["card"])])
        st.configure("TButton", font=(FONT, 9), padding=(10, 4))
        st.configure("Accent.TButton", font=(FONT, 9, "bold"), foreground="#ffffff", background=C["accent"])
        st.map("Accent.TButton", background=[("active", "#c92a2a"), ("disabled", "#adb5bd")])
        st.configure("TCheckbutton", background=C["card"], font=(FONT, 10))
        st.configure("TCombobox", font=(FONT, 10))

    def _build(self):
        head = tk.Frame(self.root, bg=C["bg"], padx=14, pady=10)
        head.pack(fill="x")
        self.l_title = lbl(head, self.app_title(), 15, True)
        self.l_title.pack(side="left")
        lbl(head, " for Windows", 10, color=C["sub"]).pack(side="left", pady=(5, 0))
        ttk.Button(head, text="⟳ 새로고침", command=self.refresh_now).pack(side="right")
        self.l_updated = lbl(head, "", 8, color=C["sub"])
        self.l_updated.pack(side="right", padx=8)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)
        self.tab_home = Scrollable(self.nb, C["bg"])
        self.tab_dex = Scrollable(self.nb, C["bg"])
        self.tab_shop = Scrollable(self.nb, C["bg"])
        self.tab_set = Scrollable(self.nb, C["bg"])
        for t, name in ((self.tab_home, "홈"), (self.tab_dex, "도감"), (self.tab_shop, "가방·상점"),
                        (self.tab_set, "설정")):
            self.nb.add(t, text=name)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh_all())
        self._build_home()
        self._build_settings()

    # ---------------- 홈
    def _build_home(self):
        p = self.tab_home.inner
        tk.Frame(p, bg=C["bg"], height=10).pack()
        self.h_weather = lbl(p, "", 9, color="#1971c2", wraplength=W(400), justify="left")
        self.h_weather.pack(fill="x", padx=W(14), pady=(0, 6))
        c1 = card(p)
        self.h_sprite = tk.Label(c1, bg=C["card"], width=W(170), height=W(170))
        self.h_sprite.pack()
        self.h_anim = Anim(self.h_sprite)
        self.h_sprite_key = None
        self.h_name = lbl(c1, "", 16, True)
        self.h_name.pack()
        self.h_meta = lbl(c1, "", 9, color=C["sub"])
        self.h_meta.pack(pady=(0, 8))
        self.h_bar = tk.Canvas(c1, width=W(380), height=W(10), highlightthickness=0, bg=C["card"])
        self.h_bar.pack(fill="x")
        self.h_prog = lbl(c1, "", 9, color=C["sub"])
        self.h_prog.pack(pady=(4, 0))
        self.h_line = tk.Frame(c1, bg=C["card"])
        self.h_line.pack(pady=(10, 0))

        c2 = card(p)
        row = tk.Frame(c2, bg=C["card"])
        row.pack(fill="x")
        lbl(row, "오늘", 10, True, color=C["sub"]).pack(side="left")
        self.h_cost = lbl(row, "", 10, color=C["sub"])
        self.h_cost.pack(side="right")
        self.h_today = lbl(c2, "—", 26, True)
        self.h_today.pack(anchor="w")
        self.h_prov = tk.Frame(c2, bg=C["card"])
        self.h_prov.pack(fill="x", pady=(4, 0))

        c3 = card(p)
        row = tk.Frame(c3, bg=C["card"])
        row.pack(fill="x")
        lbl(row, "최근 14일", 10, True, color=C["sub"]).pack(side="left")
        self.h_week = lbl(row, "", 9, color=C["sub"])
        self.h_week.pack(side="right")
        self.h_chart = tk.Canvas(c3, height=W(120), highlightthickness=0, bg=C["card"])
        self.h_chart.pack(fill="x", pady=(6, 0))
        self.h_chart.bind("<Configure>", lambda e: self._draw_chart())

        self.h_limits_card = card(p)
        lbl(self.h_limits_card, "공식 한도", 10, True, color=C["sub"]).pack(anchor="w")
        self.h_limits = tk.Frame(self.h_limits_card, bg=C["card"])
        self.h_limits.pack(fill="x")

    def _refresh_home(self):
        comp, a = self.comp, self.comp.active
        if self.pikachu_mode:
            self.h_weather.configure(text="피카츄 키우기 모드 — 날씨와 상관없이 피츄가 태어나요")
        elif not comp.settings.get("weather_boost", True):
            self.h_weather.configure(text="날씨 보너스 꺼짐 — 설정에서 켤 수 있어요")
        else:
            self.h_weather.configure(text=wx.describe(self.weather))
        key = self.current_key()
        if key != self.h_sprite_key:
            self.h_sprite_key = key
            frames, durs = self.frames_for(key, W(160))
            photos = [ImageTk.PhotoImage(f, master=self.root) for f in frames]
            self.h_anim.set(photos, durs)
            self.h_sprite_key = key if key == "egg" or self.pd.sprite_path(*key).exists() else None
        for w in self.h_line.winfo_children():
            w.destroy()
        if a:
            name = comp.name_of(a["current_id"])
            self.h_name.configure(text=name + ("  ✨" if a["shiny"] else ""))
            meta = f"{RARITY_KO[a['rarity']]} · 성격 {a['nature']} · #{dex_no(a['current_id']):03d}"
            if a.get("growth_mult", 1) > 1:
                meta += " · 재회 보너스 2× 성장"
            self.h_meta.configure(text=meta, fg=RARITY_COLOR[a["rarity"]])
            thr = comp.phase_threshold()
            node = comp.current_node()
            lv = comp.level()
            _, goal, evolves = comp.stage_levels()
            nxt = f"Lv.{goal} 진화" if evolves else f"Lv.{goal} 졸업"
            self.h_name.configure(text=f"{name}{'  ✨' if a['shiny'] else ''}   Lv.{lv}")
            bar(self.h_bar, a["progress"] / thr, "#f5b800" if self.pikachu_mode else RARITY_COLOR[a["rarity"]])
            self.h_prog.configure(text=f"{nxt}까지 {fmt_tokens(max(0, thr - a['progress']))} 남음  "
                                       f"({a['progress'] / thr:.0%}) · 다음 레벨까지 "
                                       f"{fmt_tokens(comp.tokens_to_next_level())}")
            # 진화 라인: 지나온 단계 + 현재 + 남은 단계(?)
            for i, sid in enumerate(a["path"]):
                if i:
                    lbl(self.h_line, "›", 12, color=C["sub"]).pack(side="left", padx=2)
                fr = tk.Frame(self.h_line, bg=C["card"])
                fr.pack(side="left")
                tk.Label(fr, image=self.photo((sid, a["shiny"]), W(44)), bg=C["card"]).pack()
                lbl(fr, comp.name_of(sid), 8, sid == a["current_id"],
                    color=C["text"] if sid == a["current_id"] else C["sub"]).pack()
            remaining = tree_depth(node) - 1 if node else 0
            for _ in range(remaining):
                lbl(self.h_line, "›", 12, color=C["sub"]).pack(side="left", padx=2)
                lbl(self.h_line, "?", 18, True, color="#ced4da").pack(side="left", padx=8)
        else:
            egg, thr = comp.egg, comp.egg_threshold()
            tier = {"uncommon": "고급 알", "rare": "희귀 알"}.get(
                egg.get("tier"), "피카츄 알" if self.pikachu_mode else "포켓몬 알")
            self.h_name.configure(text=tier)
            if self.hatching:
                meta = "부화하는 중…"
            elif self.hatch_error:
                meta = "부화 실패 (인터넷 연결 확인) — 1분 뒤 다시 시도해요"
            else:
                meta = "토큰을 쓰면 알이 따뜻해져요"
            self.h_meta.configure(text=meta, fg=C["egg"])
            bar(self.h_bar, egg["progress"] / thr, C["egg"])
            self.h_prog.configure(text=f"부화까지 {fmt_tokens(egg['progress'])} / {fmt_tokens(thr)}  "
                                       f"({min(1, egg['progress'] / thr):.0%})")

        s = self.summary
        for w in self.h_prov.winfo_children():
            w.destroy()
        for w in self.h_limits.winfo_children():
            w.destroy()
        if not s:
            return
        self.l_updated.configure(text=f"업데이트 {dt.datetime.fromtimestamp(s.scanned_at):%H:%M}")
        self.h_today.configure(text=f"{fmt_tokens(s.today_total)} 토큰")
        self.h_cost.configure(text=f"API 환산 ${s.today_cost:,.2f}")
        if not s.providers_found:
            lbl(self.h_prov, "Claude Code / Codex 로그를 찾지 못했어요.", 9, color=C["accent"]).pack(anchor="w")
        for m, t in sorted(s.today_by_model.items(), key=lambda kv: -kv[1])[:6]:
            r = tk.Frame(self.h_prov, bg=C["card"])
            r.pack(fill="x")
            lbl(r, m, 9, color=C["sub"]).pack(side="left")
            lbl(r, fmt_tokens(t), 9).pack(side="right")
        self._draw_chart()
        # Codex 한도 (로그에 기록됨)
        lim = s.codex_limits
        shown = False
        if lim:
            for k in ("primary", "secondary"):
                w = lim.get(k)
                if not isinstance(w, dict) or w.get("used_percent") is None:
                    continue
                shown = True
                r = tk.Frame(self.h_limits, bg=C["card"])
                r.pack(fill="x", pady=(6, 0))
                pct = float(w["used_percent"])
                reset = ""
                if w.get("resets_at"):
                    reset = f" · {dt.datetime.fromtimestamp(w['resets_at']):%m/%d %H:%M} 리셋"
                lbl(r, f"Codex {window_label(w.get('window_minutes'))}", 9).pack(side="left")
                lbl(r, f"{pct:.0f}%{reset}", 9, color=C["sub"]).pack(side="right")
                cv = tk.Canvas(self.h_limits, width=W(380), height=W(6), highlightthickness=0, bg=C["card"])
                cv.pack(fill="x", pady=(2, 0))
                bar(cv, pct / 100, C["accent"] if pct >= 90 else "#fab005" if pct >= 70 else "#40c057")
        if not shown:
            lbl(self.h_limits, "Codex 로그에 한도 정보가 없어요. (Claude 공식 한도는 아직 미지원)", 9,
                color=C["sub"], wraplength=W(380), justify="left").pack(anchor="w")

    def _draw_chart(self):
        cv, s = self.h_chart, self.summary
        cv.delete("all")
        if not s:
            return
        days = s.daily[-14:]
        w = max(200, cv.winfo_width())
        h = int(cv["height"])
        top, bottom = 16, h - 18
        mx = max((t for _, t, _ in days), default=0) or 1
        bw = w / len(days)
        week = sum(t for _, t, _ in s.daily[-7:])
        self.h_week.configure(text=f"7일 합계 {fmt_tokens(week)} · 일평균 {fmt_tokens(week / 7)}")
        for i, (d, t, c) in enumerate(days):
            x0, x1 = i * bw + bw * 0.18, (i + 1) * bw - bw * 0.18
            y = bottom - (bottom - top) * t / mx
            today = i == len(days) - 1
            cv.create_rectangle(x0, bottom if t == 0 else y, x1, bottom,
                                fill=C["bar_today"] if today else C["bar"], outline="")
            if today or t == mx:
                cv.create_text((x0 + x1) / 2, y - 7, text=fmt_tokens(t), font=(FONT, 7), fill=C["sub"])
            if i % 2 == len(days) % 2 or today:
                cv.create_text((x0 + x1) / 2, h - 7, text=str(d.day), font=(FONT, 7),
                               fill=C["text"] if today else C["sub"])

    # ---------------- 도감
    def _refresh_dex(self):
        self.dex_dirty = False
        sc = self.tab_dex
        sc.clear()
        p = sc.inner
        dex = self.comp.s["dex"]
        grads = self.comp.s["graduates"]
        owned = {int(k) for k in dex if int(k) <= DEX_MAX}
        tk.Frame(p, bg=C["bg"], height=10).pack()

        # --- 도감 완성도
        c = card(p)
        row = tk.Frame(c, bg=C["card"])
        row.pack(fill="x")
        lbl(row, "도감 완성도", 11, True).pack(side="left")
        lbl(row, f"{len(owned)} / {DEX_MAX}  ({len(owned) / DEX_MAX:.1%})", 11, True,
            color=C["accent"]).pack(side="right")
        cv = tk.Canvas(c, width=W(380), height=W(8), highlightthickness=0, bg=C["card"])
        cv.pack(fill="x", pady=(6, 4))
        bar(cv, len(owned) / DEX_MAX, C["accent"])
        gens = tk.Frame(c, bg=C["card"])
        gens.pack(fill="x")
        for i, (g, lo, hi) in enumerate(GENERATIONS):
            n = sum(1 for sid in owned if lo <= sid <= hi)
            gf = tk.Frame(gens, bg=C["card"])
            gf.grid(row=0, column=i, sticky="ew", padx=2)
            lbl(gf, f"{g}세대", 8, color=C["sub"]).pack()
            lbl(gf, f"{n}/{hi - lo + 1}", 9, True).pack()
            gens.columnconfigure(i, weight=1)
        shinies = sum(1 for d in dex.values() if d.get("shiny"))
        mode = ("피카츄 키우기 모드예요 — 피츄 라인만 부화해요. 설정에서 끄면 랜덤 부화로 도감을 채울 수 있어요."
                if self.pikachu_mode else
                "알에서는 1~5세대 기본형 중 하나가 무작위로 태어나요 (흔한 포켓몬일수록 자주, 전설은 드물게, "
                "날씨에 맞는 타입은 더 자주). 졸업시킨 라인은 다시 나오지 않으니 졸업할수록 도감이 넓어져요. "
                "키우면서 진화한 모습도 도감에 등록돼요.")
        lbl(c, f"졸업 {len(grads)}마리 · 이로치 {shinies}종\n{mode}", 8, color=C["sub"],
            wraplength=W(380), justify="left").pack(anchor="w", pady=(8, 0))

        # --- 페이지 그리드 (원본처럼 한 페이지씩 넘겨 보기)
        c = card(p)
        nav = tk.Frame(c, bg=C["card"])
        nav.pack(fill="x")
        only_owned = self.dex_filter.get() == "owned"
        if only_owned:
            ids = sorted((int(k) for k in dex), key=lambda i: (dex_no(i), i))
        else:
            ids = list(range(1, DEX_MAX + 1))
        per = 20
        pages = max(1, (len(ids) + per - 1) // per)
        self.dex_page = max(0, min(self.dex_page, pages - 1))
        ttk.Button(nav, text="◀", width=3, command=lambda: self._dex_go(self.dex_page - 1)).pack(side="left")
        lbl(nav, f"{self.dex_page + 1} / {pages}", 9, True).pack(side="left", padx=6)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._dex_go(self.dex_page + 1)).pack(side="left")
        for text, val in (("잡은 것만", "owned"), ("전체", "all")):
            ttk.Radiobutton(nav, text=text, value=val, variable=self.dex_filter,
                            command=lambda: (setattr(self, "dex_page", 0), self._refresh_dex())).pack(side="right")
        if not only_owned:
            jump = tk.Frame(c, bg=C["card"])
            jump.pack(fill="x", pady=(4, 0))
            for g, lo, hi in GENERATIONS:
                ttk.Button(jump, text=f"{g}세대", width=5,
                           command=lambda lo=lo: self._dex_go((lo - 1) // per)).pack(side="left", padx=(0, 3))
        grid = tk.Frame(c, bg=C["card"])
        grid.pack(fill="x", pady=(8, 0))
        cols = 4
        for i, sid in enumerate(ids[self.dex_page * per:(self.dex_page + 1) * per]):
            d = dex.get(str(sid))
            if d:
                shiny = d.get("shiny") and not d.get("normal")
                cell = tk.Frame(grid, bg="#f8f9fa", padx=4, pady=4, cursor="hand2",
                                highlightbackground=RARITY_COLOR.get(d.get("rarity"), C["line"]),
                                highlightthickness=1)
                im = tk.Label(cell, image=self.photo((sid, bool(shiny)), W(56)), bg="#f8f9fa")
                marks = ("✨" if d.get("shiny") else "") + (" 졸업" if d.get("graduated") else "")
                t1 = lbl(cell, f"#{dex_no(sid):03d}{' 메가' if sid in MEGA_SPECIES else ''} {marks}", 7,
                         color=C["sub"], bg="#f8f9fa")
                t2 = lbl(cell, display_name(d.get("names"), f"#{sid}"), 9, True, bg="#f8f9fa")
                for w in (cell, im, t1, t2):
                    w.bind("<Button-1>", lambda e, sid=sid: self.open_detail(sid))
            else:
                cell = tk.Frame(grid, bg="#f1f3f5", padx=4, pady=4,
                                highlightbackground=C["line"], highlightthickness=1)
                im = tk.Label(cell, image=self.blank(W(56)), text="?", compound="center",
                              font=(FONT, 20, "bold"), fg="#ced4da", bg="#f1f3f5")
                t1 = lbl(cell, f"#{sid:03d}", 7, color="#adb5bd", bg="#f1f3f5")
                t2 = lbl(cell, "???", 9, True, color="#ced4da", bg="#f1f3f5")
            cell.grid(row=i // cols, column=i % cols, padx=3, pady=3, sticky="nsew")
            im.pack(expand=True)
            t1.pack()
            t2.pack()
        for col in range(cols):
            grid.columnconfigure(col, weight=1, uniform="dex")
        if only_owned and not dex:
            lbl(grid, "아직 비어 있어요. 첫 알이 부화하면 여기에 등록돼요!", 9, color=C["sub"], bg=C["card"]).grid()

        c2 = card(p)
        lbl(c2, "포획 기록", 11, True).pack(anchor="w")
        if not grads:
            lbl(c2, "졸업한 포켓몬이 아직 없어요.", 9, color=C["sub"]).pack(anchor="w")
        for g in reversed(grads[-50:]):
            r = tk.Frame(c2, bg=C["card"])
            r.pack(fill="x", pady=2)
            tk.Label(r, image=self.photo((g["final_id"], g["shiny"]), W(36)), bg=C["card"]).pack(side="left")
            path = " › ".join(display_name(g["names"].get(str(i)), f"#{i}") for i in g["path"])
            lbl(r, path + (" ✨" if g["shiny"] else ""), 9, True).pack(side="left", padx=6)
            lbl(r, f"{RARITY_KO[g['rarity']]} · {g['nature']} · "
                   f"{dt.datetime.fromtimestamp(g['graduated_at']):%y.%m.%d}", 8,
                color=RARITY_COLOR[g["rarity"]]).pack(side="right")

    def blank(self, size: int):
        ck = ("blank", size)
        if ck not in self.photos:
            self.photos[ck] = ImageTk.PhotoImage(Image.new("RGBA", (size, size), (0, 0, 0, 0)), master=self.root)
        return self.photos[ck]

    def _dex_go(self, page: int):
        self.dex_page = page
        self._refresh_dex()
        self.tab_dex.canvas.yview_moveto(0)

    def open_detail(self, sid: int):
        d = self.comp.s["dex"].get(str(sid), {})
        top = tk.Toplevel(self.root, bg=C["card"], padx=18, pady=14)
        top.title(display_name(d.get("names"), f"#{sid}"))
        top.resizable(False, False)
        top.transient(self.root)
        shiny_var = tk.BooleanVar(value=bool(d.get("shiny") and not d.get("normal")))
        sp = tk.Label(top, bg=C["card"])
        sp.pack()
        anim = Anim(sp)

        def show():
            frames, durs = self.frames_for((sid, shiny_var.get()), W(180))
            top._photos = [ImageTk.PhotoImage(f, master=top) for f in frames]
            anim.set(top._photos, durs)
        show()
        names = d.get("names") or {}
        lbl(top, f"#{dex_no(sid):03d}  {display_name(names)}", 15, True).pack()
        lbl(top, f"{names.get('en', '')}  {names.get('ja-Hrkt') or names.get('ja') or ''}", 9,
            color=C["sub"]).pack()
        lbl(top, f"{RARITY_KO.get(d.get('rarity'), '')} · 키운 횟수 {d.get('count', 0)}"
                 + (" · 졸업" if d.get("graduated") else ""), 9,
            color=RARITY_COLOR.get(d.get("rarity"), C["sub"])).pack(pady=(2, 6))
        info = lbl(top, "불러오는 중…", 9, wraplength=W(320), justify="left")
        info.pack()
        if d.get("normal") and d.get("shiny"):
            ttk.Checkbutton(top, text="✨ 색이 다른 모습 보기", variable=shiny_var, command=show).pack(pady=(8, 0))

        def load():
            try:
                spd = self.pd.species(dex_no(sid))
                text = (f"{spd.get('genus') or ''}\n\n{spd.get('flavor') or ''}").strip()
            except Exception:  # noqa: BLE001
                text = "설명을 불러오지 못했어요."
            self.post(lambda: info.winfo_exists() and info.configure(text=text))
        threading.Thread(target=load, daemon=True).start()

    # ---------------- 가방·상점
    def _refresh_shop(self):
        sc = self.tab_shop
        y = sc.canvas.yview()[0]
        sc.clear()
        p = sc.inner
        comp = self.comp
        tk.Frame(p, bg=C["bg"], height=10).pack()
        c = card(p)
        lbl(c, "보유 토큰 (지갑)", 10, True, color=C["sub"]).pack(anchor="w")
        lbl(c, fmt_tokens(comp.wallet), 22, True).pack(anchor="w")
        lbl(c, "앱 설치 후 쓴 토큰이 그대로 화폐가 돼요. (성장과 별개로 쌓여요)", 8, color=C["sub"]).pack(anchor="w")

        c = card(p)
        lbl(c, "가방", 11, True).pack(anchor="w")
        for kind, title, desc in SHOP_ITEMS[:2]:
            n = comp.s["bag"].get(kind, 0)
            r = tk.Frame(c, bg=C["card"])
            r.pack(fill="x", pady=4)
            ic = self.item_icon(kind)
            box = tk.Frame(r, bg=C["card"], width=W(40), height=W(40))
            box.pack_propagate(False)
            box.pack(side="left", padx=(0, 8))
            if ic:
                tk.Label(box, image=ic, bg=C["card"]).pack(expand=True)
            lbl(r, f"{title}  ×{n}", 10, True).pack(side="left")
            b = ttk.Button(r, text="사용", command=lambda k=kind: self._use(k))
            b.pack(side="right")
            if n <= 0 or comp.active is None:
                b.state(["disabled"])

        c = card(p)
        lbl(c, "상점", 11, True).pack(anchor="w")
        for kind, title, desc in SHOP_ITEMS:
            if self.pikachu_mode and kind in ("egg_uncommon", "egg_rare"):
                continue
            if self.pikachu_mode and kind == "egg":
                title, desc = "피카츄 알", "지금 피카츄를 떠나보내고 새 피츄 알부터 다시 시작해요."
            price = comp.price(kind)
            r = tk.Frame(c, bg=C["card"], pady=6)
            r.pack(fill="x")
            tk.Frame(c, bg=C["line"], height=1).pack(fill="x")
            ic = self.item_icon(kind)
            box = tk.Frame(r, bg=C["card"], width=W(40), height=W(40))
            box.pack_propagate(False)
            box.pack(side="left", padx=(0, 8))
            if ic:
                tk.Label(box, image=ic, bg=C["card"]).pack(expand=True)
            left = tk.Frame(r, bg=C["card"])
            left.pack(side="left", fill="x", expand=True)
            lbl(left, title, 10, True).pack(anchor="w")
            lbl(left, desc, 8, color=C["sub"], wraplength=W(210), justify="left").pack(anchor="w")
            right = tk.Frame(r, bg=C["card"])
            right.pack(side="right")
            lbl(right, fmt_tokens(price), 10, True, color=C["accent"]).pack(anchor="e")
            qty = tk.IntVar(value=1)
            if kind in ("rare_candy", "mint"):
                ttk.Spinbox(right, from_=1, to=99, width=4, textvariable=qty).pack(side="left", padx=(0, 4))
            b = ttk.Button(right, text="구매", style="Accent.TButton",
                           command=lambda k=kind, q=qty: self._buy(k, q))
            b.pack(side="left")
            owned = kind == "shiny_charm" and comp.s["shiny_charm"]
            if owned:
                b.configure(text="보유 중")
            if owned or price > comp.wallet:
                b.state(["disabled"])
        self.root.after(10, lambda: sc.canvas.yview_moveto(y))

    def _buy(self, kind, qty_var):
        try:
            qty = max(1, int(qty_var.get()))
        except (tk.TclError, ValueError):
            qty = 1
        if kind.startswith("egg") and self.comp.active:
            name = self.comp.name_of(self.comp.active["current_id"])
            if not messagebox.askyesno("새 알", f"{josa(name, '을/를')} 떠나보내고 새 알부터 시작할까요?\n"
                                               "(도감 기록은 그대로 남아요)", parent=self.root):
                return
        err = self.comp.buy(kind, qty)
        if err:
            messagebox.showinfo("상점", err, parent=self.root)
            return
        self.comp.save()
        self.maybe_hatch()
        self.refresh_all()

    def _use(self, kind):
        err, events = self.comp.use_item(kind)
        if err:
            messagebox.showinfo("가방", err, parent=self.root)
            return
        self.comp.save()
        self.handle_events(events)
        self.maybe_hatch()
        self.refresh_all()

    # ---------------- 설정
    def _build_settings(self):
        p = self.tab_set.inner
        st = self.comp.settings
        tk.Frame(p, bg=C["bg"], height=10).pack()

        c = card(p)
        lbl(c, "키우기 모드", 11, True).pack(anchor="w")
        self.v_pika = tk.BooleanVar(value=self.pikachu_mode)
        ttk.Checkbutton(c, text="피카츄만 키우기 (피츄 → 피카츄 → 라이츄)", variable=self.v_pika,
                        command=lambda: self.set_pikachu(self.v_pika.get())).pack(anchor="w", pady=(4, 0))
        lbl(c, "끄면 원본처럼 1~5세대 포켓몬이 무작위로 부화해요.", 8, color=C["sub"]).pack(anchor="w", pady=(4, 0))

        c = card(p)
        lbl(c, "날씨", 11, True).pack(anchor="w")
        self.v_wx = tk.BooleanVar(value=st.get("weather_boost", True))
        ttk.Checkbutton(c, text="실제 날씨에 따라 잘 나오는 타입 바꾸기", variable=self.v_wx,
                        command=lambda: self._set_weather(self.v_wx.get())).pack(anchor="w", pady=(4, 0))
        r = tk.Frame(c, bg=C["card"])
        r.pack(fill="x", pady=(6, 0))
        lbl(r, "지역", 10).pack(side="left")
        self.v_city = tk.StringVar(value=st.get("city", "서울"))
        cb = ttk.Combobox(r, textvariable=self.v_city, values=list(wx.CITIES), state="readonly", width=8)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_city(self.v_city.get()))
        lbl(c, "맑음: 불꽃·풀·땅 / 구름 조금: 노말·바위 / 흐림: 페어리·격투·독 / 비: 물·전기·벌레 / "
               "바람: 드래곤·비행·에스퍼 / 눈: 얼음·강철 / 안개: 악·고스트 (포켓몬 GO 규칙, 해당 타입 5배)",
            8, color=C["sub"], wraplength=W(380), justify="left").pack(anchor="w", pady=(4, 0))

        c = card(p)
        lbl(c, "작업 표시줄", 11, True).pack(anchor="w")
        self.v_taskbar = tk.BooleanVar(value=st.get("taskbar_visible", True))
        ttk.Checkbutton(c, text="작업 표시줄에 포켓몬 + 오늘 토큰 표시", variable=self.v_taskbar,
                        command=lambda: self.set_taskbar(self.v_taskbar.get())).pack(anchor="w", pady=(4, 0))
        self.v_tcost = tk.BooleanVar(value=st.get("taskbar_cost", False))
        ttk.Checkbutton(c, text="오늘 비용($)도 함께 표시", variable=self.v_tcost,
                        command=lambda: self.set_setting("taskbar_cost", self.v_tcost.get())).pack(anchor="w")
        lbl(c, "트레이 왼쪽에 떠요. 클릭하면 이 창을 열고 닫고, 좌우로 드래그하면 위치를 옮길 수 있어요.", 8,
            color=C["sub"], wraplength=W(380), justify="left"
            ).pack(anchor="w", pady=(4, 0))

        c = card(p)
        lbl(c, "데스크톱 펫", 11, True).pack(anchor="w")
        self.v_pet = tk.BooleanVar(value=st["pet_visible"])
        ttk.Checkbutton(c, text="바탕화면에 포켓몬 띄우기", variable=self.v_pet,
                        command=lambda: self.toggle_pet() if self.v_pet.get() != st["pet_visible"] else None
                        ).pack(anchor="w", pady=(4, 0))
        r = tk.Frame(c, bg=C["card"])
        r.pack(fill="x", pady=(6, 0))
        lbl(r, "크기", 10).pack(side="left")
        self.v_pet_size = tk.IntVar(value=st["pet_size"])
        size_lbl = lbl(r, f"{st['pet_size']}px", 9, color=C["sub"])
        sc = ttk.Scale(r, from_=48, to=384, variable=self.v_pet_size,
                       command=lambda v: size_lbl.configure(text=f"{int(float(v))}px"))
        sc.pack(side="left", fill="x", expand=True, padx=8)
        size_lbl.pack(side="left")
        sc.bind("<ButtonRelease-1>", lambda e: self.set_pet_size(self.v_pet_size.get()))
        lbl(c, "펫을 드래그해서 옮기고, 클릭하면 이 창이 열려요. 우클릭 메뉴도 있어요.", 8, color=C["sub"]
            ).pack(anchor="w", pady=(4, 0))

        c = card(p)
        lbl(c, "성장 속도 · 상점 가격", 11, True).pack(anchor="w")
        lbl(c, "원본 밸런스는 하루 수억 토큰을 쓰는 헤비 유저 기준이라, 처음 실행할 때 내 사용량에 맞춰 자동 조정돼요.",
            8, color=C["sub"], wraplength=W(380), justify="left").pack(anchor="w")
        self.v_growth = tk.StringVar()
        self.v_price = tk.StringVar()
        for text, var, key in (("성장 난이도", self.v_growth, "growth_difficulty"),
                               ("상점 가격", self.v_price, "price_difficulty")):
            r = tk.Frame(c, bg=C["card"])
            r.pack(fill="x", pady=(6, 0))
            lbl(r, text, 10).pack(side="left")
            cb = ttk.Combobox(r, textvariable=var, values=[n for n, _ in PRESETS], state="readonly", width=16)
            cb.pack(side="right")
            cb.bind("<<ComboboxSelected>>", lambda e, var=var, key=key: self._set_diff(key, var.get()))
        self._sync_diff_vars()
        self.l_estimate = lbl(c, "", 9, color="#1971c2", wraplength=W(380), justify="left")
        self.l_estimate.pack(anchor="w", pady=(8, 0))
        ttk.Button(c, text="최근 사용량에 맞추기", command=self.calibrate).pack(anchor="w", pady=(6, 0))

        c = card(p)
        lbl(c, "일반", 11, True).pack(anchor="w")
        r = tk.Frame(c, bg=C["card"])
        r.pack(fill="x", pady=(6, 0))
        lbl(r, "새로고침 간격", 10).pack(side="left")
        self.v_refresh = tk.StringVar(value=f"{st['refresh_min']}분")
        cb = ttk.Combobox(r, textvariable=self.v_refresh, values=["1분", "2분", "5분", "10분", "15분"],
                          state="readonly", width=8)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self._set("refresh_min", int(self.v_refresh.get()[:-1])))
        self.v_notify = tk.BooleanVar(value=st["notify"])
        ttk.Checkbutton(c, text="부화·진화·졸업 알림 표시", variable=self.v_notify,
                        command=lambda: self._set("notify", self.v_notify.get())).pack(anchor="w", pady=(6, 0))
        self.v_auto = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(c, text="Windows 시작 시 자동 실행 (트레이로 시작)", variable=self.v_auto,
                        command=lambda: set_autostart(self.v_auto.get())).pack(anchor="w", pady=(4, 0))
        r = tk.Frame(c, bg=C["card"])
        r.pack(fill="x", pady=(8, 0))
        ttk.Button(r, text="데이터 폴더 열기", command=lambda: os.startfile(APP_DIR)).pack(side="left")
        ttk.Button(r, text="종료", command=self.quit).pack(side="right")

        c = card(p)
        lbl(c, "정보", 11, True).pack(anchor="w")
        lbl(c, "macOS 앱 chattymin/PokeTokenBar(MIT)를 Windows용으로 옮긴 비공식 버전이에요.\n"
               "Claude Code(~/.claude/projects)와 Codex(~/.codex/sessions) 로컬 로그만 읽고, "
               "포켓몬 데이터·스프라이트는 PokéAPI에서 받아요.\n"
               "Pokémon © Nintendo / Creatures / GAME FREAK. 비상업 팬 프로젝트입니다.",
            8, color=C["sub"], wraplength=W(380), justify="left").pack(anchor="w")
        self._update_estimate()

    def _set_weather(self, on: bool):
        self.comp.settings["weather_boost"] = on
        self.comp.save()
        self.wx_wake.set()
        self.refresh_all()

    def _set_city(self, city: str):
        self.comp.settings["city"] = city
        self.weather = None
        self.comp.save()
        self.wx_wake.set()
        self.refresh_all()

    def _set(self, key, value):
        self.comp.settings[key] = value
        self.comp.save()
        if key == "refresh_min":
            self.refresh_now()

    def _set_diff(self, key, name):
        v = dict(PRESETS).get(name)
        if v is None:
            return
        self._set(key, v)
        self._update_estimate()
        self.maybe_hatch()
        # 낮아진 임계 때문에 바로 진화할 수도 있으니 0 토큰을 먹여 판정
        self.handle_events(self.comp.feed(0) if self.comp.active else [])
        self.comp.save()
        self.refresh_all()

    def calibrate(self, silent=False):
        """최근 사용량에 맞춰 성장/가격 배율을 정한다 — 일반 포켓몬(Lv5→Lv50)이 사용한 날 기준 약 7일에 졸업하도록."""
        s = self.summary
        days = [t for _, t, _ in s.daily[-14:] if t > 0] if s else []
        if not days:
            if not silent:
                messagebox.showinfo("사용량에 맞추기", "최근 사용 기록이 없어 계산할 수 없어요.", parent=self.root)
            return
        avg = sum(days) / len(days)
        f = max(0.002, min(1.0, avg * CALIBRATE_DAYS / COMMON_GRAD_TOKENS))
        f = float(f"{f:.2g}")
        self.comp.settings["growth_difficulty"] = f
        self.comp.settings["price_difficulty"] = f
        self.comp.s["calibrated"] = True
        self.comp.save()
        self._sync_diff_vars()
        self._update_estimate()
        if self.comp.active:
            self.handle_events(self.comp.feed(0))
        self.maybe_hatch()
        if not silent:
            self.refresh_all()

    def _sync_diff_vars(self):
        st = self.comp.settings
        for var, key in ((self.v_growth, "growth_difficulty"), (self.v_price, "price_difficulty")):
            cur = st[key]
            var.set(next((n for n, v in PRESETS if abs(v - cur) < 1e-9), f"맞춤 ({cur:.2%})"))

    def _update_estimate(self):
        s = self.summary
        if not s:
            self.l_estimate.configure(text="")
            return
        used = [t for _, t, _ in s.daily[-14:] if t > 0]
        if not used:
            self.l_estimate.configure(text="최근 사용 기록이 없어 예상치를 계산할 수 없어요.")
            return
        avg = sum(used) / len(used)
        g = self.comp.settings["growth_difficulty"]
        per_exp = COMMON_GRAD_TOKENS / (exp_at("medium", 50) - exp_at("medium", 5)) * g
        egg_d = 5_000_000 * g / avg
        evo_d = (exp_at("medium-slow", 16) - exp_at("medium-slow", 5)) * per_exp / avg
        com_d = COMMON_GRAD_TOKENS * g / avg
        leg_d = (exp_at("slow", 50) - exp_at("slow", 5)) * per_exp * RARITY_MULT["legendary"] / avg

        def days(x):
            return f"{x * 24:.0f}시간" if x < 1 else f"{x:.0f}일"
        self.l_estimate.configure(
            text=f"사용한 날 평균 {fmt_tokens(avg)} 기준 → 알 부화 약 {days(egg_d)}, "
                 f"파이리가 리자드로(Lv.16) 약 {days(evo_d)}, 일반 포켓몬 Lv.50 졸업 약 {days(com_d)}, "
                 f"전설 약 {days(leg_d)}")


# ---------------------------------------------------------------- autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --hidden'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "PokeTokenBar.pyw"
    return f'"{pyw if pyw.exists() else exe}" "{main}" --hidden'


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


# ---------------------------------------------------------------- entry
def main():
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, "Local\\PokeTokenBarWin_SingleInstance")
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("PokeTokenBar", "이미 실행 중이에요. 작업 표시줄 오른쪽 트레이 아이콘을 확인해 주세요.")
        return
    sys.excepthook = lambda *a: log_error("".join(traceback.format_exception(*a)))
    app = App(start_hidden="--hidden" in sys.argv)
    app.root.mainloop()
