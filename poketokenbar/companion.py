"""포켓몬 동반자 상태 머신 — 알 → 부화 → 진화 → 졸업(도감) → 새 알.

밸런스 상수는 원본 PokeTokenBar(PokemonBalance / RareCandy / Mint / ShinyCharm / FreshEgg)와 같다.
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from pathlib import Path

EGG_HATCH = 5_000_000
GRAD_TOTAL = {"common": 750_000_000, "uncommon": 1_875_000_000, "rare": 3_000_000_000, "legendary": 6_000_000_000}
RARITY_KO = {"common": "일반", "uncommon": "고급", "rare": "희귀", "legendary": "전설"}
RARITY_COLOR = {"common": "#8a8f98", "uncommon": "#2f9e44", "rare": "#1c7ed6", "legendary": "#e8590c"}
CANDY_XP = 100_000_000
PRICES = {"rare_candy": 500_000_000, "mint": 100_000_000, "shiny_charm": 3_000_000_000,
          "egg": 1_000_000_000, "egg_uncommon": 2_500_000_000, "egg_rare": 4_000_000_000}
SHOP_ITEMS = [
    ("rare_candy", "이상한 사탕", "현재 포켓몬에게 100M 토큰만큼 경험치를 줘요."),
    ("mint", "민트", "현재 포켓몬의 성격을 다시 뽑아요."),
    ("shiny_charm", "빛나는 부적", "앞으로 부화하는 알의 이로치 확률 1/64 → 1/48 (영구)."),
    ("egg", "포켓몬 알", "지금 포켓몬을 떠나보내고 새 알부터 다시 시작해요."),
    ("egg_uncommon", "고급 알", "고급 이상 등급이 보장된 새 알."),
    ("egg_rare", "희귀 알", "희귀 이상 등급이 보장된 새 알."),
]
ITEM_SPRITES = {"rare_candy": "rare-candy", "mint": "mental-herb", "shiny_charm": "shiny-charm"}
NATURES = ["노력", "외로움", "용감", "고집", "개구쟁이", "대담", "온순", "무사태평", "장난꾸러기", "촐랑",
           "겁쟁이", "성급", "성실", "명랑", "천진난만", "조심", "의젓", "냉정", "수줍음", "덜렁",
           "차분", "얌전", "건방", "신중", "변덕"]


def rarity_of(sp: dict) -> str:
    if sp["is_legendary"] or sp["is_mythical"]:
        return "legendary"
    cr = sp["capture_rate"]
    return "rare" if cr <= 45 else "uncommon" if cr <= 120 else "common"


def tree_depth(node: dict) -> int:
    return 1 + max((tree_depth(c) for c in node["children"]), default=0)


def find_node(node: dict, sid: int):
    if node["id"] == sid:
        return node
    for c in node["children"]:
        r = find_node(c, sid)
        if r:
            return r
    return None


def tree_ids(node: dict) -> list[int]:
    out = [node["id"]]
    for c in node["children"]:
        out += tree_ids(c)
    return out


def display_name(names: dict | None, fallback="???") -> str:
    if not names:
        return fallback
    return names.get("ko") or names.get("en") or fallback


PIKACHU_BASE = 172  # 피츄 → 피카츄 → 라이츄


def roll_hatch(pd, collected_bases: set[int], tier: str | None, shiny_charm: bool,
               fixed_base: int | None = None) -> dict:
    """네트워크 작업(백그라운드 스레드에서 호출). 부화할 개체를 결정하고 필요한 데이터/스프라이트를 받아둔다.
    fixed_base 가 있으면 무작위 대신 항상 그 진화 라인으로 부화한다 (피카츄 키우기 모드)."""
    base = fixed_base or pd.pick_base(collected_bases, tier)
    sp = pd.species(base)
    tree = pd.chain(sp["chain"])
    node = find_node(tree, base) or tree
    names = {sid: pd.species(sid)["names"] for sid in tree_ids(node)}
    shiny = random.randrange(48 if shiny_charm else 64) == 0
    for sid in tree_ids(node):
        pd.ensure_sprite(sid, shiny)
    return {"base_id": node["id"], "tree": node, "rarity": rarity_of(sp), "names": names,
            "shiny": shiny, "nature": random.choice(NATURES)}


DEFAULT_SETTINGS = {
    "pet_visible": True, "pet_size": 128, "pet_x": None, "pet_y": None,
    "refresh_min": 2, "growth_difficulty": 1.0, "price_difficulty": 1.0,
    "notify": True, "start_hidden": False, "taskbar_visible": True, "taskbar_cost": False,
    "taskbar_offset": None, "fixed_base": PIKACHU_BASE,
}


class Companion:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.s = {}
        s = self.s
        s.setdefault("version", 1)
        s.setdefault("last_total", None)
        s.setdefault("earned", 0)
        s.setdefault("spent", 0)
        s.setdefault("egg", {"progress": 0, "tier": None})
        s.setdefault("active", None)
        s.setdefault("dex", {})
        s.setdefault("graduates", [])
        s.setdefault("graduated_lines", [])
        s.setdefault("bag", {"rare_candy": 0, "mint": 0})
        s.setdefault("shiny_charm", False)
        s.setdefault("installed_at", time.time())
        st = s.setdefault("settings", {})
        for k, v in DEFAULT_SETTINGS.items():
            st.setdefault(k, v)

    # ---------- 저장 ----------
    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def settings(self) -> dict:
        return self.s["settings"]

    @property
    def active(self):
        return self.s["active"]

    @property
    def egg(self):
        return self.s["egg"]

    @property
    def wallet(self) -> int:
        return self.s["earned"] - self.s["spent"]

    # ---------- 밸런스 ----------
    def _g(self, base: float) -> int:
        return max(1, round(base * self.settings["growth_difficulty"]))

    def price(self, kind: str) -> int:
        return max(1, round(PRICES[kind] * self.settings["price_difficulty"]))

    def egg_threshold(self) -> int:
        return self._g(EGG_HATCH)

    def phase_threshold(self, a: dict | None = None) -> int:
        a = a or self.active
        k = tree_depth(a["tree"])
        i = a["stage_index"] + 1
        std = GRAD_TOTAL[a["rarity"]] * i / (k * (k + 1) / 2)
        return max(1, self._g(std / a.get("growth_mult", 1)))

    def egg_ready(self) -> bool:
        return self.active is None and self.egg["progress"] >= self.egg_threshold()

    def current_node(self):
        a = self.active
        return find_node(a["tree"], a["current_id"]) if a else None

    # ---------- 토큰 투입 ----------
    def ingest_total(self, all_time_total: int) -> list:
        """로그 누적 합계를 받아 증가분만 먹인다. 오래된 로그가 지워져 합계가 줄면 그 지점부터 다시 센다."""
        last = self.s["last_total"]
        self.s["last_total"] = all_time_total
        if last is None:
            return []
        delta = all_time_total - last
        if delta <= 0:
            return []
        self.s["earned"] += delta
        return self.feed(delta)

    def feed(self, n: int) -> list:
        events = []
        a = self.active
        if a is None:
            self.egg["progress"] += n
            return events
        a["progress"] += n
        while self.active is not None and a["progress"] >= self.phase_threshold(a):
            thr = self.phase_threshold(a)
            node = find_node(a["tree"], a["current_id"])
            if node and node["children"]:
                a["progress"] -= thr
                fresh = [c for c in node["children"] if str(c["id"]) not in self.s["dex"]]
                child = random.choice(fresh or node["children"])
                old = a["current_id"]
                a["current_id"] = child["id"]
                a["stage_index"] += 1
                a["path"].append(child["id"])
                self._register_dex(child["id"], a)
                events.append(("evolve", self.name_of(old, a), self.name_of(child["id"], a)))
            else:
                leftover = a["progress"] - thr
                events.append(("graduate", self.name_of(a["current_id"], a), a["rarity"]))
                self._graduate(a)
                self.egg["progress"] += leftover
        return events

    def name_of(self, sid: int, a: dict | None = None) -> str:
        a = a or self.active
        names = (a or {}).get("names", {}).get(str(sid)) if a else None
        if not names:
            names = (self.s["dex"].get(str(sid)) or {}).get("names")
        return display_name(names, f"#{sid}")

    def _register_dex(self, sid: int, a: dict):
        d = self.s["dex"].setdefault(str(sid), {"names": a["names"].get(str(sid)), "normal": False,
                                                "shiny": False, "count": 0, "graduated": False,
                                                "rarity": a["rarity"], "first_at": time.time()})
        d["names"] = d.get("names") or a["names"].get(str(sid))
        d["shiny" if a["shiny"] else "normal"] = True
        d["count"] += 1

    def _graduate(self, a: dict):
        self.s["graduates"].append({
            "uid": a["uid"], "base_id": a["base_id"], "final_id": a["current_id"], "path": a["path"],
            "rarity": a["rarity"], "shiny": a["shiny"], "nature": a["nature"],
            "hatched_at": a["hatched_at"], "graduated_at": time.time(),
            "names": {str(i): a["names"].get(str(i)) for i in a["path"]},
        })
        d = self.s["dex"].get(str(a["current_id"]))
        if d:
            d["graduated"] = True
        if a["base_id"] not in self.s["graduated_lines"]:
            self.s["graduated_lines"].append(a["base_id"])
        self.s["active"] = None
        self.s["egg"] = {"progress": 0, "tier": None}

    def apply_hatch(self, r: dict) -> list:
        carry = max(0, self.egg["progress"] - self.egg_threshold())
        names = {str(k): v for k, v in r["names"].items()}
        a = {
            "uid": uuid.uuid4().hex[:12], "base_id": r["base_id"], "tree": r["tree"], "rarity": r["rarity"],
            "names": names, "current_id": r["base_id"], "stage_index": 0, "progress": 0,
            "path": [r["base_id"]], "shiny": r["shiny"], "nature": r["nature"], "hatched_at": time.time(),
            "growth_mult": 2 if r["base_id"] in self.s["graduated_lines"] else 1,
        }
        self.s["active"] = a
        self.s["egg"] = {"progress": 0, "tier": None}
        self._register_dex(a["base_id"], a)
        events = [("hatch", self.name_of(a["base_id"], a), a["rarity"], a["shiny"])]
        if carry:
            events += self.feed(carry)
        return events

    # ---------- 상점 / 가방 ----------
    def buy(self, kind: str, qty: int = 1) -> str | None:
        """구매. 실패 시 사유 문자열, 성공 시 None."""
        if kind == "shiny_charm":
            if self.s["shiny_charm"]:
                return "이미 가지고 있어요."
            qty = 1
        if kind.startswith("egg"):
            qty = 1
        cost = self.price(kind) * qty
        if cost > self.wallet:
            return "토큰이 부족해요."
        self.s["spent"] += cost
        if kind in ("rare_candy", "mint"):
            self.s["bag"][kind] = self.s["bag"].get(kind, 0) + qty
        elif kind == "shiny_charm":
            self.s["shiny_charm"] = True
        else:
            tier = {"egg": None, "egg_uncommon": "uncommon", "egg_rare": "rare"}[kind]
            self.s["active"] = None
            self.s["egg"] = {"progress": 0, "tier": tier}
        return None

    def use_item(self, kind: str) -> tuple[str | None, list]:
        if self.s["bag"].get(kind, 0) <= 0:
            return "가방에 없어요.", []
        if self.active is None:
            return "알 상태에서는 쓸 수 없어요.", []
        self.s["bag"][kind] -= 1
        if kind == "rare_candy":
            return None, self.feed(CANDY_XP)
        if kind == "mint":
            old = self.active["nature"]
            self.active["nature"] = random.choice([n for n in NATURES if n != old])
            return None, [("mint", old, self.active["nature"])]
        return None, []
