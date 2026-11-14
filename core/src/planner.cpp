// C-21 지역 플래너 / C-31 국소 플래너: 가중 A*(anytime), 귀환 필드, 경로 수치 (S3a §3)
//
// 탐색은 언제나 "창" 안에서만 한다.
//  - 전역 격자: 창 = 시작점을 가운데 둔 (재계획 반경 × 2) 정사각형. 목표가 창 밖이면 창 안에서 목표에 가장 가까운 칸까지 푼다
//  - 거친 격자 먼저(coarse_first_grid_m): 전역 격자(거친 격자)에서 푼 경로를 구간으로 잘라, 구간마다 "구간 + 양옆 회랑"
//    크기의 고운 조각을 그때 만들어 다시 풀고 이어 붙인다. 고운 격자를 전역으로 만들지 않는다
#include "ctx.hpp"

using namespace bt;

namespace {

constexpr uint8_t FL_CLOSED = 0x80, FL_OPEN = 0x40, FL_DIR = 0x0F, FL_NODIR = 0x0F;

// 탐색이 보는 지도 한 장: 전역 코스트맵이거나 고운 조각. 칸은 그 격자의 전역 (row, col)로 부른다
struct MapView {
  const float* base[BT_MAX_PROFILES];
  const float* elev;
  const uint8_t* passable;
  int32_t r0, c0;
  uint32_t h, w;
  double res;
  float min_base[BT_MAX_PROFILES];
};

inline MapView cm_view(const bt_ctx* c) {
  MapView v;
  for (int p = 0; p < BT_MAX_PROFILES; ++p) { v.base[p] = c->cm.base[p]; v.min_base[p] = c->cm.min_base[p]; }
  v.elev = c->cm.elev; v.passable = c->cm.passable;
  v.r0 = 0; v.c0 = 0; v.h = c->cm.h; v.w = c->cm.w; v.res = c->cm.res;
  return v;
}
inline MapView tile_view(const bt_ctx* c, int32_t r0, int32_t c0, uint32_t h, uint32_t w, double res) {
  MapView v;
  for (int p = 0; p < BT_MAX_PROFILES; ++p) { v.base[p] = c->tile.base[p]; v.min_base[p] = c->tile.min_base[p]; }
  v.elev = c->tile.elev; v.passable = c->tile.passable;
  v.r0 = r0; v.c0 = c0; v.h = h; v.w = w; v.res = res;
  return v;
}
inline bool in_view(const MapView& v, int32_t r, int32_t c) {
  return r >= v.r0 && c >= v.c0 && r < v.r0 + static_cast<int32_t>(v.h) && c < v.c0 + static_cast<int32_t>(v.w);
}
inline uint32_t vi(const MapView& v, int32_t r, int32_t c) {
  return static_cast<uint32_t>(r - v.r0) * v.w + static_cast<uint32_t>(c - v.c0);
}
inline bool v_pass(const MapView& v, int32_t r, int32_t c) { return in_view(v, r, c) && v.passable[vi(v, r, c)]; }

inline bool in_win(const Search& s, int32_t r, int32_t c) {
  return r >= s.wr0 && c >= s.wc0 && r < s.wr0 + static_cast<int32_t>(s.wh) && c < s.wc0 + static_cast<int32_t>(s.ww);
}
inline uint32_t wi(const Search& s, int32_t r, int32_t c) {
  return static_cast<uint32_t>(r - s.wr0) * s.ww + static_cast<uint32_t>(c - s.wc0);
}
inline void set_window(bt_ctx* c, int32_t r0, int32_t c0, uint32_t h, uint32_t w) {
  c->s.wr0 = r0; c->s.wc0 = c0; c->s.wh = h; c->s.ww = w;
}
// (cr, cc)를 가운데 둔 창. 지도 밖으로 나가지 않게 민다
inline void center_window(bt_ctx* c, const MapView& v, int32_t cr, int32_t cc) {
  const uint32_t wh = v.h < c->s.side ? v.h : c->s.side, ww = v.w < c->s.side ? v.w : c->s.side;
  int32_t r0 = cr - static_cast<int32_t>(wh / 2), c0 = cc - static_cast<int32_t>(ww / 2);
  if (r0 < v.r0) r0 = v.r0;
  if (c0 < v.c0) c0 = v.c0;
  if (r0 + static_cast<int32_t>(wh) > v.r0 + static_cast<int32_t>(v.h)) r0 = v.r0 + static_cast<int32_t>(v.h) - static_cast<int32_t>(wh);
  if (c0 + static_cast<int32_t>(ww) > v.c0 + static_cast<int32_t>(v.w)) c0 = v.c0 + static_cast<int32_t>(v.w) - static_cast<int32_t>(ww);
  set_window(c, r0, c0, wh, ww);
}

inline void next_stamp(bt_ctx* c) {
  Search& s = c->s;
  if (s.cur == 0xFFFFFFFFu) {
    std::memset(s.stamp, 0, static_cast<uint64_t>(s.cap) * sizeof(uint32_t));
    s.cur = 0;
  }
  s.cur += 1;
  s.heap.clear();
}
inline void touch(Search& s, uint32_t i) {
  if (s.stamp[i] != s.cur) {
    s.stamp[i] = s.cur;
    s.g[i] = D_INF;
    s.t[i] = 0.0f;
    s.flag[i] = FL_NODIR;
  }
}

// (r, c)에서 방향 d로 한 칸 갈 수 있는가. 대각은 양쪽 직교 이웃이 모두 통과 가능할 때만
inline bool can_step(const MapView& v, int32_t r, int32_t c, int d, int32_t* nr, int32_t* nc) {
  const int32_t rr = r + DR[d], cc = c + DC[d];
  if (!v_pass(v, rr, cc)) return false;
  if ((d & 1) && (!v_pass(v, rr, c) || !v_pass(v, r, cc))) return false;
  *nr = rr; *nc = cc;
  return true;
}

// 진행 방향의 경사(°). 오르막 +
inline double step_slope(float e_from, float e_to, double dist_m) {
  if (!(e_from == e_from) || !(e_to == e_to)) return 0.0;
  return std::atan((static_cast<double>(e_to) - static_cast<double>(e_from)) / dist_m) * RAD2DEG;
}

inline double octile(int32_t r, int32_t c, int32_t gr, int32_t gc) {
  int32_t dr = r > gr ? r - gr : gr - r, dc = c > gc ? c - gc : gc - c;
  const int32_t mx = dr > dc ? dr : dc, mn = dr > dc ? dc : dr;
  return static_cast<double>(mx) + (SQRT2 - 1.0) * static_cast<double>(mn);
}

// 통과불가(또는 창 밖) 칸이면 snap_max_m 안에서 가장 가까운, 창 안의 통과 가능 칸으로 옮긴다
bool snap(const bt_ctx* c, const MapView& v, int32_t* r, int32_t* col, double* snapped_m) {
  const Search& s = c->s;
  *snapped_m = 0.0;
  if (in_win(s, *r, *col) && v_pass(v, *r, *col)) return true;
  const int32_t K = static_cast<int32_t>(static_cast<double>(c->cfg.snap_max_m) / v.res);
  double best = D_INF;
  int32_t br = 0, bc = 0;
  bool found = false;
  for (int32_t dr = -K; dr <= K; ++dr) {
    for (int32_t dc = -K; dc <= K; ++dc) {
      const int32_t rr = *r + dr, cc = *col + dc;
      if (!in_win(s, rr, cc) || !v_pass(v, rr, cc)) continue;
      const double d = std::sqrt(static_cast<double>(dr * dr + dc * dc)) * v.res;
      if (d <= static_cast<double>(c->cfg.snap_max_m) && d < best) { best = d; br = rr; bc = cc; found = true; }   // 동률은 먼저 본 칸
    }
  }
  if (!found) return false;
  *r = br; *col = bc; *snapped_m = best;
  return true;
}

// 목표가 창 밖일 때: 창 안의 통과 가능 칸 가운데 목표에 가장 가까운 칸
bool clip_to_window(const bt_ctx* c, const MapView& v, int32_t gr, int32_t gc, int32_t* r, int32_t* col) {
  const Search& s = c->s;
  double best = D_INF;
  bool found = false;
  for (uint32_t i = 0; i < s.wh; ++i) {
    for (uint32_t j = 0; j < s.ww; ++j) {
      const int32_t rr = s.wr0 + static_cast<int32_t>(i), cc = s.wc0 + static_cast<int32_t>(j);
      if (!v_pass(v, rr, cc)) continue;
      const double dr = static_cast<double>(rr - gr), dc = static_cast<double>(cc - gc);
      const double d = dr * dr + dc * dc;
      if (d < best) { best = d; *r = rr; *col = cc; found = true; }
    }
  }
  return found;
}

// 한 ε에 대한 A*. 목표를 꺼내면 true. 예산이 바닥나거나 힙이 비면 false (*exhausted로 구분)
bool astar_round(bt_ctx* c, const MapView& v, int32_t sr, int32_t sc, int32_t gr, int32_t gc, double eps, int profile,
                 double time_cap, uint32_t max_exp, uint32_t* expansions, bool* exhausted, bool* overflow) {
  Search& s = c->s;
  const float* base = v.base[profile];
  const double w_s = static_cast<double>(c->cfg.profiles[profile].w_s);
  const double f_min = 1.0 / slope_factor(-10.0);                  // 가장 빠른 경사의 시간 배율
  const double hscale = v.res * (w_s * f_min + static_cast<double>(v.min_base[profile]));
  const double v_plan = static_cast<double>(c->cfg.v_plan_kmh) / 3.6;
  const uint32_t s_idx = wi(s, sr, sc), g_idx = wi(s, gr, gc);
  *exhausted = false;
  *overflow = false;

  next_stamp(c);
  touch(s, s_idx);
  s.g[s_idx] = 0.0;
  {
    const double h0 = octile(sr, sc, gr, gc) * hscale;
    s.flag[s_idx] = static_cast<uint8_t>(FL_NODIR | FL_OPEN);
    s.heap.push(HeapEntry{eps * h0, static_cast<float>(h0), s_idx}, false);
  }
  while (s.heap.n > 0) {
    if (*expansions >= max_exp) { *exhausted = true; return false; }
    const HeapEntry top = s.heap.pop();
    const uint32_t i = top.idx;
    s.flag[i] = static_cast<uint8_t>((s.flag[i] & FL_DIR) | FL_CLOSED);
    if (i == g_idx) return true;
    *expansions += 1;
    const int32_t r = s.wr0 + static_cast<int32_t>(i / s.ww), col = s.wc0 + static_cast<int32_t>(i % s.ww);
    const uint32_t mi = vi(v, r, col);
    for (int d = 0; d < 8; ++d) {
      int32_t nr, nc;
      if (!can_step(v, r, col, d, &nr, &nc) || !in_win(s, nr, nc)) continue;
      const uint32_t n = wi(s, nr, nc);
      touch(s, n);
      if (s.flag[n] & FL_CLOSED) continue;
      const uint32_t mn = vi(v, nr, nc);
      const double dist = ((d & 1) ? SQRT2 : 1.0) * v.res;
      const double f = slope_factor(step_slope(v.elev[mi], v.elev[mn], dist));
      const double cost = dist * (w_s / f + (static_cast<double>(base[mi]) + static_cast<double>(base[mn])) * 0.5);
      const double g2 = s.g[i] + cost;
      if (!(g2 < s.g[n])) continue;
      const double t2 = static_cast<double>(s.t[i]) + dist / (v_plan * f);
      if (time_cap > 0 && t2 > time_cap) continue;
      const bool in_heap = (s.flag[n] & FL_OPEN) != 0;
      const double h = octile(nr, nc, gr, gc) * hscale;
      if (!s.heap.push(HeapEntry{g2 + eps * h, static_cast<float>(h), n}, in_heap)) { *overflow = true; return false; }
      s.g[n] = g2;
      s.t[n] = static_cast<float>(t2);
      s.flag[n] = static_cast<uint8_t>(d | FL_OPEN);
    }
  }
  return false;
}

// 방금 끝난 탐색의 부모 방향을 거슬러 경로를 쓴다
bt_status write_cells(const bt_ctx* c, double res, int32_t sr, int32_t sc, int32_t gr, int32_t gc,
                      bt_cell* cells, uint32_t cap, uint32_t* out_len, double* out_length) {
  const Search& s = c->s;
  const uint64_t limit = static_cast<uint64_t>(s.wh) * s.ww;
  uint32_t len = 1;
  int32_t r = gr, col = gc;
  while (r != sr || col != sc) {
    const int d = s.flag[wi(s, r, col)] & FL_DIR;
    if (d >= 8 || len > limit) return BT_ERR_ARG;
    r -= DR[d]; col -= DC[d];
    len += 1;
  }
  if (len > cap) return BT_ERR_CAPACITY;
  double length = 0.0;
  r = gr; col = gc;
  for (uint32_t k = len; k-- > 0;) {
    cells[k].row = r; cells[k].col = col;
    if (r == sr && col == sc) break;
    const int d = s.flag[wi(s, r, col)] & FL_DIR;
    length += ((d & 1) ? SQRT2 : 1.0) * res;
    r -= DR[d]; col -= DC[d];
  }
  *out_len = len;
  *out_length = length;
  return BT_OK;
}

struct Sol { uint32_t len; double length, cost; float eps_bound; uint8_t complete; };

// 지금 놓인 창 안에서 ε 스케줄대로 푼다. 시작·목표는 창 안의 통과 가능 칸이어야 한다
bt_status solve(bt_ctx* c, const MapView& v, int32_t sr, int32_t sc, int32_t gr, int32_t gc, int profile, double time_cap,
                const float* eps, uint32_t eps_n, uint32_t max_exp, uint32_t* expansions,
                bt_cell* cells, uint32_t cap, Sol* out) {
  bool found = false;
  double best = D_INF;
  float last_eps = 0.0f;
  out->len = 0; out->length = 0.0; out->cost = 0.0; out->eps_bound = 0.0f; out->complete = 0;
  const uint32_t g_idx = wi(c->s, gr, gc);
  for (uint32_t k = 0; k < eps_n; ++k) {          // 큰 ε → 빠른 첫 해, 이후 개선
    const double e = eps[k] >= 1.0f ? static_cast<double>(eps[k]) : 1.0;
    bool exhausted = false, overflow = false;
    const bool ok = astar_round(c, v, sr, sc, gr, gc, e, profile, time_cap, max_exp, expansions, &exhausted, &overflow);
    if (overflow) return BT_ERR_CAPACITY;
    if (!ok) {
      if (!exhausted && !found) return BT_ERR_UNREACHABLE;       // 길이 없다
      break;
    }
    if (!found || c->s.g[g_idx] < best) {
      const bt_status st = write_cells(c, v.res, sr, sc, gr, gc, cells, cap, &out->len, &out->length);
      if (st != BT_OK) return st;
      best = c->s.g[g_idx];
    }
    found = true;
    last_eps = static_cast<float>(e);
    if (e <= 1.0) break;
  }
  if (!found) return BT_ERR_UNREACHABLE;          // 예산 안에 첫 해를 못 냈다
  out->cost = best;
  out->eps_bound = last_eps;
  out->complete = (last_eps <= 1.0f) ? 1 : 0;
  return out->complete ? BT_OK : BT_PARTIAL;
}

void path_reset(bt_path* out, double res) {
  out->len = 0; out->res_m = res; out->length_m = 0.0; out->cost = 0.0;
  out->eps_bound = 0.0f; out->expansions = 0; out->complete = 0; out->snapped_m = 0.0;
}

// 거친 칸 하나가 덮는 고운 칸의 범위 (한 축)
inline void coarse_span(double ratio, int32_t k, int32_t* lo, int32_t* hi) {
  const int32_t a = static_cast<int32_t>(std::floor(static_cast<double>(k) * ratio));
  const int32_t b = static_cast<int32_t>(std::ceil(static_cast<double>(k + 1) * ratio)) - 1;
  if (a < *lo) *lo = a;
  if (b > *hi) *hi = b;
}

// 거친 경로를 구간으로 잘라 구간마다 고운 조각에서 다시 푼다. 실패하면 음수 (부른 쪽이 거친 경로로 돌아간다)
bt_status refine(bt_ctx* c, bt_xy start, bt_xy goal, bool clipped, const bt_cell* coarse, uint32_t n, int profile, double time_cap,
                 uint32_t max_exp, uint32_t* expansions, bt_path* out) {
  Tile& T = c->tile;
  const bt_grid_geom& bg = c->cfg.cost_grid;
  const uint32_t ff = T.factor;
  const double fres = static_cast<double>(bg.res_m) * ff;
  const Geom fg{bg.origin.x, bg.origin.y, fres, (bg.h + ff - 1) / ff, (bg.w + ff - 1) / ff};
  const Geom cg = cm_geom(c);
  const double ratio = cg.res / fres;
  const int32_t Kc = static_cast<int32_t>(std::ceil(static_cast<double>(c->cfg.corridor_m) / fres));
  const int32_t Ts = static_cast<int32_t>(T.side);

  int32_t cur_r, cur_c, fin_r, fin_c;
  if (!xy_to_cell(fg, start, &cur_r, &cur_c)) return BT_ERR_UNREACHABLE;
  const bt_xy last_xy = clipped ? cell_center(cg, coarse[n - 1].row, coarse[n - 1].col) : goal;
  if (!xy_to_cell(fg, last_xy, &fin_r, &fin_c)) return BT_ERR_UNREACHABLE;

  const float one = 1.0f;                           // 회랑 안에서는 한 번에 최적으로 푼다
  uint32_t a = 0, len = 0;
  double cost = 0.0, length = 0.0, snapped = 0.0;
  uint8_t complete = 1;
  for (uint32_t guard = 0; guard <= n; ++guard) {   // 상한: 거친 경로의 칸 수
    int32_t lo_r = cur_r, hi_r = cur_r, lo_c = cur_c, hi_c = cur_c;
    coarse_span(ratio, coarse[a].row, &lo_r, &hi_r);
    coarse_span(ratio, coarse[a].col, &lo_c, &hi_c);
    uint32_t b = a;
    while (b + 1 < n) {                             // 조각에 들어가는 만큼 구간을 늘린다
      int32_t r0 = lo_r, r1 = hi_r, c0 = lo_c, c1 = hi_c;
      coarse_span(ratio, coarse[b + 1].row, &r0, &r1);
      coarse_span(ratio, coarse[b + 1].col, &c0, &c1);
      if (r1 - r0 + 1 + 2 * Kc > Ts || c1 - c0 + 1 + 2 * Kc > Ts) break;
      lo_r = r0; hi_r = r1; lo_c = c0; hi_c = c1;
      b += 1;
    }
    const bool last = (b + 1 >= n);
    if (!last && b == a) return BT_ERR_UNREACHABLE; // 조각이 구간 하나도 못 담는다
    if (last) {
      if (fin_r < lo_r) lo_r = fin_r;
      if (fin_r > hi_r) hi_r = fin_r;
      if (fin_c < lo_c) lo_c = fin_c;
      if (fin_c > hi_c) hi_c = fin_c;
    }
    int32_t tr0 = lo_r - Kc, tr1 = hi_r + Kc, tc0 = lo_c - Kc, tc1 = hi_c + Kc;
    if (tr0 < 0) tr0 = 0;
    if (tc0 < 0) tc0 = 0;
    if (tr1 >= static_cast<int32_t>(fg.h)) tr1 = static_cast<int32_t>(fg.h) - 1;
    if (tc1 >= static_cast<int32_t>(fg.w)) tc1 = static_cast<int32_t>(fg.w) - 1;
    const uint32_t th = static_cast<uint32_t>(tr1 - tr0 + 1), tw = static_cast<uint32_t>(tc1 - tc0 + 1);
    if (tr1 < tr0 || tc1 < tc0 || static_cast<uint64_t>(th) * tw > T.cap) return BT_ERR_UNREACHABLE;
    fill_rect(c, ff, tr0, tc0, th, tw, T.base, T.elev, nullptr, T.passable, T.min_base);
    const MapView tv = tile_view(c, tr0, tc0, th, tw, fres);
    set_window(c, tr0, tc0, th, tw);

    int32_t sr = cur_r, sc = cur_c, gr = fin_r, gc = fin_c;
    if (!last) {
      const bt_xy mid = cell_center(cg, coarse[b].row, coarse[b].col);
      if (!xy_to_cell(fg, mid, &gr, &gc)) return BT_ERR_UNREACHABLE;
    }
    double snap_s = 0.0, snap_g = 0.0;
    if (!snap(c, tv, &sr, &sc, &snap_s) || !snap(c, tv, &gr, &gc, &snap_g)) return BT_ERR_UNREACHABLE;
    if (len > 0 && (sr != cur_r || sc != cur_c)) return BT_ERR_UNREACHABLE;   // 이음매가 끊긴다
    if (len == 0) snapped = snap_s;
    if (last && snap_g > snapped) snapped = snap_g;

    const uint32_t at = len ? len - 1 : 0;          // 앞 구간의 끝 칸에서 이어 쓴다
    if (at >= out->cap) return BT_ERR_CAPACITY;
    Sol sol;
    const bt_status st = solve(c, tv, sr, sc, gr, gc, profile, time_cap, &one, 1, max_exp, expansions, out->cells + at, out->cap - at, &sol);
    if (st < 0) return st;
    len = at + sol.len;
    cost += sol.cost;
    length += sol.length;
    if (!sol.complete) complete = 0;
    cur_r = gr; cur_c = gc;
    if (last) break;
    a = b;
  }
  out->len = len; out->res_m = fres; out->length_m = length; out->cost = cost;
  out->eps_bound = 1.0f; out->complete = complete; out->snapped_m = snapped;
  return complete ? BT_OK : BT_PARTIAL;
}

}  // namespace

namespace bt {

bt_status plan_ex(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out, bool allow_refine) {
  if (!c || !b || !out || !out->cells || out->cap == 0) return BT_ERR_ARG;
  if (b->profile >= BT_MAX_PROFILES || b->eps_n > BT_MAX_EPS) return BT_ERR_ARG;
  if (!c->cm.built || !c->s.g) return BT_ERR_NOT_READY;
  const MapView v = cm_view(c);
  path_reset(out, v.res);
  const Geom g = cm_geom(c);
  int32_t sr, sc, gr, gc;
  if (!xy_to_cell(g, start, &sr, &sc) || !xy_to_cell(g, goal, &gr, &gc)) return BT_ERR_UNREACHABLE;   // 지도 밖
  center_window(c, v, sr, sc);
  double snap_s = 0.0, snap_g = 0.0;
  if (!snap(c, v, &sr, &sc, &snap_s)) return BT_ERR_UNREACHABLE;
  bool clipped = false;
  if (!in_win(c->s, gr, gc)) {                    // 재계획 반경 밖의 목표: 창 안에서 가장 가까운 칸까지만 푼다
    if (!clip_to_window(c, v, gr, gc, &gr, &gc)) return BT_ERR_UNREACHABLE;
    clipped = true;
  } else if (!snap(c, v, &gr, &gc, &snap_g)) {
    return BT_ERR_UNREACHABLE;
  }

  const uint32_t max_exp = b->max_expansions ? b->max_expansions : c->cfg.max_expansions;
  uint32_t eps_n = b->eps_n;
  const float* eps = b->eps;
  if (eps_n == 0) { eps_n = c->cfg.eps_n; eps = c->cfg.eps; }
  const float one = 1.0f;
  if (eps_n == 0) { eps_n = 1; eps = &one; }

  const bool c2f = allow_refine && c->tile.cap > 0 && c->cm.res > static_cast<double>(c->cfg.cost_grid.res_m) * c->tile.factor + 1e-9;
  bt_cell* cells = c2f ? c->tile.coarse : out->cells;
  const uint32_t cap = c2f ? c->tile.coarse_cap : out->cap;
  uint32_t expansions = 0;
  Sol sol;
  const bt_status st = solve(c, v, sr, sc, gr, gc, b->profile, b->time_s, eps, eps_n, max_exp, &expansions, cells, cap, &sol);
  out->expansions = expansions;
  if (st < 0) return st;

  if (c2f) {
    const bt_status rs = refine(c, start, goal, clipped, c->tile.coarse, sol.len, b->profile, b->time_s, max_exp, &expansions, out);
    out->expansions = expansions;
    if (rs == BT_ERR_CAPACITY) return rs;
    if (rs >= 0) {
      if (!sol.complete || clipped) out->complete = 0;
      return out->complete ? BT_OK : BT_PARTIAL;
    }
    // 고운 격자에서 못 이었다(예산 소진, 회랑이 끊김) → 거친 경로를 그대로 낸다
    if (sol.len > out->cap) return BT_ERR_CAPACITY;
    std::memcpy(out->cells, c->tile.coarse, static_cast<uint64_t>(sol.len) * sizeof(bt_cell));
    out->res_m = v.res;
  }
  out->len = sol.len; out->length_m = sol.length; out->cost = sol.cost;
  out->eps_bound = sol.eps_bound;
  out->snapped_m = snap_s > snap_g ? snap_s : snap_g;
  out->complete = (sol.complete && !clipped) ? 1 : 0;
  return out->complete ? BT_OK : BT_PARTIAL;
}

bt_status alternatives_ex(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out, uint32_t cap, uint32_t* n, bool allow_refine) {
  if (!c || !b || !out || !n) return BT_ERR_ARG;
  *n = 0;
  if (!c->cm.built || !c->s.g) return BT_ERR_NOT_READY;
  const Geom g = cm_geom(c);
  const MapView v = cm_view(c);
  for (int p = 0; p < BT_MAX_PROFILES && *n < cap; ++p) {
    bt_budget bb = *b;
    bb.profile = static_cast<uint8_t>(p);
    bt_path* cand = &out[*n];
    const bt_status st = plan_ex(c, start, goal, &bb, cand, allow_refine);
    if (st == BT_ERR_ARG || st == BT_ERR_NOT_READY || st == BT_ERR_CAPACITY) return st;
    if (st < 0) continue;
    // 이미 고른 경로와 많이 겹치면 같은 경로로 본다. 겹침은 전역 격자의 칸으로 센다
    int32_t r0, c0;
    if (xy_to_cell(g, start, &r0, &c0)) center_window(c, v, r0, c0);
    bool dup = false;
    for (uint32_t j = 0; j < *n && !dup; ++j) {
      next_stamp(c);
      for (uint32_t k = 0; k < out[j].len; ++k) {
        const Geom pg{g.ox, g.oy, out[j].res_m, 0, 0};
        int32_t r, col;
        if (xy_to_cell(g, cell_center(pg, out[j].cells[k].row, out[j].cells[k].col), &r, &col) && in_win(c->s, r, col)) c->s.stamp[wi(c->s, r, col)] = c->s.cur;
      }
      uint32_t shared = 0;
      for (uint32_t k = 0; k < cand->len; ++k) {
        const Geom pg{g.ox, g.oy, cand->res_m, 0, 0};
        int32_t r, col;
        if (xy_to_cell(g, cell_center(pg, cand->cells[k].row, cand->cells[k].col), &r, &col) && in_win(c->s, r, col) &&
            c->s.stamp[wi(c->s, r, col)] == c->s.cur) shared += 1;
      }
      if (cand->len > 0 && static_cast<double>(shared) / cand->len > static_cast<double>(c->cfg.alt_overlap_max)) dup = true;
    }
    next_stamp(c);   // 표시로 쓴 도장을 다음 탐색이 읽지 않게 한다
    if (!dup) *n += 1;
  }
  return *n > 0 ? BT_OK : BT_ERR_UNREACHABLE;
}

// 칸 열의 비용·길이를 다시 센다. 이어지지 않거나 통과불가 칸이 있으면 false
bool cells_cost(const bt_ctx* c, const bt_cell* cells, uint32_t len, int profile, double* cost, double* length) {
  const CostMap& m = c->cm;
  const float* base = m.base[profile];
  const double w_s = static_cast<double>(c->cfg.profiles[profile].w_s);
  *cost = 0.0; *length = 0.0;
  for (uint32_t k = 0; k < len; ++k) {
    const bt_cell a = cells[k];
    if (a.row < 0 || a.col < 0 || a.row >= static_cast<int32_t>(m.h) || a.col >= static_cast<int32_t>(m.w)) return false;
    const uint32_t i = static_cast<uint32_t>(a.row) * m.w + static_cast<uint32_t>(a.col);
    if (!m.passable[i]) return false;
    if (k == 0) continue;
    const bt_cell p = cells[k - 1];
    const int32_t dr = a.row - p.row, dc = a.col - p.col;
    if (dr < -1 || dr > 1 || dc < -1 || dc > 1 || (dr == 0 && dc == 0)) return false;
    if (dr != 0 && dc != 0) {
      if (!m.passable[static_cast<uint32_t>(a.row) * m.w + static_cast<uint32_t>(p.col)]) return false;
      if (!m.passable[static_cast<uint32_t>(p.row) * m.w + static_cast<uint32_t>(a.col)]) return false;
    }
    const uint32_t j = static_cast<uint32_t>(p.row) * m.w + static_cast<uint32_t>(p.col);
    const double dist = ((dr != 0 && dc != 0) ? SQRT2 : 1.0) * m.res;
    const double f = slope_factor(step_slope(m.elev[j], m.elev[i], dist));
    *cost += dist * (w_s / f + (static_cast<double>(base[j]) + static_cast<double>(base[i])) * 0.5);
    *length += dist;
  }
  return true;
}

// 경로 칸 하나의 고도·경사·가시선·중심 좌표. 경로가 코스트맵 격자 위면 그 값을, 아니면 레이어에서 읽는다
bool cell_info(const bt_ctx* c, double res_m, bt_cell a, float* elev, float* slope, uint8_t* los, bt_xy* xy) {
  const CostMap& m = c->cm;
  const bt_grid_geom& bg = c->cfg.cost_grid;
  const Geom pg{bg.origin.x, bg.origin.y, res_m,
                static_cast<uint32_t>(std::ceil(bg.h * static_cast<double>(bg.res_m) / res_m)),
                static_cast<uint32_t>(std::ceil(bg.w * static_cast<double>(bg.res_m) / res_m))};
  if (a.row < 0 || a.col < 0 || a.row >= static_cast<int32_t>(pg.h) || a.col >= static_cast<int32_t>(pg.w)) return false;
  const bt_xy p = cell_center(pg, a.row, a.col);
  const Geom base = geom_of(bg);
  int32_t br = 0, bc = 0;
  const bool in_base = xy_to_cell(base, p, &br, &bc);
  const uint64_t bi = static_cast<uint64_t>(br) * bg.w + static_cast<uint64_t>(bc);
  if (m.built && std::fabs(res_m - m.res) < 1e-9) {
    const uint32_t i = static_cast<uint32_t>(a.row) * m.w + static_cast<uint32_t>(a.col);
    *elev = m.elev[i]; *slope = m.slope[i];
  } else {
    if (!in_base) return false;
    *elev = c->layer_set[BT_LAYER_ELEV] ? raster_f(c->layer[BT_LAYER_ELEV], bi) : 0.0f;
    *slope = raster_f(c->layer[BT_LAYER_SLOPE], bi);
  }
  *los = (c->layer_set[BT_LAYER_LOS] && in_base) ? raster_bit(c->layer[BT_LAYER_LOS], 0, bi) : 1;
  *xy = p;
  return true;
}

double step_seconds(const bt_ctx* c, float e_from, float e_to, double dist_m, int mode) {
  const double v0 = static_cast<double>(mode == BT_WALK_RETURN ? c->cfg.v_return_kmh : c->cfg.v_plan_kmh) / 3.6;
  return dist_m / (v0 * slope_factor(step_slope(e_from, e_to, dist_m)));
}
}  // namespace bt

bt_status bt_plan(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out) {
  return plan_ex(c, start, goal, b, out, true);
}

bt_status bt_alternatives(bt_ctx* c, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out, uint32_t cap, uint32_t* n) {
  return alternatives_ex(c, start, goal, b, out, cap, n, true);
}

bt_status bt_replan(bt_ctx* c, const bt_path* prev, bt_xy start, bt_xy goal, const bt_budget* b, bt_path* out) {
  const bt_status st = bt_plan(c, start, goal, b, out);
  if (st == BT_ERR_ARG || st == BT_ERR_NOT_READY) return st;
  if (!prev || !prev->cells || prev->len < 2 || prev->cells == out->cells) return st;
  const CostMap& m = c->cm;
  // 접미부 재사용은 이전 경로와 새 경로가 둘 다 전역 격자 위에 있을 때만 (비용을 같은 자로 잴 수 있을 때)
  if (std::fabs(prev->res_m - m.res) > 1e-9 || (st >= 0 && std::fabs(out->res_m - m.res) > 1e-9)) return st;
  const Geom g = cm_geom(c);
  int32_t gr, gc;
  if (!xy_to_cell(g, goal, &gr, &gc)) return st;
  const bt_cell last = prev->cells[prev->len - 1];
  const bool same_goal = (last.row == gr && last.col == gc) ||
                         (st >= 0 && out->len > 0 && out->cells[out->len - 1].row == last.row && out->cells[out->len - 1].col == last.col);
  if (!same_goal) return st;
  // 이전 경로에서 지금 위치와 가장 가까운 칸부터의 접미부
  double best = D_INF;
  uint32_t at = 0;
  for (uint32_t k = 0; k < prev->len; ++k) {
    const bt_xy p = cell_center(g, prev->cells[k].row, prev->cells[k].col);
    const double d = std::sqrt((p.x - start.x) * (p.x - start.x) + (p.y - start.y) * (p.y - start.y));
    if (d < best) { best = d; at = k; }
  }
  if (best > static_cast<double>(c->cfg.snap_max_m)) return st;
  const uint32_t len = prev->len - at;
  double cost, length;
  if (!cells_cost(c, prev->cells + at, len, b->profile, &cost, &length)) return st;
  if (st >= 0 && !(cost < out->cost)) return st;   // 새로 푼 것이 더 싸거나 같다
  if (len > out->cap) return st;
  std::memcpy(out->cells, prev->cells + at, static_cast<uint64_t>(len) * sizeof(bt_cell));
  out->len = len; out->res_m = m.res; out->length_m = length; out->cost = cost;
  out->eps_bound = prev->eps_bound; out->complete = prev->complete; out->snapped_m = best;
  return out->complete ? BT_OK : BT_PARTIAL;
}

// 귀환 필드: 창(목표를 가운데 둔 재계획 반경) 안의 전체장 Dijkstra. 간선 비용이 방향마다 달라 목표에서 역방향 간선으로 푼다.
// 창 밖의 칸은 도달 불가(+inf)로 남는다
bt_status bt_cost_to_go(bt_ctx* c, bt_xy target, bt_walk_mode mode, bt_field_id id) {
  if (!c || id != BT_FIELD_ROVER_RETURN) return BT_ERR_ARG;
  if (!c->cm.built || !c->s.g) return BT_ERR_NOT_READY;
  const CostMap& m = c->cm;
  const MapView v = cm_view(c);
  Search& s = c->s;
  const Geom g = cm_geom(c);
  int32_t tr, tc;
  if (!xy_to_cell(g, target, &tr, &tc)) return BT_ERR_UNREACHABLE;
  center_window(c, v, tr, tc);
  double snapped;
  if (!snap(c, v, &tr, &tc, &snapped)) return BT_ERR_UNREACHABLE;
  const uint64_t cells = static_cast<uint64_t>(m.h) * m.w;
  const double v0 = static_cast<double>(mode == BT_WALK_RETURN ? c->cfg.v_return_kmh : c->cfg.v_plan_kmh) / 3.6;
  for (uint64_t k = 0; k < cells; ++k) { c->field.time[k] = F_INF; c->field.next[k] = BT_DIR_NONE; }

  next_stamp(c);
  const uint32_t t_idx = wi(s, tr, tc);
  touch(s, t_idx);
  s.g[t_idx] = 0.0;
  s.flag[t_idx] = static_cast<uint8_t>(FL_NODIR | FL_OPEN);
  s.heap.push(HeapEntry{0.0, 0.0f, t_idx}, false);
  const uint64_t win_cells = static_cast<uint64_t>(s.wh) * s.ww;
  uint64_t pops = 0;
  while (s.heap.n > 0 && pops < win_cells) {        // 상한: 창의 칸마다 한 번
    const HeapEntry top = s.heap.pop();
    const uint32_t n = top.idx;
    pops += 1;
    s.flag[n] = static_cast<uint8_t>((s.flag[n] & FL_DIR) | FL_CLOSED);
    const int32_t nr = s.wr0 + static_cast<int32_t>(n / s.ww), nc = s.wc0 + static_cast<int32_t>(n % s.ww);
    const uint32_t mn = static_cast<uint32_t>(nr) * m.w + static_cast<uint32_t>(nc);
    c->field.time[mn] = static_cast<float>(s.g[n]);
    const int d_n = s.flag[n] & FL_DIR;
    c->field.next[mn] = d_n < 8 ? static_cast<uint8_t>(d_n) : static_cast<uint8_t>(BT_DIR_NONE);
    for (int d = 0; d < 8; ++d) {                   // i → n 이 방향 d인 앞 칸 i
      const int32_t ir = nr - DR[d], ic = nc - DC[d];
      if (!in_win(s, ir, ic) || !v_pass(v, ir, ic)) continue;
      int32_t xr, xc;
      if (!can_step(v, ir, ic, d, &xr, &xc)) continue;
      const uint32_t i = wi(s, ir, ic);
      touch(s, i);
      if (s.flag[i] & FL_CLOSED) continue;
      const uint32_t mi = static_cast<uint32_t>(ir) * m.w + static_cast<uint32_t>(ic);
      const double dist = ((d & 1) ? SQRT2 : 1.0) * m.res;
      const double sec = dist / (v0 * slope_factor(step_slope(m.elev[mi], m.elev[mn], dist)));
      const double g2 = s.g[n] + sec;
      if (!(g2 < s.g[i])) continue;
      const bool in_heap = (s.flag[i] & FL_OPEN) != 0;
      if (!s.heap.push(HeapEntry{g2, 0.0f, i}, in_heap)) return BT_ERR_CAPACITY;
      s.g[i] = g2;
      s.flag[i] = static_cast<uint8_t>(d | FL_OPEN);
    }
  }
  c->field.src = 1;
  c->field.geom = g;
  return BT_OK;
}

namespace {

// 그 좌표가 걸을 수 있는 곳인가. 경로가 전역 코스트맵의 격자 위면 그것을 보고, 아니면(고운 격자 경로) 레이어와 막힘 표시를 직접 본다
bool walkable_at(const bt_ctx* c, double res_m, bt_xy p) {
  const CostMap& m = c->cm;
  if (m.built && std::fabs(res_m - m.res) < 1e-9) {
    int32_t r, col;
    if (!xy_to_cell(cm_geom(c), p, &r, &col)) return false;
    return m.passable[static_cast<uint32_t>(r) * m.w + static_cast<uint32_t>(col)] != 0;
  }
  const bt_grid_geom& bg = c->cfg.cost_grid;
  int32_t r, col;
  if (!xy_to_cell(geom_of(bg), p, &r, &col)) return false;
  const uint64_t i = static_cast<uint64_t>(r) * bg.w + static_cast<uint64_t>(col);
  const float s = raster_f(c->layer[BT_LAYER_SLOPE], i);
  if (!(s == s) || s > c->cfg.theta_max_deg) return false;
  if (c->layer_set[BT_LAYER_ELEV]) { const float e = raster_f(c->layer[BT_LAYER_ELEV], i); if (!(e == e)) return false; }
  for (uint32_t e = 0; e < c->log_n; ++e) {                      // 막힘 표시
    const bt_event& ev = c->log[e];
    if (ev.type != BT_EV_MARK || ev.kind != BT_MARK_BLOCKED) continue;
    const double dx = p.x - ev.x, dy = p.y - ev.y;
    if (dx * dx + dy * dy <= static_cast<double>(ev.a) * static_cast<double>(ev.a)) return false;
  }
  return true;
}

// a에서 b까지 직선으로 걸어도 되는가. 선 위와 양옆(칸의 0.3배)을 반 칸 간격으로 짚어 본다 — 모서리를 스치는 것을 막는다
bool straight_ok(const bt_ctx* c, double res_m, bt_xy a, bt_xy b) {
  const double dx = b.x - a.x, dy = b.y - a.y, len = std::sqrt(dx * dx + dy * dy);
  if (len < 1e-9) return true;
  const double nx = -dy / len * 0.3 * res_m, ny = dx / len * 0.3 * res_m;
  const uint32_t steps = static_cast<uint32_t>(len / (0.5 * res_m)) + 1;
  for (uint32_t k = 0; k <= steps; ++k) {
    const double t = static_cast<double>(k) / steps;
    const bt_xy p{a.x + dx * t, a.y + dy * t};
    if (!walkable_at(c, res_m, p) || !walkable_at(c, res_m, bt_xy{p.x + nx, p.y + ny}) || !walkable_at(c, res_m, bt_xy{p.x - nx, p.y - ny})) return false;
  }
  return true;
}

// 좌표의 고도: 바탕 고도 레이어의 칸 중심 네 개 사이를 두 방향으로 보간한다. 값이 없는 칸이 끼면 가장 가까운 칸의 값
bool elev_at(const bt_ctx* c, bt_xy p, double* out) {
  if (!c->layer_set[BT_LAYER_ELEV]) { *out = 0.0; return true; }
  const bt_grid_geom& bg = c->cfg.cost_grid;
  const double res = static_cast<double>(bg.res_m);
  const double fc = (p.x - bg.origin.x) / res - 0.5, fr = (bg.origin.y - p.y) / res - 0.5;
  int32_t c0 = static_cast<int32_t>(std::floor(fc)), r0 = static_cast<int32_t>(std::floor(fr));
  const int32_t wmax = static_cast<int32_t>(bg.w) - 1, hmax = static_cast<int32_t>(bg.h) - 1;
  if (c0 < 0) c0 = 0;
  if (r0 < 0) r0 = 0;
  if (c0 > wmax - 1) c0 = wmax > 0 ? wmax - 1 : 0;
  if (r0 > hmax - 1) r0 = hmax > 0 ? hmax - 1 : 0;
  const int32_t c1 = c0 < wmax ? c0 + 1 : c0, r1 = r0 < hmax ? r0 + 1 : r0;
  double a = fc - c0, b = fr - r0;
  if (a < 0) a = 0;
  if (a > 1) a = 1;
  if (b < 0) b = 0;
  if (b > 1) b = 1;
  const bt_raster& E = c->layer[BT_LAYER_ELEV];
  const float e00 = raster_f(E, static_cast<uint64_t>(r0) * bg.w + static_cast<uint64_t>(c0));
  const float e01 = raster_f(E, static_cast<uint64_t>(r0) * bg.w + static_cast<uint64_t>(c1));
  const float e10 = raster_f(E, static_cast<uint64_t>(r1) * bg.w + static_cast<uint64_t>(c0));
  const float e11 = raster_f(E, static_cast<uint64_t>(r1) * bg.w + static_cast<uint64_t>(c1));
  if (e00 == e00 && e01 == e01 && e10 == e10 && e11 == e11) {
    *out = (static_cast<double>(e00) * (1 - a) + static_cast<double>(e01) * a) * (1 - b) +
           (static_cast<double>(e10) * (1 - a) + static_cast<double>(e11) * a) * b;
    return true;
  }
  const float en = (a < 0.5 ? (b < 0.5 ? e00 : e10) : (b < 0.5 ? e01 : e11));
  if (!(en == en)) return false;
  *out = static_cast<double>(en);
  return true;
}

inline bool los_at(const bt_ctx* c, bt_xy p) {
  if (!c->layer_set[BT_LAYER_LOS]) return true;
  int32_t r, col;
  if (!xy_to_cell(geom_of(c->cfg.cost_grid), p, &r, &col)) return true;
  return raster_bit(c->layer[BT_LAYER_LOS], 0, static_cast<uint64_t>(r) * c->cfg.cost_grid.w + static_cast<uint64_t>(col)) != 0;
}

}  // namespace

namespace bt {

// anchor 칸에서 직선으로 닿는 가장 먼 칸의 번호(limit 이하). 바로 다음 칸은 언제나 닿는다(경로의 일부).
// 화면에 그리는 선(bt_path_polyline)과 시간을 재는 선(straight_measure)이 이 함수 하나를 같이 쓴다 — 그린 길과 잰 길이 같다
uint32_t straight_reach(const bt_ctx* c, const bt_cell* cells, uint32_t len, double res_m, uint32_t anchor, uint32_t limit) {
  constexpr uint32_t LOOK = 512;                                 // 한 번에 건너뛰어 보는 칸 수의 상한
  const Geom pg{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, res_m, 0, 0};
  const bt_xy a = cell_center(pg, cells[anchor].row, cells[anchor].col);
  uint32_t stop = anchor + LOOK < len - 1 ? anchor + LOOK : len - 1;
  if (stop > limit) stop = limit;
  uint32_t reach = anchor + 1;
  for (uint32_t j = anchor + 2; j <= stop; ++j) {
    if (!straight_ok(c, res_m, a, cell_center(pg, cells[j].row, cells[j].col))) break;
    reach = j;
  }
  return reach;
}

// a에서 b까지 직선으로 걷는 시간(초). 한 칸 길이쯤마다 고도를 읽어 그 구간의 경사로 속도를 낸다
double straight_seconds(const bt_ctx* c, bt_xy a, bt_xy b, double res_m, int mode, double* length, double* lost) {
  const double dx = b.x - a.x, dy = b.y - a.y, len = std::sqrt(dx * dx + dy * dy);
  if (len < 1e-9) return 0.0;
  const uint32_t n = static_cast<uint32_t>(std::ceil(len / res_m));
  const double ds = len / n;
  double sec = 0.0, e_prev = 0.0;
  bool have_prev = elev_at(c, a, &e_prev);
  for (uint32_t k = 1; k <= n; ++k) {                            // 상한: 구간 길이 / 칸 크기
    const double t = static_cast<double>(k) / n;
    const bt_xy q{a.x + dx * t, a.y + dy * t};
    double e = 0.0;
    const bool have = elev_at(c, q, &e);
    const double step = (have && have_prev) ? step_seconds(c, static_cast<float>(e_prev), static_cast<float>(e), ds, mode)
                                            : step_seconds(c, 0.0f, 0.0f, ds, mode);   // 고도를 모르는 구간은 평지로 본다
    sec += step;
    if (lost && !los_at(c, q)) *lost += step;
    e_prev = e; have_prev = have;
  }
  if (length) *length += len;
  return sec;
}

bool straight_measure(const bt_ctx* c, const bt_cell* cells, uint32_t len, double res_m, int mode,
                      const uint32_t* pins, uint32_t n_pins, double* sec, double* length, double* lost) {
  *sec = 0.0; *length = 0.0; *lost = 0.0;
  if (!cells || len == 0 || !(res_m > 0)) return false;
  const Geom pg{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, res_m, 0, 0};
  uint32_t anchor = 0, pin = 0;
  while (anchor + 1 < len) {                                     // 상한: 경로의 칸 수
    while (pin < n_pins && pins[pin] <= anchor) pin += 1;        // 다음에 꼭 지나야 하는 칸
    const uint32_t limit = pin < n_pins ? pins[pin] : len - 1;
    const uint32_t reach = straight_reach(c, cells, len, res_m, anchor, limit);
    *sec += straight_seconds(c, cell_center(pg, cells[anchor].row, cells[anchor].col), cell_center(pg, cells[reach].row, cells[reach].col),
                             res_m, mode, length, lost);
    anchor = reach;
  }
  return true;
}

}  // namespace bt

bt_status bt_path_polyline(const bt_ctx* c, const bt_path* path, bt_xy* out, uint32_t cap, uint32_t* n) {
  if (!c || !path || !path->cells || !out || !n || path->len == 0 || !(path->res_m > 0)) return BT_ERR_ARG;
  if (!c->layer_set[BT_LAYER_SLOPE]) return BT_ERR_NOT_READY;
  const Geom pg{c->cfg.cost_grid.origin.x, c->cfg.cost_grid.origin.y, path->res_m, 0, 0};
  uint32_t count = 0, anchor = 0;
  *n = 0;
  if (cap == 0) return BT_ERR_CAPACITY;
  out[count++] = cell_center(pg, path->cells[0].row, path->cells[0].col);
  while (anchor + 1 < path->len) {                               // 상한: 경로의 칸 수
    const uint32_t reach = straight_reach(c, path->cells, path->len, path->res_m, anchor, path->len - 1);
    if (count >= cap) return BT_ERR_CAPACITY;
    out[count++] = cell_center(pg, path->cells[reach].row, path->cells[reach].col);
    anchor = reach;
  }
  *n = count;
  return BT_OK;
}

bt_status bt_set_field(bt_ctx* c, bt_field_id id, const bt_raster* time, const bt_raster* next) {
  if (!c || id != BT_FIELD_ROVER_RETURN || !time || !next || !time->data || !next->data) return BT_ERR_ARG;
  if (time->dtype != BT_DT_F32 || next->dtype != BT_DT_U8) return BT_ERR_ARG;
  if (time->h != next->h || time->w != next->w || time->h == 0 || time->w == 0 || !(time->res_m > 0)) return BT_ERR_ARG;
  c->field.ext_time = *time;
  c->field.ext_next = *next;
  c->field.geom = geom_of(*time);
  c->field.src = 2;
  return BT_OK;
}

bt_status bt_field_copy(const bt_ctx* c, bt_field_id id, bt_raster* out_time, bt_raster* out_next) {
  if (!c || id != BT_FIELD_ROVER_RETURN || !out_time || !out_next || !out_time->data || !out_next->data) return BT_ERR_ARG;
  FieldView v;
  if (!field_view(c, &v)) return BT_ERR_NOT_READY;
  if (out_time->h != v.geom.h || out_time->w != v.geom.w || out_next->h != v.geom.h || out_next->w != v.geom.w) return BT_ERR_CAPACITY;
  const uint64_t cells = static_cast<uint64_t>(v.geom.h) * v.geom.w;
  std::memcpy(const_cast<void*>(out_time->data), v.time, cells * sizeof(float));
  std::memcpy(const_cast<void*>(out_next->data), v.next, cells);
  bt_raster* outs[2] = {out_time, out_next};
  for (int k = 0; k < 2; ++k) {
    outs[k]->res_m = static_cast<float>(v.geom.res);
    outs[k]->planes = 1; outs[k]->scale = 1.0f; outs[k]->offset = 0.0f;
    outs[k]->origin.x = v.geom.ox; outs[k]->origin.y = v.geom.oy;
  }
  out_time->dtype = BT_DT_F32;
  out_next->dtype = BT_DT_U8;
  return BT_OK;
}

// 귀환 필드의 방향을 따라간다. 탐색 없음, O(경로 길이). out->cost는 걷는 시간(초)
bt_status bt_return_path(bt_ctx* c, bt_field_id id, bt_xy start, bt_path* out) {
  if (!c || id != BT_FIELD_ROVER_RETURN || !out || !out->cells || out->cap == 0) return BT_ERR_ARG;
  FieldView v;
  if (!field_view(c, &v)) return BT_ERR_NOT_READY;
  path_reset(out, v.geom.res);
  int32_t r, col;
  if (!xy_to_cell(v.geom, start, &r, &col)) return BT_ERR_UNREACHABLE;
  const float t0 = v.time[static_cast<uint64_t>(r) * v.geom.w + static_cast<uint64_t>(col)];
  if (!(t0 < F_INF)) return BT_ERR_UNREACHABLE;
  double length = 0.0;
  uint32_t len = 0;
  for (;;) {                                        // 상한: out->cap
    if (len >= out->cap) return BT_ERR_CAPACITY;
    out->cells[len].row = r; out->cells[len].col = col;
    len += 1;
    const uint8_t d = v.next[static_cast<uint64_t>(r) * v.geom.w + static_cast<uint64_t>(col)];
    if (d >= 8) break;
    r += DR[d]; col += DC[d];
    if (r < 0 || col < 0 || r >= static_cast<int32_t>(v.geom.h) || col >= static_cast<int32_t>(v.geom.w)) return BT_ERR_ARG;
    length += ((d & 1) ? SQRT2 : 1.0) * v.geom.res;
  }
  out->len = len; out->length_m = length; out->cost = static_cast<double>(t0);
  out->eps_bound = 1.0f; out->complete = 1;
  return BT_OK;
}

// 경로의 수치. 시간·길이·링크가 안 되는 시간은 "곧게 편 선"으로 잰다(화면에 그리는 선과 같은 선 — bt_path_polyline).
// 격자 경로는 8방향이라 계단 모양이고, 계단을 따라 재면 실제로 걷는 직선보다 최대 약 8 % 길게 나온다(REFERENCE §4.5).
// 최대 경사는 경로가 지나는 칸의 값 그대로다(곧게 펴도 같은 칸들 사이를 지난다).
bt_status bt_path_measure(bt_ctx* c, const bt_path* path, const bt_state* state, bt_walk_mode mode, bt_path_metrics* out) {
  (void)state;
  if (!c || !path || !out || !path->cells || path->len == 0 || !(path->res_m > 0)) return BT_ERR_ARG;
  if (!c->layer_set[BT_LAYER_SLOPE]) return BT_ERR_NOT_READY;
  float smax = 0.0f;
  for (uint32_t k = 0; k < path->len; ++k) {
    const bt_cell a = path->cells[k];
    float e, sl; uint8_t los; bt_xy p;
    if (!cell_info(c, path->res_m, a, &e, &sl, &los, &p)) return BT_ERR_ARG;
    if (sl == sl && sl > smax) smax = sl;
    if (k > 0) {
      const bt_cell q = path->cells[k - 1];
      const int32_t dr = a.row - q.row, dc = a.col - q.col;
      if (dr < -1 || dr > 1 || dc < -1 || dc > 1 || (dr == 0 && dc == 0)) return BT_ERR_ARG;
    }
  }
  double sec = 0.0, length = 0.0, lost = 0.0;
  straight_measure(c, path->cells, path->len, path->res_m, static_cast<int>(mode), nullptr, 0, &sec, &length, &lost);
  out->time_min = static_cast<float>(sec / 60.0);
  out->max_slope_deg = smax;
  out->dose_uSv = c->env_set ? static_cast<float>(c->env.dose_rate_uSv_h * sec / 3600.0) : 0.0f;
  out->comm_loss_min = static_cast<float>(lost / 60.0);
  out->length_m = static_cast<float>(length);
  return BT_OK;
}
