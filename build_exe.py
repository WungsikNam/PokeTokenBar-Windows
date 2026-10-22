"""Windows exe 빌드: python build_exe.py → dist/PokeTokenBar.exe (Python 없이 실행되는 단일 파일)."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from poketokenbar.pokedata import egg_image  # noqa: E402

ico = root / "build" / "icon.ico"
ico.parent.mkdir(exist_ok=True)
egg_image(256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

subprocess.check_call([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "PokeTokenBar", "--icon", str(ico),
    "--hidden-import", "pystray._win32",
    "--collect-all", "webview",
    "PokeTokenBar.pyw",
], cwd=root)
print("built:", root / "dist" / "PokeTokenBar.exe")
