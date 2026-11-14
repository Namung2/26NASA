"""Sim — 시나리오 하나를 처음부터 끝까지 돌린다 (docs/spec/S5 §2, §3).

한 틱(1초)에 하는 일
    1. 시각을 올리고 그 시각의 환경(태양·먼지·기온)을 번들의 표에서 읽는다
    2. 시나리오의 이벤트 가운데 때가 된 것을 넣는다 (관측, 가설, 링크 끊기 …)
    3. 승무원의 참 위치를 한 걸음 옮긴다 — 기기가 보여 주는 경로를 그대로 따라 걷고, 정지점에서는 머문다
    4. 기기에 센서 프레임을 준다 (on_sensor)
    5. 기기가 내놓은 메시지를 링크가 되는 채널로만 로버에 전하고, 로버의 답을 같은 식으로 기기에 전한다
    6. 카드가 떠 있으면 시나리오의 규칙대로 고른다 — 규칙에 맞는 카드가 없으면 고르지 않는다
    7. 기록한다

링크: 채널(UHF, Wi-Fi)마다 따로 판정한다. 시나리오가 손으로 끊거나 이은 것이 먼저고, 아니면 번들의 링크 지도에서
      승무원이 선 칸을 본다(1 = 됨). Wi-Fi는 로버 가까이(link.wifi_range_m)에서만 된다.
위치: 참 위치와 오차 반경을 그대로 센서 프레임에 싣는다. 이 도구는 위치를 추정하지 않는다.
같은 시나리오·같은 번들이면 언제나 같은 기록이 나온다(난수 없음).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import yaml

from device.node import DeviceNode
from host import bundle as hb
from host import wire as w
from host.frames import SensorFrame
from rover.service import RoverService

from .scenario import Scenario


class SimLog:
    """판정에 쓰는 기록. kind: event | dp | choice | mode | inject | snap | final"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, t: float, kind: str, data: dict) -> None:
        self.rows.append({"t": round(t, 3), "kind": kind, **data})

    def of(self, kind: str) -> list[dict]:
        return [r for r in self.rows if r["kind"] == kind]

    def digest(self) -> str:
        return w.digest(self.rows)

    def to_jsonl(self, path: Path) -> None:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in self.rows))


class Sim:
    def __init__(self, scenario: Scenario, bundle_root: str, *, dt: float = 1.0, params_path: str = "config/params.yaml") -> None:
        self.sc, self.dt = scenario, dt
        p = yaml.safe_load(Path(params_path).read_text())
        self.v_plan = float(p["mobility"]["v_plan_kmh"]["value"]) / 3.6
        self.wifi_range = float(p["link"]["wifi_range_m"]["value"])
        self.base_dose = float(p["radiation"]["dose_rate_mSv_day"]["value"]) * 1000.0 / 24.0
        self.spe_mult = float(p["radiation"]["spe_multiplier"].get("value") or p["radiation"]["spe_multiplier"]["placeholder"])
        fb, rb = hb.load(bundle_root, "field"), hb.load(bundle_root, "rover")
        fb.dose_rate_uSv_h = rb.dose_rate_uSv_h = self.base_dose
        self.fb, self.meta = fb, fb.meta
        if scenario.site != self.meta["bundle_id"]:
            raise ValueError(f"시나리오의 site({scenario.site})가 번들({self.meta['bundle_id']})과 다르다")
        self.pois = {x["id"]: (float(x["xy"][0]), float(x["xy"][1])) for x in self.meta["pois"]}
        park = scenario.start.rover_park
        self.park_xy = fb.park_xy(park)
        plan = [w.Stop(xy=self.pois[k], poi_id=k, dwell_min=float(scenario.dwell_min.get(k, 0.0)), purpose="poi") for k in scenario.poi_plan]
        self.dev = DeviceNode(scenario.nodes[0], fb, plan, park_id=park, params_path=params_path)
        self.rover = RoverService(rb, plan, park_id=park, crew=scenario.nodes[0], params_path=params_path)
        # 링크 지도(1 = 로버와 UHF 링크가 된다)
        lay = next((x for x in self.meta["layers"] if x["name"] == f"los_{park}" and abs(x["res_m"] - fb.res_m) < 1e-6), None)
        self.los = None
        if lay is not None:
            h, wd = lay["shape"]
            self.los = np.unpackbits(fb.layers[f"los_{park}"][0])[: h * wd].reshape(h, wd).astype(bool)
        self.manual: dict[str, str | None] = {"uhf": None, "wifi": None}

        s = scenario.start
        self.t = float(s.eva_elapsed_min) * 60.0
        self.t0 = self.t                               # 시나리오가 시작한 시각
        if isinstance(s.pos, dict):
            self.pos = self.pois[s.pos["poi"]]
        elif s.pos:
            self.pos = (float(s.pos[0]), float(s.pos[1]))
        else:
            self.pos = self.park_xy
        self.sigma = float(s.sigma_m)
        self.heading = 0.0
        self.dose = 0.0
        self.dwell_left = 0.0
        self.dwell_at: str | None = None
        self.arrivals: dict[str, float] = {}
        self.fired: dict[int, float] = {}              # 이벤트 번호(1부터) → 일어난 시각
        self.event_ids: dict[int, str] = {}            # 이벤트 번호 → 그 이벤트가 만든 로그 이벤트의 id
        self.overrides: dict = {}
        self.spe = False
        self.seen_dp: set[str] = set()
        self.dp_seen_t: dict[str, float] = {}
        self.last_mode = "FULL"
        self.log = SimLog()
        self.home = False
        # 화면을 붙여 돌릴 때(sim/live.py) 사람에게 넘기는 것. 화면 없이 돌릴 때는 둘 다 기본값(전부 시나리오가 한다)
        self.auto_choose = True                        # False면 카드를 고르지 않는다 — 사람이 화면에서 고른다
        self.manual_types: set[str] = set()            # 여기 든 종류의 이벤트(예: "hyp")는 넣지 않고, 사람이 화면에서 넣기를 기다린다

        # 승무원이 나가기 전: 로버가 귀환 지도를 계산해 기기에 넘긴다 (Wi-Fi, 한 번)
        self.rover.set_env(rb.env_at(self.t))
        head, payload = self.rover.start(self.t)
        self.dev.on_msg(head, payload)

    # ── 링크 ──
    def link_ok(self, ch: str) -> bool:
        m = self.manual[ch]
        if m is not None:
            return m != "LOST"
        ok = True
        if self.los is not None:
            r, c = int(-self.pos[1] // self.fb.res_m), int(self.pos[0] // self.fb.res_m)
            ok = bool(self.los[r, c]) if 0 <= r < self.los.shape[0] and 0 <= c < self.los.shape[1] else False
        if ch == "wifi":
            ok = ok and math.dist(self.pos, self.park_xy) <= self.wifi_range
        return ok

    # ── 이벤트 주입 ──
    def _due(self, i: int, ev) -> bool:
        at = ev.at
        if at.t_min is not None:
            return self.t >= at.t_min * 60.0
        if at.poi is not None:
            return at.poi in self.arrivals and self.t >= self.arrivals[at.poi] + at.dwell_min * 60.0
        if at.after_event is not None:
            return at.after_event in self.fired and self.t >= self.fired[at.after_event] + at.delay_min * 60.0
        return False

    def _inject(self, i: int, ev) -> None:
        p, before = ev.payload, set(self.dev.table.by_id)
        if ev.type == "obs":
            self.dev.on_command(w.CmdObs(found=p.get("kind", "found") == "found", confirmed=bool(p.get("confirmed", False)), note=str(p.get("note", p.get("signal", "")))))
        elif ev.type == "hyp":
            hint = self.meta.get("scenario_hint") or {}
            self.dev.add_hyp(w.HypPayload(hyp_id="suit-A:h-000", rule=p.get("rule", "strata_continuity"),
                                          direction_deg=float(p.get("direction_deg", hint.get("hyp_direction_deg", 0.0))) % 360.0,
                                          extent_m=float(p.get("extent_m", hint.get("hyp_extent_m", 300.0))), confidence=float(p.get("confidence", 0.5)),
                                          origin="script"), self.pos, self.t)
        elif ev.type == "link":
            state, ch = p.get("state", "LOST"), p.get("ch", "both")
            for name in (("uhf", "wifi") if ch == "both" else (ch,)):
                self.manual[name] = None if state in ("AUTO", None) else state
        elif ev.type == "spe":
            self.spe = bool(p.get("on", True))
        elif ev.type == "env":
            self.overrides.update(p)
        elif ev.type == "sigma":
            self.sigma = float(p.get("sigma_m", 0.0))
        elif ev.type == "photo":
            self.dev.on_command(w.CmdPhoto())
        elif ev.type == "return":
            self.dev.on_command(w.CmdReturn())
        made = [e for k, e in self.dev.table.by_id.items() if k not in before and e.type in ("obs", "hyp")]
        if made:
            self.event_ids[i] = made[0].id
        self.fired[i] = self.t
        self.log.record(self.t, "inject", {"event": i, "type": ev.type, "payload": p, "event_id": self.event_ids.get(i)})

    # ── 승무원 ──
    def _move(self, snap: w.Snapshot | None) -> bool:
        """참 위치를 한 걸음. 기기가 보여 주는 경로를 따라 걷고, 정지점에 닿으면 머문다. 움직였으면 True."""
        if self.dwell_left > 0:
            self.dwell_left -= self.dt
            return False
        if snap is None or not snap.plan:
            return False
        target, route = snap.plan[0], snap.route
        speed = self.v_plan
        if snap.gauge and snap.gauge.time_min > 0.2:
            speed = snap.gauge.distance_m / (snap.gauge.time_min * 60.0)          # 코어가 낸 "그 길을 걷는 시간"에 맞춘 속도
        step, pos = speed * self.dt, self.pos
        pts = [pos] + [tuple(q) for q in route[1:]] if len(route) > 1 else [pos, target.xy]
        for q in pts[1:]:
            d = math.dist(pos, q)
            if d <= step:
                pos, step = q, step - d
            else:
                self.heading = math.degrees(math.atan2(q[0] - pos[0], q[1] - pos[1])) % 360.0
                pos = (pos[0] + (q[0] - pos[0]) * step / d, pos[1] + (q[1] - pos[1]) * step / d)
                step = 0.0
                break
        self.pos = pos
        if math.dist(pos, target.xy) <= self.dev.arrive_m:                           # 도착 → 계획된 시간만큼 머문다
            self.dwell_left = target.dwell_min * 60.0
            if target.poi_id:
                self.arrivals.setdefault(target.poi_id, self.t)
            if target.purpose == "rover":
                self.home = True
            self.log.record(self.t, "event", {"what": "arrive", "poi": target.poi_id, "purpose": target.purpose})
        return True

    def _choose(self, snap: w.Snapshot) -> None:
        dp = snap.dp
        if dp is None or not self.auto_choose:
            return
        self.dp_seen_t.setdefault(dp.dp_id, self.t)
        for rule in self.sc.choices:
            wh = rule.when
            if "trigger" in wh and wh["trigger"] != dp.trigger:
                continue
            if "cause_event" in wh and self.event_ids.get(int(wh["cause_event"])) != dp.cause:
                continue
            if "forced" in wh and bool(wh["forced"]) != dp.forced:
                continue
            if self.t - self.dp_seen_t[dp.dp_id] < rule.delay_s:
                return
            pk = rule.pick
            opt = next((o for o in dp.options if ("from_hypothesis" in pk and o.from_hypothesis == bool(pk["from_hypothesis"]))
                        or ("label_key" in pk and o.label_key == pk["label_key"]) or ("kind" in pk and o.kind == pk["kind"])), None)
            if opt is not None:
                self.dev.on_command(w.CmdChoose(dp_id=dp.dp_id, option_id=opt.id))
                self.log.record(self.t, "choice", {"dp_id": dp.dp_id, "option": opt.id, "label_key": opt.label_key})
            return

    # ── 한 틱 ──
    def step(self) -> None:
        self.t += self.dt
        sun = self.fb.sun_at(self.t)
        wx = self.fb.weather_at(self.t)
        tau = float(self.overrides.get("tau_dust", wx["tau"]))
        dose_rate = self.base_dose * (self.spe_mult if self.spe else 1.0)
        for i, ev in enumerate(self.sc.events, start=1):
            if i in self.fired:
                continue
            if ev.type in self.manual_types:
                # 사람이 화면에서 넣기를 기다린다. 같은 종류의 이벤트가 로그에 새로 생기면 이 대본 이벤트가 일어난 것으로 친다
                # (뒤따르는 "after_event" 이벤트들이 그 시각을 기준으로 이어진다)
                used = set(self.event_ids.values())
                made = next((e for e in sorted(self.dev.table.by_id.values(), key=lambda e: e.lts)
                             if e.type == ev.type and e.id not in used and e.approved and e.ts >= self.t0), None)
                if made is not None:
                    self.event_ids[i], self.fired[i] = made.id, self.t
                    self.log.record(self.t, "inject", {"event": i, "type": ev.type, "payload": {"by": "screen"}, "event_id": made.id})
                continue
            if self._due(i, ev):
                self._inject(i, ev)
        self._move(self.dev.snapshot())
        self.dose += dose_rate * self.dt / 3600.0
        lm = int(sun["lmst_min"])
        self.dev.on_sensor(SensorFrame(t=self.t, lmst=f"{lm // 60:02d}:{lm % 60:02d}", pos=self.pos, sigma=self.sigma, heading_deg=self.heading,
                                       dose_cum_uSv=self.dose, tau_dust=tau, t_air_c=wx["t_air_c"], dose_rate=dose_rate, spe=self.spe,
                                       sun_elev=sun["elev_deg"], sun_az=sun["az_deg"], t_sunset_s=sun["t_sunset_s"], shadow_bin=int(sun["shadow_bin"])))
        env = self.rover.bundle.env_at(self.t, tau_dust=tau, dose_rate=dose_rate, spe=self.spe)
        self.rover.set_env(env)
        replies: list[w.Msg] = []
        for m in self.dev.outbox():
            if self.link_ok(m.ch):
                replies += self.rover.on_msg(m)
        for m in replies:
            if self.link_ok(m.ch):
                self.dev.on_msg(m)
        snap = self.dev.snapshot()
        self._record(snap)
        self._choose(snap)

    def _record(self, snap: w.Snapshot) -> None:
        mode = snap.state.link_mode
        if mode != self.last_mode:
            self.log.record(self.t, "mode", {"mode": mode})
            self.last_mode = mode
        if snap.dp is not None and snap.dp.dp_id not in self.seen_dp:
            self.seen_dp.add(snap.dp.dp_id)
            self.log.record(self.t, "dp", {"dp": snap.dp.model_dump(), "source": snap.dp_source})
        if int(self.t) % 10 == 0 or mode == "LOCAL":   # 끊긴 동안은 틱마다 남긴다 — "빈 화면 0틱"을 틱 단위로 판정한다(expect.options_paused_while_lost)
            self.log.record(self.t, "snap", {"pos": [round(self.pos[0], 1), round(self.pos[1], 1)], "mode": mode, "has_dp": snap.dp is not None,
                                             "dp_source": snap.dp_source if snap.dp else None, "paused": snap.options_paused, "pending": snap.pending_events,
                                             "has_route": bool(snap.route) or not snap.plan, "has_return": bool(snap.return_rover), "has_nlt": snap.nlt is not None,
                                             "slack_min": snap.nlt.slack_min if snap.nlt else None, "tau": snap.state.tau_dust, "plan": [s.poi_id or s.purpose for s in snap.plan],
                                             "rover_log": len(self.rover.table.by_id), "dev_log": snap.log_count})

    def done(self) -> bool:
        if self.sc.until_min is not None:
            return self.t >= self.sc.until_min * 60.0
        return self.home or self.t >= 8 * 3600.0

    def run(self, max_ticks: int = 40000) -> SimLog:
        for _ in range(max_ticks):
            if self.done():
                break
            self.step()
        # 마지막 기록: 두 프로그램의 로그에 든 이벤트. "끊긴 동안 쌓인 것이 다시 이어진 뒤 로버에 다 올라갔는가"를 판정하는 데 쓴다
        self.log.record(self.t, "final", {"home": self.home,
                                          "dev_events": sorted([e.id, round(e.ts, 3)] for e in self.dev.table.by_id.values()),
                                          "rover_ids": sorted(self.rover.table.by_id)})
        return self.log
