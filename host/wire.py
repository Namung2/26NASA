"""와이어 형식 — 노드 사이를 오가고, 저장되고, 화면으로 가는 JSON의 정본 (docs/spec/S2 §1~§8).

두 겹 가운데 "글자가 있는 쪽"이다. 다른 한 겹은 코어의 숫자 구조체(core/include/btcore.h)이고 host/convert.py가 둘을 바꾼다.

    ┌ 이 파일이 계약이다 ─────────────────────────────────────────────────────────────┐
    │ 필드 이름·자료형을 바꾸면 기기·로버·화면이 전부 영향을 받는다.                    │
    │ 화면의 타입(screen/src/types.ts)은 이 파일에서 만든다 — scripts/gen_ts_types.py   │
    │ 모든 모델은 정의하지 않은 필드를 거부한다(extra="forbid").                        │
    └──────────────────────────────────────────────────────────────────────────────────┘

금지 규칙(R-52): Option과 DecisionPoint에는 추천·기본값·점수·순위를 뜻하는 필드가 없고, 넣을 수도 없다.
도구는 선택지를 나란히 보일 뿐 고르지 않는다. tests/test_v5_no_bias.py가 필드 이름을 검사한다.

단위: 길이 m, 좌표 (동쪽 x, 북쪽 y) — 원점은 활동 구역의 북서쪽 모서리, 시각은 EVA 경과 초, 각도는 °(0 = 북, 시계 방향).
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class M(BaseModel):
    """모든 모델의 기반: 만든 뒤 고칠 수 없고, 정의하지 않은 필드는 받지 않는다."""
    model_config = ConfigDict(frozen=True, extra="forbid")


NodeId = Annotated[str, Field(pattern=r"^(suit-[A-Z]|rover|ground|sim)$")]
Cell = tuple[int, int]            # (row, col), row 0 = 북쪽. 항상 칸 크기와 함께 쓴다
XY = tuple[float, float]          # (x 동쪽 m, y 북쪽 m) — 좌표의 정본
Deg = Annotated[float, Field(ge=0, lt=360)]
Unit01 = Annotated[float, Field(ge=0, le=1)]
Rule = Literal["strata_continuity", "proximity", "unit_boundary", "erosion_exposure"]


# ── §1 도형 ───────────────────────────────────────────────────────────────
class GeomPoint(M):
    kind: Literal["point"] = "point"
    xy: XY


class GeomCell(M):
    kind: Literal["cell"] = "cell"
    res_m: float
    cell: Cell


class GeomPolyline(M):
    kind: Literal["polyline"] = "polyline"
    xy: list[XY]


Geom = Annotated[GeomPoint | GeomCell | GeomPolyline, Field(discriminator="kind")]


# ── §4 경로의 정지점 (이벤트가 쓰므로 앞에 둔다) ──────────────────────────
class Stop(M):
    xy: XY
    poi_id: str | None = None
    dwell_min: float = 0.0
    purpose: Literal["poi", "hyp_target", "landmark", "rover"]


# ── §2 이벤트 — 현장에서 저장·동기화되는 유일한 것 ────────────────────────
class EventBase(M):
    id: str                          # f"{node}:{lts}" — 전역에서 하나뿐, 중복 제거의 열쇠
    ts: float                        # EVA 경과 초. 순서를 정하는 데는 쓰지 않는다
    lts: int                         # 논리 시계(lamport). 순서는 (lts, node)로 정한다
    node: NodeId
    geom: Geom                       # LIVE 이벤트는 point(미터)를 쓴다 — 노드마다 격자가 달라도 같은 자리가 된다
    approved: bool = True            # hyp에서만 뜻이 있다. False면 지도에 반영하지 않는다


class HypPayload(M):
    hyp_id: str                      # "suit-A:h-012" — 번호 앞에 만든 노드
    rule: Rule
    direction_deg: Deg               # 0 = 북, 시계 방향. proximity는 쓰지 않는다
    extent_m: Annotated[float, Field(gt=0, le=5000)]
    confidence: Unit01               # 메뉴에서 고른 값. 이벤트는 고치지 않는다 — 지금 확신은 로그를 다시 적용할 때 계산한다
    origin: Literal["menu", "script", "suggested"] = "menu"
    anchor_event: str | None = None  # 근거가 된 관측 이벤트의 id
    supersedes: str | None = None    # 거두는(철회하는) 가설의 hyp_id


class HypDraft(M):
    """확인 창에 뜨는, 메뉴에서 고르는 중인 가설. 빈칸이 남아 있으면 승인할 수 없다 — 시스템은 빈칸을 채우지 않는다."""
    rule: Rule | None = None
    direction_idx: int | None = None
    extent_idx: int | None = None
    confidence_idx: int | None = None
    missing: list[str] = []
    readback: str = ""               # 되읽기 문장 (host/templates.py가 만든다)
    withdraw_hyp_id: str | None = None   # 철회 확인 창일 때 거둘 가설


class ObsPayload(M):
    obs_id: str
    kind: Literal["found", "not_found"]
    signal: str = ""                 # 자유 꼬리표
    confirmed: bool = False          # 다시 확인했는가 → 관측을 얼마나 믿을지
    note: str = ""                   # 자유 메모. 글자 그대로 저장하고 보인다. 시스템은 해석하지 않는다


class ChoicePayload(M):
    dp_id: str
    option_id: str
    options_shown: list[str]
    sort_key: str                    # 고를 때 화면의 정렬 기준
    was_hypothesis_option: bool
    hyp_ids: list[str] = []          # 고른 옵션에 기여한 가설. 그 가설을 거둘 때 "고르기 직전의 계획"을 찾는 데 쓴다
    option_digest: str
    latency_s: float                 # 카드가 뜬 뒤 고르기까지
    stops: list[Stop]                # 고른 옵션의 정지점. 그 결정 지점을 본 적 없는 노드도 이 기록만으로 계획을 바꿀 수 있다


class TracePayload(M):
    kind: Literal["photo", "mention"]


class MarkPayload(M):
    what: Literal["poi", "blocked"]
    name: str = ""
    radius_m: float = 0.0
    photo: str | None = None
    note: str = ""


class HypEvent(EventBase):
    type: Literal["hyp"] = "hyp"
    payload: HypPayload


class ObsEvent(EventBase):
    type: Literal["obs"] = "obs"
    payload: ObsPayload


class ChoiceEvent(EventBase):
    type: Literal["choice"] = "choice"
    payload: ChoicePayload


class TraceEvent(EventBase):
    type: Literal["trace"] = "trace"
    payload: TracePayload


class MarkEvent(EventBase):
    type: Literal["mark"] = "mark"
    payload: MarkPayload


Event = Annotated[HypEvent | ObsEvent | ChoiceEvent | TraceEvent | MarkEvent, Field(discriminator="type")]


# ── §3 상태 — 저장하지 않고 매 틱 다시 만든다 ────────────────────────────
class State(M):
    t: float
    node: NodeId
    pos: XY                          # 주어진 입력. 이 도구는 위치를 추정하지 않는다
    sigma: float                     # 오차 반경 (m) — 주어진 입력
    tau_dust: Annotated[float, Field(ge=0)]   # 먼지 광학 두께. 번들의 기상 리플레이면 9 µm 적외선 값이다
    dose_rate: Annotated[float, Field(ge=0)]  # µSv/h
    spe: bool
    sun_elev: float
    heading_deg: Deg
    dose_cum_uSv: float
    sun_az: Deg
    t_air_c: float | None = None
    link_mode: Literal["FULL", "LOCAL"]
    rover_pos: XY | None = None


# ── §5 결정 지점과 옵션 ───────────────────────────────────────────────────
Grade = Literal["LOW", "MED", "HIGH"]
SortKey = Literal["unsorted", "time_min", "max_slope_deg", "dose_uSv", "value", "info_gain", "nlt_margin_min"]


class Reason(M):
    layer: str
    cell: Cell | None = None
    res_m: float | None = None
    value: float
    unit: str = ""
    source_id: str = ""              # 번들 메타의 레이어 이름 → 출처 표시


class Option(M):
    id: str                          # "A" | "B" | "C" — 만들어진 순서의 이름표. 순위가 아니다
    kind: Literal["route", "stay", "return"]
    label_key: str                   # continue_plan | hyp_target | restore_plan | drop_last | stay | return_rover
    path: list[XY]                   # 꺾이는 점. stay면 한 점
    stops: list[Stop]
    time_min: float
    max_slope_deg: float
    dose_uSv: float
    value_mean: float
    value_var: float
    info_gain: float                 # value_mean과 더하지 않는다
    explore_count: int               # 경로가 지나는 살아 있는 주의 흔적의 수
    comm_loss_min: float             # 로버와 링크가 안 되는 시간
    from_hypothesis: bool
    reasons: list[Reason]
    value_lo: float                  # 가설이 전부 틀렸을 때 (가설 옵션이 아니면 value_mean과 같다)
    value_hi: float                  # 가설이 전부 맞았을 때
    value_grade: Grade
    hyp_ids: list[str]
    prior_only: bool                 # 바탕 지도만으로 정해진 값 (현장 관측·가설의 기여가 없다)
    nlt_margin_min: float            # "출발까지 N분". 음수는 late인 귀환 옵션에서만
    late: bool = False
    over_limit: list[str] = []       # 안전 임계를 넘은 항목 이름. 프로그램이 판정해 싣고 화면은 그리기만 한다
    nlt_binding: Literal["sunset", "eva_max"]
    return_time_min: float
    profile: list[tuple[float, float]] = []   # 고도 단면 (누적 거리 m, 고도 m). 로버 콘솔에만 채운다
    digest: str = ""                 # 코어 bt_option_digest의 16진 문자열


class DecisionPoint(M):
    dp_id: str                       # "rover:dp-07"
    trigger: Literal["fork", "env", "link_lost", "safety", "user_request"]
    cause: str = ""                  # "route" | 이벤트 id | "spe" | "nlt" | "sunset" | "return" | "dust" | "shadow"
    cause_kind: Literal["route", "obs", "hyp", "other"] = "other"
    ts: float
    node: NodeId
    sort_key: SortKey = "unsorted"
    options: Annotated[list[Option], Field(max_length=3)]
    notices: list[str] = []
    forced: bool = False
    inputs_digest: str


# ── §7 채널 메시지 ────────────────────────────────────────────────────────
class Msg(M):
    ch: Literal["uhf", "wifi"]
    type: str
    seq: int
    node: NodeId
    t_send: float


class Hb(Msg):
    type: Literal["hb"] = "hb"
    bundle_id: str


class HbAck(Msg):
    type: Literal["hb_ack"] = "hb_ack"
    ack_seq: int


class Telemetry(Msg):
    type: Literal["telemetry"] = "telemetry"
    state: State


class Alert(Msg):
    type: Literal["alert"] = "alert"
    kind: Literal["spe_on", "spe_off"]
    dose_rate: float


class SyncUp(Msg):
    type: Literal["sync_up"] = "sync_up"
    events: list[Event]
    have_lts: dict[str, int]


class SyncDown(Msg):
    type: Literal["sync_down"] = "sync_down"
    events: list[Event]
    have_lts: dict[str, int]


class DpMsg(Msg):
    type: Literal["dp"] = "dp"
    dp: DecisionPoint


class ReturnPathMsg(Msg):
    type: Literal["return_path"] = "return_path"
    path: list[XY]
    time_s: float
    blocked_lts: int


class ReturnFieldMsg(Msg):
    """귀환 지도의 머리. 본문(걷는 시간 f32, 다음 방향 u8)은 같은 소켓의 바이너리 프레임으로 따라간다."""
    type: Literal["return_field"] = "return_field"
    rover_id: str
    rover_xy: XY
    res_m: float
    shape: tuple[int, int]


class PhotoSync(Msg):
    type: Literal["photo_sync"] = "photo_sync"
    event_id: str
    size: int


# ── §7.1 화면 ↔ 프로그램 ──────────────────────────────────────────────────
class ChannelView(M):
    state: Literal["UP", "DOWN"]
    rtt_ms: float
    loss: float
    down_for_s: float | None


class NltView(M):
    t_depart: float
    slack_min: float
    binding: Literal["sunset", "eva_max"]
    degraded: bool
    return_dist_m: float
    return_time_min: float


class GaugeView(M):
    bearing_deg: Deg
    distance_m: float
    time_min: float


class HypView(M):
    hyp_id: str
    rule: Rule
    xy: XY
    direction_deg: float
    extent_m: float
    conf_chosen: Unit01
    conf_now: Unit01
    n_used: int
    conf_chosen_name: str = ""       # "가능성 낮음" | "반반" | "가능성 높음" — 프로그램이 구간에 대어 붙인 이름. 화면은 그대로 쓴다
    conf_now_name: str = ""


class TraceMark(M):
    xy: XY
    kind: Literal["photo", "mention"]
    fade: Unit01
    kept: bool


class ObsMark(M):
    """지도에 찍는 관측 한 점(자유 메모 포함)."""
    id: str
    xy: XY
    found: bool
    confirmed: bool
    note: str = ""
    node: NodeId
    ts: float = 0.0                  # EVA 경과 초


class Snapshot(M):
    """기기 프로그램 → 현장 화면. 틱마다 전체를 보낸다. 화면이 계산해 채우는 필드는 없다."""
    state: State
    lmst: str = ""                   # 지방 평균 태양시 "hh:mm"
    sigma_m: float
    pos_warn: bool
    traces: list[TraceMark] = []
    obs: list[ObsMark] = []
    channels: dict[str, ChannelView]
    plan: list[Stop]
    route: list[XY]
    return_rover: list[XY]
    visited: list[Stop] = []         # 다녀온 지점: 계획에 있다가 도착해서 빠진 정지점을 도착한 순서로(로버는 뺀다). 도착 = 그 지점의 도착 반경(menu.arrive_radius_m) 안에 들어옴
    track: list[XY] = []             # 걸어온 길: 지나온 위치를 오래된 것부터. 기기 프로그램이 받은 위치를 탐색 격자 한 칸 넘게 움직일 때마다 한 점씩 쌓는다
    nlt: NltView | None
    nlt_warn: bool
    gauge: GaugeView | None
    dp: DecisionPoint | None
    dp_source: Literal["rover", "local", "cache"]
    dp_age_s: float
    options_paused: bool = False
    pending_events: int = 0
    dp_text: list[str]
    hyp_draft: HypDraft | None
    hyps: list[HypView] = []
    log_count: int
    log_persisted: bool
    missing_layers: list[str]
    notices: list[str] = []          # 화면 위쪽에 띄울 알림 문장(템플릿이 만든 것)
    tau_warn: bool = False           # 먼지가 경고 임계를 넘었다 — 프로그램이 판정해 싣는다
    shadow_bin: int = 0              # 지금의 그림자 시간 구간 번호 — 화면이 그림자 타일(shadow_<n>)을 고르는 데 쓴다


class CrewStatus(M):
    node: NodeId
    state: State | None
    last_rx_s: float
    nlt: NltView | None
    plan: list[Stop]
    route: list[XY]


class ConsoleSnapshot(M):
    """로버 프로그램 → 계획 화면(로버 콘솔)."""
    t: float
    lmst: str = ""
    rover_pos: XY | None
    candidates: list[Option]         # 방금 낸 결정 지점의 후보 전체. 여기서만 profile을 채운다
    shown_ids: list[str] = []        # 그 가운데 현장 화면에 카드로 간 것의 digest
    hyp_suggestions: list[HypDraft] = []
    crew: CrewStatus
    alerts: list[str]
    recent_decisions: list[DecisionPoint]
    recent_events: list[Event]
    hyps: list[HypView] = []
    obs: list[ObsMark] = []
    traces: list[TraceMark] = []
    missing_layers: list[str]
    link_up: bool = True
    shadow_bin: int = 0
    hyp_draft: HypDraft | None = None    # 콘솔의 가설 양식에서 고른 것(확인 창에 되읽기 문장과 함께 뜬다)
    science_rev: int = 0             # 과학 가치 지도가 다시 계산될 때마다 1씩 오른다. 화면은 이 값이 바뀔 때만 /console/science.png를 다시 받는다


class CmdChoose(M):
    kind: Literal["choose"] = "choose"
    dp_id: str
    option_id: str
    sort_key: SortKey = "unsorted"


class CmdObs(M):
    kind: Literal["obs"] = "obs"
    found: bool
    confirmed: bool = False
    note: str = ""


class CmdHyp(M):
    kind: Literal["hyp"] = "hyp"
    rule: Rule
    direction_idx: int               # 0~7 (8방위, 0 = 북, 시계 방향)
    extent_idx: int                  # 0~2
    confidence_idx: int              # 0~2 (가능성 낮음 / 반반 / 가능성 높음)


class CmdHypReply(M):
    kind: Literal["hyp_reply"] = "hyp_reply"
    reply: Literal["approve", "reject", "edit"]


class CmdHypWithdraw(M):
    kind: Literal["hyp_withdraw"] = "hyp_withdraw"
    hyp_id: str


class CmdReturn(M):
    kind: Literal["return"] = "return"


class CmdPhoto(M):
    kind: Literal["photo"] = "photo"


class CmdMark(M):
    kind: Literal["mark"] = "mark"
    what: Literal["poi", "blocked"]
    name: str = ""
    radius_idx: int = 0
    note: str = ""


Command = Annotated[CmdChoose | CmdObs | CmdHyp | CmdHypReply | CmdHypWithdraw | CmdReturn | CmdPhoto | CmdMark, Field(discriminator="kind")]


class ScreenCmd(M):
    """화면 → 프로그램. 화면은 응답을 기다리지 않는다 — 결과는 다음 스냅샷에 나타난다."""
    type: Literal["command"] = "command"
    cmd: Command


class ConsoleCmd(M):
    """로버 콘솔 → 로버 프로그램. 로버에 탄 사람이 메모를 읽고 가설을 넣는다(R-29). 기준점은 고른 관측(anchor_event)의 위치다."""
    type: Literal["console_command"] = "console_command"
    cmd: Annotated[CmdHyp | CmdHypReply, Field(discriminator="kind")]
    anchor_event: str | None = None  # 가설의 기준이 되는 관측 이벤트의 id. hyp 명령에는 꼭 있어야 한다


# ── §8 정규 JSON ──────────────────────────────────────────────────────────
def canonical_json(obj) -> bytes:
    """비교용 정규 JSON: 키 정렬, 실수는 소수 6자리, 공백 없음. 시뮬 로그처럼 호스트 쪽 기록을 견줄 때만 쓴다."""
    def norm(v):
        if isinstance(v, BaseModel):
            return norm(v.model_dump())
        if isinstance(v, float):
            return round(v, 6)
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    return json.dumps(norm(obj), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()
