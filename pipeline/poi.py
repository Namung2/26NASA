"""C-10f — 지점(POI) 목록을 만든다.

지금은 config/site.yaml에 손으로 적은 지점을 그대로 옮기고, 그 자리의 바탕 지도 값을 붙인다.
배치 규칙(S5 §8: 로버에서의 거리, 지점 사이 간격, 통과 가능 여부)으로 자동 배치하는 것은 scripts/place_scenario.py의 일이다.
접근 비용(로버에서 걷는 시간)은 번들에 넣지 않는다 — 로버가 선 뒤 귀환 필드에서 읽어 채운다(S3b §2).
"""
from __future__ import annotations

import math

import numpy as np

from .dtm import Grid, lonlat_to_xy


def site_xy(site: dict, item: dict) -> tuple[float, float]:
    """site.yaml의 항목에서 로컬 좌표를 얻는다. xy가 있으면 그것을, 없으면 lon_e·lat_n을 바꿔서."""
    if "xy" in item:
        return float(item["xy"][0]), float(item["xy"][1])
    return lonlat_to_xy(site, float(item["lon_e"]), float(item["lat_n"]))


def build_pois(site: dict, mu0: np.ndarray, var0: np.ndarray, sgrid: Grid) -> list[dict]:
    """번들 메타의 pois 목록(S2 §6의 POI 모양)."""
    out = []
    for p in site.get("pois", []):
        x, y = site_xy(site, p)
        r, c = sgrid.cell_of(x, y)
        inside = 0 <= r < sgrid.h and 0 <= c < sgrid.w
        mu = float(mu0[r, c]) if inside else math.nan
        var = float(var0[r, c]) if inside else math.nan
        out.append({
            "id": p["id"], "name": p.get("name", p["id"]), "xy": [round(x, 1), round(y, 1)], "kind": p.get("kind", "feature"),
            "value_mu": None if math.isnan(mu) else round(mu, 4), "value_var": None if math.isnan(var) else round(var, 4),
            "access_cost_min": None,
            "source": {"source": "config/site.yaml", "product_id": "Provisional placement", "resolution_m": None, "acquired": None,
                       "license": "", "url": None, "note": "Hand-placed site. The value is read from the prior map (a relative index, not a calibrated probability)"},
            "photos": [],
        })
    return out
