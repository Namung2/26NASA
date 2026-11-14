"""시험용 작은 합성 번들 (docs/spec/S7 §1의 mini_bundle).

실제 자료 없이 코어 시험이 돌도록, 수식으로 만든 320 m × 320 m 지형을 번들과 같은 모양(host.bundle.Bundle)으로 메모리에 만든다.
파일은 쓰지 않는다. 기기 수준은 5 m 칸(64 × 64), 로버 수준은 2 m 칸(160 × 160)이고 둘 다 같은 수식에서 나온다.

지형 (좌표: x 동쪽 0~320, y 북쪽 0~−320. 원점 = 북서쪽 모서리 — 실제 번들과 같은 약속)
  - 완만한 바닥: 동쪽으로 조금 오르고 낮은 굴곡이 있다 (경사 수 °)
  - 벽: x = 160을 따라 남북으로 선 능선. 양쪽 비탈이 통과 한계(20°)를 넘는다. y = −200 근처에 틈이 하나 있다
  - 갇힌 방: (260, −60)을 둘러싼 고리 모양 능선. 안쪽은 평탄하지만 밖에서 들어갈 수 없다 (도달 불가 시험용)
  - 로버 주차점 park1 = (40, −160) (벽의 서쪽), 지점 P1 (90, −90) 서쪽, P2 (240, −200) · P3 (250, −285) 동쪽 (틈을 지나야 한다)
  - 링크 지도: 벽의 서쪽만 링크가 된다 (동쪽에 있으면 "통신 두절"로 잡힌다)
  - 지질 단위 둘: 서쪽 = 1, 동쪽 = 2. 바탕 지도 mu0 = 0.2 / 0.6, var0 = 0.05 (10 m 칸)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from host import bundle as hb

EXTENT_M = 320.0
PARK = (40.0, -160.0)
POIS = {"P1": (90.0, -90.0), "P2": (240.0, -200.0), "P3": (250.0, -285.0)}
ROOM = (260.0, -60.0)            # 갇힌 방의 가운데 — 밖에서 닿을 수 없다
WALL_X, GAP_Y = 160.0, -200.0
SCI_RES = 10.0


def elevation(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """지형의 높이 (m). x, y는 같은 모양의 배열."""
    base = 0.02 * x + 1.5 * np.sin(x / 40.0) * np.cos(y / 50.0)
    gap = 1.0 - np.exp(-(((y - GAP_Y) / 18.0) ** 4))                      # 틈에서 0, 그 밖에서 1
    wall = 12.0 * np.exp(-((x - WALL_X) ** 2) / (2 * 6.0 ** 2)) * gap
    d = np.hypot(x - ROOM[0], y - ROOM[1])
    ring = 12.0 * np.exp(-((d - 32.0) ** 2) / (2 * 5.0 ** 2))
    return base + wall + ring


def _grid(res: float) -> tuple[np.ndarray, np.ndarray, int]:
    n = round(EXTENT_M / res)
    c = (np.arange(n) + 0.5) * res
    x, y = np.meshgrid(c, -c)                                             # 행 0 = 북쪽
    return x, y, n


def _layer(name: str, res: float, n: int, dtype: str, **extra) -> dict:
    return {"name": name, "file": "", "dtype": dtype, "res_m": res, "shape": [n, n], "bins": None, "scale": 1.0, "offset": 0.0, **extra}


def make(level: str = "field") -> hb.Bundle:
    """level = "field"(5 m, 기기용) 또는 "rover"(2 m, 로버용)."""
    res = 5.0 if level == "field" else 2.0
    x, y, n = _grid(res)
    z = elevation(x, y).astype(np.float32)
    gy, gx = np.gradient(z.astype(np.float64), res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    rough = np.full((n, n), 0.05, dtype=np.float32)
    shadow = np.zeros((2, n, n), dtype=bool)
    shadow[1] = (x > 200) & (y < -240)                                    # 둘째 시간 구간에만 남동쪽에 그림자
    los = x < WALL_X                                                      # 벽의 서쪽만 링크가 된다

    sx, _sy, sn = _grid(SCI_RES)
    units = np.where(sx < WALL_X, 1, 2).astype(np.uint8)
    mu0 = np.where(units == 1, 0.2, 0.6).astype(np.float32)
    var0 = np.full((sn, sn), 0.05, dtype=np.float32)

    layers = {
        "slope": (slope, _layer("slope", res, n, "f32")),
        "elev": (z, _layer("elev", res, n, "f32")),
        "roughness": (rough, _layer("roughness", res, n, "f32")),
        "shadow": (np.packbits(shadow.reshape(-1)), _layer("shadow", res, n, "bits", bins=2)),
        "los_park1": (np.packbits(los.reshape(-1)), _layer("los_park1", res, n, "bits")),
        "mu0": (mu0, _layer("mu0", SCI_RES, sn, "f32")),
        "var0": (var0, _layer("var0", SCI_RES, sn, "f32")),
        "units": (units, _layer("units", SCI_RES, sn, "u8")),
    }
    meta = {
        "bundle_id": "mini_v1", "extent_m": [EXTENT_M, EXTENT_M], "levels_m": [5.0, 2.0], "science_res_m": SCI_RES,
        "layers": [lay for _, lay in layers.values()], "grade_bins": [0.3, 0.5],
        "rover_parks": [{"id": "park1", "xy": list(PARK)}],
        "pois": [{"id": k, "name": k, "xy": list(v)} for k, v in POIS.items()],
        "params": [], "missing_layers": ["tiles", "photos"], "unit_codes": {"west": 1, "east": 2},
    }
    return hb.Bundle(root=Path("."), meta=meta, level=level, res_m=res, layers=layers)


def passable_mask(b: hb.Bundle, theta_max_deg: float) -> np.ndarray:
    """그 수준의 원본 격자에서 걸을 수 있는 칸 (코어를 거치지 않고 레이어에서 바로)."""
    return np.isfinite(b.layers["slope"][0]) & (b.layers["slope"][0] <= theta_max_deg)
