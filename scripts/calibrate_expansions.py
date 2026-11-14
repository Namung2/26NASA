"""확장 예산 보정 — 이 기기에서 "목표 응답 시간" 안에 탐색을 몇 칸까지 펼칠 수 있는지 재서 tiers.yaml의 max_expansions를 정한다 (S4 §4).

    python scripts/calibrate_expansions.py data/bundles/jezero_west_v1            # 재기만 한다
    python scripts/calibrate_expansions.py data/bundles/jezero_west_v1 --write    # config/tiers.yaml에 써 넣는다

왜 필요한가
    코어는 시계를 보지 않는다(같은 입력이면 같은 결과가 나와야 하므로). "2초 안에 답한다"는 약속은 시간 대신
    "탐색을 몇 칸까지 펼치는가"(max_expansions)로 지킨다. 그 수는 기기마다 다르니 대상 기기에서 한 번 재서 고정한다.

재는 법
    실제 번들에서 시작·목표 쌍을 여러 개 뽑아 예산을 넉넉히 주고 경로를 풀게 한다. 쌍마다 (펼친 칸 수 ÷ 걸린 시간)을 구해
    그 가운데 느린 쪽(아래 10 %)을 이 기기의 속도로 본다. max_expansions = time_budget_s × 속도 × 0.7 (여유 30 %).
    한번 적은 값은 고정이다 — 값이 바뀌면 같은 입력의 결과가 달라질 수 있으니, 제출물에는 잰 기기와 값을 함께 적는다.
    개발 노트북에서 잰 값은 목표 하드웨어(HPSC급)의 값이 아니다. 거기서는 그 기기에서 다시 잰다.
"""
from __future__ import annotations

import argparse
import platform
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from host import btcore as bt
from host import bundle as hb
from host import config as hc

TIERS, PARAMS = "config/tiers.yaml", "config/params.yaml"
BIG = 5_000_000          # 재는 동안 주는 넉넉한 예산


def measure(root: str, tier: str, level: str, n_pairs: int = 40) -> dict:
    b = hb.load(root, level)
    cfg = hc.load_config(TIERS, PARAMS, tier, b.meta)
    budget_s = float(__import__("yaml").safe_load(Path(TIERS).read_text())["tiers"][tier]["time_budget_s"])
    cfg.max_expansions = BIG
    core = bt.Core.create(cfg)
    b.attach(core, None)
    core.set_env(b.env_at(0.0))
    core.costmap_build()
    _cost, passable, res = core.costmap_view()
    h, w = passable.shape
    rng = np.random.default_rng(17)                              # 시험 입력을 뽑는 데만 쓴다(코어 안에는 난수가 없다)
    rates, times, exps = [], [], []
    tries = 0
    while len(rates) < n_pairs and tries < n_pairs * 20:
        tries += 1
        r0, c0, r1, c1 = rng.integers(0, h), rng.integers(0, w), rng.integers(0, h), rng.integers(0, w)
        if not (passable[r0, c0] and passable[r1, c1]):
            continue
        d = np.hypot(r1 - r0, c1 - c0) * res
        if d < 500 or d > min(5000, float(cfg.replan_radius_m)):
            continue                                             # 직선거리 0.5 km ~ 재계획 반경 (S7 V-2와 같은 범위)
        a, z = ((c0 + 0.5) * res, -(r0 + 0.5) * res), ((c1 + 0.5) * res, -(r1 + 0.5) * res)
        t0 = time.perf_counter()
        p = core.plan(a, z)
        dt = time.perf_counter() - t0
        if p.status < 0 or p.expansions < 1000:
            continue
        rates.append(p.expansions / dt)
        times.append(dt)
        exps.append(p.expansions)
    rate = float(np.percentile(rates, 10))                       # 느린 쪽 10 %
    return {"tier": tier, "pairs": len(rates), "rate_per_s": rate, "budget_s": budget_s, "max_expansions": int(budget_s * rate * 0.7),
            "p95_time_s": float(np.percentile(times, 95)), "max_exp_seen": int(max(exps)), "median_exp": int(np.median(exps))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--write", action="store_true", help="config/tiers.yaml의 max_expansions를 잰 값으로 바꾼다")
    args = ap.parse_args()
    machine = f"{platform.system()} {platform.machine()}, {platform.processor() or 'cpu'}, Python {platform.python_version()}"
    print(f"기기: {machine}")
    results = [measure(args.bundle, "device", "field"), measure(args.bundle, "rover", "rover")]
    for r in results:
        print(f"  {r['tier']:<6} 쌍 {r['pairs']}개: 초당 {r['rate_per_s']:,.0f}칸(느린 쪽 10 %) → max_expansions {r['max_expansions']:,} "
              f"(= {r['budget_s']:.0f} s × 속도 × 0.7) | 끝까지 풀 때 펼친 칸: 중앙값 {r['median_exp']:,}, 최대 {r['max_exp_seen']:,}, 걸린 시간 95 % {r['p95_time_s'] * 1000:.0f} ms")
    if args.write:
        text = Path(TIERS).read_text()
        for r in results:
            block = re.search(rf"(\n  {r['tier']}:.*?max_expansions: )(\d+)([^\n]*)", text, flags=re.DOTALL)
            text = text[:block.start(2)] + str(r["max_expansions"]) + f"          # {time.strftime('%Y-%m-%d')}에 이 기기에서 보정 (scripts/calibrate_expansions.py). 기기: {machine}" + text[block.end(3):]
        Path(TIERS).write_text(text)
        print(f"  → {TIERS} 에 써 넣었다")


if __name__ == "__main__":
    main()
