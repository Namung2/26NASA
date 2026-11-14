"""C-10a — 고도 자료(DTM)를 활동 구역의 로컬 격자로 다시 놓는다.

로컬 좌표 (이 프로젝트의 좌표 정본, docs/spec/S2 §1)
    미터, (동쪽 x, 북쪽 y). 원점 (0, 0)은 활동 구역의 북서쪽 모서리다.
    그래서 구역 안의 x는 0 ~ +한 변, y는 0 ~ -(한 변)이다 (북쪽이 +라서 남쪽으로 갈수록 음수).
    격자 칸은 (row, col), row 0이 북쪽. 칸 찾기:  col = floor(x / res),  row = floor(-y / res)
    코어(core/include/btcore.h)도 같은 약속을 쓴다 — bt_grid_geom.origin = (0, 0).

왜 다시 투영하나
    받은 고도 자료(USGS HiRISE DTM)는 기준 위도가 0°인 정거원통 도법이다. 위도 18°에서는 동서 방향이 실제보다
    1 / cos(18.46°) = 1.054배 늘어나 있다. 그대로 쓰면 동서 거리가 5.4 % 길게 잡히고 경사도 틀린다.
    구역 중심을 기준 위도로 한 정거원통으로 다시 놓으면 구역 안에서는 1 m가 실제 1 m다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject

MARS_RADIUS_M = 3396190.0   # Mars 2000 구. 받은 자료 전부가 이 반지름을 쓴다


@dataclass(frozen=True)
class Grid:
    """로컬 격자 한 장. 원점은 언제나 활동 구역의 북서쪽 모서리 (0, 0)."""
    res_m: float
    h: int
    w: int

    @property
    def transform(self) -> Affine:
        """rasterio가 쓰는 칸 → 좌표 변환. 좌상단이 (0, 0), 아래로 갈수록 y가 준다."""
        return from_origin(0.0, 0.0, self.res_m, self.res_m)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """좌표 → (row, col). 격자 밖이어도 그대로 계산해 돌려준다(부른 쪽이 범위를 본다)."""
        return int(math.floor(-y / self.res_m)), int(math.floor(x / self.res_m))

    def center_of(self, row: int, col: int) -> tuple[float, float]:
        """칸 중심의 좌표."""
        return (col + 0.5) * self.res_m, -(row + 0.5) * self.res_m


def local_crs(site: dict) -> str:
    """활동 구역의 로컬 투영을 PROJ 문자열로 낸다.

    구역 중심이 (half, -half)에 오도록 x_0, y_0를 준다 → 이 투영의 좌표가 곧 로컬 좌표다.
    """
    aoi = site["aoi"]
    half = float(aoi["half_size_m"])
    return (f"+proj=eqc +lat_ts={aoi['center_lat_n']} +lat_0={aoi['center_lat_n']} +lon_0={aoi['center_lon_e']} "
            f"+x_0={half} +y_0={-half} +R={MARS_RADIUS_M} +units=m +no_defs")


def lonlat_to_xy(site: dict, lon_e: float, lat_n: float) -> tuple[float, float]:
    """경도·위도(°) → 로컬 좌표(m). 정거원통이라 식이 단순하다."""
    aoi = site["aoi"]
    half = float(aoi["half_size_m"])
    k = math.pi / 180.0 * MARS_RADIUS_M
    x = (lon_e - aoi["center_lon_e"]) * k * math.cos(math.radians(aoi["center_lat_n"])) + half
    y = (lat_n - aoi["center_lat_n"]) * k - half
    return x, y


def grid_for(site: dict, res_m: float) -> Grid:
    """활동 구역 전체를 덮는 격자."""
    n = int(round(2.0 * float(site["aoi"]["half_size_m"]) / res_m))
    return Grid(res_m=float(res_m), h=n, w=n)


def load_and_grid(site: dict, res_m: float) -> tuple[np.ndarray, Grid]:
    """고도 자료를 읽어 로컬 격자(res_m)로 다시 놓는다.

    돌려주는 배열은 float32 고도(m). 값이 없는 칸은 NaN이다 — 코어는 NaN 칸을 통과불가로 본다.
    여러 원본 칸을 한 칸으로 줄일 때는 평균을 쓴다(1 m → 2 m, 5 m).
    """
    grid = grid_for(site, res_m)
    dst = np.full((grid.h, grid.w), np.nan, dtype=np.float32)
    with rasterio.open(site["products"]["dtm"]["path"]) as src:
        reproject(
            rasterio.band(src, 1), dst,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
            dst_transform=grid.transform, dst_crs=local_crs(site), dst_nodata=np.nan,
            resampling=Resampling.average,
        )
    return dst, grid
