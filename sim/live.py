"""화면을 붙여 돌리는 실시간 서버 (docs/spec/S5 §6, S3c §8).

    .venv/bin/python -m sim.live                       # http://localhost:8000/field.html , /console.html
    .venv/bin/python -m sim.live --scenario D1_demo --speed 20 --port 8000

지금은 기기 프로그램·로버 프로그램·시뮬레이터가 이 프로세스 하나 안에서 돈다(sim.sim.Sim이 둘 사이의 메시지를 건넨다).
명세의 최종 모양은 프로그램 둘이 따로 뜨고(`python -m device`, `python -m rover`) 무선 계층(host/transport.py)으로 잇는 것이다.
그때도 아래 주소와 메시지는 그대로다 — 화면은 어느 쪽인지 모른다.

  WS   /ws/screen         기기 프로그램 → 현장 화면: Snapshot(JSON) / 화면 → ScreenCmd
  WS   /ws/console        로버 프로그램 → 로버 콘솔: ConsoleSnapshot / 콘솔 → ConsoleCmd
  GET  /bundle/{path}     번들 파일(meta.json, tiles/…)
  GET  /sim/state         지금 도는 시나리오·배속·시각 (시뮬레이터 조작 막대용)
  POST /sim/start         {scenario, speed, manual}   manual = true면 가설 입력과 카드 선택을 사람이 한다
  POST /sim/speed         {speed}                     0 = 멈춤
  POST /sim/link          {ch, state}                 state: LOST | AUTO   (데모의 링크 버튼)
  POST /sim/inject        ScenarioEvent 한 개         지금 바로 넣는다
  GET  /sim/log           판정 기록(JSONL)
  GET  /                  screen/dist (npm run build로 만든 화면)

/sim/* 은 보여 주기·개발 전용이다. 실제 기기에는 없다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from host import wire as w

from .scenario import ScenarioEvent, load_scenario
from .sim import Sim

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "sim/scenarios"
TICK_WALL_S = 0.05            # 실제 시간으로 이만큼마다 시뮬을 밀고 화면에 보낸다(초당 20번)
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
        self._debt = 0.0                  # 아직 밀지 못한 시뮬 시간(초)
        self._last = time.monotonic()

    def start(self, name: str, speed: float, manual: bool) -> None:
        path = SCENARIO_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(name)
        sim = Sim(load_scenario(path), self.bundle_root)
        sim.auto_choose = not manual
        sim.manual_types = {"hyp"} if manual else set()
        sim.step()                        # 첫 스냅샷을 만든다
        self.sim, self.name, self.speed, self.manual, self._debt = sim, name, float(speed), manual, 0.0

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
