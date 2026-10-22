"""Windows 배포 파일 빌드 (pip install pyinstaller 필요).

    python build_exe.py
    → dist/PokeTokenBar.exe        앱 (설치 없이 바로 실행도 가능)
    → dist/PokeTokenBar-Setup.exe  설치 프로그램 (앱을 담고 있음, 시작 메뉴·바탕화면 바로가기·제거 항목 등록)
"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from poketokenbar.icon import save_ico  # noqa: E402

ico = root / "build" / "pikachu.ico"
ico.parent.mkdir(exist_ok=True)
save_ico(ico)


def pyinstaller(*args):
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                           "--windowed", "--icon", str(ico), *args], cwd=root)


# 1) 앱
pyinstaller("--name", "PokeTokenBar", "--hidden-import", "pystray._win32", "--collect-all", "webview",
            "PokeTokenBar.pyw")
# 2) 설치 프로그램 (앱 exe 를 payload 로 담는다)
pyinstaller("--name", "PokeTokenBar-Setup",
            "--add-data", f"{root / 'dist' / 'PokeTokenBar.exe'};payload", "installer.py")
print("built:", root / "dist" / "PokeTokenBar.exe", "+", root / "dist" / "PokeTokenBar-Setup.exe")
