"""설정 파일 → 코어 설정 구조체.

코어는 YAML을 읽지 않는다. 이 모듈이 config/tiers.yaml과 config/params.yaml을 읽어 숫자만 담은 구조체(bt_config) 하나로
만들고, 그것을 Core.create에 넘긴다 (docs/spec/S4 §6).

    cfg = load_config("config/tiers.yaml", "config/params.yaml", "device", bundle.meta)    # 기기
    cfg = load_config("config/tiers.yaml", "config/params.yaml", "rover", bundle.meta)     # 로버

- 출처·상태(REF, TUNE …)는 코어에 넣지 않는다. 화면의 출처 표시는 번들 메타의 params 목록을 쓴다.
- 값이 비어 있는 TBD 항목은 placeholder가 있으면 그것을, 없으면 0을 넣는다(0 = "쓰지 않음"으로 약속된 항목들이다).
- 설정이 바뀌면 코어 인스턴스를 새로 만든다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import btcore as bt


def _v(node: dict, default: float = 0.0):
    """params.yaml의 항목 하나에서 값을 꺼낸다."""
    val = node.get("value")
    if val is None:
        val = node.get("placeholder", default)
    return val


def _layer(meta: dict, name: str, res_m: float | None = None) -> dict | None:
    """번들 메타에서 이름(과 칸 크기)이 맞는 레이어를 찾는다."""
    for lay in meta["layers"]:
        if lay["name"] == name and (res_m is None or abs(lay["res_m"] - res_m) < 1e-6):
            return lay
    return None


def load_config(tiers_path: str, params_path: str, tier: str, meta: dict, node: str | None = None) -> bt.BtConfig:
    """tier = "device" 또는 "rover". meta = 번들의 meta.json(격자 크기를 여기서 읽는다)."""
    t = yaml.safe_load(Path(tiers_path).read_text())["tiers"][tier]
    p = yaml.safe_load(Path(params_path).read_text())
    c = bt.BtConfig()

    # 격자: 이 설정의 탐색 격자(grid_m)와 칸 크기가 같은 경사 레이어를 쓴다 — 기기는 field/(5 m), 로버는 rover/(2 m)
    slope = _layer(meta, "slope", float(t["grid_m"])) or _layer(meta, "slope")
    c.cost_grid.res_m, c.cost_grid.h, c.cost_grid.w = slope["res_m"], slope["shape"][0], slope["shape"][1]
    mu0 = _layer(meta, "mu0")
    if mu0:
        c.science_grid.res_m, c.science_grid.h, c.science_grid.w = mu0["res_m"], mu0["shape"][0], mu0["shape"][1]
    shadow = _layer(meta, "shadow", slope["res_m"])
    c.shadow_bins = int(shadow["bins"]) if shadow else 0
    c.grade_bins[0], c.grade_bins[1] = meta["grade_bins"]

    # 설정 블록 (tiers.yaml)
    c.node = bt.NODE[node or ("suit-A" if tier == "device" else "rover")]
    c.grid_m = float(t["grid_m"])
    c.coarse_first_grid_m = float(t.get("coarse_first_grid_m") or 0.0)
    c.replan_radius_m = float(t["replan_radius_m"])
    c.max_expansions = int(t["max_expansions"])
    c.options_mode = bt.OPTMODE_PARETO if t["options"]["mode"] == "pareto" else bt.OPTMODE_RECEIVE
    c.options_max = int(t["options"].get("max", 3))
    c.options_min = int(t["options"].get("min", 1))
    sg = t.get("science_grid_m", "bundle")
    c.science_grid_m = 0.0 if sg == "bundle" else (-1.0 if sg is None or not mu0 else float(sg))   # 0 = 번들 격자 그대로, 음수 = 재계산 안 함

    # 이동·비용
    mob, cost, pl = p["mobility"], p["cost"], p["planner"]
    c.v_plan_kmh, c.v_return_kmh, c.theta_max_deg = _v(mob["v_plan_kmh"]), _v(mob["v_return_kmh"]), _v(mob["theta_max_deg"])
    for i, name in enumerate(("balanced", "fastest", "gentle")):            # 성향 번호 0, 1, 2
        c.profiles[i].w_s, c.profiles[i].w_r, c.profiles[i].w_sh, c.profiles[i].w_rad = _v(cost["profiles"][name])
    c.rough_ref_m, c.dose_ref = _v(cost["rough_ref_m"]), _v(cost["dose_ref"])
    eps = list(_v(pl["eps_schedule"]))[: bt.MAX_EPS]
    c.eps_n = len(eps)
    for i, e in enumerate(eps):
        c.eps[i] = e
    c.snap_max_m, c.alt_overlap_max, c.corridor_m = _v(pl["snap_max_m"]), _v(pl["alt_overlap_max"]), _v(pl["corridor_m"])

    # 과학 가치
    s = p["science"]
    for key in ("l0_m", "aniso_ratio", "exposure_slope_ref_deg", "obs_noise", "unconfirmed_factor", "tau_s", "r_obs_m",
                "w_transit", "A_ref_m2", "r_plan", "touch_eps", "var_floor"):
        setattr(c, key, _v(s[key]))

    # 결정 + 표시 정밀도
    d = p["decision"]
    for key in ("eps_fork", "cooldown_s", "stay_max_min", "stay_buffer_min", "hyp_snap_m"):
        setattr(c, key, _v(d[key]))
    for key, val in _v(d["display_precision"]).items():
        setattr(c, "prec_" + key, val)

    # 안전
    sf = p["safety"]
    for key in ("k_return", "nlt_warn_min", "nlt_force_min", "sunset_margin_min", "sunset_warn_min", "dose_warn_uSv"):
        setattr(c, key, _v(sf[key]))
    c.eva_max_h = _v(p["suit"]["eva_max_h"])
    c.dust_tau_warn = _v(p["env"]["dust_tau_warn"])
    c.dust_hold_s = _v(p["env"]["dust_hold_s"])

    # 연결
    ln = p["link"]
    for ch in ("uhf", "wifi"):
        dst = getattr(c, ch)
        for key in ("timeout_ms", "n_down", "n_up", "ewma_alpha", "loss_down", "rtt_down_ms"):
            setattr(dst, key, type(getattr(dst, key))(_v(ln[ch][key])))
    c.lost_dp_s, c.hb_hz = _v(ln["lost_dp_s"]), _v(ln["hb_hz"])
    return c


def dose_rate_uSv_h(params_path: str) -> float:
    """평상시 선량률(µSv/h) = radiation.dose_rate_mSv_day를 시간당으로 바꾼 값. 환경 자료가 없을 때 bt_env에 넣는다."""
    p = yaml.safe_load(Path(params_path).read_text())
    return float(_v(p["radiation"]["dose_rate_mSv_day"])) * 1000.0 / 24.0
