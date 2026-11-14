"""DeviceNode — 기기 프로그램의 본체 (docs/spec/S3c §1, §2, §4, §7).

밖에서 부르는 것은 다섯 가지뿐이다:
    on_sensor(frame)   한 틱. 위치·환경을 받아 코어를 정해진 순서로 부르고 스냅샷을 만든다
    on_msg(msg)        로버에서 온 메시지 하나 (하트비트 응답, 결정 지점, 이벤트, 귀환 지도 …)
    on_command(cmd)    화면에서 온 조작 하나 (선택, 관측, 가설, 귀환 …)
    snapshot()         화면에 보낼 상태 — 마지막 틱에 만든 것
    outbox()           로버로 보낼 메시지들 (꺼내면 비워진다)

지키는 것
  · 틱은 네트워크를 기다리지 않는다. 그때 도착해 있는 것만 처리하고, 보낼 것은 outbox에 쌓는다.
  · 여기에는 판단이 없다. 경로·출발 한계·안전 트리거·지도는 코어 함수의 결과를 옮길 뿐이다.
    예외는 표시용 깃발 둘(pos_warn, tau_warn)과 "정지점에 닿았는가"(계획에서 지난 지점을 빼는 일)다.
  · 선택지 카드는 만들지 않는다 — 로버가 보낸 것을 보인다. 직접 내는 카드는 귀환 카드 하나뿐이다(출발 한계 임박, "귀환" 버튼).
  · 링크가 끊겨도 위치·경로·귀환 경로·출발 한계·입력은 그대로 된다. 끊김이 오래가면 떠 있던 카드만 내린다(선택지 정지).
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml

from host import btcore as bt
from host import bundle as hb
from host import config as hc
from host import convert as cv
from host import templates as tp
from host import wire as w
from host.frames import SensorFrame


def _v(node: dict):
    return node["value"] if node.get("value") is not None else node.get("placeholder")


class DeviceNode:
    def __init__(self, node: str, bundle: hb.Bundle, plan: list[w.Stop], *, park_id: str = "park1",
                 tiers_path: str = "config/tiers.yaml", params_path: str = "config/params.yaml") -> None:
        self.node, self.bundle, self.meta = node, bundle, bundle.meta
        p = yaml.safe_load(Path(params_path).read_text())
        self.sigma_warn = float(_v(p["nav"]["sigma_warn_m"]))
        self.sync_batch = int(_v(p["link"]["sync_batch"]))
        self.extent_levels = list(_v(p["menu"]["extent_levels_m"]))
        self.conf_levels = list(_v(p["menu"]["confidence_levels"]))
        self.mark_radius = list(_v(p["menu"]["mark_radius_levels_m"]))
        self.arrive_m = float(_v(p["menu"]["arrive_radius_m"]))
        self.note_max = int(_v(p["menu"]["note_max_chars"]))
        self.trace_max = int(_v(p["menu"]["trace_snapshot_max"]))

        self.cfg = hc.load_config(tiers_path, params_path, "device", bundle.meta, node=node)
        self.core = bt.Core.create(self.cfg)
        bundle.attach(self.core, park_id)
        self.table = cv.EventTable()
        self.poi_ids = [x["id"] for x in self.meta["pois"]]
        self.poi_index = {pid: i + 1 for i, pid in enumerate(self.poi_ids)}
        cv.merge_events(self.core, self.table, self._initial_events())

        self.plan: list[w.Stop] = list(plan)
        self.link = bt.BtLink()                     # 링크 상태기계의 상태(코어가 고쳐 쓴다)
        self.t = 0.0
        self.hb_seq = 0
        self.acked: dict[str, int] = {}             # 로버가 "여기까지 받았다"고 알려 준 것
        self.dp: w.DecisionPoint | None = None
        self.dp_source = "rover"
        self.dp_rx_t = 0.0
        self.dp_bt_seq = 0                          # 기기가 직접 낸 결정 지점의 코어 번호(닫을 때 쓴다)
        self.options_paused = False
        self.hyp_draft: w.HypDraft | None = None
        self.want_return = False
        self.field_ready = False
        self.rover_xy: tuple[float, float] | None = None
        self.env_bin = -1
        self.rebuild = True                         # 코스트맵을 다시 만들어야 하는가(그림자 구간·막힘 표시가 바뀜)
        self.science_dirty = True
        self.science_t = -1e9
        self.n_hyp = self.n_obs = 0
        self.spe_alert: bool | None = None
        self._route: list[tuple[float, float]] = []
        self._route_key = None
        self._gauge: w.GaugeView | None = None
        self._views = {"hyps": [], "traces": [], "obs": []}
        self._out: list[w.Msg] = []
        self._snap: w.Snapshot | None = None
        self._frame: SensorFrame | None = None

    # ── 시작 ──
    def _initial_events(self) -> list:
        """번들의 events0.json(선행 임무의 시료 결과)을 와이어 이벤트로 읽는다."""
        path = self.bundle.root / "events0.json"
        if not path.exists():
            return []
        import json
        return [w.ObsEvent.model_validate(e) for e in json.loads(path.read_text()) if e.get("type") == "obs"]

    # ── 한 틱 ──
    def on_sensor(self, f: SensorFrame) -> None:
        core = self.core
        self.t, self._frame = f.t, f
        st = self._bt_state(f)

        # 환경을 코어에 넣는다. 그림자 구간이 바뀌거나 막힘 표시가 들어왔으면 코스트맵을 다시 만든다
        env = bt.BtEnv()
        env.sun_elev_deg, env.sun_az_deg, env.t_sunset_s = f.sun_elev, f.sun_az, f.t_sunset_s
        env.tau_dust, env.dose_rate_uSv_h, env.shadow_bin = f.tau_dust, f.dose_rate, f.shadow_bin
        env.spe = 1 if (f.spe if self.spe_alert is None else self.spe_alert) else 0
        core.set_env(env)
        if self.rebuild or f.shadow_bin != self.env_bin:
            core.costmap_build()
            self.env_bin, self.rebuild, self._route_key = f.shadow_bin, False, None

        # 링크: 틱을 알리고 하트비트를 보낸다 (응답은 on_msg로 들어온다)
        t_ms = f.t * 1000.0
        changed, lost = core.link_step(self.link, t_ms, bt.NET_TICK)
        self.hb_seq += 1
        for ch_name, ch in (("uhf", bt.CH_UHF), ("wifi", bt.CH_WIFI)):
            core.link_step(self.link, t_ms, bt.NET_SENT, ch, self.hb_seq)
            self._out.append(w.Hb(ch=ch_name, seq=self.hb_seq, node=self.node, t_send=f.t, bundle_id=self.meta["bundle_id"]))
        local = self.link.mode == bt.LINK_LOCAL
        if changed and local and self.dp is not None and self.dp_source == "rover":
            self.dp_source = "cache"                # 끊기기 전에 받은 카드 — 계산 시각을 함께 보인다
        if changed and not local:
            self.options_paused = False
        if lost:                                    # 끊김이 오래갔다 → 떠 있던 카드를 내리고 선택지 정지
            if self.dp is not None and self.dp_source != "local":
                self.dp = None
            self.options_paused = True

        # 지도: 로그가 바뀌었거나 흔적이 옅어질 만큼 시간이 흘렀으면 다시 계산
        if self.science_dirty or f.t - self.science_t >= 60.0:
            core.science_update(f.t)
            self.science_dirty, self.science_t = False, f.t
            self._refresh_views()

        # 계획에서 지난 지점을 뺀다
        while self.plan and math.dist(f.pos, self.plan[0].xy) <= self.arrive_m:
            self.plan.pop(0)
            self._route_key = None
            # 지점에 닿아 계획이 한 칸 나아갔다 → 떠 있던 로버의 카드는 "닿기 전의 계획"으로 계산한 것이라 낡았다.
            # 그대로 두면 그 카드의 "계획 유지"가 방금 지난 지점을 다시 들르는 계획이 된다(되돌아가게 된다) → 내린다.
            # 연결돼 있으면 로버가 지금 상태로 다시 계산한 카드를 곧 보낸다(rover/service.py). 기기가 직접 낸 귀환 카드는 그대로 둔다
            if self.dp is not None and self.dp_source != "local":
                self.dp = None

        # 안전 감시와 귀환 카드 — 링크와 무관하게 기기가 직접 한다
        nlt_view, nlt_warn, back = None, False, []
        if self.field_ready:
            safety, nlt_warn = core.safety_check(st)
            tin = bt.BtTriggerIn()
            tin.n_safety = len(safety)
            for i, s in enumerate(safety):
                tin.safety[i] = s
            tin.user_request = 1 if self.want_return else 0
            self.want_return = False
            for tr in core.triggers(st, tin):
                if tr.kind in (bt.TRIG_SAFETY, bt.TRIG_USER_REQUEST):
                    d = core.decide(st, [cv.to_bt_stop(s, self.poi_index) for s in self.plan], tr)
                    # 이미 로버로 돌아가는 중인데 코어가 낸 것이 "귀환" 하나뿐이면 같은 카드를 다시 띄우지 않는다.
                    # (판단은 코어가 했고, 여기서는 이미 하고 있는 일을 또 묻지 않을 뿐이다. 알림이 붙었으면 그대로 띄운다)
                    returning = bool(self.plan) and all(s.purpose == "rover" for s in self.plan)
                    only_return = d.n_options > 0 and all(bt.OPT_KINDS[d.options[i].kind] == "return" for i in range(d.n_options))
                    if tr.kind == bt.TRIG_SAFETY and returning and only_return and not d.notices:
                        core.decision_close(d.seq)
                        continue
                    if d.n_options or d.notices:
                        self.dp = cv.decision_from_bt(core, d, self.poi_ids)
                        self.dp_source, self.dp_rx_t, self.dp_bt_seq = "local", f.t, d.seq
            rp = core.return_path(f.pos)
            if rp.status == bt.OK:
                back = [(float(x), float(y)) for x, y in core.path_polyline(rp)]
                m = core.path_measure(rp, st, bt.WALK_RETURN)
                n = core.depart_limit(st)
                nlt_view = w.NltView(t_depart=n.t_depart, slack_min=round(float(n.slack_min), 1), binding=bt.BINDINGS[n.binding],
                                     degraded=bool(n.degraded), return_dist_m=round(float(m.length_m), 0), return_time_min=round(float(m.time_min), 1))

        # 다음 정지점까지의 경로와 게이지 (위치가 한 칸 넘게 움직였거나 계획이 바뀌었을 때만 다시 푼다)
        if self.plan and self.plan[0].purpose == "rover" and back:
            # 로버로 돌아가는 구간: 귀환 카드·출발 한계와 같은 경로(귀환 지도)와 같은 속도(귀환 속도)로 안내한다.
            # 여기서 따로 길을 풀면 카드에 적힌 귀환 시간과 화면의 남은 시간이 서로 달라진다
            self._route, self._route_key = back, None
            self._gauge = w.GaugeView(bearing_deg=float(core.gauge(self.plan[0].xy, m, st).bearing_deg) % 360.0,
                                      distance_m=round(float(m.length_m), 0), time_min=round(float(m.time_min), 1))
        elif self.plan:
            key = (round(f.pos[0] / self.cfg.grid_m), round(f.pos[1] / self.cfg.grid_m), self.plan[0].xy)
            if key != self._route_key:
                p = core.plan(f.pos, self.plan[0].xy)
                self._route_key = key
                if p.status >= 0:
                    self._route = [(float(x), float(y)) for x, y in core.path_polyline(p)]
                    g = core.gauge(self.plan[0].xy, core.path_measure(p, st), st)
                    self._gauge = w.GaugeView(bearing_deg=float(g.bearing_deg) % 360.0, distance_m=round(float(g.distance_m), 0), time_min=round(float(g.time_min), 1))
                else:
                    self._route, self._gauge = [], None
        else:
            self._route, self._gauge = [], None

        # 로버로: 상태(텔레메트리)와 아직 못 올린 이벤트. 끊겨 있으면 로그에 쌓아 두기만 한다
        state = self._wire_state(f)
        if not local:
            self._out.append(w.Telemetry(ch="uhf", seq=self.hb_seq, node=self.node, t_send=f.t, state=state))
            pending = cv.events_since(core, self.table, self.acked, self.sync_batch)
            if pending or self.hb_seq % 5 == 0:
                self._out.append(w.SyncUp(ch="uhf", seq=self.hb_seq, node=self.node, t_send=f.t, events=pending, have_lts=cv.have_dict(core)))

        self._snap = self._build_snapshot(f, state, nlt_view, nlt_warn, back)

    # ── 로버에서 온 메시지 ──
    def on_msg(self, msg: w.Msg, payload=None) -> None:
        core, t_ms = self.core, self.t * 1000.0
        if msg.type == "hb_ack":
            core.link_step(self.link, t_ms, bt.NET_ACK, bt.CH_UHF if msg.ch == "uhf" else bt.CH_WIFI, msg.ack_seq)
        elif msg.type == "dp":
            self.dp, self.dp_source, self.dp_rx_t, self.options_paused = msg.dp, "rover", self.t, False
        elif msg.type == "sync_down":
            fresh = cv.merge_events(core, self.table, list(msg.events))
            self.acked = dict(msg.have_lts)
            if fresh:
                self.science_dirty = True
                self.rebuild = self.rebuild or any(e.type == "mark" and e.payload.what == "blocked" for e in fresh)
        elif msg.type == "return_field" and payload is not None:
            core.set_field(payload[0], payload[1], msg.res_m)        # 귀환 지도: 로버가 선 자리에서 계산해 나가기 전에 넘겨준 것
            self.field_ready, self.rover_xy = True, msg.rover_xy
        elif msg.type == "alert":
            self.spe_alert = msg.kind == "spe_on"

    # ── 화면에서 온 조작 ──
    def on_command(self, cmd) -> None:
        f = self._frame
        if f is None:
            return
        pos, t = f.pos, f.t
        if cmd.kind == "choose":
            self._choose(cmd, pos, t)
        elif cmd.kind == "obs":
            self.n_obs += 1
            cv.append_event(self.core, self.table, self.node, "obs", pos, t,
                            w.ObsPayload(obs_id=f"{self.node}:o-{self.n_obs:03d}", kind="found" if cmd.found else "not_found",
                                         confirmed=cmd.confirmed, note=cmd.note[: self.note_max]))
            cv.append_event(self.core, self.table, self.node, "trace", pos, t, w.TracePayload(kind="mention"))   # 관측한 자리는 주의 흔적으로 남는다
            self.science_dirty = True
        elif cmd.kind == "hyp":
            d = w.HypDraft(rule=cmd.rule, direction_idx=cmd.direction_idx, extent_idx=cmd.extent_idx, confidence_idx=cmd.confidence_idx)
            self.hyp_draft = d.model_copy(update={"readback": tp.hyp_readback(d, self.extent_levels)})
        elif cmd.kind == "hyp_withdraw":
            d = w.HypDraft(withdraw_hyp_id=cmd.hyp_id)
            self.hyp_draft = d.model_copy(update={"readback": tp.hyp_readback(d, self.extent_levels)})
        elif cmd.kind == "hyp_reply":
            self._hyp_reply(cmd.reply, pos, t)
        elif cmd.kind == "return":
            self.want_return = True                 # 다음 틱에 귀환 카드가 나온다
        elif cmd.kind == "photo":
            cv.append_event(self.core, self.table, self.node, "trace", pos, t, w.TracePayload(kind="photo"))
            self.science_dirty = True
        elif cmd.kind == "mark":
            blocked = cmd.what == "blocked"
            radius = self.mark_radius[max(0, min(len(self.mark_radius) - 1, cmd.radius_idx))] if blocked else 0.0
            cv.append_event(self.core, self.table, self.node, "mark", pos, t,
                            w.MarkPayload(what=cmd.what, name=cmd.name[:40], radius_m=radius, note=cmd.note[: self.note_max]))
            self.rebuild = self.rebuild or blocked  # 막힘 → 그 반경이 통과 불가가 되므로 코스트맵을 다시 만든다

    def _choose(self, cmd, pos, t) -> None:
        if self.dp is None or cmd.dp_id != self.dp.dp_id:
            return                                  # 이미 내려간 카드에 대한 선택은 버린다
        opt = next((o for o in self.dp.options if o.id == cmd.option_id), None)
        if opt is None:
            return
        cv.append_event(self.core, self.table, self.node, "choice", pos, t, w.ChoicePayload(
            dp_id=self.dp.dp_id, option_id=opt.id, options_shown=[o.id for o in self.dp.options], sort_key=cmd.sort_key,
            was_hypothesis_option=opt.from_hypothesis, hyp_ids=opt.hyp_ids, option_digest=opt.digest,
            latency_s=round(t - self.dp_rx_t, 1), stops=opt.stops))
        self.plan = list(opt.stops)                 # 고른 옵션의 정지점이 새 계획이 된다 — 바꾸는 것은 사람의 선택뿐이다
        self._route_key = None
        if self.dp_source == "local":
            self.core.decision_close(self.dp_bt_seq)
        self.dp = None

    def _hyp_reply(self, reply: str, pos, t) -> None:
        d = self.hyp_draft
        if d is None:
            return
        if reply == "edit":
            return                                  # 고른 값을 그대로 둔 채 메뉴로 돌아간다
        self.hyp_draft = None
        if reply != "approve":
            return                                  # 거절 → 이벤트 없음
        self.n_hyp += 1
        new_id = f"{self.node}:h-{self.n_hyp:03d}"
        if d.withdraw_hyp_id:                       # 철회: 이전 가설의 값을 그대로 싣고, 승인 안 됨으로 넣는다
            old = next((e for e in self.table.by_id.values() if e.type == "hyp" and e.payload.hyp_id == d.withdraw_hyp_id), None)
            if old is None:
                return
            cv.append_event(self.core, self.table, self.node, "hyp", old.geom.xy, t,
                            old.payload.model_copy(update={"hyp_id": new_id, "supersedes": d.withdraw_hyp_id}), approved=False)
        else:
            if d.rule is None or None in (d.direction_idx, d.extent_idx, d.confidence_idx):
                return                              # 빈칸이 있으면 넣지 않는다 — 시스템은 빈칸을 채우지 않는다
            cv.append_event(self.core, self.table, self.node, "hyp", pos, t, w.HypPayload(
                hyp_id=new_id, rule=d.rule, direction_deg=45.0 * d.direction_idx, extent_m=self.extent_levels[d.extent_idx],
                confidence=self.conf_levels[d.confidence_idx], origin="menu"))
        self.science_dirty = True

    def add_hyp(self, payload: w.HypPayload, xy, t) -> None:
        """시나리오가 넣는 가설(메뉴와 같은 구조). 사람이 화면에서 넣을 때는 on_command를 거친다."""
        self.n_hyp += 1
        cv.append_event(self.core, self.table, self.node, "hyp", xy, t, payload.model_copy(update={"hyp_id": f"{self.node}:h-{self.n_hyp:03d}"}))
        self.science_dirty = True

    # ── 밖으로 ──
    def snapshot(self) -> w.Snapshot | None:
        return self._snap

    def outbox(self) -> list[w.Msg]:
        out, self._out = self._out, []
        return out

    # ── 도우미 ──
    def _bt_state(self, f: SensorFrame) -> bt.BtState:
        s = bt.BtState()
        s.t, s.pos, s.heading_deg, s.sigma, s.dose_cum_uSv = f.t, bt.BtXY(*f.pos), f.heading_deg, f.sigma, f.dose_cum_uSv
        s.link_mode, s.node = self.link.mode, bt.NODE[self.node]
        s.rover_pos = bt.BtXY(*self.rover_xy) if self.rover_xy else bt.BtXY(math.nan, math.nan)
        return s

    def _wire_state(self, f: SensorFrame) -> w.State:
        return w.State(t=f.t, node=self.node, pos=(round(f.pos[0], 1), round(f.pos[1], 1)), sigma=f.sigma, tau_dust=round(f.tau_dust, 3),
                       dose_rate=round(f.dose_rate, 2), spe=bool(f.spe if self.spe_alert is None else self.spe_alert),
                       sun_elev=round(f.sun_elev, 1), heading_deg=f.heading_deg % 360.0, dose_cum_uSv=round(f.dose_cum_uSv, 2),
                       sun_az=f.sun_az % 360.0, t_air_c=None if f.t_air_c is None else round(f.t_air_c, 1),
                       link_mode="LOCAL" if self.link.mode == bt.LINK_LOCAL else "FULL", rover_pos=self.rover_xy)

    def _refresh_views(self) -> None:
        """지도에 그릴 가설·흔적·관측 목록을 코어의 지도와 곁 표에서 만든다."""
        self._views = science_views(self.core, self.table, self.trace_max)

    def _channel(self, ch: bt.BtChannel) -> w.ChannelView:
        down = ch.state == bt.CHS_DOWN
        return w.ChannelView(state="DOWN" if down else "UP", rtt_ms=round(float(ch.rtt_ms), 1), loss=round(float(ch.loss), 3),
                             down_for_s=round(self.t - ch.down_since / 1000.0, 1) if down else None)

    def _build_snapshot(self, f: SensorFrame, state: w.State, nlt, nlt_warn: bool, back) -> w.Snapshot:
        own = bt.NODE[self.node]
        pending = sum(1 for e in self.table.by_id.values() if bt.NODE[e.node] == own and e.lts > self.acked.get(self.node, 0))
        tau_warn = self.cfg.dust_tau_warn > 0 and f.tau_dust > self.cfg.dust_tau_warn
        pos_warn = f.sigma > self.sigma_warn
        notices = [tp.render_notice(k) for k, on in (("options_paused", self.options_paused), ("nlt_warn", nlt_warn), ("tau_warn", tau_warn), ("pos_warn", pos_warn)) if on]
        return w.Snapshot(
            state=state, lmst=f.lmst, sigma_m=f.sigma, pos_warn=pos_warn, traces=self._views["traces"], obs=self._views["obs"],
            channels={"uhf": self._channel(self.link.uhf), "wifi": self._channel(self.link.wifi)},
            plan=self.plan, route=self._route, return_rover=back, nlt=nlt, nlt_warn=nlt_warn, gauge=self._gauge,
            dp=self.dp, dp_source=self.dp_source, dp_age_s=round(self.t - self.dp_rx_t, 1) if self.dp else 0.0,
            options_paused=self.options_paused, pending_events=pending, dp_text=tp.dp_text(self.dp) if self.dp else [],
            hyp_draft=self.hyp_draft, hyps=self._views["hyps"], log_count=len(self.table.by_id), log_persisted=False,
            missing_layers=self.meta.get("missing_layers", []), notices=notices, tau_warn=tau_warn, shadow_bin=int(f.shadow_bin))


def science_views(core: bt.Core, table: cv.EventTable, trace_max: int) -> dict:
    """코어의 지도 상태 + 곁 표 → 화면이 그릴 목록(가설, 주의 흔적, 관측). 기기와 로버가 같이 쓴다."""
    view = core.science_view()
    hyp_events = {e.payload.hyp_id: e for e in table.by_id.values() if e.type == "hyp"}
    hyps = []
    for h in view["hyps"]:
        ev = hyp_events.get(cv.hyp_id(h["node"], h["seq"]))
        if ev is None:
            continue
        hyps.append(w.HypView(hyp_id=ev.payload.hyp_id, rule=ev.payload.rule, xy=ev.geom.xy, direction_deg=ev.payload.direction_deg,
                              extent_m=ev.payload.extent_m, conf_chosen=round(h["conf_chosen"], 3), conf_now=round(min(1.0, max(0.0, h["conf_now"])), 3), n_used=h["n_used"],
                              conf_chosen_name=tp.confidence_name(h["conf_chosen"]), conf_now_name=tp.confidence_name(h["conf_now"])))
    traces = [w.TraceMark(xy=(round(t["xy"][0], 1), round(t["xy"][1], 1)), kind="photo" if t["kind"] == bt.TRACE_PHOTO else "mention",
                          fade=round(min(1.0, max(0.0, t["fade"])), 2), kept=t["kept"]) for t in view["traces"] if t["alive"]][-trace_max:]
    obs = [w.ObsMark(id=e.id, xy=e.geom.xy, found=e.payload.kind == "found", confirmed=e.payload.confirmed, note=e.payload.note, node=e.node, ts=round(e.ts, 1))
           for e in table.ordered() if e.type == "obs"]
    return {"hyps": hyps, "traces": traces, "obs": obs}
