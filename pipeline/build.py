"""번들을 만드는 진입점.

    python -m pipeline.build --site config/site.yaml --out data/bundles/jezero_west_v1

순서: 고도(10a) → 경사·거칠기(10b) → 태양 표 → 그림자·가시선(10b) → 광물·지질 단위(10c) → 바탕 지도(10e) → 지점(10f) → 쓰기(10g)
고도 자료가 없으면 멈춘다. 광물·지질 자료가 없으면 경고만 남기고 끝까지 간다(메타의 missing_layers에 적힌다).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import yaml

from . import bundle, dtm, layers, poi, prior, register, suntable, terrain, tiles, weather


class MissingSource(Exception):
    """꼭 있어야 하는 원천 자료(고도)가 없다."""


def _params_list(params: dict, prefix: str = "") -> list[dict]:
    """params.yaml을 메타의 params 목록(S2 §6 ParamRef)으로 편다. 번들을 만들 때의 값을 기록해 두는 것이다."""
    out = []
    for key, node in params.items():
        if key == "version" or not isinstance(node, dict):
            continue
        if "status" in node:
            val = node.get("value")
            out.append({"key": prefix + key, "value": val if isinstance(val, (int, float, str)) or val is None else json.dumps(val),
                        "unit": node.get("unit", ""), "source": node.get("source", ""), "status": node["status"]})
        else:
            out += _params_list(node, prefix + key + ".")
    return out


def run(site_path: str, out_dir: str, params_path: str = "config/params.yaml", tiers_path: str = "config/tiers.yaml",
        prior_path: str = "config/prior_table.yaml") -> dict:
    site = yaml.safe_load(Path(site_path).read_text())
    # 배치 스크립트(scripts/place_scenario.py)가 정한 주차점·지점이 있으면 site.yaml의 것 대신 쓴다
    placed = Path(site_path).with_name("placement.yaml")
    if placed.exists():
        pl = yaml.safe_load(placed.read_text())
        site["rover_parks"], site["pois"] = pl["rover_parks"], pl["pois"]
        site["scenario_hint"] = pl.get("scenario_hint", {})
        print(f"  배치: {placed} 의 주차점·지점을 쓴다")
    params = yaml.safe_load(Path(params_path).read_text())
    tiers = yaml.safe_load(Path(tiers_path).read_text())
    table = yaml.safe_load(Path(prior_path).read_text())
    out = Path(out_dir)
    (out / "field").mkdir(parents=True, exist_ok=True)
    (out / "rover").mkdir(parents=True, exist_ok=True)
    crs = dtm.local_crs(site)
    tp = params["terrain"]
    n_bins = int(tp["shadow_bins"]["value"])
    products = site["products"]
    if not Path(products["dtm"]["path"]).exists():
        raise MissingSource(products["dtm"]["path"])

    def step(msg: str, t0: float) -> None:
        print(f"  {msg} ({time.time() - t0:.1f} s)")

    layer_list, missing = [], []
    src_dtm = bundle.source_ref(products["dtm"])
    # 정합 기록: 레이어마다 "기준(고도 자료)에 어떻게 맞췄나". 열쇠는 레이어 메타의 registration이 가리킨다 (pipeline/register.py)
    registration = {"dtm": {"method": "기준. 다른 레이어를 전부 여기에 맞춘다", "reference": products["dtm"]["product_id"], "after_m": 0.0}}

    # 태양 표 — 그림자를 구울 때 구간마다 대표 시각의 태양 위치가 필요하다
    t0 = time.time()
    sun = suntable.build(site, n_bins)
    (out / "sun_table.json").write_text(json.dumps(sun))
    step(f"태양 표: 일출 {sun['sunrise_lmst']} 일몰 {sun['sunset_lmst']} (지방 평균시), Ls {sun['ls_deg']}°", t0)

    # 기상 리플레이: 태양 표와 같은 날의 실측 먼지·기온을 분 단위 표로
    env_info, env_files = {}, []
    if site.get("weather") and Path(site["weather"]["tau"]["path"]).exists():
        t0 = time.time()
        (out / "env").mkdir(exist_ok=True)
        rows, env_info = weather.build(site, sun)
        with open(out / env_info["file"], "w", newline="") as f:
            wr = __import__("csv").DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
        env_files.append(env_info["file"])
        step(f"기상 리플레이 sol {env_info['sol']}: tau {env_info['tau_min']}~{env_info['tau_max']} (선외활동 8시간 안에서는 {env_info['tau_eva_min']}~{env_info['tau_eva_max']}), "
             f"실측이 있는 분 {env_info['tau_measured_pct']} %, 기온이 있는 분 {env_info['t_air_pct']} %, 기록 전체의 95 % 지점 {env_info['tau_p95_record']}", t0)

    parks = [{"id": p["id"], "xy": list(poi.site_xy(site, p))} for p in site.get("rover_parks", [])]

    # 지형 레이어: 기기용(field, 5 m)과 로버용(rover, 2 m)
    for level, res in (("field", float(site["levels_m"]["field"])), ("rover", float(site["levels_m"]["rover"]))):
        t0 = time.time()
        elev, grid = dtm.load_and_grid(site, res)
        slope = terrain.slope_deg(elev, res)
        rough = terrain.roughness(elev, res, float(tp["roughness_win_m"]["value"]))
        shadow = np.stack([terrain.shadow_mask(elev, res, b["elev_deg"], b["az_deg"], float(tp["horizon_max_m"]["value"]))
                           for b in sun["bins"]])
        tag = f"{int(res)}m"
        derived = ["elev"]
        if level == "field":
            bundle.write_f16(out / f"field/slope_{tag}.f16", slope)
            bundle.write_f16(out / f"field/roughness_{tag}.f16", rough)
            scale, offset = bundle.write_elev_u16(out / f"field/elev_{tag}.u16", elev)
            layer_list += [
                bundle.layer_meta("slope", f"field/slope_{tag}.f16", "f16", grid, "deg", src_dtm, "dtm", nodata=float("nan"), derived_from=derived),
                bundle.layer_meta("roughness", f"field/roughness_{tag}.f16", "f16", grid, "m", src_dtm, "dtm", nodata=float("nan"), derived_from=derived),
                bundle.layer_meta("elev", f"field/elev_{tag}.u16", "u16", grid, "m", src_dtm, "dtm", scale=scale, offset=offset, nodata=bundle.U16_NODATA),
            ]
        else:
            bundle.write_tif(out / f"rover/slope_{tag}.tif", slope, grid, crs)
            bundle.write_tif(out / f"rover/roughness_{tag}.tif", rough, grid, crs)
            bundle.write_tif(out / f"rover/elev_{tag}.tif", elev, grid, crs)
            layer_list += [
                bundle.layer_meta("slope", f"rover/slope_{tag}.tif", "tif", grid, "deg", src_dtm, "dtm", nodata=float("nan"), derived_from=derived),
                bundle.layer_meta("roughness", f"rover/roughness_{tag}.tif", "tif", grid, "m", src_dtm, "dtm", nodata=float("nan"), derived_from=derived),
                bundle.layer_meta("elev", f"rover/elev_{tag}.tif", "tif", grid, "m", src_dtm, "dtm", nodata=float("nan")),
            ]
        bundle.write_bits(out / f"{level}/shadow_{tag}.bits", shadow)
        layer_list.append(bundle.layer_meta("shadow", f"{level}/shadow_{tag}.bits", "bits", grid, "0/1", src_dtm, "dtm", bins=n_bins, derived_from=derived))
        for p in parks:
            # 이름은 los(가시선)지만 내용은 "UHF 링크가 되는 칸"이다 — 직선으로 보이는지가 아니라 전파 손실로 판정한다
            los, sight = terrain.link_mask(elev, res, tuple(p["xy"]), params["link"]["radio"])
            f = f"{level}/los_{p['id']}_{tag}.bits"
            bundle.write_bits(out / f, los)
            layer_list.append(bundle.layer_meta(f"los_{p['id']}", f, "bits", grid, "0/1", src_dtm, "dtm", derived_from=derived))
            if level == "field":
                p["los_file"] = f
                p["visible_pct"] = round(float(los.mean()) * 100, 1)
                p["optical_pct"] = round(float(sight.mean()) * 100, 1)
        s = slope[np.isfinite(slope)]
        step(f"{level} {tag}: {grid.h}×{grid.w}, 값 있음 {100 * np.isfinite(elev).mean():.1f} %, 경사 20° 초과 {100 * (s > 20).mean():.1f} %, "
             f"그림자(첫 구간) {100 * shadow[0].mean():.1f} %", t0)

    # 과학 격자: 광물 지도의 칸 크기를 따른다. 없으면 기본값
    t0 = time.time()
    has_min = "minerals" in products and Path(products["minerals"]["path"]).exists()
    has_geo = "geology" in products and Path(products["geology"]["path"]).exists()
    sres = float(products["minerals"]["resolution_m"]) if has_min else float(params["science"]["default_res_m"]["value"])
    sgrid = layers.science_grid(site, sres)
    minerals = units = None
    if has_min:
        # 광물 지도가 기준에서 얼마나 어긋났는지 잰다. 잰 값이 "칸의 절반"과 "측정 흩어짐의 2배"를 모두 넘을 때만 옮긴다 —
        # 분류 지도는 칸 단위라 그보다 잘게 옮겨도 칸의 값이 거의 달라지지 않고, 흩어짐 안의 값은 잡음과 구별되지 않는다
        mprod, shift = products["minerals"], (0.0, 0.0)
        if mprod.get("index_image") and "reference_image" in products and Path(mprod["index_image"]).exists():
            cls_src, _conf, m_transform, m_crs = layers.read_mineral_classes(site)
            rec = register.register_class_map(cls_src, m_transform, m_crs, mprod["index_image"], products["reference_image"]["path"], site)
            rec["applied"] = bool(rec["after_m"] > max(0.5 * sres, 2.0 * float(np.hypot(*rec["scatter_m"]))))
            if rec["applied"]:
                shift = (rec["shift_m"][0], rec["shift_m"][1])
            registration["minerals"] = rec
            print(f"  광물 지도 정합: 원자료(CRISM)의 밀림 {np.hypot(*rec['index']['center_shift_m']):.0f} m를 걷어 내고 재니 "
                  f"지도의 어긋남 동 {rec['shift_m'][0]:+.1f} m 북 {rec['shift_m'][1]:+.1f} m (분류 {len(rec['pairs'])}개, 흩어짐 {rec['scatter_m'][0]:.0f}/{rec['scatter_m'][1]:.0f} m) "
                  f"→ {'옮겼다' if rec['applied'] else '칸의 절반·흩어짐의 2배보다 작아 옮기지 않았다'}")
        else:
            registration["minerals"] = {"method": "원본의 좌표를 그대로 썼다. 위치를 확인하지 못했다(지수 그림 없음)", "after_m": None}
            print("  ⚠ 광물 지도의 위치를 확인하지 못했다(index_image 없음)")
        minerals, _conf = layers.load_minerals(site, sgrid, shift)
        minerals.tofile(out / "field/minerals.u8")
        layer_list.append(bundle.layer_meta("minerals", "field/minerals.u8", "u8", sgrid, "class", bundle.source_ref(
            products["minerals"], "신경망 분류 결과. 광물 이름은 가장 가까운 것으로 붙인 것이다(저자 readme). 번호는 pipeline/layers.py MINERAL_CLASSES"), "minerals", nodata=0))
    else:
        missing.append("minerals")
    if has_geo:
        # 지질 지도의 바탕 그림을 기준 그림에 맞춰 변환을 구하고, 그 변환으로 폴리곤을 옮긴다
        fit = None
        geo = products["geology"]
        if geo.get("base_image") and "reference_image" in products and Path(geo["base_image"]).exists() and Path(products["reference_image"]["path"]).exists():
            fit = register.register_images(geo["base_image"], products["reference_image"]["path"], site)
            registration["units"] = fit
            print(f"  지질 단위 정합: 바탕 그림의 밀림 {fit['before_m']:.1f} m → 맞춘 뒤 {fit['after_m']:.1f} m (90 %가 {fit['after_p90_m']:.1f} m 안), "
                  f"창 {fit['n_used']}/{fit['n_measured']}개, 구역 중심의 밀림 동 {fit['center_shift_m'][0]:+.1f} m 북 {fit['center_shift_m'][1]:+.1f} m")
        else:
            registration["units"] = {"method": "맞추지 않았다 — 바탕 그림 또는 기준 그림이 없다", "after_m": None}
            print("  ⚠ 지질 단위를 옮기지 못했다(바탕 그림 없음). 100 m쯤 어긋난 채로 들어간다")
        units = layers.load_units(site, sgrid, fit)
        units.tofile(out / "field/units.u8")
        if fit:                                               # 눈으로 확인하는 그림: 빨강 = 맞추기 전, 초록 = 맞춘 뒤
            (out / "qa").mkdir(exist_ok=True)
            register.overlay_png(str(out / "qa/units_on_reference.png"), products["reference_image"]["path"], site,
                                 layers.unit_rings(site, None), layers.unit_rings(site, fit))
        layer_list.append(bundle.layer_meta("units", "field/units.u8", "u8", sgrid, "class", bundle.source_ref(
            geo, "폴리곤을 정합 결과(메타의 registration.units)로 옮겨 고도 자료에 맞췄다. 번호는 pipeline/layers.py UNIT_CODES"), "units", nodata=0))
    else:
        missing.append("geology")
    mu0, var0, grade_bins = prior.rasterize(units, minerals, table, (sgrid.h, sgrid.w))
    bundle.write_f16(out / "field/mu0.f16", mu0)
    bundle.write_f16(out / "field/var0.f16", var0)
    src_prior = {"source": "config/prior_table.yaml", "product_id": "과학 가치 바탕표", "resolution_m": sres, "acquired": None,
                 "license": "", "url": None, "note": str(table.get("status", ""))}
    registration["prior"] = {"method": "지질 단위와 광물 레이어에서 계산한 것 — 두 레이어의 정합을 그대로 물려받는다",
                             "after_m": (registration.get("units") or {}).get("after_m")}
    layer_list += [bundle.layer_meta("mu0", "field/mu0.f16", "f16", sgrid, "0~1", src_prior, "prior", nodata=float("nan"), derived_from=["units", "minerals"]),
                   bundle.layer_meta("var0", "field/var0.f16", "f16", sgrid, "분산", src_prior, "prior", nodata=float("nan"), derived_from=["units", "minerals"])]
    step(f"과학 격자 {sgrid.h}×{sgrid.w} @ {sres:.0f} m: 값 있는 칸 {100 * np.isfinite(mu0).mean():.1f} %, 등급 경계 {grade_bins[0]:.3f} / {grade_bins[1]:.3f}", t0)

    pois = poi.build_pois(site, mu0, var0, sgrid)
    events0 = prior.initial_events(site, lambda lon, lat: dtm.lonlat_to_xy(site, lon, lat))
    (out / "events0.json").write_text(json.dumps(events0, ensure_ascii=False, indent=1))
    # 시료 지점은 지도 표시용으로 메타에 싣는다(유기물 보고가 확정된 것만 위의 이벤트가 된다)
    samples_meta = []
    for smp in site.get("samples", []):
        x, y = dtm.lonlat_to_xy(site, float(smp["lon_e"]), float(smp["lat_n"]))
        if 0.0 <= x <= 2 * float(site["aoi"]["half_size_m"]) and -2 * float(site["aoi"]["half_size_m"]) <= y <= 0.0:
            samples_meta.append({"id": smp["id"], "name": smp["name"], "cores": smp.get("cores", []), "xy": [round(x, 1), round(y, 1)],
                                 "lithology": smp.get("lithology", ""), "organics": smp.get("organics"), "note": smp.get("note", ""),
                                 "source": smp.get("source", "")})
    print(f"  선행 시료: 구역 안 {len(samples_meta)}곳, 그 가운데 관측 이벤트가 된 것 {len(events0)}건")
    (out / "config.json").write_text(json.dumps({"site": site, "tiers": tiers, "params": params, "prior_table": table}, ensure_ascii=False, default=str))
    if not env_files:
        missing.append("weather")
    missing += ["tiles", "photos"]                                # tiles는 끝에서 tiles.build가 만들고 이 목록에서 뺀다. photos는 아직 없다
    half = float(site["aoi"]["half_size_m"])
    meta = {
        "bundle_id": f"{site['site']}_v{site['bundle_version']}", "schema_version": 1, "site": site["site"],
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "crs": crs, "origin_xy_crs": [0.0, 0.0], "extent_m": [2 * half, 2 * half], "aoi_radius_m": half,
        "levels_m": [float(site["levels_m"]["field"]), float(site["levels_m"]["rover"])],
        "science_res_m": sres, "science_origin_xy": [0.0, 0.0],
        "layers": layer_list, "registration": registration, "pois": pois,
        "rover_parks": [{"id": p["id"], "xy": [round(p["xy"][0], 1), round(p["xy"][1], 1)], "los_file": p.get("los_file", "")} for p in parks],
        "params": _params_list(params), "grade_bins": list(grade_bins),
        "shadow_bins_lmst": [b["from_lmst"] for b in sun["bins"]] + [sun["bins"][-1]["to_lmst"]],
        "sun_table": "sun_table.json", "env_files": env_files, "env": env_info, "missing_layers": missing,
        "scenario_hint": site.get("scenario_hint", {}),
        "samples": samples_meta,
        "unit_codes": layers.UNIT_CODES, "mineral_codes": {key: num for num, key in layers.MINERAL_KEYS.items()},
        "prior_values": [{"unit": u, "mineral": m, "mu": round(v[0], 4), "var": round(v[1], 4)} for (u, m), v in prior.lookup(table).items()],
    }
    meta = bundle.finish(out, meta, float(params["bundle"]["field_limit_mb"]["value"]) * 1e6)
    t0 = time.time()
    tinfo = tiles.build(out)                                      # 표시용 타일 — 방금 쓴 레이어를 그림으로 굽고 메타에 tiles 항목을 더한다
    meta = json.loads((out / "meta.json").read_text())
    step(f"표시용 타일 {len(tinfo['layers'])}개 레이어", t0)
    print(f"  번들 {meta['bundle_id']}: field/ {meta['field_size_bytes'] / 1e6:.1f} MB, 파일 {len(meta['sha256'])}개, 링크 되는 칸 {[(p['id'], p.get('visible_pct')) for p in parks]} % (눈으로 보이는 칸 {[p.get('optical_pct') for p in parks]} %)")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="BingoTime 번들 만들기 (C-10)")
    ap.add_argument("--site", default="config/site.yaml")
    ap.add_argument("--out", required=True, help="번들을 쓸 폴더. 예: data/bundles/jezero_west_v1")
    args = ap.parse_args()
    print(f"번들 만들기: {args.site} → {args.out}")
    run(args.site, args.out)


if __name__ == "__main__":
    main()
