"""화면을 붙여 돌리는 실시간 서버 (docs/spec/S5 §6, S3c §8).

    .venv/bin/python -m sim.live                       # http://localhost:8000/field.html , /console.html
    .venv/bin/python -m sim.live --scenario D1_demo --speed 20 --port 8000

지금은 기기 프로그램·로버 프로그램·시뮬레이터가 이 프로세스 하나 안에서 돈다(sim.sim.Sim이 둘 사이의 메시지를 건넨다).
명세의 최종 모양은 프로그램 둘이 따로 뜨고(`python -m device`, `python -m rover`) 무선 계층(host/transport.py)으로 잇는 것이다.
그때도 아래 주소와 메시지는 그대로다 — 화면은 어느 쪽인지 모른다.

  WS   /ws/screen         기기 프로그램 → 현장 화면: Snapshot(JSON) / 화면 → ScreenCmd
  WS   /ws/console        로버 프로그램 → 로버 콘솔: ConsoleSnapshot / 콘솔 → ConsoleCmd
  GET  /bundle/{path}     지금 올라와 있는 번들의 파일(meta.json, tiles/…). 지도를 바꿔 시작하면 그 번들의 것으로 바뀐다
  GET  /bundles/{id}/{path}  번들 id를 짚어 읽는 파일(고르는 화면의 지도 그림용)
  GET  /console/height.json          지형의 높이 격자 (3D 보기용. 번들마다 한 번 만든다)
  GET  /console/science.png?kind=…   지금의 과학 가치 지도를 색 입힌 그림. kind: expected | max | base | var
  GET  /console/science_legend.json  그 그림의 색 눈금·등급 경계·놓임 (rover/console_map.py)
  GET  /sim/state         지금 도는 시나리오·배속·시각 (시뮬레이터 조작 막대용)
  GET  /sim/catalog       고르는 화면용: 지도(번들)와 그 지도의 시나리오 목록, 지금 도는 것
  POST /sim/start         {scenario, speed, manual, bundle}   manual = true면 가설 입력과 카드 선택을 사람이 한다.
                          bundle = 번들 id(없으면 지금 올라와 있는 번들). 다른 번들을 주면 그 지도로 바꿔서 시작한다.
                          그 번들이 이 기계에 아직 없고 받을 수 있는 목록(config/bundles.yaml)에 있으면 먼저 받아서 푼다(host/fetch.py)
  POST /sim/speed         {speed}                     0 = 멈춤
  POST /sim/link          {ch, state}                 state: LOST | AUTO   (데모의 링크 버튼)
  POST /sim/inject        ScenarioEvent 한 개         지금 바로 넣는다
  GET  /sim/log           판정 기록(JSONL)
  POST /photo             사진 한 장(JPEG, 본문 그대로) → 그 자리에 촬영 흔적을 남기고 파일을 photos_live/에 둔다 (S2 §사진)
                          환경 변수 BT_PHOTO_LIMIT가 있으면 한 번의 실행에 그 수까지만 받는다(넘으면 429) — 아래 PHOTO_LIMIT
  GET  /photos            이번 실행에서 찍은 사진 목록 [{event_id, url, t, xy}]
  GET  /photos/{name}     사진 파일
  GET  /                  screen/dist (npm run build로 만든 화면)

/sim/* 은 보여 주기·개발 전용이다. 실제 기기에는 없다.

사진 (S2: "파일은 기기에 둔다 — photos_live/<이벤트 id>.jpg. 로버에는 사진이 있다는 이벤트만 간다")
  · 화면이 사진을 올리면 기기 프로그램에 "촬영" 명령(CmdPhoto)을 넣고, 그때 생긴 흔적 이벤트의 id로 파일 이름을 짓는다.
    계약(host/wire.py)은 그대로다 — 사진 본문은 소켓이 아니라 이 주소로 오고, 스냅샷에는 싣지 않는다.
  · 파일 이름 앞에 실행을 시작한 시각을 붙인다. 시나리오를 다시 시작하면 이벤트 id가 처음부터 다시 매겨져 겹치기 때문이다.
  · 사진의 내용은 읽지 않는다(해석·분류 없음). 로버로 넘기는 일(photo_sync)은 아직 없다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from host import fetch
from host import wire as w
from rover import console_map

from .scenario import ScenarioEvent, load_scenario
from .sim import Sim

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "sim/scenarios"
TICK_WALL_S = 0.05            # 실제 시간으로 이만큼마다 시뮬을 밀고 화면에 보낸다(초당 20번)
PHOTO_DIR = ROOT / "photos_live"   # 기기에 두는 사진 (저장소에 올리지 않는다 — .gitignore)
MAX_PHOTO_BYTES = 12 * 1024 * 1024  # 사진 한 장의 상한. 문서에 정해진 값이 없어 서버를 지키려고 둔 기술값이다
# 한 번의 실행(시나리오를 시작해서 다시 시작하기 전까지)에 받는 사진 수의 상한. 0 = 제한 없음(내 기계에서 돌릴 때).
# 공개 주소에 올린 서버는 아무나 사진을 올릴 수 있으므로 환경 변수 BT_PHOTO_LIMIT로 건다 — Dockerfile이 5로 둔다(2026-11-15 사용자 결정:
# 시험용으로 5장까지). 제한이 걸려 있으면 시나리오를 다시 시작할 때 앞 실행의 사진 파일을 지운다 → 서버에 남는 사진은 많아야 그 수다.
PHOTO_LIMIT = int(os.environ.get("BT_PHOTO_LIMIT", "0") or 0)
MAX_TICKS_PER_PUSH = 200      # 한 번에 미는 시뮬 틱의 상한 — 배속을 너무 높여도 서버가 멈추지 않게


class FreshStatic(StaticFiles):
    """정적 파일을 내주되 브라우저가 매번 서버에 "바뀌었나"를 묻게 한다(Cache-Control: no-cache).

    이 머리말이 없으면 브라우저가 번들의 meta.json이나 화면 파일을 제멋대로 한동안 붙들고 있어서, 번들을 다시 만들거나 화면을 다시
    빌드해도 옛것이 보인다. 바뀌지 않았으면 서버가 "그대로"(304)라고만 답하므로 다시 내려받지는 않는다.
    """

    async def get_response(self, path: str, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


# 요청 본문. 모듈 맨 위에 둬야 한다 — 함수 안에 두면 FastAPI가 타입 이름을 찾지 못해 본문으로 읽지 않는다
class StartBody(BaseModel):
    scenario: str
    speed: float = 10.0
    manual: bool = True
    bundle: str | None = None     # 번들 id. 없으면 지금 올라와 있는 번들에서 시작한다


class SpeedBody(BaseModel):
    speed: float


class LinkBody(BaseModel):
    ch: str = "both"
    state: str = "LOST"


class Driver:
    """시뮬레이터 하나를 실제 시간에 맞춰(배속을 곱해) 돌리고, 붙어 있는 화면들에 스냅샷을 보낸다."""

    def __init__(self, bundle_root: str) -> None:
        self.bundle_root = bundle_root
        self.sim: Sim | None = None
        self.name = ""
        self.speed = 0.0
        self.manual = True
        self.screens: set[WebSocket] = set()
        self.consoles: set[WebSocket] = set()
        self._files: dict[str, FreshStatic] = {}   # 번들 폴더 → 그 폴더의 파일을 내주는 것
        self._height: dict | None = None  # 높이 격자 (번들이 같으면 다시 만들지 않는다)
        self._png: dict[tuple[int, str], bytes] = {}   # (science_rev, kind) → 그림. 지도가 바뀌면 새로 만든다
        self._debt = 0.0                  # 아직 밀지 못한 시뮬 시간(초)
        self._last = time.monotonic()
        self.run_tag = ""                 # 실행을 시작한 시각 — 사진 파일 이름 앞에 붙는다
        self.photos: list[dict] = []      # 이번 실행에서 찍은 사진 (찍은 순서)

    def bundles(self) -> dict[str, Path]:
        """고를 수 있는 번들: 켤 때 받은 번들과, 같은 폴더에 나란히 놓인 번들. {번들 id: 폴더}"""
        out = {}
        for d in sorted(q for q in Path(self.bundle_root).resolve().parent.iterdir() if (q / "meta.json").exists()):
            out[json.loads((d / "meta.json").read_text().replace("NaN", "null"))["bundle_id"]] = d
        return out

    def bundle_id(self) -> str:
        here = Path(self.bundle_root).resolve()
        return next((i for i, d in self.bundles().items() if d == here), here.name)

    def files(self, bundle: str | None = None) -> FreshStatic:
        """번들 폴더 하나의 파일을 내주는 것. bundle이 없으면 지금 올라와 있는 번들. 없는 id면 KeyError."""
        root = str(Path(self.bundle_root).resolve() if bundle is None else self.bundles()[bundle])
        if root not in self._files:
            self._files[root] = FreshStatic(directory=root)
        return self._files[root]

    def start(self, name: str, speed: float, manual: bool, bundle: str | None = None) -> None:
        """시나리오를 처음부터 시작한다. bundle(번들 id)을 주면 그 지도로 바꿔서 시작한다 — 없는 id면 KeyError.

        시나리오는 지점을 이름(P1·P2·P3)과 주차점으로만 가리키므로 다른 구역의 번들에서도 돈다(S5 §8, sim.sim.Sim의 any_site).
        시나리오 파일에 적힌 구역이 아닌 번들로 돌릴 때만 any_site를 켠다.
        """
        path = SCENARIO_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(name)
        root = self.bundle_root if bundle is None else str(self.bundles()[bundle])
        sc = load_scenario(path)
        meta_id = json.loads((Path(root) / "meta.json").read_text().replace("NaN", "null"))["bundle_id"]
        sim = Sim(sc, root, any_site=sc.site != meta_id)
        self.bundle_root = root           # 시뮬레이터가 만들어진 뒤에 바꾼다 — 만들다 실패하면 앞의 지도가 그대로 남는다
        sim.auto_choose = not manual
        sim.manual_types = {"hyp"} if manual else set()
        sim.step()                        # 첫 스냅샷을 만든다
        self.sim, self.name, self.speed, self.manual, self._debt = sim, name, float(speed), manual, 0.0
        if PHOTO_LIMIT:                       # 제한이 걸린 서버: 앞 실행의 사진 파일을 지운다(목록에서도 빠지므로 어차피 더는 내주지 않는다)
            for p in self.photos:
                (PHOTO_DIR / p["url"].rsplit("/", 1)[-1]).unlink(missing_ok=True)
        self.run_tag, self.photos = time.strftime("%Y%m%dT%H%M%S"), []
        self._height, self._png = None, {}    # 시나리오를 새로 시작했다 → 앞 판의 그림을 쓰지 않는다

    def add_photo(self, data: bytes) -> dict:
        """기기 프로그램에 촬영 명령을 넣고, 그때 생긴 흔적 이벤트의 id로 사진을 저장한다. 목록에 넣은 항목을 돌려준다."""
        dev = self.sim.dev
        before = set(dev.table.by_id)
        dev.on_command(w.CmdPhoto())
        made = [e for i, e in dev.table.by_id.items() if i not in before and e.type == "trace" and e.payload.kind == "photo"]
        if not made:                      # 아직 위치를 한 번도 받지 못했다 — 기기 프로그램이 흔적을 남기지 않았다
            raise RuntimeError("no trace")
        ev = made[-1]
        name = f"{self.run_tag}_{ev.id.replace(':', '_')}.jpg"
        PHOTO_DIR.mkdir(exist_ok=True)
        (PHOTO_DIR / name).write_bytes(data)
        item = {"event_id": ev.id, "url": f"/photos/{name}", "t": ev.ts, "xy": [round(ev.geom.xy[0], 1), round(ev.geom.xy[1], 1)]}
        self.photos.append(item)
        return item

    # ── 3D 보기·살아 있는 과학 가치 레이어 (rover/console_map.py) ──
    def height(self) -> dict:
        if self._height is None:
            self._height = console_map.height_grid(self.sim.rover.bundle)
        return self._height

    def science_png(self, kind: str) -> bytes:
        rover = self.sim.rover
        key = (rover.science_rev, kind)
        if key not in self._png:
            self._png = {k: v for k, v in self._png.items() if k[0] == rover.science_rev}   # 옛 판의 그림은 버린다
            self._png[key] = console_map.science_png(rover.core.science_view(), kind)
        return self._png[key]

    def catalog(self) -> dict:
        """고르는 화면(첫 화면)에 보일 것: 지도(번들)마다 그 지도에서 도는 시나리오. 글과 숫자는 번들 메타와 시나리오 파일에 적힌 그대로다.

        번들 폴더에 나란히 놓인 번들은 모두 고를 수 있다(loaded = true) — /sim/start에 그 번들 id를 주면 지도를 바꿔 시작한다.
        current = 지금 올라와 있는 번들. 시나리오는 지점을 이름으로만 가리키므로 어느 지도에서나 돈다(start 참고) → 지도마다 전부 보인다.
        """
        here = Path(self.bundle_root).resolve()
        scenarios = [load_scenario(p) for p in sorted(SCENARIO_DIR.glob("*.yaml"))]
        maps = []
        rows = [{"id": s.scenario, "kind": s.kind, "title": s.title or s.scenario, "summary": s.summary,
                 "start_min": s.start.eva_elapsed_min, "stops": s.poi_plan} for s in scenarios]
        have = self.bundles()
        for bid, d in have.items():
            meta = json.loads((d / "meta.json").read_text().replace("NaN", "null"))
            maps.append({"id": bid, "site": meta["site"], "extent_m": meta["extent_m"], "pois": len(meta.get("pois", [])),
                         "loaded": True, "installed": True, "current": d == here,
                         "thumb": f"/bundles/{bid}/tiles/hillshade/0/0/0.png", "scenarios": rows})
        # 이 기계에 아직 없지만 받을 수 있는 지도 — 고르면 /sim/start가 먼저 받아 온다. 그림은 아직 없다(thumb = null)
        for bid, it in fetch.manifest()["bundles"].items():
            if bid not in have:
                maps.append({"id": bid, "site": it["site"], "extent_m": it["extent_m"], "pois": it["pois"],
                             "loaded": True, "installed": False, "current": False, "thumb": None,
                             "download_mb": round(it["bytes"] / 1e6), "scenarios": rows})
        maps.sort(key=lambda m: m["id"])
        return {"maps": maps, "running": self.state()}

    def state(self) -> dict:
        s = self.sim
        return {"bundle": self.bundle_id(), "scenario": self.name, "speed": self.speed, "manual": self.manual, "running": s is not None and not s.done(),
                "t": s.t if s else 0.0, "home": bool(s and s.home), "link": dict(s.manual) if s else {},
                "scenarios": sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))}

    def _lmst(self) -> str:
        lm = int(self.sim.fb.sun_at(self.sim.t)["lmst_min"])
        return f"{lm // 60:02d}:{lm % 60:02d}"

    async def _send(self, group: set[WebSocket], text: str) -> None:
        for ws in list(group):
            try:
                await ws.send_text(text)
            except (RuntimeError, WebSocketDisconnect, OSError):   # 화면이 닫혔다
                group.discard(ws)

    async def push(self) -> None:
        s = self.sim
        if s is None:
            return
        snap = s.dev.snapshot()
        if snap is not None and self.screens:
            await self._send(self.screens, snap.model_dump_json())
        if self.consoles:
            await self._send(self.consoles, s.rover.console_snapshot(s.t, self._lmst()).model_dump_json())

    async def run(self) -> None:
        while True:
            await asyncio.sleep(TICK_WALL_S)
            now = time.monotonic()
            s = self.sim
            if s is not None and self.speed > 0 and not s.done():
                self._debt += (now - self._last) * self.speed
                n = min(MAX_TICKS_PER_PUSH, int(self._debt / s.dt))
                self._debt -= n * s.dt
                if n == MAX_TICKS_PER_PUSH:
                    self._debt = 0.0
                for _ in range(n):
                    if s.done():
                        break
                    s.step()
            self._last = now
            await self.push()


def make_app(bundle_root: str, scenario: str | None, speed: float, manual: bool) -> FastAPI:
    drv = Driver(bundle_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scenario:
            drv.start(scenario, speed, manual)
        task = asyncio.create_task(drv.run())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(lifespan=lifespan)

    @app.get("/sim/state")
    async def sim_state():
        return drv.state()

    @app.get("/sim/catalog")
    async def sim_catalog():
        return drv.catalog()

    @app.post("/sim/start")
    async def sim_start(b: StartBody):
        if b.bundle and b.bundle not in drv.bundles():      # 이 기계에 없는 지도 → 받을 수 있으면 받아 온다(수십 초 걸린다)
            try:                                            # 받는 동안 화면에 가는 스냅샷이 멈추지 않게 다른 스레드에서 한다
                await asyncio.to_thread(fetch.ensure, b.bundle, Path(drv.bundle_root).resolve().parent)
            except fetch.FetchError as e:
                raise HTTPException(502, str(e)) from None
        try:
            drv.start(b.scenario, b.speed, b.manual, b.bundle)
        except FileNotFoundError:
            raise HTTPException(404, f"시나리오 없음: {b.scenario}") from None
        except KeyError:
            raise HTTPException(404, f"번들 없음: {b.bundle}") from None
        return drv.state()

    @app.post("/sim/speed")
    async def sim_speed(b: SpeedBody):
        drv.speed = max(0.0, min(600.0, b.speed))
        return drv.state()

    @app.post("/sim/link")
    async def sim_link(b: LinkBody):
        if drv.sim is not None:
            for name in (("uhf", "wifi") if b.ch == "both" else (b.ch,)):
                drv.sim.manual[name] = None if b.state == "AUTO" else b.state
        return drv.state()

    @app.post("/sim/inject")
    async def sim_inject(ev: ScenarioEvent):
        if drv.sim is None:
            raise HTTPException(409, "도는 시나리오가 없다")
        drv.sim.sc.events.append(ev)                      # 대본 끝에 붙이고 바로 넣는다
        drv.sim._inject(len(drv.sim.sc.events), ev)
        return drv.state()

    @app.get("/sim/log", response_class=PlainTextResponse)
    async def sim_log():
        rows = drv.sim.log.rows if drv.sim else []
        return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)

    @app.post("/photo")
    async def photo_add(req: Request):
        if drv.sim is None:
            raise HTTPException(409, "no scenario is running")
        if PHOTO_LIMIT and len(drv.photos) >= PHOTO_LIMIT:
            raise HTTPException(429, f"photo limit reached ({PHOTO_LIMIT} per run on this server)")
        data = await req.body()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "photo is too large")
        if data[:3] != b"\xff\xd8\xff":                    # JPEG만 받는다(화면이 JPEG로 바꿔 보낸다)
            raise HTTPException(415, "not a JPEG image")
        try:
            return drv.add_photo(data)
        except RuntimeError:
            raise HTTPException(409, "the device has no position yet") from None

    @app.get("/photos")
    async def photo_list():
        return drv.photos

    @app.get("/photos/{name}")
    async def photo_file(name: str):
        if not any(p["url"] == f"/photos/{name}" for p in drv.photos):    # 목록에 있는 이름만 내준다(경로를 따라 올라가지 못하게)
            raise HTTPException(404, "no such photo")
        return FileResponse(PHOTO_DIR / name, media_type="image/jpeg")

    @app.get("/console/height.json")
    async def console_height():
        if drv.sim is None:
            raise HTTPException(409, "no scenario is running")
        return drv.height()

    @app.get("/console/science_legend.json")
    async def console_legend():
        if drv.sim is None:
            raise HTTPException(409, "no scenario is running")
        return console_map.legend(drv.sim.rover.core.science_view(), drv.sim.meta["grade_bins"])

    @app.get("/console/science.png")
    async def console_science(kind: str = "expected"):
        if drv.sim is None:
            raise HTTPException(409, "no scenario is running")
        if kind not in console_map.KINDS:
            raise HTTPException(400, f"kind must be one of {list(console_map.KINDS)}")
        # 주소에 판 번호(?v=science_rev)를 붙여 부르면 브라우저가 같은 그림을 다시 받지 않는다
        return Response(drv.science_png(kind), media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.websocket("/ws/screen")
    async def ws_screen(ws: WebSocket):
        await ws.accept()
        drv.screens.add(ws)
        try:
            while True:
                msg = w.ScreenCmd.model_validate_json(await ws.receive_text())
                if drv.sim is not None:
                    drv.sim.dev.on_command(msg.cmd)       # 결과는 다음 스냅샷에 나타난다 (화면은 답을 기다리지 않는다)
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            drv.screens.discard(ws)

    @app.websocket("/ws/console")
    async def ws_console(ws: WebSocket):
        await ws.accept()
        drv.consoles.add(ws)
        try:
            while True:
                msg = w.ConsoleCmd.model_validate_json(await ws.receive_text())
                if drv.sim is not None:
                    drv.sim.rover.on_command(msg)
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            drv.consoles.discard(ws)

    # 번들 파일. 고정된 폴더를 붙이지 않고 요청마다 "지금 올라와 있는 번들"에서 읽는다 — 지도를 바꿔 시작하면 같은 주소가 새 지도를 준다
    @app.get("/bundle/{path:path}")
    async def bundle_file(path: str, request: Request):
        return await drv.files().get_response(path, request.scope)

    @app.get("/bundles/{bid}/{path:path}")
    async def bundle_file_of(bid: str, path: str, request: Request):
        try:
            files = drv.files(bid)
        except KeyError:
            raise HTTPException(404, f"번들 없음: {bid}") from None
        return await files.get_response(path, request.scope)

    dist = ROOT / "screen/dist"
    if dist.exists():
        app.mount("/", FreshStatic(directory=dist, html=True), name="screen")
    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="화면을 붙여 돌리는 실시간 서버")
    ap.add_argument("--bundle", default="data/bundles/jezero_west_v1")
    ap.add_argument("--scenario", default="D1_demo")
    ap.add_argument("--speed", type=float, default=10.0, help="시뮬 배속(1 = 실제 시간)")
    ap.add_argument("--auto", action="store_true", help="가설 입력과 카드 선택도 시나리오가 한다(구경만)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="듣는 주소. 컨테이너 안에서는 0.0.0.0 (Dockerfile 참고)")
    a = ap.parse_args()
    if not (Path(a.bundle) / "meta.json").exists():       # 번들이 이 기계에 없다(저장소만 받은 직후) → 받아서 푼다
        try:
            fetch.ensure(Path(a.bundle).name, Path(a.bundle).resolve().parent)
        except fetch.FetchError as e:
            raise SystemExit(f"[bundle] {e}\n[bundle] See README.md, section 'Data bundle'.") from None
    uvicorn.run(make_app(a.bundle, a.scenario, a.speed, not a.auto), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
