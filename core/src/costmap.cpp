// C-11 코스트맵: 레이어를 합쳐 방향과 무관한 바탕을 만든다 (S3a §2)
#include "ctx.hpp"

using namespace bt;

namespace bt {

// 레이어의 한 구역을 코스트 바탕으로 채운다. 구역 = 레이어 격자의 f배 칸으로 (R0, C0)에서 H×W.
// 배열은 구역 안 자리 (r·W + c)로 쓴다. 전역 코스트맵도, 경로 주변의 고운 조각도 이 함수 하나로 만든다
void fill_rect(const bt_ctx* c, uint32_t f, int32_t R0, int32_t C0, uint32_t H, uint32_t W,
               float* const* base, float* elev, float* slope_out, uint8_t* passable, float* min_base) {
  const bt_grid_geom& g = c->cfg.cost_grid;
  const double res = static_cast<double>(g.res_m) * f;
  const bt_raster& slope = c->layer[BT_LAYER_SLOPE];
  const bool has_elev = c->layer_set[BT_LAYER_ELEV] != 0;
  const bool has_rough = c->layer_set[BT_LAYER_ROUGHNESS] != 0;
  const bool has_shadow = c->layer_set[BT_LAYER_SHADOW] != 0;
  const float theta_max = c->cfg.theta_max_deg;
  const double rough_ref = c->cfg.rough_ref_m > 0 ? static_cast<double>(c->cfg.rough_ref_m) : 1.0;
  const double dose_n = c->cfg.dose_ref > 0 ? c->env.dose_rate_uSv_h / static_cast<double>(c->cfg.dose_ref) : 0.0;

  // 보수적 다운샘플: 하위 칸 하나라도 통과불가면 통과불가. 경사는 최댓값, 나머지는 평균
  for (uint32_t R = 0; R < H; ++R) {
    for (uint32_t C = 0; C < W; ++C) {
      bool pass = true;
      float smax = 0.0f;
      double rsum = 0.0, shsum = 0.0, esum = 0.0;
      uint32_t n = 0, en = 0;
      const uint64_t gr0 = (static_cast<uint64_t>(R0) + R) * f, gc0 = (static_cast<uint64_t>(C0) + C) * f;
      const uint64_t r1 = gr0 + f < g.h ? gr0 + f : g.h;
      const uint64_t c1 = gc0 + f < g.w ? gc0 + f : g.w;
      for (uint64_t r = gr0; r < r1; ++r) {
        for (uint64_t cc = gc0; cc < c1; ++cc) {
          const uint64_t i = r * g.w + cc;
          const float s = raster_f(slope, i);
          if (!(s == s) || s > theta_max) pass = false;
          if (s == s && s > smax) smax = s;
          if (has_elev) {
            const float e = raster_f(c->layer[BT_LAYER_ELEV], i);
            if (e == e) { esum += e; en += 1; } else { pass = false; }
          }
          if (has_rough) {
            const float q = raster_f(c->layer[BT_LAYER_ROUGHNESS], i);
            if (q == q) {
              double qn = static_cast<double>(q) / rough_ref;
              if (qn < 0) qn = 0;
              if (qn > 1) qn = 1;
              rsum += qn;
            }
          }
          if (has_shadow) shsum += raster_bit(c->layer[BT_LAYER_SHADOW], c->env.shadow_bin, i);
          n += 1;
        }
      }
      if (n == 0) pass = false;
      const uint64_t k = static_cast<uint64_t>(R) * W + C;
      const double rough_n = n ? rsum / n : 0.0;
      const double shade = n ? shsum / n : 0.0;
      passable[k] = pass ? 1 : 0;
      if (slope_out) slope_out[k] = smax;
      elev[k] = en ? static_cast<float>(esum / en) : (has_elev ? __builtin_nanf("") : 0.0f);
      for (int p = 0; p < BT_MAX_PROFILES; ++p) {
        const bt_profile& w = c->cfg.profiles[p];
        base[p][k] = pass ? static_cast<float>(w.w_r * rough_n + w.w_sh * shade + w.w_rad * dose_n) : F_INF;
      }
    }
  }

  // 막힘 표시(mark/blocked)의 반경 안 칸은 통과불가 (R-26)
  const Geom mg{g.origin.x, g.origin.y, res, 0, 0};
  for (uint32_t e = 0; e < c->log_n; ++e) {
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_MARK || ev.kind != BT_MARK_BLOCKED) continue;
    const double rad = ev.a > 0 ? static_cast<double>(ev.a) : 0.0;
    const double span = rad / res + 1.0;
    const double cx = (ev.x - mg.ox) / res, cy = (mg.oy - ev.y) / res;
    int64_t r0 = static_cast<int64_t>(std::floor(cy - span)), r1 = static_cast<int64_t>(std::floor(cy + span));
    int64_t c0 = static_cast<int64_t>(std::floor(cx - span)), c1 = static_cast<int64_t>(std::floor(cx + span));
    if (r0 < R0) r0 = R0;
    if (c0 < C0) c0 = C0;
    if (r1 >= static_cast<int64_t>(R0) + H) r1 = static_cast<int64_t>(R0) + H - 1;
    if (c1 >= static_cast<int64_t>(C0) + W) c1 = static_cast<int64_t>(C0) + W - 1;
    for (int64_t r = r0; r <= r1; ++r) {
      for (int64_t cc = c0; cc <= c1; ++cc) {
        const bt_xy p = cell_center(mg, static_cast<int32_t>(r), static_cast<int32_t>(cc));
        const double dx = p.x - ev.x, dy = p.y - ev.y;
        if (dx * dx + dy * dy <= rad * rad) {
          const uint64_t k = static_cast<uint64_t>(r - R0) * W + static_cast<uint64_t>(cc - C0);
          passable[k] = 0;
          for (int p2 = 0; p2 < BT_MAX_PROFILES; ++p2) base[p2][k] = F_INF;
        }
      }
    }
  }

  // 성향별 바탕의 최솟값 (휴리스틱이 허용적이려면 이 값을 쓴다)
  const uint64_t cells = static_cast<uint64_t>(H) * W;
  for (int p = 0; p < BT_MAX_PROFILES; ++p) {
    float mn = F_INF;
    for (uint64_t k = 0; k < cells; ++k) {
      if (passable[k] && base[p][k] < mn) mn = base[p][k];
    }
    min_base[p] = (mn < F_INF) ? mn : 0.0f;
  }
}

}  // namespace bt

bt_status bt_costmap_build(bt_ctx* c, double res_m) {
  if (!c) return BT_ERR_ARG;
  if (!c->layer_set[BT_LAYER_SLOPE] || !c->env_set) return BT_ERR_NOT_READY;
  const bt_grid_geom& g = c->cfg.cost_grid;
  // 거친 격자 먼저(coarse_first_grid_m)가 켜져 있으면 전역 코스트맵은 그 격자로 만든다. 고운 격자는 경로 주변에서만 쓴다
  if (c->tile.cap > 0 && res_m < static_cast<double>(c->cfg.coarse_first_grid_m)) res_m = static_cast<double>(c->cfg.coarse_first_grid_m);
  const double fr = res_m / static_cast<double>(g.res_m);
  const uint32_t f = static_cast<uint32_t>(fr + 0.5);
  if (!(res_m > 0) || f < 1 || std::fabs(fr - static_cast<double>(f)) > 1e-6) return BT_ERR_ARG;
  const uint32_t H = (g.h + f - 1) / f, W = (g.w + f - 1) / f;
  if (static_cast<uint64_t>(H) * W > c->cm.cap) return BT_ERR_CAPACITY;
  CostMap& m = c->cm;
  m.h = H; m.w = W; m.factor = f; m.res = static_cast<double>(g.res_m) * f;
  fill_rect(c, f, 0, 0, H, W, m.base, m.elev, m.slope, m.passable, m.min_base);
  m.built = 1;
  return BT_OK;
}

bt_status bt_costmap_view(const bt_ctx* c, bt_raster* out_cost, bt_raster* out_passable) {
  if (!c) return BT_ERR_ARG;
  if (!c->cm.built) return BT_ERR_NOT_READY;
  bt_raster r;
  std::memset(&r, 0, sizeof(r));
  r.h = c->cm.h; r.w = c->cm.w; r.res_m = static_cast<float>(c->cm.res);
  r.planes = 1; r.scale = 1.0f; r.offset = 0.0f; r.origin = c->cfg.cost_grid.origin;
  if (out_cost) { *out_cost = r; out_cost->data = c->cm.base[0]; out_cost->dtype = BT_DT_F32; }   // 균형 성향의 바탕
  if (out_passable) { *out_passable = r; out_passable->data = c->cm.passable; out_passable->dtype = BT_DT_U8; }
  return BT_OK;
}
