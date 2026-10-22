# PokeTokenBar for Windows

[chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar)(macOS, MIT)를 Windows로 옮긴 비공식 버전입니다.
AI 코딩 도구에 쓴 토큰으로 포켓몬 알을 부화시키고, 진화시키고, 도감을 채워요.

**피카츄 키우기 모드(기본값)**: 알은 항상 피츄로 부화해 피카츄, 라이츄로 진화해요. 졸업하면 다시 피츄 알이 오고, 같은 라인을 다시 키우면 2배 빠르게 자라요.
설정 → 키우기 모드에서 끄면 원본처럼 1~5세대 포켓몬이 무작위로 부화해요.

## 실행

`run.bat`을 더블클릭하세요. 의존성(Pillow, pystray)을 설치한 뒤 콘솔 창 없이 실행돼요.

```
python -m pip install -r requirements.txt
pythonw PokeTokenBar.pyw
```

## 표시되는 곳

- **작업 표시줄 위젯**: 트레이 왼쪽에 움직이는 포켓몬과 오늘 쓴 토큰(선택하면 비용도 함께). 클릭하면 창을 열고 닫고, 좌우로 드래그하면 위치를 옮겨요.
- **트레이 아이콘**: 마우스를 올리면 요약이 보이고, 메뉴에서 위젯·펫 켜기/끄기와 종료를 할 수 있어요.
- **데스크톱 펫**: 바탕화면 위에 떠 있는 포켓몬(48~384px). 드래그·클릭·우클릭 메뉴를 지원하고, 부화하거나 진화하면 말풍선을 띄워요.
- **메인 창**: 홈(포켓몬, 오늘 사용량, 14일 차트, Codex 한도), 도감, 가방·상점, 설정.

## 읽는 데이터

- Claude Code: `~/.claude/projects/**/*.jsonl` (`CLAUDE_CONFIG_DIR` 지원)
- Codex: `~/.codex/sessions/**/*.jsonl` (`CODEX_HOME` 지원). 로그에 남은 사용 한도도 표시해요.
- 포켓몬 데이터와 스프라이트: PokéAPI (처음 받은 뒤에는 캐시에서 읽어요)

앱 데이터는 `%APPDATA%\PokeTokenBarWin`에 저장돼요(`state.json`, 캐시, `error.log`).

## 원본과 다른 점

- 지원하는 도구는 Claude Code와 Codex뿐이에요. Gemini, Cursor 등은 아직 지원하지 않아요.
- Claude 공식 5시간·주간 한도와, 한도를 채우면 받는 이상한 사탕 보상은 아직 없어요.
- 폼 체인지, 개체값·기술 프로필, 다국어 UI는 빠져 있어요(한국어만).
- 성장 속도: 원본 밸런스는 하루 수억 토큰을 쓰는 기준이라, 처음 실행할 때 내 사용량에 맞춰 성장 속도와 상점 가격 배율을 자동으로 정해요. 설정에서 바꿀 수 있어요.

Pokémon © Nintendo / Creatures / GAME FREAK. 비상업 팬 프로젝트입니다.
