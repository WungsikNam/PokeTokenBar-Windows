"""PokeTokenBar for Windows 실행 진입점 (pythonw 로 실행하면 콘솔 창 없이 뜸)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poketokenbar.app import main  # noqa: E402

main()
