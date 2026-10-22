"""로컬 AI 코딩 도구 로그에서 토큰 사용량을 읽는다.

- Claude Code: ~/.claude/projects/**/*.jsonl — assistant 메시지의 message.usage 4종 토큰.
  같은 (message.id, requestId) 가 스트리밍/세션 재개로 여러 번 기록되므로 total 이 가장 큰 것만 남긴다.
- Codex: ~/.codex/sessions/**/*.jsonl — event_msg.payload.type == "token_count" 의 last_token_usage(턴 델타).
  같은 rate_limits 정보도 여기서 읽는다.

totalTokens = input + output + cache(write+read), 날짜는 로컬 시간 기준 (원본 PokeTokenBar 와 동일).
파일 단위 (mtime, size) 캐시로 바뀐 파일만 다시 파싱한다.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

# USD / 1M tokens: (input, output, cache_write, cache_read) — 원본 ModelPricing 표의 일부.
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4, 20, 5, 0.2),
    "claude-opus-5": (5, 25, 6.25, 0.5),
    "claude-sonnet-5-5": (2, 10, 2.5, 0.1),
    "claude-sonnet-5": (2, 10, 2.5, 0.2),
    "claude-haiku-5-5": (1, 5, 1.25, 0.1),
    "claude-fable-5-1": (10, 50, 12.5, 0.25),
    "claude-fable-5": (10, 50, 12.5, 1.0),
    "claude-opus-4-8": (5, 25, 6.25, 0.5),
    "claude-opus-4-7": (5, 25, 6.25, 0.5),
    "claude-opus-4-6": (5, 25, 6.25, 0.5),
    "claude-opus-4-5": (5, 25, 6.25, 0.5),
    "claude-opus-4-1": (15, 75, 18.75, 1.5),
    "claude-opus-4": (15, 75, 18.75, 1.5),
    "claude-sonnet-4-6": (3, 15, 3.75, 0.3),
    "claude-sonnet-4-5": (3, 15, 3.75, 0.3),
    "claude-sonnet-4": (3, 15, 3.75, 0.3),
    "claude-haiku-4-5": (1, 5, 1.25, 0.1),
    "claude-3-7-sonnet": (3, 15, 3.75, 0.3),
    "claude-3-5-haiku": (0.8, 4, 1, 0.08),
    "gpt-6-astra": (10, 50, 12.5, 1),
    "gpt-6.1-sol": (2, 10, 2.5, 0.1),
    "gpt-6-sol": (2, 10, 2.5, 0.2),
    "gpt-6-luna": (0.1, 0.5, 0.125, 0.01),
    "gpt-5.6-sol": (4, 20, 5, 0.4),
    "gpt-5.6-terra": (2, 12, 2.5, 0.2),
    "gpt-5.6-luna": (0.2, 1.2, 0.25, 0.02),
    "gpt-5.5": (5, 30, 0, 0.5),
    "gpt-5.4": (2.5, 15, 0, 0.25),
    "gpt-5.3-codex": (1.75, 14, 0, 0.175),
    "gpt-5.2": (1.75, 14, 0, 0.175),
    "gpt-5.1": (1.25, 10, 0, 0.125),
    "gpt-5": (1.25, 10, 0, 0.125),
}
_PRICING_KEYS = sorted(PRICING, key=len, reverse=True)


def rate_for(model: str | None):
    if not model:
        return None
    m = model.lower()
    if m in PRICING:
        return PRICING[m]
    for k in _PRICING_KEYS:  # 날짜 접미사(-20250929) 등은 가장 긴 접두사로 매칭
        if m.startswith(k):
            return PRICING[k]
    return None


def cost_of(model, inp, out, cw, cr) -> float:
    r = rate_for(model)
    if not r:
        return 0.0
    return (inp * r[0] + out * r[1] + cw * r[2] + cr * r[3]) / 1_000_000


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# 엔트리 = [timestamp, provider, model, total, cost, dedup_key]
def parse_claude_file(path: str) -> list:
    out: dict[str, list] = {}
    anon = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            ts = _ts(obj.get("timestamp"))
            if ts is None:
                continue
            inp = _int(usage.get("input_tokens"))
            outp = _int(usage.get("output_tokens"))
            cw = _int(usage.get("cache_creation_input_tokens"))
            cr = _int(usage.get("cache_read_input_tokens"))
            total = inp + outp + cw + cr
            if total <= 0:
                continue
            model = msg.get("model")
            if model == "<synthetic>":
                continue
            e = [ts, "claude", model, total, cost_of(model, inp, outp, cw, cr), None]
            mid, rid = msg.get("id"), obj.get("requestId")
            if mid or rid:
                key = f"{mid or ''}|{rid or ''}"
                e[5] = key
                prev = out.get(key)
                if prev is None or prev[3] < total:
                    out[key] = e
            else:
                anon.append(e)
    return list(out.values()) + anon


def parse_codex_file(path: str, limits_sink: dict) -> list:
    entries = []
    model = None
    prev_cum = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"turn_context"' in line or '"session_meta"' in line:
                try:
                    obj = json.loads(line)
                    m = (obj.get("payload") or {}).get("model")
                    if m:
                        model = m
                except ValueError:
                    pass
                continue
            if '"token_count"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            payload = obj.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            ts = _ts(obj.get("timestamp"))
            rl = payload.get("rate_limits")
            if ts and isinstance(rl, dict) and ts > limits_sink.get("ts", 0):
                limits_sink.update({"ts": ts, "data": rl})
            info = payload.get("info")
            if not isinstance(info, dict) or ts is None:
                continue
            cum = info.get("total_token_usage")
            if cum is not None and cum == prev_cum:  # 같은 상태가 반복 기록된 경우
                continue
            prev_cum = cum
            last = info.get("last_token_usage")
            if not isinstance(last, dict):
                continue
            inp = _int(last.get("input_tokens"))
            cached = _int(last.get("cached_input_tokens"))
            outp = _int(last.get("output_tokens"))
            total = _int(last.get("total_tokens")) or (inp + outp)
            if total <= 0:
                continue
            c = cost_of(model, max(0, inp - cached), outp, 0, cached)
            entries.append([ts, "codex", model, total, c, None])
    return entries


def _claude_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".claude" / "projects", home / ".config" / "claude" / "projects"]
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        for p in env.split(","):
            if p.strip():
                roots.append(Path(p.strip()) / "projects")
    return [r for r in dict.fromkeys(roots) if r.is_dir()]


def _codex_roots() -> list[Path]:
    base = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    return [r for r in (base / "sessions", base / "archived_sessions") if r.is_dir()]


@dataclass
class UsageSummary:
    today_total: int = 0
    today_cost: float = 0.0
    today_by_provider: dict = field(default_factory=dict)
    today_by_model: dict = field(default_factory=dict)
    daily: list = field(default_factory=list)  # [(date, total, cost)] 최근 30일, 오래된 순
    all_time_total: int = 0
    codex_limits: dict | None = None
    providers_found: list = field(default_factory=list)
    scanned_at: float = 0.0


class UsageScanner:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.cache: dict = {}
        try:
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if self.cache.get("v") != 2:
                self.cache = {}
        except (OSError, ValueError):
            self.cache = {}
        self.cache.setdefault("v", 2)
        self.cache.setdefault("files", {})

    def _files(self):
        for root in _claude_roots():
            for p in glob.iglob(str(root / "**" / "*.jsonl"), recursive=True):
                yield "claude", p
        for root in _codex_roots():
            for p in glob.iglob(str(root / "**" / "*.jsonl"), recursive=True):
                yield "codex", p

    def scan(self) -> UsageSummary:
        with self.lock:
            files = self.cache["files"]
            seen = set()
            changed = False
            providers = set()
            for prov, p in self._files():
                seen.add(p)
                providers.add(prov)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                c = files.get(p)
                if c and c["m"] == st.st_mtime and c["s"] == st.st_size:
                    continue
                sink: dict = {}
                try:
                    ents = parse_claude_file(p) if prov == "claude" else parse_codex_file(p, sink)
                except OSError:
                    continue
                files[p] = {"m": st.st_mtime, "s": st.st_size, "e": ents, "l": sink or None}
                changed = True
            for p in list(files):
                if p not in seen:
                    del files[p]
                    changed = True
            if changed:
                try:
                    tmp = self.cache_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(self.cache, separators=(",", ":")), encoding="utf-8")
                    os.replace(tmp, self.cache_path)
                except OSError:
                    pass
            return self._summarize(files, sorted(providers))

    @staticmethod
    def _summarize(files: dict, providers: list) -> UsageSummary:
        # 전역 dedup (Claude 세션 재개 시 같은 메시지가 여러 파일에 존재)
        keyed: dict[str, list] = {}
        plain = []
        limits = None
        for c in files.values():
            for e in c["e"]:
                if e[5]:
                    prev = keyed.get(e[5])
                    if prev is None or prev[3] < e[3]:
                        keyed[e[5]] = e
                else:
                    plain.append(e)
            lim = c.get("l")
            if lim and (limits is None or lim["ts"] > limits["ts"]):
                limits = lim
        today = dt.date.today()
        start = today - dt.timedelta(days=29)
        daily: dict[dt.date, list] = {start + dt.timedelta(days=i): [0, 0.0] for i in range(30)}
        s = UsageSummary(providers_found=providers)
        for e in list(keyed.values()) + plain:
            ts, prov, model, total, cost = e[0], e[1], e[2], e[3], e[4]
            s.all_time_total += total
            d = dt.date.fromtimestamp(ts)
            if d in daily:
                daily[d][0] += total
                daily[d][1] += cost
            if d == today:
                s.today_total += total
                s.today_cost += cost
                s.today_by_provider[prov] = s.today_by_provider.get(prov, 0) + total
                mk = model or prov
                s.today_by_model[mk] = s.today_by_model.get(mk, 0) + total
        s.daily = [(d, v[0], v[1]) for d, v in sorted(daily.items())]
        s.codex_limits = limits["data"] if limits else None
        s.scanned_at = dt.datetime.now().timestamp()
        return s


def fmt_tokens(n: float) -> str:
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            v = n / div
            return f"{v:.1f}{unit}" if v < 100 else f"{v:.0f}{unit}"
    return f"{int(n)}"
