"""V-7 결정론 (docs/spec/S7 §2 V-7).

같은 입력이면 같은 결과가 나와야 한다. 코어에는 시계도 난수도 없고, 이벤트는 들어온 순서가 아니라 (lts, node)로 줄을 세운다.
그래서 기기와 로버가 같은 이벤트를 다른 순서로 받아도 같은 지도가 되고, 로그를 여러 번 합쳐도 결과가 같다.
시나리오를 두 번 돌려 같은 기록이 나오는지는 V-6의 rerun_identical이 본다(tests/test_v6_scenario.py).
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

import numpy as np
import pytest

from host import btcore as bt
from host import convert as cv
from tests.conftest import make_core
from tests.fixtures import mini_bundle as mb
from tests.scene import ANCHOR, Scene

ROOT = Path(__file__).resolve().parents[1]


def _digest(s: Scene, d: bt.BtDecision) -> int:
    return int(s.core.lib.bt_decision_digest(d))


def _scene_with_events() -> tuple[Scene, object]:
    s = Scene()
    s.obs()
    s.obs((ANCHOR[0], ANCHOR[1] - 40.0), found=False, confirmed=True, ts=3550.0)
    h = s.hyp()
    return s, h


def test_v7_decide_twice_identical():
    s, h = _scene_with_events()
    d1 = s.decide(cause="hyp", event=h)
    first = (_digest(s, d1), [o.digest for o in s.options(d1)], d1.inputs_digest)
    s.core.decision_close(d1.seq)
    d2 = s.decide(cause="hyp", event=h)
    assert (_digest(s, d2), [o.digest for o in s.options(d2)], d2.inputs_digest) == first
    assert d1.n_options >= 2


def test_v7_fresh_instance_identical():
    got = []
    for _ in range(3):
        s, h = _scene_with_events()                    # 같은 설정·번들·로그로 인스턴스를 새로 만든다
        d = s.decide(cause="hyp", event=h)
        got.append((s.core.config_digest(), s.core.log_digest(), s.core.science_digest(), _digest(s, d)))
    assert got[0] == got[1] == got[2]                  # 숨은 상태가 없다


def test_v7_plan_twice_identical(tier):
    core, _b = make_core(tier)
    for goal in mb.POIS.values():
        a, b = core.plan(mb.PARK, goal), core.plan(mb.PARK, goal)
        assert a.status == b.status and np.array_equal(a.cells, b.cells)
        assert (a.cost, a.expansions, a.length_m, a.res_m) == (b.cost, b.expansions, b.length_m, b.res_m)
    other, _b2 = make_core(tier)                        # 다른 인스턴스에서도 같다
    a, b = core.plan(mb.PARK, mb.POIS["P3"]), other.plan(mb.PARK, mb.POIS["P3"])
    assert np.array_equal(a.cells, b.cells) and a.cost == b.cost and a.expansions == b.expansions


def _thirty_events() -> list[bt.BtEvent]:
    """두 노드(기기, 로버)가 만든 이벤트 30개: 관측, 가설(규칙 네 가지), 주의 흔적, 철회."""
    rng = random.Random(7)
    out = []
    for tier in ("device", "rover"):
        s = Scene(tier)
        hyps = []
        for i in range(15):
            xy = (ANCHOR[0] + rng.uniform(-40, 40), ANCHOR[1] + rng.uniform(-60, 60))
            ts = 3000.0 + 20.0 * i
            if i % 5 == 1:
                hyps.append(s.hyp(bt.RULES[(i // 5) % 4], rng.choice((0.0, 90.0, 180.0, 270.0)), rng.choice((100.0, 300.0)), rng.choice((0.17, 0.5, 0.83)), xy=xy, ts=ts))
            elif i == 13:
                s.withdraw(hyps[0], ts=ts)
            elif i % 5 == 3:
                from host import wire as w
                cv.append_event(s.core, s.table, s.node, "trace", xy, ts, w.TracePayload(kind=rng.choice(("photo", "mention"))))
            else:
                s.obs(xy, found=rng.random() < 0.6, confirmed=rng.random() < 0.5, ts=ts)
        out += [cv.to_bt_event(e) for e in s.table.ordered()]
    assert len(out) == 30
    return out


def test_v7_event_order_invariance():
    events = _thirty_events()
    rng = random.Random(17)
    digests = set()
    for _ in range(20):
        rng.shuffle(events)
        s = Scene()
        assert s.core.log_merge(events) == 30
        s.core.science_update(4000.0)
        digests.add((s.core.log_digest(), s.core.science_digest()))
    assert len(digests) == 1


def test_v7_merge_properties():
    events = _thirty_events()
    a = [e for e in events if e.node == bt.NODE["suit-A"]]        # 기기 로그
    b = [e for e in events if e.node == bt.NODE["rover"]]         # 로버 로그
    c = a[:6]                                                     # 기기 로그의 앞부분

    def merged(*parts) -> int:
        s = Scene()
        for p in parts:
            s.core.log_merge(p)
        return s.core.log_digest()

    assert merged(a) == merged(a, a) == merged(a, c)             # 멱등: 이미 있는 것을 또 합쳐도 같다
    assert merged(a, b) == merged(b, a)                           # 교환: 합치는 순서와 무관
    assert merged(a + b, c) == merged(a, b + c) == merged(c, b, a)   # 결합
    s = Scene()
    assert s.core.log_merge(a) == len(a) and s.core.log_merge(a) == 0   # 두 번째는 새로 들어온 것이 없다


def test_v7_core_never_reads_clock():
    """코어 라이브러리가 바깥에서 가져다 쓰는 함수에 시계·난수가 없다."""
    lib = next((p for p in (ROOT / "build/native/libbtcore.dylib", ROOT / "build/native/libbtcore.so") if p.exists()), None)
    if lib is None:
        pytest.skip("코어 라이브러리가 없다")
    syms = subprocess.run(["nm", "-u", str(lib)], capture_output=True, text=True, check=True).stdout.split()
    names = {s.lstrip("_").split("@")[0] for s in syms}
    banned = {"time", "clock", "clock_gettime", "gettimeofday", "mach_absolute_time", "localtime", "gmtime",
              "rand", "srand", "random", "srandom", "arc4random", "arc4random_uniform", "getentropy", "drand48"}
    assert not (names & banned), names & banned
    assert not any("chrono" in s or "random_device" in s for s in syms)
