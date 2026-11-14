"""RoverService — 로버 프로그램의 본체 (docs/spec/S3b §2, §3).

밖에서 부르는 것:
    start(t)            로버가 섰다. 귀환 지도를 계산해 기기에 넘길 메시지를 돌려준다(승무원이 나가기 전에 한 번)
    set_env(env)        환경이 바뀌었다(그림자 구간, 먼지 …)
    on_msg(msg)         기기에서 온 메시지 하나 → 기기로 돌려보낼 메시지들
    console_snapshot()  계획 화면(로버 콘솔)에 보낼 상태

선택지 카드는 여기서만 만든다. 흐름:
    기기가 이벤트를 올림(sync_up) → 합침 → 지도 다시 계산 → 코어에 "물을 일이 생겼나"(bt_triggers) → 있으면 bt_decide →
    카드 2~3장은 기기로(dp), 후보 전체는 콘솔로. 사람이 고르면 choice 이벤트가 올라오고, 거기 실린 정지점이 새 계획이 된다.
로버는 고르지 않는다. 계획을 바꾸는 것은 올라온 choice 이벤트뿐이다.
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import yaml

from device.node import science_views
from host import btcore as bt
from host import bundle as hb
from host import config as hc
from host import convert as cv
from host import wire as w


def _v(node: dict):
    return node["value"] if node.get("value") is not None else node.get("placeholder")


class RoverService:
    def __init__(self, bundle: hb.Bundle, plan: list[w.Stop], *, park_id: str = "park1", crew: str = "suit-A",
                 tiers_path: str = "config/tiers.yaml", params_path: str = "config/params.yaml") -> None:
        self.bundle, self.meta, self.crew_node, self.node = bundle, bundle.meta, crew, "rover"
        p = yaml.safe_load(Path(params_path).read_text())
        self.sync_batch = int(_v(p["link"]["sync_batch"]))
        self.path_max_pts = int(_v(p["link"]["path_max_pts"]))
        self.arrive_m = float(_v(p["menu"]["arrive_radius_m"]))
        self.trace_max = int(_v(p["menu"]["trace_snapshot_max"]))
        self.cfg = hc.load_config(tiers_path, params_path, "rover", bundle.meta)
        self.core = bt.Core.create(self.cfg)
        bundle.attach(self.core, park_id)
        self.park_xy = bundle.park_xy(park_id)
        self.table = cv.EventTable()
        self.poi_ids = [x["id"] for x in self.meta["pois"]]
        self.poi_index = {pid: i + 1 for i, pid in enumerate(self.poi_ids)}
        cv.merge_events(self.core, self.table, self._initial_events())

        self.plan: list[w.Stop] = list(plan)        # 밖에 나간 우주인 한 사람의 계획
        self.visited: list[tuple[float, float]] = []
        self.history: list[tuple[w.ChoiceEvent, list[w.Stop]]] = []   # (선택, 그 선택 직전의 계획) — 가설을 거둘 때 되돌아갈 길을 찾는다
        self.crew: w.State | None = None
        self.t = 0.0
        self.last_rx_t = -1e9
        self._resend = False                        # 링크가 돌아온 뒤 열린 결정 지점을 다시 보낼 차례인가
        self.env_bin = -1
        self.rebuild = True
        self.seq = 0
        self.open_trigger: bt.BtTrigger | None = None               # 사람이 아직 고르지 않은 결정 지점의 원인
        self.open_dp: w.DecisionPoint | None = None
        self.open_seq = 0
        self.candidates: list[w.Option] = []
        self.recent_dps: list[w.DecisionPoint] = []
        self.alerts: list[str] = []
        self._route: list[tuple[float, float]] = []
        self._route_key = None
        self._views = {"hyps": [], "traces": [], "obs": []}
        self._env: bt.BtEnv | None = None

    def _initial_events(self) -> list:
        import json
        path = self.bundle.root / "events0.json"
        if not path.exists():
            return []
        return [w.ObsEvent.model_validate(e) for e in json.loads(path.read_text()) if e.get("type") == "obs"]

    # ── 시작·환경 ──
    def set_env(self, env: bt.BtEnv) -> None:
        self._env = env
        self.core.set_env(env)
        if self.rebuild or env.shadow_bin != self.env_bin:
            self.core.costmap_build()
            self.env_bin, self.rebuild, self._route_key = env.shadow_bin, False, None

    def start(self, t: float):
        """로버가 선 자리에서 귀환 지도를 계산한다. (머리 메시지, (걷는 시간 배열, 다음 방향 배열))을 돌려준다.

        실제로는 승무원이 나가기 전에 Wi-Fi로 기기에 넘긴다. 승무원이 밖에 있는 동안 로버는 그 자리에 머문다.
        """
        self.core.cost_to_go(self.park_xy)
        tm, nx, res = self.core.field_copy()
        self.core.science_update(t)
        self._views = science_views(self.core, self.table, self.trace_max)
        self.seq += 1
        head = w.ReturnFieldMsg(ch="wifi", seq=self.seq, node="rover", t_send=t, rover_id="rover", rover_xy=self.park_xy, res_m=res, shape=tm.shape)
        return head, (tm, nx)

    # ── 기기에서 온 메시지 ──
    def on_msg(self, msg: w.Msg) -> list[w.Msg]:
        self.t = max(self.t, msg.t_send)
        out: list[w.Msg] = []
        if msg.type == "hb":
            gap = msg.t_send - self.last_rx_t
            self.last_rx_t = msg.t_send
            out.append(w.HbAck(ch=msg.ch, seq=msg.seq, node="rover", t_send=msg.t_send, ack_seq=msg.seq))
            if msg.ch == "uhf" and gap > 5.0:
                self._resend = True                 # 끊겼다 다시 이어졌다 → 새 상태(텔레메트리)가 오면 열린 결정 지점을 다시 보낸다
        elif msg.type == "telemetry":
            self.crew = msg.state
            self._track_visits()
            if self._resend:
                # 사람이 아직 고르지 않은 결정 지점은 "지금" 상태로 다시 계산해 한 번 더 보낸다 (기기는 끊김이 오래가면 카드를 내린다).
                # 하트비트가 아니라 텔레메트리에서 하는 이유: 끊기기 전의 위치·시각으로 계산한 카드를 보내지 않기 위해서다.
                # 기기는 링크가 돌아왔다고 판정한 뒤에야 텔레메트리를 보내므로, 기기 화면의 링크 표시와 카드가 어긋나지 않는다.
                self._resend = False
                if self.open_trigger is not None:
                    out += self._decide(self.open_trigger)
            out += self._check_triggers([])
        elif msg.type == "sync_up":
            fresh = cv.merge_events(self.core, self.table, list(msg.events))
            self.seq += 1
            out.append(w.SyncDown(ch="uhf", seq=self.seq, node="rover", t_send=self.t,          # 새 것이 없어도 항상 답한다 — 기기의 재전송을 멈춘다
                                  events=cv.events_since(self.core, self.table, dict(msg.have_lts), self.sync_batch), have_lts=cv.have_dict(self.core)))
            if fresh:
                out += self._on_new_events(fresh)
        return out

    def _on_new_events(self, fresh: list) -> list[w.Msg]:
        prev_plan: list[w.Stop] | None = None
        for e in fresh:
            if e.type == "choice":                  # 사람이 골랐다 → 그 결정 지점을 닫고 계획을 바꾼다
                self.history.append((e, list(self.plan)))
                self.plan = list(e.payload.stops)
                self._route_key = None
                if self.open_dp is not None and e.payload.dp_id == self.open_dp.dp_id:
                    self.core.decision_close(self.open_seq)
                    self.open_trigger = self.open_dp = None
            elif e.type == "mark" and e.payload.what == "blocked":
                self.rebuild = True                 # 막힘 → 코스트맵과 귀환 지도를 다시 계산한다
            elif e.type == "hyp" and e.payload.supersedes:
                prev_plan = self._plan_before(e.payload.supersedes)
        if self.rebuild and self._env is not None:
            self.set_env(self._env)
            self.core.cost_to_go(self.park_xy)
        self.core.science_update(self.t)
        self._views = science_views(self.core, self.table, self.trace_max)
        return self._check_triggers(fresh, prev_plan)

    def _plan_before(self, hyp_id: str) -> list[w.Stop] | None:
        """그 가설이 기여한 선택 직전의 계획에서, 그 뒤에 이미 들른 지점을 뺀 것. 그런 선택이 없으면 None."""
        for choice, before in reversed(self.history):
            if hyp_id in choice.payload.hyp_ids:
                left = [s for s in before if not any(math.dist(s.xy, v) <= self.arrive_m for v in self.visited)]
                return left or None
        return None

    def _track_visits(self) -> None:
        while self.crew is not None and self.plan and math.dist(self.crew.pos, self.plan[0].xy) <= self.arrive_m:
            self.visited.append(self.plan.pop(0).xy)
            self._route_key = None

    # ── 결정 지점 ──
    def _bt_state(self) -> bt.BtState:
        c, s = self.crew, bt.BtState()
        s.t, s.pos, s.heading_deg, s.sigma, s.dose_cum_uSv = c.t, bt.BtXY(*c.pos), c.heading_deg, c.sigma, c.dose_cum_uSv
        s.link_mode, s.node, s.rover_pos = bt.LINK_FULL, bt.NODE[self.crew_node], bt.BtXY(*self.park_xy)
        return s

    def _check_triggers(self, fresh: list, prev_plan: list[w.Stop] | None = None) -> list[w.Msg]:
        if self.crew is None:
            return []
        tin = bt.BtTriggerIn()
        changed = [e for e in fresh if e.type in ("obs", "hyp")][-bt.MAX_CHANGED:]
        tin.n_changed = len(changed)
        for i, e in enumerate(changed):
            tin.changed[i].lts, tin.changed[i].node = e.lts, bt.NODE[e.node]
        # 경로 갈림길은 "다음 지점으로 가는 길"에만 묻는다. 로버로 돌아가는 중이면 묻지 않는다 — 귀환 경로는 귀환 지도가 정한다
        if self.plan and self.plan[0].purpose != "rover":
            tin.has_next_stop, tin.next_stop = 1, bt.BtXY(*self.plan[0].xy)
        out: list[w.Msg] = []
        for tr in self.core.triggers(self._bt_state(), tin):
            if tr.kind in (bt.TRIG_FORK, bt.TRIG_ENV):
                out += self._decide(tr, prev_plan)
        return out

    def _decide(self, tr: bt.BtTrigger, prev_plan: list[w.Stop] | None = None) -> list[w.Msg]:
        st = self._bt_state()
        to_bt = lambda stops: [cv.to_bt_stop(s, self.poi_index) for s in stops]
        d = self.core.decide(st, to_bt(self.plan), tr, to_bt(prev_plan) if prev_plan else None)
        if d.n_options == 0 and d.notices == 0:
            return []                               # 코어가 "묻지 않는다"고 했다(눈에 같은 선택지)
        dp = cv.decision_from_bt(self.core, d, self.poi_ids, self.path_max_pts)
        # 콘솔용: 출발 한계를 통과한 후보 전체 + 경로의 고도 단면
        self.candidates = []
        for c in self.core.decision_candidates(d):
            tmp = bt.BtDecision()
            tmp.seq, tmp.n_options = d.seq, 1
            tmp.options[0] = c
            via = [(c.stops[k].xy.x, c.stops[k].xy.y) for k in range(max(0, c.n_stops - 1))]
            pts = self.core.path_polyline(self.core.decision_path(tmp, 0), via)
            opt = cv.option_from_bt(self.core, c, pts, self.poi_ids)
            self.candidates.append(opt.model_copy(update={"profile": self._profile(pts)}))
        self.open_trigger, self.open_dp, self.open_seq = bt.BtTrigger.from_buffer_copy(tr), dp, d.seq
        self.recent_dps = (self.recent_dps + [dp])[-5:]
        self.seq += 1
        return [w.DpMsg(ch="uhf", seq=self.seq, node="rover", t_send=self.t, dp=dp)]

    def _profile(self, pts) -> list[tuple[float, float]]:
        """경로의 고도 단면 (누적 거리 m, 고도 m). 꺾이는 점 사이를 20 m 간격으로 짚어 번들의 고도 레이어에서 읽는다."""
        if "elev" not in self.bundle.layers or len(pts) < 2:
            return []
        elev, lay = self.bundle.layers["elev"]
        res, (h, w_) = lay["res_m"], lay["shape"]
        out, dist = [], 0.0
        for a, b in itertools.pairwise(pts):
            seg = float(np.hypot(b[0] - a[0], b[1] - a[1]))
            n = max(1, int(seg // 20.0))
            for k in range(n):
                x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
                r, c = min(h - 1, max(0, int(-y // res))), min(w_ - 1, max(0, int(x // res)))
                z = float(elev[r, c]) * float(lay.get("scale", 1.0)) + float(lay.get("offset", 0.0))
                out.append((round(dist + seg * k / n, 1), round(z, 1)))
            dist += seg
        return out

    # ── 콘솔 ──
    def console_snapshot(self, t: float, lmst: str = "") -> w.ConsoleSnapshot:
        nlt = None
        if self.crew is not None:
            st = self._bt_state()
            key = (round(self.crew.pos[0] / 10), round(self.crew.pos[1] / 10), self.plan[0].xy if self.plan else None)
            if key != self._route_key:
                self._route_key, self._route = key, []
                if self.plan:
                    p = self.core.plan(self.crew.pos, self.plan[0].xy)
                    if p.status >= 0:
                        self._route = [(float(x), float(y)) for x, y in self.core.path_polyline(p)]
            try:
                n = self.core.depart_limit(st)
                rp = self.core.return_path(self.crew.pos)
                m = self.core.path_measure(rp, st, bt.WALK_RETURN) if rp.status == bt.OK else None
                nlt = w.NltView(t_depart=n.t_depart, slack_min=round(float(n.slack_min), 1), binding=bt.BINDINGS[n.binding], degraded=bool(n.degraded),
                                return_dist_m=round(float(m.length_m), 0) if m else 0.0, return_time_min=round(float(m.time_min), 1) if m else 0.0)
            except bt.BtError:
                nlt = None
        link_up = (t - self.last_rx_t) <= 5.0
        alerts = [] if link_up else [f"기기 응답 없음 · {t - self.last_rx_t:.0f}초"]
        shown = [o.digest for o in self.open_dp.options] if self.open_dp else []
        crew = w.CrewStatus(node=self.crew_node, state=self.crew, last_rx_s=round(t - self.last_rx_t, 1), nlt=nlt, plan=self.plan, route=self._route)
        return w.ConsoleSnapshot(t=t, lmst=lmst, rover_pos=self.park_xy, candidates=self.candidates, shown_ids=shown, crew=crew, alerts=alerts,
                                 recent_decisions=self.recent_dps, recent_events=self.table.ordered()[-20:], hyps=self._views["hyps"],
                                 obs=self._views["obs"], traces=self._views["traces"], missing_layers=self.meta.get("missing_layers", []), link_up=link_up)
