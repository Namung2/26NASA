"""로버 콘솔의 3D 보기용 자료 (rover/console_map.py): 높이 격자, 과학 가치 그림, 범례.

화면은 이 셋을 받은 대로 그린다. 여기서는 모양과 놓임(북쪽이 위, 원점이 북서쪽 모서리)이 약속대로인지,
관측·가설을 넣으면 그림이 실제로 바뀌는지 본다.
"""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from rover import console_map as cm
from tests.fixtures import mini_bundle as mb
from tests.scene import ANCHOR, Scene


def _png(view, kind="expected") -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(cm.science_png(view, kind))).convert("RGB"))


def test_height_grid_matches_terrain():
    g = cm.height_grid(mb.make("rover"))
    n_r, n_c = g["shape"]
    assert g["res_m"] == 20.0 and (n_r, n_c) == (16, 16) and len(g["heights"]) == n_r * n_c
    assert g["extent_m"] == [mb.EXTENT_M, mb.EXTENT_M]
    z = np.array(g["heights"], dtype=float).reshape(n_r, n_c)
    # 격자점 (i, j)는 칸의 중심: x = (j + 0.5)·res, y = −(i + 0.5)·res. 평탄한 곳에서 지형 수식과 맞아야 한다
    for i, j in ((2, 1), (12, 3), (13, 13)):
        x, y = (j + 0.5) * 20.0, -(i + 0.5) * 20.0
        assert z[i, j] == pytest.approx(float(mb.elevation(np.array(x), np.array(y))), abs=0.6)
    assert z[:, 7:9].max() > z[:, 0:3].max() + 3.0          # 가운데의 벽(x = 160)이 서쪽 바닥보다 높다
    assert g["z_min"] == pytest.approx(float(np.nanmin(z)), abs=0.11) and g["z_max"] == pytest.approx(float(np.nanmax(z)), abs=0.11)


def test_science_png_shape_and_orientation():
    s = Scene()
    view = s.update()
    img = _png(view, "base")
    h, w = view["mu"].shape
    assert img.shape == (h, w, 3)
    # 바탕값: 서쪽 단위 0.2, 동쪽 단위 0.6 → 서쪽이 더 어둡다(눈금은 값이 클수록 밝다). 열 0이 서쪽이다
    assert img[:, : w // 4].astype(int).sum() < img[:, -w // 4:].astype(int).sum()
    leg = cm.legend(view, [0.3, 0.5])
    assert leg["shape"] == [h, w] and leg["extent_m"] == [w * leg["res_m"], h * leg["res_m"]]
    assert [x["value"] for x in leg["ramp"]] == sorted(x["value"] for x in leg["ramp"]) and leg["ramp"][0]["value"] == 0.0 and leg["ramp"][-1]["value"] == 1.0
    assert set(leg["kinds"]) == {"expected", "max", "base", "var"} and "Not a calibrated probability" in leg["note"] and "relative index" in leg["name"]
    with pytest.raises(KeyError):
        cm.science_png(view, "score")


def test_science_png_changes_with_observation_and_hypothesis():
    s = Scene()
    before = _png(s.update(), "expected")
    s.obs()                                                  # 발견 → 그 둘레의 값이 오른다
    after_obs = _png(s.update(), "expected")
    res = float(s.update()["res_m"])
    r, c = int(-ANCHOR[1] // res), int(ANCHOR[0] // res)
    assert not np.array_equal(before, after_obs)
    assert after_obs[r, c].astype(int).sum() > before[r, c].astype(int).sum()      # 관측한 칸이 더 밝아졌다
    s.hyp()                                                  # 가설 → 기대값과 "전부 맞았을 때"가 갈린다
    v = s.update()
    assert not np.array_equal(_png(v, "expected"), _png(v, "max"))
    assert np.array_equal(_png(v, "base"), after_obs)        # 가설을 뺀 값은 그대로다
    assert (_png(v, "max").astype(int).sum(axis=2) >= _png(v, "expected").astype(int).sum(axis=2) - 1).all()
