"""번들이 이 기계에 없으면 받아서 푼다.

    .venv/bin/python -m host.fetch                    # 기본 지도(jezero_west_v1)만
    .venv/bin/python -m host.fetch jezero_floor_v1    # 고른 것
    .venv/bin/python -m host.fetch --all              # 목록에 있는 것 전부

왜 있나: 번들은 한 개에 60 MB쯤이라 저장소에 올리지 않는다(.gitignore의 data/bundles/). 그래서 저장소만 받은 사람은 실행할 지도가 없다.
이 모듈이 그 틈을 메운다 — 실시간 서버(sim/live.py)가 켜질 때, 그리고 첫 화면에서 아직 없는 지도를 고를 때 이 모듈을 불러 번들을 받는다.

무엇을 어디서 가져오나: config/bundles.yaml에 적힌 것만 다룬다. 그 파일에는 받는 곳(주소)과 번들마다 파일 이름·크기·SHA-256이 있다.
  - 먼저 저장소의 release/ 폴더를 본다. 거기에 그 zip이 있으면(저장소를 받으면 함께 온다) 내려받지 않고 그것을 푼다.
  - 없으면 목록에 적힌 주소에서 받는다.
  - 어느 쪽이든 파일의 크기와 SHA-256이 목록과 다르면 풀지 않는다(받은 것이면 버린다).
  - zip 안의 경로가 `data/bundles/<번들 id>/` 아래가 아니면 풀지 않는다(다른 곳에 파일을 쓰지 못하게).
  - 임시 폴더에 다 푼 뒤에 이름을 바꿔 놓는다 → 받다가 끊겨도 반쯤 풀린 번들이 남지 않는다.
받는 곳을 바꾸려면 환경 변수 BT_BUNDLE_URL에 다른 주소를 준다(시험할 때 로컬 서버를 가리키는 데 쓴다).

목록(config/bundles.yaml)은 scripts/make_release.py가 만든다 — 번들을 zip으로 묶고 크기와 SHA-256을 적는다.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "config/bundles.yaml"
BUNDLE_DIR = ROOT / "data/bundles"
LOCAL_DIR = ROOT / "release"   # 저장소에 함께 올린 zip이 있는 곳
DEFAULT = "jezero_west_v1"
CHUNK = 1 << 20   # 한 번에 읽는 크기(1 MiB)
_LOCK = threading.Lock()   # 한 번에 하나만 받는다 — 같은 번들을 두 곳에서 동시에 받아 풀다가 서로 덮어쓰지 않게


class FetchError(RuntimeError):
    """번들을 받지 못했다. 글에 이유가 들어 있다(사람에게 그대로 보여 준다)."""


def manifest() -> dict:
    """config/bundles.yaml을 읽는다. 없으면 빈 목록(받을 수 있는 것이 없다)."""
    if not MANIFEST.exists():
        return {"release": "", "bundles": {}}
    m = yaml.safe_load(MANIFEST.read_text()) or {}
    return {"release": m.get("release", ""), "bundles": m.get("bundles") or {}}


def base_url() -> str:
    return (os.environ.get("BT_BUNDLE_URL") or manifest()["release"]).rstrip("/")


def is_installed(bundle_id: str, dest: Path = BUNDLE_DIR) -> bool:
    return (dest / bundle_id / "meta.json").exists()


def ensure(bundle_id: str, dest: Path = BUNDLE_DIR, say=print) -> Path:
    """번들 폴더를 돌려준다. 없으면 받아서 푼다. 받지 못하면 FetchError."""
    with _LOCK:
        return _ensure(bundle_id, dest, say)


def _ensure(bundle_id: str, dest: Path, say) -> Path:
    out = dest / bundle_id
    if is_installed(bundle_id, dest):
        return out
    item = manifest()["bundles"].get(bundle_id)
    if item is None:
        raise FetchError(f"bundle '{bundle_id}' is not on this machine and is not listed in {MANIFEST.relative_to(ROOT)}")
    dest.mkdir(parents=True, exist_ok=True)
    local = LOCAL_DIR / item["file"]
    with tempfile.TemporaryDirectory(dir=dest, prefix=f".{bundle_id}.") as tmp:
        if local.exists() and not os.environ.get("BT_BUNDLE_URL"):      # 저장소에 함께 온 zip이 있다 → 받지 않고 그것을 푼다
            say(f"[bundle] {bundle_id} is not unpacked yet. Unpacking {local.relative_to(ROOT)} ({item['bytes'] / 1e6:.0f} MB)")
            _verify(local, int(item["bytes"]), str(item["sha256"]))
            zpath = local
        else:
            url = f"{base_url()}/{item['file']}"
            say(f"[bundle] {bundle_id} is not on this machine. Downloading {item['file']} ({item['bytes'] / 1e6:.0f} MB) from {url}")
            zpath = Path(tmp) / item["file"]
            _download(url, zpath, int(item["bytes"]), str(item["sha256"]), say)
        _extract(zpath, bundle_id, Path(tmp) / "x")
        if out.exists():                  # 반쯤 있는 폴더(meta.json 없음)가 남아 있었다 → 새것으로 바꾼다
            shutil.rmtree(out)
        (Path(tmp) / "x").rename(out)
    say(f"[bundle] {bundle_id} installed at {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return out


def _verify(path: Path, want_bytes: int, want_sha: str) -> None:
    """이미 있는 zip의 크기와 SHA-256이 목록과 같은지 본다. 다르면 FetchError."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for buf in iter(lambda: f.read(CHUNK), b""):
            h.update(buf)
    if path.stat().st_size != want_bytes or h.hexdigest() != want_sha:
        raise FetchError(f"{path.name} does not match the list (size {path.stat().st_size} vs {want_bytes}, sha256 {h.hexdigest()[:12]}… vs {want_sha[:12]}…)")


def _download(url: str, to: Path, want_bytes: int, want_sha: str, say) -> None:
    h, got, step = hashlib.sha256(), 0, 0
    try:
        with urllib.request.urlopen(url, timeout=30) as r, open(to, "wb") as f:
            while True:
                buf = r.read(CHUNK)
                if not buf:
                    break
                f.write(buf)
                h.update(buf)
                got += len(buf)
                if got * 4 // want_bytes > step:      # 25 %마다 한 줄
                    step = got * 4 // want_bytes
                    say(f"[bundle]   {got / 1e6:.0f} / {want_bytes / 1e6:.0f} MB")
    except OSError as e:                              # 주소가 없다, 연결이 안 된다, 중간에 끊겼다
        raise FetchError(f"could not download {url}: {e}") from None
    if got != want_bytes or h.hexdigest() != want_sha:
        raise FetchError(f"downloaded file does not match the list (size {got} vs {want_bytes}, sha256 {h.hexdigest()[:12]}… vs {want_sha[:12]}…)")


def _extract(zpath: Path, bundle_id: str, to: Path) -> None:
    """zip 안의 `data/bundles/<id>/…`만 `to/…`로 푼다. 그 밖의 경로가 하나라도 있으면 아무것도 풀지 않는다."""
    prefix = f"data/bundles/{bundle_id}/"
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        bad = [n for n in names if not n.startswith(prefix) or ".." in Path(n).parts]
        if bad or not names:
            raise FetchError(f"unexpected path in {zpath.name}: {bad[:1] or 'empty archive'}")
        for n in names:
            p = to / n[len(prefix):]
            p.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(p, "wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
    if not (to / "meta.json").exists():
        raise FetchError(f"{zpath.name} has no meta.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="Download map bundles that are not on this machine")
    ap.add_argument("bundles", nargs="*", help=f"bundle ids (default: {DEFAULT})")
    ap.add_argument("--all", action="store_true", help="every bundle in config/bundles.yaml")
    a = ap.parse_args()
    ids = list(manifest()["bundles"]) if a.all else (a.bundles or [DEFAULT])
    try:
        for i in ids:
            ensure(i)
    except FetchError as e:
        sys.exit(f"[bundle] {e}")


if __name__ == "__main__":
    main()
