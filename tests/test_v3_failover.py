"""V-3 링크 두절 — 코어의 링크 판정 부분 (docs/spec/S7 §2 V-3).

여기서는 코어의 상태기계(bt_link_step)만 본다: 하트비트가 몇 번 빠지면 로컬 모드로 가고, 몇 번 돌아오면 되돌아오는가.
화면이 어떻게 보이는지(카드 유지, 선택지 정지, 대기 건수)는 시나리오 V2가 본다(tests/test_v6_scenario.py).

기기 프로그램이 부르는 순서 그대로 부른다(device/node.py): 틱을 알림 → 채널마다 하트비트를 보냈다고 알림 → 응답이 오면 알림.
"""
from __future__ import annotations

from host import btcore as bt
from tests.conftest import make_core


class Link:
    def __init__(self) -> None:
        self.core, self._b = make_core("device", field=False)
        self.state = bt.BtLink()
        self.seq = 0
        self.t = 0.0

    def tick(self, uhf: bool, wifi: bool) -> None:
        """1초 틱 하나. uhf / wifi = 그 채널의 응답이 오는가(50 ms 뒤)."""
        self.t += 1000.0
        self.core.link_step(self.state, self.t, bt.NET_TICK)
        self.seq += 1
        for ch, ok in ((bt.CH_UHF, uhf), (bt.CH_WIFI, wifi)):
            self.core.link_step(self.state, self.t, bt.NET_SENT, ch, self.seq)
            if ok:
                self.core.link_step(self.state, self.t + 50.0, bt.NET_ACK, ch, self.seq)

    @property
    def local(self) -> bool:
        return self.state.mode == bt.LINK_LOCAL


def test_v3_local_mode_entered():
    k = Link()
    cfg = k.core.cfg
    for _ in range(10):
        k.tick(True, True)
    assert not k.local
    t_cut = k.t + 1000.0                               # 응답을 받지 못한 첫 하트비트를 보낸 시각 — 여기서부터 잰다
    ticks = 0
    while not k.local and ticks < 30:
        k.tick(False, False)
        ticks += 1
    assert k.local
    limit_s = cfg.uhf.n_down / cfg.hb_hz + cfg.uhf.timeout_ms / 1000.0          # S4 §3: 5 / 1 Hz + 0.5 s = 5.5 s
    assert (k.t - t_cut) / 1000.0 <= limit_s
    assert ticks >= cfg.uhf.n_down                     # n_down번째 미응답이 확인되기 전에는 FULL이다

    # 미응답 사이에 응답이 하나 끼면 다시 센다
    k2 = Link()
    for _ in range(10):
        k2.tick(True, True)
    for _ in range(cfg.uhf.n_down - 1):
        k2.tick(False, False)
    k2.tick(True, True)
    for _ in range(cfg.uhf.n_down - 1):
        k2.tick(False, False)
    assert not k2.local


def test_v3_mode_table():
    """모드는 UHF만 따른다. Wi-Fi가 끊기거나 이어져도 모드는 바뀌지 않는다."""
    for uhf in (True, False):
        for wifi in (True, False):
            k = Link()
            for _ in range(10):
                k.tick(True, True)
            for _ in range(20):
                k.tick(uhf, wifi)
            assert k.local == (not uhf), (uhf, wifi)
            assert (k.state.wifi.state == bt.CHS_DOWN) == (not wifi)


def test_v3_recovery_hysteresis():
    k = Link()
    n_up = k.core.cfg.uhf.n_up
    for _ in range(10):
        k.tick(True, True)
    for _ in range(20):
        k.tick(False, False)
    assert k.local
    for _ in range(n_up - 1):                          # n_up보다 적게 돌아와서는 되돌아가지 않는다
        k.tick(True, True)
        assert k.local
    k.tick(True, True)
    k.tick(True, True)                                 # 응답은 다음 틱에 반영된다
    assert not k.local
