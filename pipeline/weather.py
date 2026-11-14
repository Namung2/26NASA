"""기상 리플레이 — 실제 화성의 하루치 먼지·기온 기록을 번들에 넣는다 (S1 §5의 env/weather_<id>.csv).

시뮬레이터가 이 표를 시각에 따라 재생하면 "선외활동 도중에 먼지가 짙어지는" 상황이 실제 기록대로 나온다.
표의 줄은 태양 표(sun_table.json)와 같은 1,440줄(화성의 분)이고 같은 순서다 → 같은 번호로 찾으면 된다.

    tau          먼지 광학 두께. ※ 9 µm 적외선에서의 값이다(먼지 + 얼음 안개의 소광). 흔히 말하는 가시광 tau의 절반쯤인데
                 그 비율이 1.3~3배로 일정하지 않아서 환산하지 않고 그대로 쓴다. 경고 임계값(env.dust_tau_warn)도 같은 양으로 정한다.
    tau_measured 1 = 그 시각 10분 안에 실제 측정이 있다, 0 = 앞뒤 측정 사이를 이은 값(태양이 센서 시야에 드는 오후 등)
    t_air_k      기온(K). 돛대의 센서 셋(1.45 m 높이)의 가운데 값, 분 평균. 측정이 없는 분은 빈칸

자료
    tau    Smith, M. D. (2022), "Perseverance MEDA/TIRS aerosol retrievals", Mendeley Data V1, doi 10.17632/48phhtkcj8.1 (CC BY 4.0).
           Smith 등 2023, JGR Planets 128, e2022JE007560의 자료. MEDA의 적외선 센서(TIRS)에서 5분 간격으로 뽑은 값, sol 15~400.
    기온   NASA PDS Atmospheres Node, Mars 2020 MEDA 번들(doi 10.17189/1522849)의 보정 자료 CAL_ATS, 1초 간격.
    두 자료 모두 지방 진태양시(LTST)로 시각이 적혀 있어서 태양 표의 ltst_h와 맞춘다.
"""
from __future__ import annotations

import csv

import numpy as np


def tau_record(path: str) -> np.ndarray:
    """tau 표 전체를 읽는다. 열: [LTST(시), tau, sol]."""
    a = np.loadtxt(path, skiprows=1)
    return np.c_[a[:, 0], a[:, 1], a[:, 7]]


def tau_percentile(path: str, pct: float) -> float:
    """기록 전체에서 "값의 pct %가 이 아래"인 tau. 경고 임계값을 정할 때 쓴다(build가 계산해 메타에 적는다)."""
    return float(np.percentile(tau_record(path)[:, 1], pct))


def _unwrapped_ltst(sun: dict) -> np.ndarray:
    """태양 표의 진태양시를 자정을 넘어도 이어지게 편다(다음 날로 넘어간 뒤는 +24)."""
    lt = np.asarray(sun["ltst_h"], dtype=np.float64)
    wrap = np.concatenate([[0.0], np.cumsum(np.diff(lt) < -12.0)])
    return lt + 24.0 * wrap


def build(site: dict, sun: dict) -> tuple[list[dict], dict]:
    """site.yaml의 weather 설정으로 분 단위 표와 그 설명(메타)을 만든다."""
    w = site["weather"]
    sol = int(w["sol"])
    lt = _unwrapped_ltst(sun)

    # 먼지: 그 sol과 다음 sol의 측정을 이어 놓고(자정 너머까지) 분마다 값을 읽는다
    rec = tau_record(w["tau"]["path"])
    day = rec[(rec[:, 2] == sol) | (rec[:, 2] == sol + 1)]
    t_meas = day[:, 0] + 24.0 * (day[:, 2] - sol)
    order = np.argsort(t_meas)
    t_meas, v_meas = t_meas[order], day[order, 1]
    tau = np.interp(lt, t_meas, v_meas)
    nearest = np.abs(lt[:, None] - t_meas[None, :]).min(axis=1)
    measured = (nearest <= 10.0 / 60.0).astype(int)

    # 기온: 1초 자료를 분 평균으로. 돛대 센서 1~3의 가운데 값(차체 가까운 4·5번은 로버의 열을 받을 수 있다)
    t_air = np.full(len(lt), np.nan)
    if w.get("air_temp"):
        hours, temps = [], []
        with open(w["air_temp"]["path"], newline="") as f:
            for row in csv.DictReader(f):
                s, hms = row["LTST"].split()
                hh, mm, ss = hms.split(":")
                vals = [float(row[k]) for k in ("ATS_LOCAL_TEMP1", "ATS_LOCAL_TEMP2", "ATS_LOCAL_TEMP3") if row[k] not in ("", None)]
                if not vals:
                    continue
                hours.append(int(hh) + int(mm) / 60.0 + float(ss) / 3600.0 + 24.0 * (int(s) - sol))
                temps.append(float(np.median(vals)))
        hours, temps = np.asarray(hours), np.asarray(temps)
        idx = np.clip(np.searchsorted(lt, hours) - 1, 0, len(lt) - 1)         # 그 측정이 속한 분
        ok = (hours >= lt[0]) & (hours < lt[-1] + (lt[-1] - lt[-2]))
        sums, counts = np.zeros(len(lt)), np.zeros(len(lt))
        np.add.at(sums, idx[ok], temps[ok])
        np.add.at(counts, idx[ok], 1)
        t_air = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)

    rows = [{"lmst_min": round(float(sun["lmst_min"][i]), 3), "ltst_h": round(float(sun["ltst_h"][i]), 4), "tau": round(float(tau[i]), 4),
             "tau_measured": int(measured[i]), "t_air_k": "" if np.isnan(t_air[i]) else round(float(t_air[i]), 2)} for i in range(len(lt))]
    eva = np.asarray(sun["t_eva_s"])
    inside = (eva >= 0) & (eva <= 8 * 3600)
    info = {
        "id": f"sol{sol}", "sol": sol, "file": f"env/weather_sol{sol}.csv",
        "tau_kind": "9 µm 적외선 소광 광학 두께(먼지 + 얼음). 가시광 tau가 아니다 — 환산하지 않았다",
        "tau_source": w["tau"].get("source", ""), "air_temp_source": (w.get("air_temp") or {}).get("source", ""),
        "tau_measured_pct": round(float(measured.mean()) * 100, 1), "t_air_pct": round(float(np.isfinite(t_air).mean()) * 100, 1),
        "tau_min": round(float(tau.min()), 3), "tau_max": round(float(tau.max()), 3),
        "tau_eva_min": round(float(tau[inside].min()), 3), "tau_eva_max": round(float(tau[inside].max()), 3),
        "tau_p95_record": round(tau_percentile(w["tau"]["path"], 95.0), 3),
        "radiation": "측정 자료 없음(Jezero에는 방사선 측정기가 없다). 평상시 선량률(params.yaml radiation)에 시나리오가 SPE를 얹는다",
    }
    return rows, info
