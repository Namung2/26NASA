"""레이어 정합 — 서로 다른 바탕 그림 위에 만들어진 자료를 한 기준에 맞춘다.

이 파일의 함수
    register_images     사진끼리 맞춘다 (지질 단위 지도의 바탕 그림 → 기준 그림)
    register_class_map  분류 지도를 맞춘다 (광물 지도 → 그 원자료인 지수 그림 → 기준 그림)
    to_reference        잰 결과로 좌표를 옮긴다
    overlay_png         눈으로 확인하는 그림

기준은 하나다: 고도 자료(USGS Mars 2020 TRN HiRISE DTM). 이 DTM은 같은 제품군의 CTX 정사 모자이크("TRN CTX")에
맞춰져 있다. 번들의 모든 레이어는 이 기준에 맞아야 하고, 맞춘 방법과 남은 오차를 메타의 registration에 적는다.
정합 기록이 없는 레이어는 번들에 넣지 않는다(pipeline/build.py가 확인한다) — 레이어가 쌓이면서 조용히 틀어지는 것을 막기 위해서다.

지질 단위 지도(USGS SIM 3464)가 왜 어긋나나
    그 지도의 선은 Caltech CTX 모자이크(2018, 위치를 대략만 맞춘 것) 위에 그려졌다. TRN CTX는 그 뒤에 HRSC 지형에
    정밀하게 맞춘 것이라 두 그림이 100 m쯤 다르다(REFERENCE §1.2). 어긋남은 구역 안에서도 고르지 않다.

맞추는 방법 (measure → fit → apply → 다시 재서 확인)
    1. 두 바탕 그림(지도의 바탕 = 움직일 그림, TRN CTX = 기준 그림)을 로컬 격자에 올린다.
    2. 창(기본 1.28 km)마다 위상 상관으로 "움직일 그림이 기준에서 얼마나 밀려 있나"를 잰다. 창은 절반씩 겹친다.
    3. 믿을 만한 창만 골라(밀어 본 뒤의 상관이 높은 것) 위치의 1차식(affine)으로 맞춘다:
           밀림(x, y) = [a0 + a1·x + a2·y,  b0 + b1·x + b2·y]      (m, 동쪽·북쪽)
       평행이동만으로는 구역의 끝과 끝에서 수 m ~ 수십 m가 남는다. 1차식은 완만한 회전·늘어남까지 잡는다.
    4. 폴리곤의 점마다  기준 좌표 = 지도 좌표 − 밀림(지도 좌표)  로 옮긴다.
    5. 움직일 그림을 같은 식으로 옮겨 다시 재고, 남은 밀림(중앙값과 흩어짐)을 기록한다. 이것이 정합 오차다.

한계 (숨기지 않는다)
    - 맞추는 것은 "바탕 그림"이다. 지도의 선 자체는 축척 1:75,000으로 그린 것이라 선의 위치에는 따로 수십 m의
      그리기 오차가 있다(지도 위 0.5 mm = 현장 37 m). 정합으로 줄일 수 없는 부분이다.
    - 창 안에 무늬가 없으면(모래 평원) 잘 재지지 않는다. 그런 창은 버리고, 쓴 창의 수를 기록한다.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy import ndimage as ndi
from skimage.registration import phase_cross_correlation

from .dtm import local_crs


def _to_local(path: str, site: dict, res_m: float, margin_m: float) -> np.ndarray:
    """그림 한 장을 로컬 격자(구역 + 여백)에 올린다. 값 없는 곳은 0."""
    half = float(site["aoi"]["half_size_m"])
    n = int(round((2 * half + 2 * margin_m) / res_m))
    out = np.zeros((n, n), dtype=np.float32)
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), out, src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                  dst_transform=from_origin(-margin_m, margin_m, res_m, res_m), dst_crs=local_crs(site), dst_nodata=0,
                  resampling=Resampling.bilinear)
    return out


def _detail(img: np.ndarray) -> np.ndarray:
    """밝기의 큰 흐름을 빼고 무늬만 남긴다. 두 그림의 밝기·대비가 달라도 무늬끼리 견줄 수 있다."""
    g = ndi.gaussian_filter(img, 2) - ndi.gaussian_filter(img, 25)
    g[img <= 0] = 0
    return g


def measure(moving: np.ndarray, reference: np.ndarray, res_m: float, origin_xy: tuple[float, float], win: int = 256) -> np.ndarray:
    """창마다 밀림을 잰다. 돌려주는 배열의 줄 = [창 중심 x, y, 동쪽 밀림 m, 북쪽 밀림 m, 밀기 전 상관, 민 뒤 상관].

    밀림의 뜻: 움직일 그림의 무늬 위치 = 기준 그림의 무늬 위치 + 밀림.
    """
    hann = np.outer(np.hanning(win), np.hanning(win))
    core = slice(win // 4, 3 * win // 4)
    rows = []
    for i in range(0, moving.shape[0] - win + 1, win // 2):
        for j in range(0, moving.shape[1] - win + 1, win // 2):
            a, b = moving[i:i + win, j:j + win], reference[i:i + win, j:j + win]
            if (a > 0).mean() < 0.98 or (b > 0).mean() < 0.98:
                continue
            da, db = _detail(a), _detail(b)
            shift, _err, _ph = phase_cross_correlation(da * hann, db * hann, upsample_factor=10, normalization="phase")
            moved = ndi.shift(db, shift, order=1)                        # 기준 그림을 잰 만큼 밀어 본다

            def corr(u, v):
                return float(np.corrcoef(u[core, core].ravel(), v[core, core].ravel())[0, 1])

            cx = origin_xy[0] + (j + win / 2) * res_m
            cy = origin_xy[1] - (i + win / 2) * res_m
            rows.append((cx, cy, shift[1] * res_m, -shift[0] * res_m, corr(da, db), corr(da, moved)))   # 행이 늘면 남쪽 → 북쪽은 부호 반대
    return np.array(rows, dtype=np.float64).reshape(-1, 6)


def fit_affine(samples: np.ndarray, min_corr: float = 0.5) -> dict:
    """잰 값에 1차식을 맞춘다. 상관이 낮은 창과, 맞춘 식에서 크게 벗어난 창(중앙값 편차의 3배)은 뺀다.

    돌려주는 사전: east = [a0, a1, a2], north = [b0, b1, b2], n_used, n_measured, rms_m(맞춘 식과 잰 값의 차이)
    """
    good = samples[samples[:, 5] >= min_corr]
    if len(good) < 6:
        raise ValueError(f"믿을 만한 창이 {len(good)}개뿐이다 — 바탕 그림에 무늬가 부족하거나 두 그림이 겹치지 않는다")
    keep = np.ones(len(good), dtype=bool)
    coef_e = coef_n = None
    for _ in range(5):                                                   # 벗어난 창을 빼고 다시 맞추기를 몇 번
        A = np.c_[np.ones(keep.sum()), good[keep, 0], good[keep, 1]]
        coef_e, *_ = np.linalg.lstsq(A, good[keep, 2], rcond=None)
        coef_n, *_ = np.linalg.lstsq(A, good[keep, 3], rcond=None)
        full = np.c_[np.ones(len(good)), good[:, 0], good[:, 1]]
        resid = np.hypot(good[:, 2] - full @ coef_e, good[:, 3] - full @ coef_n)
        limit = 3.0 * max(1.4826 * np.median(np.abs(resid - np.median(resid))), 1.0) + np.median(resid)
        new_keep = resid <= limit
        if (new_keep == keep).all():
            break
        keep = new_keep
    return {"east": [float(v) for v in coef_e], "north": [float(v) for v in coef_n],
            "n_used": int(keep.sum()), "n_measured": len(samples), "rms_m": float(np.sqrt(np.mean(resid[keep] ** 2)))}


def shift_at(fit: dict, x, y):
    """그 자리의 밀림 (동쪽 m, 북쪽 m). x, y는 수 하나여도 배열이어도 된다."""
    e, n = fit["east"], fit["north"]
    return e[0] + e[1] * x + e[2] * y, n[0] + n[1] * x + n[2] * y


def to_reference(fit: dict | None, x, y):
    """움직일 자료(지질 지도)의 좌표 → 기준 좌표. fit이 없으면 그대로."""
    if not fit:
        return x, y
    de, dn = shift_at(fit, x, y)
    return x - de, y - dn


def register_images(moving_path: str, reference_path: str, site: dict, res_m: float = 5.0, margin_m: float = 1000.0) -> dict:
    """두 바탕 그림을 정합하고 기록을 만든다. 번들 메타의 registration 항목이 된다.

    기록: method, moving, reference, east/north(1차식 계수), n_used, n_measured, rms_m,
          before_m(맞추기 전 밀림의 중앙 크기), after_m(맞춘 뒤 다시 잰 밀림의 중앙 크기), after_p90_m, center_shift_m(구역 중심의 밀림)
    """
    mov = _to_local(moving_path, site, res_m, margin_m)
    ref = _to_local(reference_path, site, res_m, margin_m)
    origin = (-margin_m, margin_m)
    samples = measure(mov, ref, res_m, origin)
    fit = fit_affine(samples)
    # 확인: 움직일 그림을 맞춘 식대로 옮겨 다시 잰다 → 남은 밀림
    n = mov.shape[0]
    rows, cols = np.mgrid[0:n, 0:n].astype(np.float64)
    x, y = origin[0] + (cols + 0.5) * res_m, origin[1] - (rows + 0.5) * res_m
    de, dn = shift_at(fit, x, y)
    fixed = ndi.map_coordinates(mov, [rows - dn / res_m, cols + de / res_m], order=1, mode="constant", cval=0.0)   # 기준 자리 p의 값 = 움직일 그림의 p + 밀림
    again = measure(fixed.astype(np.float32), ref, res_m, origin)
    ok = again[again[:, 5] >= 0.5]
    good = samples[samples[:, 5] >= 0.5]
    half = float(site["aoi"]["half_size_m"])
    ce, cn = shift_at(fit, half, -half)
    fit.update({
        "method": "창별 위상 상관 → 1차식(affine) 맞춤 → 다시 재서 확인 (pipeline/register.py)",
        "moving": moving_path, "reference": reference_path, "res_m": res_m,
        "before_m": float(np.median(np.hypot(good[:, 2], good[:, 3]))),
        "after_m": float(np.median(np.hypot(ok[:, 2], ok[:, 3]))) if len(ok) else None,
        "after_p90_m": float(np.percentile(np.hypot(ok[:, 2], ok[:, 3]), 90)) if len(ok) else None,
        "center_shift_m": [float(ce), float(cn)],
    })
    return fit


def register_class_map(classes: np.ndarray, src_transform, src_crs, index_path: str, reference_path: str, site: dict,
                       res_m: float = 12.0, margin_m: float = 1000.0, min_cells: int = 2000, min_corr: float = 0.5) -> dict:
    """분류 지도(광물 지도)가 기준에서 얼마나 어긋났는지 잰다. 분류 지도는 무늬 있는 사진이 아니라서 두 단계를 잇는다.

        ① 지수 그림 ↔ 기준 그림   지수 그림 = 그 분류를 만든 원자료(CRISM 요약 파라미터, index_path). 그 안의 적외선 밝기(R1330)를
                                  기준 그림과 창별 위상 상관으로 맞춘다(register_images와 같은 방법) → 지수 그림을 기준 틀로 옮긴다.
        ② 분류 지도 ↔ 지수 그림   분류마다 "그 분류인 칸 = 1" 표시를 만들고, 기준 틀로 옮긴 지수들 가운데 그 표시와 가장 잘 맞는
                                  지수를 고른다(상관의 크기 ≥ min_corr, 칸 수 ≥ min_cells). 표시를 12 m씩 밀어 보며 상관이 가장 큰
                                  자리를 찾고 봉우리를 2차 곡선으로 다듬어 칸보다 잘게 읽는다.
        분류별 결과를 상관으로 가중 평균한 것이 "분류 지도를 이만큼 옮기면 기준에 맞는다"는 값(shift_m)이다.

    왜 이렇게 돌아가나: 분류 지도를 지질 단위나 고도, 사진 밝기와 직접 견주면 답이 100 m씩 서로 달랐다(2026-11-14).
    분류와 그것들의 관계가 느슨해서다. 같은 원자료에서 나온 지수와는 관계가 뚜렷하다(상관 0.8).

    돌려주는 기록: method, index(지수 그림의 정합 — center_shift_m, after_m …), pairs[{class, index, corr, shift_m}],
                  shift_m [동, 북], scatter_m [동, 북](분류 사이의 흩어짐 = 이 측정의 불확실성), after_m(= shift의 크기)
    """
    half = float(site["aoi"]["half_size_m"])
    n = int(round((2 * half + 2 * margin_m) / res_m))
    T = from_origin(-margin_m, margin_m, res_m, res_m)
    crs = local_crs(site)
    origin = (-margin_m, margin_m)
    with rasterio.open(index_path) as src:
        names = list(src.descriptions)

        def band_local(i: int) -> np.ndarray:
            a = src.read(i + 1).astype(np.float32)
            a[a >= 65534] = np.nan                                       # CRISM의 값 없음(65535)
            out = np.full((n, n), np.nan, dtype=np.float32)
            reproject(a, out, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                      dst_transform=T, dst_crs=crs, dst_nodata=np.nan, resampling=Resampling.bilinear)
            return out

        # ① 지수 그림의 적외선 밝기를 기준 그림에 맞춘다
        albedo = band_local(names.index("R1330"))
        ref = ndi.gaussian_filter(_to_local(reference_path, site, res_m, margin_m), 1.5)   # 기준 그림을 CRISM의 선명도에 가깝게
        fit = fit_affine(measure(np.nan_to_num(albedo, nan=0.0), ref, res_m, origin, win=128))
        rows, cols = np.mgrid[0:n, 0:n].astype(np.float64)
        de, dn = shift_at(fit, origin[0] + (cols + 0.5) * res_m, origin[1] - (rows + 0.5) * res_m)
        src_rows, src_cols = rows - dn / res_m, cols + de / res_m

        def in_reference_frame(a: np.ndarray) -> np.ndarray:             # 기준 자리 p의 값 = 지수 그림의 p + 밀림. 값 없음은 NaN
            out = ndi.map_coordinates(np.nan_to_num(a, nan=-9e9), [src_rows, src_cols], order=1, mode="constant", cval=-9e9)
            out[out < -1e6] = np.nan
            return out

        again = measure(np.nan_to_num(in_reference_frame(albedo), nan=0.0).astype(np.float32), ref, res_m, origin, win=128)
        ok = again[again[:, 5] >= 0.5]
        idx_rec = {"center_shift_m": [float(v) for v in shift_at(fit, half, -half)], "n_used": fit["n_used"], "rms_m": fit["rms_m"],
                   "after_m": float(np.median(np.hypot(ok[:, 2], ok[:, 3]))) if len(ok) else None}
        index_maps = [in_reference_frame(band_local(i)) for i in range(len(names))]

    # ② 분류 지도를 같은 격자에 올리고(원본 좌표 그대로) 분류마다 가장 잘 맞는 지수를 찾는다
    cls = np.zeros((n, n), dtype=np.uint8)
    reproject(classes, cls, src_transform=src_transform, src_crs=src_crs, src_nodata=None,
              dst_transform=T, dst_crs=crs, dst_nodata=None, resampling=Resampling.nearest)
    K = 10                                                               # ±120 m까지 밀어 본다
    pairs = []
    for num in np.unique(cls):
        if num == 0 or (cls == num).sum() < min_cells:
            continue
        mark = (cls == num).astype(np.float32)
        best = (0.0, -1)
        for i, m in enumerate(index_maps):
            v = np.isfinite(m) & (cls > 0)
            if v.sum() < min_cells or mark[v].std() == 0 or np.nanstd(m[v]) == 0:
                continue
            c = float(np.corrcoef(mark[v], m[v])[0, 1])
            if abs(c) > abs(best[0]):
                best = (c, i)
        if abs(best[0]) < min_corr:
            continue
        sign, m = np.sign(best[0]), index_maps[best[1]]
        base_valid = np.isfinite(m)
        base_valid[:K + 1] = base_valid[-K - 1:] = False                 # 밀 때 가장자리가 말려 들어오지 않게
        base_valid[:, :K + 1] = base_valid[:, -K - 1:] = False
        g = {}
        for dy in range(-K, K + 1):
            for dx in range(-K, K + 1):
                moved_cls = np.roll(np.roll(cls, dy, axis=0), dx, axis=1)                       # 분류 지도를 동쪽 dx칸, 남쪽 dy칸 민다
                v = base_valid & (moved_cls > 0)
                g[(dx, dy)] = sign * float(np.corrcoef((moved_cls == num)[v].astype(np.float32), m[v])[0, 1])
        bx, by = max(g, key=g.get)
        fx = fy = 0.0
        if abs(bx) < K and abs(by) < K:                                  # 봉우리를 2차 곡선으로 다듬는다
            fx = (g[(bx + 1, by)] - g[(bx - 1, by)]) / (2 * (2 * g[(bx, by)] - g[(bx + 1, by)] - g[(bx - 1, by)]) + 1e-12)
            fy = (g[(bx, by + 1)] - g[(bx, by - 1)]) / (2 * (2 * g[(bx, by)] - g[(bx, by + 1)] - g[(bx, by - 1)]) + 1e-12)
        pairs.append({"class": int(num), "index": names[best[1]], "corr": round(abs(best[0]), 3),
                      "shift_m": [round((bx + fx) * res_m, 1), round(-(by + fy) * res_m, 1)]})
    if not pairs:
        raise ValueError("분류와 잘 맞는 지수를 찾지 못했다 — 지수 그림이 이 분류 지도의 원자료가 맞는지 본다")
    w = np.array([p["corr"] for p in pairs])
    sh = np.array([p["shift_m"] for p in pairs], dtype=np.float64)
    shift = (sh * w[:, None]).sum(0) / w.sum()
    return {"method": "두 단계: 지수 그림(CRISM)의 적외선 밝기를 기준 그림에 맞춤 → 분류 표시와 지수의 상관이 가장 큰 자리 (pipeline/register.py)",
            "moving": "분류 지도", "index_image": index_path, "reference": reference_path, "index": idx_rec, "pairs": pairs,
            "shift_m": [float(shift[0]), float(shift[1])], "scatter_m": [float(sh[:, 0].std()), float(sh[:, 1].std())],
            "after_m": float(np.hypot(shift[0], shift[1]))}


def overlay_png(path: str, reference_path: str, site: dict, rings_before: list, rings_after: list, res_m: float = 5.0) -> None:
    """눈으로 확인하는 그림: 기준 그림 위에 지질 단위의 경계를 맞추기 전(빨강)과 맞춘 뒤(초록)로 그린다.

    번들의 qa/ 폴더에 들어간다. 숫자(after_m)만으로는 "선이 지형과 맞는가"를 알 수 없으므로 사람이 한 번 본다.
    rings_* 는 로컬 좌표의 고리 목록([[x, y], …]).
    """
    from PIL import Image, ImageDraw
    img = _to_local(reference_path, site, res_m, 0.0)
    lo, hi = np.percentile(img[img > 0], [2, 98]) if (img > 0).any() else (0.0, 1.0)
    g = np.clip((img - lo) / max(hi - lo, 1e-6), 0, 1) * 255
    scale = 2
    canvas = Image.fromarray(g.astype(np.uint8)).convert("RGB").resize((img.shape[1] * scale, img.shape[0] * scale), Image.BILINEAR)
    draw = ImageDraw.Draw(canvas)
    for rings, color, width in ((rings_before, (255, 70, 70), 1), (rings_after, (60, 255, 120), 2)):
        for ring in rings:
            pts = [(x / res_m * scale, -y / res_m * scale) for x, y in ring]
            if len(pts) >= 2:
                draw.line(pts, fill=color, width=width)
    canvas.save(path)
