"""PokéAPI 조회 + 디스크 캐시, Gen-V 애니메이션 스프라이트 로딩."""
from __future__ import annotations

import json
import random
import re
import threading
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageSequence

API = "https://pokeapi.co/api/v2"
GRAPHQL = "https://graphql.pokeapi.co/v1beta2"
SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
MAX_ID = 649          # Gen-V 애니메이션 스프라이트 상한
DITTO = 132
UA = {"User-Agent": "PokeTokenBarWin/1.0 (+https://github.com/chattymin/PokeTokenBar)"}


def _get(url: str, data: bytes | None = None, timeout=20) -> bytes:
    headers = dict(UA)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class PokeData:
    def __init__(self, cache_dir: Path):
        self.api_dir = cache_dir / "api"
        self.sprite_dir = cache_dir / "sprites"
        self.api_dir.mkdir(parents=True, exist_ok=True)
        self.sprite_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ---------- JSON API ----------
    def _cached_json(self, name: str, fetch, max_age: float | None = None):
        path = self.api_dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".json")
        if path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        data = fetch()
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def species(self, sid: int) -> dict:
        def fetch():
            d = json.loads(_get(f"{API}/pokemon-species/{sid}"))
            return {
                "id": d["id"],
                "capture_rate": d["capture_rate"],
                "is_legendary": d["is_legendary"],
                "is_mythical": d["is_mythical"],
                "evolves_from": (d.get("evolves_from_species") or {}).get("url"),
                "chain": d["evolution_chain"]["url"],
                "names": {n["language"]["name"]: n["name"] for n in d["names"]
                          if n["language"]["name"] in ("ko", "en", "ja-Hrkt", "ja")},
                "genus": next((g["genus"] for g in d.get("genera", []) if g["language"]["name"] == "ko"), None),
                "flavor": next((f["flavor_text"].replace("\n", " ").replace("\f", " ")
                                for f in reversed(d.get("flavor_text_entries", []))
                                if f["language"]["name"] == "ko"), None),
            }
        return self._cached_json(f"species_{sid}", fetch)

    def base_index(self) -> list[dict]:
        """부화 후보: 진화 전 형태(base) 전체 (id ≤ 649, 메타몽 제외) + capture_rate."""
        def fetch():
            q = ("{ pokemonspecies(where: {evolves_from_species_id: {_is_null: true}, "
                 f"id: {{_lte: {MAX_ID}, _neq: {DITTO}}}}}, order_by: {{id: asc}}) {{ id capture_rate }} }}")
            d = json.loads(_get(GRAPHQL, json.dumps({"query": q}).encode()))
            rows = d["data"]["pokemonspecies"]
            if not rows:
                raise ValueError("empty base index")
            return rows
        return self._cached_json("base_index", fetch, max_age=30 * 86400)

    def chain(self, url: str) -> dict:
        m = re.search(r"/evolution-chain/(\d+)/?$", url)
        if not m or not url.startswith("https://pokeapi.co/"):
            raise ValueError(f"bad chain url {url}")
        cid = m.group(1)

        def fetch():
            d = json.loads(_get(f"{API}/evolution-chain/{cid}"))

            def build(node):
                sid = int(node["species"]["url"].rstrip("/").split("/")[-1])
                kids = [build(c) for c in node["evolves_to"]]
                return {"id": sid, "children": [k for k in kids if k["id"] <= MAX_ID]}
            return build(d["chain"])
        return self._cached_json(f"chain_{cid}", fetch)

    def pick_base(self, collected_bases: set[int], min_tier: str | None = None) -> int:
        """capture_rate 가중 무작위 선택. 이미 졸업시킨 라인은 가중치 절반 (원본과 동일)."""
        ceilings = {"uncommon": 120, "rare": 45}
        try:
            idx = self.base_index()
            if min_tier in ceilings:
                idx = [e for e in idx if e["capture_rate"] <= ceilings[min_tier]]
            weights = [max(1, e["capture_rate"] // 2) if e["id"] in collected_bases else max(1, e["capture_rate"])
                       for e in idx]
            return random.choices(idx, weights=weights, k=1)[0]["id"]
        except Exception:
            # GraphQL 장애 시 REST 폴백: 무작위 종 → 진화 체인 루트
            sid = random.randint(1, MAX_ID)
            if sid == DITTO:
                sid = 1
            ch = self.chain(self.species(sid)["chain"])
            return ch["id"] if ch["id"] <= MAX_ID else sid

    # ---------- 스프라이트 ----------
    def sprite_path(self, sid: int, shiny: bool, animated: bool = True) -> Path:
        kind = ("anim" if animated else "still") + ("_shiny" if shiny else "")
        return self.sprite_dir / f"{kind}_{sid}.{'gif' if animated else 'png'}"

    def ensure_sprite(self, sid: int, shiny: bool) -> Path | None:
        p = self.sprite_path(sid, shiny)
        if p.exists() and p.stat().st_size > 0:
            return p
        sub = "versions/generation-v/black-white/animated/" + ("shiny/" if shiny else "")
        try:
            data = _get(f"{SPRITE_BASE}/{sub}{sid}.gif")
        except Exception:
            # 애니메이션이 없으면 정지 스프라이트로 폴백
            try:
                data = _get(f"{SPRITE_BASE}/{'shiny/' if shiny else ''}{sid}.png")
            except Exception:
                return None
        p.write_bytes(data)
        return p

    def ensure_item_sprite(self, name: str) -> Path | None:
        p = self.sprite_dir / f"item_{name}.png"
        if p.exists():
            return p
        try:
            p.write_bytes(_get(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/{name}.png"))
            return p
        except Exception:
            return None


def load_frames(path: Path, size: int) -> tuple[list[Image.Image], list[int]]:
    """GIF 프레임을 RGBA 로 합성한 뒤, 모든 프레임 공통 bbox 로 자르고 size 정사각형에 맞춰 확대."""
    im = Image.open(path)
    frames, durations = [], []
    for fr in ImageSequence.Iterator(im):
        frames.append(fr.convert("RGBA"))
        durations.append(max(40, fr.info.get("duration", 100) or 100))
    bbox = None
    for f in frames:
        b = f.getbbox()
        if b:
            bbox = b if bbox is None else (min(bbox[0], b[0]), min(bbox[1], b[1]), max(bbox[2], b[2]), max(bbox[3], b[3]))
    out = []
    for f in frames:
        if bbox:
            f = f.crop(bbox)
        w, h = f.size
        scale = min(size / w, size / h)
        # 픽셀아트: 정수 배율이면 NEAREST 로 또렷하게
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        f = f.resize((nw, nh), Image.NEAREST)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(f, ((size - nw) // 2, size - nh), f)  # 바닥 정렬
        out.append(canvas)
    return out, durations


PIKACHU_EGG = ((255, 222, 89, 255), (222, 72, 50, 255))  # 노란 바탕 + 빨간 볼 무늬


def egg_image(size: int, wobble: float = 0.0, pikachu: bool = False) -> Image.Image:
    """간단한 픽셀 알 이미지 (네트워크 없이 그림). pikachu=True 면 피카츄 색 알."""
    from PIL import ImageDraw
    base = 32
    im = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    shell, spot = PIKACHU_EGG if pikachu else ((250, 246, 232, 255), (120, 200, 120, 255))
    d.ellipse((7, 3, 25, 29), fill=shell, outline=(60, 60, 60, 255))
    if pikachu:
        # 번개 무늬 + 빨간 볼
        d.line([(16, 6), (13, 12), (18, 13), (14, 20)], fill=(60, 60, 60, 255), width=1)
        for (x, y, r) in ((11, 21, 2), (21, 21, 2)):
            d.ellipse((x - r, y - r, x + r, y + r), fill=spot)
    else:
        for (x, y, r) in ((12, 10, 3), (19, 15, 2), (13, 21, 3), (20, 23, 2)):
            d.ellipse((x - r, y - r, x + r, y + r), fill=spot)
    im = im.rotate(wobble, resample=Image.NEAREST, center=(16, 29))
    return im.resize((size, size), Image.NEAREST)
