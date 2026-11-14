"""환경 트리거 — 먼지 (S3a §6.1).

먼지 광학 두께가 경고 임계를 넘으면 로버가 선택지를 다시 낸다. 다만 임계 근처에서 잠깐 넘었다 내려오는 것으로는 묻지 않는다:
임계 위에 env.dust_hold_s(측정 간격, 300초) 동안 이어져야 "넘었다"고 본다. 화면의 경고 표시는 기다리지 않고 바로 뜬다(기기 쪽 판정).
"""
from __future__ import annotations

from host import btcore as bt
from tests.conftest import default_env, make_core, state_at
from tests.fixtures import mini_bundle as mb


class Dust:
    def __init__(self, tau0: float) -> None:
        self.core, self._b = make_core("rover")
        self.warn, self.hold = self.core.cfg.dust_tau_warn, self.core.cfg.dust_hold_s
        self.t = 3600.0
        self.fired: list[float] = []
        self.step(tau0, 0.0)

    def step(self, tau: float, dt: float = 60.0) -> bool:
        """dt초 뒤 먼지 값이 tau일 때 한 틱. 먼지 트리거가 나왔으면 True."""
        self.t += dt
        env = default_env()
        env.tau_dust = tau
        self.core.set_env(env)
        trs = self.core.triggers(state_at(mb.POIS["P1"], self.t), bt.BtTriggerIn())
        hit = any(t.kind == bt.TRIG_ENV and bt.CAUSES[t.cause_kind] == "dust" for t in trs)
        if hit:
            self.fired.append(self.t)
        return hit


def test_dust_blip_does_not_ask():
    d = Dust(0.30)
    assert d.hold == 300.0 and 0 < d.warn < 1
    d.step(d.warn - 0.003)
    assert not d.step(d.warn + 0.001)                  # 임계를 살짝 넘었다
    assert not d.step(d.warn - 0.006)                  # 1분 뒤 다시 아래 → 묻지 않는다
    for _ in range(20):
        assert not d.step(d.warn - 0.05)
    assert d.fired == []


def test_dust_sustained_asks_once():
    d = Dust(0.30)
    t_cross = None
    for i in range(30):                                # 임계 위에 계속 머문다
        hit = d.step(d.warn + 0.02)
        if t_cross is None:
            t_cross = d.t
        if hit:
            assert d.t - t_cross >= d.hold             # 넘은 지 hold가 지난 뒤에
            assert d.t - t_cross <= d.hold + 60.0      # 그 틱에 바로
            assert i >= 1
    assert len(d.fired) == 1                           # 한 번만 묻는다
    # 아래로 내려갔다가 다시 넘어 이어지면 또 묻는다
    for _ in range(3):
        d.step(d.warn - 0.1)
    for _ in range(10):
        d.step(d.warn + 0.02)
    assert len(d.fired) == 2


def test_dust_above_from_start_does_not_ask():
    d = Dust(0.9)                                      # 처음부터 임계 위: 바뀐 것이 없다
    for _ in range(15):
        d.step(0.9)
    assert d.fired == []
