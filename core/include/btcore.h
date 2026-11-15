/* btcore.h — BingoTime 코어의 유일한 공개 헤더 (C ABI)
 *
 * 기기 프로그램과 로버 프로그램이 같은 라이브러리 파일을 이 헤더의 C 함수로만 부른다.
 * 명세: docs/spec/S2_data_schemas.md §9, docs/spec/S3a_modules_pipeline_core.md
 *
 * 규칙
 * - 구조체·열거값·함수 원형을 바꾸면 BT_ABI_VERSION을 올린다. 호스트는 시작할 때
 *   bt_abi_version()과 bt_sizeof()를 대조하고 어긋나면 실행하지 않는다.
 * - 단위: 길이 m, 좌표 (동쪽 x, 북쪽 y), 시각 EVA 경과 초, 각도 °(0 = 북, 시계 방향).
 * - 격자: (row, col), row 0 = 북쪽. 칸 찾기는
 *     col = floor((x - origin.x) / res_m),  row = floor((origin.y - y) / res_m)
 *   origin은 래스터 좌상단(북서쪽 모서리)의 로컬 좌표다.
 * - 아직 본문이 없는 함수는 BT_ERR_NOT_READY를 돌려준다.
 */
#ifndef BTCORE_H
#define BTCORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#  define BT_API
#elif defined(BT_BUILD)
#  define BT_API __attribute__((visibility("default")))
#else
#  define BT_API
#endif

#define BT_ABI_VERSION 6u

/* ── 용량 상수 ─────────────────────────────────────────────────────────── */
#define BT_MAX_OPTIONS     3
#define BT_MAX_CANDIDATES  8
#define BT_MAX_STOPS       8
#define BT_MAX_REASONS     4
#define BT_MAX_HYPS        16
#define BT_MAX_NODES       8
#define BT_MAX_EVENTS      4096
#define BT_MAX_PROFILES    3      /* 경로 성향: 0 균형, 1 가장 빠름, 2 완만함 */
#define BT_MAX_EPS         4
#define BT_MAX_CHANGED     8      /* bt_trigger_in.changed */
#define BT_MAX_TRIGGERS    4      /* 한 틱에 나올 수 있는 트리거 수 */
#define BT_OPTION_HYPS     4      /* bt_option.hyp_seq */

#define BT_POI_NONE        255    /* bt_stop.poi: 지점 번호 없음 */
#define BT_DIR_NONE        255    /* 귀환 필드 next: 더 갈 곳 없음(목표 칸 또는 도달 불가) */
#define BT_U16_NODATA      65535  /* U16 래스터의 값 없음 */
/* 가설 열쇠: 가설을 만든 노드와 그 노드가 매긴 번호(1~4095)를 한 수로 묶은 것.
 * bt_option.hyp_seq, bt_path_value.hyp_seq, HYP 이벤트의 aux(대체할 가설)가 이 값을 쓴다. 0 = 없음.
 * 와이어의 hyp_id "suit-A:h-012" ↔ BT_HYP_KEY(BT_NODE_SUIT_A, 12) */
#define BT_HYP_KEY(node, seq)  ((uint16_t)((((uint32_t)(node)) << 12) | (((uint32_t)(seq)) & 0x0FFFu)))
#define BT_HYP_KEY_NODE(key)   ((uint8_t)(((uint32_t)(key)) >> 12))
#define BT_HYP_KEY_SEQ(key)    ((uint16_t)(((uint32_t)(key)) & 0x0FFFu))
/* F32 래스터의 값 없음은 NaN이다. 값 없는 칸은 통과불가로 본다. */

/* ── 상태 코드 ─────────────────────────────────────────────────────────── */
typedef enum {
  BT_OK = 0,
  BT_PARTIAL = 1,            /* 예산 소진, 최선해 반환 (bt_log_since에서는 "더 남았음") */
  BT_ERR_ARG = -1,
  BT_ERR_CAPACITY = -2,
  BT_ERR_UNREACHABLE = -3,
  BT_ERR_NOT_READY = -4,     /* 레이어·환경·필드를 넣기 전이거나, 본문이 아직 없는 함수 */
  BT_ERR_ABI = -5
} bt_status;

/* ── 열거값 (구조체 안에서는 uint8_t로 담는다) ─────────────────────────── */
enum { BT_NODE_SUIT_A = 1, BT_NODE_ROVER = 3, BT_NODE_GROUND = 4, BT_NODE_SIM = 5 };   /* 2는 쓰지 않는다 */

enum { BT_EV_HYP = 0, BT_EV_OBS = 1, BT_EV_CHOICE = 2, BT_EV_TRACE = 3, BT_EV_MARK = 4 };
enum { BT_EVF_APPROVED = 1, BT_EVF_FOUND = 2, BT_EVF_CONFIRMED = 4, BT_EVF_WAS_HYP_OPTION = 8 };   /* bt_event.flags */
enum { BT_TRACE_PHOTO = 0, BT_TRACE_MENTION = 1 };      /* TRACE의 kind */
enum { BT_MARK_POI = 0, BT_MARK_BLOCKED = 1 };          /* MARK의 kind */
enum { BT_RULE_STRATA_CONTINUITY = 0, BT_RULE_PROXIMITY = 1, BT_RULE_UNIT_BOUNDARY = 2, BT_RULE_EROSION_EXPOSURE = 3 };

enum { BT_LINK_FULL = 0, BT_LINK_LOCAL = 1 };           /* bt_state.link_mode, bt_link.mode */
enum { BT_STOP_POI = 0, BT_STOP_HYP_TARGET = 1, BT_STOP_LANDMARK = 2, BT_STOP_ROVER = 3 };   /* bt_stop.purpose */

enum { BT_OPT_ROUTE = 0, BT_OPT_STAY = 1, BT_OPT_RETURN = 2 };                               /* bt_option.kind */
/* bt_option.label_key. 번호 = 후보를 만드는 순서(카드의 A·B·C도 이 순서를 따른다).
 * ROUTE_FASTEST / ROUTE_GENTLE: 경로 갈림길(fork/route)에서만 나온다 — 다음 정지점까지를 다른 성향으로 가는 길.
 * 그때의 CONTINUE_PLAN이 지금 성향(보통 균형)의 길이다. 정지점은 같고 가는 길만 다르다(bt_stop.profile).
 * CUSTOM_PLAN: 사람이 직접 짠 정지점 순서(화면의 "경로 재설정"). 트리거가 USER_REQUEST · 원인이 BT_CAUSE_PLAN일 때,
 * bt_decide의 prev_plan 자리에 넘긴 정지점들을 후보로 계산한다. 고르기 전에는 계획이 바뀌지 않는다 */
enum { BT_LABEL_CONTINUE_PLAN = 0, BT_LABEL_ROUTE_FASTEST = 1, BT_LABEL_ROUTE_GENTLE = 2, BT_LABEL_HYP_TARGET = 3,
       BT_LABEL_RESTORE_PLAN = 4, BT_LABEL_CUSTOM_PLAN = 5, BT_LABEL_DROP_LAST = 6, BT_LABEL_STAY = 7, BT_LABEL_RETURN_ROVER = 8 };
enum { BT_OPTF_FROM_HYPOTHESIS = 1, BT_OPTF_PRIOR_ONLY = 2, BT_OPTF_LATE = 4 };              /* bt_option.flags */
enum { BT_OVER_MAX_SLOPE = 1, BT_OVER_DOSE = 2 };                                            /* bt_option.over_limit */
enum { BT_GRADE_LOW = 0, BT_GRADE_MED = 1, BT_GRADE_HIGH = 2 };
enum { BT_BIND_SUNSET = 0, BT_BIND_EVA_MAX = 1 };                                            /* nlt_binding */

enum { BT_TRIG_FORK = 0, BT_TRIG_ENV = 1, BT_TRIG_LINK_LOST = 2, BT_TRIG_SAFETY = 3, BT_TRIG_USER_REQUEST = 4 };
/* cause_kind: 0~3은 와이어 DecisionPoint.cause_kind와 같다. 4 이상은 와이어에서 "other"이고
 * 호스트가 이름을 DecisionPoint.cause에 적는다("spe", "nlt", "sunset", "return", …). */
enum { BT_CAUSE_ROUTE = 0, BT_CAUSE_OBS = 1, BT_CAUSE_HYP = 2, BT_CAUSE_OTHER = 3,
       BT_CAUSE_SPE = 4, BT_CAUSE_NLT = 5, BT_CAUSE_SUNSET = 6, BT_CAUSE_RETURN = 7,
       BT_CAUSE_DUST = 8, BT_CAUSE_SHADOW = 9, BT_CAUSE_LINK = 10,
       BT_CAUSE_PLAN = 11 };            /* 사람이 직접 짠 계획을 견줘 달라고 했다 (USER_REQUEST와 함께) */
enum { BT_NOTICE_HYP_UNREACHABLE = 1, BT_NOTICE_NO_FEASIBLE_RETURN = 2,
       BT_NOTICE_HYP_NO_EFFECT = 4,
       BT_NOTICE_CUSTOM_UNREACHABLE = 8 };   /* 사람이 짠 계획이 출발 한계 안에 끝나지 않거나 길이 없어 선택지에 넣지 않았다 */
/* bt_decision.notices 비트. NO_EFFECT: 가설이 그 방향의 지도 값을 올리지 않아 갈 목표가 없다 */

enum { BT_DT_F32 = 0, BT_DT_U16 = 1, BT_DT_U8 = 2, BT_DT_BITS = 3 };                         /* bt_raster.dtype */
typedef enum { BT_LAYER_SLOPE = 0, BT_LAYER_ELEV = 1, BT_LAYER_ROUGHNESS = 2, BT_LAYER_SHADOW = 3,
               BT_LAYER_LOS = 4, BT_LAYER_MU0 = 5, BT_LAYER_VAR0 = 6, BT_LAYER_UNITS = 7,
               BT_LAYER_TERRAIN_CLASS = 8, BT_LAYER_COUNT = 9 } bt_layer_kind;
typedef enum { BT_WALK_PLAN = 0, BT_WALK_RETURN = 1 } bt_walk_mode;
typedef enum { BT_FIELD_ROVER_RETURN = 0, BT_FIELD_COUNT = 1 } bt_field_id;

enum { BT_CH_UHF = 0, BT_CH_WIFI = 1 };                                                      /* bt_link_in.ch */
enum { BT_CHS_UP = 0, BT_CHS_DOWN = 1 };                                                     /* bt_channel.state */
enum { BT_NET_SENT = 0, BT_NET_ACK = 1, BT_NET_SEND_ERROR = 2, BT_NET_TICK = 3 };            /* bt_link_in.kind */
enum { BT_OPTMODE_RECEIVE = 0, BT_OPTMODE_PARETO = 1 };                                      /* bt_config.options_mode */

/* bt_sizeof에 넘기는 번호 */
typedef enum {
  BT_SID_XY = 0, BT_SID_CELL = 1, BT_SID_RASTER = 2, BT_SID_EVENT = 3, BT_SID_STATE = 4,
  BT_SID_STOP = 5, BT_SID_REASON = 6, BT_SID_PATH_METRICS = 7, BT_SID_OPTION = 8, BT_SID_DECISION = 9,
  BT_SID_CONFIG = 10, BT_SID_ENV = 11, BT_SID_TRIGGER_IN = 12, BT_SID_GAUGE = 13, BT_SID_PATH_VALUE = 14,
  BT_SID_SCIENCE_VIEW = 15, BT_SID_BUDGET = 16, BT_SID_PATH = 17, BT_SID_NLT = 18, BT_SID_CHANNEL = 19,
  BT_SID_LINK = 20, BT_SID_LINK_IN = 21, BT_SID_TRIGGER = 22, BT_SID_EVENT_REF = 23, BT_SID_PROFILE = 24,
  BT_SID_LINK_CFG = 25, BT_SID_GRID_GEOM = 26, BT_SID_HYP_VIEW = 27, BT_SID_TRACE_PT = 28,
  BT_SID_COUNT = 29
} bt_struct_id;

/* ── 기본 타입 ─────────────────────────────────────────────────────────── */
typedef struct { double x, y; } bt_xy;                       /* 미터, (동쪽, 북쪽) */
typedef struct { int32_t row, col; } bt_cell;

/* 래스터 뷰. 메모리는 호출자 것이고 코어는 포인터만 든다.
 * - F32: float. 값 없음 = NaN
 * - U16: 값 = 저장값 × scale + offset. 값 없음 = 65535
 * - U8 : 그대로
 * - BITS: 한 장이 ceil(h·w/8) 바이트, 장 b는 그만큼 건너뛴 자리에서 시작.
 *         칸 i = row·w + col 의 비트는 (바이트[i >> 3] >> (7 - (i & 7))) & 1  (numpy.packbits 기본 순서)
 *         그림자: 1 = 그림자. 가시선(LOS 레이어): 1 = 로버와 UHF 링크가 된다고 본 칸 — 눈으로 보이는지가 아니라
 *         전파 손실로 번들이 미리 판정한 것이다 (pipeline/terrain.py link_mask). */
typedef struct {
  const void* data; uint32_t h, w; float res_m; uint8_t dtype; uint8_t planes;
  float scale, offset; bt_xy origin;
} bt_raster;

/* ── 이벤트 (64 B, 문자열 없음) ────────────────────────────────────────── */
typedef struct {
  uint32_t lts;                  /* lamport */
  uint8_t  node;                 /* BT_NODE_* */
  uint8_t  type;                 /* BT_EV_* */
  uint8_t  kind;                 /* type별 세부: CHOICE = 고른 옵션 번호, TRACE = BT_TRACE_*, MARK = BT_MARK_* */
  uint8_t  flags;                /* BT_EVF_* */
  double   ts;                   /* EVA 경과 초 */
  double   x, y;                 /* 위치 (미터) */
  float    a, b, c, d;           /* HYP: 방향(°), 범위(m), 확신 / CHOICE: 선택까지 걸린 초 / MARK: 반경(막힘) */
                                 /* HYP의 x, y = 가설의 닻. seq = 이 노드가 매긴 가설 번호(1~4095) */
  uint32_t ref_lts; uint8_t ref_node; uint8_t rule; uint16_t seq;   /* 참조 이벤트 / 가설 규칙 / 일련번호(가설·관측·결정 지점 번호) */
  uint32_t aux; uint32_t _pad;   /* HYP: 대체(철회)할 가설의 열쇠 BT_HYP_KEY(없으면 0) / CHOICE: 옵션 다이제스트 하위 32비트 */
} bt_event;

typedef struct { uint32_t lts; uint8_t node; uint8_t _pad[3]; } bt_event_ref;

/* ── 상태·환경 ─────────────────────────────────────────────────────────── */
typedef struct {
  double t; bt_xy pos; double heading_deg, sigma;     /* pos, sigma(오차 반경) = 주어진 입력 */
  double dose_cum_uSv;
  uint8_t link_mode, node; bt_xy rover_pos;           /* rover_pos를 모르면 x = y = NaN */
} bt_state;

typedef struct {                 /* 환경. 값이 바뀔 때 bt_set_env로 넣는다 */
  double sun_elev_deg, sun_az_deg;
  double t_sunset_s;             /* EVA 경과 초 */
  double tau_dust;
  double dose_rate_uSv_h;
  uint8_t shadow_bin;            /* 0 ~ planes-1 */
  uint8_t spe;                   /* 0 / 1 */
  uint8_t _pad[6];
} bt_env;

/* ── 설정 (숫자만. 출처·상태는 호스트가 든다) ─────────────────────────── */
typedef struct { bt_xy origin; float res_m; uint32_t h, w; uint32_t _pad; } bt_grid_geom;
typedef struct { float w_s, w_r, w_sh, w_rad; } bt_profile;                       /* 경사, 거칠기, 그림자, 방사선 */
typedef struct { uint32_t timeout_ms; uint8_t n_down, n_up; uint8_t _pad[2];
                 float ewma_alpha, loss_down, rtt_down_ms; } bt_link_cfg;

typedef struct {
  /* 번들 기하. cost_grid = 이 인스턴스가 받을 비용 레이어(경사·고도·거칠기·그림자·가시선)의 격자.
   * science_grid = 과학 레이어(mu0·var0·units)의 격자 */
  bt_grid_geom cost_grid, science_grid;

  /* 노드와 설정 블록 (S4 §1) */
  uint32_t max_expansions;
  uint8_t  node;                 /* BT_NODE_* */
  uint8_t  options_mode;         /* BT_OPTMODE_* */
  uint8_t  options_max, options_min;
  uint8_t  shadow_bins;          /* 그림자 구간 수. 그림자 레이어가 없으면 0 */
  uint8_t  eps_n;                /* planner.eps_schedule의 길이 (≤ BT_MAX_EPS) */
  uint8_t  _pad[2];
  float grid_m;                  /* 탐색 격자. cost_grid.res_m의 정수 배 */
  float coarse_first_grid_m;     /* 없으면 0. 있으면 cost_grid.res_m의 정수 배(2 m 레이어면 4 m). 전역 코스트맵·귀환 필드는 이 격자로
                                    만들고, grid_m 격자는 경로 주변(corridor_m)에서만 다시 푼다 */
  float replan_radius_m;         /* 탐색 창의 반지름. 창은 시작점 중심이고, 목표가 창 밖이면 창 안에서 목표에 가장 가까운 칸까지만
                                    풀고 BT_PARTIAL을 돌려준다. 0이면 탐색 배열을 잡지 않는다 */
  float science_grid_m;          /* 0 = 번들 격자 그대로, 음수 = 재계산 안 함 */
  float grade_bins[2];           /* LOW/MED, MED/HIGH 경계 */

  /* 비용 (S4 §3) */
  bt_profile profiles[BT_MAX_PROFILES];
  float rough_ref_m, dose_ref;

  /* 이동 (S4 §2) */
  float v_plan_kmh, v_return_kmh, theta_max_deg;

  /* 플래너 */
  float eps[BT_MAX_EPS];
  float snap_max_m, alt_overlap_max, corridor_m;

  /* 과학·흔적 */
  float l0_m, aniso_ratio, exposure_slope_ref_deg, obs_noise, unconfirmed_factor, tau_s,
        r_obs_m, w_transit, A_ref_m2, r_plan, touch_eps, var_floor;

  /* 결정 + 표시 정밀도 (S4 §5) */
  float eps_fork, cooldown_s, stay_max_min, stay_buffer_min, hyp_snap_m;
  float prec_time_min, prec_max_slope_deg, prec_dose_uSv, prec_value, prec_value_var,
        prec_info_gain, prec_nlt_margin_min, prec_comm_loss_min;

  /* 안전 */
  float k_return, nlt_warn_min, nlt_force_min, sunset_margin_min, sunset_warn_min, eva_max_h,
        dose_warn_uSv,           /* 없으면 0 */
        dust_tau_warn,
        dust_hold_s,             /* 먼지가 임계 위에 이만큼 이어져야 "넘었다"고 본다(결정 지점). 0이면 넘는 순간. 화면의 경고 표시는 기다리지 않는다 */
        _pad_env;                /* 0 (자리 맞춤 — bt_config는 통째로 해시하므로 빈 자리를 두지 않는다) */

  /* 연결 */
  bt_link_cfg uhf, wifi;
  float lost_dp_s, hb_hz;
} bt_config;

/* ── 경로 ──────────────────────────────────────────────────────────────── */
/* profile: 이 정지점까지 가는 길의 성향(0 균형, 1 가장 빠름, 2 완만함 — bt_config.profiles의 번호). 갈림길에서 사람이 고른 길을
 * 계획이 기억하는 자리다. _pad는 0 (구조체의 크기는 그대로다 — 빈 자리였던 두 바이트를 쓴다) */
typedef struct { bt_xy xy; float dwell_min; uint8_t purpose; uint8_t poi; uint8_t profile; uint8_t _pad; } bt_stop;
typedef struct { uint8_t layer; float value; bt_cell cell; float res_m; } bt_reason;   /* cell.row < 0 이면 칸 없음 */
typedef struct { float time_min, max_slope_deg, dose_uSv, comm_loss_min, length_m; } bt_path_metrics;

typedef struct { double time_s;               /* 경로의 걷는 시간 상한(초). 0 이하면 상한 없음 */
                 uint32_t max_expansions;     /* 0이면 설정값 */
                 uint8_t eps_n; float eps[BT_MAX_EPS];   /* eps_n = 0이면 설정의 스케줄 */
                 uint8_t profile; } bt_budget;
typedef struct { bt_cell* cells; uint32_t cap, len; double res_m, length_m, cost;
                 float eps_bound; uint32_t expansions; uint8_t complete; double snapped_m; } bt_path;
/* 경로의 칸은 cost_grid.origin 기준, 칸 크기 res_m. 8-연결, 시작·끝 포함.
 * res_m은 경로마다 다를 수 있다(고운 격자로 다시 푼 경로, 전역 격자 경로, 귀환 필드의 격자). 좌표로 바꿀 때 꼭 res_m을 쓴다. */

typedef struct { float bearing_deg, distance_m, time_min; } bt_gauge;

/* ── 과학 가치 ─────────────────────────────────────────────────────────── */
typedef struct {
  float value_mean, value_lo, value_hi, value_var, info_gain;
  float peak;                    /* 경로가 지나는 칸 중 최댓값 — 등급을 매기는 값 */
  uint16_t explore_count; uint8_t prior_only; uint8_t _pad;
  uint16_t hyp_seq[BT_OPTION_HYPS];   /* 기여한 가설 번호. 빈 칸은 0 */
} bt_path_value;

typedef struct { uint32_t lts; uint16_t seq; uint8_t node; uint8_t n_used;
                 float conf_chosen, conf_now; } bt_hyp_view;        /* 가설 하나: 처음 고른 확신 / 지금 확신 / 확신 계산에 쓰인 관측 수 */
typedef struct { bt_xy xy; double ts; uint32_t lts; float fade;       /* fade: 1 = 방금 */
                 uint8_t node, kind, kept, alive; } bt_trace_pt;      /* 주의 흔적 한 점. kind = BT_TRACE_* */
/* 가설은 지도에 "더해지는 값"으로 반영된다. 여러 가설이 같은 칸을 올리면 전부 더한다.
 * 가설마다 지도를 따로 저장하지 않고 합친 것만 둔다 (가설 하나의 몫이 필요하면 bt_science_hyp_delta로 그때 계산한다):
 *   add_expected = Σ 확신 × (가설이 더하는 값)    → 기대 지도 = mu_base + add_expected
 *   add_full     = Σ (가설이 더하는 값)           → 가설이 전부 맞았을 때의 지도 = mu_base + add_full */
typedef struct {                 /* 읽기 전용. 전부 과학 격자 */
  bt_raster mu_base, var, live_touched;
  bt_raster add_expected, add_full;
  const bt_trace_pt* traces; uint32_t n_traces;
  uint32_t n_hyps;
  bt_hyp_view hyps[BT_MAX_HYPS];
} bt_science_view;

/* ── 결정 지점 ─────────────────────────────────────────────────────────── */
typedef struct {
  uint8_t label;                 /* 0, 1, 2 → "A", "B", "C" (생성 순. 순위가 아니다) */
  uint8_t kind;                  /* BT_OPT_* */
  uint8_t label_key;             /* BT_LABEL_* */
  uint8_t flags;                 /* BT_OPTF_* */
  uint8_t over_limit;            /* BT_OVER_* 비트 집합 */
  uint8_t n_stops, n_reasons, value_grade, nlt_binding;
  bt_stop stops[BT_MAX_STOPS];
  uint32_t path_off, path_len;   /* 코어 경로 풀 안의 칸 구간 — bt_decision_path로 꺼낸다 */
  float time_min, max_slope_deg, dose_uSv;
  float value_mean, value_var, value_lo, value_hi, info_gain;  uint16_t explore_count;   /* lo~hi 범위는 가설 옵션에만. 그 밖에는 lo = hi = mean */
  float comm_loss_min, nlt_margin_min, return_time_min;
  uint16_t hyp_seq[BT_OPTION_HYPS];
  bt_reason reasons[BT_MAX_REASONS];
  uint64_t digest;
} bt_option;

typedef struct {
  uint32_t seq; uint8_t trigger, cause_kind, forced, n_options;             /* trigger: BT_TRIG_* */
  uint32_t cause_lts; uint8_t cause_node; uint8_t node; uint16_t notices;   /* notices: BT_NOTICE_* 비트 집합 */
  double ts;
  bt_option options[BT_MAX_OPTIONS];
  uint64_t inputs_digest, digest;
} bt_decision;

typedef struct { uint8_t kind; uint8_t forced; uint8_t cause_kind; uint8_t _pad;
                 uint32_t cause_lts; uint8_t cause_node; } bt_trigger;      /* kind: BT_TRIG_*, cause_kind: BT_CAUSE_* */

typedef struct {                 /* bt_triggers에 넘기는 이번 틱의 입력 */
  bt_event_ref changed[BT_MAX_CHANGED]; uint32_t n_changed;   /* 이번에 지도를 바꾼 이벤트 */
  bt_trigger safety[BT_MAX_TRIGGERS];   uint32_t n_safety;    /* 같은 틱에 bt_safety_check가 낸 것 */
  uint8_t link_lost, user_request, has_next_stop, _pad;
  bt_xy next_stop;                                            /* 계획의 다음 정지점. 없으면 has_next_stop = 0 */
} bt_trigger_in;

typedef struct { double t_depart; float slack_min; uint8_t binding; uint8_t degraded; } bt_nlt;   /* binding: BT_BIND_* */

/* ── 링크 ──────────────────────────────────────────────────────────────── */
/* 호스트가 0으로 채워 만들고 bt_link_step에만 넘긴다. down_since, pending_t_ms는 bt_link_in.t_ms와 같은 시계(ms) */
typedef struct { uint8_t state; float rtt_ms, loss; double down_since; uint8_t miss_run, ack_run;
                 uint8_t pending; uint32_t pending_seq; double pending_t_ms; } bt_channel;   /* pending = 답을 기다리는 하트비트 */
typedef struct { bt_channel uhf, wifi; uint8_t mode; uint8_t lost_fired;                  /* mode: BT_LINK_* (UHF만 본다) */
                 double last_tick_ms; } bt_link;
/* bt_link_in: SENT·ACK·SEND_ERROR는 ch의 채널에, TICK은 두 채널 모두에 적용된다(ch는 무시). */
typedef struct { double t_ms; uint8_t ch; uint8_t kind; uint32_t seq; } bt_link_in;       /* kind: BT_NET_* */

/* ══ 함수 ═══════════════════════════════════════════════════════════════ */
typedef struct bt_ctx bt_ctx;    /* 불투명 핸들. 노드 하나의 코어 인스턴스. 한 번에 한 호출만 받는다 */

/* 공통 (S3a §0) */
BT_API uint32_t  bt_abi_version(void);
BT_API uint32_t  bt_sizeof(uint32_t struct_id);                    /* 모르는 번호면 0 */
BT_API bt_status bt_arena_bytes(const bt_config* cfg, uint64_t* out_bytes);
BT_API bt_status bt_create(const bt_config* cfg, void* arena, uint64_t arena_bytes, bt_ctx** out);
BT_API bt_status bt_set_layer(bt_ctx*, bt_layer_kind kind, const bt_raster* r);   /* 복사 없음. ctx가 사는 동안 메모리 유지 */
BT_API bt_status bt_set_env(bt_ctx*, const bt_env* env);

/* 보행 모델·코스트맵 (S3a §2) */
BT_API double    bt_speed_mps(const bt_ctx*, double slope_deg, bt_walk_mode mode);
BT_API bt_status bt_costmap_build(bt_ctx*, double res_m);          /* 레이어·환경·막힘 표시가 바뀌면 다시 부른다.
                                                                      coarse_first_grid_m이 있으면 그보다 고운 res_m은 그 격자로 올린다 */
BT_API bt_status bt_costmap_view(const bt_ctx*, bt_raster* out_cost, bt_raster* out_passable);

/* 플래너 (S3a §3) */
BT_API bt_status bt_plan(bt_ctx*, bt_xy start, bt_xy goal, const bt_budget*, bt_path* out);
BT_API bt_status bt_replan(bt_ctx*, const bt_path* prev, bt_xy start, bt_xy goal, const bt_budget*, bt_path* out);
BT_API bt_status bt_cost_to_go(bt_ctx*, bt_xy target, bt_walk_mode mode, bt_field_id out_field);
BT_API bt_status bt_set_field(bt_ctx*, bt_field_id id, const bt_raster* time, const bt_raster* next);
BT_API bt_status bt_field_copy(const bt_ctx*, bt_field_id id, bt_raster* out_time, bt_raster* out_next);
/* 귀환 필드: time = F32 초(도달 불가 = +inf), next = U8 방향 번호(0 북, 1 북동, 2 동, 3 남동, 4 남, 5 남서, 6 서, 7 북서,
 * BT_DIR_NONE = 없음). bt_field_copy는 out_*->data가 가리키는 호출자 버퍼(h·w 칸)에 쓰고 나머지 필드를 채운다. */
BT_API bt_status bt_return_path(bt_ctx*, bt_field_id field, bt_xy start, bt_path* out);
BT_API bt_status bt_path_measure(bt_ctx*, const bt_path*, const bt_state*, bt_walk_mode mode, bt_path_metrics* out);
BT_API bt_status bt_alternatives(bt_ctx*, bt_xy start, bt_xy goal, const bt_budget*, bt_path* out, uint32_t cap, uint32_t* n);
/* 경로의 꺾이는 점만 낸다(칸 중심의 좌표, 시작·끝 포함). 격자 경로는 8방향이라 계단 모양인데, 사이를 직선으로 이어도
 * 통과 가능한 곳만 지나는 구간은 선 하나로 줄인다. 화면에 그릴 때와 UHF로 보낼 때(점 수를 줄여야 한다) 쓴다.
 * 걷는 시간·길이·링크가 안 되는 시간도 이 선으로 잰다(bt_path_measure, bt_depart_limit, 옵션의 시간과 귀환 시간) — 그린 길과 잰 길이 같다.
 * 계단 길을 따라 재면 직선보다 최대 약 8 % 길게 나온다(REFERENCE §4.5). 귀환 지도에 적힌 값(bt_field_copy, bt_return_path의 cost)만
 * 계단 길의 시간 그대로이고, 귀환 경로를 적지 못했을 때의 대신 값으로만 쓴다(긴 쪽이라 안전하다). */
BT_API bt_status bt_path_polyline(const bt_ctx*, const bt_path*, bt_xy* out, uint32_t cap, uint32_t* n);
/* 들를 지점과 순서를 고른다: start에서 출발해 고른 지점을 차례로 들르고 end에 닿는 걷는 시간 + 체류 시간이
 * budget->time_s 안에 드는 것 가운데 과학 가치의 합이 가장 큰 것. 값이 같으면 시간이 짧은 쪽, 그것도 같으면 번호가 앞선 쪽.
 * time_s ≤ 0이면 시간 제한 없이 전부 들르는 가장 짧은 순서. n ≤ BT_MAX_STOPS. out은 n칸 이상. */
BT_API bt_status bt_select_pois(bt_ctx*, const bt_stop* pois, uint32_t n, bt_xy start, bt_xy end,
                                const bt_budget*, bt_stop* out, uint32_t* out_n);

/* 이벤트 로그 (S3a §4) */
BT_API bt_status bt_log_append(bt_ctx*, bt_event* ev_inout);       /* lts와 node를 채운다 */
BT_API bt_status bt_log_merge(bt_ctx*, const bt_event* evs, uint32_t n, uint32_t* out_fresh);
BT_API bt_status bt_log_since(const bt_ctx*, const uint32_t have_lts[BT_MAX_NODES], bt_event* out, uint32_t cap, uint32_t* n);
BT_API bt_status bt_log_have(const bt_ctx*, uint32_t out_have_lts[BT_MAX_NODES]);          /* 노드 번호로 찾는 최대 lts */
BT_API bt_status bt_log_view(const bt_ctx*, const bt_event** out, uint32_t* n);            /* (lts, node) 정렬 */
BT_API uint64_t  bt_log_digest(const bt_ctx*);

/* 과학 가치 (S3a §5) */
BT_API bt_status bt_science_update(bt_ctx*, double t_eval);
BT_API bt_status bt_science_get_view(const bt_ctx*, bt_science_view* out);
BT_API bt_status bt_science_hyp_delta(const bt_ctx*, uint32_t hyp_index, bt_raster* out);   /* 가설 하나가 더하는 값. out->data = 호출자 버퍼(F32, 과학 격자 h·w 칸) */
BT_API uint64_t  bt_science_digest(const bt_ctx*);
BT_API bt_status bt_path_evaluate(const bt_ctx*, const bt_path*, const bt_stop* stops, uint32_t n_stops, bt_path_value* out);

/* 결정 지점 (S3a §6) */
BT_API bt_status bt_triggers(bt_ctx*, const bt_state* now, const bt_state* prev, const bt_trigger_in* in,
                             bt_trigger* out, uint32_t cap, uint32_t* n);
BT_API bt_status bt_decide(bt_ctx*, const bt_state*, const bt_stop* plan, uint32_t n_plan,
                           const bt_stop* prev_plan, uint32_t n_prev,
                           const bt_trigger*, bt_decision* out);
/* BT_OK인데 out->n_options == 0 이고 out->notices == 0 이면 "결정 지점을 내지 않는다"(S3a §6.4) — 호스트는 버린다.
 * 안전·귀환 요청이 아닌 트리거는 options_mode = PARETO인 인스턴스(로버)만 받는다. 그 밖에는 BT_ERR_ARG. */
BT_API bt_status bt_decision_close(bt_ctx*, uint32_t dp_seq);
BT_API bt_status bt_decision_path(const bt_ctx*, const bt_decision*, uint32_t option_index, bt_path* out);
BT_API bt_status bt_decision_candidates(const bt_ctx*, const bt_decision*, bt_option* out, uint32_t cap, uint32_t* n);
BT_API bt_status bt_nlt_feasible(const bt_ctx*, const bt_path*, const bt_stop* stops, uint32_t n,
                                 const bt_state*, bt_nlt* out);                 /* out->slack_min < 0 이면 출발 한계를 넘긴다 */

/* 안전 (S3a §7) */
BT_API bt_status bt_depart_limit(const bt_ctx*, const bt_state*, bt_nlt* out);
BT_API bt_status bt_safety_check(bt_ctx*, const bt_state* now, const bt_state* prev,
                                 bt_trigger* out, uint32_t cap, uint32_t* n, uint8_t* out_warn);

/* 게이지 (S3a §8) */
BT_API bt_status bt_gauge_compute(const bt_ctx*, bt_xy next_stop, const bt_path_metrics* leg, const bt_state*, bt_gauge* out);

/* 링크 (S3a §9) */
BT_API bt_status bt_link_step(const bt_ctx*, bt_link* s, const bt_link_in* in, uint8_t* out_mode_changed, uint8_t* out_lost_trigger);

/* 다이제스트 (S3a §10) — FNV-1a 64 */
BT_API uint64_t  bt_config_digest(const bt_ctx*);                  /* 설정 + 연결된 레이어의 내용 */
BT_API uint64_t  bt_decision_digest(const bt_decision*);
BT_API uint64_t  bt_option_digest(const bt_option*);

#ifdef __cplusplus
}
#endif
#endif /* BTCORE_H */
