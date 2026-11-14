"""C-10g — 번들을 디스크에 쓴다 (형식: docs/spec/S1 §5, 메타: S2 §6).

번들 = 한 지역의 STATIC 자료 묶음. 지구에서 만들고 현장에서는 읽기만 한다.

    meta.json            번들 메타(BundleMeta). 레이어마다 파일·형식·격자·출처가 적혀 있다 — 읽는 쪽은 이것만 믿는다
    config.json          번들을 만든 설정의 기록(site, tiers, params, prior_table)
    sun_table.json       분 단위 태양 표
    events0.json         초기 이벤트(선행 임무 샘플). 지금은 빈 목록
    field/               기기용 (5 m). 코어가 그대로 읽는 raw 배열. 합계 50 MB 이하
        slope_5m.f16         경사(°). float16, row-major, 값 없음 = NaN
        roughness_5m.f16     거칠기(m)
        elev_5m.u16          고도. 실제 값 = 저장값 × scale + offset (메타). 값 없음 = 65535
        shadow_5m.bits       그림자, 시간 구간마다 한 장. 1 = 그림자 (비트 순서는 terrain.pack_bits)
        los_<주차점>_5m.bits  가시선. 1 = 로버가 보임
        mu0.f16 · var0.f16   과학 가치 바탕 지도 (과학 격자). 값 없음 = NaN
        units.u8             지질 단위 번호 (과학 격자). 0 = 없음
        minerals.u8          광물 분류 번호 (과학 격자). 화면 표시용 — 코어는 읽지 않는다
    rover/               로버용 (2 m). 큰 래스터는 GeoTIFF(float32), 비트 마스크는 field/와 같은 형식
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio

from .dtm import Grid
from .terrain import pack_bits

ELEV_STEP_M = 0.05          # 고도를 u16으로 담는 단위 (S1 §5)
U16_NODATA = 65535


def write_f16(path: Path, a: np.ndarray) -> None:
    a.astype("<f2").tofile(path)


def write_elev_u16(path: Path, elev: np.ndarray) -> tuple[float, float]:
    """고도를 "가장 낮은 칸에서 몇 단위 위인가"로 바꿔 u16으로 쓴다. (scale, offset)을 돌려준다 — 메타에 적는다."""
    base = float(np.nanmin(elev))
    q = np.rint((elev - base) / ELEV_STEP_M)
    if np.nanmax(q) >= U16_NODATA:
        raise ValueError("고도 범위가 u16에 담기지 않는다 (3,276 m 초과)")
    np.where(np.isfinite(elev), q, U16_NODATA).astype("<u2").tofile(path)
    return ELEV_STEP_M, base


def write_tif(path: Path, a: np.ndarray, grid: Grid, crs: str) -> None:
    with rasterio.open(path, "w", driver="GTiff", height=grid.h, width=grid.w, count=1, dtype="float32", crs=crs,
                       transform=grid.transform, nodata=float("nan"), compress="deflate", predictor=3, tiled=True) as dst:
        dst.write(a.astype(np.float32), 1)


def write_bits(path: Path, mask: np.ndarray) -> None:
    path.write_bytes(pack_bits(mask))


def layer_meta(name: str, file: str, dtype: str, grid: Grid, unit: str, source: dict, registration: str, *, bins: int | None = None,
               scale: float = 1.0, offset: float = 0.0, nodata: float | None = None, derived_from: list[str] | None = None) -> dict:
    """메타의 레이어 한 줄 (S2 §6 LayerMeta).

    registration — 이 레이어가 기준(고도 자료)에 어떻게 맞춰졌는지를 가리키는 열쇠. 메타의 registration 사전에 같은 열쇠의
    기록이 있어야 한다. 빈 문자열은 허용하지 않는다 — 정합을 따지지 않은 레이어가 번들에 섞이는 것을 막는다.
    """
    if not registration:
        raise ValueError(f"레이어 {name}: 정합 기록이 없다")
    return {"name": name, "file": file, "dtype": dtype, "res_m": grid.res_m, "shape": [grid.h, grid.w], "bins": bins,
            "scale": scale, "offset": offset, "unit": unit, "nodata": nodata, "source": source, "derived_from": derived_from or [],
            "registration": registration}


def source_ref(product: dict | None, note: str = "") -> dict:
    """site.yaml의 products 항목 → 메타의 출처(S2 §6 SourceRef)."""
    p = product or {}
    return {"source": p.get("source", ""), "product_id": p.get("product_id", "TBD"), "resolution_m": p.get("resolution_m"),
            "acquired": p.get("acquired"), "license": p.get("license", ""), "url": p.get("url"), "note": note}


def finish(out: Path, meta: dict, limit_bytes: float) -> dict:
    """파일 해시와 field/ 크기를 메타에 채우고 meta.json을 쓴다. field/가 한도를 넘으면 실패한다."""
    sha, field_bytes = {}, 0
    for f in sorted(out.rglob("*")):
        if not f.is_file() or f.name == "meta.json":
            continue
        rel = f.relative_to(out).as_posix()
        sha[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
        if rel.startswith("field/"):
            field_bytes += f.stat().st_size
    for lay in meta["layers"]:                                # 레이어마다 정합 기록이 실제로 있는지 다시 본다
        if lay["registration"] not in meta.get("registration", {}):
            raise ValueError(f"레이어 {lay['name']}: 정합 기록 '{lay['registration']}'이 메타에 없다")
    meta["sha256"] = sha
    meta["field_size_bytes"] = field_bytes
    if field_bytes > limit_bytes:
        raise ValueError(f"field/ 가 {field_bytes / 1e6:.1f} MB — 한도 {limit_bytes / 1e6:.0f} MB를 넘는다")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta
