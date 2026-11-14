"""C++ 코어(btcore)의 Python 바인딩.

코어의 계약은 헤더 한 장이다: core/include/btcore.h. 이 파일은 그 헤더를 ctypes로 그대로 옮긴 것이다.

    ┌ 헤더를 고치면 여기도 같이 고친다 ────────────────────────────────────────────────┐
    │ 구조체의 필드 순서·자료형이 헤더와 한 칸이라도 다르면 값이 조용히 어긋난다.          │
    │ 그래서 load()가 시작할 때 버전(bt_abi_version)과 구조체 29종의 크기(bt_sizeof)를    │
    │ 전부 대조하고, 하나라도 다르면 AbiMismatch로 멈춘다.                               │
    └──────────────────────────────────────────────────────────────────────────────────┘

쓰는 법 (자세한 예는 scripts/check_bundle.py)
    from host import btcore, config, bundle
    b = bundle.load("data/bundles/jezero_west_v1", level="field")
    core = btcore.Core.create(config.load_config("config/tiers.yaml", "config/params.yaml", "device", b.meta))
    b.attach(core)                         # 번들 배열을 코어에 연결 (복사 없음)
    core.set_env(b.env_at(t_eva_s=0.0))    # 그림자 구간, 일몰 시각, 선량률 …
    core.costmap_build()
    path = core.plan((x0, y0), (x1, y1))

메모리 약속
    - 코어는 시작할 때 받은 메모리 한 덩어리(아레나)만 쓴다. Core 객체가 그 메모리를 들고 있다.
    - set_layer·set_field로 넘긴 numpy 배열은 코어가 복사하지 않고 포인터만 든다. Core 객체가 배열을 붙들고 있으니
      부른 쪽이 따로 보관할 필요는 없다. 단 넘긴 뒤에 그 배열의 내용을 바꾸면 안 된다.
    - 코어는 한 번에 한 호출만 받는다. 여러 스레드·태스크에서 부르려면 부르는 쪽이 줄을 세운다(잠금 하나).
"""
from __future__ import annotations

import ctypes as C
import os
import sys
from pathlib import Path

import numpy as np

ABI_VERSION = 3      # core/include/btcore.h의 BT_ABI_VERSION과 같아야 한다

# ── 용량 상수 (헤더의 BT_MAX_*) ──────────────────────────────────────────
MAX_OPTIONS, MAX_CANDIDATES, MAX_STOPS, MAX_REASONS, MAX_HYPS, MAX_NODES = 3, 8, 8, 4, 16, 8
MAX_EVENTS, MAX_PROFILES, MAX_EPS, MAX_CHANGED, MAX_TRIGGERS, OPTION_HYPS = 4096, 3, 4, 8, 4, 4
POI_NONE, DIR_NONE, U16_NODATA = 255, 255, 65535

# ── 상태 코드 ────────────────────────────────────────────────────────────
OK, PARTIAL = 0, 1
ERR_ARG, ERR_CAPACITY, ERR_UNREACHABLE, ERR_NOT_READY, ERR_ABI = -1, -2, -3, -4, -5
STATUS_NAME = {0: "OK", 1: "PARTIAL", -1: "ERR_ARG", -2: "ERR_CAPACITY", -3: "ERR_UNREACHABLE", -4: "ERR_NOT_READY", -5: "ERR_ABI"}

# ── 열거값 (헤더의 enum과 같은 번호) ─────────────────────────────────────
NODE = {"suit-A": 1, "rover": 3, "ground": 4, "sim": 5}
NODE_NAME = {v: k for k, v in NODE.items()}
EV_HYP, EV_OBS, EV_CHOICE, EV_TRACE, EV_MARK = range(5)
EVF_APPROVED, EVF_FOUND, EVF_CONFIRMED, EVF_WAS_HYP_OPTION = 1, 2, 4, 8
TRACE_PHOTO, TRACE_MENTION = 0, 1
MARK_POI, MARK_BLOCKED = 0, 1
RULES = ["strata_continuity", "proximity", "unit_boundary", "erosion_exposure"]
LINK_FULL, LINK_LOCAL = 0, 1
STOP_PURPOSES = ["poi", "hyp_target", "landmark", "rover"]
OPT_KINDS = ["route", "stay", "return"]
LABEL_KEYS = ["continue_plan", "hyp_target", "restore_plan", "drop_last", "stay", "return_rover"]
OPTF_FROM_HYPOTHESIS, OPTF_PRIOR_ONLY, OPTF_LATE = 1, 2, 4
OVER_MAX_SLOPE, OVER_DOSE = 1, 2
GRADES = ["LOW", "MED", "HIGH"]
BINDINGS = ["sunset", "eva_max"]
TRIGGERS = ["fork", "env", "link_lost", "safety", "user_request"]
TRIG_FORK, TRIG_ENV, TRIG_LINK_LOST, TRIG_SAFETY, TRIG_USER_REQUEST = range(5)
CAUSES = ["route", "obs", "hyp", "other", "spe", "nlt", "sunset", "return", "dust", "shadow", "link"]
NOTICE_HYP_UNREACHABLE, NOTICE_NO_FEASIBLE_RETURN = 1, 2
DT_F32, DT_U16, DT_U8, DT_BITS = range(4)
LAYER = {"slope": 0, "elev": 1, "roughness": 2, "shadow": 3, "los": 4, "mu0": 5, "var0": 6, "units": 7, "terrain_class": 8}
WALK_PLAN, WALK_RETURN = 0, 1
FIELD_ROVER_RETURN = 0
CH_UHF, CH_WIFI = 0, 1
NET_SENT, NET_ACK, NET_SEND_ERROR, NET_TICK = range(4)
OPTMODE_RECEIVE, OPTMODE_PARETO = 0, 1


def hyp_key(node: int, seq: int) -> int:
    """가설 열쇠: 만든 노드와 그 노드가 매긴 번호를 한 수로 묶은 것 (헤더의 BT_HYP_KEY). hyp_id "suit-A:h-012" ↔ hyp_key(1, 12)."""
    return ((node << 12) | (seq & 0x0FFF)) & 0xFFFF


def hyp_key_split(key: int) -> tuple[int, int]:
    return key >> 12, key & 0x0FFF


# ── 구조체 미러 (필드 순서는 헤더 그대로) ────────────────────────────────
u8, u16, u32, u64, i32, f32, f64 = C.c_uint8, C.c_uint16, C.c_uint32, C.c_uint64, C.c_int32, C.c_float, C.c_double


class BtXY(C.Structure):
    _fields_ = [("x", f64), ("y", f64)]


class BtCell(C.Structure):
    _fields_ = [("row", i32), ("col", i32)]


class BtRaster(C.Structure):
    _fields_ = [("data", C.c_void_p), ("h", u32), ("w", u32), ("res_m", f32), ("dtype", u8), ("planes", u8),
                ("scale", f32), ("offset", f32), ("origin", BtXY)]


class BtEvent(C.Structure):
    _fields_ = [("lts", u32), ("node", u8), ("type", u8), ("kind", u8), ("flags", u8), ("ts", f64), ("x", f64), ("y", f64),
                ("a", f32), ("b", f32), ("c", f32), ("d", f32), ("ref_lts", u32), ("ref_node", u8), ("rule", u8), ("seq", u16),
                ("aux", u32), ("_pad", u32)]


class BtEventRef(C.Structure):
    _fields_ = [("lts", u32), ("node", u8), ("_pad", u8 * 3)]


class BtState(C.Structure):
    _fields_ = [("t", f64), ("pos", BtXY), ("heading_deg", f64), ("sigma", f64), ("dose_cum_uSv", f64),
                ("link_mode", u8), ("node", u8), ("rover_pos", BtXY)]


class BtEnv(C.Structure):
    _fields_ = [("sun_elev_deg", f64), ("sun_az_deg", f64), ("t_sunset_s", f64), ("tau_dust", f64), ("dose_rate_uSv_h", f64),
                ("shadow_bin", u8), ("spe", u8), ("_pad", u8 * 6)]


class BtGridGeom(C.Structure):
    _fields_ = [("origin", BtXY), ("res_m", f32), ("h", u32), ("w", u32), ("_pad", u32)]


class BtProfile(C.Structure):
    _fields_ = [("w_s", f32), ("w_r", f32), ("w_sh", f32), ("w_rad", f32)]


class BtLinkCfg(C.Structure):
    _fields_ = [("timeout_ms", u32), ("n_down", u8), ("n_up", u8), ("_pad", u8 * 2), ("ewma_alpha", f32), ("loss_down", f32), ("rtt_down_ms", f32)]


class BtConfig(C.Structure):
    _fields_ = [
        ("cost_grid", BtGridGeom), ("science_grid", BtGridGeom),
        ("max_expansions", u32), ("node", u8), ("options_mode", u8), ("options_max", u8), ("options_min", u8),
        ("shadow_bins", u8), ("eps_n", u8), ("_pad", u8 * 2),
        ("grid_m", f32), ("coarse_first_grid_m", f32), ("replan_radius_m", f32), ("science_grid_m", f32), ("grade_bins", f32 * 2),
        ("profiles", BtProfile * MAX_PROFILES), ("rough_ref_m", f32), ("dose_ref", f32),
        ("v_plan_kmh", f32), ("v_return_kmh", f32), ("theta_max_deg", f32),
        ("eps", f32 * MAX_EPS), ("snap_max_m", f32), ("alt_overlap_max", f32), ("corridor_m", f32),
        ("l0_m", f32), ("aniso_ratio", f32), ("exposure_slope_ref_deg", f32), ("obs_noise", f32), ("unconfirmed_factor", f32), ("tau_s", f32),
        ("r_obs_m", f32), ("w_transit", f32), ("A_ref_m2", f32), ("r_plan", f32), ("touch_eps", f32), ("var_floor", f32),
        ("eps_fork", f32), ("cooldown_s", f32), ("stay_max_min", f32), ("stay_buffer_min", f32), ("hyp_snap_m", f32),
        ("prec_time_min", f32), ("prec_max_slope_deg", f32), ("prec_dose_uSv", f32), ("prec_value", f32), ("prec_value_var", f32),
        ("prec_info_gain", f32), ("prec_nlt_margin_min", f32), ("prec_comm_loss_min", f32),
        ("k_return", f32), ("nlt_warn_min", f32), ("nlt_force_min", f32), ("sunset_margin_min", f32), ("sunset_warn_min", f32),
        ("eva_max_h", f32), ("dose_warn_uSv", f32), ("dust_tau_warn", f32),
        ("uhf", BtLinkCfg), ("wifi", BtLinkCfg), ("lost_dp_s", f32), ("hb_hz", f32),
    ]


class BtStop(C.Structure):
    _fields_ = [("xy", BtXY), ("dwell_min", f32), ("purpose", u8), ("poi", u8)]


class BtReason(C.Structure):
    _fields_ = [("layer", u8), ("value", f32), ("cell", BtCell), ("res_m", f32)]


class BtPathMetrics(C.Structure):
    _fields_ = [("time_min", f32), ("max_slope_deg", f32), ("dose_uSv", f32), ("comm_loss_min", f32), ("length_m", f32)]


class BtBudget(C.Structure):
    _fields_ = [("time_s", f64), ("max_expansions", u32), ("eps_n", u8), ("eps", f32 * MAX_EPS), ("profile", u8)]


class BtPath(C.Structure):
    _fields_ = [("cells", C.POINTER(BtCell)), ("cap", u32), ("len", u32), ("res_m", f64), ("length_m", f64), ("cost", f64),
                ("eps_bound", f32), ("expansions", u32), ("complete", u8), ("snapped_m", f64)]


class BtGauge(C.Structure):
    _fields_ = [("bearing_deg", f32), ("distance_m", f32), ("time_min", f32)]


class BtPathValue(C.Structure):
    _fields_ = [("value_mean", f32), ("value_lo", f32), ("value_hi", f32), ("value_var", f32), ("info_gain", f32), ("peak", f32),
                ("explore_count", u16), ("prior_only", u8), ("_pad", u8), ("hyp_seq", u16 * OPTION_HYPS)]


class BtHypView(C.Structure):
    _fields_ = [("lts", u32), ("seq", u16), ("node", u8), ("n_used", u8), ("conf_chosen", f32), ("conf_now", f32)]


class BtTracePt(C.Structure):
    _fields_ = [("xy", BtXY), ("ts", f64), ("lts", u32), ("fade", f32), ("node", u8), ("kind", u8), ("kept", u8), ("alive", u8)]


class BtScienceView(C.Structure):
    _fields_ = [("mu_base", BtRaster), ("var", BtRaster), ("live_touched", BtRaster),
                ("add_expected", BtRaster), ("add_full", BtRaster), ("traces", C.POINTER(BtTracePt)),
                ("n_traces", u32), ("n_hyps", u32), ("hyps", BtHypView * MAX_HYPS)]


class BtOption(C.Structure):
    _fields_ = [
        ("label", u8), ("kind", u8), ("label_key", u8), ("flags", u8), ("over_limit", u8),
        ("n_stops", u8), ("n_reasons", u8), ("value_grade", u8), ("nlt_binding", u8),
        ("stops", BtStop * MAX_STOPS), ("path_off", u32), ("path_len", u32),
        ("time_min", f32), ("max_slope_deg", f32), ("dose_uSv", f32),
        ("value_mean", f32), ("value_var", f32), ("value_lo", f32), ("value_hi", f32), ("info_gain", f32), ("explore_count", u16),
        ("comm_loss_min", f32), ("nlt_margin_min", f32), ("return_time_min", f32),
        ("hyp_seq", u16 * OPTION_HYPS), ("reasons", BtReason * MAX_REASONS), ("digest", u64),
    ]


class BtDecision(C.Structure):
    _fields_ = [("seq", u32), ("trigger", u8), ("cause_kind", u8), ("forced", u8), ("n_options", u8),
                ("cause_lts", u32), ("cause_node", u8), ("node", u8), ("notices", u16), ("ts", f64),
                ("options", BtOption * MAX_OPTIONS), ("inputs_digest", u64), ("digest", u64)]


class BtTrigger(C.Structure):
    _fields_ = [("kind", u8), ("forced", u8), ("cause_kind", u8), ("_pad", u8), ("cause_lts", u32), ("cause_node", u8)]


class BtTriggerIn(C.Structure):
    _fields_ = [("changed", BtEventRef * MAX_CHANGED), ("n_changed", u32), ("safety", BtTrigger * MAX_TRIGGERS), ("n_safety", u32),
                ("link_lost", u8), ("user_request", u8), ("has_next_stop", u8), ("_pad", u8), ("next_stop", BtXY)]


class BtNlt(C.Structure):
    _fields_ = [("t_depart", f64), ("slack_min", f32), ("binding", u8), ("degraded", u8)]


class BtChannel(C.Structure):
    _fields_ = [("state", u8), ("rtt_ms", f32), ("loss", f32), ("down_since", f64), ("miss_run", u8), ("ack_run", u8),
                ("pending", u8), ("pending_seq", u32), ("pending_t_ms", f64)]


class BtLink(C.Structure):
    _fields_ = [("uhf", BtChannel), ("wifi", BtChannel), ("mode", u8), ("lost_fired", u8), ("last_tick_ms", f64)]


class BtLinkIn(C.Structure):
    _fields_ = [("t_ms", f64), ("ch", u8), ("kind", u8), ("seq", u32)]


# bt_sizeof에 넘기는 번호 순서 (헤더의 bt_struct_id)
_SIZED = [BtXY, BtCell, BtRaster, BtEvent, BtState, BtStop, BtReason, BtPathMetrics, BtOption, BtDecision, BtConfig, BtEnv,
          BtTriggerIn, BtGauge, BtPathValue, BtScienceView, BtBudget, BtPath, BtNlt, BtChannel, BtLink, BtLinkIn, BtTrigger,
          BtEventRef, BtProfile, BtLinkCfg, BtGridGeom, BtHypView, BtTracePt]


class AbiMismatch(RuntimeError):
    """이 파일의 구조체가 빌드된 코어와 다르다. 코어를 다시 빌드하거나 이 파일을 헤더에 맞춘다."""


class BtError(RuntimeError):
    """코어가 오류 코드를 돌려줬다."""

    def __init__(self, func: str, status: int):
        super().__init__(f"{func} → {STATUS_NAME.get(status, status)}")
        self.status = status


_lib = None


def lib_path() -> Path:
    """코어 라이브러리 파일. 환경변수 BT_CORE_LIB가 있으면 그것, 없으면 저장소의 build/native/ 아래."""
    if os.environ.get("BT_CORE_LIB"):
        return Path(os.environ["BT_CORE_LIB"])
    name = "libbtcore.dylib" if sys.platform == "darwin" else "libbtcore.so"   # 운영체제마다 확장자가 다르다
    return Path(__file__).resolve().parent.parent / "build" / "native" / name


def load() -> C.CDLL:
    """라이브러리를 불러 버전과 구조체 크기를 대조한다. 한 번만 불러 두고 다시 쓴다."""
    global _lib
    if _lib is not None:
        return _lib
    path = lib_path()
    if not path.exists():
        raise FileNotFoundError(f"코어 라이브러리가 없다: {path}\n저장소 루트에서 `cmake --preset native && cmake --build --preset native`")
    lib = C.CDLL(str(path))
    lib.bt_abi_version.restype = u32
    lib.bt_sizeof.restype = u32
    lib.bt_sizeof.argtypes = [u32]
    if lib.bt_abi_version() != ABI_VERSION:
        raise AbiMismatch(f"코어 ABI {lib.bt_abi_version()} ≠ 바인딩 {ABI_VERSION}")
    for sid, cls in enumerate(_SIZED):
        if lib.bt_sizeof(sid) != C.sizeof(cls):
            raise AbiMismatch(f"{cls.__name__}: 코어 {lib.bt_sizeof(sid)} B ≠ 바인딩 {C.sizeof(cls)} B")
    P, vp = C.POINTER, C.c_void_p            # vp = bt_ctx* (불투명 핸들)
    sig = {
        "bt_arena_bytes": (C.c_int, [P(BtConfig), P(u64)]),
        "bt_create": (C.c_int, [P(BtConfig), vp, u64, P(vp)]),
        "bt_set_layer": (C.c_int, [vp, C.c_int, P(BtRaster)]),
        "bt_set_env": (C.c_int, [vp, P(BtEnv)]),
        "bt_speed_mps": (f64, [vp, f64, C.c_int]),
        "bt_costmap_build": (C.c_int, [vp, f64]),
        "bt_costmap_view": (C.c_int, [vp, P(BtRaster), P(BtRaster)]),
        "bt_plan": (C.c_int, [vp, BtXY, BtXY, P(BtBudget), P(BtPath)]),
        "bt_replan": (C.c_int, [vp, P(BtPath), BtXY, BtXY, P(BtBudget), P(BtPath)]),
        "bt_cost_to_go": (C.c_int, [vp, BtXY, C.c_int, C.c_int]),
        "bt_set_field": (C.c_int, [vp, C.c_int, P(BtRaster), P(BtRaster)]),
        "bt_field_copy": (C.c_int, [vp, C.c_int, P(BtRaster), P(BtRaster)]),
        "bt_return_path": (C.c_int, [vp, C.c_int, BtXY, P(BtPath)]),
        "bt_path_measure": (C.c_int, [vp, P(BtPath), P(BtState), C.c_int, P(BtPathMetrics)]),
        "bt_alternatives": (C.c_int, [vp, BtXY, BtXY, P(BtBudget), P(BtPath), u32, P(u32)]),
        "bt_log_append": (C.c_int, [vp, P(BtEvent)]),
        "bt_log_merge": (C.c_int, [vp, P(BtEvent), u32, P(u32)]),
        "bt_log_since": (C.c_int, [vp, P(u32), P(BtEvent), u32, P(u32)]),
        "bt_log_have": (C.c_int, [vp, P(u32)]),
        "bt_log_view": (C.c_int, [vp, P(P(BtEvent)), P(u32)]),
        "bt_log_digest": (u64, [vp]),
        "bt_science_update": (C.c_int, [vp, f64]),
        "bt_science_get_view": (C.c_int, [vp, P(BtScienceView)]),
        "bt_science_digest": (u64, [vp]),
        "bt_science_hyp_delta": (C.c_int, [vp, u32, P(BtRaster)]),
        "bt_path_evaluate": (C.c_int, [vp, P(BtPath), P(BtStop), u32, P(BtPathValue)]),
        "bt_triggers": (C.c_int, [vp, P(BtState), P(BtState), P(BtTriggerIn), P(BtTrigger), u32, P(u32)]),
        "bt_decide": (C.c_int, [vp, P(BtState), P(BtStop), u32, P(BtStop), u32, P(BtTrigger), P(BtDecision)]),
        "bt_decision_close": (C.c_int, [vp, u32]),
        "bt_decision_path": (C.c_int, [vp, P(BtDecision), u32, P(BtPath)]),
        "bt_decision_candidates": (C.c_int, [vp, P(BtDecision), P(BtOption), u32, P(u32)]),
        "bt_nlt_feasible": (C.c_int, [vp, P(BtPath), P(BtStop), u32, P(BtState), P(BtNlt)]),
        "bt_depart_limit": (C.c_int, [vp, P(BtState), P(BtNlt)]),
        "bt_safety_check": (C.c_int, [vp, P(BtState), P(BtState), P(BtTrigger), u32, P(u32), P(u8)]),
        "bt_gauge_compute": (C.c_int, [vp, BtXY, P(BtPathMetrics), P(BtState), P(BtGauge)]),
        "bt_link_step": (C.c_int, [vp, P(BtLink), P(BtLinkIn), P(u8), P(u8)]),
        "bt_config_digest": (u64, [vp]),
        "bt_decision_digest": (u64, [P(BtDecision)]),
        "bt_option_digest": (u64, [P(BtOption)]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    _lib = lib
    return lib


class Path_:
    """경로 하나: 칸의 열과 그 수치. 코어가 쓰는 버퍼(칸 배열)를 이 객체가 들고 있다.

    칸은 격자 원점 (0, 0) 기준, 칸 크기 res_m. 경로마다 res_m이 다를 수 있다(로버의 2 m 경로, 4 m 귀환 경로 …)
    → 좌표로 바꿀 때는 꼭 이 객체의 res_m을 쓴다 (xy()가 그렇게 한다).
    """

    def __init__(self, cap: int):
        self.buf = (BtCell * cap)()
        self.c = BtPath()
        self.c.cells = C.cast(self.buf, C.POINTER(BtCell))
        self.c.cap = cap
        self.status = OK

    @property
    def cells(self) -> np.ndarray:
        """[n, 2] 정수 배열 (row, col)."""
        return np.frombuffer(self.buf, dtype=np.int32, count=2 * self.c.len).reshape(-1, 2).copy()

    def xy(self) -> np.ndarray:
        """[n, 2] 칸 중심의 로컬 좌표 (x 동쪽, y 북쪽)."""
        rc = self.cells
        return np.stack([(rc[:, 1] + 0.5) * self.c.res_m, -(rc[:, 0] + 0.5) * self.c.res_m], axis=1)

    res_m = property(lambda s: s.c.res_m)
    length_m = property(lambda s: s.c.length_m)
    cost = property(lambda s: s.c.cost)
    expansions = property(lambda s: s.c.expansions)
    complete = property(lambda s: bool(s.c.complete))
    n = property(lambda s: s.c.len)


def _xy(p) -> BtXY:
    return p if isinstance(p, BtXY) else BtXY(float(p[0]), float(p[1]))


class Core:
    """코어 인스턴스 하나 = 노드 하나(기기 또는 로버). 메서드는 헤더의 함수와 1:1이다.

    오류 처리: 코어가 음수 상태 코드를 내면 BtError를 던진다. 다만 "길이 없음"처럼 정상 흐름에서 나올 수 있는 코드는
    메서드마다 ok=(…)로 받아들이고 결과 객체의 status에 남긴다 — 부른 쪽이 status를 보고 갈린다.
    """

    def __init__(self, cfg: BtConfig):
        self.lib = load()
        self.cfg = cfg
        need = u64()
        self._check("bt_arena_bytes", self.lib.bt_arena_bytes(C.byref(cfg), C.byref(need)))
        self.arena_bytes = need.value
        self._arena = C.create_string_buffer(need.value)          # 코어가 쓰는 메모리 전부
        self.ctx = C.c_void_p()
        self._check("bt_create", self.lib.bt_create(C.byref(cfg), self._arena, need, C.byref(self.ctx)))
        self._keep: dict = {}                                      # 코어가 포인터만 들고 있는 배열들을 붙들어 둔다
        self._path_cap = max(4096, 16 * (cfg.cost_grid.h + cfg.cost_grid.w))

    @classmethod
    def create(cls, cfg: BtConfig) -> Core:
        return cls(cfg)

    @staticmethod
    def _check(func: str, status: int, ok: tuple = (OK,)) -> int:
        if status not in ok:
            raise BtError(func, status)
        return status

    # ── 레이어·환경 ──
    def _raster(self, a: np.ndarray, res_m: float, dtype: int, h: int, w: int, planes: int = 1, scale: float = 1.0, offset: float = 0.0) -> BtRaster:
        r = BtRaster()
        r.data = a.ctypes.data
        r.h, r.w, r.res_m, r.dtype, r.planes, r.scale, r.offset = h, w, res_m, dtype, planes, scale, offset
        r.origin = BtXY(0.0, 0.0)                                   # 모든 격자의 원점은 구역의 북서쪽 모서리
        return r

    def set_layer(self, kind: str, a: np.ndarray, res_m: float, shape: tuple[int, int], *, bits: bool = False, planes: int = 1,
                  scale: float = 1.0, offset: float = 0.0) -> None:
        """번들 배열을 코어에 연결한다. a는 float32 / uint16 / uint8(또는 bits=True면 묶인 비트) 배열."""
        a = np.ascontiguousarray(a)
        dtype = DT_BITS if bits else {np.dtype("float32"): DT_F32, np.dtype("uint16"): DT_U16, np.dtype("uint8"): DT_U8}[a.dtype]
        r = self._raster(a, res_m, dtype, shape[0], shape[1], planes, scale, offset)
        self._check(f"bt_set_layer({kind})", self.lib.bt_set_layer(self.ctx, LAYER[kind], C.byref(r)))
        self._keep[kind] = a

    def set_env(self, env: BtEnv) -> None:
        self._check("bt_set_env", self.lib.bt_set_env(self.ctx, C.byref(env)))

    # ── 코스트맵·경로 ──
    def costmap_build(self, res_m: float | None = None) -> None:
        """레이어·환경·막힘 표시가 바뀌면 다시 부른다. res_m을 안 주면 설정의 탐색 격자."""
        self._check("bt_costmap_build", self.lib.bt_costmap_build(self.ctx, float(res_m or self.cfg.grid_m)))

    def costmap_view(self) -> tuple[np.ndarray, np.ndarray, float]:
        """(비용 바탕 float32, 통과 가능 uint8, 칸 크기). 코어 메모리를 그대로 보는 뷰다 — 고치지 말 것."""
        cost, passable = BtRaster(), BtRaster()
        self._check("bt_costmap_view", self.lib.bt_costmap_view(self.ctx, C.byref(cost), C.byref(passable)))
        n = cost.h * cost.w
        a = np.ctypeslib.as_array(C.cast(cost.data, C.POINTER(f32)), shape=(n,)).reshape(cost.h, cost.w)
        b = np.ctypeslib.as_array(C.cast(passable.data, C.POINTER(u8)), shape=(n,)).reshape(cost.h, cost.w)
        return a, b, cost.res_m

    def plan(self, start, goal, profile: int = 0, max_expansions: int = 0) -> Path_:
        """start → goal 경로. status: OK(끝까지 풂) / PARTIAL(예산 소진 또는 목표가 재계획 반경 밖) / ERR_UNREACHABLE(길 없음)."""
        p, b = Path_(self._path_cap), BtBudget()
        b.profile, b.max_expansions = profile, max_expansions
        p.status = self._check("bt_plan", self.lib.bt_plan(self.ctx, _xy(start), _xy(goal), C.byref(b), C.byref(p.c)), ok=(OK, PARTIAL, ERR_UNREACHABLE))
        return p

    def cost_to_go(self, target, mode: int = WALK_RETURN) -> None:
        """target까지의 귀환 필드(걷는 시간, 다음 방향)를 계산해 코어 안에 둔다. 로버가 설 때 한 번 부른다."""
        self._check("bt_cost_to_go", self.lib.bt_cost_to_go(self.ctx, _xy(target), mode, FIELD_ROVER_RETURN))

    def field_copy(self) -> tuple[np.ndarray, np.ndarray, float]:
        """계산한 귀환 필드를 꺼낸다: (걷는 시간 float32 초 — 도달 불가는 inf, 다음 방향 uint8, 칸 크기). 기기에 넘길 때 쓴다."""
        _cost, passable, res = self.costmap_view()
        h, w = passable.shape
        t, nx = np.empty((h, w), np.float32), np.empty((h, w), np.uint8)
        rt, rn = self._raster(t, res, DT_F32, h, w), self._raster(nx, res, DT_U8, h, w)
        self._check("bt_field_copy", self.lib.bt_field_copy(self.ctx, FIELD_ROVER_RETURN, C.byref(rt), C.byref(rn)))
        return t, nx, float(rt.res_m)

    def set_field(self, time_s: np.ndarray, next_dir: np.ndarray, res_m: float) -> None:
        """로버가 넘겨준 귀환 필드를 연결한다(기기). 격자는 기기의 탐색 격자와 달라도 된다."""
        t, nx = np.ascontiguousarray(time_s, np.float32), np.ascontiguousarray(next_dir, np.uint8)
        rt, rn = self._raster(t, res_m, DT_F32, *t.shape), self._raster(nx, res_m, DT_U8, *nx.shape)
        self._check("bt_set_field", self.lib.bt_set_field(self.ctx, FIELD_ROVER_RETURN, C.byref(rt), C.byref(rn)))
        self._keep["field"] = (t, nx)

    def return_path(self, start) -> Path_:
        """귀환 필드를 따라 로버까지 가는 경로. 탐색하지 않는다. cost = 걷는 시간(초)."""
        p = Path_(self._path_cap)
        p.status = self._check("bt_return_path", self.lib.bt_return_path(self.ctx, FIELD_ROVER_RETURN, _xy(start), C.byref(p.c)), ok=(OK, ERR_UNREACHABLE))
        return p

    def path_measure(self, path: Path_, state: BtState, mode: int = WALK_PLAN) -> BtPathMetrics:
        """경로의 걷는 시간·최대 경사·선량·통신 두절 시간·길이."""
        m = BtPathMetrics()
        self._check("bt_path_measure", self.lib.bt_path_measure(self.ctx, C.byref(path.c), C.byref(state), mode, C.byref(m)))
        return m

    # ── 이벤트 로그 ──
    def log_append(self, ev: BtEvent) -> BtEvent:
        """이 노드가 만든 이벤트를 넣는다. 코어가 lts와 node를 채워 돌려준다."""
        self._check("bt_log_append", self.lib.bt_log_append(self.ctx, C.byref(ev)))
        return ev

    def log_merge(self, events: list[BtEvent]) -> int:
        """다른 노드에서 온 이벤트를 합친다. 새로 들어온 수를 돌려준다(이미 있던 것은 세지 않는다)."""
        arr = (BtEvent * max(1, len(events)))(*events)
        fresh = u32()
        self._check("bt_log_merge", self.lib.bt_log_merge(self.ctx, arr, len(events), C.byref(fresh)))
        return fresh.value

    def log_have(self) -> list[int]:
        """노드 번호로 찾는 "어디까지 갖고 있나"(최대 lts). 길이 MAX_NODES."""
        have = (u32 * MAX_NODES)()
        self._check("bt_log_have", self.lib.bt_log_have(self.ctx, have))
        return list(have)

    def log_since(self, have: list[int], cap: int = 16) -> tuple[list[BtEvent], bool]:
        """상대가 아직 안 가진 이벤트를 cap건까지. 둘째 값이 True면 더 남았다."""
        out, n = (BtEvent * cap)(), u32()
        st = self._check("bt_log_since", self.lib.bt_log_since(self.ctx, (u32 * MAX_NODES)(*have), out, cap, C.byref(n)), ok=(OK, PARTIAL))
        return [BtEvent.from_buffer_copy(out[i]) for i in range(n.value)], st == PARTIAL

    def log_view(self) -> list[BtEvent]:
        p, n = C.POINTER(BtEvent)(), u32()
        self._check("bt_log_view", self.lib.bt_log_view(self.ctx, C.byref(p), C.byref(n)))
        return [BtEvent.from_buffer_copy(p[i]) for i in range(n.value)]

    def log_digest(self) -> int:
        return self.lib.bt_log_digest(self.ctx)

    # ── 과학 가치 ──
    def science_update(self, t_eval: float) -> int:
        """바탕 지도에 로그 전체를 다시 적용한다. 로그가 바뀌면 부른다. PARTIAL = 닻이 지도 밖이라 건너뛴 가설이 있다."""
        return self._check("bt_science_update", self.lib.bt_science_update(self.ctx, float(t_eval)), ok=(OK, PARTIAL))

    def science_view(self) -> dict:
        """지금의 과학 가치 지도를 복사해 꺼낸다.

        mu           가설이 전부 틀렸을 때의 값 (바탕 지도 + 관측)
        add_expected 가설들이 더하는 값의 기대 (Σ 확신 × 몫) → 기대 지도 = mu + add_expected
        add_full     가설이 전부 맞았을 때 더해지는 값 (Σ 몫)  → 최대 지도 = mu + add_full
        var, live_touched(관측이 닿은 칸), hyps(가설마다 확신. 지도는 따로 없다 — hyp_delta로 꺼낸다), traces
        """
        v = BtScienceView()
        self._check("bt_science_get_view", self.lib.bt_science_get_view(self.ctx, C.byref(v)))
        h, w = v.mu_base.h, v.mu_base.w

        def arr(r: BtRaster, ct, dt):
            return np.ctypeslib.as_array(C.cast(r.data, C.POINTER(ct)), shape=(h * w,)).reshape(h, w).astype(dt)

        hyps = [{"key": hyp_key(v.hyps[i].node, v.hyps[i].seq), "node": v.hyps[i].node, "seq": v.hyps[i].seq, "n_used": v.hyps[i].n_used,
                 "conf_chosen": v.hyps[i].conf_chosen, "conf_now": v.hyps[i].conf_now} for i in range(v.n_hyps)]
        traces = [{"xy": (v.traces[i].xy.x, v.traces[i].xy.y), "kind": v.traces[i].kind, "fade": v.traces[i].fade,
                   "kept": bool(v.traces[i].kept), "alive": bool(v.traces[i].alive)} for i in range(v.n_traces)]
        return {"res_m": v.mu_base.res_m, "mu": arr(v.mu_base, f32, np.float32), "var": arr(v.var, f32, np.float32),
                "add_expected": arr(v.add_expected, f32, np.float32), "add_full": arr(v.add_full, f32, np.float32),
                "live_touched": arr(v.live_touched, u8, np.uint8), "hyps": hyps, "traces": traces}

    def hyp_delta(self, hyp_index: int, shape: tuple[int, int]) -> np.ndarray:
        """가설 하나가 더하는 값의 지도(과학 격자). 화면에서 가설 하나의 영향 범위를 그릴 때 그때그때 부른다."""
        a = np.empty(shape, np.float32)
        r = self._raster(a, 0.0, DT_F32, shape[0], shape[1])
        self._check("bt_science_hyp_delta", self.lib.bt_science_hyp_delta(self.ctx, hyp_index, C.byref(r)))
        return a

    def science_digest(self) -> int:
        return self.lib.bt_science_digest(self.ctx)

    # ── 안전·결정 지점 ──
    def depart_limit(self, state: BtState) -> BtNlt:
        """로버 귀환 출발 한계: t_depart(EVA 경과 초), slack_min(여유 분), binding(일몰 / EVA 최대)."""
        n = BtNlt()
        self._check("bt_depart_limit", self.lib.bt_depart_limit(self.ctx, C.byref(state), C.byref(n)))
        return n

    def safety_check(self, now: BtState, prev: BtState | None = None) -> tuple[list[BtTrigger], bool]:
        """(안전 트리거 목록, 경고 배너를 켤지). 매 틱 부른다."""
        out, n, warn = (BtTrigger * MAX_TRIGGERS)(), u32(), u8()
        self._check("bt_safety_check", self.lib.bt_safety_check(self.ctx, C.byref(now), C.byref(prev or now), out, MAX_TRIGGERS, C.byref(n), C.byref(warn)))
        return [BtTrigger.from_buffer_copy(out[i]) for i in range(n.value)], bool(warn.value)

    def triggers(self, now: BtState, tin: BtTriggerIn, prev: BtState | None = None) -> list[BtTrigger]:
        """이번 틱에 사람에게 물을 일이 있는가. 같은 원인은 열려 있는 동안·cooldown 동안 다시 나오지 않는다."""
        out, n = (BtTrigger * 16)(), u32()
        self._check("bt_triggers", self.lib.bt_triggers(self.ctx, C.byref(now), C.byref(prev or now), C.byref(tin), out, 16, C.byref(n)))
        return [BtTrigger.from_buffer_copy(out[i]) for i in range(n.value)]

    def decide(self, state: BtState, plan: list[BtStop], trigger: BtTrigger, prev_plan: list[BtStop] | None = None) -> BtDecision:
        """결정 지점을 만든다. n_options == 0이고 notices == 0이면 "내지 않는다"는 뜻이니 버린다(헤더 주석)."""
        d = BtDecision()
        a = (BtStop * max(1, len(plan)))(*plan)
        pp = prev_plan or []
        b = (BtStop * max(1, len(pp)))(*pp)
        self._check("bt_decide", self.lib.bt_decide(self.ctx, C.byref(state), a, len(plan), b, len(pp), C.byref(trigger), C.byref(d)))
        return d

    def decision_close(self, seq: int) -> None:
        self._check("bt_decision_close", self.lib.bt_decision_close(self.ctx, seq))

    def decision_path(self, d: BtDecision, option_index: int) -> Path_:
        """방금 낸 결정 지점의 옵션 경로. 다음 bt_decide를 부르기 전에 꺼내야 한다."""
        p = Path_(self._path_cap * 4)
        self._check("bt_decision_path", self.lib.bt_decision_path(self.ctx, C.byref(d), option_index, C.byref(p.c)))
        return p

    def decision_candidates(self, d: BtDecision) -> list[BtOption]:
        """출발 한계를 통과한 후보 전체(로버 콘솔의 비교 표용). 카드로 고른 것도 들어 있다."""
        out, n = (BtOption * MAX_CANDIDATES)(), u32()
        self._check("bt_decision_candidates", self.lib.bt_decision_candidates(self.ctx, C.byref(d), out, MAX_CANDIDATES, C.byref(n)))
        return [BtOption.from_buffer_copy(out[i]) for i in range(n.value)]

    def gauge(self, next_stop, leg: BtPathMetrics, state: BtState) -> BtGauge:
        g = BtGauge()
        self._check("bt_gauge_compute", self.lib.bt_gauge_compute(self.ctx, _xy(next_stop), C.byref(leg), C.byref(state), C.byref(g)))
        return g

    def link_step(self, link: BtLink, t_ms: float, kind: int, ch: int = CH_UHF, seq: int = 0) -> tuple[bool, bool]:
        """링크 상태기계를 한 걸음. link는 호스트가 들고 있는 상태(0으로 시작). (모드가 바뀌었나, 두절이 오래됐나)를 돌려준다."""
        i, changed, lost = BtLinkIn(t_ms, ch, kind, seq), u8(), u8()
        self._check("bt_link_step", self.lib.bt_link_step(self.ctx, C.byref(link), C.byref(i), C.byref(changed), C.byref(lost)))
        return bool(changed.value), bool(lost.value)

    def config_digest(self) -> int:
        return self.lib.bt_config_digest(self.ctx)
