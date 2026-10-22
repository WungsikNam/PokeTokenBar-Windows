"""제거 화면 (PokeTokenBar.exe --uninstall).

--yes [--delete-data]: 묻지 않고 제거 (자동화·테스트용)
"""
import sys
import tkinter as tk
from tkinter import messagebox

from . import setup_win

TITLE = "PokeTokenBar 제거"


def main():
    quiet = "--yes" in sys.argv
    if quiet:
        setup_win.uninstall("--delete-data" in sys.argv)
        return
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno(TITLE, "PokeTokenBar를 이 PC에서 제거할까요?", parent=root):
        return
    delete_data = messagebox.askyesno(
        TITLE, "키우던 포켓몬·도감·설정 데이터도 지울까요?\n\n"
               "'아니요'를 누르면 데이터를 남겨둬서, 다시 설치하면 이어서 키울 수 있어요.", parent=root)
    setup_win.uninstall(delete_data)
    messagebox.showinfo(TITLE, "제거했어요. 그동안 함께해 줘서 고마워요!", parent=root)
