"""시험이 같이 쓰는 검사 도구. 코어의 결과를 코어 밖에서(numpy로) 다시 확인한다."""
from __future__ import annotations

import itertools

import numpy as np

from host import btcore as bt


def base_passable(bundle, theta_max_deg: float) -> np.ndarray:
    """그 수준의 원본 레이어 격자에서 걸을 수 있는 칸. 코어의 코스트맵을 거치지 않는다."""
    s = np.asarray(bundle.layers["slope"][0], dtype=np.float64).reshape(bundle.layers["slope"][1]["shape"])
    ok = np.isfinite(s) & (s <= theta_max_deg)
    if "elev" in bundle.layers:
        e, lay = bundle.layers["elev"]
        e = np.asarray(e).reshape(lay["shape"])
        ok &= (e != lay.get("nodata", 65535)) if e.dtype == np.uint16 else np.isfinite(e)
    return ok


def path_violations(path: bt.Path_, ok: np.ndarray, base_res: float) -> tuple[int, int]:
    """경로를 원본 격자에 다시 얹어 센다: (통과 불가 칸을 밟은 수, 대각 이동이 막힌 모서리를 끼고 돈 수).

    경로의 칸이 원본보다 크면(로버의 4 m 경로 ↔ 2 m 원본) 그 칸이 덮는 원본 칸이 전부 걸을 수 있어야 한다.
    대각 이동은 옆의 두 칸(가로로 한 칸, 세로로 한 칸)이 모두 걸을 수 있어야 한다.
    """
    f = round(path.res_m / base_res)
    cells = path.cells
    h, w = ok.shape

    def cell_ok(r: int, c: int) -> bool:
        if r < 0 or c < 0 or (r + 1) * f > h or (c + 1) * f > w:
            return False
        return bool(ok[r * f:(r + 1) * f, c * f:(c + 1) * f].all())

    bad = sum(0 if cell_ok(int(r), int(c)) else 1 for r, c in cells)
    cut = 0
    for (r0, c0), (r1, c1) in itertools.pairwise(cells):
        assert max(abs(int(r1 - r0)), abs(int(c1 - c0))) == 1, "경로의 이웃한 칸이 한 칸 넘게 떨어져 있다"
        if r0 != r1 and c0 != c1 and not (cell_ok(int(r0), int(c1)) and cell_ok(int(r1), int(c0))):
            cut += 1
    return bad, cut


def random_passable_xy(rng, ok: np.ndarray, res: float) -> tuple[float, float]:
    """걸을 수 있는 칸 하나의 중심 좌표."""
    rows, cols = np.nonzero(ok)
    i = rng.randrange(len(rows))
    return (float(cols[i]) + 0.5) * res, -(float(rows[i]) + 0.5) * res
