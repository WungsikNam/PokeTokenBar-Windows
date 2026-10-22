"""실제 날씨 → 잘 나오는 포켓몬 타입 (포켓몬 GO 의 날씨 부스트 규칙).

날씨는 Open-Meteo(무료, API 키 없음)에서 도시 좌표로만 조회한다 — 위치 권한이나 IP 위치 조회는 쓰지 않는다.
"""
from __future__ import annotations

import json
import time
import urllib.request

# 도시 → (위도, 경도)
CITIES = {
    "서울": (37.566, 126.978), "부산": (35.180, 129.075), "인천": (37.456, 126.705), "대구": (35.871, 128.601),
    "대전": (36.350, 127.385), "광주": (35.160, 126.851), "울산": (35.538, 129.311), "세종": (36.480, 127.289),
    "수원": (37.264, 127.029), "성남": (37.420, 127.127), "용인": (37.241, 127.178), "고양": (37.658, 126.832),
    "창원": (35.228, 128.681), "청주": (36.642, 127.489), "천안": (36.815, 127.114), "전주": (35.824, 127.148),
    "포항": (36.019, 129.343), "춘천": (37.881, 127.730), "강릉": (37.752, 128.876), "제주": (33.499, 126.531),
}

# 날씨 종류 → (이름, 기호, 잘 나오는 타입). 기호는 Tk 가 그릴 수 있는 BMP 문자만 쓴다.
WEATHERS = {
    "clear": ("맑음", "☀", ["fire", "grass", "ground"]),
    "partly": ("구름 조금", "⛅", ["normal", "rock"]),
    "cloudy": ("흐림", "☁", ["fairy", "fighting", "poison"]),
    "rain": ("비", "☂", ["water", "electric", "bug"]),
    "windy": ("바람", "≋", ["dragon", "flying", "psychic"]),
    "snow": ("눈", "❄", ["ice", "steel"]),
    "fog": ("안개", "≡", ["dark", "ghost"]),
}
TYPE_KO = {
    "normal": "노말", "fire": "불꽃", "water": "물", "electric": "전기", "grass": "풀", "ice": "얼음",
    "fighting": "격투", "poison": "독", "ground": "땅", "flying": "비행", "psychic": "에스퍼", "bug": "벌레",
    "rock": "바위", "ghost": "고스트", "dragon": "드래곤", "dark": "악", "steel": "강철", "fairy": "페어리",
}
BOOST = 5          # 날씨에 맞는 타입의 부화 가중치 배수
FRESH_FOR = 3 * 3600  # 이보다 오래된 날씨 정보는 쓰지 않는다


def classify(code: int, wind_kmh: float) -> str:
    """WMO 날씨 코드 + 풍속 → 날씨 종류."""
    if code in (45, 48):
        return "fog"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 51 <= code <= 67 or 80 <= code <= 82 or code >= 95:
        return "rain"
    if wind_kmh >= 24:
        return "windy"
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly"
    return "cloudy"


def fetch(city: str) -> dict:
    lat, lon = CITIES.get(city, CITIES["서울"])
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=weather_code,wind_speed_10m,temperature_2m,is_day&timezone=auto")
    req = urllib.request.Request(url, headers={"User-Agent": "PokeTokenBarWin/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        cur = json.load(r)["current"]
    kind = classify(int(cur["weather_code"]), float(cur.get("wind_speed_10m") or 0))
    return {"city": city, "kind": kind, "temp": cur.get("temperature_2m"), "is_day": cur.get("is_day", 1),
            "at": time.time()}


def boost_types(w: dict | None) -> list[str]:
    if not w or time.time() - w.get("at", 0) > FRESH_FOR:
        return []
    return WEATHERS[w["kind"]][2]


def describe(w: dict | None) -> str:
    if not w:
        return "날씨 정보를 불러오는 중이에요"
    name, sym, types = WEATHERS[w["kind"]]
    temp = f" {w['temp']:.0f}°C" if w.get("temp") is not None else ""
    stale = "" if boost_types(w) else " (오래된 정보)"
    return (f"{sym} {w['city']} {name}{temp}{stale} — "
            f"{'·'.join(TYPE_KO[t] for t in types)} 타입이 잘 나와요")
