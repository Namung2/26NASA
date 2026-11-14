"""태양 고도·방위 표 — NASA GISS "Mars24 Sunclock" 계산 절차를 옮긴 것.

근거: Allison & McEwen 2000 (Planet. Space Sci. 48, 215–235), GISS "Mars24 Sunclock — Algorithm and Worked Examples"
      (giss.nasa.gov/tools/mars24/help/algorithm.html). 단계 이름(A-5, B-1 …)은 그 페이지의 것이다.
검증 (2026-11-14): GISS가 실은 계산 예제 2건을 넣어 본 값
    2000-01-06 00:00 UTC, 0°N 0°W        → Ls 277.18759°, 균시차 -5.18775°, 평균시 23:59:39, 진태양시 23:38:54, 방위 191.04°
    2004-01-03 13:46:31 UTC, Spirit 지점 → Ls 327.32416°, 적위 -13.42040°, 진태양시 00:00:01, 방위 179.99°
  페이지의 값(277.18758°, -5.18774°, 23:38:54, 191.04° / 327.32416°, -13.42065°, 179.99°)과 다섯째 자리에서 1,
  적위는 0.00025° 다르다. 그림자를 굽는 데는 영향이 없는 차이다. 정식 시험은 tests/unit/test_suntable.py에 둔다(S7 §5).
정확도: 태양 황경 오차 최대 0.008°, 진태양시 최대 3초, 일출·일몰 30초 미만(지형·대기 효과 제외) — GISS 기술 노트.

이 모듈이 만드는 표는 번들의 sun_table.json이 된다. 실행 중에 호스트가 표에서 지금 시각의 줄을 찾아 코어에 넣는다(bt_set_env).
"""
from __future__ import annotations

import datetime as dt
import math

SOL_S = 88775.244147          # 화성의 하루(sol) = 지구의 초로
TT_MINUS_UTC_S = 69.184       # 2017-01-01 이후의 지구시 − 협정세계시 (윤초 37 + 32.184)


def _julian_date(t: dt.datetime) -> float:
    """협정세계시 → 율리우스일."""
    return 2440587.5 + (t - dt.datetime(1970, 1, 1)).total_seconds() / 86400.0


def mars24(jd_ut: float, lon_e: float, lat_n: float, tt_minus_utc_s: float = TT_MINUS_UTC_S) -> dict:
    """한 시각, 한 지점의 화성 시각과 태양 위치.

    돌려주는 값: ls(태양 황경 °), eot_deg(균시차 °), mst_h(본초 자오선 평균시), lmst_h(지방 평균 태양시),
                ltst_h(지방 진태양시), dec_deg(태양 적위), elev_deg(태양 고도), az_deg(태양 방위: 북에서 시계 방향)
    """
    lon_w = (-lon_e) % 360.0                                   # 이 절차는 서경을 쓴다
    jd_tt = jd_ut + tt_minus_utc_s / 86400.0                   # A-5
    d = jd_tt - 2451545.0                                      # A-6: J2000부터의 날수
    m = 19.3871 + 0.52402073 * d                               # B-1: 평균 근점각
    a_fms = 270.3871 + 0.524038496 * d                         # B-2: 가상 평균 태양의 각
    pert = ((0.0071, 2.2353, 49.409), (0.0057, 2.7543, 168.173), (0.0039, 1.1177, 191.837), (0.0037, 15.7866, 21.736),
            (0.0021, 2.1354, 15.704), (0.0020, 2.4694, 95.528), (0.0018, 32.8493, 49.095))
    pbs = sum(a * math.cos(math.radians(0.985626 * d / tau + phi)) for a, tau, phi in pert)   # B-3: 행성 섭동
    mr = math.radians(m)
    eoc = ((10.691 + 3.0e-7 * d) * math.sin(mr) + 0.623 * math.sin(2 * mr) + 0.050 * math.sin(3 * mr)
           + 0.005 * math.sin(4 * mr) + 0.0005 * math.sin(5 * mr) + pbs)                      # B-4: 중심차
    ls = (a_fms + eoc) % 360.0                                 # B-5: 태양 황경
    lr = math.radians(ls)
    eot = 2.861 * math.sin(2 * lr) - 0.071 * math.sin(4 * lr) + 0.002 * math.sin(6 * lr) - eoc   # C-1: 균시차(°)
    mst = (24.0 * (((jd_tt - 2451549.5) / 1.0274912517) + 44796.0 - 0.0009626)) % 24.0       # C-2
    lmst = (mst - lon_w / 15.0) % 24.0                         # C-3
    ltst = (lmst + eot / 15.0) % 24.0                          # C-4
    subsolar_w = (mst * 15.0 + eot + 180.0) % 360.0            # C-5: 태양 직하점의 서경
    dec = math.degrees(math.asin(0.42565 * math.sin(lr))) + 0.25 * math.sin(lr)               # D-1: 태양 적위
    hour = math.radians(lon_w - subsolar_w)                    # 시간각
    phi, dl = math.radians(lat_n), math.radians(dec)
    cos_z = math.sin(dl) * math.sin(phi) + math.cos(dl) * math.cos(phi) * math.cos(hour)      # D-5
    elev = 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_z))))
    az = math.degrees(math.atan2(math.sin(hour), math.cos(phi) * math.tan(dl) - math.sin(phi) * math.cos(hour))) % 360.0   # D-6
    return {"ls": ls, "eot_deg": eot, "mst_h": mst, "lmst_h": lmst, "ltst_h": ltst, "dec_deg": dec, "elev_deg": elev, "az_deg": az}


def _hhmm(h: float) -> str:
    m = int(round(h * 60.0)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def build(site: dict, n_bins: int) -> dict:
    """그날 그 자리의 태양 표를 화성 분(하루의 1/1440) 간격으로 만든다.

    돌려주는 사전 (sun_table.json 그대로)
        lmst_min[i]   지방 평균 태양시, 분 (0 ~ 1439)
        ltst_h[i]     지방 진태양시, 시 (평균시와 수십 분 다르다 — 균시차)
        t_eva_s[i]    EVA 경과 초 (site.sun.eva_start_lmst가 0초). 시작 전은 음수
        elev_deg[i], az_deg[i]
        shadow_bin[i] 그 시각이 속한 그림자 구간 (0 ~ n_bins-1). 낮(일출~일몰)을 n_bins로 똑같이 나눈 것. 밤은 가까운 끝 구간
        sunrise_lmst, sunset_lmst, t_sunset_s   고도가 0°를 지나는 시각(표에서 보간)
        bins[b]       구간의 경계 시각과, 그림자를 구울 때 쓴 대표 시각(구간 가운데)의 태양 고도·방위
    """
    aoi, sun = site["aoi"], site["sun"]
    lon, lat = float(aoi["center_lon_e"]), float(aoi["center_lat_n"])
    jd = _julian_date(dt.datetime.fromisoformat(str(sun["date_utc"])))
    step_d = SOL_S / 1440.0 / 86400.0
    # 지방 평균시가 00:00을 지나는 순간을 찾아 거기서부터 한 sol
    prev = mars24(jd, lon, lat)["lmst_h"]
    for _ in range(1500):
        jd += step_d
        cur = mars24(jd, lon, lat)["lmst_h"]
        if cur < prev:
            break
        prev = cur
    rows = [mars24(jd + i * step_d, lon, lat) for i in range(1440)]
    lmst_min = [r["lmst_h"] * 60.0 for r in rows]
    elev = [r["elev_deg"] for r in rows]

    def crossing(rising: bool) -> float:
        """고도가 0°를 지나는 지방 평균시(분). 표의 이웃한 두 줄 사이를 직선으로 보간한다."""
        for i in range(1, 1440):
            a, b = elev[i - 1], elev[i]
            if (a < 0.0 <= b) if rising else (a >= 0.0 > b):
                return lmst_min[i - 1] + (lmst_min[i] - lmst_min[i - 1]) * (0.0 - a) / (b - a)
        raise ValueError("이 날 이 자리에서는 해가 뜨거나 지지 않는다")

    sunrise, sunset = crossing(True), crossing(False)
    hh, mm = str(sun["eva_start_lmst"]).split(":")
    start_min = int(hh) * 60 + int(mm)
    sec_per_min = SOL_S / 1440.0                                # 화성의 1분은 지구의 61.65초
    width = (sunset - sunrise) / n_bins
    bins = []
    for b in range(n_bins):
        mid = sunrise + (b + 0.5) * width
        r = rows[min(1439, int(round(mid - lmst_min[0])))]
        bins.append({"from_lmst": _hhmm((sunrise + b * width) / 60.0), "to_lmst": _hhmm((sunrise + (b + 1) * width) / 60.0),
                     "mid_lmst": _hhmm(mid / 60.0), "elev_deg": round(r["elev_deg"], 3), "az_deg": round(r["az_deg"], 3)})
    return {
        "source": "NASA GISS Mars24 계산 절차 (Allison & McEwen 2000)를 pipeline/suntable.py에 구현",
        "date_utc": str(sun["date_utc"]), "lon_e": lon, "lat_n": lat, "ls_deg": round(rows[720]["ls"], 3),
        "eva_start_lmst": str(sun["eva_start_lmst"]),
        "sunrise_lmst": _hhmm(sunrise / 60.0), "sunset_lmst": _hhmm(sunset / 60.0),
        "t_sunset_s": round((sunset - start_min) * sec_per_min, 1),
        "bins": bins,
        "lmst_min": [round(v, 3) for v in lmst_min],
        "ltst_h": [round(r["ltst_h"], 4) for r in rows],           # 지방 진태양시. 공개된 먼지 자료가 이 시각으로 적혀 있어서 맞출 때 쓴다
        "t_eva_s": [round((v - start_min) * sec_per_min, 1) for v in lmst_min],
        "elev_deg": [round(v, 3) for v in elev],
        "az_deg": [round(r["az_deg"], 3) for r in rows],
        "shadow_bin": [int(min(n_bins - 1, max(0, math.floor((v - sunrise) / width)))) for v in lmst_min],
    }
