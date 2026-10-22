"""PokeTokenBar for Windows 실행 진입점 (pythonw 로 실행하면 콘솔 창 없이 뜸).

--login: Claude 로그인 창만 띄우는 모드 (exe 로 묶었을 때 앱이 자기 자신을 이 모드로 실행한다).
--uninstall: 설치 제거 (Windows 설정 → 앱 → 제거 에서 이 모드로 실행된다).
"""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "--login" in sys.argv:
    from poketokenbar.login import main
elif "--uninstall" in sys.argv:
    from poketokenbar.uninstall_ui import main
else:
    from poketokenbar.app import main

main()
