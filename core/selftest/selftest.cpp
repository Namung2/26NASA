// 자체 시험 실행 파일. AddressSanitizer·UBSan 빌드로 돌린다 (S7 §3).
// 합성 격자에서 경로·귀환 필드·출발 한계·로그를 돌려 본다. 코어 규칙(할당 금지 등)은 core/src에만 적용된다.
#include "btcore.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static int g_fail = 0, g_checks = 0;
#define CHECK(cond) do { g_checks++; if (!(cond)) { g_fail++; std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define NEAR(a, b, tol) CHECK(std::fabs((a) - (b)) <= (tol))

static bt_config make_cfg(uint32_t h, uint32_t w, float res, float grid) {
  bt_config c;
  std::memset(&c, 0, sizeof(c));
  c.cost_grid.origin = bt_xy{0.0, 0.0};
  c.cost_grid.res_m = res; c.cost_grid.h = h; c.cost_grid.w = w;
  c.science_grid = c.cost_grid; c.science_grid.res_m = 20.0f;
  c.max_expansions = 200000; c.node = BT_NODE_SUIT_A; c.options_mode = BT_OPTMODE_RECEIVE; c.options_max = 3;
  c.shadow_bins = 0; c.eps_n = 3; c.eps[0] = 3.0f; c.eps[1] = 1.5f; c.eps[2] = 1.0f;
  c.grid_m = grid; c.replan_radius_m = 2000.0f;
  c.profiles[0] = bt_profile{1.0f, 0.5f, 0.3f, 0.1f};
  c.profiles[1] = bt_profile{1.0f, 0.0f, 0.0f, 0.0f};
  c.profiles[2] = bt_profile{2.0f, 1.0f, 0.3f, 0.1f};
  c.rough_ref_m = 0.5f; c.dose_ref = 27.9f;
  c.v_plan_kmh = 2.0f; c.v_return_kmh = 2.7f; c.theta_max_deg = 20.0f;
  c.snap_max_m = 20.0f; c.alt_overlap_max = 0.8f; c.corridor_m = 100.0f;
  c.k_return = 1.0f; c.nlt_warn_min = 20.0f; c.nlt_force_min = 7.0f;
  c.sunset_margin_min = 30.0f; c.sunset_warn_min = 60.0f; c.eva_max_h = 8.0f;
  return c;
}

struct Core {
  std::vector<uint8_t> arena;
  bt_ctx* ctx = nullptr;
  bt_config cfg;
  bool create(const bt_config& c) {
    cfg = c;
    uint64_t bytes = 0;
    if (bt_arena_bytes(&cfg, &bytes) != BT_OK) return false;
    arena.assign(bytes, 0xAB);
    return bt_create(&cfg, arena.data(), bytes, &ctx) == BT_OK;
  }
};

static bt_raster f32_raster(const std::vector<float>& v, uint32_t h, uint32_t w, float res) {
  bt_raster r;
  std::memset(&r, 0, sizeof(r));
  r.data = v.data(); r.h = h; r.w = w; r.res_m = res; r.dtype = BT_DT_F32; r.planes = 1; r.scale = 1.0f;
  return r;
}
static bt_env calm_env() {
  bt_env e;
  std::memset(&e, 0, sizeof(e));
  e.sun_elev_deg = 40; e.sun_az_deg = 180; e.t_sunset_s = 12 * 3600.0; e.tau_dust = 0.4; e.dose_rate_uSv_h = 27.9;
  return e;
}
static bt_xy cxy(float res, int row, int col) { return bt_xy{(col + 0.5) * res, -(row + 0.5) * res}; }
static bt_budget budget() { bt_budget b; std::memset(&b, 0, sizeof(b)); return b; }

static void test_abi() {
  CHECK(bt_abi_version() == BT_ABI_VERSION);
  CHECK(bt_sizeof(BT_SID_EVENT) == 64);
  for (uint32_t i = 0; i < BT_SID_COUNT; ++i) CHECK(bt_sizeof(i) > 0);
  CHECK(bt_sizeof(999) == 0);
  CHECK(bt_sizeof(BT_SID_OPTION) == sizeof(bt_option));
}

static void test_arena() {
  bt_config c = make_cfg(64, 64, 5.0f, 5.0f);
  uint64_t bytes = 0;
  CHECK(bt_arena_bytes(&c, &bytes) == BT_OK);
  std::vector<uint8_t> a(bytes);
  bt_ctx* ctx = nullptr;
  CHECK(bt_create(&c, a.data(), bytes - 1, &ctx) == BT_ERR_CAPACITY);   // 1바이트 모자라면 거부
  CHECK(bt_create(&c, a.data(), bytes, &ctx) == BT_OK);
  bt_config bad = c; bad.grid_m = 7.0f;                                  // 레이어 격자의 정수 배가 아님
  CHECK(bt_arena_bytes(&bad, &bytes) == BT_ERR_ARG);
}

static void test_speed() {
  Core k; CHECK(k.create(make_cfg(8, 8, 5.0f, 5.0f)));
  NEAR(bt_speed_mps(k.ctx, 0.0, BT_WALK_PLAN), 2.0 / 3.6, 1e-6);
  NEAR(bt_speed_mps(k.ctx, 0.0, BT_WALK_RETURN), 0.75, 1e-6);
  NEAR(bt_speed_mps(k.ctx, 10.0, BT_WALK_RETURN), 0.65, 1e-6);          // v = 0.75 - 0.01·θ
  NEAR(bt_speed_mps(k.ctx, -10.0, BT_WALK_RETURN), 0.85, 1e-6);
  NEAR(bt_speed_mps(k.ctx, -11.0, BT_WALK_RETURN), 0.85 * 0.905, 1e-6);  // 급한 내리막: 1°마다 9.5 %
  CHECK(bt_speed_mps(k.ctx, -15.0, BT_WALK_RETURN) < bt_speed_mps(k.ctx, -10.0, BT_WALK_RETURN));
}

// 64×64 @ 5 m: 동쪽으로 완만히 오르는 면, 가운데 세로 벽(col 32)에 틈(row 30~33), 구석에 갇힌 방
struct Mini {
  static constexpr uint32_t H = 64, W = 64;
  std::vector<float> slope, elev, rough;
  Mini() : slope(H * W, 3.0f), elev(H * W), rough(H * W, 0.1f) {
    for (uint32_t r = 0; r < H; ++r) for (uint32_t c = 0; c < W; ++c) {
      elev[r * W + c] = 0.05f * 5.0f * c;
      if (c == 32 && !(r >= 30 && r <= 33)) slope[r * W + c] = 35.0f;
      const bool room_wall = (r >= 50 && r <= 60 && c >= 50 && c <= 60) && (r == 50 || r == 60 || c == 50 || c == 60);
      if (room_wall) slope[r * W + c] = 35.0f;
    }
    slope[5 * W + 5] = std::nanf("");   // 값 없는 칸
  }
  bool blocked(int r, int c) const { const float s = slope[r * W + c]; return !(s == s) || s > 20.0f; }
};

static bool setup(Core& k, const Mini& m, float grid) {
  if (!k.create(make_cfg(Mini::H, Mini::W, 5.0f, grid))) return false;
  bt_raster rs = f32_raster(m.slope, Mini::H, Mini::W, 5.0f), re = f32_raster(m.elev, Mini::H, Mini::W, 5.0f),
            rr = f32_raster(m.rough, Mini::H, Mini::W, 5.0f);
  bt_env e = calm_env();
  return bt_set_layer(k.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ELEV, &re) == BT_OK &&
         bt_set_layer(k.ctx, BT_LAYER_ROUGHNESS, &rr) == BT_OK && bt_set_env(k.ctx, &e) == BT_OK;
}

// 경로를 5 m 원본 격자에 다시 얹어 통과불가 침범과 모서리 끼어들기를 센다
static int violations(const Mini& m, const bt_path& p) {
  int bad = 0;
  const int f = static_cast<int>(p.res_m / 5.0 + 0.5);
  for (uint32_t i = 0; i < p.len; ++i) {
    const bt_cell a = p.cells[i];
    for (int r = a.row * f; r < (a.row + 1) * f && r < 64; ++r)
      for (int c = a.col * f; c < (a.col + 1) * f && c < 64; ++c)
        if (m.blocked(r, c)) bad++;
    if (i > 0 && f == 1) {
      const bt_cell q = p.cells[i - 1];
      if (a.row != q.row && a.col != q.col && (m.blocked(a.row, q.col) || m.blocked(q.row, a.col))) bad++;
    }
  }
  return bad;
}

static void test_plan() {
  Mini m; Core k; CHECK(setup(k, m, 5.0f));
  std::vector<bt_cell> buf(4096), buf2(4096);
  bt_path p; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 4096;
  bt_budget b = budget();
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p) == BT_ERR_NOT_READY);   // 코스트맵을 만들기 전
  CHECK(bt_costmap_build(k.ctx, 5.0) == BT_OK);

  const bt_status st = bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p);
  CHECK(st == BT_OK);
  CHECK(p.complete == 1 && p.eps_bound == 1.0f && p.len > 55);
  CHECK(p.cells[0].row == 10 && p.cells[0].col == 5 && p.cells[p.len - 1].row == 10 && p.cells[p.len - 1].col == 60);
  CHECK(violations(m, p) == 0);
  bool through_gap = false;
  for (uint32_t i = 0; i < p.len; ++i) if (p.cells[i].col == 32) through_gap = (p.cells[i].row >= 30 && p.cells[i].row <= 33);
  CHECK(through_gap);                                                    // 벽의 틈을 찾는다
  CHECK(p.expansions <= k.cfg.max_expansions);

  bt_path p2; std::memset(&p2, 0, sizeof(p2)); p2.cells = buf2.data(); p2.cap = 4096;   // 두 번 풀면 같다 (V-7)
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p2) == BT_OK);
  CHECK(p2.len == p.len && p2.cost == p.cost && p2.expansions == p.expansions);
  CHECK(std::memcmp(buf.data(), buf2.data(), p.len * sizeof(bt_cell)) == 0);

  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 55, 55), &b, &p2) == BT_ERR_UNREACHABLE);   // 갇힌 방
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), bt_xy{-50.0, 10.0}, &b, &p2) == BT_ERR_UNREACHABLE);   // 지도 밖
  bt_path small; std::memset(&small, 0, sizeof(small)); small.cells = buf2.data(); small.cap = 10;
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &small) == BT_ERR_CAPACITY);       // 버퍼가 짧다

  bt_budget tight = budget(); tight.max_expansions = 30;                // 예산이 바닥나도 멈춘다
  const bt_status st2 = bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &tight, &p2);
  CHECK(st2 == BT_PARTIAL || st2 == BT_ERR_UNREACHABLE);
  CHECK(p2.expansions <= 30);

  bt_path p3; std::memset(&p3, 0, sizeof(p3)); p3.cells = buf2.data(); p3.cap = 4096;      // 통과불가 시작점은 가까운 칸으로
  CHECK(bt_plan(k.ctx, cxy(5, 10, 32), cxy(5, 10, 60), &b, &p3) == BT_OK);
  CHECK(p3.snapped_m > 0.0 && p3.snapped_m <= 20.0 && violations(m, p3) == 0);

  // 임의 쌍: 침범 0, 예산 초과 0
  uint32_t seed = 17;
  int solved = 0;
  for (int it = 0; it < 300; ++it) {
    seed = seed * 1664525u + 1013904223u; const int r0 = (seed >> 8) % 64, c0 = (seed >> 16) % 64;
    seed = seed * 1664525u + 1013904223u; const int r1 = (seed >> 8) % 64, c1 = (seed >> 16) % 64;
    bt_budget bb = budget(); bb.profile = static_cast<uint8_t>(it % 3);
    const bt_status s = bt_plan(k.ctx, cxy(5, r0, c0), cxy(5, r1, c1), &bb, &p2);
    CHECK(s == BT_OK || s == BT_ERR_UNREACHABLE);
    if (s == BT_OK) { solved++; CHECK(violations(m, p2) == 0); }
    CHECK(p2.expansions <= k.cfg.max_expansions);
  }
  CHECK(solved > 200);

  // 이전 경로의 접미부를 다시 쓴다
  bt_path p4; std::vector<bt_cell> buf4(4096); std::memset(&p4, 0, sizeof(p4)); p4.cells = buf4.data(); p4.cap = 4096;
  const bt_cell mid = p.cells[p.len / 2];
  CHECK(bt_replan(k.ctx, &p, cxy(5, mid.row, mid.col), cxy(5, 10, 60), &b, &p4) == BT_OK);
  CHECK(p4.cells[p4.len - 1].col == 60 && violations(m, p4) == 0);

  // 대안 경로
  std::vector<bt_cell> ab[3]; bt_path alts[3]; uint32_t n = 0;
  for (int i = 0; i < 3; ++i) { ab[i].resize(4096); std::memset(&alts[i], 0, sizeof(bt_path)); alts[i].cells = ab[i].data(); alts[i].cap = 4096; }
  CHECK(bt_alternatives(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, alts, 3, &n) == BT_OK);
  CHECK(n >= 1 && n <= 3);

  bt_raster cost, pass;
  CHECK(bt_costmap_view(k.ctx, &cost, &pass) == BT_OK);
  CHECK(cost.h == 64 && pass.dtype == BT_DT_U8 && static_cast<const uint8_t*>(pass.data)[5 * 64 + 5] == 0);
}

static void test_downsample() {
  Mini m; Core k; CHECK(setup(k, m, 10.0f));
  CHECK(bt_costmap_build(k.ctx, 10.0) == BT_OK);
  bt_raster cost, pass;
  CHECK(bt_costmap_view(k.ctx, &cost, &pass) == BT_OK);
  CHECK(pass.h == 32 && pass.w == 32);
  const uint8_t* pp = static_cast<const uint8_t*>(pass.data);
  int wrong = 0;                                    // 5 m 통과불가 칸이 든 거친 칸은 통과불가
  for (int r = 0; r < 64; ++r) for (int c = 0; c < 64; ++c) if (m.blocked(r, c) && pp[(r / 2) * 32 + c / 2]) wrong++;
  CHECK(wrong == 0);
  std::vector<bt_cell> buf(4096); bt_path p; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 4096;
  bt_budget b = budget();
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p) == BT_OK);
  CHECK(p.res_m == 10.0 && violations(m, p) == 0);
  CHECK(bt_costmap_build(k.ctx, 5.0) == BT_ERR_CAPACITY);   // 설정한 탐색 격자보다 고운 격자는 버퍼에 안 들어간다
}

static void test_field() {
  Mini m; Core k; CHECK(setup(k, m, 5.0f));
  CHECK(bt_costmap_build(k.ctx, 5.0) == BT_OK);
  bt_state st; std::memset(&st, 0, sizeof(st)); st.pos = cxy(5, 10, 5); st.t = 3600.0;
  bt_nlt nlt;
  CHECK(bt_depart_limit(k.ctx, &st, &nlt) == BT_ERR_NOT_READY);          // 귀환 필드가 아직 없다
  const bt_xy rover = cxy(5, 40, 58);
  CHECK(bt_cost_to_go(k.ctx, rover, BT_WALK_RETURN, BT_FIELD_ROVER_RETURN) == BT_OK);

  std::vector<float> ft(64 * 64); std::vector<uint8_t> fn(64 * 64);
  bt_raster rt, rn; std::memset(&rt, 0, sizeof(rt)); std::memset(&rn, 0, sizeof(rn));
  rt.data = ft.data(); rt.h = 64; rt.w = 64; rn.data = fn.data(); rn.h = 64; rn.w = 64;
  CHECK(bt_field_copy(k.ctx, BT_FIELD_ROVER_RETURN, &rt, &rn) == BT_OK);
  CHECK(ft[40 * 64 + 58] == 0.0f && fn[40 * 64 + 58] == BT_DIR_NONE);
  CHECK(std::isinf(ft[55 * 64 + 55]));                                   // 갇힌 방에서는 못 돌아온다

  // 귀환 경로 (V-1): 지도에 적힌 값은 8방향 계단 길의 시간이고(경로의 cost로 그대로 나온다), 재는 시간은 그 길을 곧게 편 선의 시간이다.
  // 곧게 편 선은 계단 길보다 길 수 없다(삼각 부등식). 시간은 계단 길의 값과 8방향 격자의 기하학적 한도(1/cos 22.5° ≈ 1.082) 안에서 맞아야 한다
  std::vector<bt_cell> buf(4096); bt_path p; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 4096;
  uint32_t seed = 17; int tried = 0;
  double ratio_lo = 1e9, ratio_hi = 0.0;
  for (int it = 0; it < 200; ++it) {
    seed = seed * 1664525u + 1013904223u; const int r = (seed >> 8) % 64, c = (seed >> 16) % 64;
    if (!std::isfinite(ft[r * 64 + c])) {
      // 막힌 칸: 가까이에 갈 수 있는 칸이 있으면 거기서 시작한 경로(snapped_m > 0), 없으면 길 없음
      const bt_status rs = bt_return_path(k.ctx, BT_FIELD_ROVER_RETURN, cxy(5, r, c), &p);
      CHECK(rs == BT_ERR_UNREACHABLE || (rs == BT_OK && p.snapped_m > 0.0 && p.len >= 1));
      continue;
    }
    CHECK(bt_return_path(k.ctx, BT_FIELD_ROVER_RETURN, cxy(5, r, c), &p) == BT_OK);
    CHECK(p.cells[p.len - 1].row == 40 && p.cells[p.len - 1].col == 58 && violations(m, p) == 0);
    bt_path_metrics pm;
    CHECK(bt_path_measure(k.ctx, &p, &st, BT_WALK_RETURN, &pm) == BT_OK);
    CHECK(p.cost == static_cast<double>(ft[r * 64 + c]));
    CHECK(pm.length_m <= p.length_m * (1.0 + 1e-6) + 1e-3);
    ratio_lo = std::min(ratio_lo, pm.time_min * 60.0 / std::max(1e-9, static_cast<double>(ft[r * 64 + c])));
    ratio_hi = std::max(ratio_hi, pm.time_min * 60.0 / std::max(1e-9, static_cast<double>(ft[r * 64 + c])));
    if (ft[r * 64 + c] > 0) CHECK(pm.time_min * 60.0 <= ft[r * 64 + c] * 1.02 + 1.0 && pm.time_min * 60.0 >= ft[r * 64 + c] / 1.0824 * 0.97 - 1.0);
    tried++;
  }
  CHECK(tried > 100);
  std::printf("  귀환: 곧게 편 선의 시간 / 지도에 적힌 시간 = %.3f ~ %.3f\n", ratio_lo, ratio_hi);

  // 같은 필드를 다른 인스턴스(기기 쪽)에 넘겨도 같은 출발 한계가 나온다
  Core dev; CHECK(setup(dev, m, 5.0f));
  rt.dtype = BT_DT_F32; rn.dtype = BT_DT_U8;
  CHECK(bt_set_field(dev.ctx, BT_FIELD_ROVER_RETURN, &rt, &rn) == BT_OK);
  bt_nlt a, b2;
  CHECK(bt_depart_limit(k.ctx, &st, &a) == BT_OK && bt_depart_limit(dev.ctx, &st, &b2) == BT_OK);
  CHECK(a.t_depart == b2.t_depart && a.slack_min == b2.slack_min && a.binding == BT_BIND_EVA_MAX && a.degraded == 0);
  {                                                                      // 출발 한계 = 마감 − (지금 자리에서 곧게 편 귀환 경로를 걷는 시간)
    bt_path_metrics pm0;
    CHECK(bt_return_path(k.ctx, BT_FIELD_ROVER_RETURN, st.pos, &p) == BT_OK && bt_path_measure(k.ctx, &p, &st, BT_WALK_RETURN, &pm0) == BT_OK);
    NEAR(a.t_depart, 8 * 3600.0 - pm0.time_min * 60.0, 0.05);
    CHECK(a.t_depart >= 8 * 3600.0 - ft[10 * 64 + 5] - 1e-6);              // 지도에 적힌(계단 길) 시간보다 늦게 떠나도 된다
  }
  st.pos = cxy(5, 55, 55);                                               // 필드가 닿지 않는 자리 → 가까운 칸 값 + 걷는 시간
  CHECK(bt_depart_limit(k.ctx, &st, &a) == BT_OK && a.degraded == 1);

  // 안전 감시
  bt_trigger trg[BT_MAX_TRIGGERS]; uint32_t n = 0; uint8_t warn = 0;
  st.pos = cxy(5, 10, 5); st.t = 3600.0;
  CHECK(bt_safety_check(k.ctx, &st, &st, trg, BT_MAX_TRIGGERS, &n, &warn) == BT_OK && n == 0 && warn == 0);
  CHECK(bt_depart_limit(k.ctx, &st, &a) == BT_OK);
  st.t = a.t_depart - 10 * 60.0;                                         // 여유 10분 → 경고만
  CHECK(bt_safety_check(k.ctx, &st, &st, trg, BT_MAX_TRIGGERS, &n, &warn) == BT_OK && n == 0 && warn == 1);
  st.t = a.t_depart - 5 * 60.0;                                          // 여유 5분 → 강제 귀환
  CHECK(bt_safety_check(k.ctx, &st, &st, trg, BT_MAX_TRIGGERS, &n, &warn) == BT_OK && n == 1);
  CHECK(trg[0].kind == BT_TRIG_SAFETY && trg[0].forced == 1 && trg[0].cause_kind == BT_CAUSE_NLT);
  bt_env e = calm_env(); e.spe = 1; st.t = 3600.0;
  CHECK(bt_set_env(k.ctx, &e) == BT_OK);
  CHECK(bt_safety_check(k.ctx, &st, &st, trg, BT_MAX_TRIGGERS, &n, &warn) == BT_OK && n == 1 && trg[0].cause_kind == BT_CAUSE_SPE);

  // 게이지: 정동쪽 = 90°
  bt_path_metrics leg; std::memset(&leg, 0, sizeof(leg)); leg.length_m = 120.0f; leg.time_min = 3.6f;
  bt_gauge gz;
  CHECK(bt_gauge_compute(k.ctx, bt_xy{st.pos.x + 100.0, st.pos.y}, &leg, &st, &gz) == BT_OK);
  NEAR(gz.bearing_deg, 90.0, 1e-4); CHECK(gz.distance_m == 120.0f && gz.time_min == 3.6f);
}

// 평지 4.4 km를 2.7 km/h로 → 97.8분 (REFERENCE §3.1의 아폴로 17 기록)
static void test_apollo_walkback() {
  const uint32_t W = 900;
  std::vector<float> slope(W, 0.0f), elev(W, 0.0f);
  Core k; CHECK(k.create(make_cfg(1, W, 5.0f, 5.0f)));
  bt_raster rs = f32_raster(slope, 1, W, 5.0f), re = f32_raster(elev, 1, W, 5.0f);
  bt_env e = calm_env();
  CHECK(bt_set_layer(k.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ELEV, &re) == BT_OK);
  CHECK(bt_set_env(k.ctx, &e) == BT_OK && bt_costmap_build(k.ctx, 5.0) == BT_OK);
  CHECK(bt_cost_to_go(k.ctx, cxy(5, 0, 0), BT_WALK_RETURN, BT_FIELD_ROVER_RETURN) == BT_OK);
  bt_state st; std::memset(&st, 0, sizeof(st)); st.pos = cxy(5, 0, 880); st.t = 0.0;
  bt_nlt nlt;
  CHECK(bt_depart_limit(k.ctx, &st, &nlt) == BT_OK);
  NEAR((8 * 3600.0 - nlt.t_depart) / 60.0, 97.78, 0.01);
  e.t_sunset_s = 6 * 3600.0;                        // 일몰이 먼저 묶는다
  CHECK(bt_set_env(k.ctx, &e) == BT_OK && bt_depart_limit(k.ctx, &st, &nlt) == BT_OK);
  CHECK(nlt.binding == BT_BIND_SUNSET);
  NEAR(nlt.t_depart, 6 * 3600.0 - 30 * 60.0 - 4400.0 / 0.75, 0.01);
}

static bt_event ev(uint8_t type, double ts, double x, double y) {
  bt_event e; std::memset(&e, 0, sizeof(e)); e.type = type; e.ts = ts; e.x = x; e.y = y; return e;
}

static void test_log() {
  bt_config cs = make_cfg(8, 8, 5.0f, 5.0f), cr = cs; cr.node = BT_NODE_ROVER;
  Core suit, rover, third; CHECK(suit.create(cs) && rover.create(cr) && third.create(cr));
  for (int i = 0; i < 5; ++i) { bt_event e = ev(BT_EV_OBS, 10.0 * i, i, -i); CHECK(bt_log_append(suit.ctx, &e) == BT_OK); CHECK(e.lts == static_cast<uint32_t>(i + 1) && e.node == BT_NODE_SUIT_A); }
  for (int i = 0; i < 3; ++i) { bt_event e = ev(BT_EV_TRACE, 5.0 * i, i, i); CHECK(bt_log_append(rover.ctx, &e) == BT_OK); }
  const bt_event *sv, *rv; uint32_t sn, rn, fresh = 0;
  CHECK(bt_log_view(suit.ctx, &sv, &sn) == BT_OK && sn == 5);
  CHECK(bt_log_view(rover.ctx, &rv, &rn) == BT_OK && rn == 3);
  std::vector<bt_event> s_copy(sv, sv + sn), r_copy(rv, rv + rn);

  // since / have 왕복
  uint32_t have[BT_MAX_NODES]; bt_event out[16]; uint32_t n = 0;
  CHECK(bt_log_have(rover.ctx, have) == BT_OK && have[BT_NODE_ROVER] == 3 && have[BT_NODE_SUIT_A] == 0);
  CHECK(bt_log_since(suit.ctx, have, out, 2, &n) == BT_PARTIAL && n == 2);   // 다 못 실었다
  CHECK(bt_log_since(suit.ctx, have, out, 16, &n) == BT_OK && n == 5);
  CHECK(bt_log_merge(rover.ctx, out, n, &fresh) == BT_OK && fresh == 5);
  CHECK(bt_log_merge(rover.ctx, out, n, &fresh) == BT_OK && fresh == 0);     // 멱등
  CHECK(bt_log_merge(suit.ctx, r_copy.data(), 3, &fresh) == BT_OK && fresh == 3);
  CHECK(bt_log_digest(suit.ctx) == bt_log_digest(rover.ctx));                // 교환
  CHECK(bt_log_merge(third.ctx, r_copy.data(), 3, &fresh) == BT_OK && bt_log_merge(third.ctx, s_copy.data(), 5, &fresh) == BT_OK);
  CHECK(bt_log_digest(third.ctx) == bt_log_digest(suit.ctx));
  bt_event e = ev(BT_EV_OBS, 99.0, 0, 0);
  CHECK(bt_log_append(rover.ctx, &e) == BT_OK && e.lts == 6);                // lamport: 본 것보다 크게

  // 용량 초과는 상태 코드로
  Core full; CHECK(full.create(cs));
  bt_status last = BT_OK;
  for (int i = 0; i < BT_MAX_EVENTS + 1; ++i) { bt_event x = ev(BT_EV_TRACE, i, 0, 0); last = bt_log_append(full.ctx, &x); }
  CHECK(last == BT_ERR_CAPACITY);

  // 막힘 표시는 코스트맵에 반영된다
  Mini m; Core k; CHECK(setup(k, m, 5.0f));
  bt_event mk = ev(BT_EV_MARK, 0, 0, 0); mk.kind = BT_MARK_BLOCKED; mk.a = 10.0f;
  const bt_xy at = cxy(5, 20, 20); mk.x = at.x; mk.y = at.y;
  CHECK(bt_log_append(k.ctx, &mk) == BT_OK && bt_costmap_build(k.ctx, 5.0) == BT_OK);
  bt_raster cost, pass; CHECK(bt_costmap_view(k.ctx, &cost, &pass) == BT_OK);
  const uint8_t* pp = static_cast<const uint8_t*>(pass.data);
  CHECK(pp[20 * 64 + 20] == 0 && pp[20 * 64 + 22] == 0 && pp[20 * 64 + 23] == 1);
}

// 들를 지점과 순서 고르기
static void test_select_pois() {
  Mini m; Core k; CHECK(setup(k, m, 5.0f));
  bt_stop pois[3], out[3]; uint32_t n = 0; std::memset(pois, 0, sizeof(pois));
  const bt_xy start = cxy(5, 10, 5), end = cxy(5, 10, 5);
  pois[0].xy = cxy(5, 10, 25); pois[1].xy = cxy(5, 10, 10); pois[2].xy = cxy(5, 10, 18);     // 서쪽에서 동쪽으로 1, 2, 0 순
  for (int i = 0; i < 3; ++i) { pois[i].dwell_min = 5; pois[i].poi = static_cast<uint8_t>(i + 1); }
  bt_budget b = budget();
  CHECK(bt_select_pois(k.ctx, pois, 3, start, end, &b, out, &n) == BT_ERR_NOT_READY);
  CHECK(bt_costmap_build(k.ctx, 5.0) == BT_OK);
  CHECK(bt_select_pois(k.ctx, pois, 3, start, end, &b, out, &n) == BT_OK && n == 3);          // 시간 제한 없음 → 전부, 가장 짧은 순서
  CHECK((out[0].poi == 2 && out[1].poi == 3 && out[2].poi == 1) || (out[0].poi == 1 && out[1].poi == 3 && out[2].poi == 2));
  b.time_s = 12 * 60.0;                                                                       // 12분: 가까운 하나만 다녀올 수 있다
  CHECK(bt_select_pois(k.ctx, pois, 3, start, end, &b, out, &n) == BT_OK && n == 1 && out[0].poi == 2);
  b.time_s = 60.0;                                                                            // 1분: 아무 데도 못 간다
  CHECK(bt_select_pois(k.ctx, pois, 3, start, end, &b, out, &n) == BT_OK && n == 0);
  bt_stop many[9]; std::memset(many, 0, sizeof(many));
  CHECK(bt_select_pois(k.ctx, many, 9, start, end, &b, many, &n) == BT_ERR_CAPACITY);
}

static void test_link() {
  bt_config cfg = make_cfg(8, 8, 5.0f, 5.0f);
  cfg.uhf.timeout_ms = 500; cfg.uhf.n_down = 5; cfg.uhf.n_up = 3; cfg.uhf.ewma_alpha = 0.3f; cfg.uhf.loss_down = 0.85f; cfg.uhf.rtt_down_ms = 400.0f;
  cfg.wifi = cfg.uhf; cfg.lost_dp_s = 120.0f; cfg.hb_hz = 1.0f;
  Core k; CHECK(k.create(cfg));
  bt_link L; std::memset(&L, 0, sizeof(L));
  uint8_t changed = 0, lost = 0;
  uint32_t seq = 0;
  // 한 초: 하트비트 송신 → (응답) → 틱. 두 채널에 같은 번호를 쓴다
  auto second = [&](double t0, bool uhf_ack, bool wifi_ack, uint8_t* any_changed, uint8_t* any_lost) {
    seq += 1;
    for (uint8_t ch = 0; ch < 2; ++ch) {
      bt_link_in in{t0, ch, BT_NET_SENT, seq};
      CHECK(bt_link_step(k.ctx, &L, &in, &changed, &lost) == BT_OK); *any_changed |= changed;
      if (ch == BT_CH_UHF ? uhf_ack : wifi_ack) {
        bt_link_in ack{t0 + 50.0, ch, BT_NET_ACK, seq};
        CHECK(bt_link_step(k.ctx, &L, &ack, &changed, &lost) == BT_OK); *any_changed |= changed;
      }
    }
    bt_link_in tick{t0 + 600.0, 0, BT_NET_TICK, 0};
    CHECK(bt_link_step(k.ctx, &L, &tick, &changed, &lost) == BT_OK); *any_changed |= changed; *any_lost |= lost;
  };
  double t = 0.0; uint8_t ch_any = 0, lost_any = 0;
  for (int i = 0; i < 10; ++i, t += 1000.0) second(t, true, true, &ch_any, &lost_any);       // 정상 10초
  CHECK(L.mode == BT_LINK_FULL && L.uhf.state == BT_CHS_UP && ch_any == 0);
  NEAR(L.uhf.rtt_ms, 50.0, 1e-3);
  for (int i = 0; i < 4; ++i, t += 1000.0) second(t, false, true, &ch_any, &lost_any);       // 4번 놓침: 아직 FULL
  CHECK(L.mode == BT_LINK_FULL && L.uhf.miss_run == 4 && ch_any == 0);
  second(t, true, true, &ch_any, &lost_any); t += 1000.0;                                     // 응답 하나가 끼면 다시 센다
  CHECK(L.uhf.miss_run == 0 && L.mode == BT_LINK_FULL);
  for (int i = 0; i < 3; ++i, t += 1000.0) second(t, false, true, &ch_any, &lost_any);       // 다시 3번: 아직 FULL
  CHECK(L.mode == BT_LINK_FULL && ch_any == 0);
  // (9번 중 8번을 놓치면 연속 5번이 아니어도 손실률 임계 0.85로 끊김 판정이 난다 — S4 §3의 loss_down)
  for (int i = 0; i < 12; ++i, t += 1000.0) second(t, true, true, &ch_any, &lost_any);       // 손실률이 가라앉을 때까지 정상
  CHECK(L.mode == BT_LINK_FULL && ch_any == 0 && L.uhf.loss < 0.05f);
  for (int i = 0; i < 4; ++i, t += 1000.0) second(t, false, true, &ch_any, &lost_any);
  CHECK(L.mode == BT_LINK_FULL && ch_any == 0);
  const double t_first_miss = t - 4000.0;
  second(t, false, true, &ch_any, &lost_any); t += 1000.0;                                    // 5번째 miss가 타임아웃된 틱에 LOCAL
  CHECK(L.mode == BT_LINK_LOCAL && L.uhf.state == BT_CHS_DOWN && ch_any == 1);
  CHECK(L.uhf.down_since - t_first_miss <= 5500.0);
  CHECK(L.wifi.state == BT_CHS_UP);                                                           // Wi-Fi는 그대로
  // 두절이 lost_dp_s를 넘기면 한 번만 알린다
  int fired = 0;
  for (int i = 0; i < 130; ++i, t += 1000.0) { uint8_t c2 = 0, l2 = 0; second(t, false, true, &c2, &l2); fired += l2; }
  CHECK(fired == 1 && L.mode == BT_LINK_LOCAL);
  // 복구는 연속 n_up번 응답이 있어야 한다
  ch_any = 0;
  second(t, true, true, &ch_any, &lost_any); t += 1000.0;
  second(t, true, true, &ch_any, &lost_any); t += 1000.0;
  CHECK(L.mode == BT_LINK_LOCAL && ch_any == 0);
  second(t, true, true, &ch_any, &lost_any); t += 1000.0;
  CHECK(L.mode == BT_LINK_FULL && L.uhf.state == BT_CHS_UP && ch_any == 1);
  // Wi-Fi만 끊겨도 모드는 그대로
  ch_any = 0;
  for (int i = 0; i < 8; ++i, t += 1000.0) second(t, true, false, &ch_any, &lost_any);
  CHECK(L.wifi.state == BT_CHS_DOWN && L.mode == BT_LINK_FULL && ch_any == 0);
  // 송신 오류는 즉시 DOWN
  bt_link_in err{t, BT_CH_UHF, BT_NET_SEND_ERROR, 0};
  CHECK(bt_link_step(k.ctx, &L, &err, &changed, &lost) == BT_OK && changed == 1 && L.mode == BT_LINK_LOCAL);
  // 틱이 밀린 구간의 miss는 세지 않는다
  bt_link L2; std::memset(&L2, 0, sizeof(L2));
  bt_link_in s1{0.0, BT_CH_UHF, BT_NET_SENT, 1}, late{30000.0, 0, BT_NET_TICK, 0};
  CHECK(bt_link_step(k.ctx, &L2, &s1, &changed, &lost) == BT_OK && bt_link_step(k.ctx, &L2, &late, &changed, &lost) == BT_OK);
  CHECK(L2.uhf.miss_run == 0 && L2.uhf.pending == 0);
}

// 과학 격자 16×16 @ 20 m (비용 격자 64×64 @ 5 m와 같은 범위)
struct Sci {
  static constexpr uint32_t N = 16;
  std::vector<float> mu0, var0; std::vector<uint8_t> units;
  Sci() : mu0(N * N, 0.2f), var0(N * N, 0.04f), units(N * N) {
    for (uint32_t r = 0; r < N; ++r) for (uint32_t c = 0; c < N; ++c) units[r * N + c] = c < 8 ? 1 : 2;
  }
};
static bt_xy sxy(int row, int col) { return bt_xy{(col + 0.5) * 20.0, -(row + 0.5) * 20.0}; }

static bt_config sci_cfg(uint8_t node, uint8_t mode) {
  bt_config c = make_cfg(Mini::H, Mini::W, 5.0f, 5.0f);
  c.node = node; c.options_mode = mode; c.options_min = 2;
  c.science_grid.h = Sci::N; c.science_grid.w = Sci::N; c.science_grid.res_m = 20.0f;
  c.grade_bins[0] = 0.3f; c.grade_bins[1] = 0.6f;
  c.l0_m = 50; c.aniso_ratio = 4; c.exposure_slope_ref_deg = 20; c.obs_noise = 0.05f; c.unconfirmed_factor = 4;
  c.tau_s = 1800; c.r_obs_m = 20; c.w_transit = 0.25f; c.A_ref_m2 = 400; c.r_plan = 0.05f; c.touch_eps = 0.05f; c.var_floor = 0.0001f;
  c.eps_fork = 0.10f; c.cooldown_s = 120; c.stay_max_min = 20; c.stay_buffer_min = 2; c.hyp_snap_m = 50;
  c.prec_time_min = 1; c.prec_max_slope_deg = 1; c.prec_dose_uSv = 0.1f; c.prec_value = 0.1f; c.prec_value_var = 0.01f;
  c.prec_info_gain = 0.1f; c.prec_nlt_margin_min = 1; c.prec_comm_loss_min = 1;
  c.dust_tau_warn = 1.0f;
  return c;
}
static bool sci_setup(Core& k, const Mini& m, const Sci& s, uint8_t node, uint8_t mode) {
  if (!k.create(sci_cfg(node, mode))) return false;
  bt_raster rs = f32_raster(m.slope, Mini::H, Mini::W, 5.0f), re = f32_raster(m.elev, Mini::H, Mini::W, 5.0f),
            rr = f32_raster(m.rough, Mini::H, Mini::W, 5.0f),
            rm = f32_raster(s.mu0, Sci::N, Sci::N, 20.0f), rv = f32_raster(s.var0, Sci::N, Sci::N, 20.0f);
  bt_raster ru; std::memset(&ru, 0, sizeof(ru));
  ru.data = s.units.data(); ru.h = Sci::N; ru.w = Sci::N; ru.res_m = 20.0f; ru.dtype = BT_DT_U8; ru.planes = 1; ru.scale = 1.0f;
  bt_env e = calm_env();
  return bt_set_layer(k.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ELEV, &re) == BT_OK &&
         bt_set_layer(k.ctx, BT_LAYER_ROUGHNESS, &rr) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_MU0, &rm) == BT_OK &&
         bt_set_layer(k.ctx, BT_LAYER_VAR0, &rv) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_UNITS, &ru) == BT_OK &&
         bt_set_env(k.ctx, &e) == BT_OK;
}
static bt_event obs_ev(bt_xy p, double ts, bool found, bool confirmed) {
  bt_event e = ev(BT_EV_OBS, ts, p.x, p.y);
  e.flags = static_cast<uint8_t>((found ? BT_EVF_FOUND : 0) | (confirmed ? BT_EVF_CONFIRMED : 0));
  return e;
}
static bt_event hyp_ev(bt_xy anchor, double ts, uint8_t rule, float dir, float extent, float conf, uint16_t seq, bool approved) {
  bt_event e = ev(BT_EV_HYP, ts, anchor.x, anchor.y);
  e.rule = rule; e.a = dir; e.b = extent; e.c = conf; e.seq = seq; e.flags = approved ? BT_EVF_APPROVED : 0;
  return e;
}
static float conf_after(const Mini& m, const Sci& s, bool before, bool found, bool confirmed, bt_xy where) {
  Core k; if (!sci_setup(k, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE)) return -1.0f;
  bt_event o = obs_ev(where, 20.0, found, confirmed);
  bt_event h = hyp_ev(sxy(8, 4), 10.0, BT_RULE_PROXIMITY, 0.0f, 100.0f, 0.5f, 1, true);
  if (before) { bt_log_append(k.ctx, &o); bt_log_append(k.ctx, &h); } else { bt_log_append(k.ctx, &h); bt_log_append(k.ctx, &o); }
  if (bt_science_update(k.ctx, 30.0) != BT_OK) return -1.0f;
  bt_science_view v;
  if (bt_science_get_view(k.ctx, &v) != BT_OK || v.n_hyps != 1) return -1.0f;
  if (v.hyps[0].conf_chosen != 0.5f) return -1.0f;        // 처음 고른 값은 바뀌지 않는다
  return v.hyps[0].conf_now;
}

static std::vector<float> hyp_delta(bt_ctx* ctx, uint32_t k) {
  std::vector<float> v(Sci::N * Sci::N);
  bt_raster r; std::memset(&r, 0, sizeof(r)); r.data = v.data(); r.h = Sci::N; r.w = Sci::N;
  if (bt_science_hyp_delta(ctx, k, &r) != BT_OK) v.clear();
  return v;
}

static void test_science() {
  Mini m; Sci s;
  Core k; CHECK(sci_setup(k, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  bt_path_value pv;
  CHECK(bt_path_evaluate(k.ctx, nullptr, nullptr, 0, &pv) == BT_ERR_NOT_READY);
  CHECK(bt_science_update(k.ctx, 0.0) == BT_OK);
  bt_science_view v;
  CHECK(bt_science_get_view(k.ctx, &v) == BT_OK && v.n_hyps == 0 && v.mu_base.h == 16 && v.n_traces == 0);
  const float* mu = static_cast<const float*>(v.mu_base.data);
  const float* var = static_cast<const float*>(v.var.data);
  const uint8_t* live = static_cast<const uint8_t*>(v.live_touched.data);
  bool prior_same = true;
  for (uint32_t i = 0; i < 256; ++i) if (mu[i] != 0.2f || var[i] != 0.04f || live[i]) prior_same = false;
  CHECK(prior_same);                                        // 이벤트 0개 → prior 그대로
  const uint64_t d0 = bt_science_digest(k.ctx);

  // 발견: 그 자리의 값이 오르고 분산이 준다. 멀수록 덜 움직인다
  bt_event o1 = obs_ev(sxy(8, 8), 100.0, true, true);
  CHECK(bt_log_append(k.ctx, &o1) == BT_OK && bt_science_update(k.ctx, 100.0) == BT_OK);
  CHECK(mu[8 * 16 + 8] > 0.5f && var[8 * 16 + 8] < 0.03f && live[8 * 16 + 8] == 1);
  CHECK(mu[8 * 16 + 10] > 0.2f && mu[8 * 16 + 10] < mu[8 * 16 + 8] && var[8 * 16 + 10] > var[8 * 16 + 8]);
  CHECK(mu[0] == 0.2f && live[0] == 0);
  CHECK(bt_science_digest(k.ctx) != d0);
  // 없음: 값이 내려간다. 확인 안 된 관측은 덜 움직인다
  Core k2, k3; CHECK(sci_setup(k2, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE) && sci_setup(k3, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  bt_event o2 = obs_ev(sxy(8, 8), 100.0, false, true), o3 = obs_ev(sxy(8, 8), 100.0, false, false);
  CHECK(bt_log_append(k2.ctx, &o2) == BT_OK && bt_science_update(k2.ctx, 100.0) == BT_OK);
  CHECK(bt_log_append(k3.ctx, &o3) == BT_OK && bt_science_update(k3.ctx, 100.0) == BT_OK);
  bt_science_view v2, v3; CHECK(bt_science_get_view(k2.ctx, &v2) == BT_OK && bt_science_get_view(k3.ctx, &v3) == BT_OK);
  const float m2 = static_cast<const float*>(v2.mu_base.data)[8 * 16 + 8], m3 = static_cast<const float*>(v3.mu_base.data)[8 * 16 + 8];
  CHECK(m2 < 0.2f && m3 < 0.2f && m3 > m2);

  // 확인된 관측이 가설의 확신을 고친다 (S3a §5.2a): 틀리면 0.2, 맞으면 0.6이 되는 칸
  Sci sc;
  const double w = std::exp(-0.5 * (60.0 * 60.0) / (100.0 * 100.0));   // 닻에서 60 m, 범위 100 m
  sc.mu0[8 * 16 + 4] = static_cast<float>(0.2 + 0.4 / w);
  NEAR(conf_after(m, sc, false, true, true, sxy(8, 7)), 0.75, 1e-3);    // 발견
  NEAR(conf_after(m, sc, false, false, true, sxy(8, 7)), 1.0 / 3.0, 1e-3);   // 없음
  NEAR(conf_after(m, sc, false, true, false, sxy(8, 7)), 0.5, 1e-6);    // 확인 안 된 관측
  NEAR(conf_after(m, sc, true, true, true, sxy(8, 7)), 0.5, 1e-6);      // 가설보다 앞선 관측
  sc.mu0[0 * 16 + 15] = 0.9f;                                           // 닻보다 값이 높은 칸: 가설이 더할 것이 없다
  NEAR(conf_after(m, sc, false, true, true, sxy(0, 15)), 0.5, 1e-6);    // 가설이 영향을 주지 않는 자리

  // 가설: 승인 안 된 것은 무시, 철회하면 가설이 없던 지도로 돌아간다
  Core a, b, w0; CHECK(sci_setup(a, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE) && sci_setup(b, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE) && sci_setup(w0, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  bt_event oa = obs_ev(sxy(8, 4), 10.0, true, true), ob = obs_ev(sxy(3, 3), 30.0, false, false);
  bt_event hy = hyp_ev(sxy(8, 4), 20.0, BT_RULE_STRATA_CONTINUITY, 90.0f, 100.0f, 0.5f, 1, true);
  bt_event un = hyp_ev(sxy(8, 4), 20.0, BT_RULE_STRATA_CONTINUITY, 90.0f, 100.0f, 0.5f, 2, false);
  bt_event e1 = oa, e2 = ob;
  CHECK(bt_log_append(a.ctx, &e1) == BT_OK && bt_log_append(a.ctx, &e2) == BT_OK && bt_science_update(a.ctx, 50.0) == BT_OK);
  const uint64_t d_obs = bt_science_digest(a.ctx);
  e1 = oa; e2 = ob;
  CHECK(bt_log_append(b.ctx, &e1) == BT_OK && bt_log_append(b.ctx, &un) == BT_OK && bt_log_append(b.ctx, &e2) == BT_OK);
  CHECK(bt_science_update(b.ctx, 50.0) == BT_OK && bt_science_digest(b.ctx) == d_obs);
  e1 = oa; e2 = ob;
  CHECK(bt_log_append(w0.ctx, &e1) == BT_OK && bt_log_append(w0.ctx, &hy) == BT_OK && bt_log_append(w0.ctx, &e2) == BT_OK);
  CHECK(bt_science_update(w0.ctx, 50.0) == BT_OK && bt_science_digest(w0.ctx) != d_obs);
  bt_science_view vh; CHECK(bt_science_get_view(w0.ctx, &vh) == BT_OK && vh.n_hyps == 1);
  const std::vector<float> dl = hyp_delta(w0.ctx, 0);
  CHECK(dl.size() == 256 && dl[8 * 16 + 7] > 0.0f && dl[8 * 16 + 7] > dl[5 * 16 + 4]);      // 층서연속: 장축(동쪽) 가중 > 수직 방향
  NEAR(static_cast<const float*>(vh.add_full.data)[8 * 16 + 7], dl[8 * 16 + 7], 1e-7);      // 가설이 하나면 합 = 그 가설의 몫
  NEAR(static_cast<const float*>(vh.add_expected.data)[8 * 16 + 7], 0.5f * dl[8 * 16 + 7], 1e-7);
  // 경로 가치: 가설이 끼면 lo < mean < hi
  bt_stop stp; std::memset(&stp, 0, sizeof(stp)); stp.xy = sxy(8, 7); stp.poi = BT_POI_NONE;
  CHECK(bt_path_evaluate(w0.ctx, nullptr, &stp, 1, &pv) == BT_OK);
  CHECK(pv.value_lo < pv.value_mean && pv.value_mean < pv.value_hi && pv.hyp_seq[0] == BT_HYP_KEY(BT_NODE_SUIT_A, 1) && pv.prior_only == 0);
  CHECK(bt_path_evaluate(a.ctx, nullptr, &stp, 1, &pv) == BT_OK && pv.value_lo == pv.value_hi && pv.hyp_seq[0] == 0);
  bt_event wd = hyp_ev(sxy(8, 4), 60.0, BT_RULE_STRATA_CONTINUITY, 90.0f, 100.0f, 0.5f, 3, false);
  wd.aux = BT_HYP_KEY(BT_NODE_SUIT_A, 1);                                // 철회
  CHECK(bt_log_append(w0.ctx, &wd) == BT_OK && bt_science_update(w0.ctx, 50.0) == BT_OK);
  CHECK(bt_science_digest(w0.ctx) == d_obs);
  const bt_event* lv; uint32_t ln; CHECK(bt_log_view(w0.ctx, &lv, &ln) == BT_OK && ln == 4);   // 이전 가설 이벤트는 지워지지 않는다

  // 규칙의 모양: 근접 = 방향 불변, 단위 경계 = 다른 단위 0, 침식 노출 = 평지 0
  Core r1; CHECK(sci_setup(r1, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  bt_event oo = obs_ev(sxy(8, 6), 1.0, true, true);
  bt_event hp = hyp_ev(sxy(8, 6), 2.0, BT_RULE_PROXIMITY, 0.0f, 100.0f, 0.5f, 1, true);
  bt_event hu = hyp_ev(sxy(8, 6), 3.0, BT_RULE_UNIT_BOUNDARY, 0.0f, 100.0f, 0.5f, 2, true);
  CHECK(bt_log_append(r1.ctx, &oo) == BT_OK && bt_log_append(r1.ctx, &hp) == BT_OK && bt_log_append(r1.ctx, &hu) == BT_OK);
  CHECK(bt_science_update(r1.ctx, 5.0) == BT_OK && bt_science_get_view(r1.ctx, &vh) == BT_OK && vh.n_hyps == 2);
  const std::vector<float> dp = hyp_delta(r1.ctx, 0), du = hyp_delta(r1.ctx, 1);
  NEAR(dp[8 * 16 + 9], dp[11 * 16 + 6], 1e-6); NEAR(dp[8 * 16 + 9], dp[5 * 16 + 6], 1e-6);
  CHECK(du[8 * 16 + 4] > 0.0f && du[8 * 16 + 9] == 0.0f);               // col 8부터 다른 단위
  NEAR(static_cast<const float*>(vh.add_full.data)[8 * 16 + 4], dp[8 * 16 + 4] + du[8 * 16 + 4], 1e-6);   // 두 가설이 같은 칸을 올리면 더한다
  bt_stop two; std::memset(&two, 0, sizeof(two)); two.xy = sxy(8, 4); two.poi = BT_POI_NONE;
  CHECK(bt_path_evaluate(r1.ctx, nullptr, &two, 1, &pv) == BT_OK && pv.hyp_seq[0] == BT_HYP_KEY(BT_NODE_SUIT_A, 1) && pv.hyp_seq[1] == BT_HYP_KEY(BT_NODE_SUIT_A, 2));

  // 같은 이벤트를 다른 순서로 병합해도 같은 지도 (V-7)
  const bt_event* av; uint32_t an; CHECK(bt_log_view(w0.ctx, &av, &an) == BT_OK);
  std::vector<bt_event> evs(av, av + an);
  const uint64_t d_ref = bt_science_digest(w0.ctx);
  uint32_t seed = 17;
  for (int it = 0; it < 10; ++it) {
    for (size_t i = evs.size(); i > 1; --i) { seed = seed * 1664525u + 1013904223u; std::swap(evs[i - 1], evs[(seed >> 8) % i]); }
    Core x; CHECK(sci_setup(x, m, s, BT_NODE_ROVER, BT_OPTMODE_PARETO));
    uint32_t fresh; CHECK(bt_log_merge(x.ctx, evs.data(), an, &fresh) == BT_OK && fresh == an);
    CHECK(bt_science_update(x.ctx, 50.0) == BT_OK && bt_science_digest(x.ctx) == d_ref && bt_log_digest(x.ctx) == bt_log_digest(w0.ctx));
  }

  // 주의 흔적: 30분 뒤 사라지고, 발견이 난 자리의 흔적은 남는다
  Core t; CHECK(sci_setup(t, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  bt_event tr1 = ev(BT_EV_TRACE, 0.0, sxy(2, 2).x, sxy(2, 2).y); tr1.kind = BT_TRACE_PHOTO;
  bt_event tr2 = ev(BT_EV_TRACE, 0.0, sxy(12, 12).x, sxy(12, 12).y); tr2.kind = BT_TRACE_MENTION;
  bt_event fo = obs_ev(sxy(12, 12), 600.0, true, false);
  CHECK(bt_log_append(t.ctx, &tr1) == BT_OK && bt_log_append(t.ctx, &tr2) == BT_OK && bt_log_append(t.ctx, &fo) == BT_OK);
  CHECK(bt_science_update(t.ctx, 900.0) == BT_OK && bt_science_get_view(t.ctx, &v) == BT_OK && v.n_traces == 2);
  CHECK(v.traces[0].alive == 1 && v.traces[0].kept == 0); NEAR(v.traces[0].fade, 0.5, 1e-6);
  CHECK(v.traces[1].alive == 1 && v.traces[1].kept == 1); NEAR(v.traces[1].fade, 1.0 - 600.0 / 1800.0, 1e-6);
  stp.xy = sxy(2, 2);
  CHECK(bt_path_evaluate(t.ctx, nullptr, &stp, 1, &pv) == BT_OK && pv.explore_count == 1);
  CHECK(bt_science_update(t.ctx, 2000.0) == BT_OK && bt_science_get_view(t.ctx, &v) == BT_OK);
  CHECK(v.traces[0].alive == 0 && v.traces[1].alive == 1);
  CHECK(bt_path_evaluate(t.ctx, nullptr, &stp, 1, &pv) == BT_OK && pv.explore_count == 0);
}

static void test_decide() {
  Mini m; Sci s;
  Core k; CHECK(sci_setup(k, m, s, BT_NODE_ROVER, BT_OPTMODE_PARETO));
  CHECK(bt_costmap_build(k.ctx, 5.0) == BT_OK);
  const bt_xy rover = cxy(5, 40, 58);
  CHECK(bt_cost_to_go(k.ctx, rover, BT_WALK_RETURN, BT_FIELD_ROVER_RETURN) == BT_OK);
  bt_state st; std::memset(&st, 0, sizeof(st)); st.pos = cxy(5, 10, 40); st.t = 3600.0; st.node = BT_NODE_SUIT_A;
  bt_stop plan[2]; std::memset(plan, 0, sizeof(plan));
  plan[0].xy = cxy(5, 20, 50); plan[0].dwell_min = 10; plan[0].purpose = BT_STOP_POI; plan[0].poi = 1;
  plan[1].xy = cxy(5, 45, 45); plan[1].dwell_min = 10; plan[1].purpose = BT_STOP_POI; plan[1].poi = 2;
  bt_trigger tr[8]; uint32_t nt = 0;
  bt_trigger_in in; std::memset(&in, 0, sizeof(in));
  bt_decision d, d2;

  // 관측이 지도를 바꿨다 → FORK(원인 = 그 관측)
  bt_event o = obs_ev(st.pos, 3590.0, true, true); o.node = BT_NODE_SUIT_A; o.lts = 1;
  uint32_t fresh; CHECK(bt_log_merge(k.ctx, &o, 1, &fresh) == BT_OK && fresh == 1);
  bt_trigger f0; std::memset(&f0, 0, sizeof(f0)); f0.kind = BT_TRIG_FORK; f0.cause_kind = BT_CAUSE_OBS; f0.cause_lts = 1; f0.cause_node = BT_NODE_SUIT_A;
  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &f0, &d) == BT_ERR_NOT_READY);      // 지도를 다시 계산하기 전
  CHECK(bt_science_update(k.ctx, st.t) == BT_OK);
  in.changed[0].lts = 1; in.changed[0].node = BT_NODE_SUIT_A; in.n_changed = 1;
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 1);
  CHECK(tr[0].kind == BT_TRIG_FORK && tr[0].cause_kind == BT_CAUSE_OBS && tr[0].cause_lts == 1);

  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &tr[0], &d) == BT_OK);
  CHECK(d.n_options >= 2 && d.n_options <= 3 && d.forced == 0 && d.node == BT_NODE_ROVER && d.notices == 0);
  int n_hyp = 0;
  std::vector<bt_cell> buf(8192);
  for (uint32_t i = 0; i < d.n_options; ++i) {
    const bt_option& op = d.options[i];
    CHECK(op.label == i && op.nlt_margin_min >= 0.0f && op.digest == bt_option_digest(&op));   // 라벨은 생성 순, 출발 한계 위반 0
    CHECK(op.value_lo <= op.value_mean && op.value_mean <= op.value_hi);
    if (op.label_key == BT_LABEL_HYP_TARGET) n_hyp++;
    bt_path p; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 8192;
    CHECK(bt_decision_path(k.ctx, &d, i, &p) == BT_OK && p.len == op.path_len && violations(m, p) == 0);
  }
  CHECK(n_hyp == 0 && d.options[0].label_key == BT_LABEL_CONTINUE_PLAN);
  CHECK(d.options[0].time_min >= 20.0f);                                               // 걷는 시간 + 체류 20분
  bt_option cands[BT_MAX_CANDIDATES]; uint32_t nc = 0;
  CHECK(bt_decision_candidates(k.ctx, &d, cands, BT_MAX_CANDIDATES, &nc) == BT_OK && nc >= d.n_options && nc <= BT_MAX_CANDIDATES);
  CHECK(cands[nc - 1].label_key == BT_LABEL_RETURN_ROVER);

  // 같은 입력으로 두 번 → 같은 다이제스트 (V-7)
  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &tr[0], &d2) == BT_OK);
  CHECK(d2.digest == d.digest && d2.inputs_digest == d.inputs_digest && d2.seq != d.seq);
  CHECK(bt_decision_digest(&d2) == d2.digest);

  // 같은 원인은 열려 있는 동안, 그리고 닫은 뒤 cooldown 동안 다시 내지 않는다. 새 원인은 바로 낸다
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 0);
  CHECK(bt_decision_close(k.ctx, d2.seq) == BT_OK);
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 0);
  st.t += 200.0;
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 1);
  st.t -= 200.0;

  // 가설을 승인하면 가설 옵션이 정확히 1개 들어간다 (R-22)
  bt_event h = hyp_ev(st.pos, 3595.0, BT_RULE_STRATA_CONTINUITY, 180.0f, 100.0f, 0.5f, 1, true); h.node = BT_NODE_SUIT_A; h.lts = 2;
  CHECK(bt_log_merge(k.ctx, &h, 1, &fresh) == BT_OK && bt_science_update(k.ctx, st.t) == BT_OK);
  in.changed[0].lts = 2;
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 1 && tr[0].cause_kind == BT_CAUSE_HYP);
  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &tr[0], &d) == BT_OK);
  n_hyp = 0;
  for (uint32_t i = 0; i < d.n_options; ++i) {
    const bt_option& op = d.options[i];
    CHECK(op.nlt_margin_min >= 0.0f);
    if (op.label_key != BT_LABEL_HYP_TARGET) { CHECK(op.value_lo == op.value_hi && op.value_lo == op.value_mean && op.hyp_seq[0] == 0); continue; }   // 범위는 가설 옵션만
    n_hyp++;
    CHECK((op.flags & BT_OPTF_FROM_HYPOTHESIS) && op.stops[0].purpose == BT_STOP_HYP_TARGET && op.hyp_seq[0] == BT_HYP_KEY(BT_NODE_SUIT_A, 1));
    CHECK(op.value_hi > op.value_lo);
  }
  CHECK(n_hyp == 1 && d.n_options == 3);

  // 그 가설 옵션을 고른 뒤(계획이 이미 가설 목표를 들른다): "가설 목표로"를 또 만들지 않는다. 닿을 수 없다는 알림도 없다
  {
    bt_option hopt; std::memset(&hopt, 0, sizeof(hopt));
    for (uint32_t i = 0; i < d.n_options; ++i) if (d.options[i].label_key == BT_LABEL_HYP_TARGET) hopt = d.options[i];
    bt_trigger_in in3; std::memset(&in3, 0, sizeof(in3)); in3.user_request = 0;
    bt_trigger t3; std::memset(&t3, 0, sizeof(t3)); t3.kind = BT_TRIG_ENV; t3.cause_kind = BT_CAUSE_SHADOW;
    bt_decision d3;
    CHECK(bt_decide(k.ctx, &st, hopt.stops, hopt.n_stops, nullptr, 0, &t3, &d3) == BT_OK);
    uint32_t again = 0;
    for (uint32_t i = 0; i < d3.n_options; ++i) if (d3.options[i].label_key == BT_LABEL_HYP_TARGET) again++;
    CHECK(again == 0 && (d3.notices & BT_NOTICE_HYP_UNREACHABLE) == 0);
    CHECK(bt_decision_close(k.ctx, d3.seq) == BT_OK);
  }

  // 철회 뒤: 되돌리기 옵션이 나란히 나온다 (prev_plan을 넘겼을 때만)
  bt_event wd = hyp_ev(st.pos, 3598.0, BT_RULE_STRATA_CONTINUITY, 180.0f, 100.0f, 0.5f, 2, false); wd.node = BT_NODE_SUIT_A; wd.lts = 3;
  wd.aux = BT_HYP_KEY(BT_NODE_SUIT_A, 1);
  CHECK(bt_log_merge(k.ctx, &wd, 1, &fresh) == BT_OK && bt_science_update(k.ctx, st.t) == BT_OK);
  in.changed[0].lts = 3;
  CHECK(bt_triggers(k.ctx, &st, &st, &in, tr, 8, &nt) == BT_OK && nt == 1 && tr[0].cause_kind == BT_CAUSE_HYP && tr[0].cause_lts == 3);
  CHECK(bt_decide(k.ctx, &st, plan, 1, plan, 2, &tr[0], &d) == BT_OK);
  bool has_restore = false; n_hyp = 0;
  for (uint32_t i = 0; i < d.n_options; ++i) { if (d.options[i].label_key == BT_LABEL_RESTORE_PLAN) has_restore = (d.options[i].n_stops == 2); if (d.options[i].label_key == BT_LABEL_HYP_TARGET) n_hyp++; }
  CHECK(has_restore && n_hyp == 0);

  // 안전·귀환 요청 → 귀환 옵션 하나
  bt_trigger_in in2; std::memset(&in2, 0, sizeof(in2)); in2.user_request = 1;
  CHECK(bt_triggers(k.ctx, &st, &st, &in2, tr, 8, &nt) == BT_OK && nt == 1 && tr[0].kind == BT_TRIG_USER_REQUEST && tr[0].forced == 0);
  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &tr[0], &d) == BT_OK);
  CHECK(d.n_options == 1 && d.options[0].kind == BT_OPT_RETURN && d.options[0].label_key == BT_LABEL_RETURN_ROVER && d.forced == 0);
  CHECK(d.options[0].stops[0].purpose == BT_STOP_ROVER && !(d.options[0].flags & BT_OPTF_LATE));
  bt_path rp; std::memset(&rp, 0, sizeof(rp)); rp.cells = buf.data(); rp.cap = 8192;
  CHECK(bt_decision_path(k.ctx, &d, 0, &rp) == BT_OK && rp.cells[rp.len - 1].row == 40 && rp.cells[rp.len - 1].col == 58);

  // 안전 트리거가 있으면 그것만 나온다
  std::memset(&in2, 0, sizeof(in2)); in2.user_request = 1; in2.n_safety = 2;
  in2.safety[0].kind = BT_TRIG_ENV; in2.safety[0].cause_kind = BT_CAUSE_SUNSET;
  in2.safety[1].kind = BT_TRIG_SAFETY; in2.safety[1].forced = 1; in2.safety[1].cause_kind = BT_CAUSE_NLT;
  CHECK(bt_triggers(k.ctx, &st, &st, &in2, tr, 8, &nt) == BT_OK && nt == 1 && tr[0].kind == BT_TRIG_SAFETY && tr[0].forced == 1);

  // 출발 한계를 이미 넘겼다 → "늦음" 귀환 하나를 강제로
  bt_state late = st; late.t = 8 * 3600.0 - 60.0;
  CHECK(bt_decide(k.ctx, &late, plan, 2, nullptr, 0, &f0, &d) == BT_OK);
  CHECK(d.n_options == 1 && d.forced == 1 && (d.options[0].flags & BT_OPTF_LATE) && d.options[0].nlt_margin_min < 0.0f);
  // 로버까지 길이 없다 → 옵션 없이 알림만
  bt_state trapped = st; trapped.pos = bt_xy{-999.0, 999.0};
  CHECK(bt_decide(k.ctx, &trapped, nullptr, 0, nullptr, 0, &tr[0], &d) == BT_OK);
  CHECK(d.n_options == 0 && (d.notices & BT_NOTICE_NO_FEASIBLE_RETURN));

  // 출발 한계가 빡빡하면 위반하는 옵션은 만들지 않는다
  bt_env e = calm_env(); e.t_sunset_s = st.t + 30 * 60.0 + 16 * 60.0;   // 여유 약 16분 − 귀환 시간
  CHECK(bt_set_env(k.ctx, &e) == BT_OK);
  CHECK(bt_decide(k.ctx, &st, plan, 2, nullptr, 0, &f0, &d) == BT_OK && d.n_options >= 1);
  for (uint32_t i = 0; i < d.n_options; ++i) CHECK(d.options[i].nlt_margin_min >= 0.0f && d.options[i].nlt_binding == BT_BIND_SUNSET);
  bt_nlt nl; bt_path one; std::memset(&one, 0, sizeof(one));
  CHECK(bt_nlt_feasible(k.ctx, &one, plan, 2, &st, &nl) == BT_OK && nl.slack_min < 0.0f);   // 제자리에서 20분 머물면 넘긴다

  // 환경: 그림자 구간·먼지가 바뀌면 ENV
  Core kk; bt_config cc = sci_cfg(BT_NODE_ROVER, BT_OPTMODE_PARETO); cc.shadow_bins = 0;
  CHECK(sci_setup(kk, m, s, BT_NODE_ROVER, BT_OPTMODE_PARETO));
  std::memset(&in2, 0, sizeof(in2));
  CHECK(bt_triggers(kk.ctx, &st, &st, &in2, tr, 8, &nt) == BT_OK && nt == 0);
  e = calm_env(); e.tau_dust = 1.5;
  CHECK(bt_set_env(kk.ctx, &e) == BT_OK && bt_triggers(kk.ctx, &st, &st, &in2, tr, 8, &nt) == BT_OK);
  CHECK(nt == 1 && tr[0].kind == BT_TRIG_ENV && tr[0].cause_kind == BT_CAUSE_DUST);
  CHECK(bt_triggers(kk.ctx, &st, &st, &in2, tr, 8, &nt) == BT_OK && nt == 0);              // 넘어가는 순간에만

  // 기기(선택지를 만들지 않는 인스턴스)는 귀환 카드만 낸다
  Core dev; CHECK(sci_setup(dev, m, s, BT_NODE_SUIT_A, BT_OPTMODE_RECEIVE));
  std::vector<float> ft(64 * 64); std::vector<uint8_t> fn(64 * 64);
  bt_raster rt, rn; std::memset(&rt, 0, sizeof(rt)); std::memset(&rn, 0, sizeof(rn));
  rt.data = ft.data(); rt.h = 64; rt.w = 64; rn.data = fn.data(); rn.h = 64; rn.w = 64;
  CHECK(bt_field_copy(k.ctx, BT_FIELD_ROVER_RETURN, &rt, &rn) == BT_OK && bt_set_field(dev.ctx, BT_FIELD_ROVER_RETURN, &rt, &rn) == BT_OK);
  CHECK(bt_decide(dev.ctx, &st, plan, 2, nullptr, 0, &f0, &d) == BT_ERR_ARG);
  bt_trigger sf; std::memset(&sf, 0, sizeof(sf)); sf.kind = BT_TRIG_SAFETY; sf.forced = 1; sf.cause_kind = BT_CAUSE_NLT;
  CHECK(bt_decide(dev.ctx, &st, plan, 2, nullptr, 0, &sf, &d) == BT_OK);
  CHECK(d.n_options == 1 && d.forced == 1 && d.options[0].kind == BT_OPT_RETURN && d.node == BT_NODE_SUIT_A);
  CHECK(d.options[0].time_min > 0.0f);
}

// 탐색 창: 재계획 반경 밖의 목표는 창 안에서 가장 가까운 칸까지만 푼다
static void test_window() {
  Mini m;
  bt_config cfg = make_cfg(Mini::H, Mini::W, 5.0f, 5.0f);
  cfg.replan_radius_m = 60.0f;                       // 창 = 25×25칸
  Core k; CHECK(k.create(cfg));
  uint64_t small = 0, big = 0; bt_config full = make_cfg(Mini::H, Mini::W, 5.0f, 5.0f);
  CHECK(bt_arena_bytes(&cfg, &small) == BT_OK && bt_arena_bytes(&full, &big) == BT_OK && small < big);   // 탐색 메모리가 준다
  bt_raster rs = f32_raster(m.slope, Mini::H, Mini::W, 5.0f), re = f32_raster(m.elev, Mini::H, Mini::W, 5.0f);
  bt_env e = calm_env();
  CHECK(bt_set_layer(k.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ELEV, &re) == BT_OK);
  CHECK(bt_set_env(k.ctx, &e) == BT_OK && bt_costmap_build(k.ctx, 5.0) == BT_OK);
  std::vector<bt_cell> buf(4096); bt_path p; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 4096;
  bt_budget b = budget();
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 12, 12), &b, &p) == BT_OK && p.complete == 1);   // 창 안의 목표
  CHECK(p.cells[p.len - 1].row == 12 && p.cells[p.len - 1].col == 12);
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p) == BT_PARTIAL && p.complete == 0);   // 창 밖의 목표
  CHECK(p.cells[0].row == 10 && p.cells[0].col == 5 && violations(m, p) == 0);
  const bt_cell end = p.cells[p.len - 1];
  CHECK(end.col > 5 && end.col <= 24 && end.col >= 17);                 // 목표 쪽 창 끝까지 갔다
  // 창 가장자리에 선 시작점 (지도 구석)
  CHECK(bt_plan(k.ctx, cxy(5, 0, 0), cxy(5, 3, 20), &b, &p) == BT_OK && violations(m, p) == 0);
  CHECK(bt_plan(k.ctx, cxy(5, 63, 63), cxy(5, 62, 45), &b, &p) == BT_OK && violations(m, p) == 0);
  // 귀환 필드도 창 안만 채운다
  CHECK(bt_cost_to_go(k.ctx, cxy(5, 40, 58), BT_WALK_RETURN, BT_FIELD_ROVER_RETURN) == BT_OK);
  std::vector<float> ft(64 * 64); std::vector<uint8_t> fn(64 * 64);
  bt_raster rt, rn; std::memset(&rt, 0, sizeof(rt)); std::memset(&rn, 0, sizeof(rn));
  rt.data = ft.data(); rt.h = 64; rt.w = 64; rn.data = fn.data(); rn.h = 64; rn.w = 64;
  CHECK(bt_field_copy(k.ctx, BT_FIELD_ROVER_RETURN, &rt, &rn) == BT_OK);
  CHECK(ft[40 * 64 + 58] == 0.0f && std::isfinite(ft[40 * 64 + 50]) && std::isinf(ft[10 * 64 + 5]));
}

// 거친 격자 먼저: 10 m에서 풀고 경로 주변만 5 m로 다시 푼다
static void test_coarse_to_fine() {
  Mini m;
  bt_config cfg = make_cfg(Mini::H, Mini::W, 5.0f, 5.0f);
  cfg.coarse_first_grid_m = 10.0f; cfg.corridor_m = 20.0f;             // 조각 = 26×26칸 → 여러 구간으로 나뉜다
  Core k; CHECK(k.create(cfg));
  bt_config bad = cfg; bad.coarse_first_grid_m = 12.0f;                 // 레이어 격자의 정수 배가 아님
  uint64_t bytes; CHECK(bt_arena_bytes(&bad, &bytes) == BT_ERR_ARG);
  bt_raster rs = f32_raster(m.slope, Mini::H, Mini::W, 5.0f), re = f32_raster(m.elev, Mini::H, Mini::W, 5.0f),
            rr = f32_raster(m.rough, Mini::H, Mini::W, 5.0f);
  bt_env e = calm_env();
  CHECK(bt_set_layer(k.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ELEV, &re) == BT_OK && bt_set_layer(k.ctx, BT_LAYER_ROUGHNESS, &rr) == BT_OK);
  CHECK(bt_set_env(k.ctx, &e) == BT_OK && bt_costmap_build(k.ctx, 5.0) == BT_OK);
  bt_raster cost, pass; CHECK(bt_costmap_view(k.ctx, &cost, &pass) == BT_OK && pass.h == 32 && pass.res_m == 10.0f);   // 전역은 거친 격자
  Core ref; CHECK(setup(ref, m, 5.0f) && bt_costmap_build(ref.ctx, 5.0) == BT_OK);   // 비교용: 5 m 전체를 한 번에

  std::vector<bt_cell> buf(8192), buf2(8192);
  bt_path p, q; std::memset(&p, 0, sizeof(p)); p.cells = buf.data(); p.cap = 8192; std::memset(&q, 0, sizeof(q)); q.cells = buf2.data(); q.cap = 8192;
  bt_budget b = budget();
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p) == BT_OK);
  CHECK(p.res_m == 5.0 && p.complete == 1 && violations(m, p) == 0);
  CHECK(p.cells[0].row == 10 && p.cells[0].col == 5 && p.cells[p.len - 1].row == 10 && p.cells[p.len - 1].col == 60);
  bool joined = true;
  for (uint32_t i = 1; i < p.len; ++i) { const int dr = p.cells[i].row - p.cells[i - 1].row, dc = p.cells[i].col - p.cells[i - 1].col; if (dr < -1 || dr > 1 || dc < -1 || dc > 1 || (dr == 0 && dc == 0)) joined = false; }
  CHECK(joined);                                                        // 구간 이음매가 이어진다
  CHECK(bt_plan(ref.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &q) == BT_OK);
  CHECK(p.cost >= q.cost - 1e-6 && p.cost <= q.cost * 1.25);            // 전체 최적보다 조금 나쁠 수 있다
  bt_state st; std::memset(&st, 0, sizeof(st));
  bt_path_metrics pm; CHECK(bt_path_measure(k.ctx, &p, &st, BT_WALK_PLAN, &pm) == BT_OK && pm.time_min > 0.0f && pm.max_slope_deg <= 20.0f);

  uint32_t seed = 17; int solved = 0;
  for (int it = 0; it < 200; ++it) {
    seed = seed * 1664525u + 1013904223u; const int r0 = (seed >> 8) % 64, c0 = (seed >> 16) % 64;
    seed = seed * 1664525u + 1013904223u; const int r1 = (seed >> 8) % 64, c1 = (seed >> 16) % 64;
    const bt_status s = bt_plan(k.ctx, cxy(5, r0, c0), cxy(5, r1, c1), &b, &p);
    CHECK(s == BT_OK || s == BT_PARTIAL || s == BT_ERR_UNREACHABLE);
    if (s >= 0) { solved++; CHECK(violations(m, p) == 0 && (p.res_m == 5.0 || p.res_m == 10.0)); }
    CHECK(p.expansions <= k.cfg.max_expansions);
  }
  CHECK(solved > 120);

  // 꺾이는 점: 계단 모양이 직선으로 줄고, 직선 구간도 통과불가를 지나지 않는다
  CHECK(bt_plan(k.ctx, cxy(5, 10, 5), cxy(5, 10, 60), &b, &p) == BT_OK);
  {
    std::vector<bt_xy> pts(p.len); uint32_t np2 = 0;
    CHECK(bt_path_polyline(k.ctx, &p, pts.data(), p.len, &np2) == BT_OK && np2 >= 2 && np2 < p.len / 3);
    CHECK(pts[0].x == cxy(5, 10, 5).x && pts[np2 - 1].x == cxy(5, 10, 60).x && pts[np2 - 1].y == cxy(5, 10, 60).y);
    int hit = 0; double poly = 0.0;
    for (uint32_t i = 1; i < np2; ++i) {
      const double dx = pts[i].x - pts[i - 1].x, dy = pts[i].y - pts[i - 1].y, len = std::hypot(dx, dy);
      poly += len;
      for (int q = 0; q <= static_cast<int>(len); ++q) { const double t = len > 0 ? q / len : 0; if (m.blocked(static_cast<int>(-(pts[i - 1].y + dy * t) / 5), static_cast<int>((pts[i - 1].x + dx * t) / 5))) hit++; }
    }
    CHECK(hit == 0 && poly <= p.length_m + 1e-6 && poly > 0.9 * p.length_m);
    bt_xy two[2]; CHECK(bt_path_polyline(k.ctx, &p, two, 1, &np2) == BT_ERR_CAPACITY);
  }

  // 귀환 필드는 거친 격자, 결정 지점의 경로는 고운 격자
  Sci s;
  Core rv; bt_config rc = sci_cfg(BT_NODE_ROVER, BT_OPTMODE_PARETO); rc.coarse_first_grid_m = 10.0f; rc.corridor_m = 20.0f;
  CHECK(rv.create(rc));
  bt_raster rm = f32_raster(s.mu0, Sci::N, Sci::N, 20.0f), rvv = f32_raster(s.var0, Sci::N, Sci::N, 20.0f);
  CHECK(bt_set_layer(rv.ctx, BT_LAYER_SLOPE, &rs) == BT_OK && bt_set_layer(rv.ctx, BT_LAYER_ELEV, &re) == BT_OK &&
        bt_set_layer(rv.ctx, BT_LAYER_MU0, &rm) == BT_OK && bt_set_layer(rv.ctx, BT_LAYER_VAR0, &rvv) == BT_OK && bt_set_env(rv.ctx, &e) == BT_OK);
  CHECK(bt_costmap_build(rv.ctx, 5.0) == BT_OK && bt_cost_to_go(rv.ctx, cxy(5, 40, 58), BT_WALK_RETURN, BT_FIELD_ROVER_RETURN) == BT_OK);
  CHECK(bt_science_update(rv.ctx, 0.0) == BT_OK);
  st.pos = cxy(5, 10, 40); st.t = 3600.0; st.node = BT_NODE_SUIT_A;
  bt_stop plan[2]; std::memset(plan, 0, sizeof(plan));
  plan[0].xy = cxy(5, 20, 50); plan[0].dwell_min = 10; plan[0].poi = 1; plan[1].xy = cxy(5, 45, 45); plan[1].dwell_min = 10; plan[1].poi = 2;
  // 환경 트리거로 묻는다(후보 전부가 나온다). 경로 갈림길 트리거는 실제로 다른 길이 있을 때만 선택지를 낸다
  bt_trigger f0; std::memset(&f0, 0, sizeof(f0)); f0.kind = BT_TRIG_ENV; f0.cause_kind = BT_CAUSE_SHADOW;
  bt_decision d;
  CHECK(bt_decide(rv.ctx, &st, plan, 2, nullptr, 0, &f0, &d) == BT_OK && d.n_options >= 2);
  for (uint32_t i = 0; i < d.n_options; ++i) {
    CHECK(bt_decision_path(rv.ctx, &d, i, &p) == BT_OK && violations(m, p) == 0 && d.options[i].nlt_margin_min >= 0.0f);
    if (d.options[i].kind == BT_OPT_ROUTE) CHECK(p.res_m == 5.0);
    if (d.options[i].kind == BT_OPT_RETURN) CHECK(p.res_m == 10.0);
  }
}

int main() {
  test_abi(); test_arena(); test_speed(); test_plan(); test_downsample(); test_field();
  test_apollo_walkback(); test_log(); test_link(); test_science(); test_decide();
  test_window(); test_coarse_to_fine(); test_select_pois();
  std::printf("selftest: %d checks, %d failed\n", g_checks, g_fail);
  return g_fail ? 1 : 0;
}
