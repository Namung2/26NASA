// bt_ctx 내부 구조와 아레나. 시작할 때 한 번 받은 메모리를 잘라 쓰고 그 뒤로는 더 잡지 않는다
#pragma once
#include "btcore.h"
#include "fixed.hpp"
#include "grid.hpp"
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace bt {

struct Arena {
  uint8_t* base;     // nullptr이면 크기만 센다
  uint64_t off;
  template <class T>
  T* take(uint64_t count) {
    off = (off + 63u) & ~static_cast<uint64_t>(63u);
    T* p = base ? reinterpret_cast<T*>(base + off) : nullptr;
    off += count * sizeof(T);
    return p;
  }
};

// 코스트맵: 방향과 무관한 바탕. 성향마다 base 한 장 (통과불가 칸은 +inf)
struct CostMap {
  uint32_t cap;      // 버퍼의 칸 수
  uint32_t h, w, factor;
  double res;
  float* base[BT_MAX_PROFILES];
  float* elev;       // 칸 평균 고도 (값 없으면 NaN)
  float* slope;      // 칸 안 최대 경사
  uint8_t* passable;
  float min_base[BT_MAX_PROFILES];
  uint8_t built;
};

// 탐색 작업 배열 (A*, 전체장 Dijkstra가 같이 쓴다)
struct Search {
  double* g;         // 누적 비용 (Dijkstra에서는 초)
  float* t;          // 누적 걷는 시간(초)
  uint32_t* stamp;   // 이번 탐색에서 건드렸는지
  uint8_t* flag;     // 하위 4비트 = 들어온 방향, 0x80 = 닫힘, 0x40 = 힙 안
  Heap heap;
  uint32_t cur;
  uint32_t cap;      // 배열의 칸 수
  uint32_t side;     // 전역 격자에서 탐색 창의 한 변(칸). 재계획 반경이 정한다
  int32_t wr0, wc0;  // 지금 탐색 창의 자리 (탐색하는 격자의 칸)
  uint32_t wh, ww;
};

// 경로 주변만 고운 격자로 다시 풀 때 쓰는 조각 (coarse_first_grid_m이 있을 때만)
struct Tile {
  uint32_t cap, side, factor;   // cap = 0이면 쓰지 않는다
  float* base[BT_MAX_PROFILES];
  float* elev;
  uint8_t* passable;
  float min_base[BT_MAX_PROFILES];
  bt_cell* coarse; uint32_t coarse_cap;   // 거친 격자에서 먼저 푼 경로
};

struct Field {
  uint8_t src;       // 0 없음, 1 코어가 계산한 것, 2 호스트가 넘긴 것
  float* time;       // 내부 버퍼 (초)
  uint8_t* next;
  bt_raster ext_time, ext_next;
  Geom geom;
};

struct FieldView { const float* time; const uint8_t* next; Geom geom; };

// 과학 가치 맵 (S3a §5). 전부 과학 작업 격자
struct Hyp {
  uint32_t lts; uint16_t seq, key; uint8_t node, rule, n_used, unit;
  float dir_deg, extent_m, conf0, conf;
  bt_xy anchor; int32_t ar, ac;
};
struct Science {
  Geom g; uint32_t cells;
  uint8_t ready, same_grid;
  float* mu; float* var; uint8_t* live; float* scratch;
  // 가설이 더하는 값을 합친 지도 세 장 (가설마다 따로 두지 않는다):
  //   add_exp = Σ 확신·δ,  add_full = Σ δ,  add_var = Σ 확신·(1−확신)·δ²
  float* add_exp; float* add_full; float* add_var;
  uint32_t n_hyps; Hyp hyp[BT_MAX_HYPS];
  bt_trace_pt* traces; uint32_t n_traces;
  uint32_t skipped;
};

// 결정 지점의 상태 (S3a §6)
constexpr uint32_t COOL_N = 32;
struct Decide {
  uint32_t seq_counter;
  uint8_t open; uint32_t open_seq; bt_trigger open_trig;
  bt_trigger cool_trig[COOL_N]; double cool_ts[COOL_N]; uint32_t cool_n;
  bt_option cand[BT_MAX_CANDIDATES]; uint32_t n_cand; uint32_t cand_seq;
  double cand_res[BT_MAX_CANDIDATES];           // 후보 경로의 칸 크기 (귀환 경로는 필드 격자를 따른다)
  bt_cell* pool; uint32_t pool_cap, pool_len;   // 후보 경로의 칸
  bt_cell* alt; uint32_t alt_per;               // 갈림길 검사용 (경로 3개)
  uint8_t env_seen, prev_bin; double prev_tau;
  uint8_t route_seen; bt_xy route_stop;
};

}  // namespace bt

struct bt_ctx {
  bt_config cfg;
  bt_raster layer[BT_LAYER_COUNT];
  uint8_t layer_set[BT_LAYER_COUNT];
  uint64_t layer_digest[BT_LAYER_COUNT];
  bt_env env;
  uint8_t env_set;

  bt::CostMap cm;
  bt::Tile tile;
  bt::Search s;
  bt::Field field;

  bt_event* log;
  uint32_t log_n;
  uint32_t clock;

  bt::Science sci;
  bt::Decide dec;

  bt_cell* ret;        // 귀환 경로를 따라가 볼 때 쓰는 작업 버퍼 (return_seconds). 결과로 남기지 않는다
  uint32_t ret_cap;
};

namespace bt {

inline Geom cm_geom(const bt_ctx* c) {
  return Geom{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, c->cm.res, c->cm.h, c->cm.w};
}
inline bool field_view(const bt_ctx* c, FieldView* v) {
  if (c->field.src == 1) { v->time = c->field.time; v->next = c->field.next; v->geom = c->field.geom; return true; }
  if (c->field.src == 2) {
    v->time = static_cast<const float*>(c->field.ext_time.data);
    v->next = static_cast<const uint8_t*>(c->field.ext_next.data);
    v->geom = c->field.geom;
    return true;
  }
  return false;
}

// costmap.cpp
void fill_rect(const bt_ctx* c, uint32_t f, int32_t R0, int32_t C0, uint32_t H, uint32_t W,
               float* const* base, float* elev, float* slope_out, uint8_t* passable, float* min_base);

// planner.cpp
bt_status plan_ex(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out, bool refine);
bt_status alternatives_ex(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out, uint32_t cap, uint32_t* n, bool refine);
bool cell_info(const bt_ctx* c, double res_m, bt_cell a, float* elev, float* slope, uint8_t* los, bt_xy* xy);
double step_seconds(const bt_ctx* c, float e_from, float e_to, double dist_m, int mode);
bool cells_cost(const bt_ctx* c, const bt_cell* cells, uint32_t len, int profile, double* cost, double* length);
// 칸 경로를 "곧게 편 선"으로 걸을 때의 시간(초)·길이(m)·로버와 링크가 안 되는 시간(초). 화면에 그리는 선과 같은 선이다.
// pins: 꼭 지나야 하는 칸의 번호(오름차순 — 들르는 정지점). 그 칸을 건너뛰어 곧게 펴지 않는다. 없으면 nullptr, 0.
uint32_t straight_reach(const bt_ctx* c, const bt_cell* cells, uint32_t len, double res_m, uint32_t anchor, uint32_t limit);
double straight_seconds(const bt_ctx* c, bt_xy a, bt_xy b, double res_m, int mode, double* length, double* lost);
bool straight_measure(const bt_ctx* c, const bt_cell* cells, uint32_t len, double res_m, int mode,
                      const uint32_t* pins, uint32_t n_pins, double* sec, double* length, double* lost);

// safety.cpp
bool return_seconds(const bt_ctx* c, const FieldView& v, bt_xy pos, double* sec, uint8_t* degraded);
double depart_deadline(const bt_ctx* c, uint8_t* binding);    // min(EVA 최대, 일몰 - 여유), EVA 경과 초

// eventlog.cpp
const bt_event* log_find(const bt_ctx* c, uint32_t lts, uint8_t node);

// science.cpp
bool science_geom(const bt_config& cfg, Geom* g);              // 과학 작업 격자. 재계산 안 함이면 false
double hyp_delta_at(const bt_ctx* c, uint32_t hyp_index, uint32_t cell);   // 가설 하나가 그 칸에 더하는 값 (그때 계산)

// mobility.cpp
double slope_factor(double slope_deg);                       // 평지 속도에 곱하는 배율
double walk_mps(const bt_config& cfg, double slope_deg, int mode);

// digest.cpp
constexpr uint64_t FNV_OFFSET = 14695981039346656037ull;
uint64_t fnv_bytes(uint64_t h, const void* p, uint64_t n);
template <class T>
inline uint64_t fnv(uint64_t h, const T& v) { return fnv_bytes(h, &v, sizeof(T)); }

}  // namespace bt
