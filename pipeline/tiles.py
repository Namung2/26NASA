"""표시용 타일 (S1 §5의 tiles/, S3a C-10g, R-06).

화면의 지도는 번들의 숫자 레이어를 직접 읽지 않는다. 여기서 미리 그림(PNG 타일)으로 구워 둔 것을 겹쳐 보인다.
숫자 레이어가 바뀌면(번들을 다시 만들면) 이 타일도 다시 굽는다 — build.py가 끝에서 부른다. 따로 돌릴 수도 있다:

    .venv/bin/python -m pipeline.tiles data/bundles/jezero_west_v1

■ 타일 좌표 (웹 지도의 경위도 타일이 아니다 — 활동 구역의 로컬 미터 좌표를 그대로 쓴다)
  - 구역 전체(원점 = 북서쪽 모서리, 한 변 extent_m)를 확대 단계 z에서 2^z × 2^z장으로 나눈다. 한 장은 256 × 256 픽셀.
  - tiles/<레이어>/<z>/<x>/<y>.png — x는 서→동, y는 북→남으로 센다. (x, y) 타일이 덮는 범위:
        동서 [x, x+1] · extent / 2^z,  남북 −[y, y+1] · extent / 2^z   (로컬 좌표의 y는 북쪽이 +라서 구역 안은 음수)
  - z = 0(한 장, 약 19.5 m/픽셀) … z = 3(64장, 약 2.4 m/픽셀). 한 변 5 km 기준.
  화면(Leaflet)은 CRS.Simple에 배율 256 / extent_m를 주면 이 타일이 로컬 좌표에 그대로 놓인다.

■ 레이어 (메타의 tiles.layers에 이름·종류·범례가 실린다. 화면은 범례를 메타에서 읽어 그린다 — 색을 화면에 따로 적지 않는다)
  hillshade   음영 기복. 고도에서 만든다(빛은 북서쪽 위 45° — 지도 제작의 관례. 실제 태양 위치가 아니다)
  slope       경사. 통과 한계(mobility.theta_max_deg)를 넘는 칸은 따로 표시
  units       지질 단위 (종류별 색. 지질도 원본의 색이 아니라 표시용으로 고른 색이다)
  minerals    광물 분류 (종류별 색)
  prior       바탕 지도 mu0 (등급 경계 grade_bins로 세 단계)
  link_<주차점>  그 주차점에 선 로버와 UHF 링크가 "안 되는" 칸을 덮는다
  shadow_<n>  n번째 시간 구간의 그림자 칸 (구간의 시각은 메타의 shadow_bins_lmst)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

TILE_PX = 256
ZOOM_MAX = 3

# 표시용 색 (R, G, B). 종류를 가르기 위한 색일 뿐 값의 크고 작음을 뜻하지 않는다
_QUAL = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75), (227, 119, 194),
         (127, 127, 127), (188, 189, 34), (23, 190, 207), (174, 199, 232), (255, 187, 120), (152, 223, 138), (255, 152, 150)]
_SLOPE = [(5.0, (255, 255, 204)), (10.0, (254, 217, 118)), (15.0, (253, 141, 60))]      # 위 경계(°) → 색. 그 위는 아래 두 줄
_SLOPE_HIGH = (227, 26, 28)             # 15° ~ 통과 한계
_SLOPE_BLOCK = (90, 0, 30)              # 통과 한계 초과
_PRIOR = [(237, 248, 251), (102, 194, 164), (0, 109, 44)]                                # LOW, MED, HIGH


def _hex(c) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def _read(root: Path, lay: dict) -> np.ndarray:
    """번들의 레이어 파일 하나를 [h, w] (bits는 [구간, h, w]) 배열로 읽는다. 형식은 pipeline/bundle.py가 쓴 그대로."""
    path, kind = root / lay["file"], lay["dtype"]
    h, w = lay["shape"]
    if kind == "f16":
        return np.fromfile(path, dtype="<f2").astype(np.float32).reshape(h, w)
    if kind == "u16":
        raw = np.fromfile(path, dtype="<u2").reshape(h, w)
        return np.where(raw == lay.get("nodata", 65535), np.nan, raw.astype(np.float32) * float(lay.get("scale", 1.0)) + float(lay.get("offset", 0.0)))
    if kind == "u8":
        return np.fromfile(path, dtype=np.uint8).reshape(h, w)
    if kind == "bits":
        planes = int(lay.get("bins") or 1)
        bits = np.unpackbits(np.fromfile(path, dtype=np.uint8))[: planes * h * w].reshape(planes, h, w)
        return bits.astype(bool)
    if kind == "tif":
        import rasterio
        with rasterio.open(path) as src:
            return src.read(1).astype(np.float32)
    raise ValueError(f"모르는 레이어 형식: {kind}")


def _finest(meta: dict, name: str) -> dict | None:
    """그 이름의 레이어 가운데 칸이 가장 작은 것."""
    cands = [x for x in meta["layers"] if x["name"] == name]
    return min(cands, key=lambda x: x["res_m"]) if cands else None


def _to_canvas(a: np.ndarray, size: int, smooth: bool) -> np.ndarray:
    """[h, w] 또는 [h, w, 채널] 배열을 size × size 그림 크기로 맞춘다. 분류·마스크는 가장 가까운 칸, 연속 값은 부드럽게."""
    if a.dtype == bool:
        a = a.astype(np.uint8) * 255
    mode = Image.Resampling.BILINEAR if smooth else Image.Resampling.NEAREST
    if a.ndim == 2 and a.dtype != np.uint8:
        return np.asarray(Image.fromarray(a.astype(np.float32), mode="F").resize((size, size), mode))
    return np.asarray(Image.fromarray(a).resize((size, size), mode))


def hillshade(elev: np.ndarray, res_m: float, az_deg: float = 315.0, alt_deg: float = 45.0) -> np.ndarray:
    """음영 기복 0~255 (uint8). 빛의 방위는 북에서 시계 방향, 고도는 지평선 위 각도."""
    z = np.where(np.isfinite(elev), elev, np.nanmean(elev))
    dzdy, dzdx = np.gradient(z, res_m)               # 행은 남쪽으로 늘어난다 → 북쪽 기울기는 −dzdy
    az, alt = np.radians(az_deg), np.radians(alt_deg)
    # 지표의 법선 (동, 북, 위) = (−dz/d동, −dz/d북, 1), 빛 방향 = (sin az·cos alt, cos az·cos alt, sin alt)
    nx, ny = -dzdx, dzdy
    shade = (nx * np.sin(az) * np.cos(alt) + ny * np.cos(az) * np.cos(alt) + np.sin(alt)) / np.sqrt(nx * nx + ny * ny + 1.0)
    return np.clip(shade * 255.0, 0, 255).astype(np.uint8)


def _rgba(shape, color, alpha_mask: np.ndarray, alpha: int) -> np.ndarray:
    out = np.zeros((*shape, 4), dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = color
    out[..., 3] = np.where(alpha_mask, alpha, 0)
    return out


def _class_image(codes: np.ndarray, names: dict[str, int], alpha: int) -> tuple[np.ndarray, list[dict]]:
    """분류 번호 배열 → 색 그림과 범례. 번들에 실제로 나오는 종류만 범례에 올린다."""
    out = np.zeros((*codes.shape, 4), dtype=np.uint8)
    legend = []
    for key, num in sorted(names.items(), key=lambda kv: kv[1]):
        m = codes == num
        if not m.any():
            continue
        color = _QUAL[(num - 1) % len(_QUAL)]
        out[m, :3], out[m, 3] = color, alpha
        legend.append({"key": key, "code": int(num), "color": _hex(color)})
    return out, legend


def _cut(img: np.ndarray, out_dir: Path) -> int:
    """size × size 그림(가장 큰 확대 단계)을 피라미드로 잘라 쓴다. 쓴 파일 수를 돌려준다."""
    full = Image.fromarray(img)
    n = 0
    for z in range(ZOOM_MAX, -1, -1):
        side = TILE_PX * (2 ** z)
        level = full if full.size[0] == side else full.resize((side, side), Image.Resampling.BOX)
        for x in range(2 ** z):
            d = out_dir / str(z) / str(x)
            d.mkdir(parents=True, exist_ok=True)
            for y in range(2 ** z):
                level.crop((x * TILE_PX, y * TILE_PX, (x + 1) * TILE_PX, (y + 1) * TILE_PX)).save(d / f"{y}.png", optimize=True)
                n += 1
    return n


def build(bundle_root: str | Path) -> dict:
    """번들 폴더의 레이어를 읽어 tiles/를 쓰고 meta.json을 고친다(tiles 항목, missing_layers, sha256). 메타의 tiles 항목을 돌려준다."""
    root = Path(bundle_root)
    meta = json.loads((root / "meta.json").read_text())
    params = {p["key"]: p for p in meta.get("params", []) if isinstance(p, dict) and "key" in p}
    theta_max = float(params.get("mobility.theta_max_deg", {}).get("value", 20.0))
    size = TILE_PX * (2 ** ZOOM_MAX)
    tdir = root / "tiles"
    layers_out: list[dict] = []

    def add(name: str, img: np.ndarray, kind: str, source: str, legend: list[dict] | None = None, **extra) -> None:
        n = _cut(img, tdir / name)
        layers_out.append({"name": name, "kind": kind, "source_layer": source, "legend": legend or [], "n_tiles": n, **extra})

    elev_l, slope_l = _finest(meta, "elev"), _finest(meta, "slope")
    if elev_l:
        hs = _to_canvas(hillshade(_read(root, elev_l), float(elev_l["res_m"])), size, True)
        add("hillshade", np.stack([hs, hs, hs, np.full_like(hs, 255)], axis=-1), "shade", "elev", light={"az_deg": 315.0, "alt_deg": 45.0})
    if slope_l:
        s = _to_canvas(_read(root, slope_l), size, True)
        img = np.zeros((size, size, 4), dtype=np.uint8)
        lo, legend = 0.0, []
        for hi, color in [*_SLOPE, (theta_max, _SLOPE_HIGH)]:
            m = (s >= lo) & (s < hi)
            img[m, :3], img[m, 3] = color, 150
            legend.append({"from": lo, "to": hi, "unit": "deg", "color": _hex(color)})
            lo = hi
        m = s >= theta_max
        img[m, :3], img[m, 3] = _SLOPE_BLOCK, 200
        legend.append({"from": theta_max, "to": None, "unit": "deg", "color": _hex(_SLOPE_BLOCK), "blocked": True})
        add("slope", img, "continuous", "slope", legend)
    for name, codes_key in (("units", "unit_codes"), ("minerals", "mineral_codes")):
        lay = _finest(meta, name)
        if lay:
            img, legend = _class_image(_read(root, lay), meta.get(codes_key, {}), 140)
            add(name, np.asarray(Image.fromarray(img).resize((size, size), Image.Resampling.NEAREST)), "class", name, legend)
    mu_l = _finest(meta, "mu0")
    if mu_l:
        mu = _to_canvas(_read(root, mu_l), size, False)          # 바탕 지도는 칸마다 한 값 — 칸 경계가 보이게 둔다
        g0, g1 = (float(x) for x in meta["grade_bins"])
        img = np.zeros((size, size, 4), dtype=np.uint8)
        legend = []
        for grade, lo, hi, color in (("LOW", -np.inf, g0, _PRIOR[0]), ("MED", g0, g1, _PRIOR[1]), ("HIGH", g1, np.inf, _PRIOR[2])):
            m = np.isfinite(mu) & (mu >= lo) & (mu < hi)
            img[m, :3], img[m, 3] = color, 150
            legend.append({"grade": grade, "from": None if lo == -np.inf else lo, "to": None if hi == np.inf else hi, "color": _hex(color)})
        add("prior", img, "grade", "mu0", legend)
    for park in meta.get("rover_parks", []):
        lay = _finest(meta, f"los_{park['id']}")
        if lay:
            ok = _to_canvas(_read(root, lay)[0], size, False) > 0
            add(f"link_{park['id']}", _rgba((size, size), (40, 40, 60), ~ok, 110), "mask", lay["name"],
                [{"key": "no_link", "color": _hex((40, 40, 60))}], park=park["id"])
    sh_l = _finest(meta, "shadow")
    if sh_l:
        planes = _read(root, sh_l)
        for i in range(planes.shape[0]):
            m = _to_canvas(planes[i], size, False) > 0
            add(f"shadow_{i}", _rgba((size, size), (0, 0, 40), m, 120), "mask", "shadow", [{"key": "shadow", "color": _hex((0, 0, 40))}], bin=i)

    extent = [float(x) for x in meta["extent_m"]]
    info = {"path": "tiles/{layer}/{z}/{x}/{y}.png", "tile_px": TILE_PX, "zoom_min": 0, "zoom_max": ZOOM_MAX, "extent_m": extent,
            "m_per_px_at_zoom_max": round(extent[0] / size, 4), "layers": layers_out}
    meta["tiles"] = info
    meta["missing_layers"] = [x for x in meta.get("missing_layers", []) if x != "tiles"]
    sha = {k: v for k, v in meta.get("sha256", {}).items() if not k.startswith("tiles/")}
    for f in sorted(tdir.rglob("*.png")):
        sha[f.relative_to(root).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    meta["sha256"] = sha
    (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="번들의 표시용 타일을 굽는다")
    ap.add_argument("bundle")
    a = ap.parse_args()
    info = build(a.bundle)
    total = sum(f.stat().st_size for f in (Path(a.bundle) / "tiles").rglob("*.png"))
    print(f"타일: 레이어 {len(info['layers'])}개 ({', '.join(x['name'] for x in info['layers'])}), 파일 {sum(x['n_tiles'] for x in info['layers'])}개, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
