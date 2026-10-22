"""Windows 설치/제거 — 관리자 권한 없이 현재 사용자에게만 설치한다.

설치 위치: %LOCALAPPDATA%\\Programs\\PokeTokenBar\\PokeTokenBar.exe
바로가기: 시작 메뉴(항상), 바탕화면(선택)
제거: Windows 설정 → 앱 → 설치된 앱 → PokeTokenBar → 제거 (= PokeTokenBar.exe --uninstall)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import winreg
from pathlib import Path

APP = "PokeTokenBar"
EXE_NAME = "PokeTokenBar.exe"
VERSION = "1.1.1"
RUN_VALUE = "PokeTokenBarWin"  # 앱 설정의 '자동 실행'과 같은 이름
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NO_WINDOW = 0x08000000


def install_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP


def data_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "PokeTokenBarWin"


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.stdout.strip()


def _folder(name: str) -> Path:
    """바탕화면·시작 메뉴 실제 경로 (OneDrive 로 옮겨진 바탕화면도 처리)."""
    return Path(_ps(f"[Environment]::GetFolderPath('{name}')"))


def _shortcut_paths() -> list[Path]:
    return [_folder("Programs") / f"{APP}.lnk", _folder("Desktop") / f"{APP}.lnk"]


def _make_shortcut(lnk: Path, target: Path):
    q = lambda p: str(p).replace("'", "''")  # noqa: E731
    _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
        f"$s.TargetPath='{q(target)}';$s.WorkingDirectory='{q(target.parent)}';"
        f"$s.IconLocation='{q(target)},0';$s.Description='AI 코딩 토큰으로 포켓몬 키우기';$s.Save()")


def stop_running_app():
    """실행 중인 앱을 끈다. 제거 프로그램 자신(PokeTokenBar.exe --uninstall)은 남겨둔다."""
    _ps(f"Get-CimInstance Win32_Process -Filter \"Name='{EXE_NAME}'\" | "
        "Where-Object { $_.CommandLine -notlike '*--uninstall*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    time.sleep(0.8)


def install(payload: Path, desktop: bool = True, autostart: bool = True, launch: bool = True) -> Path:
    stop_running_app()
    dst_dir = install_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    exe = dst_dir / EXE_NAME
    shutil.copy2(payload, exe)

    progs, desk = _shortcut_paths()
    _make_shortcut(progs, exe)
    if desktop:
        _make_shortcut(desk, exe)
    elif desk.exists():
        desk.unlink()

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", APP), ("DisplayVersion", VERSION), ("Publisher", "WungsikNam"),
                          ("DisplayIcon", f"{exe},0"), ("InstallLocation", str(dst_dir)),
                          ("UninstallString", f'"{exe}" --uninstall'),
                          ("URLInfoAbout", "https://github.com/WungsikNam/PokeTokenBar-Windows")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, exe.stat().st_size // 1024)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if autostart:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, f'"{exe}" --hidden')
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except OSError:
                pass

    if launch:
        subprocess.Popen([str(exe)], cwd=str(dst_dir), creationflags=0x00000008)  # DETACHED_PROCESS
    return exe


def uninstall(delete_data: bool):
    stop_running_app()
    for lnk in _shortcut_paths():
        try:
            lnk.unlink()
        except OSError:
            pass
    for key, value in ((RUN_KEY, RUN_VALUE),):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, value)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if delete_data:
        shutil.rmtree(data_dir(), ignore_errors=True)
    # 실행 중인 자기 자신(exe)은 바로 못 지우므로, 이 프로세스가 끝난 뒤 폴더를 지운다
    d = install_dir()
    if d.exists():
        subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{d}"', shell=True,
                         creationflags=NO_WINDOW | 0x00000008)
