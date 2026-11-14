"""번들 읽기 — 파일을 메모리에 올려 코어에 연결한다.

코어는 파일을 열지 않는다. 이 모듈이 번들(형식: pipeline/bundle.py 머리말)을 읽어 numpy 배열로 만들고,
attach()가 그 배열들을 코어에 넘긴다(bt_set_layer — 복사 없이 포인터만).

    b = load("data/bundles/jezero_west_v1", level="field")   # 기기: field/의 5 m 레이어
    b = load("data/bundles/jezero_west_v1", level="rover")   # 로버: rover/의 2 m 레이어 (과학 레이어는 field/의 것을 같이 쓴다)
    b.attach(core, park_id="park1")
    core.set_env(b.env_at(t_eva_s))

읽는 쪽은 meta.json만 믿는다 — 파일 이름·격자·형식을 여기서 따로 가정하지 않는다.
"""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import btcore as bt


@dataclass
class Bundle:
    root: Path
    meta: dict
    level: str                                   # "field" 또는 "rover"
    res_m: float                                 # 이 수준의 비용 레이어 칸 크기
    layers: dict = field(default_factory=dict)   # 이름 → (배열, 메타의 레이어 항목)
    sun: dict = field(default_factory=dict)      # sun_table.json
    dose_rate_uSv_h: float = 27.9                # 환경 자료가 없을 때 쓰는 평상시 선량률

    def attach(self, core: bt.Core, park_id: str | None = None) -> list[str]:
        """번들의 레이어를 코어에 연결한다. 연결한 레이어 이름을 돌려준다.

        park_id를 주면 그 주차점의 가시선 마스크도 연결한다(없으면 통신 두절 시간은 0으로 나온다).
        """
        done = []
        for name in ("slope", "elev", "roughness", "shadow", "mu0", "var0", "units"):
            if name not in self.layers:
                continue
            a, lay = self.layers[name]
            core.set_layer(name, a, lay["res_m"], tuple(lay["shape"]), bits=(lay["dtype"] == "bits"), planes=int(lay.get("bins") or 1),
                           scale=float(lay.get("scale", 1.0)), offset=float(lay.get("offset", 0.0)))
            done.append(name)
        if park_id and f"los_{park_id}" in self.layers:
            a, lay = self.layers[f"los_{park_id}"]
            core.set_layer("los", a, lay["res_m"], tuple(lay["shape"]), bits=True)
            done.append("los")
        return done

    def sun_at(self, t_eva_s: float) -> dict:
        """EVA 경과 초 → 그 시각의 태양 표 한 줄 {elev_deg, az_deg, shadow_bin, t_sunset_s}. 표 밖이면 가까운 끝 줄."""
        t = self.sun["t_eva_s"]
        i = min(len(t) - 1, max(0, bisect.bisect_left(t, t_eva_s)))
        return {"elev_deg": self.sun["elev_deg"][i], "az_deg": self.sun["az_deg"][i], "shadow_bin": self.sun["shadow_bin"][i],
                "t_sunset_s": self.sun["t_sunset_s"], "lmst_min": self.sun["lmst_min"][i]}

    def env_at(self, t_eva_s: float, tau_dust: float = 0.0, dose_rate: float | None = None, spe: bool = False) -> bt.BtEnv:
        """그 시각의 환경 구조체. 먼지·선량률·SPE는 환경 리플레이(시뮬레이터)가 줄 값이고, 안 주면 평상시 값이다."""
        s = self.sun_at(t_eva_s)
        e = bt.BtEnv()
        e.sun_elev_deg, e.sun_az_deg, e.t_sunset_s = s["elev_deg"], s["az_deg"], s["t_sunset_s"]
        e.shadow_bin = int(s["shadow_bin"])
        e.tau_dust = tau_dust
        e.dose_rate_uSv_h = self.dose_rate_uSv_h if dose_rate is None else dose_rate
        e.spe = 1 if spe else 0
        return e

    def park_xy(self, park_id: str) -> tuple[float, float]:
        for p in self.meta["rover_parks"]:
            if p["id"] == park_id:
                return float(p["xy"][0]), float(p["xy"][1])
        raise KeyError(park_id)


def _read(root: Path, lay: dict) -> np.ndarray:
    """레이어 파일 하나를 코어가 받는 형식의 배열로 읽는다."""
    path, kind = root / lay["file"], lay["dtype"]
    h, w = lay["shape"]
    if kind == "f16":
        return np.fromfile(path, dtype="<f2").astype(np.float32).reshape(h, w)       # float16은 올릴 때 float32로 넓힌다
    if kind == "u16":
        return np.fromfile(path, dtype="<u2").reshape(h, w)                          # 고도: 코어가 scale·offset으로 푼다
    if kind == "u8":
        return np.fromfile(path, dtype=np.uint8).reshape(h, w)
    if kind == "bits":
        return np.fromfile(path, dtype=np.uint8)                                     # 묶인 비트 그대로
    if kind == "tif":
        import rasterio  # 로버 쪽에서만 필요하다
        with rasterio.open(path) as src:
            return src.read(1).astype(np.float32)
    raise ValueError(f"모르는 레이어 형식: {kind}")


def load(root: str, level: str = "field") -> Bundle:
    """번들을 읽는다. level에 맞는 칸 크기의 비용 레이어와, 과학 레이어(칸 크기가 따로다)를 올린다."""
    r = Path(root)
    meta = json.loads((r / "meta.json").read_text())
    res = float(meta["levels_m"][0 if level == "field" else 1])
    b = Bundle(root=r, meta=meta, level=level, res_m=res, sun=json.loads((r / meta["sun_table"]).read_text()))
    science = {"mu0", "var0", "units", "minerals"}
    for lay in meta["layers"]:
        is_science = lay["name"] in science
        if not is_science and abs(lay["res_m"] - res) > 1e-6:
            continue                                                                 # 다른 수준의 레이어
        b.layers[lay["name"]] = (_read(r, lay), lay)
    return b
