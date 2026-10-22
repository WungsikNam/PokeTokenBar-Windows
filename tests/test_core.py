"""핵심 로직 테스트 — 네트워크·화면 없이 돈다.  python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poketokenbar import weather  # noqa: E402
from poketokenbar.companion import (Companion, edge_level, exp_at, path_start_levels,  # noqa: E402
                                    COMMON_GRAD_TOKENS)
from poketokenbar.usage import UsageScanner, parse_claude_file, parse_codex_file  # noqa: E402

CHARMANDER = {"id": 4, "children": [{"id": 5, "lv": 16, "trig": None,
                                     "children": [{"id": 6, "lv": 36, "trig": None, "children": []}]}]}
EEVEE = {"id": 133, "children": [{"id": 134, "lv": None, "trig": "use-item", "children": []},
                                 {"id": 196, "lv": None, "trig": "friendship", "children": []}]}
NAMES = {i: {"ko": f"포켓몬{i}"} for i in (4, 5, 6, 133, 134, 196)}


def hatch(c, tree, rate="medium-slow", rarity="common"):
    c.s["egg"] = {"progress": c.egg_threshold(), "tier": None}
    return c.apply_hatch({"base_id": tree["id"], "tree": json.loads(json.dumps(tree)), "rarity": rarity,
                          "names": NAMES, "shiny": False, "nature": "명랑", "growth_rate": rate})


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.state = self.dir / "state.json"

    def comp(self, diff=1.0):
        c = Companion(self.state)
        c.settings["growth_difficulty"] = diff
        return c


class ExpCurves(unittest.TestCase):
    # PokéAPI growth-rate 표와 같은 값 (전 구간 대조는 개발 중에 확인함)
    TABLE = {"slow": {5: 156, 16: 5120, 36: 58320, 50: 156250, 100: 1250000},
             "medium": {5: 125, 16: 4096, 36: 46656, 50: 125000, 100: 1000000},
             "fast": {5: 100, 16: 3276, 36: 37324, 50: 100000, 100: 800000},
             "medium-slow": {5: 135, 16: 2535, 36: 40007, 50: 117360, 100: 1059860},
             "slow-then-very-fast": {5: 237, 16: 6881, 36: 59719, 50: 125000, 100: 600000},
             "fast-then-very-slow": {5: 65, 16: 2457, 36: 46656, 50: 142500, 100: 1640000}}

    def test_matches_games(self):
        for rate, table in self.TABLE.items():
            for lv, exp in table.items():
                self.assertEqual(int(exp_at(rate, lv)), exp, (rate, lv))

    def test_evolution_levels(self):
        self.assertEqual(path_start_levels(CHARMANDER, [4, 5, 6]), [5, 16, 36])
        self.assertEqual(edge_level(EEVEE["children"][0], 0, 5), 25)  # 진화의 돌 → 대표 레벨
        self.assertEqual(edge_level(EEVEE["children"][1], 0, 5), 15)  # 친밀도 → 대표 레벨
        self.assertEqual(edge_level({"trig": "mega"}, 2, 40), 50)


class Growth(Tmp):
    def test_evolves_at_real_levels_and_graduates_at_50(self):
        c = self.comp(0.01)
        ev = hatch(c, CHARMANDER)
        self.assertEqual(ev[0][0], "hatch")
        a = c.active
        self.assertEqual((c.level(), c.stage_levels()), (5, (5, 16, True)))
        c.feed(c.phase_threshold() - 1)
        self.assertEqual((a["current_id"], c.level()), (4, 15))
        ev = c.feed(1)
        self.assertEqual(ev[0][0], "evolve")
        self.assertEqual((a["current_id"], c.level()), (5, 16))
        c.feed(c.phase_threshold())
        self.assertEqual((a["current_id"], c.stage_levels()), (6, (36, 50, False)))
        ev = c.feed(c.phase_threshold() + 123)
        self.assertEqual(ev[-1][0], "graduate")
        self.assertIsNone(c.active)
        self.assertEqual(c.egg["progress"], 123)  # 남은 토큰은 다음 알로 이월
        self.assertEqual(c.s["graduated_lines"], [4])
        self.assertTrue(c.s["dex"]["6"]["graduated"])

    def test_total_cost_scales_with_difficulty(self):
        c = self.comp(1.0)
        hatch(c, {"id": 10, "children": []}, rate="medium")
        self.assertAlmostEqual(c.phase_threshold(), COMMON_GRAD_TOKENS, delta=1)  # Lv5→50 = 기준값
        c.settings["growth_difficulty"] = 0.1
        self.assertAlmostEqual(c.phase_threshold(), COMMON_GRAD_TOKENS * 0.1, delta=1)

    def test_rare_candy_is_one_level(self):
        c = self.comp(0.05)
        hatch(c, CHARMANDER)
        c.s["bag"]["rare_candy"] = 3
        for want in (6, 7, 8):
            err, _ = c.use_item("rare_candy")
            self.assertIsNone(err)
            self.assertEqual(c.level(), want)

    def test_branch_records_actual_evolve_level(self):
        c = self.comp(0.01)
        hatch(c, EEVEE, rate="medium")
        c.feed(c.phase_threshold())  # 가장 낮은 진화 레벨(15)에서 진화
        self.assertEqual(c.stage_levels()[0], 15)

    def test_ingest_total_counts_only_increase(self):
        c = self.comp()
        self.assertEqual(c.ingest_total(1000), [])  # 첫 호출은 기준점
        c.ingest_total(1500)
        self.assertEqual((c.s["earned"], c.egg["progress"]), (500, 500))
        c.ingest_total(200)  # 오래된 로그가 지워져 합계가 줄어도
        c.ingest_total(260)
        self.assertEqual(c.s["earned"], 560)  # 줄어든 지점부터 다시 센다

    def test_shop(self):
        c = self.comp(0.001)
        c.s["earned"] = c.price("mint") * 2
        self.assertIsNone(c.buy("mint", 2))
        self.assertEqual(c.wallet, 0)
        self.assertEqual(c.buy("mint"), "토큰이 부족해요.")


class ClaudeAppUsage(Tmp):
    class S:
        def __init__(self, code=0, hist=None):
            self.code, self.plan_history = code, hist or []

        def claude_tokens_between(self, a, b):
            return self.code

    def test_live_delta_reset_and_code_subtraction(self):
        c = self.comp()
        t = time.time()
        c.ingest_live(self.S(), {"org": "o", "t": t, "fh": 10, "fh_reset": t + 99, "sd": 1, "sd_reset": None})
        extra, _ = c.ingest_live(self.S(), {"org": "o", "t": t + 120, "fh": 13, "fh_reset": t + 99, "sd": 1,
                                            "sd_reset": None})
        self.assertEqual(extra, 3 * c.LIVE_K_DEFAULT)
        extra, _ = c.ingest_live(self.S(), {"org": "o", "t": t + 240, "fh": 2, "fh_reset": t + 20000, "sd": 1,
                                            "sd_reset": None})
        self.assertEqual(extra, 2 * c.LIVE_K_DEFAULT)  # 5시간 창이 리셋된 뒤 2%
        extra, _ = c.ingest_live(self.S(code=10 ** 9), {"org": "o", "t": t + 360, "fh": 5, "fh_reset": t + 20000,
                                                        "sd": 1, "sd_reset": None})
        self.assertEqual(extra, 0)  # 같은 시간 Claude Code 토큰으로 이미 셈 → 중복 없음

    def test_plan_history_first_run_is_baseline(self):
        c = self.comp()
        hist = [(1000.0, "o", 0, 10), (2000.0, "o", 0, 12)]
        self.assertEqual(c.ingest_plan_usage(self.S(hist=hist))[0], 0)
        hist.append((3000.0, "o", 0, 15))
        self.assertEqual(c.ingest_plan_usage(self.S(hist=hist))[0], 3 * 800_000)


class StateSafety(Tmp):
    def test_save_load_roundtrip_and_backup(self):
        c = self.comp()
        c.s["earned"] = 42
        c.save()
        c.s["earned"] = 43
        c.save()
        self.assertEqual(json.loads((self.dir / "state.bak").read_text(encoding="utf-8"))["earned"], 42)
        self.assertEqual(Companion(self.state).s["earned"], 43)

    def test_corrupt_file_recovers_from_backup(self):
        c = self.comp()
        hatch(c, CHARMANDER)
        c.save()
        c.save()  # state.bak 생성
        self.state.write_text("{ 망가진 파일", encoding="utf-8")
        c2 = Companion(self.state)
        self.assertEqual(c2.recovered_from, "backup")
        self.assertEqual(c2.active["base_id"], 4)
        self.assertTrue(list(self.dir.glob("state.corrupt-*.json")))

    def test_broken_active_is_set_aside_not_crash(self):
        c = self.comp()
        hatch(c, CHARMANDER)
        c.s["active"]["current_id"] = 999  # 트리에 없는 종
        c.save()
        c2 = Companion(self.state)
        self.assertIsNone(c2.active)
        self.assertIn("broken_active", c2.s)

    def test_first_run_is_not_a_recovery(self):
        self.assertIsNone(Companion(self.state).recovered_from)


class UsageLogs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, rows, mode="w", partial=""):
        p = self.dir / name
        with open(p, mode, encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.write(partial)
        return str(p)

    @staticmethod
    def claude(mid, out, ts="2026-10-22T01:00:00Z", model="claude-opus-5-5"):
        return {"type": "assistant", "timestamp": ts, "requestId": "r" + mid,
                "message": {"id": mid, "model": model,
                            "usage": {"input_tokens": 10, "output_tokens": out,
                                      "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000}}}

    def test_claude_dedup_keeps_largest_and_skips_synthetic(self):
        p = self.write("a.jsonl", [self.claude("m1", 5), self.claude("m1", 50), self.claude("m2", 1),
                                   self.claude("m3", 9, model="<synthetic>")])
        ents, off = parse_claude_file(p)
        self.assertEqual(sorted(e[3] for e in ents), [1111, 1160])
        self.assertEqual(off, os.path.getsize(p))

    def test_claude_incremental_with_partial_line(self):
        half = json.dumps(self.claude("m2", 7))
        p = self.write("b.jsonl", [self.claude("m1", 5)], partial=half[:20])  # 쓰는 중인 줄
        ents, off = parse_claude_file(p)
        self.assertEqual(len(ents), 1)
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(half[20:] + "\n")
            f.write(json.dumps(self.claude("m1", 99)) + "\n")  # 같은 메시지가 더 크게 다시 기록됨
        ents2, off2 = parse_claude_file(p, off, ents)
        full, _ = parse_claude_file(p)
        self.assertEqual(sorted(e[3] for e in ents2), sorted(e[3] for e in full))
        self.assertEqual(sorted(e[3] for e in ents2), [1117, 1209])

    def test_codex_turn_deltas_and_repeats(self):
        def tc(total, cum):
            return {"timestamp": "2026-10-22T01:00:00Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {
                        "total_token_usage": {"total_tokens": cum},
                        "last_token_usage": {"input_tokens": total, "cached_input_tokens": 0,
                                             "output_tokens": 0, "total_tokens": total}},
                        "rate_limits": {"primary": {"used_percent": 7.0, "window_minutes": 300}}}}
        p = self.write("c.jsonl", [{"type": "turn_context", "payload": {"model": "gpt-5.5"}},
                                   tc(100, 100), tc(100, 100), tc(50, 150)])
        sink = {}
        ents, off, st = parse_codex_file(p, sink)
        self.assertEqual([e[3] for e in ents], [100, 50])  # 반복 기록은 한 번만
        self.assertEqual(ents[0][2], "gpt-5.5")
        self.assertEqual(sink["data"]["primary"]["used_percent"], 7.0)

    def test_scanner_end_to_end(self):
        import poketokenbar.usage as U
        orig = U._claude_roots, U._codex_roots, U.read_plan_history
        proj = self.dir / "projects" / "x"
        proj.mkdir(parents=True)
        U._claude_roots = lambda: [self.dir / "projects"]
        U._codex_roots = lambda: []
        U.read_plan_history = lambda: []
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.write("projects/x/s.jsonl", [self.claude("m1", 5, ts=now)])
            sc = UsageScanner(self.dir / "cache.json")
            s1 = sc.scan()
            self.write("projects/x/s.jsonl", [self.claude("m2", 5, ts=now)], mode="a")
            s2 = UsageScanner(self.dir / "cache.json").scan()  # 디스크 캐시에서 이어 읽기
            self.assertEqual((s1.all_time_total, s2.all_time_total), (1115, 2230))
            self.assertEqual(s2.today_total, 2230)
        finally:
            U._claude_roots, U._codex_roots, U.read_plan_history = orig


class Weather(unittest.TestCase):
    def test_classify(self):
        cases = {(0, 3): "clear", (2, 3): "partly", (3, 3): "cloudy", (61, 3): "rain", (95, 3): "rain",
                 (73, 3): "snow", (45, 3): "fog", (0, 30): "windy", (61, 40): "rain"}
        for (code, wind), want in cases.items():
            self.assertEqual(weather.classify(code, wind), want, (code, wind))

    def test_stale_weather_gives_no_boost(self):
        w = {"kind": "rain", "city": "서울", "at": time.time() - 4 * 3600}
        self.assertEqual(weather.boost_types(w), [])
        w["at"] = time.time()
        self.assertEqual(weather.boost_types(w), ["water", "electric", "bug"])


if __name__ == "__main__":
    unittest.main()
