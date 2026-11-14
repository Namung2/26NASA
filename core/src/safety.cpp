// C-32 안전 감시: 로버 귀환 출발 한계(NLT), SPE, 일몰 (S3a §7). 탐색하지 않고 귀환 필드를 조회만 한다
#include "ctx.hpp"

using namespace bt;

namespace bt {

double depart_deadline(const bt_ctx* c, uint8_t* binding) {
  const double t_eva = static_cast<double>(c->cfg.eva_max_h) * 3600.0;
  const double t_sun = c->env.t_sunset_s - static_cast<double>(c->cfg.sunset_margin_min) * 60.0;
  const bool sun_binds = t_sun < t_eva;
  if (binding) *binding = sun_binds ? BT_BIND_SUNSET : BT_BIND_EVA_MAX;
  return sun_binds ? t_sun : t_eva;
}

// 현 위치의 로버 귀환 시간(초). 도달 불가 칸이면 가장 가까운 유한 칸 값 + 그 거리의 보행 시간
bool return_seconds(const bt_ctx* c, const FieldView& v, bt_xy pos, double* sec, uint8_t* degraded) {
  int32_t r, col;
  *degraded = 0;
  if (!xy_to_cell(v.geom, pos, &r, &col)) return false;
  const float t0 = v.time[static_cast<uint64_t>(r) * v.geom.w + static_cast<uint64_t>(col)];
  if (t0 < F_INF) { *sec = static_cast<double>(t0); return true; }
  const int32_t maxk = static_cast<int32_t>(v.geom.h > v.geom.w ? v.geom.h : v.geom.w);
  const double v_ret = static_cast<double>(c->cfg.v_return_kmh) / 3.6;
  double best = D_INF;
  for (int32_t k = 1; k <= maxk; ++k) {             // 상한: 격자 한 변
    if (best < D_INF && (static_cast<double>(k) - 1.0) * v.geom.res / v_ret > best) break;   // 더 먼 고리는 볼 필요 없다
    for (int32_t dr = -k; dr <= k; ++dr) {
      const int32_t step = (dr == -k || dr == k) ? 1 : 2 * k;
      for (int32_t dc = -k; dc <= k; dc += step) {
        const int32_t rr = r + dr, cc = col + dc;
        if (rr < 0 || cc < 0 || rr >= static_cast<int32_t>(v.geom.h) || cc >= static_cast<int32_t>(v.geom.w)) continue;
        const float t = v.time[static_cast<uint64_t>(rr) * v.geom.w + static_cast<uint64_t>(cc)];
        if (!(t < F_INF)) continue;
        const double d = std::sqrt(static_cast<double>(dr) * dr + static_cast<double>(dc) * dc) * v.geom.res;
        const double total = static_cast<double>(t) + d / v_ret;
        if (total < best) best = total;
      }
    }
  }
  if (!(best < D_INF)) return false;
  *sec = best;
  *degraded = 1;
  return true;
}

}  // namespace bt

bt_status bt_depart_limit(const bt_ctx* c, const bt_state* st, bt_nlt* out) {
  if (!c || !st || !out) return BT_ERR_ARG;
  FieldView v;
  if (!field_view(c, &v) || !c->env_set) return BT_ERR_NOT_READY;
  double need;
  uint8_t degraded;
  if (!return_seconds(c, v, st->pos, &need, &degraded)) return BT_ERR_UNREACHABLE;
  need *= static_cast<double>(c->cfg.k_return);
  uint8_t binding;
  const double limit = depart_deadline(c, &binding);
  out->t_depart = limit - need;
  out->slack_min = static_cast<float>((out->t_depart - st->t) / 60.0);
  out->binding = binding;
  out->degraded = degraded;
  return BT_OK;
}

bt_status bt_safety_check(bt_ctx* c, const bt_state* now, const bt_state* prev,
                          bt_trigger* out, uint32_t cap, uint32_t* n, uint8_t* out_warn) {
  (void)prev;
  if (!c || !now || !n || !out_warn || (!out && cap > 0)) return BT_ERR_ARG;
  *n = 0;
  *out_warn = 0;
  bt_nlt nlt;
  const bt_status st = bt_depart_limit(c, now, &nlt);
  if (st != BT_OK) return st;
  bt_trigger t[3];
  uint32_t k = 0;
  std::memset(t, 0, sizeof(t));
  if (nlt.slack_min < c->cfg.nlt_force_min) {        // "귀환"
    t[k].kind = BT_TRIG_SAFETY; t[k].forced = 1; t[k].cause_kind = BT_CAUSE_NLT; k += 1;
  } else if (nlt.slack_min < c->cfg.nlt_warn_min) {
    *out_warn = 1;                                   // 경고 배너만, 결정 지점 아님
  }
  if (c->env.spe) {                                  // "대피"
    t[k].kind = BT_TRIG_SAFETY; t[k].forced = 1; t[k].cause_kind = BT_CAUSE_SPE; k += 1;
  }
  if ((c->env.t_sunset_s - now->t) / 60.0 < static_cast<double>(c->cfg.sunset_warn_min)) {   // "귀환 마진"
    t[k].kind = BT_TRIG_ENV; t[k].forced = 0; t[k].cause_kind = BT_CAUSE_SUNSET; k += 1;
  }
  if (k > cap) return BT_ERR_CAPACITY;
  for (uint32_t i = 0; i < k; ++i) out[i] = t[i];
  *n = k;
  return BT_OK;
}
