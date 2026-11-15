"""로버 콘솔의 3D 보기와 "살아 있는" 과학 가치 레이어에 쓰는 자료 (S3c §6.1 Terrain3D, R-06).

화면은 계산하지 않는다. 여기서 프로그램이 세 가지를 만들어 내주고, 화면은 받은 대로 그린다:

  height_grid(bundle)        지형의 높이 격자(3D로 세울 때 쓴다). 번들의 고도 레이어를 20 m 칸으로 줄인 것 — 번들마다 한 번만 만든다
  science_png(view, kind)    지금의 과학 가치 지도를 색 입힌 그림(PNG). 관측·가설이 들어오면 바뀐다
  legend(grade_bins)         그 그림의 색 눈금과 등급 경계. 화면은 색을 따로 정하지 않고 이것을 읽어 범례를 그린다

과학 가치는 "보정된 확률"이 아니라 0~1의 상대 지수다(config/prior_table.yaml). 화면에서도 그렇게 적는다.

그림의 놓임: 행 0이 북쪽, 열 0이 서쪽. 구역의 북서쪽 모서리(로컬 좌표의 원점)에서 시작해 동쪽·남쪽으로 칸 크기(res_m)씩 간다.
과학 격자는 번들의 칸 크기에서 나오므로 한 변이 구역보다 조금 길 수 있다(예: 5 m × 1001칸 = 5005 m) — 화면은 legend의 extent_m을 쓴다.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

HEIGHT_STEP_M = 20.0          # 높이 격자의 칸. 5 km 구역이면 250 × 250점 — 브라우저가 가볍게 세울 수 있는 크기
VAR_MAX = 0.25                # 0~1 사이 값의 분산이 가질 수 있는 가장 큰 값(수학적 상한). 분산 그림의 눈금 끝

# 색 눈금 (값 0 → 1). 값이 클수록 밝고 따뜻한 색. 표시용 색일 뿐이다 — 등급의 경계는 legend의 grade_bins가 따로 알린다
RAMP = [(0.00, (26, 32, 64)), (0.25, (38, 96, 140)), (0.50, (52, 160, 150)), (0.75, (190, 210, 90)), (1.00, (253, 231, 37))]
NO_DATA = (70, 70, 74)        # 값이 없는 칸(바탕표에 근거가 없는 지질 단위)
KINDS = {        # 화면에 그대로 뜨는 글(화면의 글은 영어다 — host/templates.py와 같다)
    "expected": "Expected — prior map + observations + what hypotheses add (weighted by confidence)",
    "max": "If every hypothesis is right",
    "base": "Without hypotheses — prior map + observations",
    "var": "Variance — how little is known about each cell",
}


def _colorize(v: np.ndarray, v_max: float = 1.0) -> np.ndarray:
    """[h, w] 값 → [h, w, 3] 색. 값이 없는(NaN) 칸은 NO_DATA."""
    x = np.clip(v / v_max, 0.0, 1.0)
    stops = np.array([s for s, _ in RAMP])
    out = np.stack([np.interp(x, stops, [c[k] for _, c in RAMP]) for k in range(3)], axis=-1)
    out[~np.isfinite(v)] = NO_DATA
    return out.astype(np.uint8)


def science_values(view: dict, kind: str) -> np.ndarray:
    """코어의 과학 가치 지도(Core.science_view)에서 그릴 값을 고른다."""
    mu = view["mu"].astype(np.float64)
    if kind == "expected":
        return mu + view["add_expected"]
    if kind == "max":
        return mu + view["add_full"]
    if kind == "base":
        return mu
    if kind == "var":
        return view["var"].astype(np.float64)
    raise KeyError(kind)


def science_png(view: dict, kind: str = "expected") -> bytes:
    """지금의 과학 가치 지도를 색 입힌 PNG로. 크기는 과학 격자 그대로(칸 하나 = 화소 하나)."""
    v = science_values(view, kind)
    img = Image.fromarray(_colorize(v, VAR_MAX if kind == "var" else 1.0), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def legend(view: dict, grade_bins: list[float]) -> dict:
    """그림의 색 눈금, 등급 경계, 놓임. 화면은 이것만 보고 범례를 그리고 그림을 지도에 놓는다."""
    h, w = view["mu"].shape
    res = float(view["res_m"])
    return {
        "name": "Science value (relative index)",
        "note": "Not a calibrated probability. A 0–1 relative index carried over from ordinal grades in the literature (config/prior_table.yaml).",
        "kinds": KINDS,
        "ramp": [{"value": s, "color": "#{:02x}{:02x}{:02x}".format(*c)} for s, c in RAMP],
        "var_max": VAR_MAX,                                   # kind=var일 때 눈금의 끝(값 1.0 자리)
        "no_data_color": "#{:02x}{:02x}{:02x}".format(*NO_DATA),
        "grade_bins": [float(x) for x in grade_bins],         # LOW/MED, MED/HIGH 경계 (번들 메타와 같은 값)
        "res_m": res, "shape": [int(h), int(w)], "extent_m": [w * res, h * res],
    }


def height_grid(bundle, step_m: float = HEIGHT_STEP_M) -> dict:
    """번들의 고도 레이어를 step_m 칸으로 줄인 높이 격자. 한 칸의 높이 = 그 칸에 드는 원본 칸들의 평균. 값이 없으면 null.

    heights는 행 우선(북 → 남, 각 행은 서 → 동)의 한 줄 목록이고 단위는 m다. 격자점은 칸의 중심에 있다:
    (i행, j열)의 좌표 = (x, y) = ((j + 0.5) · res_m, −(i + 0.5) · res_m).
    """
    a, lay = bundle.layers["elev"]
    h, w = lay["shape"]
    z = np.asarray(a).reshape(h, w)
    if z.dtype == np.uint16:
        z = np.where(z == lay.get("nodata", 65535), np.nan, z.astype(np.float64) * float(lay.get("scale", 1.0)) + float(lay.get("offset", 0.0)))
    else:
        z = z.astype(np.float64)
    f = max(1, round(step_m / float(lay["res_m"])))
    hh, ww = h // f, w // f
    blocks = z[: hh * f, : ww * f].reshape(hh, f, ww, f)
    with np.errstate(invalid="ignore"):
        cnt = np.isfinite(blocks).sum(axis=(1, 3))
        mean = np.where(cnt > 0, np.nansum(blocks, axis=(1, 3)) / np.maximum(cnt, 1), np.nan)
    res = float(lay["res_m"]) * f
    flat = [None if not np.isfinite(v) else round(float(v), 1) for v in mean.reshape(-1)]
    return {"res_m": res, "shape": [int(hh), int(ww)], "extent_m": [ww * res, hh * res],
            "z_min": round(float(np.nanmin(mean)), 1), "z_max": round(float(np.nanmax(mean)), 1), "unit": "m",
            "source_layer": "elev", "source_res_m": float(lay["res_m"]), "heights": flat}
