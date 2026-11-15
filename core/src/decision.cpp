// C-22 결정 지점·옵션 (S3a §6): 언제 물을지(트리거)와 무엇을 보여줄지(옵션 2~3개). 추천은 하지 않는다
#include "ctx.hpp"

using namespace bt;

namespace {

inline float rnd(double x, float prec) {            // 표시 정밀도로 맞춘다 (눈에 같은 수치는 같은 값)
  if (!(prec > 0)) return static_cast<float>(x);
  return static_cast<float>(std::floor(x / static_cast<double>(prec) + 0.5) * static_cast<double>(prec));
}
inline bool same_trigger(const bt_trigger& a, const bt_trigger& b) {
  return a.kind == b.kind && a.cause_kind == b.cause_kind && a.cause_lts == b.cause_lts && a.cause_node == b.cause_node;
}
inline bool near_m(bt_xy a, bt_xy b, double r) {
  const double dx = a.x - b.x, dy = a.y - b.y;
  return dx * dx + dy * dy <= r * r;
}

inline bool same_stops(const bt_stop* a, uint32_t na, const bt_stop* b, uint32_t nb) {
  if (na != nb) return false;
  for (uint32_t k = 0; k < na; ++k) {
    if (a[k].xy.x != b[k].xy.x || a[k].xy.y != b[k].xy.y || a[k].dwell_min != b[k].dwell_min) return false;
  }
  return true;
}

// 두 칸 경로가 서로 가장 멀리 벌어지는 거리(m): 한쪽의 어느 칸에서 다른 쪽까지의 가장 가까운 거리 가운데 가장 큰 값(양쪽 모두).
// 경로 갈림길에서 "다른 길"인지 가리는 데 쓴다. 8방향 격자에서는 비용이 같은 길이 칸만 다르게 여러 개 나오는데, 곧게 펴면 같은 선이다 —
// 칸이 겹치는 비율만으로는 그런 길을 다른 길로 잘못 본다. 관측 반경(r_obs_m) 안에서만 벌어지는 두 길은 같은 것을 보며 걷는 같은 길이다
double path_separation(const bt_ctx* c, const bt_cell* a, uint32_t na, double res_a, const bt_cell* b, uint32_t nb, double res_b) {
  const Geom ga{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, res_a, 0, 0};
  const Geom gb{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, res_b, 0, 0};
  double worst = 0.0;
  for (int side = 0; side < 2; ++side) {            // 상한: 2 · na · nb
    const bt_cell* p = side ? b : a; const bt_cell* q = side ? a : b;
    const uint32_t np = side ? nb : na, nq = side ? na : nb;
    const Geom& gp = side ? gb : ga; const Geom& gq = side ? ga : gb;
    for (uint32_t i = 0; i < np; ++i) {
      const bt_xy x = cell_center(gp, p[i].row, p[i].col);
      double best = D_INF;
      for (uint32_t j = 0; j < nq; ++j) {
        const bt_xy y = cell_center(gq, q[j].row, q[j].col);
        const double d2 = (x.x - y.x) * (x.x - y.x) + (x.y - y.y) * (x.y - y.y);
        if (d2 < best) best = d2;
      }
      if (best > worst) worst = best;
    }
  }
  return std::sqrt(worst);
}

// 정지점 사이를 플래너로 이어 경로 풀의 off부터 쓴다. 정지점이 없으면 지금 선 칸 하나.
// 구간마다 칸 크기가 달라지면(*mixed) 한 경로로 이을 수 없다
bool build_route_ex(bt_ctx* c, bt_xy start, const bt_stop* stops, uint32_t n, uint32_t off, uint32_t* out_len,
                    double* out_res, bool refine, bool* mixed) {
  Decide& D = c->dec;
  const Geom g = cm_geom(c);
  *mixed = false;
  if (off >= D.pool_cap) return false;
  if (n == 0) {
    int32_t r, col;
    if (!xy_to_cell(g, start, &r, &col)) return false;
    D.pool[off].row = r; D.pool[off].col = col;
    *out_len = 1;
    *out_res = g.res;
    return true;
  }
  bt_budget bud;
  std::memset(&bud, 0, sizeof(bud));              // 설정의 예산·ε 스케줄, 균형 성향
  uint32_t len = 0;
  double res = 0.0;
  bt_xy cur = start;
  for (uint32_t k = 0; k < n; ++k) {
    const uint32_t at = off + (len ? len - 1 : 0);  // 앞 구간의 끝 칸에서 이어 쓴다
    if (at >= D.pool_cap) return false;
    const bt_cell joint = D.pool[at];
    bt_path leg;
    std::memset(&leg, 0, sizeof(leg));
    leg.cells = D.pool + at;
    leg.cap = D.pool_cap - at;
    bud.profile = stops[k].profile < BT_MAX_PROFILES ? stops[k].profile : 0;   // 그 정지점까지 가는 길의 성향(갈림길에서 사람이 고른 것)
    if (plan_ex(c, cur, stops[k].xy, &bud, &leg, refine) < 0) return false;
    if (!path_reaches(c, &leg, stops[k].xy)) return false;   // 정지점에 닿지 못한 길(예산 소진, 반경 밖)로는 옵션을 만들지 않는다
    if (k == 0) {
      res = leg.res_m;
    } else if (std::fabs(leg.res_m - res) > 1e-9) {
      *mixed = true;
      return false;
    } else if (leg.cells[0].row != joint.row || leg.cells[0].col != joint.col) {
      return false;                                 // 이음매가 끊겼다
    }
    len = (at - off) + leg.len;
    const Geom pg{g.ox, g.oy, res, 0, 0};
    cur = cell_center(pg, D.pool[off + len - 1].row, D.pool[off + len - 1].col);
  }
  *out_len = len;
  *out_res = res;
  return true;
}

bool build_route(bt_ctx* c, bt_xy start, const bt_stop* stops, uint32_t n, uint32_t off, uint32_t* out_len, double* out_res) {
  bool mixed = false;
  if (build_route_ex(c, start, stops, n, off, out_len, out_res, true, &mixed)) return true;
  if (!mixed) return false;
  return build_route_ex(c, start, stops, n, off, out_len, out_res, false, &mixed);   // 전부 전역 격자로 다시 잇는다
}

// 정지점마다 경로에서 가장 가까운 칸의 번호 (앞 정지점보다 뒤에서 찾는다). 경로가 없으면 전부 0
bool stop_cells(const bt_ctx* c, const bt_path* path, const bt_stop* stops, uint32_t n, uint32_t* sidx) {
  const uint32_t len = (path && path->cells) ? path->len : 0;
  uint32_t from = 0;
  for (uint32_t j = 0; j < n; ++j) {
    double best = D_INF;
    uint32_t at = from;
    for (uint32_t i = from; i < len; ++i) {
      float e, sl; uint8_t los; bt_xy p;
      if (!cell_info(c, path->res_m, path->cells[i], &e, &sl, &los, &p)) return false;
      const double d2 = (p.x - stops[j].xy.x) * (p.x - stops[j].xy.x) + (p.y - stops[j].xy.y) * (p.y - stops[j].xy.y);
      if (d2 < best) { best = d2; at = i; }
    }
    sidx[j] = at;
    from = at;
  }
  return true;
}

// 그 자리에서 지금 돌아서면 남는 여유(초)를 worst에 반영한다. 로버까지 길이 없으면 false
bool margin_at(const bt_ctx* c, const FieldView& fv, bt_xy p, double limit, double k_ret, double t_there, double* worst, uint8_t* degraded) {
  double back;
  uint8_t deg;
  if (!return_seconds(c, fv, p, &back, &deg)) { *worst = -1e9; return false; }
  if (deg) *degraded = 1;
  const double margin = limit - (t_there + k_ret * back);
  if (margin < *worst) *worst = margin;
  return true;
}

// 후보 하나를 만들고 평가한다. 출발 한계를 넘기면 만들지 않는다 (late_ok면 넘겨도 만든다)
bool add_candidate(bt_ctx* c, const bt_state* st, uint8_t kind, uint8_t label_key, uint8_t flags,
                   const bt_stop* stops, uint32_t n_stops, bool late_ok) {
  Decide& D = c->dec;
  if (D.n_cand >= BT_MAX_CANDIDATES || n_stops > BT_MAX_STOPS) return false;
  const bt_config& cfg = c->cfg;
  const uint32_t off = D.pool_len;
  bt_option o;
  std::memset(&o, 0, sizeof(o));
  bt_path p;
  std::memset(&p, 0, sizeof(p));
  bt_path_metrics pm;
  bt_nlt nl;
  bt_stop own[BT_MAX_STOPS];
  double dwell = 0.0, back_s = 0.0;

  if (kind == BT_OPT_RETURN) {
    if (off >= D.pool_cap) return false;
    p.cells = D.pool + off;
    p.cap = D.pool_cap - off;
    if (bt_return_path(c, BT_FIELD_ROVER_RETURN, st->pos, &p) != BT_OK) return false;   // 탐색하지 않고 필드를 따라간다
    if (bt_path_measure(c, &p, st, BT_WALK_RETURN, &pm) != BT_OK) return false;
    if (bt_depart_limit(c, st, &nl) != BT_OK) return false;
    if (nl.slack_min < 0) {
      if (!late_ok) return false;
      flags = static_cast<uint8_t>(flags | BT_OPTF_LATE);      // 한계를 이미 넘긴 뒤의 귀환
    }
    FieldView fv;
    field_view(c, &fv);
    std::memset(own, 0, sizeof(own));
    own[0].xy = cell_center(fv.geom, p.cells[p.len - 1].row, p.cells[p.len - 1].col);
    own[0].purpose = BT_STOP_ROVER;
    own[0].poi = BT_POI_NONE;
    stops = own;
    n_stops = 1;
  } else {
    uint32_t len = 0;
    double res = 0.0;
    if (!build_route(c, st->pos, kind == BT_OPT_ROUTE ? stops : nullptr, kind == BT_OPT_ROUTE ? n_stops : 0, off, &len, &res)) return false;
    p.cells = D.pool + off; p.cap = len; p.len = len; p.res_m = res;
    if (bt_path_measure(c, &p, st, BT_WALK_PLAN, &pm) != BT_OK) return false;
    if (kind == BT_OPT_ROUTE && n_stops > 1) {
      // 들르는 정지점을 건너뛰어 곧게 펴면 안 된다 — 정지점을 꼭 지나는 선으로 시간·길이·두절을 다시 잰다
      uint32_t sidx[BT_MAX_STOPS];
      double sec = 0.0, length = 0.0, lost = 0.0;
      if (!stop_cells(c, &p, stops, n_stops, sidx)) return false;
      straight_measure(c, p.cells, p.len, p.res_m, BT_WALK_PLAN, sidx, n_stops, &sec, &length, &lost);
      pm.time_min = static_cast<float>(sec / 60.0);
      pm.length_m = static_cast<float>(length);
      pm.comm_loss_min = static_cast<float>(lost / 60.0);
    }
    if (bt_nlt_feasible(c, &p, stops, n_stops, st, &nl) != BT_OK) return false;
    if (nl.slack_min < 0) return false;                        // 출발 한계를 넘기는 옵션은 만들지 않는다
    for (uint32_t k = 0; k < n_stops; ++k) dwell += static_cast<double>(stops[k].dwell_min);
    FieldView fv;
    uint8_t deg;
    float e, sl; uint8_t los; bt_xy end;
    if (field_view(c, &fv) && cell_info(c, p.res_m, p.cells[p.len - 1], &e, &sl, &los, &end)) {
      if (!return_seconds(c, fv, end, &back_s, &deg)) back_s = 0.0;
    }
  }

  bt_path_value pv;
  std::memset(&pv, 0, sizeof(pv));
  if (c->sci.ready) bt_path_evaluate(c, &p, stops, n_stops, &pv);

  // 링크가 안 되는 자리에서 머무는 시간도 두절 시간에 넣는다 (걷는 구간만 세면 "머물기"의 두절이 0으로 나온다)
  double silent_dwell = 0.0;
  if (c->layer_set[BT_LAYER_LOS]) {
    const Geom lg = geom_of(c->cfg.cost_grid);
    for (uint32_t k = 0; k < n_stops; ++k) {
      int32_t r, col;
      if (!xy_to_cell(lg, stops[k].xy, &r, &col)) continue;
      if (!raster_bit(c->layer[BT_LAYER_LOS], 0, static_cast<uint64_t>(r) * lg.w + static_cast<uint64_t>(col))) silent_dwell += static_cast<double>(stops[k].dwell_min);
    }
  }
  const double total_min = static_cast<double>(pm.time_min) + dwell;
  o.kind = kind; o.label_key = label_key; o.flags = flags;
  if (pv.prior_only) o.flags = static_cast<uint8_t>(o.flags | BT_OPTF_PRIOR_ONLY);
  o.n_stops = static_cast<uint8_t>(n_stops);
  for (uint32_t k = 0; k < n_stops; ++k) o.stops[k] = stops[k];
  o.path_off = off; o.path_len = p.len;
  o.time_min = rnd(total_min, cfg.prec_time_min);
  o.max_slope_deg = rnd(pm.max_slope_deg, cfg.prec_max_slope_deg);
  o.dose_uSv = rnd(c->env.dose_rate_uSv_h * total_min / 60.0, cfg.prec_dose_uSv);
  o.value_mean = rnd(pv.value_mean, cfg.prec_value);
  // 가치 범위(lo~hi)는 가설 옵션에만 준다 (2026-11-14 결정). 가설이 아닌 옵션은 경로가 가설의 영향권을 스치더라도
  // 기대값 하나만 보인다 — 범위가 보이면 그 옵션도 가설에 기대는 것처럼 읽히기 때문이다
  const bool from_hyp = (flags & BT_OPTF_FROM_HYPOTHESIS) != 0;
  o.value_lo = from_hyp ? rnd(pv.value_lo, cfg.prec_value) : o.value_mean;
  o.value_hi = from_hyp ? rnd(pv.value_hi, cfg.prec_value) : o.value_mean;
  o.value_var = rnd(pv.value_var, cfg.prec_value_var);
  o.info_gain = rnd(pv.info_gain, cfg.prec_info_gain);
  o.explore_count = pv.explore_count;
  o.comm_loss_min = rnd(static_cast<double>(pm.comm_loss_min) + silent_dwell, cfg.prec_comm_loss_min);
  o.nlt_margin_min = rnd(nl.slack_min, cfg.prec_nlt_margin_min);
  o.return_time_min = rnd(back_s / 60.0, cfg.prec_time_min);
  o.nlt_binding = nl.binding;
  // 등급: 경로에서 가치가 가장 높은 칸의 값(가설이 맞았을 때 기준)을 grade_bins에 댄다
  o.value_grade = pv.peak < cfg.grade_bins[0] ? BT_GRADE_LOW : (pv.peak < cfg.grade_bins[1] ? BT_GRADE_MED : BT_GRADE_HIGH);
  if (pm.max_slope_deg > cfg.theta_max_deg) o.over_limit = static_cast<uint8_t>(o.over_limit | BT_OVER_MAX_SLOPE);
  if (cfg.dose_warn_uSv > 0 && o.dose_uSv > cfg.dose_warn_uSv) o.over_limit = static_cast<uint8_t>(o.over_limit | BT_OVER_DOSE);
  for (int k = 0; k < BT_OPTION_HYPS; ++k) o.hyp_seq[k] = from_hyp ? pv.hyp_seq[k] : static_cast<uint16_t>(0);
  o.n_reasons = 2;
  o.reasons[0].layer = BT_LAYER_SLOPE; o.reasons[0].value = pm.max_slope_deg;
  o.reasons[0].cell.row = -1; o.reasons[0].cell.col = -1; o.reasons[0].res_m = static_cast<float>(p.res_m);
  o.reasons[1].layer = BT_LAYER_MU0; o.reasons[1].value = pv.peak;
  o.reasons[1].cell.row = -1; o.reasons[1].cell.col = -1; o.reasons[1].res_m = static_cast<float>(c->sci.g.res);
  o.label = 255;

  D.cand[D.n_cand] = o;
  D.cand_res[D.n_cand] = p.res_m;
  D.n_cand += 1;
  D.pool_len = off + p.len;
  return true;
}

// 가설의 목표: 닻에서 direction 방향 extent·scale 거리 근처에서 delta가 가장 큰 통과 가능 칸.
// 그 가설을 넣은 뒤에 관측한 자리의 관측 반경(r_obs) 안은 목표로 삼지 않는다 — 거기는 이미 본 곳이다(2026-11-14 결정:
// "가설 목표는 거기서 관측을 남겨야 끝난다". 다녀오기만 하고 관측을 남기지 않았으면 다시 나온다 — 로그에 본 기록이 없기 때문이다).
// examined: 값이 오르는 칸이 있었지만 전부 이미 관측한 자리여서 목표가 없을 때 true
bool hyp_target(const bt_ctx* c, uint32_t k, double scale, bt_xy* out, bool* examined) {
  const Science& s = c->sci;
  const Hyp& h = s.hyp[k];
  const double L = static_cast<double>(h.extent_m) * scale;
  bt_xy center = h.anchor;
  double radius = L;
  if (h.rule != BT_RULE_PROXIMITY) {                 // 근접 군집은 방향을 쓰지 않는다
    const double th = static_cast<double>(h.dir_deg) / RAD2DEG;
    center.x += std::sin(th) * L;
    center.y += std::cos(th) * L;
    radius = static_cast<double>(c->cfg.hyp_snap_m);
  }
  *examined = false;

  // 이 가설보다 뒤에 들어온 관측 가운데 찾는 범위에 걸치는 것 (가설보다 앞선 관측은 "그 가설을 보러 간 것"이 아니다 — 확신 갱신과 같은 기준)
  constexpr uint32_t SEEN_MAX = 128;                 // 상한. 넘치면 뒤의 관측은 보지 않는다(그 자리가 다시 목표가 될 수 있다)
  bt_xy seen[SEEN_MAX];
  uint32_t n_seen = 0;
  const double r_obs = static_cast<double>(c->cfg.r_obs_m);
  for (uint32_t e = 0; e < c->log_n && n_seen < SEEN_MAX; ++e) {
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_OBS || !(ev.lts > h.lts)) continue;
    const double dx = ev.x - center.x, dy = ev.y - center.y, reach = radius + r_obs + s.g.res;
    if (dx * dx + dy * dy > reach * reach) continue;
    seen[n_seen].x = ev.x; seen[n_seen].y = ev.y;
    n_seen += 1;
  }

  const Geom cg = cm_geom(c);
  const int32_t c0 = static_cast<int32_t>(std::floor((center.x - radius - s.g.ox) / s.g.res));
  const int32_t c1 = static_cast<int32_t>(std::floor((center.x + radius - s.g.ox) / s.g.res));
  const int32_t r0 = static_cast<int32_t>(std::floor((s.g.oy - (center.y + radius)) / s.g.res));
  const int32_t r1 = static_cast<int32_t>(std::floor((s.g.oy - (center.y - radius)) / s.g.res));
  float best = 0.0f;
  bool found = false;
  for (int32_t r = r0 < 0 ? 0 : r0; r <= r1 && r < static_cast<int32_t>(s.g.h); ++r) {
    for (int32_t col = c0 < 0 ? 0 : c0; col <= c1 && col < static_cast<int32_t>(s.g.w); ++col) {
      const float d = static_cast<float>(hyp_delta_at(c, k, static_cast<uint32_t>(r) * s.g.w + static_cast<uint32_t>(col)));
      if (!(d > best)) continue;                     // 동률은 먼저 본 칸
      const bt_xy q = cell_center(s.g, r, col);
      int32_t pr, pc;
      if (!xy_to_cell(cg, q, &pr, &pc)) continue;
      if (!c->cm.passable[static_cast<uint32_t>(pr) * c->cm.w + static_cast<uint32_t>(pc)]) continue;
      bool already = false;
      for (uint32_t e = 0; e < n_seen && !already; ++e) already = near_m(q, seen[e], r_obs);
      if (already) { *examined = true; continue; }   // 이미 관측한 자리
      best = d; *out = q; found = true;
    }
  }
  return found;
}

// 목적 벡터 (전부 "작을수록 좋다"로 맞춘다): 시간, 최대 경사, 선량, 분산, -기대 가치, -정보 이득, -흔적 수
constexpr int N_OBJ = 7;
inline void objectives(const bt_option& o, double* v) {
  v[0] = o.time_min; v[1] = o.max_slope_deg; v[2] = o.dose_uSv; v[3] = o.value_var;
  v[4] = -static_cast<double>(o.value_mean); v[5] = -static_cast<double>(o.info_gain); v[6] = -static_cast<double>(o.explore_count);
}

// 후보에서 보여 줄 것을 고른다 (S3a §6.3). chosen[i] = 1
void pareto_select(const bt_ctx* c, uint8_t* chosen) {
  const Decide& D = c->dec;
  const uint32_t n = D.n_cand;
  double v[BT_MAX_CANDIDATES][N_OBJ];
  bool front[BT_MAX_CANDIDATES];
  for (uint32_t i = 0; i < n; ++i) { objectives(D.cand[i], v[i]); chosen[i] = 0; }
  for (uint32_t i = 0; i < n; ++i) {
    front[i] = true;
    for (uint32_t j = 0; j < n && front[i]; ++j) {
      if (j == i) continue;
      bool no_worse = true, better = false;
      for (int k = 0; k < N_OBJ; ++k) {
        if (v[j][k] > v[i][k]) no_worse = false;
        if (v[j][k] < v[i][k]) better = true;
      }
      if (no_worse && better) front[i] = false;      // j가 i를 지배한다
    }
  }
  uint32_t n_chosen = 0;
  const uint32_t max_n = c->cfg.options_max < BT_MAX_OPTIONS ? (c->cfg.options_max ? c->cfg.options_max : 1) : BT_MAX_OPTIONS;
  // 가설 옵션 1개는 지배당해도 넣는다 (R-22). 여러 개면 정보 이득이 가장 큰 것, 동률은 생성 순
  int hyp = -1;
  for (uint32_t i = 0; i < n; ++i) {
    if (D.cand[i].label_key != BT_LABEL_HYP_TARGET) continue;
    if (hyp < 0 || D.cand[i].info_gain > D.cand[hyp].info_gain) hyp = static_cast<int>(i);
  }
  if (hyp >= 0 && n_chosen < max_n) { chosen[hyp] = 1; n_chosen += 1; }
  for (uint32_t i = 0; i < n && n_chosen < max_n; ++i) {       // 철회한 사람이 돌아갈 길
    if ((D.cand[i].label_key == BT_LABEL_RESTORE_PLAN || D.cand[i].label_key == BT_LABEL_CUSTOM_PLAN) && !chosen[i]) { chosen[i] = 1; n_chosen += 1; }   // 사람이 짠 계획도 반드시 보인다
  }
  // 경로 갈림길에서 나온 길들: "계획 유지"(지금 성향의 길)와 나란히 보인다 — 어느 길로 갈지를 묻는 결정 지점이기 때문이다
  bool has_alt = false;
  for (uint32_t i = 0; i < n; ++i) if (D.cand[i].label_key == BT_LABEL_ROUTE_FASTEST || D.cand[i].label_key == BT_LABEL_ROUTE_GENTLE) has_alt = true;
  for (uint32_t i = 0; i < n && n_chosen < max_n; ++i) {
    if (D.cand[i].label_key == BT_LABEL_CONTINUE_PLAN && (front[i] || has_alt) && !chosen[i]) { chosen[i] = 1; n_chosen += 1; }
  }
  for (uint32_t i = 0; i < n && n_chosen < max_n; ++i) {
    if ((D.cand[i].label_key == BT_LABEL_ROUTE_FASTEST || D.cand[i].label_key == BT_LABEL_ROUTE_GENTLE) && !chosen[i]) { chosen[i] = 1; n_chosen += 1; }
  }
  // 나머지는 정규화한 목적 공간에서 이미 고른 것과 가장 먼 것부터
  double lo[N_OBJ], span[N_OBJ];
  for (int k = 0; k < N_OBJ; ++k) {
    lo[k] = D_INF;
    double hi = -D_INF;
    for (uint32_t i = 0; i < n; ++i) { if (v[i][k] < lo[k]) lo[k] = v[i][k]; if (v[i][k] > hi) hi = v[i][k]; }
    span[k] = hi - lo[k];
  }
  for (uint32_t round = 0; round < BT_MAX_OPTIONS && n_chosen < max_n; ++round) {
    int pick = -1;
    double pick_d = -1.0;
    for (uint32_t i = 0; i < n; ++i) {
      if (chosen[i] || !front[i]) continue;
      double dmin = D_INF;
      for (uint32_t j = 0; j < n; ++j) {
        if (!chosen[j]) continue;
        double d2 = 0.0;
        for (int k = 0; k < N_OBJ; ++k) {
          if (!(span[k] > 0)) continue;
          const double d = (v[i][k] - v[j][k]) / span[k];
          d2 += d * d;
        }
        if (d2 < dmin) dmin = d2;
      }
      if (n_chosen == 0) dmin = 0.0;                 // 아직 고른 것이 없으면 생성 순으로 첫 번째
      if (dmin > pick_d) { pick_d = dmin; pick = static_cast<int>(i); }   // 동률은 생성 순
    }
    if (pick < 0) break;
    chosen[pick] = 1;
    n_chosen += 1;
  }
}

inline bool same_numbers(const bt_option& a, const bt_option& b) {
  return a.time_min == b.time_min && a.max_slope_deg == b.max_slope_deg && a.dose_uSv == b.dose_uSv &&
         a.value_mean == b.value_mean && a.value_var == b.value_var && a.value_lo == b.value_lo &&
         a.value_hi == b.value_hi && a.info_gain == b.info_gain && a.explore_count == b.explore_count &&
         a.comm_loss_min == b.comm_loss_min && a.nlt_margin_min == b.nlt_margin_min;
}

uint64_t inputs_digest(const bt_ctx* c, const bt_state* st, const bt_stop* plan, uint32_t n_plan,
                       const bt_stop* prev, uint32_t n_prev, const bt_trigger* tr) {
  uint64_t h = FNV_OFFSET;
  const uint64_t cd = bt_config_digest(c), ld = bt_log_digest(c);
  h = fnv(h, cd); h = fnv(h, ld);
  h = fnv(h, st->t); h = fnv(h, st->pos.x); h = fnv(h, st->pos.y); h = fnv(h, st->heading_deg); h = fnv(h, st->sigma);
  h = fnv(h, st->dose_cum_uSv); h = fnv(h, st->link_mode); h = fnv(h, st->node);
  h = fnv(h, c->env.sun_elev_deg); h = fnv(h, c->env.sun_az_deg); h = fnv(h, c->env.t_sunset_s);
  h = fnv(h, c->env.tau_dust); h = fnv(h, c->env.dose_rate_uSv_h); h = fnv(h, c->env.shadow_bin); h = fnv(h, c->env.spe);
  for (uint32_t pass = 0; pass < 2; ++pass) {
    const bt_stop* s = pass ? prev : plan;
    const uint32_t n = pass ? n_prev : n_plan;
    h = fnv(h, n);
    for (uint32_t k = 0; k < n; ++k) {
      h = fnv(h, s[k].xy.x); h = fnv(h, s[k].xy.y); h = fnv(h, s[k].dwell_min); h = fnv(h, s[k].purpose); h = fnv(h, s[k].poi); h = fnv(h, s[k].profile);
    }
  }
  h = fnv(h, tr->kind); h = fnv(h, tr->forced); h = fnv(h, tr->cause_kind); h = fnv(h, tr->cause_lts); h = fnv(h, tr->cause_node);
  return h;
}

}  // namespace

// 경로를 걷는 도중 어디서든 돌아서도 제때 로버에 닿는가. 가장 빠듯한 자리의 여유를 낸다.
// 걷는 시간은 곧게 편 선으로 잰다(정지점은 꼭 지난다). 여유를 보는 자리: 출발점, 꺾이는 점 전부, 정지점(머문 뒤), 끝,
// 그리고 긴 직선 구간 안에서는 경로의 1/16마다. 직선 구간 안에서 여유는 고르게 변하므로 그 사이의 값은 양 끝 값 사이에 있다
bt_status bt_nlt_feasible(const bt_ctx* c, const bt_path* path, const bt_stop* stops, uint32_t n,
                          const bt_state* st, bt_nlt* out) {
  if (!c || !st || !out || (!stops && n > 0) || n > BT_MAX_STOPS) return BT_ERR_ARG;
  FieldView fv;
  if (!field_view(c, &fv) || !c->env_set) return BT_ERR_NOT_READY;
  uint8_t binding;
  const double limit = depart_deadline(c, &binding);
  const double k_ret = static_cast<double>(c->cfg.k_return);
  const uint32_t len = (path && path->cells) ? path->len : 0;
  double worst = D_INF;
  uint8_t degraded = 0;
  uint32_t sidx[BT_MAX_STOPS];
  if (!stop_cells(c, path, stops, n, sidx)) return BT_ERR_ARG;

  double tau = 0.0;
  uint32_t j = 0;
  bool ok = true;
  if (len == 0) {                                    // 걷지 않는다(머물기): 머문 뒤 지금 자리에서
    for (; j < n; ++j) tau += static_cast<double>(stops[j].dwell_min) * 60.0;
    ok = margin_at(c, fv, st->pos, limit, k_ret, st->t + tau, &worst, &degraded);
  } else {
    const Geom pg{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, path->res_m, 0, 0};
    const uint32_t stride = len > 16 ? len / 16 : 1;
    while (j < n && sidx[j] == 0) { tau += static_cast<double>(stops[j].dwell_min) * 60.0; j += 1; }
    ok = margin_at(c, fv, cell_center(pg, path->cells[0].row, path->cells[0].col), limit, k_ret, st->t + tau, &worst, &degraded);
    uint32_t anchor = 0, pin = 0;
    while (ok && anchor + 1 < len) {                 // 상한: 경로의 칸 수
      while (pin < n && sidx[pin] <= anchor) pin += 1;
      const uint32_t reach = straight_reach(c, path->cells, len, path->res_m, anchor, pin < n ? sidx[pin] : len - 1);
      const bt_xy a = cell_center(pg, path->cells[anchor].row, path->cells[anchor].col);
      const bt_xy b = cell_center(pg, path->cells[reach].row, path->cells[reach].col);
      const double seg = straight_seconds(c, a, b, path->res_m, BT_WALK_PLAN, nullptr, nullptr);
      for (uint32_t i = anchor + 1; ok && i < reach; ++i) {     // 긴 직선 구간 안의 표본
        if (i % stride != 0) continue;
        const double f = static_cast<double>(i - anchor) / static_cast<double>(reach - anchor);
        ok = margin_at(c, fv, bt_xy{a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f}, limit, k_ret, st->t + tau + seg * f, &worst, &degraded);
      }
      tau += seg;
      while (j < n && sidx[j] == reach) { tau += static_cast<double>(stops[j].dwell_min) * 60.0; j += 1; }
      if (ok) ok = margin_at(c, fv, b, limit, k_ret, st->t + tau, &worst, &degraded);
      anchor = reach;
    }
  }
  (void)ok;
  out->t_depart = st->t + worst;
  out->slack_min = static_cast<float>(worst / 60.0);
  out->binding = binding;
  out->degraded = degraded;
  return BT_OK;
}

bt_status bt_triggers(bt_ctx* c, const bt_state* now, const bt_state* prev, const bt_trigger_in* in,
                      bt_trigger* out, uint32_t cap, uint32_t* n) {
  (void)prev;
  if (!c || !now || !in || !n || (!out && cap > 0)) return BT_ERR_ARG;
  if (in->n_changed > BT_MAX_CHANGED || in->n_safety > BT_MAX_TRIGGERS) return BT_ERR_ARG;
  *n = 0;
  Decide& D = c->dec;
  bt_trigger t[BT_MAX_TRIGGERS + 6];
  uint32_t k = 0;
  std::memset(t, 0, sizeof(t));

  bool safety = false;
  bool new_leg_fork = false;                          // 이번에 낸 경로 갈림길이 "새 구간"의 것인가 (아래의 다시-내지-않기 규칙에서 뺀다)
  for (uint32_t i = 0; i < in->n_safety; ++i) if (in->safety[i].kind == BT_TRIG_SAFETY) safety = true;

  // 환경의 직전 값은 컨텍스트가 기억한다
  bool dust = false, shadow = false;
  if (c->env_set) {
    if (D.env_seen) {
      // 먼지: 임계를 넘은 채로 dust_hold_s가 지나야 "넘었다"고 보고 한 번 묻는다. 임계 근처에서 잠깐 넘었다 내려오는 것
      // (측정 한 번의 흔들림)으로는 묻지 않는다. 한 번 물은 뒤에는 임계 아래로 내려갔다 다시 넘어야 또 묻는다.
      const double warn = static_cast<double>(c->cfg.dust_tau_warn);
      if (warn > 0 && c->env.tau_dust > warn) {
        if (!D.dust_above) { D.dust_above = 1; D.dust_fired = 0; D.dust_since = now->t; }
        if (!D.dust_fired && now->t - D.dust_since >= static_cast<double>(c->cfg.dust_hold_s)) { dust = true; D.dust_fired = 1; }
      } else {
        D.dust_above = 0;
      }
      shadow = c->env.shadow_bin != D.prev_bin;
    }
    if (!D.env_seen && c->cfg.dust_tau_warn > 0 && c->env.tau_dust > static_cast<double>(c->cfg.dust_tau_warn)) {
      D.dust_above = 1; D.dust_fired = 1;             // 처음부터 임계 위였다: 바뀐 것이 아니므로 묻지 않는다(화면의 경고 표시는 떠 있다)
    }
    D.env_seen = 1; D.prev_tau = c->env.tau_dust; D.prev_bin = c->env.shadow_bin;
  }

  if (safety) {                                       // 안전이 있으면 그것만
    for (uint32_t i = 0; i < in->n_safety; ++i) if (in->safety[i].kind == BT_TRIG_SAFETY) t[k++] = in->safety[i];
  } else {
    for (uint32_t i = 0; i < in->n_safety; ++i) t[k++] = in->safety[i];     // 일몰 여유(ENV)
    if (in->user_request) { t[k].kind = BT_TRIG_USER_REQUEST; t[k].cause_kind = BT_CAUSE_RETURN; k += 1; }
    if (in->link_lost) { t[k].kind = BT_TRIG_LINK_LOST; t[k].cause_kind = BT_CAUSE_LINK; k += 1; }
    if (dust) { t[k].kind = BT_TRIG_ENV; t[k].cause_kind = BT_CAUSE_DUST; k += 1; }
    if (shadow) { t[k].kind = BT_TRIG_ENV; t[k].cause_kind = BT_CAUSE_SHADOW; k += 1; }

    // ① 지도를 바꾼 이벤트(관측, 승인된 가설, 가설 철회). 여럿이면 가장 뒤의 것을 원인으로 적는다
    bool by_event = false;
    for (uint32_t i = in->n_changed; i-- > 0 && !by_event;) {
      const bt_event* ev = log_find(c, in->changed[i].lts, in->changed[i].node);
      if (!ev) continue;
      const bool hyp = ev->type == BT_EV_HYP && ((ev->flags & BT_EVF_APPROVED) || ev->aux != 0);
      if (ev->type != BT_EV_OBS && !hyp) continue;
      t[k].kind = BT_TRIG_FORK;
      t[k].cause_kind = ev->type == BT_EV_OBS ? BT_CAUSE_OBS : BT_CAUSE_HYP;
      t[k].cause_lts = ev->lts; t[k].cause_node = ev->node;
      k += 1;
      by_event = true;
    }
    // ① 경로 갈림길: 다음 정지점이 바뀌었을 때 한 번 본다. 선택지를 만드는 인스턴스(로버)만
    if (!by_event && in->has_next_stop && c->cfg.options_mode == BT_OPTMODE_PARETO && c->cm.built && c->s.g &&
        (!D.route_seen || D.route_stop.x != in->next_stop.x || D.route_stop.y != in->next_stop.y)) {
      D.route_seen = 1;
      D.route_stop = in->next_stop;
      bt_path alt[BT_MAX_PROFILES];
      std::memset(alt, 0, sizeof(alt));
      for (int p = 0; p < BT_MAX_PROFILES; ++p) { alt[p].cells = D.alt + static_cast<uint64_t>(p) * D.alt_per; alt[p].cap = D.alt_per; }
      bt_budget bud;
      std::memset(&bud, 0, sizeof(bud));
      uint32_t na = 0;
      // 비용을 같은 자로 재야 하므로 전역 격자에서만 푼다 (고운 격자 정밀화 없이)
      if (alternatives_ex(c, now->pos, in->next_stop, &bud, alt, BT_MAX_PROFILES, &na, false) == BT_OK && na >= 2) {
        double c0, len0;
        if (cells_cost(c, alt[0].cells, alt[0].len, 0, &c0, &len0) && c0 > 0) {
          for (uint32_t a = 1; a < na; ++a) {
            double ca, la;
            if (!cells_cost(c, alt[a].cells, alt[a].len, 0, &ca, &la)) continue;
            if (std::fabs(ca - c0) / c0 < static_cast<double>(c->cfg.eps_fork) &&       // 서로 다른 경로의 비용이 비슷하고
                path_separation(c, alt[0].cells, alt[0].len, alt[0].res_m, alt[a].cells, alt[a].len, alt[a].res_m)
                    > static_cast<double>(c->cfg.r_obs_m)) {                                 // 실제로 다른 곳을 지난다
              t[k].kind = BT_TRIG_FORK; t[k].cause_kind = BT_CAUSE_ROUTE; k += 1;
              new_leg_fork = true;
              break;
            }
          }
        }
      }
    }
  }

  // 같은 (종류, 원인)의 결정 지점이 열려 있거나 cooldown 안이면 다시 내지 않는다
  uint32_t m = 0;
  for (uint32_t i = 0; i < k; ++i) {
    bool skip = false;
    // 새 구간의 경로 갈림길은 앞 구간의 것과 원인 표시(종류·원인)가 같아도 다른 물음이다. 구간마다 한 번만 보므로(route_seen)
    // 여기서 걸러 버리면 그 구간의 갈림길은 다시 나오지 않는다 → 열려 있는 앞 구간의 카드나 cooldown에 막히지 않게 한다
    const bool fresh = new_leg_fork && t[i].kind == BT_TRIG_FORK && t[i].cause_kind == BT_CAUSE_ROUTE;
    if (t[i].kind != BT_TRIG_LINK_LOST && !fresh) {
      if (D.open && same_trigger(D.open_trig, t[i])) skip = true;
      const uint32_t nc = D.cool_n < COOL_N ? D.cool_n : COOL_N;
      for (uint32_t j = 0; j < nc && !skip; ++j) {
        if (same_trigger(D.cool_trig[j], t[i]) && now->t - D.cool_ts[j] < static_cast<double>(c->cfg.cooldown_s) && now->t >= D.cool_ts[j]) skip = true;
      }
    }
    if (skip) continue;
    if (m >= cap) return BT_ERR_CAPACITY;
    out[m] = t[i];
    m += 1;
  }
  *n = m;
  return BT_OK;
}

bt_status bt_decide(bt_ctx* c, const bt_state* st, const bt_stop* plan, uint32_t n_plan,
                    const bt_stop* prev_plan, uint32_t n_prev, const bt_trigger* tr, bt_decision* out) {
  if (!c || !st || !tr || !out || (!plan && n_plan > 0) || (!prev_plan && n_prev > 0)) return BT_ERR_ARG;
  if (n_plan > BT_MAX_STOPS || n_prev > BT_MAX_STOPS || tr->kind > BT_TRIG_USER_REQUEST || tr->kind == BT_TRIG_LINK_LOST) return BT_ERR_ARG;
  FieldView fv;
  if (!field_view(c, &fv) || !c->env_set) return BT_ERR_NOT_READY;
  // 사람이 직접 짠 계획을 견줘 달라는 요청: prev_plan 자리에 그 정지점들이 온다. 다른 선택지와 나란히 계산해 보인다
  const bool custom = tr->kind == BT_TRIG_USER_REQUEST && tr->cause_kind == BT_CAUSE_PLAN;
  const bool return_only = (tr->kind == BT_TRIG_SAFETY || (tr->kind == BT_TRIG_USER_REQUEST && !custom));
  if (!return_only) {
    if (c->cfg.options_mode != BT_OPTMODE_PARETO) return BT_ERR_ARG;        // 선택지는 로버만 만든다
    if (!c->cm.built || !c->s.g || !c->sci.ready) return BT_ERR_NOT_READY;
  }
  Decide& D = c->dec;
  const bt_config& cfg = c->cfg;
  std::memset(out, 0, sizeof(*out));
  D.pool_len = 0;
  D.n_cand = 0;
  D.seq_counter += 1;
  D.cand_seq = D.seq_counter;
  out->seq = D.seq_counter;
  out->trigger = tr->kind; out->cause_kind = tr->cause_kind; out->forced = tr->forced;
  out->cause_lts = tr->cause_lts; out->cause_node = tr->cause_node;
  out->node = cfg.node; out->ts = st->t;

  if (!return_only) {
    // 후보는 생성 순 = 라벨 순으로 고정: 계획 유지 → (갈림길이면) 가장 빠른 길·완만한 길 → 가설 → 되돌리기 → 마지막 포기 → 머물기 → 귀환
    if (n_plan > 0) add_candidate(c, st, BT_OPT_ROUTE, BT_LABEL_CONTINUE_PLAN, 0, plan, n_plan, false);

    // 경로 갈림길: 다음 정지점까지를 다른 성향으로 가는 길을 선택지로 낸다. 결정 지점을 띄운 까닭("비슷한 길이 둘 이상 있다")과
    // 묻는 내용이 같아야 한다. 정지점은 그대로이고 첫 정지점의 성향만 다르다. 표시 수치가 이미 나온 길과 전부 같으면 내지 않는다
    if (n_plan > 0 && tr->kind == BT_TRIG_FORK && tr->cause_kind == BT_CAUSE_ROUTE && D.n_cand > 0) {
      const uint8_t alt_profile[2] = {1, 2};
      const uint8_t alt_label[2] = {BT_LABEL_ROUTE_FASTEST, BT_LABEL_ROUTE_GENTLE};
      for (int a = 0; a < 2; ++a) {
        if (plan[0].profile == alt_profile[a]) continue;           // 지금 계획이 이미 그 성향이다 = "계획 유지"와 같은 길
        bt_stop alt[BT_MAX_STOPS];
        for (uint32_t k = 0; k < n_plan; ++k) alt[k] = plan[k];
        alt[0].profile = alt_profile[a];
        const uint32_t n_before = D.n_cand, pool_before = D.pool_len;
        if (!add_candidate(c, st, BT_OPT_ROUTE, alt_label[a], 0, alt, n_plan, false)) continue;
        bool dup = false;
        const bt_option& nw = D.cand[n_before];
        for (uint32_t i = 0; i < n_before && !dup; ++i) {
          const bt_option& old = D.cand[i];
          dup = same_numbers(old, nw) ||
                path_separation(c, D.pool + old.path_off, old.path_len, D.cand_res[i], D.pool + nw.path_off, nw.path_len, D.cand_res[n_before])
                    <= static_cast<double>(cfg.r_obs_m);
        }
        if (dup) { D.n_cand = n_before; D.pool_len = pool_before; }   // 눈에 같은 길 → 뺀다
      }
    }

    const bool want_restore = !custom && n_prev > 0 && !same_stops(prev_plan, n_prev, plan, n_plan);
    const bool want_custom = custom && n_prev > 0 && !same_stops(prev_plan, n_prev, plan, n_plan);   // 지금 계획과 같으면 "계획 유지"다
    const uint32_t reserve = ((want_restore || want_custom) ? 1u : 0u) + (n_plan >= 2 ? 1u : 0u) + 2u;
    const uint32_t room = BT_MAX_CANDIDATES > D.n_cand + reserve ? BT_MAX_CANDIDATES - D.n_cand - reserve : 0;
    const uint32_t nh = c->sci.n_hyps;
    bool hyp_late = false, hyp_flat = false;                                // 가설 옵션이 못 나온 까닭: 출발 한계 / 지도에 더한 것이 없음
    for (uint32_t k = nh > room ? nh - room : 0; k < nh; ++k) {             // 넘치면 최신 가설만
      bool made = false, has_target = false, examined = false;
      const double scales[3] = {1.0, 0.5, 0.25};                            // 출발 한계에 안 맞으면 범위를 줄여 본다
      for (int si = 0; si < 3 && !made; ++si) {
        bt_stop stops[BT_MAX_STOPS];
        std::memset(stops, 0, sizeof(stops));
        bool ex = false;
        const bool got = hyp_target(c, k, scales[si], &stops[0].xy, &ex);
        if (ex) examined = true;
        if (!got) continue;
        has_target = true;
        // 이미 그 목표에 와 있거나(관측 반경 안), 계획이 이미 그 목표를 들르면 "가설 목표로"를 따로 만들지 않는다.
        // 만들면 "계획 유지"와 눈에 같은 선택지(같은 길, 같은 시간)가 하나 더 생긴다. 닿을 수 없어서 빠진 것이 아니므로 알림도 내지 않는다
        bool covered = near_m(st->pos, stops[0].xy, static_cast<double>(cfg.r_obs_m));
        for (uint32_t j = 0; j < n_plan && !covered; ++j) covered = near_m(plan[j].xy, stops[0].xy, static_cast<double>(cfg.r_obs_m));
        if (covered) { made = true; break; }
        stops[0].purpose = BT_STOP_HYP_TARGET;
        stops[0].poi = BT_POI_NONE;
        const uint32_t keep_max = n_plan < BT_MAX_STOPS - 1 ? n_plan : BT_MAX_STOPS - 1;
        for (uint32_t keep = keep_max + 1; keep-- > 0 && !made;) {          // 안 맞으면 뒤에서부터 정지점을 뺀다
          for (uint32_t j = 0; j < keep; ++j) stops[1 + j] = plan[j];
          made = add_candidate(c, st, BT_OPT_ROUTE, BT_LABEL_HYP_TARGET, BT_OPTF_FROM_HYPOTHESIS, stops, 1 + keep, false);
        }
      }
      // 까닭을 가려서 알린다: 목표는 있는데 출발 한계에 안 맞는 것과, 가설이 그 방향의 값을 올리지 않아 목표 자체가 없는 것은 다르다
      // 목표가 될 자리를 이미 다 관측했으면 알릴 것이 없다 — 그 가설은 본 것이다
      if (!made) { if (has_target) hyp_late = true; else if (!examined) hyp_flat = true; }
    }
    if (hyp_late) out->notices = static_cast<uint16_t>(out->notices | BT_NOTICE_HYP_UNREACHABLE);
    if (hyp_flat) out->notices = static_cast<uint16_t>(out->notices | BT_NOTICE_HYP_NO_EFFECT);

    if (want_restore) add_candidate(c, st, BT_OPT_ROUTE, BT_LABEL_RESTORE_PLAN, 0, prev_plan, n_prev, false);
    // 사람이 짠 계획: 출발 한계를 넘기거나 길이 없으면 만들지 않고(넘기는 옵션은 만들지 않는다) 그 사실을 알린다
    if (want_custom && !add_candidate(c, st, BT_OPT_ROUTE, BT_LABEL_CUSTOM_PLAN, 0, prev_plan, n_prev, false))
      out->notices = static_cast<uint16_t>(out->notices | BT_NOTICE_CUSTOM_UNREACHABLE);
    if (n_plan >= 2) add_candidate(c, st, BT_OPT_ROUTE, BT_LABEL_DROP_LAST, 0, plan, n_plan - 1, false);

    bt_nlt nl;
    if (bt_depart_limit(c, st, &nl) == BT_OK) {
      double dwell = static_cast<double>(nl.slack_min) - static_cast<double>(cfg.stay_buffer_min);
      if (dwell > static_cast<double>(cfg.stay_max_min)) dwell = static_cast<double>(cfg.stay_max_min);
      if (dwell > 0) {
        bt_stop stay;
        std::memset(&stay, 0, sizeof(stay));
        stay.xy = st->pos; stay.dwell_min = static_cast<float>(dwell); stay.purpose = BT_STOP_LANDMARK; stay.poi = BT_POI_NONE;
        add_candidate(c, st, BT_OPT_STAY, BT_LABEL_STAY, 0, &stay, 1, false);
      }
    }
  }
  add_candidate(c, st, BT_OPT_RETURN, BT_LABEL_RETURN_ROVER, 0, nullptr, 0, false);

  if (D.n_cand == 0) {
    // 통과한 옵션이 없다 = 출발 한계를 이미 넘겼다. 가장 빠른 귀환 하나를 "늦음"으로 강제한다
    if (add_candidate(c, st, BT_OPT_RETURN, BT_LABEL_RETURN_ROVER, 0, nullptr, 0, true)) {
      out->forced = 1;
    } else {
      out->notices = static_cast<uint16_t>(out->notices | BT_NOTICE_NO_FEASIBLE_RETURN);   // 로버까지 길이 없다
    }
  }

  uint8_t chosen[BT_MAX_CANDIDATES];
  for (uint32_t i = 0; i < BT_MAX_CANDIDATES; ++i) chosen[i] = 0;
  if (return_only || D.n_cand <= 1) {
    for (uint32_t i = 0; i < D.n_cand && i < BT_MAX_OPTIONS; ++i) chosen[i] = 1;
  } else {
    pareto_select(c, chosen);
  }
  uint32_t no = 0;
  for (uint32_t i = 0; i < D.n_cand; ++i) {
    if (chosen[i] && no < BT_MAX_OPTIONS) { D.cand[i].label = static_cast<uint8_t>(no); no += 1; }
    D.cand[i].digest = bt_option_digest(&D.cand[i]);
  }
  no = 0;
  for (uint32_t i = 0; i < D.n_cand; ++i) {
    if (D.cand[i].label != 255 && no < BT_MAX_OPTIONS) { out->options[no] = D.cand[i]; no += 1; }
  }
  out->n_options = static_cast<uint8_t>(no);

  // 경로 갈림길인데 고를 다른 길이 하나도 남지 않았으면 묻지 않는다 — 띄운 까닭과 묻는 내용이 어긋난 카드를 내지 않는다
  if (tr->kind == BT_TRIG_FORK && tr->cause_kind == BT_CAUSE_ROUTE) {
    bool any_alt = false;
    for (uint32_t i = 0; i < no; ++i) if (out->options[i].label_key == BT_LABEL_ROUTE_FASTEST || out->options[i].label_key == BT_LABEL_ROUTE_GENTLE) any_alt = true;
    if (!any_alt) { out->n_options = 0; no = 0; }
  }
  // 경로 갈림길인데 표시 수치가 전부 같으면 묻지 않는다 (S3a §6.4)
  if (tr->kind == BT_TRIG_FORK && tr->cause_kind == BT_CAUSE_ROUTE && no >= 2) {
    bool all_same = true;
    for (uint32_t i = 1; i < no; ++i) if (!same_numbers(out->options[0], out->options[i])) all_same = false;
    if (all_same) {
      const uint32_t seq = out->seq;
      std::memset(out, 0, sizeof(*out));
      out->seq = seq;
      D.n_cand = 0;
      return BT_OK;
    }
  }

  out->inputs_digest = inputs_digest(c, st, plan, n_plan, prev_plan, n_prev, tr);
  out->digest = bt_decision_digest(out);
  if (no > 0) {                                       // 새 결정 지점은 열려 있던 것을 대체한다
    D.open = 1; D.open_seq = out->seq; D.open_trig = *tr;
    const uint32_t slot = D.cool_n % COOL_N;
    D.cool_trig[slot] = *tr; D.cool_ts[slot] = st->t;
    D.cool_n += 1;                                    // 고리 버퍼: 가장 오래된 기록부터 덮어쓴다
  }
  return BT_OK;
}

bt_status bt_decision_close(bt_ctx* c, uint32_t dp_seq) {
  if (!c) return BT_ERR_NOT_READY;
  if (c->dec.open && c->dec.open_seq == dp_seq) c->dec.open = 0;
  return BT_OK;
}

bt_status bt_decision_path(const bt_ctx* c, const bt_decision* d, uint32_t option_index, bt_path* out) {
  if (!c || !d || !out || !out->cells || option_index >= d->n_options) return BT_ERR_ARG;
  const Decide& D = c->dec;
  if (d->seq != D.cand_seq) return BT_ERR_ARG;        // 방금 낸 결정 지점의 경로만 꺼낼 수 있다
  const bt_option& o = d->options[option_index];
  if (static_cast<uint64_t>(o.path_off) + o.path_len > D.pool_len) return BT_ERR_ARG;
  if (o.path_len > out->cap) return BT_ERR_CAPACITY;
  std::memcpy(out->cells, D.pool + o.path_off, static_cast<uint64_t>(o.path_len) * sizeof(bt_cell));
  double res = c->cm.res;
  for (uint32_t i = 0; i < D.n_cand; ++i) if (D.cand[i].path_off == o.path_off && D.cand[i].path_len == o.path_len) res = D.cand_res[i];
  double length = 0.0;
  for (uint32_t i = 1; i < o.path_len; ++i) {
    const bt_cell a = out->cells[i], q = out->cells[i - 1];
    length += ((a.row != q.row && a.col != q.col) ? SQRT2 : 1.0) * res;
  }
  out->len = o.path_len; out->res_m = res; out->length_m = length; out->cost = 0.0;
  out->eps_bound = 1.0f; out->expansions = 0; out->complete = 1; out->snapped_m = 0.0;
  return BT_OK;
}

bt_status bt_decision_candidates(const bt_ctx* c, const bt_decision* d, bt_option* out, uint32_t cap, uint32_t* n) {
  if (!c || !d || !n || (!out && cap > 0)) return BT_ERR_ARG;
  const Decide& D = c->dec;
  if (d->seq != D.cand_seq) return BT_ERR_ARG;
  if (D.n_cand > cap) return BT_ERR_CAPACITY;
  for (uint32_t i = 0; i < D.n_cand; ++i) out[i] = D.cand[i];
  *n = D.n_cand;
  return BT_OK;
}
