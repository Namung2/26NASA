"""C-10c — 받은 광물 지도와 지질 단위 지도를 과학 격자에 맞춘다.

과학 격자: 과학 가치 지도(mu0, var0, units)가 쓰는 격자. 경로 비용 격자(5 m, 2 m)와는 별개다.
    칸 크기는 받은 광물 래스터를 따른다(Parente 2021 지도는 36 m). 광물 지도는 칸마다 "종류"가 적힌 자료라
    잘게 나눠도 정보가 늘지 않는다. 광물 자료가 없으면 science.default_res_m(20 m)를 쓴다.
    원점은 다른 격자와 같이 활동 구역의 북서쪽 모서리 (0, 0)에 둔다.
    ※ S3a §1은 "광물 래스터의 칸 경계를 그대로 따른다"고 적었지만, 광물 지도도 기준 위도 0°의 투영이라
      로컬 투영으로 옮기면 칸이 정사각형이 아니게 된다(동서 34 m × 남북 36 m). 그래서 칸 크기만 따르고
      칸마다 가장 가까운 원본 칸의 종류를 가져온다.
"""
from __future__ import annotations

import struct
import warnings

import numpy as np
import pyogrio.raw
import rasterio
import rasterio.features
import rasterio.warp
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from . import register
from .dtm import Grid, local_crs

# Parente 2021 지도의 범례 (자료/mineral_parente2021/Jezero_readme.pdf 5쪽 "Key for Mineral Detections").
# (분류 번호, 열쇠, 이름, 확신 매우 높음일 때의 색, 높음/중간일 때의 색). 번호 0 = 분류 안 됨(검정) 또는 자료 범위 밖(흰색).
MINERAL_CLASSES = [
    (1, "olivine", "감람석", (255, 0, 0), (153, 0, 0)),
    (2, "mg_carbonate", "Mg-탄산염", (0, 255, 0), (0, 153, 0)),
    (3, "fe_mg_smectite", "Fe/Mg-스멕타이트", (0, 255, 255), (0, 153, 153)),
    (4, "olivine_smectite", "감람석 + 스멕타이트", (255, 128, 114), (153, 77, 68)),
    (5, "olv_smect_2p2", "감람석·스멕타이트 + 2.2 µm", (128, 128, 0), (77, 77, 0)),
    (6, "carb_2p2", "탄산염 + 2.2 µm", (255, 215, 0), (153, 129, 0)),
    (7, "hcp", "고칼슘 휘석", (255, 128, 0), (153, 77, 0)),
    (8, "lcp", "저칼슘 휘석", (218, 165, 32), (130, 99, 19)),
    (9, "kaolinite", "카올리나이트", (139, 69, 19), (83, 41, 11)),
    (10, "mg_smectite_2", "Mg-스멕타이트 2", (0, 0, 255), (0, 0, 153)),
]
MINERAL_KEYS = {num: key for num, key, _, _, _ in MINERAL_CLASSES}

# 지질 단위 기호 → 번들 units.u8의 번호. 0 = 단위 없음(지도 범위 밖). 순서는 SIM 3464의 범례 순.
UNIT_CODES = {"NHjf2": 1, "NHjf1": 2, "Njf": 3, "Nle": 4, "Hnpf": 5, "Nnp2": 6, "Nnp1": 7,
              "Aeb": 8, "su": 9, "Nrb": 10, "Nue": 11, "cr": 12, "ce": 13, "ci": 14}


def science_grid(site: dict, res_m: float) -> Grid:
    """활동 구역을 덮는 과학 격자. 한 변이 칸 크기로 나누어떨어지지 않으면 한 칸 더 잡는다."""
    n = int(np.ceil(2.0 * float(site["aoi"]["half_size_m"]) / res_m))
    return Grid(res_m=float(res_m), h=n, w=n)


def read_mineral_classes(site: dict):
    """광물 지도를 원본 격자 그대로 읽어 (분류 번호 u8, 확신 u8, 변환, 좌표계)로 돌려준다.

    분류 번호는 MINERAL_CLASSES의 1~10, 0 = 분류 안 됨·범위 밖. 확신은 2 = 매우 높음, 1 = 높음/중간, 0 = 없음.
    원본은 색으로 분류를 적은 그림(RGB)인데, 여러 장면을 이어 붙이는 과정에서 색이 조금씩 섞여 범례 색과 딱 맞지 않는
    칸이 많다(REFERENCE §6.1). 그래서 칸마다 가장 가까운 범례 색으로 되돌린다. 검정·흰색에 가장 가까우면 0이다.
    """
    palette = [((0, 0, 0), 0, 0), ((255, 255, 255), 0, 0)]
    for num, _key, _name, bold, subdued in MINERAL_CLASSES:
        palette += [(bold, num, 2), (subdued, num, 1)]
    colors = np.array([p[0] for p in palette], dtype=np.int32)                    # [색 수, 3]
    with rasterio.open(site["products"]["minerals"]["path"]) as src:
        rgb = src.read([1, 2, 3]).astype(np.int32)                                # [3, H, W]
        flat = rgb.reshape(3, -1).T                                               # [칸 수, 3]
        nearest = np.argmin(((flat[:, None, :] - colors[None, :, :]) ** 2).sum(-1), axis=1)
        cls = np.array([p[1] for p in palette], dtype=np.uint8)[nearest].reshape(rgb.shape[1:])
        conf = np.array([p[2] for p in palette], dtype=np.uint8)[nearest].reshape(rgb.shape[1:])
        return cls, conf, src.transform, src.crs


def load_minerals(site: dict, grid: Grid, shift_m: tuple[float, float] = (0.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    """광물 지도를 과학 격자의 (분류 번호 u8, 확신 u8)로 만든다.

    shift_m = (동, 북) — 지도를 이만큼 옮겨 기준에 맞춘다(register.register_class_map이 잰 값). 기본은 옮기지 않음.
    """
    cls, conf, src_transform, src_crs = read_mineral_classes(site)
    # 격자 칸 p가 원본의 (p − 옮김) 자리 값을 갖게 한다 = 지도 내용이 (+옮김)만큼 움직인다
    dst_transform = Affine.translation(-shift_m[0], -shift_m[1]) * grid.transform
    out_cls = np.zeros((grid.h, grid.w), dtype=np.uint8)
    out_conf = np.zeros((grid.h, grid.w), dtype=np.uint8)
    for a, b in ((cls, out_cls), (conf, out_conf)):
        # 종류(번호)라서 평균 내지 않고 가장 가까운 칸을 가져온다.
        # 주의: nodata를 0으로 지정하면 안 된다 — GDAL이 "값 없음과 겹치지 않게" 진짜 0(분류 안 됨)을 1(감람석)로
        # 바꿔 쓴다(2026-11-14에 실제로 겪음: 감람석이 16 %가 아니라 43 %로 나왔다). 지정하지 않으면 그대로 옮겨진다.
        reproject(a, b, src_transform=src_transform, src_crs=src_crs, src_nodata=None,
                  dst_transform=dst_transform, dst_crs=local_crs(site), dst_nodata=None, resampling=Resampling.nearest)
    return out_cls, out_conf


def _wkb_polygons(buf: bytes) -> list[list[list[list[float]]]]:
    """WKB(다각형, 다중 다각형)를 [다각형[고리[점[x, y]]]]로 푼다.

    shapely 없이 지오데이터베이스의 도형을 읽으려고 둔 작은 해석기다. z값이 있으면 버린다.
    """
    pos = 0

    def take(fmt: str):
        nonlocal pos
        v = struct.unpack_from(fmt, buf, pos)
        pos += struct.calcsize(fmt)
        return v

    def geometry() -> list:
        nonlocal pos
        order = "<" if take("<B")[0] == 1 else ">"
        code = take(order + "I")[0]
        kind = code % 1000
        dims = 3 if (code // 1000) in (1, 3) or (code & 0x80000000) else 2
        if kind == 3:                                         # 다각형
            rings = []
            for _ in range(take(order + "I")[0]):
                n = take(order + "I")[0]
                pts = np.frombuffer(buf, dtype=order + "f8", count=n * dims, offset=pos).reshape(n, dims)
                pos += n * dims * 8
                rings.append(pts[:, :2].tolist())
            return [rings]
        if kind == 6:                                         # 다중 다각형
            out = []
            for _ in range(take(order + "I")[0]):
                out += geometry()
            return out
        raise ValueError(f"다루지 않는 도형 종류(WKB {code})")

    return geometry()


def unit_rings(site: dict, fit: dict | None) -> list:
    """지질 단위 폴리곤의 고리를 로컬 좌표로 낸다(확인용 그림에 쓴다). fit을 주면 정합한 자리, None이면 원래 자리."""
    geo = site["products"]["geology"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        meta, _fids, geoms, _fields = pyogrio.raw.read(geo["path"], layer=geo["layer"], columns=["symbol"])
    half2 = 2.0 * float(site["aoi"]["half_size_m"])
    out = []
    for wkb in geoms:
        if wkb is None:
            continue
        for rings in _wkb_polygons(bytes(wkb)):
            g = rasterio.warp.transform_geom(meta["crs"], local_crs(site), {"type": "Polygon", "coordinates": rings})
            for ring in g["coordinates"]:
                pts = np.asarray(ring, dtype=np.float64)
                x, y = register.to_reference(fit, pts[:, 0], pts[:, 1])
                if x.max() < 0 or x.min() > half2 or y.min() > 0 or y.max() < -half2:
                    continue                                  # 구역 밖
                out.append(np.c_[x, y].tolist())
    return out


def load_units(site: dict, grid: Grid, fit: dict | None) -> np.ndarray:
    """지질 단위 폴리곤을 읽어 격자의 단위 번호(u8, UNIT_CODES)로 굽는다.

    폴리곤은 횡축 메르카토르(중앙경선 77.5°E)로 돼 있다 → 로컬 투영으로 옮긴 다음, 정합 결과(fit —
    register.register_images가 낸 것)로 점마다 옮겨 고도 자료의 기준에 맞춘다. fit이 None이면 옮기지 않는다.
    """
    geo = site["products"]["geology"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                       # 조각이 많은 다각형에 대한 GDAL의 안내
        meta, _fids, geoms, fields = pyogrio.raw.read(geo["path"], layer=geo["layer"], columns=["symbol"])
    symbols = fields[list(meta["fields"]).index("symbol")]
    dst_crs = local_crs(site)
    shapes = []
    for wkb, sym in zip(geoms, symbols):
        code = UNIT_CODES.get(str(sym))
        if code is None or wkb is None:
            continue
        for rings in _wkb_polygons(bytes(wkb)):
            g = rasterio.warp.transform_geom(meta["crs"], dst_crs, {"type": "Polygon", "coordinates": rings})
            moved = []
            for ring in g["coordinates"]:
                pts = np.asarray(ring, dtype=np.float64)
                x, y = register.to_reference(fit, pts[:, 0], pts[:, 1])       # 지도의 좌표 → 기준 좌표
                moved.append(np.c_[x, y].tolist())
            shapes.append(({"type": "Polygon", "coordinates": moved}, code))
    return rasterio.features.rasterize(shapes, out_shape=(grid.h, grid.w), transform=grid.transform, fill=0, dtype="uint8")
