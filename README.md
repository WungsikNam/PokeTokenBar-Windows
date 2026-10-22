# PokeTokenBar for Windows

[chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar)(macOS, MIT)를 Windows로 옮긴 비공식 버전입니다.
AI 코딩 도구에 쓴 토큰으로 포켓몬 알을 부화시키고, 진화시키고, 도감을 채워요.

> [!IMPORTANT]
> **비공식 팬 프로젝트(Unofficial Fan Project)입니다.** Nintendo, Creatures Inc., GAME FREAK inc., The Pokémon Company와 아무 관련이 없고, 이들의 승인이나 후원을 받지 않았어요.
> 비상업 목적으로만 만들었고, 판매·광고·후원 등 어떤 수익도 얻지 않아요. 자세한 내용은 아래 [저작권 및 면책 고지](#저작권-및-면책-고지)를 참고하세요.

**도감 채우기(기본값)**: 알에서 1~5세대 기본형 포켓몬 중 하나가 무작위로 부화해요. 흔한 포켓몬일수록 자주 나오고 전설은 드물게 나와요. 키우면서 진화한 모습도 도감에 등록되니, 649종을 모두 채워 보세요.
도감 탭에서 완성도, 세대별 수집 현황, 미발견 칸(???)을 페이지 단위로 볼 수 있어요.

**피카츄 키우기 모드**: 설정 → 키우기 모드에서 켜면 피츄 → 피카츄 → 라이츄 → 메가라이츄 X/Y 라인만 부화해요.

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

## 저작권 및 면책 고지

**한국어**

- 이 프로젝트는 **비공식·비상업 팬 프로젝트**예요. Nintendo, Creatures Inc., GAME FREAK inc., The Pokémon Company와 아무 관련이 없고, 이들의 승인이나 후원을 받지 않았어요.
- 포켓몬(Pokémon), 포켓몬 이름, 캐릭터, 이미지에 대한 모든 권리는 © Nintendo / Creatures Inc. / GAME FREAK inc. / The Pokémon Company에 있어요. Pokémon은 Nintendo의 등록 상표예요.
- 이 저장소에는 **포켓몬 이미지나 게임 데이터가 들어 있지 않아요.** 스프라이트, 이름, 도감 설명은 앱을 실행할 때 [PokéAPI](https://pokeapi.co/)에서 받아 내 PC에만 캐시해요.
- 저장소에 들어 있는 것은 직접 작성한 소스 코드뿐이고, 이 코드는 MIT 라이선스예요([LICENSE](LICENSE)).
- 판매, 광고, 유료 기능, 후원 등 **어떤 방식으로도 수익을 얻지 않아요.**
- 권리자의 요청이 있으면 즉시 내리거나 수정할게요. [Issues](https://github.com/WungsikNam/PokeTokenBar-Windows/issues)에 남겨 주세요.

**English**

This is an **unofficial, non-commercial fan project**. It is not affiliated with, endorsed, sponsored, or approved by Nintendo, Creatures Inc., GAME FREAK inc., or The Pokémon Company.
Pokémon and all related names, characters, and images are trademarks and © of Nintendo / Creatures Inc. / GAME FREAK inc. / The Pokémon Company.
This repository contains **no Pokémon artwork or game data**. Sprites and Pokédex data are fetched at runtime from [PokéAPI](https://pokeapi.co/) and cached only on the user's machine. Only the original source code is distributed here, under the MIT License.
No revenue of any kind is generated from this project. If you are a rights holder and would like anything changed or removed, please open an issue and it will be addressed promptly.

## 크레딧

- 원작: [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar) (macOS, MIT License). 게임 규칙과 밸런스 수치는 원작을 따랐어요.
- 데이터와 스프라이트: [PokéAPI](https://pokeapi.co/), [PokeAPI/sprites](https://github.com/PokeAPI/sprites)
