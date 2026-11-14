"""C-10e — 과학 가치 바탕 지도(mu0, var0)를 만든다.

1층 prior: 과학 격자의 칸마다 "생명 흔적이 남아 있을 가능성"의 값(mu0, 0~1)과 불확실성(var0, 분산).
값은 지질 단위에서 먼저 정하고 광물로 조정한다. 표와 계산 규칙은 config/prior_table.yaml 머리말에 있다.
이 모듈은 그 규칙을 그대로 계산할 뿐이고 수치를 따로 갖고 있지 않다.

지도에 굽지 않는 것: 선행 임무의 샘플 결과. 그것은 번들의 events0.json에 "확인된 관측" 이벤트로 넣어
코어가 다른 관측과 같은 식으로 반영한다(S3a §5). 지금은 샘플의 좌표를 확보하지 못해 빈 목록이다.
"""
from __future__ import annotations

import numpy as np

from .layers import MINERAL_KEYS, UNIT_CODES


def _row_stats(table: dict, name: str) -> tuple[float, float]:
    """등급표 한 줄의 (값, 분산).

    값   = 다섯 칸의 등급을 구간의 가운데로 옮긴 수의 평균
    분산 = 다섯 칸 사이의 분산 + 구간 폭² / 12
           뒤 항은 "등급 하나가 구간 안의 어디인지 모른다"는 불확실성이다(구간 안에서 고르다고 볼 때의 분산).
           이것이 없으면 다섯 칸이 전부 같은 줄(예: 전부 −)의 분산이 0이 되어 "확실히 낮다"로 읽힌다.
    """
    scale = table["grade_scale"]
    vals = np.array([scale[g] for g in table["rows"][name]["grades"]], dtype=np.float64)
    width = 1.0 / len(scale)                                  # 등급 하나가 차지하는 구간의 폭 (4단계면 0.25)
    return float(vals.mean()), float(vals.var()) + width * width / 12.0


def entry_value(table: dict, entry: dict) -> tuple[float, float]:
    """표의 한 항목(rows, alt)에서 (mu, var)를 계산한다. 규칙은 prior_table.yaml 머리말."""
    stats = [_row_stats(table, r) for r in entry["rows"]]
    means = np.array([m for m, _ in stats])
    mu = float(means.mean())
    var = float(np.mean([v for _, v in stats])) + float(means.var())
    if entry.get("alt"):
        # 다른 해석이 맞설 때: 값은 주된 해석에 두고, "그 값에서 벗어날 수 있는 정도"를 분산에 더한다.
        # 다른 해석이 맞을 확률을 p라 하면 주된 값 기준의 평균 제곱 편차는 p·차이² 이다. p를 모르므로 반반(0.5)으로 둔다.
        # (베이지안 모형 평균의 p(1−p)·차이²은 값도 두 해석의 평균으로 옮겼을 때의 식이라 여기에는 맞지 않는다 — 2026-11-14 조사에서 바로잡음)
        alt_mu = float(np.mean([_row_stats(table, r)[0] for r in entry["alt"]]))
        var += 0.5 * (mu - alt_mu) ** 2
    return mu, var


def lookup(table: dict) -> dict:
    """(단위 기호, 광물 열쇠 또는 None) → (mu, var). 화면의 바탕표 패널과 메타에도 이 사전을 쓴다."""
    out = {}
    for unit, entry in table.get("units", {}).items():
        out[(unit, None)] = entry_value(table, entry)
    for unit, minerals in table.get("cells", {}).items():
        for mineral, entry in minerals.items():
            out[(unit, mineral)] = entry_value(table, entry)
    return out


def rasterize(units: np.ndarray | None, minerals: np.ndarray | None, table: dict, shape: tuple[int, int]):
    """단위 번호 격자와 광물 분류 격자에서 (mu0, var0, grade_bins)를 만든다.

    units    — layers.load_units의 결과(없으면 None)
    minerals — layers.load_minerals의 분류 번호(없으면 None)
    값이 없는 칸(표에 없는 단위, 지도 범위 밖)은 NaN으로 둔다. 코어는 NaN 칸을 "가치 0, 불확실성 0"으로 읽는다.
    grade_bins — 값이 있는 칸의 mu0를 3등분하는 경계(LOW/MED, MED/HIGH). 옵션 카드의 등급 표시에 쓴다(S2 §5).
    """
    mu = np.full(shape, np.nan, dtype=np.float32)
    var = np.full(shape, np.nan, dtype=np.float32)
    if units is not None:
        values = lookup(table)
        code_to_unit = {code: sym for sym, code in UNIT_CODES.items()}
        for code in np.unique(units):
            sym = code_to_unit.get(int(code))
            if (sym, None) not in values:
                continue                                      # 표에 없는 단위 → 값 없음
            here = units == code
            mu[here], var[here] = values[(sym, None)]
            if minerals is None:
                continue
            for num, key in MINERAL_KEYS.items():
                if (sym, key) in values:
                    cell = here & (minerals == num)
                    mu[cell], var[cell] = values[(sym, key)]
    known = mu[np.isfinite(mu)]
    bins = (float(np.quantile(known, 1 / 3)), float(np.quantile(known, 2 / 3))) if known.size else (0.0, 0.0)
    return mu, var, bins
