"""한 틱의 입력 — 센서 프레임 (docs/spec/S2 §9.1).

기기 프로그램은 틱마다 이것 하나를 받는다. 실제에서는 우주복의 센서·항법 시스템이 주는 값이고,
데모에서는 시뮬레이터가 만든다. 위치와 오차 반경은 "주어진 입력"이다 — 이 도구는 위치를 추정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SensorFrame:
    t: float                    # EVA 경과 초
    lmst: str                   # 지방 평균 태양시 "hh:mm"
    pos: tuple[float, float]    # 위치 (m)
    sigma: float                # 오차 반경 (m)
    heading_deg: float
    dose_cum_uSv: float         # 누적 선량 (시뮬에서는 SuitModel이 센다)
    # 환경
    tau_dust: float
    t_air_c: float | None
    dose_rate: float            # µSv/h
    spe: bool
    # 태양 (번들의 태양 표에서)
    sun_elev: float
    sun_az: float
    t_sunset_s: float
    shadow_bin: int
