"""번들을 내려받을 수 있게 묶고, 받는 쪽이 읽을 목록(config/bundles.yaml)을 쓴다.

    .venv/bin/python scripts/make_release.py            # data/bundles/ 아래의 번들 전부 → release/bundle_<id>.zip + config/bundles.yaml

하는 일
  ① data/bundles/<id>/ 를 release/bundle_<id>.zip 으로 묶는다. zip 안의 경로는 `data/bundles/<id>/…` 이다(받는 쪽 host/fetch.py가 이 모양만 푼다).
  ② 파일마다 크기와 SHA-256을 재서 config/bundles.yaml에 적는다. 지도 이름·넓이·지점 수도 번들 메타에서 옮겨 적는다
     (아직 받지 않은 지도를 첫 화면 목록에 보이는 데 쓴다).
묶은 zip은 저장소에 함께 올린다(.gitignore에서 release/*.zip만 예외로 풀어 두었다). 한 개에 60 MB쯤이라 GitHub의 파일 한도(100 MB) 안이다.
저장소를 받은 사람은 zip을 이미 갖고 있으므로 받는 쪽은 그것을 풀기만 한다. zip 없이 코드만 가진 경우에는 아래 주소에서 받는다.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RELEASE_URL = "https://raw.githubusercontent.com/Namung2/26NASA/main/release"   # 저장소의 release/ 폴더를 그대로 가리킨다


def main() -> None:
    out = ROOT / "release"
    out.mkdir(exist_ok=True)
    items = {}
    for d in sorted(q for q in (ROOT / "data/bundles").iterdir() if (q / "meta.json").exists()):
        meta = json.loads((d / "meta.json").read_text().replace("NaN", "null"))
        bid = meta["bundle_id"]
        if bid != d.name:
            sys.exit(f"폴더 이름과 번들 id가 다르다: {d.name} / {bid}")
        z = out / f"bundle_{bid}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in sorted(d.rglob("*")):
                if p.is_file() and p.name != ".DS_Store":
                    zf.write(p, f"data/bundles/{bid}/{p.relative_to(d).as_posix()}")
        h = hashlib.sha256()
        with open(z, "rb") as f:
            for buf in iter(lambda: f.read(1 << 20), b""):
                h.update(buf)
        items[bid] = {"file": z.name, "bytes": z.stat().st_size, "sha256": h.hexdigest(),
                      "site": meta["site"], "extent_m": meta["extent_m"], "pois": len(meta.get("pois", []))}
        print(f"{z.relative_to(ROOT)}  {z.stat().st_size / 1e6:.1f} MB  {h.hexdigest()[:16]}…")
    head = ("# 내려받을 수 있는 번들의 목록. scripts/make_release.py가 만든다 — 손으로 고치지 않는다.\n"
            "# 읽는 곳: host/fetch.py (번들이 이 기계에 없으면 저장소의 release/ 폴더에 있는 zip을 풀고, 그것도 없으면 여기 적힌 곳에서 받는다.\n"
            "#          어느 쪽이든 크기와 SHA-256을 확인한 뒤에 푼다)\n")
    (ROOT / "config/bundles.yaml").write_text(head + yaml.safe_dump({"release": RELEASE_URL, "bundles": items}, sort_keys=False, allow_unicode=True))
    print("config/bundles.yaml 을 썼다")


if __name__ == "__main__":
    main()
