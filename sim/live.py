"""화면을 붙여 돌리는 실시간 서버 (docs/spec/S5 §6, S3c §8).

    .venv/bin/python -m sim.live                       # http://localhost:8000/field.html , /console.html
    .venv/bin/python -m sim.live --scenario D1_demo --speed 20 --port 8000

지금은 기기 프로그램·로버 프로그램·시뮬레이터가 이 프로세스 하나 안에서 돈다(sim.sim.Sim이 둘 사이의 메시지를 건넨다).
명세의 최종 모양은 프로그램 둘이 따로 뜨고(`python -m device`, `python -m rover`) 무선 계층(host/transport.py)으로 잇는 것이다.
그때도 아래 주소와 메시지는 그대로다 — 화면은 어느 쪽인지 모른다.

  WS   /ws/screen         기기 프로그램 → 현장 화면: Snapshot(JSON) / 화면 → ScreenCmd
  WS   /ws/console        로버 프로그램 → 로버 콘솔: ConsoleSnapshot / 콘솔 → ConsoleCmd
  GET  /bundle/{path}     번들 파일(meta.json, tiles/…)
  GET  /console/height.json          지형의 높이 격자 (3D 보기용. 번들마다 한 번 만든다)
  GET  /console/science.png?kind=…   지금의 과학 가치 지도를 색 입힌 그림. kind: expected | max | base | var
  GET  /console/science_legend.json  그 그림의 색 눈금·등급 경계·놓임 (rover/console_map.py)
  GET  /sim/state         지금 도는 시나리오·배속·시각 (시뮬레이터 조작 막대용)
  POST /sim/start         {scenario, speed, manual}   manual = true면 가설 입력과 카드 선택을 사람이 한다
  POST /sim/speed         {speed}                     0 = 멈춤
  POST /sim/link          {ch, state}                 state: LOST | AUTO   (데모의 링크 버튼)
  POST /sim/inject        ScenarioEvent 한 개         지금 바로 넣는다
  GET  /sim/log           판정 기록(JSONL)
  POST /photo             사진 한 장(JPEG, 본문 그대로) → 그 자리에 촬영 흔적을 남기고 파일을 photos_live/에 둔다 (S2 §사진)
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
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from host import wire as w
from rover import console_map

from .scenario import ScenarioEvent, load_scenario
from .sim import Sim

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "sim/scenarios"
TICK_WALL_S = 0.05            # 실제 시간으로 이만큼마다 시뮬을 밀고 화면에 보낸다(초당 20번)
PHOTO_DIR = ROOT / "photos_live"   # 기기에 두는 사진 (저장소에 올리지 않는다 — .gitignore)
MAX_PHOTO_BYTES = 12 * 1024 * 1024  # 사진 한 장의 상한. 문서에 정해진 값이 없어 서버를 지키려고 둔 기술값이다
MAX_TICKS_PER_PUSH = 200      # 한 번에 미는 시뮬 틱의 상한 — 배속을 너무 높여도 서버가 멈추지 않게


# 요청 본문. 모듈 맨 위에 둬야 한다 — 함수 안에 두면 FastAPI가 타입 이름을 찾지 못해 본문으로 읽지 않는다
class StartBody(BaseModel):
    scenario: str
    speed: float = 10.0
    manual: bool = True


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
        self._height: dict | None = None  # 높이 격자 (번들이 같으면 다시 만들지 않는다)
        self._png: dict[tuple[int, str], bytes] = {}   # (science_rev, kind) → 그림. 지도가 바뀌면 새로 만든다
        self._debt = 0.0                  # 아직 밀지 못한 시뮬 시간(초)
        self._last = time.monotonic()
        self.run_tag = ""                 # 실행을 시작한 시각 — 사진 파일 이름 앞에 붙는다
        self.photos: list[dict] = []      # 이번 실행에서 찍은 사진 (찍은 순서)

    def start(self, name: str, speed: float, manual: bool) -> None:
        path = SCENARIO_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(name)
        sim = Sim(load_scenario(path), self.bundle_root)
        sim.auto_choose = not manual
        sim.manual_types = {"hyp"} if manual else set()
        sim.step()                        # 첫 스냅샷을 만든다
        self.sim, self.name, self.speed, self.manual, self._debt = sim, name, float(speed), manual, 0.0
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

    def state(self) -> dict:
        s = self.sim
        return {"scenario": self.name, "speed": self.speed, "manual": self.manual, "running": s is not None and not s.done(),
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

    @app.post("/sim/start")
    async def sim_start(b: StartBody):
        try:
            drv.start(b.scenario, b.speed, b.manual)
        except FileNotFoundError:
            raise HTTPException(404, f"시나리오 없음: {b.scenario}") from None
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

    app.mount("/bundle", StaticFiles(directory=bundle_root), name="bundle")
    dist = ROOT / "screen/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="screen")
    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="화면을 붙여 돌리는 실시간 서버")
    ap.add_argument("--bundle", default="data/bundles/jezero_west_v1")
    ap.add_argument("--scenario", default="D1_demo")
    ap.add_argument("--speed", type=float, default=10.0, help="시뮬 배속(1 = 실제 시간)")
    ap.add_argument("--auto", action="store_true", help="가설 입력과 카드 선택도 시나리오가 한다(구경만)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    uvicorn.run(make_app(a.bundle, a.scenario, a.speed, not a.auto), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
