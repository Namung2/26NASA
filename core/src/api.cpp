// C ABI 진입점 가운데 공통부: 버전·크기 대조, 아레나, 레이어·환경 연결
#include "ctx.hpp"

using namespace bt;

static_assert(sizeof(bt_event) == 64, "bt_event는 64 B");
static_assert(sizeof(bt_grid_geom) == 32, "bt_grid_geom 안에 빈 자리가 없어야 한다");
static_assert(sizeof(bt_link_cfg) == 20, "bt_link_cfg 안에 빈 자리가 없어야 한다");
static_assert(sizeof(bt_config) == 384, "bt_config 안에 빈 자리가 없어야 한다 (통째로 해시한다)");

uint32_t bt_abi_version(void) { return BT_ABI_VERSION; }

uint32_t bt_sizeof(uint32_t id) {
  switch (id) {
    case BT_SID_XY: return sizeof(bt_xy);
    case BT_SID_CELL: return sizeof(bt_cell);
    case BT_SID_RASTER: return sizeof(bt_raster);
    case BT_SID_EVENT: return sizeof(bt_event);
    case BT_SID_STATE: return sizeof(bt_state);
    case BT_SID_STOP: return sizeof(bt_stop);
    case BT_SID_REASON: return sizeof(bt_reason);
    case BT_SID_PATH_METRICS: return sizeof(bt_path_metrics);
    case BT_SID_OPTION: return sizeof(bt_option);
    case BT_SID_DECISION: return sizeof(bt_decision);
    case BT_SID_CONFIG: return sizeof(bt_config);
    case BT_SID_ENV: return sizeof(bt_env);
    case BT_SID_TRIGGER_IN: return sizeof(bt_trigger_in);
    case BT_SID_GAUGE: return sizeof(bt_gauge);
    case BT_SID_PATH_VALUE: return sizeof(bt_path_value);
    case BT_SID_SCIENCE_VIEW: return sizeof(bt_science_view);
    case BT_SID_BUDGET: return sizeof(bt_budget);
    case BT_SID_PATH: return sizeof(bt_path);
    case BT_SID_NLT: return sizeof(bt_nlt);
    case BT_SID_CHANNEL: return sizeof(bt_channel);
    case BT_SID_LINK: return sizeof(bt_link);
    case BT_SID_LINK_IN: return sizeof(bt_link_in);
    case BT_SID_TRIGGER: return sizeof(bt_trigger);
    case BT_SID_EVENT_REF: return sizeof(bt_event_ref);
    case BT_SID_PROFILE: return sizeof(bt_profile);
    case BT_SID_LINK_CFG: return sizeof(bt_link_cfg);
    case BT_SID_GRID_GEOM: return sizeof(bt_grid_geom);
    case BT_SID_HYP_VIEW: return sizeof(bt_hyp_view);
    case BT_SID_TRACE_PT: return sizeof(bt_trace_pt);
    default: return 0;
  }
}

namespace {

constexpr uint64_t MAX_CELLS = 64ull * 1000 * 1000;   // 한 격자의 칸 수 상한

struct Sizes {
  uint64_t cm_cells;      // 전역 코스트맵(탐색 격자, 또는 거친 격자)의 칸 수
  uint64_t search_cells;  // 탐색 배열의 칸 수 = 탐색 창과 고운 조각 중 큰 쪽
  uint32_t side;          // 탐색 창의 한 변
  uint64_t tile_cells; uint32_t tile_side, tile_factor;   // 고운 조각 (없으면 0)
  uint64_t path_cells;    // 경로 하나의 길이 상한
};

bool int_factor(double res, double base, uint32_t* f) {
  const double fr = res / base;
  const uint32_t k = static_cast<uint32_t>(fr + 0.5);
  if (k < 1 || std::fabs(fr - static_cast<double>(k)) > 1e-6) return false;
  *f = k;
  return true;
}

bool cfg_ok(const bt_config* cfg, Sizes* z) {
  const bt_grid_geom& g = cfg->cost_grid;
  if (!(g.res_m > 0) || g.h == 0 || g.w == 0) return false;
  if (static_cast<uint64_t>(g.h) * g.w > MAX_CELLS) return false;
  uint32_t f = 0, fc = 0;
  if (!int_factor(cfg->grid_m, g.res_m, &f)) return false;          // 탐색 격자는 레이어 격자의 정수 배
  const bool c2f = cfg->coarse_first_grid_m > cfg->grid_m;
  if (c2f) {
    if (!int_factor(cfg->coarse_first_grid_m, g.res_m, &fc)) return false;   // 거친 격자도 정수 배 (2 m 레이어면 4 m, 6 m …)
    if (!(cfg->corridor_m > 0) || !(cfg->replan_radius_m > 0)) return false;
  }
  if (cfg->node >= BT_MAX_NODES) return false;
  if (cfg->eps_n > BT_MAX_EPS) return false;
  if (!(cfg->v_plan_kmh > 0) || !(cfg->v_return_kmh > 0) || !(cfg->theta_max_deg > 0)) return false;
  if (!(cfg->replan_radius_m >= 0)) return false;
  const bt_grid_geom& sg = cfg->science_grid;
  if (!(cfg->science_grid_m < 0)) {
    if (!(sg.res_m > 0) || sg.h == 0 || sg.w == 0) return false;
    Geom wg;
    if (!science_geom(*cfg, &wg) || static_cast<uint64_t>(wg.h) * wg.w > MAX_CELLS) return false;
  }
  const uint32_t fm = c2f ? fc : f;                                   // 전역 코스트맵의 배율
  const uint64_t H = (g.h + fm - 1) / fm, W = (g.w + fm - 1) / fm;
  const uint64_t fh = (g.h + f - 1) / f, fw = (g.w + f - 1) / f;      // 고운(탐색) 격자의 크기
  z->cm_cells = H * W;
  // 탐색 창: 재계획 반경의 두 배 + 1칸. 격자보다 크면 격자 전체
  const double cm_res = static_cast<double>(g.res_m) * fm;
  uint64_t side = static_cast<uint64_t>(std::ceil(static_cast<double>(cfg->replan_radius_m) / cm_res)) * 2 + 1;
  const uint64_t big = H > W ? H : W;
  if (side > big) side = big;
  z->side = static_cast<uint32_t>(side);
  z->search_cells = (side < H ? side : H) * (side < W ? side : W);
  z->tile_cells = 0; z->tile_side = 0; z->tile_factor = f;
  if (c2f) {
    // 조각의 한 변 = 회랑 폭의 6배 (경로 한 구간 + 양옆 회랑이 들어간다)
    const double fine_res = static_cast<double>(g.res_m) * f;
    uint64_t ts = static_cast<uint64_t>(std::ceil(6.0 * static_cast<double>(cfg->corridor_m) / fine_res)) + 2;
    const uint64_t th = ts < fh ? ts : fh, tw = ts < fw ? ts : fw;
    z->tile_side = static_cast<uint32_t>(ts);
    z->tile_cells = th * tw;
    if (z->tile_cells > z->search_cells) z->search_cells = z->tile_cells;
  }
  // 경로 하나의 길이 상한: 고운 격자 둘레의 16배 또는 칸 수 중 작은 쪽
  const uint64_t ring = 16 * (fh + fw);
  z->path_cells = ring < fh * fw ? ring : fh * fw;
  return true;
}

// 아레나를 앞에서부터 잘라 배정한다. base가 없으면 크기만 센다
bt_ctx* layout(Arena& a, const bt_config* cfg, const Sizes& z) {
  bt_ctx* c = a.take<bt_ctx>(1);
  bt_ctx tmp;
  bt_ctx* x = c ? c : &tmp;
  if (c) std::memset(c, 0, sizeof(bt_ctx));
  const uint64_t cells = z.cm_cells;
  x->log = a.take<bt_event>(BT_MAX_EVENTS);
  x->cm.cap = static_cast<uint32_t>(cells);
  for (int p = 0; p < BT_MAX_PROFILES; ++p) x->cm.base[p] = a.take<float>(cells);
  x->cm.elev = a.take<float>(cells);
  x->cm.slope = a.take<float>(cells);
  x->cm.passable = a.take<uint8_t>(cells);
  x->field.time = a.take<float>(cells);
  x->field.next = a.take<uint8_t>(cells);
  Geom sg;
  if (science_geom(*cfg, &sg)) {
    const uint64_t sc = static_cast<uint64_t>(sg.h) * sg.w;
    x->sci.g = sg;
    x->sci.cells = static_cast<uint32_t>(sc);
    x->sci.same_grid = (sg.res == static_cast<double>(cfg->science_grid.res_m)) ? 1 : 0;
    x->sci.mu = a.take<float>(sc);
    x->sci.var = a.take<float>(sc);
    x->sci.live = a.take<uint8_t>(sc);
    x->sci.scratch = a.take<float>(sc);
    x->sci.add_exp = a.take<float>(sc);
    x->sci.add_full = a.take<float>(sc);
    x->sci.add_var = a.take<float>(sc);
    x->sci.traces = a.take<bt_trace_pt>(BT_MAX_EVENTS);
  }
  x->dec.pool_cap = static_cast<uint32_t>(z.path_cells * BT_MAX_CANDIDATES);
  x->dec.pool = a.take<bt_cell>(z.path_cells * BT_MAX_CANDIDATES);
  x->dec.alt_per = static_cast<uint32_t>(z.path_cells);
  x->dec.alt = a.take<bt_cell>(z.path_cells * BT_MAX_PROFILES);
  x->ret_cap = static_cast<uint32_t>(z.path_cells);
  x->ret = a.take<bt_cell>(z.path_cells);
  if (cfg->replan_radius_m > 0) {
    const uint64_t n = z.search_cells;
    x->s.cap = static_cast<uint32_t>(n);
    x->s.side = z.side;
    x->s.g = a.take<double>(n);
    x->s.t = a.take<float>(n);
    x->s.stamp = a.take<uint32_t>(n);
    x->s.flag = a.take<uint8_t>(n);
    x->s.heap.e = a.take<HeapEntry>(n);
    x->s.heap.pos = a.take<int32_t>(n);
    x->s.heap.cap = static_cast<uint32_t>(n);
    if (z.tile_cells > 0) {
      x->tile.cap = static_cast<uint32_t>(z.tile_cells);
      x->tile.side = z.tile_side;
      x->tile.factor = z.tile_factor;
      for (int p = 0; p < BT_MAX_PROFILES; ++p) x->tile.base[p] = a.take<float>(z.tile_cells);
      x->tile.elev = a.take<float>(z.tile_cells);
      x->tile.passable = a.take<uint8_t>(z.tile_cells);
      x->tile.coarse_cap = static_cast<uint32_t>(z.path_cells);
      x->tile.coarse = a.take<bt_cell>(z.path_cells);
    }
  }
  return c;
}

}  // namespace

bt_status bt_arena_bytes(const bt_config* cfg, uint64_t* out_bytes) {
  if (!cfg || !out_bytes) return BT_ERR_ARG;
  Sizes z;
  if (!cfg_ok(cfg, &z)) return BT_ERR_ARG;
  Arena a{nullptr, 0};
  layout(a, cfg, z);
  *out_bytes = a.off + 64;   // 호스트 버퍼의 정렬 여유
  return BT_OK;
}

bt_status bt_create(const bt_config* cfg, void* arena, uint64_t arena_bytes, bt_ctx** out) {
  if (!cfg || !arena || !out) return BT_ERR_ARG;
  uint64_t need = 0;
  const bt_status st = bt_arena_bytes(cfg, &need);
  if (st != BT_OK) return st;
  if (arena_bytes < need) return BT_ERR_CAPACITY;
  Sizes z;
  cfg_ok(cfg, &z);
  const uint64_t addr = reinterpret_cast<uintptr_t>(arena);
  const uint64_t pad = (64 - (addr & 63u)) & 63u;
  Arena a{static_cast<uint8_t*>(arena) + pad, 0};
  bt_ctx* c = layout(a, cfg, z);
  c->cfg = *cfg;
  // 자리 채움 바이트는 0으로 맞춘다 (설정을 통째로 해시하므로)
  c->cfg.cost_grid._pad = 0;
  c->cfg.science_grid._pad = 0;
  std::memset(c->cfg._pad, 0, sizeof(c->cfg._pad));
  std::memset(c->cfg.uhf._pad, 0, sizeof(c->cfg.uhf._pad));
  std::memset(c->cfg.wifi._pad, 0, sizeof(c->cfg.wifi._pad));
  if (c->s.stamp) std::memset(c->s.stamp, 0, z.search_cells * sizeof(uint32_t));
  *out = c;
  return BT_OK;
}

bt_status bt_set_layer(bt_ctx* c, bt_layer_kind kind, const bt_raster* r) {
  if (!c || !r || !r->data) return BT_ERR_ARG;
  if (static_cast<int>(kind) < 0 || kind >= BT_LAYER_COUNT) return BT_ERR_ARG;
  const bool science = (kind == BT_LAYER_MU0 || kind == BT_LAYER_VAR0 || kind == BT_LAYER_UNITS);
  const bt_grid_geom& g = science ? c->cfg.science_grid : c->cfg.cost_grid;
  if (r->h != g.h || r->w != g.w) return BT_ERR_ARG;
  if (std::fabs(static_cast<double>(r->res_m) - static_cast<double>(g.res_m)) > 1e-6) return BT_ERR_ARG;
  bool ok = false;
  switch (kind) {
    case BT_LAYER_SLOPE: case BT_LAYER_ROUGHNESS: case BT_LAYER_MU0: case BT_LAYER_VAR0:
      ok = (r->dtype == BT_DT_F32); break;
    case BT_LAYER_ELEV:
      ok = (r->dtype == BT_DT_F32 || r->dtype == BT_DT_U16); break;
    case BT_LAYER_SHADOW:
      ok = (r->dtype == BT_DT_BITS && r->planes >= 1 && r->planes == c->cfg.shadow_bins); break;
    case BT_LAYER_LOS:
      ok = (r->dtype == BT_DT_BITS); break;
    case BT_LAYER_UNITS: case BT_LAYER_TERRAIN_CLASS:
      ok = (r->dtype == BT_DT_U8); break;
    default: break;
  }
  if (!ok) return BT_ERR_ARG;
  c->layer[kind] = *r;
  if (c->layer[kind].planes == 0) c->layer[kind].planes = 1;
  c->layer_set[kind] = 1;
  c->layer_digest[kind] = fnv_bytes(FNV_OFFSET, r->data, raster_bytes(c->layer[kind]));
  c->cm.built = 0;   // 레이어가 바뀌면 코스트맵을 다시 만든다
  return BT_OK;
}

bt_status bt_set_env(bt_ctx* c, const bt_env* env) {
  if (!c || !env) return BT_ERR_ARG;
  if (c->cfg.shadow_bins > 0 && env->shadow_bin >= c->cfg.shadow_bins) return BT_ERR_ARG;
  if (!(env->dose_rate_uSv_h >= 0) || !(env->tau_dust >= 0)) return BT_ERR_ARG;
  c->env = *env;
  std::memset(c->env._pad, 0, sizeof(c->env._pad));
  c->env_set = 1;
  return BT_OK;
}
