"""C-10b — 고도에서 경사, 거칠기, 그림자, 가시선을 낸다.

전부 번들을 만들 때 한 번 계산해 구워 둔다. 실행 중에 코어는 구운 값을 읽기만 한다.
배열은 (row, col), row 0 = 북쪽. 값 없는 칸(NaN)은 결과에서도 값 없음으로 남긴다.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import uniform_filter


def _filled(elev: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """NaN을 평균 고도로 채운 배열과 '값 있음' 마스크. 필터가 NaN을 퍼뜨리지 않게 하려는 것이다."""
    valid = np.isfinite(elev)
    fill = float(np.nanmean(elev)) if valid.any() else 0.0
    return np.where(valid, elev, fill).astype(np.float64), valid


def slope_deg(elev: np.ndarray, res_m: float) -> np.ndarray:
    """칸의 경사 크기(°). 이웃 칸과의 고도 차로 구한다.

    코어는 이 값이 mobility.theta_max_deg(20°)를 넘는 칸을 통과불가로 본다.
    값 없는 칸과 맞닿은 칸은 경사를 믿을 수 없으므로 값 없음(NaN)으로 둔다.
    """
    z, valid = _filled(elev)
    gy, gx = np.gradient(z, res_m)
    out = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    near_hole = uniform_filter(valid.astype(np.float32), 3) < 0.999
    out[near_hole] = np.nan
    return out


def roughness(elev: np.ndarray, res_m: float, win_m: float) -> np.ndarray:
    """거칠기(m): 창(win_m) 안에서 완만한 지형을 뺀 나머지 요철의 표준편차.

    창 평균을 빼는 것으로 평면 제거를 대신했다(간단한 근사). 코어는 이 값을 cost.rough_ref_m로 나눠 0~1로 쓴다.
    """
    z, valid = _filled(elev)
    win = max(3, int(round(win_m / res_m)) | 1)       # 홀수 칸 수
    resid = z - uniform_filter(z, win)
    out = np.sqrt(uniform_filter(resid * resid, win)).astype(np.float32)
    out[~valid] = np.nan
    return out


def _shifted(z: np.ndarray, drow: int, dcol: int) -> np.ndarray:
    """out[r, c] = z[r + drow, c + dcol]. 배열 밖은 -inf(가리는 지형이 없다는 뜻)."""
    h, w = z.shape
    out = np.full_like(z, -np.inf)
    r0, r1 = max(0, -drow), min(h, h - drow)
    c0, c1 = max(0, -dcol), min(w, w - dcol)
    if r0 < r1 and c0 < c1:
        out[r0:r1, c0:c1] = z[r0 + drow:r1 + drow, c0 + dcol:c1 + dcol]
    return out


def shadow_mask(elev: np.ndarray, res_m: float, sun_elev_deg: float, sun_az_deg: float, max_m: float) -> np.ndarray:
    """그 태양 위치에서 그림자인 칸(True).

    칸에서 태양 쪽으로 걸어가며 "거기 지형이 태양빛보다 높이 솟아 있는가"를 본다:
        z(태양 쪽으로 d만큼 간 곳) - z(여기) > d · tan(태양 고도)  인 d가 하나라도 있으면 그림자.
    d는 1칸에서 시작해 1.25배씩 늘린다(가까운 지형은 촘촘히, 먼 지형은 성기게). 최대 max_m.
    태양 방위는 북에서 시계 방향(동 = 90°). 태양이 지평선 아래면 전부 그림자다.
    """
    if sun_elev_deg <= 0.0:
        return np.ones(elev.shape, dtype=bool)
    z, valid = _filled(elev)
    tan_e = math.tan(math.radians(sun_elev_deg))
    ux, uy = math.sin(math.radians(sun_az_deg)), math.cos(math.radians(sun_az_deg))   # 태양 쪽 단위 벡터 (동, 북)
    shadow = np.zeros(elev.shape, dtype=bool)
    d_cells, seen = 1.0, set()
    while d_cells * res_m <= max_m:
        dcol, drow = int(round(ux * d_cells)), int(round(-uy * d_cells))   # 북쪽이 row가 줄어드는 쪽
        if (drow, dcol) != (0, 0) and (drow, dcol) not in seen:
            seen.add((drow, dcol))
            dist = math.hypot(drow, dcol) * res_m
            shadow |= (_shifted(z, drow, dcol) - z) > dist * tan_e
        d_cells = max(d_cells + 1.0, d_cells * 1.25)
    shadow[~valid] = False
    return shadow


def knife_edge_loss_db(nu: np.ndarray) -> np.ndarray:
    """칼날 능선 하나가 만드는 회절 손실 J(ν) (ITU-R P.526 식 31). ν ≤ −0.78이면 0."""
    nu = np.asarray(nu, dtype=np.float64)
    j = 6.9 + 20.0 * np.log10(np.sqrt((nu - 0.1) ** 2 + 1.0) + nu - 0.1)
    return np.where(nu > -0.78, j, 0.0)


def link_mask(elev: np.ndarray, res_m: float, park_xy: tuple[float, float], radio: dict) -> tuple[np.ndarray, np.ndarray]:
    """로버 주차점에서 UHF 링크가 된다고 보는 칸. (링크 됨, 눈으로 보임) 두 장을 돌려준다.

    처음에는 "두 안테나를 잇는 직선을 지형이 가리지 않으면 된다"(엄격한 가시선)로 구웠는데, 그러면 5 km 구역의 11.5 %만
    보이고 평지를 걷는 31분 중 27분이 두절로 나왔다. 조사 결과(REFERENCE §4.4) 그 판정은 두 방향으로 틀렸다:
      · 로버 가까이에서는 너무 엄격하다 — UHF는 살짝 가린 능선을 넘어간다(회절). 1 km 거리에서 능선이 직선보다 10 m 솟아도
        손실은 14 dB쯤이다. 아폴로 15의 실측에서도 가시선이 가려진 채로 링크가 유지됐다.
      · 멀리서는 너무 너그럽다 — 안테나가 낮으면(2~3 m) 가리는 것이 없어도 거리의 4제곱으로 약해져 2 km쯤에서 한계에 닿는다.
    그래서 "보이느냐"가 아니라 "손실이 한계 안이냐"로 판정한다:

        평지 손실(d) + 지형 가림 손실 + 페이딩 여유  ≤  허용 손실
        평지 손실     = 40·log10(d) − 20·log10(h_로버 · h_우주복)   (평면 대지 모델. 자유 공간 손실보다 작아지면 자유 공간 손실)
        지형 가림 손실 = max(0, J(ν) − J(ν_평지))                    (칼날 회절. 같은 자리가 평지였을 때보다 더 잃는 만큼만)
        ν = h · sqrt(2/λ · (1/d1 + 1/d2)),  h = 가리는 능선이 두 안테나를 잇는 직선보다 솟은 높이(가리지 않으면 음수)

    가리는 능선은 살마다 하나, "로버에서 올려본각이 가장 큰 지점"으로 잡는다(능선이 여럿이어도 하나로 본 근사).
    ν_평지를 빼는 이유: 평지 손실에 이미 지면의 영향이 들어 있어서, 평지에서도 0이 아닌 J를 또 더하면 두 번 세게 된다.
    이 빼기는 우리가 정한 처리다(문헌의 식 둘을 잇는 방식). radio = params.yaml의 link.radio (값의 출처가 거기 있다).
    모델에 없는 것: 몸과 차체의 가림, 자세, 다중 경로, 고도 자료의 오차. 대기 굴절과 전리층 반사는 화성에서 무시한다.
    """
    h_tx, h_rx = float(radio["antenna_rover_h_m"]["value"]), float(radio["antenna_suit_h_m"]["value"])
    freq = float(radio["freq_mhz"]["value"])
    allow, margin = float(radio["loss_allow_db"]["value"]), float(radio["fade_margin_db"]["value"])
    lam = 299.792458 / freq
    z, valid = _filled(elev)
    h, w = z.shape
    pr, pc = -park_xy[1] / res_m - 0.5, park_xy[0] / res_m - 0.5            # 주차점의 (row, col), 소수
    r_max = int(math.ceil(math.hypot(max(pr, h - pr), max(pc, w - pc)))) + 1
    n_ray = int(math.ceil(2.0 * math.pi * r_max * 1.5))                     # 가장 먼 고리에서도 칸마다 살 하나 이상
    ang = np.arange(n_ray) * (2.0 * math.pi / n_ray)
    dr, dc = -np.cos(ang), np.sin(ang)                                      # 각 0 = 북쪽
    ir0, ic0 = int(round(pr)), int(round(pc))
    if not (0 <= ir0 < h and 0 <= ic0 < w):
        raise ValueError("로버 주차점이 격자 밖이다")
    z0 = z[ir0, ic0] + h_tx
    link_ray = np.zeros((n_ray, r_max + 1), dtype=bool)
    sight_ray = np.zeros((n_ray, r_max + 1), dtype=bool)
    link_ray[:, 0] = sight_ray[:, 0] = True
    top_ang = np.full(n_ray, -np.inf)                                       # 살마다 지금까지의 최대 올려본각(탄젠트)
    top_d = np.zeros(n_ray)                                                 # 그 능선까지의 거리
    top_z = np.zeros(n_ray)                                                 # 그 능선의 고도
    for k in range(1, r_max + 1):
        rr, cc = np.rint(pr + dr * k).astype(np.int64), np.rint(pc + dc * k).astype(np.int64)
        inside = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
        ground = np.where(inside, z[np.clip(rr, 0, h - 1), np.clip(cc, 0, w - 1)], -np.inf)
        dist = k * res_m
        target = ground + h_rx
        sight_ray[:, k] = inside & ((target - z0) / dist >= top_ang)
        have = top_d > 0
        d1 = np.where(have, top_d, 1.0)
        d2 = np.maximum(dist - d1, 1e-6)
        fac = np.sqrt(2.0 / lam * (1.0 / d1 + 1.0 / d2))
        ray_h = z0 + (target - z0) * d1 / dist                              # 능선 자리에서 두 안테나를 잇는 직선의 고도
        nu = (top_z - ray_h) * fac
        nu_flat = -(h_tx + (h_rx - h_tx) * d1 / dist) * fac                 # 같은 자리가 평지였을 때
        shadow = np.where(have & inside, np.maximum(0.0, knife_edge_loss_db(nu) - knife_edge_loss_db(nu_flat)), 0.0)
        plane = max(40.0 * math.log10(dist) - 20.0 * math.log10(h_tx * h_rx), 20.0 * math.log10(dist) + 20.0 * math.log10(freq) - 27.55)
        link_ray[:, k] = inside & (plane + shadow + margin <= allow)
        a = (ground - z0) / dist
        higher = a > top_ang
        top_ang, top_d, top_z = np.where(higher, a, top_ang), np.where(higher, dist, top_d), np.where(higher, ground, top_z)
    rows, cols = np.mgrid[0:h, 0:w]
    off_r, off_c = rows - pr, cols - pc
    k_idx = np.clip(np.rint(np.hypot(off_r, off_c)).astype(np.int64), 0, r_max)
    a_idx = np.rint(np.mod(np.arctan2(off_c, -off_r), 2.0 * math.pi) / (2.0 * math.pi / n_ray)).astype(np.int64) % n_ray
    link, sight = link_ray[a_idx, k_idx], sight_ray[a_idx, k_idx]
    link[~valid] = False
    sight[~valid] = False
    return link, sight


def pack_bits(mask: np.ndarray) -> bytes:
    """bool 배열(여러 장이면 [장, H, W])을 번들의 .bits 형식으로 묶는다.

    한 장은 ceil(H·W / 8) 바이트, 장마다 따로 묶어 이어 붙인다. 칸 i = row·W + col 의 비트는
    (바이트[i >> 3] >> (7 - (i & 7))) & 1 — numpy.packbits의 기본 순서. 코어(core/src/grid.hpp)가 같은 순서로 읽는다.
    """
    planes = mask.reshape((-1,) + mask.shape[-2:])
    return b"".join(np.packbits(p.reshape(-1).astype(np.uint8)).tobytes() for p in planes)
