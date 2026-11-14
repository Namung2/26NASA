// C-12 과학 가치 모델 + C-36 주의 흔적 (S3a §5).
// STATIC prior에 이벤트 로그 전체를 재적용해 맵을 만든다. 맵을 만드는 길은 이 파일 하나뿐이다
#include "ctx.hpp"

using namespace bt;

namespace bt {
// 과학 작업 격자: science_grid_m = 0이면 번들 격자 그대로, 양수면 그 크기로 다시 나눈다(같은 범위)
bool science_geom(const bt_config& cfg, Geom* g) {
  const bt_grid_geom& s = cfg.science_grid;
  if (cfg.science_grid_m < 0 || !(s.res_m > 0) || s.h == 0 || s.w == 0) return false;
  const double res = cfg.science_grid_m > 0 ? static_cast<double>(cfg.science_grid_m) : static_cast<double>(s.res_m);
  g->ox = s.origin.x; g->oy = s.origin.y; g->res = res;
  g->h = static_cast<uint32_t>(std::ceil(s.h * static_cast<double>(s.res_m) / res));
  g->w = static_cast<uint32_t>(std::ceil(s.w * static_cast<double>(s.res_m) / res));
  return g->h > 0 && g->w > 0;
}
}  // namespace bt

namespace {

// 번들 과학 레이어에서 작업 격자 칸 i의 값을 읽는다 (가장 가까운 칸. 값 없으면 NaN)
inline float prior_of(const bt_ctx* c, int kind, uint32_t i) {
  const Science& s = c->sci;
  if (s.same_grid) return raster_f(c->layer[kind], i);
  const bt_xy p = cell_center(s.g, static_cast<int32_t>(i / s.g.w), static_cast<int32_t>(i % s.g.w));
  int32_t r, col;
  if (!xy_to_cell(geom_of(c->cfg.science_grid), p, &r, &col)) return __builtin_nanf("");
  return raster_f(c->layer[kind], static_cast<uint64_t>(r) * c->cfg.science_grid.w + static_cast<uint64_t>(col));
}
inline uint8_t unit_at(const bt_ctx* c, bt_xy p) {
  if (!c->layer_set[BT_LAYER_UNITS]) return 0;
  int32_t r, col;
  if (!xy_to_cell(geom_of(c->cfg.science_grid), p, &r, &col)) return 0;
  return static_cast<const uint8_t*>(c->layer[BT_LAYER_UNITS].data)[static_cast<uint64_t>(r) * c->cfg.science_grid.w + static_cast<uint64_t>(col)];
}
inline float slope_at(const bt_ctx* c, bt_xy p) {
  if (!c->layer_set[BT_LAYER_SLOPE]) return 0.0f;
  int32_t r, col;
  if (!xy_to_cell(geom_of(c->cfg.cost_grid), p, &r, &col)) return 0.0f;
  const float s = raster_f(c->layer[BT_LAYER_SLOPE], static_cast<uint64_t>(r) * c->cfg.cost_grid.w + static_cast<uint64_t>(col));
  return (s == s) ? s : 0.0f;
}

// 가설 규칙 커널의 가중 (0~1). 닻 기준 (S3a §5.1)
double hyp_weight(const bt_ctx* c, const Hyp& h, bt_xy p) {
  const double dx = p.x - h.anchor.x, dy = p.y - h.anchor.y;   // 동쪽, 북쪽
  const double L = static_cast<double>(h.extent_m);
  if (!(L > 0)) return 0.0;
  if (dx * dx + dy * dy > 9.0 * L * L) return 0.0;             // 영향 범위는 닻에서 3·extent까지
  if (h.rule == BT_RULE_STRATA_CONTINUITY) {
    const double th = static_cast<double>(h.dir_deg) / RAD2DEG;
    const double ux = std::sin(th), uy = std::cos(th);         // 0 = 북, 시계 방향
    const double along = dx * ux + dy * uy, across = -dx * uy + dy * ux;
    const double ratio = c->cfg.aniso_ratio > 0 ? static_cast<double>(c->cfg.aniso_ratio) : 1.0;
    const double a = along / L, b = across / (L / ratio);
    return std::exp(-0.5 * (a * a + b * b));
  }
  double w = std::exp(-0.5 * (dx * dx + dy * dy) / (L * L));
  if (h.rule == BT_RULE_UNIT_BOUNDARY) {
    if (unit_at(c, p) != h.unit) w = 0.0;                      // 경계 너머는 0
  } else if (h.rule == BT_RULE_EROSION_EXPOSURE) {
    const double ref = c->cfg.exposure_slope_ref_deg > 0 ? static_cast<double>(c->cfg.exposure_slope_ref_deg) : 1.0;
    double k = static_cast<double>(slope_at(c, p)) / ref;
    if (k < 0) k = 0;
    if (k > 1) k = 1;
    w *= k;                                                    // 경사면 가산
  }
  return w;
}

// 가설 h가 칸 i에 더하는 값: 이미 관측된 곳(분산이 준 곳)에서는 사라진다
inline double delta_at(const bt_ctx* c, const Hyp& h, uint32_t i) {
  const Science& s = c->sci;
  const bt_xy p = cell_center(s.g, static_cast<int32_t>(i / s.g.w), static_cast<int32_t>(i % s.g.w));
  const double w = hyp_weight(c, h, p);
  if (!(w > 0)) return 0.0;
  const float v0 = prior_of(c, BT_LAYER_VAR0, i);
  if (!(v0 > 0)) return 0.0;
  const uint32_t a = static_cast<uint32_t>(h.ar) * s.g.w + static_cast<uint32_t>(h.ac);
  const double gap = static_cast<double>(s.mu[a]) - static_cast<double>(s.mu[i]);
  if (!(gap > 0)) return 0.0;
  return w * gap * (static_cast<double>(s.var[i]) / static_cast<double>(v0));
}

}  // namespace

namespace bt {
double hyp_delta_at(const bt_ctx* c, uint32_t hyp_index, uint32_t cell) {
  if (hyp_index >= c->sci.n_hyps || cell >= c->sci.cells) return 0.0;
  return delta_at(c, c->sci.hyp[hyp_index], cell);
}
}  // namespace bt

namespace {

struct Win { int32_t r0, r1, c0, c1; };
inline Win window(const Geom& g, bt_xy p, double radius) {
  Win w;
  w.c0 = static_cast<int32_t>(std::floor((p.x - radius - g.ox) / g.res));
  w.c1 = static_cast<int32_t>(std::floor((p.x + radius - g.ox) / g.res));
  w.r0 = static_cast<int32_t>(std::floor((g.oy - (p.y + radius)) / g.res));
  w.r1 = static_cast<int32_t>(std::floor((g.oy - (p.y - radius)) / g.res));
  if (w.c0 < 0) w.c0 = 0;
  if (w.r0 < 0) w.r0 = 0;
  if (w.c1 >= static_cast<int32_t>(g.w)) w.c1 = static_cast<int32_t>(g.w) - 1;
  if (w.r1 >= static_cast<int32_t>(g.h)) w.r1 = static_cast<int32_t>(g.h) - 1;
  return w;
}

}  // namespace

bt_status bt_science_update(bt_ctx* c, double t_eval) {
  if (!c) return BT_ERR_NOT_READY;
  Science& s = c->sci;
  if (!s.mu || !c->layer_set[BT_LAYER_MU0] || !c->layer_set[BT_LAYER_VAR0]) return BT_ERR_NOT_READY;
  const bt_config& cfg = c->cfg;
  const float var_floor = cfg.var_floor;

  // 1층: prior 복사
  for (uint32_t i = 0; i < s.cells; ++i) {
    const float m0 = prior_of(c, BT_LAYER_MU0, i), v0 = prior_of(c, BT_LAYER_VAR0, i);
    s.mu[i] = (m0 == m0) ? m0 : 0.0f;
    s.var[i] = (v0 == v0) ? v0 : 0.0f;
    s.live[i] = 0;
  }

  // 살아 있는 가설: 승인됐고, 다른 가설 이벤트가 대체(철회)하지 않은 것. 넘치면 최신 것만
  s.n_hyps = 0;
  s.skipped = 0;
  for (uint32_t e = 0; e < c->log_n; ++e) {
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_HYP || !(ev.flags & BT_EVF_APPROVED)) continue;
    const uint16_t key = BT_HYP_KEY(ev.node, ev.seq);
    bool replaced = false;
    for (uint32_t f = 0; f < c->log_n && !replaced; ++f) {
      if (c->log[f].type == BT_EV_HYP && c->log[f].aux == key && f != e) replaced = true;
    }
    if (replaced) continue;
    Hyp h;
    std::memset(&h, 0, sizeof(h));
    h.lts = ev.lts; h.seq = ev.seq; h.key = key; h.node = ev.node; h.rule = ev.rule;
    h.dir_deg = ev.a; h.extent_m = ev.b; h.conf0 = ev.c; h.conf = ev.c;
    h.anchor.x = ev.x; h.anchor.y = ev.y;
    if (!xy_to_cell(s.g, h.anchor, &h.ar, &h.ac) || !(h.extent_m > 0)) { s.skipped += 1; continue; }   // 닻이 격자 밖
    h.unit = unit_at(c, h.anchor);
    if (s.n_hyps == BT_MAX_HYPS) {
      for (uint32_t k = 1; k < BT_MAX_HYPS; ++k) s.hyp[k - 1] = s.hyp[k];
      s.n_hyps -= 1;
    }
    s.hyp[s.n_hyps] = h;
    s.n_hyps += 1;
  }

  // 3층: 관측을 정렬 순으로 재적용 (크리깅식 국소 갱신, 창 = 3·l0)
  const double l0 = cfg.l0_m > 0 ? static_cast<double>(cfg.l0_m) : 1.0;
  for (uint32_t e = 0; e < c->log_n; ++e) {
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_OBS) continue;
    const bt_xy p{ev.x, ev.y};
    int32_t orow, ocol;
    if (!xy_to_cell(s.g, p, &orow, &ocol)) continue;
    const uint32_t o = static_cast<uint32_t>(orow) * s.g.w + static_cast<uint32_t>(ocol);
    const bool found = (ev.flags & BT_EVF_FOUND) != 0;
    const bool confirmed = (ev.flags & BT_EVF_CONFIRMED) != 0;

    // 확인된 관측은 지도에 적용하기 직전에 가설의 확신을 고친다 (S3a §5.2a)
    if (confirmed) {
      for (uint32_t k = 0; k < s.n_hyps; ++k) {
        Hyp& h = s.hyp[k];
        if (!(ev.lts > h.lts)) continue;                      // 가설보다 앞선 관측은 쓰지 않는다
        const double p0 = static_cast<double>(s.mu[o]);
        double p1 = p0 + delta_at(c, h, o);
        if (p1 > 1.0) p1 = 1.0;
        if (p1 == p0) continue;                               // 가설이 영향을 주지 않는 자리
        const double L0 = found ? p0 : 1.0 - p0, L1 = found ? p1 : 1.0 - p1;
        const double conf = static_cast<double>(h.conf);
        const double den = conf * L1 + (1.0 - conf) * L0;
        if (den > 0) h.conf = static_cast<float>(conf * L1 / den);
        if (h.n_used < 255) h.n_used += 1;
      }
    }

    const double y = found ? 1.0 : 0.0;
    const double r = static_cast<double>(cfg.obs_noise) * (confirmed ? 1.0 : static_cast<double>(cfg.unconfirmed_factor));
    const double var_o = static_cast<double>(s.var[o]), mu_o = static_cast<double>(s.mu[o]);
    if (!(var_o + r > 0)) continue;
    const bt_xy oc = cell_center(s.g, orow, ocol);
    const Win w = window(s.g, oc, 3.0 * l0);
    for (int32_t rr = w.r0; rr <= w.r1; ++rr) {
      for (int32_t cc = w.c0; cc <= w.c1; ++cc) {
        const bt_xy q = cell_center(s.g, rr, cc);
        const double d2 = (q.x - oc.x) * (q.x - oc.x) + (q.y - oc.y) * (q.y - oc.y);
        if (d2 > 9.0 * l0 * l0) continue;
        const double k = std::exp(-0.5 * d2 / (l0 * l0));
        const uint32_t i = static_cast<uint32_t>(rr) * s.g.w + static_cast<uint32_t>(cc);
        const double cov = k * std::sqrt(static_cast<double>(s.var[i]) * var_o);
        double mu = static_cast<double>(s.mu[i]) + cov / (var_o + r) * (y - mu_o);
        double var = static_cast<double>(s.var[i]) - cov * cov / (var_o + r);
        if (mu < 0) mu = 0;
        if (mu > 1) mu = 1;
        if (var < static_cast<double>(var_floor)) var = static_cast<double>(var_floor);
        s.mu[i] = static_cast<float>(mu);
        s.var[i] = static_cast<float>(var);
        if (k > static_cast<double>(cfg.touch_eps)) s.live[i] = 1;
      }
    }
  }

  // 2층: 가설이 더하는 값. 가설마다 지도를 따로 두지 않고 세 가지 합만 쌓는다 (창 = 3·extent).
  // 여러 가설이 같은 칸을 올리면 전부 더해진다.
  std::memset(s.add_exp, 0, static_cast<uint64_t>(s.cells) * sizeof(float));
  std::memset(s.add_full, 0, static_cast<uint64_t>(s.cells) * sizeof(float));
  std::memset(s.add_var, 0, static_cast<uint64_t>(s.cells) * sizeof(float));
  for (uint32_t k = 0; k < s.n_hyps; ++k) {
    const Hyp& h = s.hyp[k];
    const double conf = static_cast<double>(h.conf);
    const Win w = window(s.g, h.anchor, 3.0 * static_cast<double>(h.extent_m));
    for (int32_t rr = w.r0; rr <= w.r1; ++rr) {
      for (int32_t cc = w.c0; cc <= w.c1; ++cc) {
        const uint32_t i = static_cast<uint32_t>(rr) * s.g.w + static_cast<uint32_t>(cc);
        const double d = delta_at(c, h, i);
        if (!(d > 0)) continue;
        s.add_exp[i] = static_cast<float>(static_cast<double>(s.add_exp[i]) + conf * d);
        s.add_full[i] = static_cast<float>(static_cast<double>(s.add_full[i]) + d);
        s.add_var[i] = static_cast<float>(static_cast<double>(s.add_var[i]) + conf * (1.0 - conf) * d * d);   // 맞다/틀리다의 불확실성
      }
    }
  }

  // 주의 흔적: 촬영·관측을 한 자리의 점. tau_s 동안 살아 있고, 발견이 난 자리의 흔적은 남는다
  s.n_traces = 0;
  const double tau = cfg.tau_s > 0 ? static_cast<double>(cfg.tau_s) : 1.0;
  const double r_obs2 = static_cast<double>(cfg.r_obs_m) * static_cast<double>(cfg.r_obs_m);
  for (uint32_t e = 0; e < c->log_n; ++e) {
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_TRACE) continue;
    bool kept = false;
    double first_found = D_INF;
    for (uint32_t f = 0; f < c->log_n; ++f) {
      const bt_event& ob = c->log[f];
      if (ob.type != BT_EV_OBS || !(ob.flags & BT_EVF_FOUND) || ob.ts < ev.ts) continue;
      const double d2 = (ob.x - ev.x) * (ob.x - ev.x) + (ob.y - ev.y) * (ob.y - ev.y);
      if (d2 > r_obs2) continue;
      kept = true;
      if (ob.ts < first_found) first_found = ob.ts;
    }
    double age = (kept ? first_found : t_eval) - ev.ts;
    if (age < 0) age = 0;
    bt_trace_pt& t = s.traces[s.n_traces];
    std::memset(&t, 0, sizeof(t));
    t.xy.x = ev.x; t.xy.y = ev.y; t.ts = ev.ts; t.lts = ev.lts; t.node = ev.node; t.kind = ev.kind;
    t.kept = kept ? 1 : 0;
    t.alive = (kept || age < tau) ? 1 : 0;
    t.fade = static_cast<float>(1.0 - (age < tau ? age : tau) / tau);
    s.n_traces += 1;
  }

  s.ready = 1;
  return s.skipped ? BT_PARTIAL : BT_OK;            // BT_PARTIAL = 닻이 격자 밖이라 건너뛴 가설이 있다
}

bt_status bt_science_get_view(const bt_ctx* c, bt_science_view* out) {
  if (!c || !out) return BT_ERR_ARG;
  const Science& s = c->sci;
  if (!s.ready) return BT_ERR_NOT_READY;
  std::memset(out, 0, sizeof(*out));
  bt_raster r;
  std::memset(&r, 0, sizeof(r));
  r.h = s.g.h; r.w = s.g.w; r.res_m = static_cast<float>(s.g.res); r.planes = 1; r.scale = 1.0f;
  r.origin.x = s.g.ox; r.origin.y = s.g.oy; r.dtype = BT_DT_F32;
  out->mu_base = r; out->mu_base.data = s.mu;
  out->var = r; out->var.data = s.var;
  out->live_touched = r; out->live_touched.data = s.live; out->live_touched.dtype = BT_DT_U8;
  out->add_expected = r; out->add_expected.data = s.add_exp;
  out->add_full = r; out->add_full.data = s.add_full;
  out->traces = s.traces; out->n_traces = s.n_traces;
  out->n_hyps = s.n_hyps;
  for (uint32_t k = 0; k < s.n_hyps; ++k) {
    bt_hyp_view& v = out->hyps[k];
    v.lts = s.hyp[k].lts; v.seq = s.hyp[k].seq; v.node = s.hyp[k].node; v.n_used = s.hyp[k].n_used;
    v.conf_chosen = s.hyp[k].conf0; v.conf_now = s.hyp[k].conf;
  }
  return BT_OK;
}

bt_status bt_science_hyp_delta(const bt_ctx* c, uint32_t hyp_index, bt_raster* out) {
  if (!c || !out || !out->data) return BT_ERR_ARG;
  const Science& s = c->sci;
  if (!s.ready) return BT_ERR_NOT_READY;
  if (hyp_index >= s.n_hyps) return BT_ERR_ARG;
  if (out->h != s.g.h || out->w != s.g.w) return BT_ERR_CAPACITY;
  float* dst = static_cast<float*>(const_cast<void*>(out->data));
  for (uint32_t i = 0; i < s.cells; ++i) dst[i] = static_cast<float>(delta_at(c, s.hyp[hyp_index], i));
  out->res_m = static_cast<float>(s.g.res); out->dtype = BT_DT_F32; out->planes = 1; out->scale = 1.0f; out->offset = 0.0f;
  out->origin.x = s.g.ox; out->origin.y = s.g.oy;
  return BT_OK;
}

uint64_t bt_science_digest(const bt_ctx* c) {
  if (!c || !c->sci.ready) return 0;
  const Science& s = c->sci;
  uint64_t h = FNV_OFFSET;
  h = fnv_bytes(h, s.mu, static_cast<uint64_t>(s.cells) * sizeof(float));
  h = fnv_bytes(h, s.var, static_cast<uint64_t>(s.cells) * sizeof(float));
  h = fnv_bytes(h, s.live, s.cells);
  h = fnv(h, s.n_hyps);
  for (uint32_t k = 0; k < s.n_hyps; ++k) { h = fnv(h, s.hyp[k].key); h = fnv(h, s.hyp[k].conf); }
  if (s.n_hyps > 0) {
    h = fnv_bytes(h, s.add_exp, static_cast<uint64_t>(s.cells) * sizeof(float));
    h = fnv_bytes(h, s.add_full, static_cast<uint64_t>(s.cells) * sizeof(float));
    h = fnv_bytes(h, s.add_var, static_cast<uint64_t>(s.cells) * sizeof(float));
  }
  return h;
}

// 경로·정지점 주변(r_obs)의 가치·정보 이득 (S3a §5.3)
bt_status bt_path_evaluate(const bt_ctx* c, const bt_path* path, const bt_stop* stops, uint32_t n_stops, bt_path_value* out) {
  if (!c || !out || (!stops && n_stops > 0)) return BT_ERR_ARG;
  const Science& s = c->sci;
  if (!s.ready) return BT_ERR_NOT_READY;
  std::memset(out, 0, sizeof(*out));
  const bt_config& cfg = c->cfg;
  const double r_obs = static_cast<double>(cfg.r_obs_m);
  float* wt = s.scratch;                            // 칸마다 관측 가중 (정지점 1, 통과 구간 w_transit)
  std::memset(wt, 0, static_cast<uint64_t>(s.cells) * sizeof(float));

  const uint32_t n_path = (path && path->cells) ? path->len : 0;
  const bt_grid_geom& bg = c->cfg.cost_grid;
  for (uint32_t pass = 0; pass < 2; ++pass) {
    const uint32_t n = pass == 0 ? n_path : n_stops;
    const float weight = pass == 0 ? cfg.w_transit : 1.0f;
    for (uint32_t k = 0; k < n; ++k) {
      bt_xy p;
      if (pass == 0) {
        const Geom pg{bg.origin.x, bg.origin.y, path->res_m, 0, 0};
        p = cell_center(pg, path->cells[k].row, path->cells[k].col);
      } else {
        p = stops[k].xy;
      }
      int32_t r0, c0;
      if (xy_to_cell(s.g, p, &r0, &c0)) {           // 서 있는 칸은 언제나 포함
        float& x = wt[static_cast<uint32_t>(r0) * s.g.w + static_cast<uint32_t>(c0)];
        if (weight > x) x = weight;
      }
      const Win w = window(s.g, p, r_obs);
      for (int32_t rr = w.r0; rr <= w.r1; ++rr) {
        for (int32_t cc = w.c0; cc <= w.c1; ++cc) {
          const bt_xy q = cell_center(s.g, rr, cc);
          if ((q.x - p.x) * (q.x - p.x) + (q.y - p.y) * (q.y - p.y) > r_obs * r_obs) continue;
          float& x = wt[static_cast<uint32_t>(rr) * s.g.w + static_cast<uint32_t>(cc)];
          if (weight > x) x = weight;
        }
      }
    }
  }

  const double a = s.g.res * s.g.res / (cfg.A_ref_m2 > 0 ? static_cast<double>(cfg.A_ref_m2) : 1.0);
  const double r_plan = static_cast<double>(cfg.r_plan);
  double v_mean = 0, v_lo = 0, v_hi = 0, v_var = 0, gain = 0, peak = 0;
  double contrib[BT_MAX_HYPS];
  for (int k = 0; k < BT_MAX_HYPS; ++k) contrib[k] = 0.0;
  bool touched = false;
  for (uint32_t i = 0; i < s.cells; ++i) {
    const double w = static_cast<double>(wt[i]);
    if (!(w > 0)) continue;
    const double mu = static_cast<double>(s.mu[i]);
    const double exp_add = static_cast<double>(s.add_exp[i]), full_add = static_cast<double>(s.add_full[i]);
    const double var_eff = static_cast<double>(s.var[i]) + static_cast<double>(s.add_var[i]);   // 가설의 맞다/틀리다 불확실성 포함
    if (full_add > 0) {                             // 어느 가설의 몫인지는 이 경로가 지나는 칸에서만 그때 계산한다
      for (uint32_t k = 0; k < s.n_hyps; ++k) contrib[k] += w * delta_at(c, s.hyp[k], i);
    }
    v_mean += w * (mu + exp_add) * a;
    v_lo += w * mu * a;
    v_hi += w * (mu + full_add) * a;
    v_var += w * var_eff * a;
    if (var_eff + r_plan > 0) gain += w * var_eff * var_eff / (var_eff + r_plan) * a;
    if (mu + full_add > peak) peak = mu + full_add;
    if (s.live[i]) touched = true;
  }
  out->value_mean = static_cast<float>(v_mean);
  out->value_lo = static_cast<float>(v_lo);
  out->value_hi = static_cast<float>(v_hi);
  out->value_var = static_cast<float>(v_var);
  out->info_gain = static_cast<float>(gain);
  out->peak = static_cast<float>(peak);
  uint32_t nh = 0;
  bool any_hyp = false;
  for (uint32_t k = 0; k < s.n_hyps; ++k) {
    if (!(contrib[k] > 0)) continue;
    any_hyp = true;
    if (nh < BT_OPTION_HYPS) { out->hyp_seq[nh] = s.hyp[k].key; nh += 1; }
  }
  out->prior_only = (!touched && !any_hyp) ? 1 : 0;

  // 경로·정지점에서 r_obs 안에 있는 살아 있는 흔적의 수 (가치에 더하지 않는다)
  uint32_t count = 0;
  for (uint32_t t = 0; t < s.n_traces; ++t) {
    if (!s.traces[t].alive) continue;
    const bt_xy q = s.traces[t].xy;
    bool near = false;
    for (uint32_t k = 0; k < n_stops && !near; ++k) {
      const bt_xy p = stops[k].xy;
      if ((q.x - p.x) * (q.x - p.x) + (q.y - p.y) * (q.y - p.y) <= r_obs * r_obs) near = true;
    }
    for (uint32_t k = 0; k < n_path && !near; ++k) {
      const Geom pg{bg.origin.x, bg.origin.y, path->res_m, 0, 0};
      const bt_xy p = cell_center(pg, path->cells[k].row, path->cells[k].col);
      if ((q.x - p.x) * (q.x - p.x) + (q.y - p.y) * (q.y - p.y) <= r_obs * r_obs) near = true;
    }
    if (near) count += 1;
  }
  out->explore_count = static_cast<uint16_t>(count > 65535 ? 65535 : count);
  return BT_OK;
}
