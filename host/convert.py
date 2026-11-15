"""코어의 숫자 구조체 ↔ 와이어 JSON 변환과, 글자를 보관하는 곁 표(side table).

코어는 숫자만 다룬다. 자유 메모, 지점 이름, 선택 때의 카드 목록 같은 글자·목록은 코어에 들어가지 않는다.
그래서 호스트가 이벤트마다 와이어 모델(글자 포함)을 통째로 들고 있다 — EventTable. 열쇠는 이벤트 id "노드:lts"다.

    새 이벤트(이 노드가 만든 것):  append_event()  →  코어에 넣고(lts를 받는다) → 와이어 이벤트를 만들어 표에 둔다
    받은 이벤트(다른 노드의 것):  merge_events()  →  와이어를 숫자로 바꿔 코어에 넣고 → 새로 들어온 것만 표에 둔다
    보낼 이벤트:                  events_since()  →  코어에 "상대가 아직 안 가진 것"을 묻고 → 표에서 와이어 이벤트를 꺼낸다

번호 약속 (코어의 가설 열쇠와 맞춘다 — btcore.h의 BT_HYP_KEY)
    hyp_id "suit-A:h-012"  ↔  (노드 번호, 가설 번호 12)      obs_id "suit-A:o-003"  ↔  관측 번호 3
    dp_id  "rover:dp-07"   ↔  (노드 번호, 결정 지점 번호 7)
"""
from __future__ import annotations

from . import btcore as bt
from . import wire as w


class EventTable:
    """이벤트 id → 와이어 이벤트. 글자를 여기서 찾는다."""

    def __init__(self) -> None:
        self.by_id: dict[str, w.EventBase] = {}

    def put(self, ev) -> None:
        self.by_id[ev.id] = ev

    def get(self, node: int, lts: int):
        return self.by_id.get(f"{bt.NODE_NAME.get(node, '?')}:{lts}")

    def ordered(self) -> list:
        """(lts, 노드) 순 — 코어의 로그와 같은 순서."""
        return sorted(self.by_id.values(), key=lambda e: (e.lts, bt.NODE[e.node]))


def _split(ident: str) -> tuple[int, int]:
    """"suit-A:h-012" → (노드 번호, 12). 번호가 없으면 0."""
    node, _, tail = ident.partition(":")
    digits = "".join(ch for ch in tail if ch.isdigit())
    return bt.NODE[node], int(digits) if digits else 0


def hyp_id(node: int, seq: int) -> str:
    return f"{bt.NODE_NAME[node]}:h-{seq:03d}"


def hyp_id_from_key(key: int) -> str:
    return hyp_id(*bt.hyp_key_split(key))


def to_bt_event(e) -> bt.BtEvent:
    """와이어 이벤트 → 코어 이벤트(숫자만). 글자는 버려진다 — 부른 쪽이 EventTable에 따로 둔다."""
    b = bt.BtEvent()
    b.lts, b.node, b.ts = int(e.lts), bt.NODE[e.node], float(e.ts)
    b.x, b.y = float(e.geom.xy[0]), float(e.geom.xy[1])
    p = e.payload
    if e.type == "hyp":
        b.type = bt.EV_HYP
        b.flags = bt.EVF_APPROVED if e.approved else 0
        b.rule, b.a, b.b, b.c = bt.RULES.index(p.rule), p.direction_deg, p.extent_m, p.confidence
        b.seq = _split(p.hyp_id)[1]
        if p.supersedes:
            b.aux = bt.hyp_key(*_split(p.supersedes))
        if p.anchor_event:
            b.ref_node, b.ref_lts = _split(p.anchor_event)
    elif e.type == "obs":
        b.type = bt.EV_OBS
        b.flags = (bt.EVF_FOUND if p.kind == "found" else 0) | (bt.EVF_CONFIRMED if p.confirmed else 0)
        b.seq = _split(p.obs_id)[1]
    elif e.type == "choice":
        b.type = bt.EV_CHOICE
        b.kind = "ABC".find(p.option_id) if p.option_id in ("A", "B", "C") else 0
        b.flags = bt.EVF_WAS_HYP_OPTION if p.was_hypothesis_option else 0
        b.a = p.latency_s
        b.ref_node, b.seq = _split(p.dp_id)
        b.aux = int(p.option_digest[-8:], 16) if p.option_digest else 0
    elif e.type == "trace":
        b.type, b.kind = bt.EV_TRACE, (bt.TRACE_PHOTO if p.kind == "photo" else bt.TRACE_MENTION)
    elif e.type == "mark":
        b.type, b.kind, b.a = bt.EV_MARK, (bt.MARK_BLOCKED if p.what == "blocked" else bt.MARK_POI), p.radius_m
    return b


_EVENT_CLASS = {"hyp": w.HypEvent, "obs": w.ObsEvent, "choice": w.ChoiceEvent, "trace": w.TraceEvent, "mark": w.MarkEvent}


def append_event(core: bt.Core, table: EventTable, node: str, kind: str, xy, ts: float, payload, approved: bool = True):
    """이 노드가 만든 이벤트를 코어 로그에 넣고 와이어 이벤트를 돌려준다. 순서 번호(lts)는 코어가 매긴다."""
    draft = _EVENT_CLASS[kind](id=f"{node}:0", ts=ts, lts=1, node=node, geom=w.GeomPoint(xy=(float(xy[0]), float(xy[1]))),
                               approved=approved, payload=payload)
    b = core.log_append(to_bt_event(draft))
    ev = draft.model_copy(update={"id": f"{node}:{b.lts}", "lts": int(b.lts)})
    table.put(ev)
    return ev


def merge_events(core: bt.Core, table: EventTable, events: list) -> list:
    """다른 노드에서 온 이벤트를 합친다. 새로 들어온 것만 돌려준다(이미 있던 것은 조용히 지나간다 — 여러 번 받아도 같다)."""
    fresh = [e for e in events if e.id not in table.by_id]
    if fresh:
        core.log_merge([to_bt_event(e) for e in fresh])
        for e in fresh:
            table.put(e)
    return fresh


def have_dict(core: bt.Core) -> dict[str, int]:
    """코어의 "어디까지 갖고 있나"를 와이어 모양(노드 이름 → 최대 lts)으로."""
    return {bt.NODE_NAME[i]: v for i, v in enumerate(core.log_have()) if v and i in bt.NODE_NAME}


def have_list(have: dict[str, int]) -> list[int]:
    out = [0] * bt.MAX_NODES
    for name, v in have.items():
        if name in bt.NODE:
            out[bt.NODE[name]] = int(v)
    return out


def events_since(core: bt.Core, table: EventTable, have: dict[str, int], cap: int) -> list:
    """상대가 아직 안 가진 이벤트를 cap건까지, (lts, 노드) 순으로."""
    evs, _more = core.log_since(have_list(have), cap)
    out = [table.get(b.node, b.lts) for b in evs]
    return [e for e in out if e is not None]


def to_bt_stop(s: w.Stop, poi_index: dict[str, int]) -> bt.BtStop:
    b = bt.BtStop()
    b.xy = bt.BtXY(float(s.xy[0]), float(s.xy[1]))
    b.dwell_min, b.purpose = float(s.dwell_min), bt.STOP_PURPOSES.index(s.purpose)
    b.poi = poi_index.get(s.poi_id, bt.POI_NONE) if s.poi_id else bt.POI_NONE
    b.profile = bt.PROFILES.index(s.profile)
    return b


def from_bt_stop(b: bt.BtStop, poi_ids: list[str]) -> w.Stop:
    pid = poi_ids[b.poi - 1] if 1 <= b.poi <= len(poi_ids) else None
    return w.Stop(xy=(b.xy.x, b.xy.y), poi_id=pid, dwell_min=round(float(b.dwell_min), 2), purpose=bt.STOP_PURPOSES[b.purpose],
                  profile=bt.PROFILES[b.profile] if b.profile < len(bt.PROFILES) else "balanced")


def _thin(pts: list, max_pts: int) -> list:
    """점이 max_pts보다 많으면 고르게 솎는다(처음과 끝은 남긴다). UHF 메시지에 실을 때 쓴다."""
    if max_pts <= 0 or len(pts) <= max_pts:
        return pts
    idx = sorted({round(i * (len(pts) - 1) / (max_pts - 1)) for i in range(max_pts)})
    return [pts[i] for i in idx]


def option_from_bt(core: bt.Core, o: bt.BtOption, path_xy, poi_ids: list[str], max_pts: int = 0) -> w.Option:
    """코어의 옵션 → 와이어 옵션. path_xy는 그 옵션의 꺾이는 점(없으면 빈 목록)."""
    over = [name for bit, name in ((bt.OVER_MAX_SLOPE, "max_slope_deg"), (bt.OVER_DOSE, "dose_uSv")) if o.over_limit & bit]
    reasons = []
    layer_names = {v: k for k, v in bt.LAYER.items()}
    for i in range(o.n_reasons):
        r = o.reasons[i]
        reasons.append(w.Reason(layer=layer_names.get(r.layer, "?"), cell=None if r.cell.row < 0 else (r.cell.row, r.cell.col),
                                res_m=float(r.res_m), value=round(float(r.value), 3), source_id=layer_names.get(r.layer, "")))
    pts = _thin([(round(float(x), 1), round(float(y), 1)) for x, y in path_xy], max_pts)
    return w.Option(
        id="ABC"[o.label] if o.label < 3 else "", kind=bt.OPT_KINDS[o.kind], label_key=bt.LABEL_KEYS[o.label_key], path=pts,
        stops=[from_bt_stop(o.stops[i], poi_ids) for i in range(o.n_stops)],
        time_min=float(o.time_min), max_slope_deg=float(o.max_slope_deg), dose_uSv=round(float(o.dose_uSv), 2),
        value_mean=round(float(o.value_mean), 2), value_var=round(float(o.value_var), 3), info_gain=round(float(o.info_gain), 2),
        explore_count=int(o.explore_count), comm_loss_min=float(o.comm_loss_min),
        from_hypothesis=bool(o.flags & bt.OPTF_FROM_HYPOTHESIS), reasons=reasons,
        value_lo=round(float(o.value_lo), 2), value_hi=round(float(o.value_hi), 2), value_grade=bt.GRADES[o.value_grade],
        hyp_ids=[hyp_id_from_key(k) for k in o.hyp_seq if k], prior_only=bool(o.flags & bt.OPTF_PRIOR_ONLY),
        nlt_margin_min=float(o.nlt_margin_min), late=bool(o.flags & bt.OPTF_LATE), over_limit=over,
        nlt_binding=bt.BINDINGS[o.nlt_binding], return_time_min=float(o.return_time_min), digest=f"{o.digest:016x}")


def decision_from_bt(core: bt.Core, d: bt.BtDecision, poi_ids: list[str], max_pts: int = 0) -> w.DecisionPoint:
    """코어의 결정 지점 → 와이어. 옵션의 경로는 꺾이는 점으로 꺼낸다. 다음 bt_decide를 부르기 전에 불러야 한다."""
    opts = []
    for i in range(d.n_options):
        o = d.options[i]
        via = [(o.stops[k].xy.x, o.stops[k].xy.y) for k in range(max(0, o.n_stops - 1))]      # 도중에 들르는 지점에서 선을 끊는다
        opts.append(option_from_bt(core, o, core.path_polyline(core.decision_path(d, i), via), poi_ids, max_pts))
    cause_name = bt.CAUSES[d.cause_kind]
    by_event = cause_name in ("obs", "hyp")
    notices = [name for bit, name in ((bt.NOTICE_HYP_UNREACHABLE, "hyp_unreachable_within_nlt"), (bt.NOTICE_NO_FEASIBLE_RETURN, "no_feasible_return"),
                                     (bt.NOTICE_HYP_NO_EFFECT, "hyp_no_effect"), (bt.NOTICE_CUSTOM_UNREACHABLE, "custom_plan_unreachable")) if d.notices & bit]
    return w.DecisionPoint(
        dp_id=f"{bt.NODE_NAME[d.node]}:dp-{d.seq:02d}", trigger=bt.TRIGGERS[d.trigger],
        cause=f"{bt.NODE_NAME.get(d.cause_node, '?')}:{d.cause_lts}" if by_event else cause_name,
        cause_kind=cause_name if cause_name in ("route", "obs", "hyp") else "other",
        ts=float(d.ts), node=bt.NODE_NAME[d.node], options=opts, notices=notices, forced=bool(d.forced), inputs_digest=f"{d.inputs_digest:016x}")
